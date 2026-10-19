"""Salesforce OAuth 2.0 web-server flow with PKCE.

Docs: https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_web_server_flow.htm
"""
import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .errors import SalesforceAuthExpired, SalesforceError

_MY_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.(my\.salesforce\.com|my\.salesforce-sites\.com|lightning\.force\.com)$", re.I)


def login_host_for(environment: str, my_domain: str | None) -> str:
    if environment == "production":
        return "login.salesforce.com"
    if environment == "sandbox":
        return "test.salesforce.com"
    if environment == "custom":
        domain = (my_domain or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        if not _MY_DOMAIN.match(domain):
            raise ValueError("Enter a valid My Domain, for example acme.my.salesforce.com.")
        return domain
    raise ValueError("Unknown environment.")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_pkce() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) using S256."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def authorize_url(*, login_host: str, client_id: str, redirect_uri: str, scopes: str, state: str, code_challenge: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "login consent",
        }
    )
    return f"https://{login_host}/services/oauth2/authorize?{query}"


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    instance_url: str
    identity_url: str | None


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return body.get("error_description") or body.get("error") or f"HTTP {resp.status_code}"
    except ValueError:
        return f"HTTP {resp.status_code}"


def exchange_code(http: httpx.Client, *, login_host: str, client_id: str, client_secret: str, code: str, code_verifier: str, redirect_uri: str) -> TokenSet:
    resp = http.post(
        f"https://{login_host}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    if resp.status_code != 200:
        raise SalesforceError(f"Salesforce rejected the sign-in: {_error_text(resp)}", resp.status_code)
    body = resp.json()
    return TokenSet(body["access_token"], body.get("refresh_token"), body["instance_url"], body.get("id"))


def refresh_access_token(http: httpx.Client, *, login_host: str, client_id: str, client_secret: str, refresh_token: str) -> tuple[str, str | None, str | None]:
    """Returns (access_token, instance_url, new_refresh_token).

    With "refresh token rotation" on the Connected App, Salesforce returns a new refresh token and retires the old
    one, so it must be saved or the next refresh fails with "expired access/refresh token".
    """
    resp = http.post(
        f"https://{login_host}/services/oauth2/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret},
    )
    if resp.status_code != 200:
        raise SalesforceAuthExpired(f"Your Salesforce connection has expired ({_error_text(resp)}). Please reconnect.", resp.status_code)
    body = resp.json()
    return body["access_token"], body.get("instance_url"), body.get("refresh_token")


def revoke(http: httpx.Client, *, login_host: str, token: str) -> None:
    """Best effort: revoking the refresh token also revokes its access tokens."""
    try:
        http.post(f"https://{login_host}/services/oauth2/revoke", data={"token": token})
    except httpx.HTTPError:
        pass


def fetch_identity(http: httpx.Client, identity_url: str, access_token: str) -> dict:
    resp = http.get(identity_url, headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code != 200:
        raise SalesforceError(f"Couldn't read your Salesforce user details ({_error_text(resp)}).", resp.status_code)
    return resp.json()
