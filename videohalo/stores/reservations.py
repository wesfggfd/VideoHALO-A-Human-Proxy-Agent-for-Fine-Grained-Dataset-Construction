"""SQLite-backed source-fact reservations with idempotent transactions."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Mapping, Sequence


class ReservationConflict(RuntimeError):
    pass


class ReservationLedger:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS reservations (
                    dataset_id TEXT NOT NULL,
                    source_fact_id TEXT NOT NULL,
                    planning_round_id TEXT NOT NULL,
                    quota_cell_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(dataset_id, source_fact_id)
                )"""
            )
        finally:
            connection.close()

    def reserve_many(
        self, *, dataset_id: str, planning_round_id: str,
        records: Sequence[Mapping[str, object]]
    ) -> int:
        connection = self._connect()
        inserted = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                fact = str(record["source_fact_id"])
                cell = str(record.get("quota_cell_id") or record["cell_id"])
                key = str(record.get("idempotency_key") or "%s:%s:%s" % (dataset_id, planning_round_id, fact))
                payload = json.dumps(dict(record), ensure_ascii=False, sort_keys=True)
                existing = connection.execute(
                    "SELECT idempotency_key, quota_cell_id FROM reservations WHERE dataset_id=? AND source_fact_id=?",
                    (dataset_id, fact),
                ).fetchone()
                if existing:
                    if existing == (key, cell):
                        continue
                    raise ReservationConflict("Source fact already reserved: %s" % fact)
                connection.execute(
                    "INSERT INTO reservations VALUES (?, ?, ?, ?, ?, ?)",
                    (dataset_id, fact, planning_round_id, cell, key, payload),
                )
                inserted += 1
            connection.execute("COMMIT")
            return inserted
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def list_for_dataset(self, dataset_id: str) -> list:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT payload_json FROM reservations WHERE dataset_id=? ORDER BY source_fact_id",
                (dataset_id,),
            ).fetchall()
        finally:
            connection.close()
        return [json.loads(row[0]) for row in rows]
