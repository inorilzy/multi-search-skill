"""Desktop-owned config.sqlite fixture for CLI tests.

The desktop application is the only schema owner. CLI tests that need a
writable configuration database must create it through this helper, which
mirrors the desktop's version-1 schema exactly (see
``desktop/src-tauri/src/config_db.rs``).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS credentials(provider TEXT PRIMARY KEY, encrypted_value BLOB NOT NULL, saved_at REAL NOT NULL);"
    "CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);"
    f"PRAGMA user_version={SCHEMA_VERSION};"
)


def create_config_db(path: str | Path) -> Path:
    """Create (or refresh) a desktop-shaped config.sqlite at ``path``.

    Idempotent: an existing version-1 database is left in place.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    return path


def reset_config_db(path: str | Path) -> Path:
    """Delete and recreate the database, for tests that start from nothing."""
    path = Path(path)
    if path.exists():
        path.unlink()
    return create_config_db(path)
