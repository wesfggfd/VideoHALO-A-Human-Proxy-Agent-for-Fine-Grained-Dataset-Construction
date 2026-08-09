"""Monitor a sharded VidHalLoc run and enforce pair and AUD stop limits."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videohalo.runtime_metrics import collect_event_metrics, estimate_cost


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = (
    ROOT / "VidHalLoc_1200_budget500_build" / "budget_policy.json"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl_tolerant(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A worker may be in the middle of an atomic line append.
                continue
    return rows


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def worker_directories(run_dir: Path) -> list[Path]:
    shards = sorted(
        path
        for path in run_dir.glob("shard_*")
        if path.is_dir()
    )
    return shards or [run_dir]


def usage_and_pairs(run_dir: Path) -> dict[str, Any]:
    usage = {
        "completed_api_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "thought_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
    }
    pair_ids: set[str] = set()
    output_video_ids: set[str] = set()
    completed_video_ids: set[str] = set()
    run_started_at: list[datetime] = []
    run_ended_at: list[datetime] = []
    completed_video_durations: list[float] = []
    for worker_dir in worker_directories(run_dir):
        output = worker_dir / "public_probe_items.jsonl"
        for row in read_jsonl_tolerant(output):
            pair_id = str(row.get("pair_id", ""))
            if pair_id:
                pair_ids.add(pair_id)
            video_id = str((row.get("media") or {}).get("video_id", ""))
            if video_id:
                output_video_ids.add(video_id)

        event_metrics = collect_event_metrics(output)
        event_usage = event_metrics["usage"]
        usage["completed_api_calls"] += int(
            event_metrics["completed_call_count"]
        )
        usage["input_tokens"] += int(
            event_usage["total_input_tokens"]
        )
        usage["output_tokens"] += int(
            event_usage["total_output_tokens"]
        )
        usage["thought_tokens"] += int(
            event_usage["total_thought_tokens"]
        )
        usage["cached_tokens"] += int(
            event_usage["total_cached_tokens"]
        )
        usage["total_tokens"] += int(event_usage["total_tokens"])

        status_path = worker_dir / "status.json"
        if status_path.exists():
            try:
                status = json.loads(
                    status_path.read_text(encoding="utf-8-sig")
                )
            except json.JSONDecodeError:
                status = {}
            if status.get("started_at"):
                run_started_at.append(
                    datetime.fromisoformat(
                        str(status["started_at"]).replace("Z", "+00:00")
                    )
                )
                run_ended_at.append(
                    datetime.fromisoformat(
                        str(
                            status.get("completed_at")
                            or datetime.now(timezone.utc).isoformat()
                        ).replace("Z", "+00:00")
                    )
                )
            for video_id, result in (status.get("results") or {}).items():
                if result.get("status") == "completed":
                    completed_video_ids.add(str(video_id))
                    if result.get("started_at") and result.get(
                        "completed_at"
                    ):
                        completed_video_durations.append(
                            (
                                datetime.fromisoformat(
                                    str(result["completed_at"]).replace(
                                        "Z", "+00:00"
                                    )
                                )
                                - datetime.fromisoformat(
                                    str(result["started_at"]).replace(
                                        "Z", "+00:00"
                                    )
                                )
                            ).total_seconds()
                        )
    wall_seconds = (
        (max(run_ended_at) - min(run_started_at)).total_seconds()
        if run_started_at
        else 0.0
    )
    return {
        "usage": usage,
        "accepted_pair_count": len(pair_ids),
        "unique_output_video_count": len(output_video_ids),
        "completed_video_count": len(completed_video_ids),
        "runtime_metrics": {
            "wall_seconds": round(wall_seconds, 6),
            "accepted_pairs_per_hour": (
                round(len(pair_ids) / (wall_seconds / 3600.0), 6)
                if wall_seconds > 0
                else 0.0
            ),
            "completed_videos_per_hour": (
                round(
                    len(completed_video_ids)
                    / (wall_seconds / 3600.0),
                    6,
                )
                if wall_seconds > 0
                else 0.0
            ),
            "mean_video_inference_seconds": (
                round(
                    sum(completed_video_durations)
                    / len(completed_video_durations),
                    6,
                )
                if completed_video_durations
                else None
            ),
        },
    }


def estimate_aud(
    usage: dict[str, int], billing: dict[str, Any]
) -> dict[str, float]:
    value = estimate_cost(
        {
            "total_input_tokens": usage["input_tokens"],
            "total_output_tokens": usage["output_tokens"],
            "total_thought_tokens": usage["thought_tokens"],
            "total_cached_tokens": usage["cached_tokens"],
            "total_tokens": usage["total_tokens"],
        },
        billing,
    )
    return {
        "usd": value["usd"],
        "aud_before_gst": value["aud_before_gst"],
        "aud_including_gst": value["aud_including_gst"],
    }


def command_line_for_pid(pid: int) -> str:
    command = (
        "$p=Get-CimInstance Win32_Process -Filter "
        f"'ProcessId = {pid}' -ErrorAction SilentlyContinue;"
        "if($p){$p.CommandLine}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def stop_workers(run_dir: Path) -> list[dict[str, Any]]:
    stopped: list[dict[str, Any]] = []
    run_text = str(run_dir.resolve()).lower()
    for pid_path in sorted(run_dir.rglob("runner.pid")):
        try:
            pid = int(pid_path.read_text(encoding="utf-8-sig").strip())
        except (OSError, ValueError):
            continue
        command_line = command_line_for_pid(pid)
        command_lower = command_line.lower()
        safe_match = (
            run_text in command_lower
            or "run_vidhalloc_full.py" in command_lower
            or "launch_with_stdin_env.py" in command_lower
        )
        if not command_line:
            stopped.append(
                {
                    "pid": pid,
                    "pid_file": str(pid_path),
                    "result": "not_running",
                }
            )
            continue
        if not safe_match:
            stopped.append(
                {
                    "pid": pid,
                    "pid_file": str(pid_path),
                    "result": "refused_command_line_mismatch",
                    "command_line": command_line,
                }
            )
            continue
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        stopped.append(
            {
                "pid": pid,
                "pid_file": str(pid_path),
                "result": (
                    "stopped" if result.returncode == 0 else "stop_failed"
                ),
                "return_code": result.returncode,
            }
        )
    return stopped


def snapshot(
    run_dir: Path, policy: dict[str, Any]
) -> dict[str, Any]:
    observed = usage_and_pairs(run_dir)
    costs = estimate_aud(
        observed["usage"], policy["billing_formula"]
    )
    target_pairs = int(policy["target_accepted_pairs"])
    live_stop = float(policy["live_cost_stop_aud"])
    reasons = []
    if observed["accepted_pair_count"] >= target_pairs:
        reasons.append("target_accepted_pairs_reached")
    if costs["aud_including_gst"] >= live_stop:
        reasons.append("live_cost_stop_reached")
    return {
        "schema_version": "vidhalloc_budget_guard_status_1.0",
        "updated_at": utc_now(),
        "run_dir": str(run_dir),
        "state": "stop_required" if reasons else "monitoring",
        "stop_reasons": reasons,
        **observed,
        "estimated_cost": costs,
        "limits": {
            "target_accepted_pairs": target_pairs,
            "live_cost_stop_aud": live_stop,
            "hard_budget_aud": float(policy["hard_budget_aud"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Write one monitoring snapshot without waiting or stopping.",
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    policy = json.loads(
        Path(args.policy).resolve().read_text(encoding="utf-8-sig")
    )
    status_path = run_dir / "budget_guard_status.json"

    while True:
        status = snapshot(run_dir, policy)
        atomic_json(status_path, status)
        if args.once:
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0
        if status["state"] == "stop_required":
            status["stopped_at"] = utc_now()
            status["worker_stop_results"] = stop_workers(run_dir)
            status["state"] = "stopped"
            atomic_json(status_path, status)
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0
        time.sleep(max(1.0, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
