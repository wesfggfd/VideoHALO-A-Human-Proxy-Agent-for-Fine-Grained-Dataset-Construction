"""Continuously record cumulative and Enterprise-session build efficiency."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from videohalo.runtime_metrics import (
    USAGE_FIELDS,
    collect_event_metrics,
    estimate_cost,
    latency_summary,
)


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = (
    ROOT / "VidHalLoc_1200_budget500_build" / "formal_run_2000_enterprise"
)
POLICY = ROOT / "VidHalLoc_1200_budget500_build" / "budget_policy.json"


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, value: dict) -> None:
    handle, temporary = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def session_events(output: Path, started_at: datetime) -> dict:
    usage = {field: 0 for field in USAGE_FIELDS}
    calls_started = 0
    calls_completed = 0
    latencies: list[float] = []
    for path in sorted((output.parent / "events").glob("*.jsonl")):
        queues: dict[str, deque[datetime]] = defaultdict(deque)
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    occurred_at = timestamp(str(event["timestamp"]))
                except (ValueError, KeyError, json.JSONDecodeError):
                    continue
                if occurred_at < started_at:
                    continue
                node = str(event.get("node_name", "UNKNOWN"))
                if event.get("event_type") == "structured_call_started":
                    calls_started += 1
                    queues[node].append(occurred_at)
                elif event.get("event_type") == "structured_call_completed":
                    calls_completed += 1
                    call_usage = (event.get("payload") or {}).get("usage") or {}
                    for field in USAGE_FIELDS:
                        usage[field] += int(call_usage.get(field, 0) or 0)
                    if queues[node]:
                        latencies.append(
                            (occurred_at - queues[node].popleft()).total_seconds()
                        )
    return {
        "started_call_count": calls_started,
        "completed_call_count": calls_completed,
        "unpaired_started_call_count": max(0, calls_started - calls_completed),
        "usage": usage,
        "latency": latency_summary(latencies),
    }


def snapshot(run_root: Path = RUN_ROOT, policy_path: Path = POLICY) -> dict:
    status = read_json(run_root / "status.json")
    output = run_root / "public_probe_items.jsonl"
    billing = read_json(policy_path)["billing_formula"]
    started_at = timestamp(status["enterprise_run_started_at"])
    observed_at = datetime.now(timezone.utc)
    wall_hours = max((observed_at - started_at).total_seconds() / 3600.0, 1e-9)
    new_pairs = max(
        0,
        int(status["total_pair_count"])
        - int(status.get("resume_baseline_pair_count", 0)),
    )
    new_videos = max(
        0,
        int(status["completed_video_count"])
        - int(status.get("resume_baseline_completed_video_count", 0)),
    )
    session = session_events(output, started_at)
    session_cost = estimate_cost(session["usage"], billing)
    cumulative = collect_event_metrics(output)
    cumulative_cost = estimate_cost(cumulative["usage"], billing)
    pairs_per_hour = new_pairs / wall_hours
    videos_per_hour = new_videos / wall_hours
    remaining_pairs = max(0, 2000 - int(status["total_pair_count"]))
    projection = None
    if new_pairs >= 10 and pairs_per_hour > 0:
        projection = {
            "remaining_hours_at_observed_rate": round(
                remaining_pairs / pairs_per_hour, 3
            ),
            "session_aud_per_accepted_pair": round(
                float(session_cost["aud_including_gst"]) / new_pairs, 6
            ),
            "projected_cumulative_aud_at_target": round(
                float(cumulative_cost["aud_including_gst"])
                + remaining_pairs
                * float(session_cost["aud_including_gst"])
                / new_pairs,
                3,
            ),
        }
    return {
        "schema_version": "vidhalloc_enterprise_efficiency_snapshot_1.0",
        "observed_at": observed_at.isoformat(),
        "run_state": status["state"],
        "total_pair_count": status["total_pair_count"],
        "remaining_pair_count": remaining_pairs,
        "completed_video_count": status["completed_video_count"],
        "failed_video_count": status["failed_video_count"],
        "session": {
            **session,
            "new_accepted_pairs": new_pairs,
            "new_completed_videos": new_videos,
            "wall_hours": round(wall_hours, 6),
            "accepted_pairs_per_hour": round(pairs_per_hour, 6),
            "completed_videos_per_hour": round(videos_per_hour, 6),
            "estimated_cost": session_cost,
        },
        "cumulative": {
            "usage": cumulative["usage"],
            "estimated_cost": cumulative_cost,
        },
        "projection_after_10_new_pairs": projection,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=RUN_ROOT)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run_root = args.run_dir.resolve()
    policy_path = args.policy.resolve()
    latest = run_root / "efficiency_metrics.json"
    history = run_root / "efficiency_metrics.jsonl"
    while True:
        value = snapshot(run_root, policy_path)
        atomic_json(latest, value)
        with history.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        if args.once or value["run_state"] not in {"preloading", "running"}:
            return 0
        time.sleep(max(5.0, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
