"""Freeze six representative, non-smoke2 videos for the 3-worker gate."""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "VidHalLoc_1200_budget500.json"
OUTPUT_ROOT = (
    ROOT
    / "VidHalLoc_1200_budget500_build"
    / "concurrent_smoke6_20260730"
)
OUTPUT = OUTPUT_ROOT / "selection_smoke6.json"
EXCLUDED_SMOKE2_IDS = {"captioning_0271", "videoqa_1104"}
SOURCE_SEQUENCES = {3, 4, 5, 15, 16, 30}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(
            descriptor, "w", encoding="utf-8", closefd=True
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(temporary).replace(path)
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parent = json.loads(PARENT.read_text(encoding="utf-8-sig"))
    selected = [
        dict(row)
        for row in parent["videos"]
        if int(row["sequence"]) in SOURCE_SEQUENCES
    ]
    if len(selected) != 6:
        raise RuntimeError("Expected exactly six source sequences")
    if {row["video_id"] for row in selected} & EXCLUDED_SMOKE2_IDS:
        raise RuntimeError("Smoke6 overlaps the prior two-video smoke")
    if len({row["sha256"] for row in selected}) != 6:
        raise RuntimeError("Smoke6 contains duplicate source bytes")
    task_counts = Counter(row["task_type"] for row in selected)
    if task_counts != {
        "video_captioning": 3,
        "video_qa": 3,
    }:
        raise RuntimeError("Smoke6 task allocation is not 3+3")
    for smoke_sequence, row in enumerate(selected, 1):
        row["smoke_sequence"] = smoke_sequence

    document = {
        "schema_version": "videohalo_concurrent_smoke6_selection_3.7.6",
        "selection_id": "VidHalLoc_concurrent_smoke6_20260730",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_selection": str(PARENT),
        "status": "frozen_for_three_worker_smoke",
        "policy": {
            "taxonomy": "VHal-Fixed8-3.7",
            "task_targets": dict(task_counts),
            "selection_seed": 42,
            "target_accepted_pairs": 12,
            "per_video_pair_cap": 2,
            "video_workers": 3,
            "upload_workers": 3,
            "window_size": 6,
            "prior_smoke2_video_ids_excluded": sorted(
                EXCLUDED_SMOKE2_IDS
            ),
            "formal_output_mutation": False,
        },
        "selection_summary": {
            "total": 6,
            "by_task": dict(task_counts),
            "clear_scene_cut_count": sum(
                bool(row["audited_clear_scene_cut"])
                for row in selected
            ),
            "source_datasets": dict(
                Counter(row["source_dataset"] for row in selected)
            ),
            "duration_seconds": round(
                sum(float(row["duration_seconds"]) for row in selected),
                6,
            ),
            "bytes": sum(int(row["bytes"]) for row in selected),
        },
        "videos": selected,
        "runtime": {
            "output": str(OUTPUT_ROOT / "public_probe_items.jsonl"),
            "status": str(OUTPUT_ROOT / "status.json"),
            "events": str(OUTPUT_ROOT / "events"),
            "runner_pid": str(OUTPUT_ROOT / "runner.pid"),
            "runner_log": str(OUTPUT_ROOT / "runner.log"),
        },
    }
    atomic_json(OUTPUT, document)
    print(json.dumps(document["selection_summary"], indent=2))
    print(str(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
