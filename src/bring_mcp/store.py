"""Small SQLite key-value store: OAuth clients and tokens, staple items."""

import json
import os
import sqlite3
import time
from pathlib import Path


def data_dir() -> Path:
    """DATA_DIR, or ~/.bring-mcp when unset (local stdio use)."""
    return Path(os.environ.get("DATA_DIR") or Path.home() / ".bring-mcp")


def db_path() -> Path:
    return data_dir() / "bring-mcp.sqlite"


class Store:
    def __init__(self, path: Path):
        # OAuth tokens live here: owner-only directory and file, whatever the umask.
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (kind TEXT, key TEXT, value TEXT, PRIMARY KEY (kind, key))")
        self.db.commit()

    def get(self, kind: str, key: str) -> dict | None:
        row = self.db.execute("SELECT value FROM kv WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind: str, key: str, value: dict) -> None:
        self.db.execute("REPLACE INTO kv VALUES (?, ?, ?)", (kind, key, json.dumps(value)))
        self.db.commit()

    def delete(self, kind: str, key: str) -> None:
        self.db.execute("DELETE FROM kv WHERE kind = ? AND key = ?", (kind, key))
        self.db.commit()

    def purge_expired(self) -> None:
        now = time.time()
        for kind, key, value in self.db.execute("SELECT kind, key, value FROM kv WHERE kind != 'client'").fetchall():
            expires_at = json.loads(value).get("expires_at")
            if expires_at and expires_at < now:
                self.delete(kind, key)
