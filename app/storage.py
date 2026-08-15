"""Persistencia local: alias aprendidos y registro de lo que entra por voz."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS aliases (
    phrase      TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    phrase       TEXT NOT NULL,
    product_id   TEXT,
    product_name TEXT,
    thumbnail    TEXT,
    quantity     REAL,
    source       TEXT,
    score        REAL,
    status       TEXT NOT NULL,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_voice_log_ts ON voice_log (ts DESC);
"""


class Storage:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    # --------------------------------------------------------------- alias

    def alias(self, phrase: str) -> str | None:
        row = self._db.execute("SELECT product_id FROM aliases WHERE phrase = ?", (phrase,)).fetchone()
        return row["product_id"] if row else None

    def set_alias(self, phrase: str, product_id: str) -> None:
        self._db.execute(
            "INSERT INTO aliases (phrase, product_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(phrase) DO UPDATE SET product_id = excluded.product_id, "
            "updated_at = excluded.updated_at",
            (phrase, str(product_id), time.time()),
        )
        self._db.commit()

    def aliases(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._db.execute(
            "SELECT phrase, product_id, updated_at FROM aliases ORDER BY updated_at DESC")]

    def delete_alias(self, phrase: str) -> None:
        self._db.execute("DELETE FROM aliases WHERE phrase = ?", (phrase,))
        self._db.commit()

    # ----------------------------------------------------------- registro

    def log(self, phrase: str, status: str, product: dict[str, Any] | None = None,
            quantity: float = 1.0, source: str = "", score: float = 0.0,
            detail: str = "") -> int:
        cur = self._db.execute(
            "INSERT INTO voice_log (ts, phrase, product_id, product_name, thumbnail, "
            "quantity, source, score, status, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (time.time(), phrase,
             str(product["id"]) if product else None,
             product.get("display_name") if product else None,
             product.get("thumbnail") if product else None,
             quantity, source, score, status, detail),
        )
        self._db.commit()
        return cur.lastrowid or 0

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        return [dict(r) for r in self._db.execute(
            "SELECT * FROM voice_log ORDER BY ts DESC LIMIT ?", (limit,))]

    def pending(self) -> list[dict[str, Any]]:
        """Frases que no se pudieron resolver y esperan que alguien elija en el panel."""
        return [dict(r) for r in self._db.execute(
            "SELECT * FROM voice_log WHERE status = 'pending' ORDER BY ts DESC")]

    def resolve_pending(self, entry_id: int, status: str, product: dict[str, Any] | None = None,
                        detail: str = "") -> None:
        self._db.execute(
            "UPDATE voice_log SET status = ?, product_id = COALESCE(?, product_id), "
            "product_name = COALESCE(?, product_name), thumbnail = COALESCE(?, thumbnail), "
            "detail = ? WHERE id = ?",
            (status,
             str(product["id"]) if product else None,
             product.get("display_name") if product else None,
             product.get("thumbnail") if product else None,
             detail, entry_id),
        )
        self._db.commit()

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM voice_log WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None
