"""Database migrations (Alembic). Runs on start-up so every environment is on the latest schema."""
import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .config import BACKEND_DIR
from .db import engine

log = logging.getLogger("aquarient.migrate")

# Databases created before migrations existed are equal to this revision.
BASELINE = "0001"


def _config(connection: Connection) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logging"] = False
    return cfg


def _adopt_legacy_database(connection: Connection) -> bool:
    """A database from before migrations: bring it to the baseline shape and mark it as such."""
    insp = inspect(connection)
    if insp.has_table("alembic_version") or not insp.has_table("assessment"):
        return False
    # The one column the pre-migration app added by hand after its first release.
    if insp.has_table("finding") and "object_name" not in {c["name"] for c in insp.get_columns("finding")}:
        connection.execute(text("ALTER TABLE finding ADD COLUMN object_name VARCHAR(80)"))
    command.stamp(_config(connection), BASELINE)
    return True


def upgrade_database() -> None:
    with engine.begin() as connection:
        if _adopt_legacy_database(connection):
            log.info("Existing database adopted at migration %s", BASELINE)
        command.upgrade(_config(connection), "head")
    log.info("Database schema is up to date")
