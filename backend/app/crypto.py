"""Encryption for secrets stored in the database (Salesforce access/refresh tokens)."""
from functools import lru_cache
import logging

from cryptography.fernet import Fernet, InvalidToken

from .config import BACKEND_DIR, get_settings

log = logging.getLogger(__name__)
_KEY_FILE = BACKEND_DIR / ".data" / "token.key"


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().token_encryption_key.strip()
    if not key:
        # Development convenience: create and reuse a local key file (git-ignored).
        # In production, always set TOKEN_ENCRYPTION_KEY from a secret manager.
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not _KEY_FILE.exists():
            _KEY_FILE.write_bytes(Fernet.generate_key())
            log.warning("TOKEN_ENCRYPTION_KEY not set; generated a development key at %s", _KEY_FILE)
        key = _KEY_FILE.read_text().strip()
    return Fernet(key.encode())


def encrypt(value: str | None) -> str | None:
    return None if value is None else _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:  # key changed or data tampered with
        raise RuntimeError("Stored Salesforce credentials could not be decrypted. Reconnect Salesforce.") from exc
