"""Durable, transaction-safe provider media lease registry."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Tuple


def parse_time(value: Optional[str]):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ProviderLeaseRegistry:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS provider_media_leases (
                provider TEXT NOT NULL, project_hash TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                mime_type TEXT NOT NULL, lease_json TEXT NOT NULL,
                PRIMARY KEY(provider, project_hash, source_sha256, mime_type)
            )""")
        finally:
            connection.close()

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get(self, *, provider: str, project_hash: str, source_sha256: str, mime_type: str) -> Optional[dict]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT lease_json FROM provider_media_leases WHERE provider=? AND project_hash=? AND source_sha256=? AND mime_type=?",
                (provider, project_hash, source_sha256, mime_type),
            ).fetchone()
        finally:
            connection.close()
        return json.loads(row[0]) if row else None

    def claim_pending(self, *, key: Mapping[str, str], pending: Mapping[str, object]) -> Tuple[dict, bool]:
        """Atomically claim a materialization slot.

        Active leases and fresh in-flight claims are reused.  Expired, failed,
        or abandoned pending rows are replaced in the same transaction so a
        resumed run cannot remain attached to a stale ``pending:`` URI.
        """
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT lease_json FROM provider_media_leases WHERE provider=? AND project_hash=? AND source_sha256=? AND mime_type=?",
                (key["provider"], key["project_hash"], key["source_sha256"], key["mime_type"]),
            ).fetchone()
            if row:
                existing = json.loads(row[0])
                if self.reusable(existing):
                    connection.execute("COMMIT")
                    return existing, False
                payload = json.dumps(dict(pending), ensure_ascii=False, sort_keys=True)
                connection.execute(
                    "UPDATE provider_media_leases SET lease_json=? WHERE provider=? AND project_hash=? AND source_sha256=? AND mime_type=?",
                    (payload, key["provider"], key["project_hash"], key["source_sha256"], key["mime_type"]),
                )
                connection.execute("COMMIT")
                return dict(pending), True
            payload = json.dumps(dict(pending), ensure_ascii=False, sort_keys=True)
            connection.execute("INSERT INTO provider_media_leases VALUES (?, ?, ?, ?, ?)",
                               (key["provider"], key["project_hash"], key["source_sha256"], key["mime_type"], payload))
            connection.execute("COMMIT")
            return dict(pending), True
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def upsert(self, lease: Mapping[str, object]) -> None:
        payload = json.dumps(dict(lease), ensure_ascii=False, sort_keys=True)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""INSERT INTO provider_media_leases VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, project_hash, source_sha256, mime_type)
                DO UPDATE SET lease_json=excluded.lease_json""",
                (lease["provider"], lease["project_hash"], lease["source_sha256"], lease["mime_type"], payload))
            connection.execute("COMMIT")
        finally:
            connection.close()

    @staticmethod
    def reusable(lease: Mapping[str, object], *, now=None, margin_minutes: int = 120) -> bool:
        now = now or datetime.now(timezone.utc)
        if lease.get("state") not in {"pending", "active"}:
            return False
        if lease.get("state") == "pending":
            created = parse_time(lease.get("created_at"))
            if created is None or now >= created + timedelta(minutes=15):
                return False
        expires = parse_time(lease.get("expires_at"))
        return expires is None or now < expires - timedelta(minutes=margin_minutes)
