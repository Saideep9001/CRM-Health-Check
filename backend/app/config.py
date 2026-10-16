"""Application settings, read from environment variables or backend/.env."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_version: str = "0.1.0"
    # The frontend's origin. OAuth redirect URIs must start with this, and CORS allows it.
    frontend_origin: str = "http://localhost:5173"
    database_url: str = f"sqlite:///{(BACKEND_DIR / '.data' / 'aquarient.db').as_posix()}"

    # --- Security ---
    # Fernet key used to encrypt Salesforce tokens at rest. Generated into .data/ if empty (dev only).
    token_encryption_key: str = ""

    # --- Salesforce Connected App ---
    sf_client_id: str = ""
    sf_client_secret: str = ""
    sf_api_version: str = "v61.0"
    # Scopes requested on the consent screen.
    sf_scopes: str = "api refresh_token offline_access"

    # --- Background jobs (health checks) ---
    # embedded: a worker runs inside the API process (one machine / local development).
    # external: the API only queues checks; run `python -m app.worker` separately (production, can scale out).
    # inline:   run each check right after the request (tests).
    job_mode: Literal["embedded", "external", "inline"] = "embedded"
    worker_threads: int = 1  # checks one worker process runs at the same time
    worker_poll_seconds: float = 2.0
    # A running check whose worker hasn't checked in for this long is treated as interrupted.
    worker_heartbeat_timeout_seconds: int = 120
    job_max_attempts: int = 2  # an interrupted check is restarted once, then marked failed

    # --- Scheduled checks and alert email (email is sent only when SMTP_HOST and SMTP_FROM are set) ---
    scheduler_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    # --- Local profile (until sign-in is enabled) ---
    local_user_name: str = "Local User"
    local_user_email: str = "user@localhost"

    @property
    def salesforce_configured(self) -> bool:
        return bool(self.sf_client_id and self.sf_client_secret)

    @property
    def oauth_callback_url(self) -> str:
        return f"{self.frontend_origin.rstrip('/')}/connection/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
