"""Freeze the two caption videos that exposed the task/leaf schema bug."""
from __future__ import annotations

import copy
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "VidHalLoc_1200_budget500_build"
PARENT = ROOT / "VidHalLoc_1200_budget500.json"
OUTPUT_ROOT = BUILD_ROOT / "enterprise_smoke" / "caption_fix"
OUTPUT = OUTPUT_ROOT / "selection.json"
VIDEO_IDS = {"captioning_0021", "captioning_1290"}


def main() -> int:
    if any(
        (OUTPUT_ROOT / name).exists()
        for name in ("public_probe_items.jsonl", "status.json")
    ):
        raise FileExistsError("Refusing to overwrite caption-fix smoke")
    parent = json.loads(PARENT.read_text(encoding="utf-8-sig"))
    videos = [
        copy.deepcopy(row)
        for row in parent["videos"]
        if str(row["video_id"]) in VIDEO_IDS
    ]
    if {str(row["video_id"]) for row in videos} != VIDEO_IDS:
        raise RuntimeError("Caption-fix sources are missing")
    videos.sort(key=lambda row: int(row["sequence"]))
    for index, row in enumerate(videos, 1):
        row["parent_sequence"] = int(row["sequence"])
        row["sequence"] = index
    task_counts = Counter(row["task_type"] for row in videos)
    if task_counts != {"video_captioning": 2}:
        raise RuntimeError("Caption-fix smoke must contain two caption videos")
    document = copy.deepcopy(parent)
    document.update(
        {
            "schema_version": "videohalo_enterprise_caption_fix_smoke_3.7.5",
            "selection_id": "VidHalLoc_enterprise_caption_fix_smoke",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parent_selection": str(PARENT),
            "status": "frozen_for_caption_existence_schema_regression",
            "videos": videos,
        }
    )
    document["policy"]["task_targets"] = dict(task_counts)
    document["policy"]["target_accepted_pairs"] = 4
    document["policy"]["smoke_only"] = True
    document["selection_summary"] = {
        "total": 2,
        "by_task": dict(task_counts),
        "video_ids": [row["video_id"] for row in videos],
        "regression": "captioning_entity_existence_answer_form",
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_name("." + OUTPUT.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, OUTPUT)
    print(str(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
