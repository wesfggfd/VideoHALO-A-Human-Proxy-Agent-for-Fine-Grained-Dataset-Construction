"""Freeze one-video and six-video Enterprise smoke selections from pending sources."""
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
FORMAL_STATUS = BUILD_ROOT / "formal_run_2000_enterprise" / "status.json"
SMOKE_ROOT = BUILD_ROOT / "enterprise_smoke"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def selection_document(parent: dict, videos: list[dict], *, stage: str) -> dict:
    rows = [copy.deepcopy(item) for item in videos]
    for index, row in enumerate(rows, 1):
        row["parent_sequence"] = int(row["sequence"])
        row["sequence"] = index
    task_counts = Counter(str(row["task_type"]) for row in rows)
    document = copy.deepcopy(parent)
    document["schema_version"] = "videohalo_enterprise_%s_smoke_3.7.5" % stage
    document["selection_id"] = "VidHalLoc_enterprise_%s_smoke" % stage
    document["created_at"] = datetime.now(timezone.utc).isoformat()
    document["parent_selection"] = str(PARENT)
    document["formal_status"] = str(FORMAL_STATUS)
    document["status"] = "frozen_for_enterprise_smoke"
    document["videos"] = rows
    document["policy"]["task_targets"] = dict(sorted(task_counts.items()))
    document["policy"]["target_accepted_pairs"] = len(rows) * 2
    document["policy"]["smoke_only"] = True
    document["selection_summary"] = {
        "total": len(rows),
        "by_task": dict(sorted(task_counts.items())),
        "unique_video_ids": len({row["video_id"] for row in rows}),
        "unique_sha256": len({row["sha256"] for row in rows}),
        "clear_scene_cut_count": sum(
            bool(row.get("audited_clear_scene_cut")) for row in rows
        ),
        "source_sequences": [row["parent_sequence"] for row in rows],
    }
    return document


def main() -> int:
    parent = json.loads(PARENT.read_text(encoding="utf-8-sig"))
    formal = json.loads(FORMAL_STATUS.read_text(encoding="utf-8-sig"))
    completed = {
        video_id
        for video_id, result in formal.get("results", {}).items()
        if result.get("status") == "completed"
    }
    pending = sorted(
        (
            row
            for row in parent["videos"]
            if str(row["video_id"]) not in completed
        ),
        key=lambda row: (
            not bool(row.get("audited_clear_scene_cut")),
            int(row["sequence"]),
        ),
    )
    if len(pending) < 7:
        raise RuntimeError("Not enough pending videos for Enterprise smokes")

    smoke_one = [pending[0]]
    excluded = {str(smoke_one[0]["video_id"])}
    smoke_six = []
    for task_type in ("video_captioning", "video_qa"):
        choices = [
            row
            for row in pending
            if row["task_type"] == task_type
            and str(row["video_id"]) not in excluded
        ][:3]
        if len(choices) != 3:
            raise RuntimeError("Could not allocate a 3+3 task smoke")
        smoke_six.extend(choices)
        excluded.update(str(row["video_id"]) for row in choices)
    smoke_six.sort(key=lambda row: int(row["sequence"]))
    if len({row["sha256"] for row in smoke_one + smoke_six}) != 7:
        raise RuntimeError("Enterprise smoke sources are not byte-unique")

    one_path = SMOKE_ROOT / "one" / "selection.json"
    six_path = SMOKE_ROOT / "six" / "selection.json"
    for path in (one_path, six_path):
        output_dir = path.parent
        if any(
            (output_dir / name).exists()
            for name in ("public_probe_items.jsonl", "status.json")
        ):
            raise FileExistsError("Refusing to overwrite smoke output: %s" % output_dir)
    atomic_json(one_path, selection_document(parent, smoke_one, stage="one"))
    atomic_json(six_path, selection_document(parent, smoke_six, stage="six"))
    print(
        json.dumps(
            {
                "one": str(one_path),
                "one_video_id": smoke_one[0]["video_id"],
                "six": str(six_path),
                "six_task_counts": dict(
                    Counter(row["task_type"] for row in smoke_six)
                ),
                "all_clear_scene_cut_count": sum(
                    bool(row.get("audited_clear_scene_cut"))
                    for row in smoke_one + smoke_six
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
