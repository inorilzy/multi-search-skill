"""Read and write the ``settings`` record of the desktop-owned ``config.sqlite``.

API keys are not stored here; they live in ``~/.multi-search/keys.json``. The
legacy ``credentials`` table may still exist in the database but is never read
or written.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import CONFIG_SCHEMA_VERSION, config_db_path

SCHEMA_VERSION = CONFIG_SCHEMA_VERSION
_SETTINGS_COLUMNS = [("id", "INTEGER", 0, 1), ("data", "TEXT", 1, 0)]
_MISSING_DATABASE = (
    "configuration database is missing; open the desktop application "
    "to create and migrate config.sqlite"
)


class ConfigDatabaseError(RuntimeError):
    """The configuration database is unavailable, has an unsupported schema, or is unreadable."""


class ConfigDatabase:
    """Read/write a desktop-owned ``config.sqlite``.

    The desktop owns schema creation and migration. This class only validates
    the on-disk schema version and the ``settings`` column layout; it never
    creates tables and never upgrades a version. A missing database reads as
    empty settings, and an unversioned or future-versioned database raises an
    explicit error that points the user at the desktop application.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else config_db_path()

    @contextmanager
    def connect(self):
        if not self.path.exists():
            yield None
            return
        conn = None
        try:
            conn = sqlite3.connect(str(self.path), timeout=5)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise ConfigDatabaseError(
                    "configuration database schema version "
                    f"{version} is not supported by this CLI (expected {SCHEMA_VERSION}); "
                    "the desktop application owns schema creation and migration"
                )
            actual = [(r[1], r[2].upper(), r[3], r[5]) for r in conn.execute("PRAGMA table_info(settings)")]
            if actual != _SETTINGS_COLUMNS:
                raise ConfigDatabaseError("configuration database schema is invalid")
            yield conn
            conn.commit()
        except ConfigDatabaseError:
            if conn is not None:
                conn.rollback()
            raise
        except (sqlite3.Error, OSError):
            if conn is not None:
                conn.rollback()
            raise ConfigDatabaseError("configuration database operation failed") from None
        finally:
            if conn is not None:
                conn.close()

    def read_settings(self) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT data FROM settings WHERE id=1").fetchone() if conn else None
        if not row:
            return {}
        try:
            data = json.loads(row[0])
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (TypeError, ValueError):
            raise ConfigDatabaseError("stored settings are unreadable") from None

    def write_settings(self, data: dict) -> None:
        try:
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raise ConfigDatabaseError("settings must contain JSON values") from None
        with self.connect() as conn:
            if conn is None:
                # Creating the database here would make the CLI a second schema owner.
                raise ConfigDatabaseError(_MISSING_DATABASE)
            conn.execute("INSERT INTO settings(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (raw,))
