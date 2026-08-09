"""Create the reproducible, clean-room VidHalLoc 2600-video selection.

Only ``video_dataset_staging/final_10000`` is eligible.  Every source video
ever processed by the three earlier ProbeBuild rounds is excluded, including
videos that did not survive into the 234-pair public release.  Exclusion is
enforced by canonical video id, absolute source path, and SHA-256 identity.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL_ROOT = ROOT / "video_dataset_staging" / "final_10000"
FINAL_MANIFEST = FINAL_ROOT / "final_manifest.csv"
PRIOR_MANIFESTS = (
    ROOT / "probe_build_round1" / "video_manifest.jsonl",
    ROOT
    / "probe_build_expansion_200"
    / "append_run_160"
    / "video_manifest.jsonl",
)
PRIOR_SOURCE_SELECTION = (
    ROOT
    / "probe_build_full11_expansion_400"
    / "source_selection_400.json"
)
OUTPUT = ROOT / "VidHalLoc.json"
BUILD_ROOT = ROOT / "VidHalLoc_2600_build"
BUILD_INPUT = BUILD_ROOT / "input_2600.jsonl"
SMOKE_INPUT = BUILD_ROOT / "smoke" / "input_1.jsonl"

TASKS = ("video_captioning", "video_qa")
TARGET_PER_TASK = 1300
SELECTION_SEED = 42
PER_VIDEO_PAIR_CAP = 2

# Preserve source diversity in the portion drawn from final_10000.
FINAL_GROUP_WEIGHTS = {
    "video_captioning": {
        "captioning_perception": 3,
        "captioning_vidor": 2,
    },
    "video_qa": {
        "videoqa_perception": 2,
        "videoqa_nextqa": 3,
    },
}


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def numeric_sort_key(value: str) -> tuple[str, int, str]:
    stem = Path(value).stem
    suffix = stem.rsplit("_", 1)[-1]
    return (stem.rsplit("_", 1)[0], int(suffix) if suffix.isdigit() else -1, stem)


def proportional_quotas(total: int, weights: dict[str, int]) -> dict[str, int]:
    weight_sum = sum(weights.values())
    raw = {key: total * value / weight_sum for key, value in weights.items()}
    quotas = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(quotas.values())
    order = sorted(weights, key=lambda key: (-(raw[key] - quotas[key]), key))
    for key in order[:remainder]:
        quotas[key] += 1
    return quotas


def main() -> None:
    with FINAL_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        final_rows = list(csv.DictReader(handle))

    prior_sources: list[dict] = []
    for manifest_path in PRIOR_MANIFESTS:
        for item in read_jsonl(manifest_path):
            prior_sources.append(
                {
                    "round": str(manifest_path),
                    "video_id": str(item["video_id"]),
                    "source_path": str(item["source_asset"]["uri"]),
                    "sha256": str(item["source_asset"]["sha256"]),
                }
            )
    source_selection = json.loads(
        PRIOR_SOURCE_SELECTION.read_text(encoding="utf-8-sig")
    )
    for item in source_selection["videos"]:
        prior_sources.append(
            {
                "round": str(PRIOR_SOURCE_SELECTION),
                "video_id": str(item["video_id"]),
                "source_path": str(Path(item["source_path"]).resolve()),
                "sha256": str(item["sha256"]),
            }
        )

    prior_video_ids = {item["video_id"] for item in prior_sources}
    prior_hashes = {item["sha256"] for item in prior_sources}
    prior_paths = {
        item["source_path"].casefold()
        for item in prior_sources
        if not item["source_path"].startswith("file:")
    }
    if len(prior_sources) != 600 or len(prior_hashes) != 600:
        raise RuntimeError(
            "Prior ProbeBuild universe must contain exactly 600 source rows "
            f"and 600 unique hashes; got {len(prior_sources)} and "
            f"{len(prior_hashes)}"
        )

    final_candidates: list[dict] = []
    for row in final_rows:
        task_type = (
            "video_captioning" if row["task"] == "captioning" else "video_qa"
        )
        path = Path(row["final_path"]).resolve()
        final_candidates.append(
            {
                "video_id": "f10000_" + row["target_id"],
                "source_path": str(path),
                "task_type": task_type,
                "source_pool": "final_10000",
                "source_dataset": row["source_dataset"],
                "allocation_group": row["allocation_group"],
                "source_video_id": row["source_video_id"],
                "duration_seconds": float(row["duration_seconds"]),
                "audio_mean_db": float(row["audio_mean_db"]),
                "audio_peak_db": float(row["audio_peak_db"]),
                "sha256": row["sha256"],
                "bytes": path.stat().st_size,
                "nextqa_questions": int(row["nextqa_questions"] or 0),
            }
        )

    all_candidates = final_candidates
    prior_filtered = [
        row
        for row in all_candidates
        if row["video_id"] not in prior_video_ids
        and row["sha256"] not in prior_hashes
        and row["source_path"].casefold() not in prior_paths
    ]
    excluded_by_id = sum(row["video_id"] in prior_video_ids for row in all_candidates)
    excluded_by_hash = sum(
        row["sha256"] in prior_hashes and row["video_id"] not in prior_video_ids
        for row in all_candidates
    )
    excluded_by_path = sum(
        row["source_path"].casefold() in prior_paths
        and row["video_id"] not in prior_video_ids
        and row["sha256"] not in prior_hashes
        for row in all_candidates
    )
    eligible: list[dict] = []
    eligible_hashes: set[str] = set()
    internal_duplicate_rows = 0
    for row in prior_filtered:
        if row["sha256"] in eligible_hashes:
            internal_duplicate_rows += 1
            continue
        eligible.append(row)
        eligible_hashes.add(row["sha256"])

    selected: list[dict] = []
    selected_hashes: set[str] = set()
    quota_summary: dict[str, dict] = {}
    for task_type in TASKS:
        quotas = proportional_quotas(
            TARGET_PER_TASK, FINAL_GROUP_WEIGHTS[task_type]
        )
        final_selected: list[dict] = []
        for group, quota in quotas.items():
            available = sorted(
                (
                    row
                    for row in eligible
                    if row["task_type"] == task_type
                    and row["source_pool"] == "final_10000"
                    and row["allocation_group"] == group
                    and row["sha256"] not in selected_hashes
                ),
                key=lambda row: numeric_sort_key(row["video_id"]),
            )
            chosen = available[:quota]
            if len(chosen) != quota:
                raise RuntimeError(
                    f"Insufficient {task_type}/{group}: need {quota}, got {len(chosen)}"
                )
            final_selected.extend(chosen)
            selected_hashes.update(row["sha256"] for row in chosen)
        if len(final_selected) != TARGET_PER_TASK:
            raise RuntimeError(
                f"Selection count mismatch for {task_type}: "
                f"{len(final_selected)}"
            )
        selected.extend(final_selected)
        quota_summary[task_type] = dict(
            Counter(row["allocation_group"] for row in final_selected)
        )

    selected_by_task = {
        task_type: [
            row for row in selected if row["task_type"] == task_type
        ]
        for task_type in TASKS
    }
    selected = [
        selected_by_task[task_type][index]
        for index in range(TARGET_PER_TASK)
        for task_type in TASKS
    ]

    if len(selected) != TARGET_PER_TASK * len(TASKS):
        raise RuntimeError("Global selection count mismatch")
    if len({row["video_id"] for row in selected}) != len(selected):
        raise RuntimeError("Selected video_id values are not unique")
    if len({row["sha256"] for row in selected}) != len(selected):
        raise RuntimeError("Selected video contents are not unique")
    selected_ids = {row["video_id"] for row in selected}
    selected_paths = {row["source_path"].casefold() for row in selected}
    if prior_video_ids.intersection(selected_ids):
        raise RuntimeError("A prior ProbeBuild video_id leaked into the selection")
    if prior_hashes.intersection(selected_hashes):
        raise RuntimeError("Prior ProbeBuild video content leaked into the selection")
    if prior_paths.intersection(selected_paths):
        raise RuntimeError("A prior ProbeBuild source path leaked into the selection")
    expected_root = str(FINAL_ROOT.resolve()).casefold() + "\\"
    if any(
        not row["source_path"].casefold().startswith(expected_root)
        for row in selected
    ):
        raise RuntimeError("Selection contains a source outside final_10000")

    for sequence, row in enumerate(selected, 1):
        row["sequence"] = sequence

    smoke = selected[0]

    historical_captioning_rate = 96 / 310
    historical_videoqa_rate = 138 / 324
    estimated_captioning = TARGET_PER_TASK * historical_captioning_rate
    estimated_videoqa = TARGET_PER_TASK * historical_videoqa_rate

    document = {
        "schema_version": "videohalo_vidhalloc_selection_3.7.0",
        "selection_id": "VidHalLoc_2600_cleanroom_excluding_all_prior600",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "taxonomy": "VHal-Fixed8-3.7",
            "eligible_source_root": str(FINAL_ROOT.resolve()),
            "eligible_source_scope": "final_10000_only",
            "prior_probe_exclusion_sources": [
                *(str(path) for path in PRIOR_MANIFESTS),
                str(PRIOR_SOURCE_SELECTION),
            ],
            "deduplication_keys": [
                "canonical_video_id",
                "absolute_source_path",
                "sha256",
            ],
            "task_targets": {
                "video_captioning": TARGET_PER_TASK,
                "video_qa": TARGET_PER_TASK,
            },
            "selection_strategy": (
                "select only from final_10000, in numeric filename order "
                "within the established allocation-group quotas, then "
                "round-robin interleave Captioning and VideoQA"
            ),
            "selection_seed": SELECTION_SEED,
            "per_video_pair_cap": PER_VIDEO_PAIR_CAP,
            "forced_leaf_balance": False,
        },
        "exclusion_summary": {
            "prior_probe_source_row_count": len(prior_sources),
            "prior_probe_unique_video_id_count": len(prior_video_ids),
            "prior_probe_unique_content_hash_count": len(prior_hashes),
            "candidate_rows_excluded_by_prior_video_id": excluded_by_id,
            "additional_candidate_rows_excluded_by_sha256": excluded_by_hash,
            "additional_candidate_rows_excluded_by_path": excluded_by_path,
            "additional_candidate_rows_excluded_as_internal_duplicates": (
                internal_duplicate_rows
            ),
            "selected_overlap_with_prior_video_ids": 0,
            "selected_overlap_with_prior_sha256": 0,
            "selected_overlap_with_prior_source_paths": 0,
        },
        "pool_summary": {
            "raw": dict(
                Counter(
                    f'{row["source_pool"]}::{row["task_type"]}'
                    for row in all_candidates
                )
            ),
            "eligible_after_probe_exclusion": dict(
                Counter(
                    f'{row["source_pool"]}::{row["task_type"]}'
                    for row in eligible
                )
            ),
        },
        "selection_summary": {
            "total": len(selected),
            "by_task": dict(Counter(row["task_type"] for row in selected)),
            "by_source_pool": dict(
                Counter(row["source_pool"] for row in selected)
            ),
            "by_allocation_group": dict(
                Counter(row["allocation_group"] for row in selected)
            ),
            "task_source_quotas": quota_summary,
            "unique_video_id_count": len({row["video_id"] for row in selected}),
            "unique_sha256_count": len({row["sha256"] for row in selected}),
            "all_sources_under_final_10000": True,
        },
        "yield_estimate": {
            "basis": (
                "234 retained Fixed-8 pairs from 634 historical source-video "
                "runs, with task-specific retained yields"
            ),
            "historical_pairs_per_video": {
                "video_captioning": historical_captioning_rate,
                "video_qa": historical_videoqa_rate,
                "overall": 234 / 634,
            },
            "point_estimate": {
                "video_captioning_pairs": round(estimated_captioning),
                "video_qa_pairs": round(estimated_videoqa),
                "total_pairs": round(estimated_captioning + estimated_videoqa),
            },
            "planning_interval_total_pairs": [817, 1151],
            "theoretical_maximum_at_cap_2": 5200,
        },
        "runtime": {
            "build_profile": "probe_build",
            "build_input_jsonl": str(BUILD_INPUT),
            "smoke_input_jsonl": str(SMOKE_INPUT),
            "smoke_output_jsonl": str(
                BUILD_ROOT / "smoke" / "public_probe_items.jsonl"
            ),
            "full_output_jsonl": str(BUILD_ROOT / "public_probe_items.jsonl"),
            "full_event_log_jsonl": str(
                BUILD_ROOT / "public_probe_items.jsonl.events.jsonl"
            ),
        },
        "smoke_test": {
            "status": "pending",
            "selected_sequence": smoke["sequence"],
            "video_id": smoke["video_id"],
            "source_path": smoke["source_path"],
            "task_type": smoke["task_type"],
        },
        "videos": selected,
    }

    OUTPUT.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    BUILD_INPUT.parent.mkdir(parents=True, exist_ok=True)
    with BUILD_INPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for row in selected:
            handle.write(
                json.dumps(
                    {
                        "video_id": row["video_id"],
                        "source_path": row["source_path"],
                        "task_type": row["task_type"],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
    SMOKE_INPUT.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_INPUT.write_text(
        json.dumps(
            {
                "video_id": smoke["video_id"],
                "source_path": smoke["source_path"],
                "task_type": smoke["task_type"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "selected": len(selected),
                "by_task": document["selection_summary"]["by_task"],
                "by_allocation_group": document["selection_summary"][
                    "by_allocation_group"
                ],
                "smoke_video_id": smoke["video_id"],
                "point_estimate": document["yield_estimate"]["point_estimate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
