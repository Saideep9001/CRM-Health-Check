"""Shared FastAPI dependencies."""
from collections.abc import Iterator

import httpx
from fastapi import Request

from .config import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()


def http_dep(request: Request) -> Iterator[httpx.Client]:
    """Outbound HTTP client for Salesforce. Tests swap the transport via app.state.http_transport."""
    transport = getattr(request.app.state, "http_transport", None)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False) as client:
        yield client
