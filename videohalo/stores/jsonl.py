"""Schema-first, duplicate-safe JSONL output for VideoHALO 3.8."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..contracts.registry import ContractRegistry

PAIR_SCHEMA = "videohalo_probe_pair_sample_fixed8.schema.json"


@contextmanager
def _exclusive_lock(path: Path, timeout_sec: float = 30.0) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_sec
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: Optional[int] = None
    while descriptor is None:
        try:
            descriptor = os.open(
                str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
            os.write(descriptor, ("%d\n" % os.getpid()).encode("ascii"))
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for JSONL lock: %s" % lock_path)
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Invalid JSONL at %s:%d" % (path, line_number)
                ) from exc
            if not isinstance(value, dict):
                raise ValueError("JSONL record must be an object at %s:%d" % (path, line_number))
            records.append(value)
    return records


def append_jsonl_record(
    path: Path,
    record: dict,
    *,
    schema_name: str,
    identity_field: str,
    registry: Optional[ContractRegistry] = None,
    max_records: Optional[int] = None,
) -> None:
    registry = registry or ContractRegistry()
    registry.validate(schema_name, record)
    identity = record.get(identity_field)
    if not identity:
        raise ValueError("Missing record identity: %s" % identity_field)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(path):
        existing = read_jsonl(path)
        seen = {item.get(identity_field) for item in existing}
        if identity in seen:
            raise ValueError("Duplicate %s: %s" % (identity_field, identity))
        if max_records is not None:
            if max_records < 1:
                raise ValueError("Global JSONL record limit must be positive")
            if len(existing) >= max_records:
                raise RuntimeError(
                    "Global public pair target is already reached"
                )
        encoded = json.dumps(
            record, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        with path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())


def append_pair_jsonl(
    path: Path,
    record: dict,
    *,
    max_records: Optional[int] = None,
) -> None:
    append_jsonl_record(
        path,
        record,
        schema_name=PAIR_SCHEMA,
        identity_field="pair_id",
        max_records=max_records,
    )
