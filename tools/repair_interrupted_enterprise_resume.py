"""Return infrastructure-interrupted videos to pending without burning attempts."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = (
    ROOT
    / "runs"
    / "formal_run_2000_enterprise"
    / "status.json"
)


def atomic_write(status_path: Path, value: dict) -> None:
    handle, temporary = tempfile.mkstemp(
        prefix="status.", suffix=".tmp", dir=str(status_path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, status_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--restart-reason",
        default="operator_restart_after_runtime_change",
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=DEFAULT_STATUS,
        help="Path to the interrupted run status.json file.",
    )
    args = parser.parse_args()
    status_path = args.status.resolve()
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    repaired = []
    for video_id, result in status.get("results", {}).items():
        running = result.get("status") == "running"
        artifact_race = (
            result.get("status") == "failed"
            and result.get("error_type") == "PermissionError"
            and "leaf_search_plan" in str(result.get("error", ""))
        )
        if not running and not artifact_race:
            continue
        result["status"] = "pending_infrastructure_retry"
        result["attempts"] = max(0, int(result.get("attempts", 0)) - 1)
        result["interrupted_at"] = datetime.now(timezone.utc).isoformat()
        result["infrastructure_reason"] = (
            "artifact_store_write_race_repaired"
            if artifact_race
            else args.restart_reason
        )
        for key in ("failed_at", "error", "error_type"):
            result.pop(key, None)
        repaired.append(video_id)
    status["state"] = "paused_for_repaired_restart"
    status["current_window"] = None
    status["current_videos"] = {}
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    status.setdefault("infrastructure_repairs", []).append(
        {
            "repair_id": args.restart_reason,
            "repaired_video_ids": repaired,
            "attempts_restored": True,
            "applied_at": status["updated_at"],
        }
    )
    atomic_write(status_path, status)
    print(json.dumps({"repaired_video_ids": repaired}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
