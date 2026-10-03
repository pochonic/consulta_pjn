from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .client import PjnResult


class Storage:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_slots (
                slot_key TEXT PRIMARY KEY,
                claimed_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def start_run(self, source: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(source, started_at, status) VALUES (?, ?, ?)",
            (source, datetime.now(timezone.utc).isoformat(), "running"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, results: list[PjnResult], error: str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?, results_json = ?, error = ?
            WHERE id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                "error" if error else "success",
                json.dumps([result.as_dict() for result in results], ensure_ascii=False),
                error,
                run_id,
            ),
        )
        self.connection.commit()

    def claim_slot(self, slot_key: str) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO scheduled_slots(slot_key, claimed_at) VALUES (?, ?)",
            (slot_key, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def close(self) -> None:
        self.connection.close()
