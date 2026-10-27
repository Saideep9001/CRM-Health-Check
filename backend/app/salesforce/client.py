"""Authenticated, read-only Salesforce client (REST, and Bulk API 2.0 for record queries) with automatic token refresh."""
import logging
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from .. import crypto
from ..config import Settings
from ..models import SalesforceConnectionRow
from . import bulk
from .app_config import AppCredentials
from .errors import SalesforceAuthExpired, SalesforceError
from .oauth import refresh_access_token


log = logging.getLogger("aquarient.salesforce")

# Brief problems worth retrying: rate limiting and Salesforce/server hiccups.
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRIES = 3
BACKOFF_SECONDS = 1.0


def _sf_message(resp: httpx.Response) -> str:
    """Salesforce errors look like [{"message": "...", "errorCode": "..."}]."""
    try:
        body = resp.json()
        if isinstance(body, list) and body and isinstance(body[0], dict):
            return body[0].get("message") or body[0].get("errorCode") or f"HTTP {resp.status_code}"
        if isinstance(body, dict):
            return body.get("message") or body.get("error_description") or f"HTTP {resp.status_code}"
    except ValueError:
        pass
    return f"HTTP {resp.status_code}"


class SalesforceClient:
    def __init__(
        self,
        http: httpx.Client,
        conn: SalesforceConnectionRow,
        settings: Settings,
        creds: AppCredentials | None,
        on_tokens_changed: Callable[[], None],
    ):
        self.http = http
        self.conn = conn
        self.settings = settings
        self.creds = creds  # Connected App keys; needed only to refresh the access token
        self._sleep = time.sleep  # swapped out in tests
        self._save = on_tokens_changed
        self._access = crypto.decrypt(conn.access_token_enc)

    @property
    def base(self) -> str:
        return self.conn.instance_url.rstrip("/")

    def _refresh(self) -> None:
        refresh = crypto.decrypt(self.conn.refresh_token_enc)
        if not refresh or self.creds is None:
            raise SalesforceAuthExpired("Your Salesforce session has expired. Please reconnect.")
        access, instance, rotated = refresh_access_token(
            self.http,
            login_host=self.conn.login_host,
            client_id=self.creds.client_id,
            client_secret=self.creds.client_secret,
            refresh_token=refresh,
        )
        self._access = access
        self.conn.access_token_enc = crypto.encrypt(access)
        if rotated and rotated != refresh:
            self.conn.refresh_token_enc = crypto.encrypt(rotated)  # the old one no longer works
        if instance:
            self.conn.instance_url = instance
        self._save()

    def _send(self, path: str, extra: dict[str, str], method: str = "GET", json: dict | None = None,
              params: dict | None = None) -> httpx.Response:
        """One request, retrying brief Salesforce/network hiccups (rate limiting, 5xx, timeouts) with growing waits."""
        for attempt in range(RETRIES + 1):
            url = path if path.startswith("http") else f"{self.base}{path}"
            try:
                resp = self.http.request(method, url, json=json, params=params,
                                         headers={"Authorization": f"Bearer {self._access}", "Accept": "application/json", **extra})
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == RETRIES:
                    raise
            else:
                if resp.status_code not in RETRY_STATUSES or attempt == RETRIES:
                    return resp
                log.info("Salesforce returned %s; retrying (%d/%d)", resp.status_code, attempt + 1, RETRIES)
            self._sleep(BACKOFF_SECONDS * (2 ** attempt))
        raise AssertionError("unreachable")

    def get(self, path: str, headers: dict[str, str] | None = None) -> dict:
        """GET a REST path (e.g. /services/data/v61.0/limits), refreshing the token once on 401."""
        extra = headers or {}
        resp = self._send(path, extra)
        if resp.status_code == 401:
            self._refresh()
            resp = self._send(path, extra)
            if resp.status_code == 401:
                raise SalesforceAuthExpired("Your Salesforce session has expired. Please reconnect.", 401)
        if resp.status_code >= 400:
            raise SalesforceError(_sf_message(resp), resp.status_code)
        return resp.json()

    def request(self, method: str, path: str, json: dict | None = None, params: dict | None = None,
                accept: str = "application/json", ok_errors: bool = False) -> httpx.Response:
        """Any request (Bulk API jobs need POST, PATCH and DELETE), refreshing the token once on 401.
        Only Bulk query jobs are created, read and removed: no record is ever changed."""
        extra = {"Accept": accept}
        resp = self._send(path, extra, method, json, params)
        if resp.status_code == 401:
            self._refresh()
            resp = self._send(path, extra, method, json, params)
            if resp.status_code == 401:
                raise SalesforceAuthExpired("Your Salesforce session has expired. Please reconnect.", 401)
        if resp.status_code >= 400 and not ok_errors:
            raise SalesforceError(_sf_message(resp), resp.status_code)
        return resp

    def _bulk(self, soql: str) -> bool:
        return self.settings.sf_query_api == "bulk" and bulk.eligible(soql)

    def _rest(self, soql: str, page_size: int | None = None) -> dict:
        headers = {"Sforce-Query-Options": f"batchSize={page_size}"} if page_size else None
        return self.get(f"/services/data/{self.settings.sf_api_version}/query?q={quote(soql)}", headers=headers)

    def query(self, soql: str, max_rows: int | None = None) -> dict:
        """Run a read-only SOQL query (fixed server-side strings only).

        With Bulk API on, a record query runs as a Bulk job and comes back whole (or its first `max_rows`), done=True.
        Counts and GROUP BY (no Bulk version) and anything Salesforce won't run as a Bulk job use REST, which pages
        (nextRecordsUrl) as before."""
        if self._bulk(soql):
            try:
                return bulk.query(self, soql, max_rows)
            except bulk.Unsupported as exc:
                log.info("Bulk API can't run this query (%s); using REST", exc)
        return self._rest(soql)

    def query_page(self, soql: str, page_size: int) -> dict:
        """The first page of a query for a record table; `nextRecordsUrl` is the cursor for `query_more`."""
        if self._bulk(soql):
            try:
                return bulk.first_page(self, soql, page_size)
            except bulk.Unsupported as exc:
                log.info("Bulk API can't run this query (%s); using REST", exc)
        return self._rest(soql, page_size)

    def query_more(self, cursor: str, page_size: int) -> dict:
        if bulk.CURSOR_RE.match(cursor):
            return bulk.next_page(self, cursor, page_size)
        return self.get(cursor, headers={"Sforce-Query-Options": f"batchSize={page_size}"})

    def limits(self) -> dict:
        return self.get(f"/services/data/{self.settings.sf_api_version}/limits")
