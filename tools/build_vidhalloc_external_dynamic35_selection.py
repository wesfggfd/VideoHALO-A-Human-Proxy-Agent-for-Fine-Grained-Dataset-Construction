"""Build a provisional UCF-family 35%-dynamic VidHalLoc selection.

The existing VidHalLoc.json is never overwritten.  Seven hundred low-change
Perception Test rows (350 per task) are replaced one-for-one with UCF101 and
UCF101-DS candidates. Every addition has audio, is within the existing media
caps, uses a unique content hash, and comes from a unique source parent group.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_SELECTION = ROOT / "VidHalLoc.json"
FINAL_MANIFEST = (
    ROOT / "video_dataset_staging" / "final_10000" / "final_manifest.csv"
)
SCREEN_UCF101 = (
    ROOT
    / "video_dataset_staging"
    / "ucf101_videohalo"
    / "camera_screen.jsonl"
)
SCREEN_UCF101DS = (
    ROOT
    / "video_dataset_staging"
    / "ucf101ds_videohalo"
    / "camera_screen.jsonl"
)
AUDIO_AUDIT = (
    ROOT
    / "VidHalLoc_dynamic35_external_build"
    / "audio_loudness.jsonl"
)
AUDIO_EXCLUSIONS = (
    ROOT
    / "VidHalLoc_dynamic35_external_build"
    / "audio_exclusions.jsonl"
)
OUTPUT = ROOT / "VidHalLoc_dynamic35_external_provisional.json"
BUILD_ROOT = ROOT / "VidHalLoc_dynamic35_external_build"
PAIR_OUTPUT = BUILD_ROOT / "replacement_pairs.jsonl"
SUMMARY_OUTPUT = BUILD_ROOT / "selection_summary.json"
BUILD_INPUT = BUILD_ROOT / "input_2600.jsonl"

TASKS = ("video_captioning", "video_qa")
REPLACE_PER_TASK = 350
REPLACE_TOTAL = REPLACE_PER_TASK * len(TASKS)
SOURCE_QUOTAS = {"UCF101": 430, "UCF101-DS": 270}
SOURCE_CUT_TARGETS = {"UCF101": 35, "UCF101-DS": 180}
PERCEPTION_GROUPS = {
    "video_captioning": "captioning_perception",
    "video_qa": "videoqa_perception",
}


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def max_adjacent_phash_distance(serialized: str) -> int:
    hashes = [int(value, 16) for value in serialized.split(";") if value]
    if len(hashes) < 2:
        return 0
    return max(
        bin(left ^ right).count("1")
        for left, right in zip(hashes, hashes[1:])
    )


def candidate_rank(row: dict) -> tuple:
    return (
        -int(int(row["persistent_cut_count"]) > 0),
        -min(int(row["persistent_cut_count"]), 4),
        -int(row["strong_global_motion_pair_count"]),
        -int(row["robust_global_motion_pair_count"]),
        -float(row["maximum_corner_displacement"]),
        -int(row["maximum_pair_phash_distance"]),
        row["video_id"],
    )


def round_robin_labels(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=candidate_rank):
        buckets[row["source_label"]].append(row)
    labels = sorted(
        buckets,
        key=lambda label: (candidate_rank(buckets[label][0]), label),
    )
    output = []
    while labels:
        next_labels = []
        for label in labels:
            output.append(buckets[label].pop(0))
            if buckets[label]:
                next_labels.append(label)
        labels = next_labels
    return output


def unique_parent_candidates(rows: list[dict]) -> list[dict]:
    best_by_parent: dict[str, dict] = {}
    for row in rows:
        if not row["camera_dynamic_candidate"]:
            continue
        parent = row["source_parent_video_id"]
        current = best_by_parent.get(parent)
        if current is None or candidate_rank(row) < candidate_rank(current):
            best_by_parent[parent] = row
    return list(best_by_parent.values())


def take_stratified(
    rows: list[dict], *, total: int, target_cuts: int
) -> list[dict]:
    cuts = round_robin_labels(
        [row for row in rows if int(row["persistent_cut_count"]) > 0]
    )
    motions = round_robin_labels(
        [row for row in rows if int(row["persistent_cut_count"]) == 0]
    )
    selected = cuts[:target_cuts] + motions[: total - target_cuts]
    used_parents = {
        row["source_parent_video_id"] for row in selected
    }
    used_hashes = {row["sha256"] for row in selected}
    if len(selected) < total:
        fallback = round_robin_labels(
            [
                row
                for row in rows
                if row["source_parent_video_id"] not in used_parents
                and row["sha256"] not in used_hashes
            ]
        )
        selected.extend(fallback[: total - len(selected)])
    deduplicated = []
    used_parents.clear()
    used_hashes.clear()
    for row in selected:
        parent = row["source_parent_video_id"]
        if parent in used_parents or row["sha256"] in used_hashes:
            continue
        deduplicated.append(row)
        used_parents.add(parent)
        used_hashes.add(row["sha256"])
    if len(deduplicated) < total:
        fallback = round_robin_labels(
            [
                row
                for row in rows
                if row["source_parent_video_id"] not in used_parents
                and row["sha256"] not in used_hashes
            ]
        )
        for row in fallback:
            deduplicated.append(row)
            used_parents.add(row["source_parent_video_id"])
            used_hashes.add(row["sha256"])
            if len(deduplicated) == total:
                break
    if len(deduplicated) != total:
        raise RuntimeError(
            f"Only {len(deduplicated)} unique-parent dynamic candidates"
        )
    return deduplicated


def main() -> int:
    current_document = json.loads(
        CURRENT_SELECTION.read_text(encoding="utf-8-sig")
    )
    current = list(current_document["videos"])
    audio_by_id = (
        {
            row["video_id"]: row
            for row in read_jsonl(AUDIO_AUDIT)
        }
        if AUDIO_AUDIT.exists()
        else {}
    )
    known_inaudible_ids = {
        video_id
        for video_id, row in audio_by_id.items()
        if not (row.get("ok") and row.get("audible"))
    }
    if AUDIO_EXCLUSIONS.exists():
        known_inaudible_ids.update(
            row["video_id"] for row in read_jsonl(AUDIO_EXCLUSIONS)
        )
    selected_by_source: dict[str, list[dict]] = {}
    for source_name, screen_path in (
        ("UCF101", SCREEN_UCF101),
        ("UCF101-DS", SCREEN_UCF101DS),
    ):
        candidates = [
            row
            for row in unique_parent_candidates(read_jsonl(screen_path))
            if row["video_id"] not in known_inaudible_ids
            and (
                int(row["persistent_cut_count"]) > 0
                or int(row["strong_global_motion_pair_count"]) >= 2
            )
        ]
        selected_by_source[source_name] = take_stratified(
            candidates,
            total=SOURCE_QUOTAS[source_name],
            target_cuts=SOURCE_CUT_TARGETS[source_name],
        )
    additions = [
        row
        for source_name in ("UCF101", "UCF101-DS")
        for row in selected_by_source[source_name]
    ]
    assigned: dict[str, list[dict]] = {task: [] for task in TASKS}
    for source_name in ("UCF101", "UCF101-DS"):
        rows = sorted(
            selected_by_source[source_name],
            key=lambda row: (
                row["source_label"],
                int(row["persistent_cut_count"]) == 0,
                candidate_rank(row),
            ),
        )
        for index, row in enumerate(rows):
            assigned[TASKS[index % 2]].append(row)
    if any(len(assigned[task]) != REPLACE_PER_TASK for task in TASKS):
        raise RuntimeError("Candidate task split is not 350/350")

    with FINAL_MANIFEST.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        manifest_rows = list(csv.DictReader(handle))
    manifest_by_hash = {row["sha256"]: row for row in manifest_rows}

    removals: dict[str, list[dict]] = {}
    for task in TASKS:
        rows = []
        for row in current:
            if (
                row["task_type"] != task
                or row["allocation_group"] != PERCEPTION_GROUPS[task]
            ):
                continue
            manifest = manifest_by_hash[row["sha256"]]
            rows.append(
                {
                    **row,
                    "max_adjacent_phash_distance": (
                        max_adjacent_phash_distance(
                            manifest["visual_phash_5x64"]
                        )
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                row["max_adjacent_phash_distance"],
                float(row["duration_seconds"]),
                row["video_id"],
            )
        )
        removals[task] = rows[:REPLACE_PER_TASK]
        if len(removals[task]) != REPLACE_PER_TASK:
            raise RuntimeError(f"Insufficient removal rows for {task}")

    replacement_pairs = []
    removed_ids = set()
    addition_rows = []
    for task in TASKS:
        task_additions = assigned[task]
        task_additions.sort(key=candidate_rank)
        for removal, addition in zip(removals[task], task_additions):
            removed_ids.add(removal["video_id"])
            stratum = (
                "persistent_cut"
                if int(addition["persistent_cut_count"]) > 0
                else "global_camera_motion"
            )
            replacement_pairs.append(
                {
                    "task_type": task,
                    "camera_stratum": stratum,
                    "removed_video_id": removal["video_id"],
                    "removed_source_path": removal["source_path"],
                    "removed_sha256": removal["sha256"],
                    "removed_allocation_group": removal[
                        "allocation_group"
                    ],
                    "removed_max_adjacent_phash_distance": removal[
                        "max_adjacent_phash_distance"
                    ],
                    "added_video_id": addition["video_id"],
                    "added_source_path": addition["source_path"],
                    "added_sha256": addition["sha256"],
                    "added_parent_video_id": addition[
                        "source_parent_video_id"
                    ],
                    "added_source_label": addition["source_label"],
                    "added_duration_seconds": addition[
                        "duration_seconds"
                    ],
                    "added_bytes": addition["bytes"],
                    "camera_evidence": {
                        "persistent_cut_count": addition[
                            "persistent_cut_count"
                        ],
                        "robust_global_motion_pair_count": addition[
                            "robust_global_motion_pair_count"
                        ],
                        "strong_global_motion_pair_count": addition[
                            "strong_global_motion_pair_count"
                        ],
                        "maximum_corner_displacement": addition[
                            "maximum_corner_displacement"
                        ],
                    },
                }
            )
            addition_rows.append(
                {
                    "video_id": addition["video_id"],
                    "source_path": addition["source_path"],
                    "task_type": task,
                    "source_pool": "external_dynamic",
                    "source_dataset": addition["source_dataset"],
                    "allocation_group": (
                        "external_ucf101ds_dynamic"
                        if addition["source_dataset"] == "UCF101-DS"
                        else "external_ucf101_dynamic"
                    ),
                    "source_video_id": addition[
                        "source_parent_video_id"
                    ],
                    "source_label": addition["source_label"],
                    "duration_seconds": addition["duration_seconds"],
                    "audio_mean_db": audio_by_id.get(
                        addition["video_id"], {}
                    ).get("audio_mean_db"),
                    "audio_peak_db": audio_by_id.get(
                        addition["video_id"], {}
                    ).get("audio_peak_db"),
                    "audio_stream_count": addition[
                        "audio_stream_count"
                    ],
                    "sha256": addition["sha256"],
                    "bytes": addition["bytes"],
                    "width": addition["width"],
                    "height": addition["height"],
                    "nextqa_questions": 0,
                    "camera_source_evidence": {
                        "stratum": stratum,
                        "persistent_cut_count": addition[
                            "persistent_cut_count"
                        ],
                        "robust_global_motion_pair_count": addition[
                            "robust_global_motion_pair_count"
                        ],
                        "strong_global_motion_pair_count": addition[
                            "strong_global_motion_pair_count"
                        ],
                        "maximum_corner_displacement": addition[
                            "maximum_corner_displacement"
                        ],
                        "screen_schema": addition["screen_schema"],
                    },
                }
            )

    combined = [
        row for row in current if row["video_id"] not in removed_ids
    ] + addition_rows
    by_task = {
        task: sorted(
            (row for row in combined if row["task_type"] == task),
            key=lambda row: row["video_id"],
        )
        for task in TASKS
    }
    if any(len(rows) != 1300 for rows in by_task.values()):
        raise RuntimeError("Final task counts changed")
    final_rows = [
        by_task[task][index]
        for index in range(1300)
        for task in TASKS
    ]
    for sequence, row in enumerate(final_rows, 1):
        row["sequence"] = sequence

    if len({row["video_id"] for row in final_rows}) != 2600:
        raise RuntimeError("Final video IDs are not unique")
    if len({row["sha256"] for row in final_rows}) != 2600:
        raise RuntimeError("Final content hashes are not unique")
    if len(
        {
            row["source_video_id"]
            for row in addition_rows
        }
    ) != REPLACE_TOTAL:
        raise RuntimeError("External source parent groups are not unique")

    summary = {
        "schema_version": "videohalo_vidhalloc_external_dynamic35_summary_1.0",
        "status": "provisional_pending_human_camera_audit",
        "total": len(final_rows),
        "replaced_total": len(replacement_pairs),
        "replacement_by_task": dict(
            Counter(pair["task_type"] for pair in replacement_pairs)
        ),
        "replacement_by_camera_stratum": dict(
            Counter(
                pair["camera_stratum"] for pair in replacement_pairs
            )
        ),
        "replacement_by_source_label": dict(
            Counter(row["source_label"] for row in addition_rows)
        ),
        "replacement_by_source_dataset": dict(
            Counter(row["source_dataset"] for row in addition_rows)
        ),
        "replacement_unique_source_labels": len(
            {row["source_label"] for row in addition_rows}
        ),
        "replacement_unique_parent_video_ids": len(
            {row["source_video_id"] for row in addition_rows}
        ),
        "final_by_task": dict(
            Counter(row["task_type"] for row in final_rows)
        ),
        "final_by_source_dataset": dict(
            Counter(row["source_dataset"] for row in final_rows)
        ),
        "unique_video_ids": len(
            {row["video_id"] for row in final_rows}
        ),
        "unique_sha256": len({row["sha256"] for row in final_rows}),
        "all_additions_have_audio_stream": all(
            row["audio_stream_count"] >= 1 for row in addition_rows
        ),
        "known_inaudible_candidates_excluded": len(
            known_inaudible_ids
        ),
        "all_additions_within_existing_caps": all(
            float(row["duration_seconds"]) <= 140.833333
            and int(row["bytes"]) <= 122791611
            and int(row["width"]) * int(row["height"]) <= 2073600
            for row in addition_rows
        ),
        "current_selection_overwritten": False,
        "model_smoke_started": False,
    }
    document = {
        "schema_version": "videohalo_vidhalloc_selection_3.7.3",
        "selection_id": (
            "VidHalLoc_2600_dynamic35_external_"
            "provisional_pending_human_audit"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_selection": str(CURRENT_SELECTION),
        "status": "provisional_pending_human_camera_audit",
        "policy": {
            **current_document["policy"],
            "eligible_source_scope": (
                "base final_10000 plus audited UCF101/UCF101-DS dynamics"
            ),
            "camera_source_target_ratio": 0.35,
            "camera_source_replacement_count": REPLACE_TOTAL,
            "camera_source_replacement_per_task": REPLACE_PER_TASK,
            "replacement_is_one_to_one": True,
            "external_parent_video_unique": True,
            "external_audio_stream_required": True,
            "current_selection_overwritten": False,
        },
        "selection_summary": summary,
        "videos": final_rows,
    }
    atomic_write(
        OUTPUT,
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        PAIR_OUTPUT,
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in replacement_pairs
        ),
    )
    atomic_write(
        SUMMARY_OUTPUT,
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        BUILD_INPUT,
        "".join(
            json.dumps(
                {
                    "video_id": row["video_id"],
                    "task_type": row["task_type"],
                    "source_path": row["source_path"],
                    "sequence": row["sequence"],
                },
                ensure_ascii=False,
            )
            + "\n"
            for row in final_rows
        ),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
