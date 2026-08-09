"""Shared runtime telemetry for windowed builds and budget guards."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


USAGE_FIELDS = (
    "total_input_tokens",
    "total_output_tokens",
    "total_thought_tokens",
    "total_cached_tokens",
    "total_tool_use_tokens",
    "total_tokens",
)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _read_jsonl_tolerant(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                # Event writers append one line at a time. A live observer can
                # briefly encounter the line that is still being written.
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def event_paths_for_output(output_path: Path) -> list[Path]:
    """Return every event stream associated with one public output."""
    output_path = output_path.resolve()
    candidates = [
        output_path.with_suffix(output_path.suffix + ".events.jsonl")
    ]
    event_dir = output_path.parent / "events"
    if event_dir.is_dir():
        candidates.extend(sorted(event_dir.glob("*.jsonl")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def latency_summary(values: Iterable[float]) -> dict[str, Any]:
    values = [float(value) for value in values]
    if not values:
        return {
            "count": 0,
            "mean_seconds": None,
            "median_seconds": None,
            "p90_seconds": None,
            "max_seconds": None,
        }
    return {
        "count": len(values),
        "mean_seconds": round(statistics.mean(values), 6),
        "median_seconds": round(statistics.median(values), 6),
        "p90_seconds": round(_percentile(values, 0.9), 6),
        "max_seconds": round(max(values), 6),
    }


def collect_event_metrics(output_path: Path) -> dict[str, Any]:
    """Aggregate token usage and call latency across all worker logs."""
    usage = {field: 0 for field in USAGE_FIELDS}
    by_role: dict[str, Counter] = defaultdict(Counter)
    latencies: list[float] = []
    started_call_count = 0
    completed_call_count = 0
    unpaired_started_call_count = 0
    event_count = 0
    paths = event_paths_for_output(output_path)

    for path in paths:
        queues: dict[str, deque[str]] = defaultdict(deque)
        for event in _read_jsonl_tolerant(path):
            event_count += 1
            event_type = event.get("event_type")
            node_name = str(event.get("node_name", "UNKNOWN"))
            payload = event.get("payload") or {}
            if event_type == "structured_call_started":
                started_call_count += 1
                queues[node_name].append(str(event["timestamp"]))
                continue
            if event_type != "structured_call_completed":
                continue
            completed_call_count += 1
            call_usage = payload.get("usage") or {}
            role = str(payload.get("role") or node_name)
            for field in USAGE_FIELDS:
                value = int(call_usage.get(field, 0) or 0)
                usage[field] += value
                by_role[role][field] += value
            by_role[role]["completed_call_count"] += 1
            if queues[node_name]:
                started_at = queues[node_name].popleft()
                latencies.append(
                    (
                        _timestamp(str(event["timestamp"]))
                        - _timestamp(started_at)
                    ).total_seconds()
                )
        unpaired_started_call_count += sum(
            len(queue) for queue in queues.values()
        )

    return {
        "event_paths": [str(path) for path in paths],
        "event_count": event_count,
        "started_call_count": started_call_count,
        "completed_call_count": completed_call_count,
        "unpaired_started_call_count": unpaired_started_call_count,
        "usage": usage,
        "latency": latency_summary(latencies),
        "by_role": {
            role: dict(values)
            for role, values in sorted(by_role.items())
        },
    }


def estimate_cost(
    usage: Mapping[str, int],
    billing: Mapping[str, Any],
) -> dict[str, float | int]:
    input_tokens = int(usage.get("total_input_tokens", 0))
    cached_tokens = min(
        input_tokens, int(usage.get("total_cached_tokens", 0))
    )
    noncached_tokens = input_tokens - cached_tokens
    output_and_thought = int(
        usage.get("total_output_tokens", 0)
    ) + int(usage.get("total_thought_tokens", 0))
    usd = (
        noncached_tokens
        * float(billing["usd_per_million_noncached_input"])
        + cached_tokens
        * float(billing["usd_per_million_cached_input"])
        + output_and_thought
        * float(billing["usd_per_million_output_including_thought"])
    ) / 1_000_000
    aud_before_gst = usd / float(billing["aud_usd_reference"])
    aud_including_gst = aud_before_gst * (
        1.0 + float(billing["gst_rate"])
    )
    return {
        "billable_noncached_input_tokens": noncached_tokens,
        "billable_cached_input_tokens": cached_tokens,
        "billable_output_and_thought_tokens": output_and_thought,
        "usd": round(usd, 6),
        "aud_before_gst": round(aud_before_gst, 6),
        "aud_including_gst": round(aud_including_gst, 6),
    }
