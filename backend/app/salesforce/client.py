"""Authenticated, read-only Salesforce REST client with automatic token refresh."""
import logging
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from .. import crypto
from ..config import Settings
from ..models import SalesforceConnectionRow
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

    def _send(self, path: str, extra: dict[str, str]) -> httpx.Response:
        """One GET, retrying brief Salesforce/network hiccups (rate limiting, 5xx, timeouts) with growing waits."""
        for attempt in range(RETRIES + 1):
            url = path if path.startswith("http") else f"{self.base}{path}"
            try:
                resp = self.http.get(url, headers={"Authorization": f"Bearer {self._access}", "Accept": "application/json", **extra})
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

    def query(self, soql: str) -> dict:
        """Run a read-only SOQL query (fixed server-side strings only)."""
        return self.get(f"/services/data/{self.settings.sf_api_version}/query?q={quote(soql)}")

    def limits(self) -> dict:
        return self.get(f"/services/data/{self.settings.sf_api_version}/limits")
