"""Build a distribution-preserving VidHalLoc pool for a 500 AUD budget.

The frozen 2,600-video source collection is never mutated.  This tool creates:

* a 1,200-video active candidate pool (600 videos per task);
* a 1,100-video core schedule and a 100-video rolling reserve;
* an exclusion manifest for the other 1,400 videos; and
* an independent audit describing task, source, camera, duration, and
  resolution preservation.

The active schedule is arranged in ten-video batches containing five
captioning and five video-QA videos.  The caller can process the core first,
then add reserve batches until 2,000 accepted pairs are reached.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
BASE_SELECTION = ROOT / "VidHalLoc.json"
BASE_CLEARCUT_SCREEN = (
    ROOT
    / "VidHalLoc_dynamic35_external_build"
    / "base2600_dense_clearcut_screen.jsonl"
)
OUTPUT_SELECTION = ROOT / "VidHalLoc_1200_budget500.json"
OUTPUT_ROOT = ROOT / "VidHalLoc_1200_budget500_build"
FULL_INPUT = OUTPUT_ROOT / "input_1200_budget500.jsonl"
CORE_INPUT = OUTPUT_ROOT / "core_input_1100.jsonl"
RESERVE_INPUT = OUTPUT_ROOT / "reserve_input_100.jsonl"
SCHEDULE = OUTPUT_ROOT / "run_schedule_1200.jsonl"
EXCLUDED = OUTPUT_ROOT / "excluded_1400.jsonl"
AUDIT = OUTPUT_ROOT / "selection_audit.json"
BUDGET_POLICY = OUTPUT_ROOT / "budget_policy.json"
GUARD_SCRIPT = ROOT / "tools" / "monitor_vidhalloc_budget_guard.py"

SEED = 42
CAPTIONING = "video_captioning"
VIDEO_QA = "video_qa"

# Exact active-pool cells.  Counts preserve source allocation and the audited
# 35% clear-scene-cut ratio: 210 / 600 for each task.
ACTIVE_TARGETS: dict[tuple[str, str, bool], int] = {
    (CAPTIONING, "captioning_perception", False): 193,
    (CAPTIONING, "captioning_perception", True): 8,
    (CAPTIONING, "captioning_vidor", False): 197,
    (CAPTIONING, "captioning_vidor", True): 16,
    (CAPTIONING, "external_coin_clearcut", True): 152,
    (CAPTIONING, "external_ucf101ds_clearcut", True): 33,
    (CAPTIONING, "external_ucf101_clearcut", True): 1,
    (VIDEO_QA, "videoqa_perception", False): 87,
    (VIDEO_QA, "videoqa_perception", True): 4,
    (VIDEO_QA, "videoqa_nextqa", False): 303,
    (VIDEO_QA, "videoqa_nextqa", True): 35,
    (VIDEO_QA, "external_coin_clearcut", True): 143,
    (VIDEO_QA, "external_ucf101ds_clearcut", True): 27,
    (VIDEO_QA, "external_ucf101_clearcut", True): 1,
}

# The first 1,100 videos form the lower-risk core.  It has 550 videos per task
# and 385 clear-cut videos overall (35%): 192 captioning and 193 video-QA.
CORE_TARGETS: dict[tuple[str, str, bool], int] = {
    (CAPTIONING, "captioning_perception", False): 177,
    (CAPTIONING, "captioning_perception", True): 7,
    (CAPTIONING, "captioning_vidor", False): 181,
    (CAPTIONING, "captioning_vidor", True): 14,
    (CAPTIONING, "external_coin_clearcut", True): 140,
    (CAPTIONING, "external_ucf101ds_clearcut", True): 30,
    (CAPTIONING, "external_ucf101_clearcut", True): 1,
    (VIDEO_QA, "videoqa_perception", False): 81,
    (VIDEO_QA, "videoqa_perception", True): 3,
    (VIDEO_QA, "videoqa_nextqa", False): 276,
    (VIDEO_QA, "videoqa_nextqa", True): 33,
    (VIDEO_QA, "external_coin_clearcut", True): 131,
    (VIDEO_QA, "external_ucf101ds_clearcut", True): 25,
    (VIDEO_QA, "external_ucf101_clearcut", True): 1,
}

FULL_2600_AUD_INCL_GST = 1052.3116089247312
EXPECTED_PAIRS_PER_VIDEO = 1.740741
TARGET_ACCEPTED_PAIRS = 2000
LIVE_COST_STOP_AUD = 480.0
HARD_BUDGET_AUD = 500.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    atomic_text(path, text)


def stable_rank(namespace: str, value: str) -> str:
    return hashlib.sha256(
        f"{SEED}|{namespace}|{value}".encode("utf-8")
    ).hexdigest()


def resolution_tier(row: dict[str, Any]) -> str:
    height = int(row.get("height") or 0)
    if height <= 360:
        return "height_le_360"
    if height <= 720:
        return "height_361_720"
    return "height_gt_720"


def assign_duration_bins(rows: list[dict[str, Any]]) -> dict[str, int]:
    bins: dict[str, int] = {}
    for task in (CAPTIONING, VIDEO_QA):
        task_rows = sorted(
            (row for row in rows if row["task_type"] == task),
            key=lambda row: (
                float(row.get("duration_seconds") or 0.0),
                row["video_id"],
            ),
        )
        total = len(task_rows)
        for index, row in enumerate(task_rows):
            bins[row["video_id"]] = min(3, (index * 4) // total)
    return bins


def proportional_allocations(
    groups: dict[tuple[Any, ...], list[dict[str, Any]]],
    target: int,
    namespace: str,
) -> dict[tuple[Any, ...], int]:
    total = sum(len(rows) for rows in groups.values())
    if target > total:
        raise ValueError(f"Target {target} exceeds available {total}")
    quotas = {
        key: target * len(rows) / total for key, rows in groups.items()
    }
    result = {key: math.floor(value) for key, value in quotas.items()}
    remaining = target - sum(result.values())
    ranked = sorted(
        groups,
        key=lambda key: (
            -(quotas[key] - result[key]),
            stable_rank(namespace, repr(key)),
        ),
    )
    for key in ranked[:remaining]:
        result[key] += 1
    if sum(result.values()) != target:
        raise AssertionError("Proportional allocation did not close")
    if any(result[key] > len(groups[key]) for key in groups):
        raise AssertionError("Sub-stratum allocation exceeds availability")
    return result


def select_from_cell(
    rows: list[dict[str, Any]],
    target: int,
    duration_bins: dict[str, int],
    namespace: str,
) -> list[dict[str, Any]]:
    subgroups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        subgroups[
            (
                duration_bins[row["video_id"]],
                resolution_tier(row),
            )
        ].append(row)
    allocations = proportional_allocations(subgroups, target, namespace)
    selected: list[dict[str, Any]] = []
    for key in sorted(subgroups, key=repr):
        candidates = sorted(
            subgroups[key],
            key=lambda row: stable_rank(namespace, row["video_id"]),
        )
        selected.extend(candidates[: allocations[key]])
    if len(selected) != target:
        raise AssertionError("Cell selection count mismatch")
    return selected


def select_by_targets(
    rows: list[dict[str, Any]],
    targets: dict[tuple[str, str, bool], int],
    duration_bins: dict[str, int],
    namespace: str,
) -> list[dict[str, Any]]:
    cells: dict[tuple[str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cells[
            (
                row["task_type"],
                row["allocation_group"],
                bool(row["_clearcut"]),
            )
        ].append(row)
    unexpected = {
        key: len(value)
        for key, value in cells.items()
        if key not in targets and value
    }
    if unexpected:
        raise ValueError(f"Unexpected selection cells: {unexpected}")
    selected: list[dict[str, Any]] = []
    for key in sorted(targets, key=repr):
        available = cells.get(key, [])
        target = targets[key]
        if len(available) < target:
            raise ValueError(
                f"Insufficient rows in {key}: need {target}, have {len(available)}"
            )
        selected.extend(
            select_from_cell(
                available,
                target,
                duration_bins,
                f"{namespace}|{key}",
            )
        )
    return selected


def smooth_task_order(
    rows: list[dict[str, Any]],
    duration_bins: dict[str, int],
    namespace: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[
            (
                row["allocation_group"],
                bool(row["_clearcut"]),
                duration_bins[row["video_id"]],
                resolution_tier(row),
            )
        ].append(row)
    for key in groups:
        groups[key].sort(
            key=lambda row: stable_rank(
                f"{namespace}|{key}", row["video_id"]
            )
        )
    counts = {key: len(value) for key, value in groups.items()}
    used = Counter()
    total = len(rows)
    ordered: list[dict[str, Any]] = []
    for position in range(total):
        candidates = [key for key in groups if used[key] < counts[key]]
        key = max(
            candidates,
            key=lambda candidate: (
                ((position + 1) * counts[candidate] / total) - used[candidate],
                stable_rank(namespace, repr(candidate)),
            ),
        )
        ordered.append(groups[key][used[key]])
        used[key] += 1
    return ordered


def interleave_tasks(
    rows: list[dict[str, Any]],
    duration_bins: dict[str, int],
    namespace: str,
) -> list[dict[str, Any]]:
    captioning = smooth_task_order(
        [row for row in rows if row["task_type"] == CAPTIONING],
        duration_bins,
        f"{namespace}|captioning",
    )
    video_qa = smooth_task_order(
        [row for row in rows if row["task_type"] == VIDEO_QA],
        duration_bins,
        f"{namespace}|videoqa",
    )
    if len(captioning) != len(video_qa):
        raise ValueError("Task lists must have equal length for interleaving")
    result: list[dict[str, Any]] = []
    for captioning_row, videoqa_row in zip(captioning, video_qa):
        result.extend((captioning_row, videoqa_row))
    return result


def counts_by(
    rows: Iterable[dict[str, Any]], fields: tuple[str, ...]
) -> dict[str, int]:
    result = Counter()
    for row in rows:
        values = []
        for field in fields:
            if field == "clearcut":
                values.append(str(bool(row["_clearcut"])))
            else:
                values.append(str(row.get(field, "")))
        result[" | ".join(values)] += 1
    return dict(sorted(result.items()))


def distribution_shift_pp(
    original: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    field_fn,
) -> float:
    original_counts = Counter(field_fn(row) for row in original)
    selected_counts = Counter(field_fn(row) for row in selected)
    keys = set(original_counts) | set(selected_counts)
    return max(
        abs(
            100.0 * original_counts[key] / len(original)
            - 100.0 * selected_counts[key] / len(selected)
        )
        for key in keys
    )


def public_input_row(row: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "video_id": row["video_id"],
        "source_path": row["source_path"],
        "task_type": row["task_type"],
        "sequence": sequence,
    }


def main() -> int:
    base_document = json.loads(
        BASE_SELECTION.read_text(encoding="utf-8-sig")
    )
    original_rows = [dict(row) for row in base_document["videos"]]
    if len(original_rows) != 2600:
        raise ValueError("Expected the frozen 2,600-video selection")

    base_clearcut_ids = {
        str(row["video_id"])
        for row in read_jsonl(BASE_CLEARCUT_SCREEN)
        if bool(row.get("clear_scene_cut_candidate"))
    }
    for row in original_rows:
        evidence = row.get("camera_source_evidence") or {}
        row["_clearcut"] = bool(
            (
                evidence.get("policy") == "clear_scene_cut_only"
                and int(evidence.get("persistent_cut_count", 0)) > 0
            )
            or str(row.get("original_video_id", "")) in base_clearcut_ids
        )
        row["_original_sequence"] = int(row["sequence"])

    original_camera_counts = counts_by(
        original_rows, ("task_type", "clearcut")
    )
    expected_camera_counts = {
        f"{CAPTIONING} | False": 845,
        f"{CAPTIONING} | True": 455,
        f"{VIDEO_QA} | False": 845,
        f"{VIDEO_QA} | True": 455,
    }
    if original_camera_counts != expected_camera_counts:
        raise ValueError(
            "Frozen clear-cut membership was not recovered exactly: "
            f"{original_camera_counts}"
        )

    duration_bins = assign_duration_bins(original_rows)
    active = select_by_targets(
        original_rows,
        ACTIVE_TARGETS,
        duration_bins,
        "active1200",
    )
    active_ids = {row["video_id"] for row in active}
    core = select_by_targets(
        active,
        CORE_TARGETS,
        duration_bins,
        "core1100",
    )
    core_ids = {row["video_id"] for row in core}
    reserve = [row for row in active if row["video_id"] not in core_ids]
    excluded = [
        row for row in original_rows if row["video_id"] not in active_ids
    ]

    ordered_core = interleave_tasks(core, duration_bins, "core_order")
    ordered_reserve = interleave_tasks(
        reserve, duration_bins, "reserve_order"
    )
    ordered_active = ordered_core + ordered_reserve

    schedule_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    for index, row in enumerate(ordered_active, start=1):
        phase = "core" if index <= 1100 else "reserve"
        phase_sequence = index if phase == "core" else index - 1100
        output = {
            key: value
            for key, value in row.items()
            if not key.startswith("_")
        }
        output["sequence"] = index
        output["original_sequence"] = row["_original_sequence"]
        output["budget_phase"] = phase
        output["phase_sequence"] = phase_sequence
        output["schedule_batch"] = ((index - 1) // 10) + 1
        output["audited_clear_scene_cut"] = bool(row["_clearcut"])
        output["duration_quartile_within_task"] = (
            duration_bins[row["video_id"]] + 1
        )
        output["resolution_tier"] = resolution_tier(row)
        selection_rows.append(output)
        schedule_rows.append(
            {
                "sequence": index,
                "phase": phase,
                "phase_sequence": phase_sequence,
                "batch": ((index - 1) // 10) + 1,
                "video_id": row["video_id"],
                "source_path": row["source_path"],
                "task_type": row["task_type"],
                "allocation_group": row["allocation_group"],
                "source_dataset": row["source_dataset"],
                "audited_clear_scene_cut": bool(row["_clearcut"]),
                "duration_quartile_within_task": (
                    duration_bins[row["video_id"]] + 1
                ),
                "resolution_tier": resolution_tier(row),
            }
        )

    excluded_rows = []
    for row in sorted(excluded, key=lambda item: item["_original_sequence"]):
        excluded_rows.append(
            {
                "video_id": row["video_id"],
                "source_path": row["source_path"],
                "task_type": row["task_type"],
                "allocation_group": row["allocation_group"],
                "source_dataset": row["source_dataset"],
                "audited_clear_scene_cut": bool(row["_clearcut"]),
                "original_sequence": row["_original_sequence"],
                "sha256": row["sha256"],
                "exclusion_reason": (
                    "distribution_preserving_budget_downsample"
                ),
                "physical_source_deleted": False,
            }
        )

    active_public = [
        public_input_row(row, index)
        for index, row in enumerate(ordered_active, start=1)
    ]
    core_public = [
        public_input_row(row, index)
        for index, row in enumerate(ordered_core, start=1)
    ]
    reserve_public = [
        public_input_row(row, index)
        for index, row in enumerate(ordered_reserve, start=1)
    ]

    active_camera = counts_by(active, ("task_type", "clearcut"))
    core_camera = counts_by(core, ("task_type", "clearcut"))
    reserve_camera = counts_by(reserve, ("task_type", "clearcut"))
    active_groups = counts_by(active, ("task_type", "allocation_group"))

    all_files_exist = all(
        Path(row["source_path"]).is_file() for row in original_rows
    )
    unique_original_ids = len({row["video_id"] for row in original_rows})
    unique_active_ids = len(active_ids)
    unique_active_hashes = len({row["sha256"] for row in active})
    partition_ok = (
        active_ids.isdisjoint(
            {row["video_id"] for row in excluded}
        )
        and active_ids
        | {row["video_id"] for row in excluded}
        == {row["video_id"] for row in original_rows}
    )
    every_batch_balanced = True
    for batch_start in range(0, len(schedule_rows), 10):
        batch = schedule_rows[batch_start : batch_start + 10]
        task_counts = Counter(row["task_type"] for row in batch)
        if task_counts != Counter({CAPTIONING: 5, VIDEO_QA: 5}):
            every_batch_balanced = False
            break

    expected_active_camera = {
        f"{CAPTIONING} | False": 390,
        f"{CAPTIONING} | True": 210,
        f"{VIDEO_QA} | False": 390,
        f"{VIDEO_QA} | True": 210,
    }
    expected_core_camera = {
        f"{CAPTIONING} | False": 358,
        f"{CAPTIONING} | True": 192,
        f"{VIDEO_QA} | False": 357,
        f"{VIDEO_QA} | True": 193,
    }
    expected_reserve_camera = {
        f"{CAPTIONING} | False": 32,
        f"{CAPTIONING} | True": 18,
        f"{VIDEO_QA} | False": 33,
        f"{VIDEO_QA} | True": 17,
    }
    expected_active_groups = {
        f"{CAPTIONING} | captioning_perception": 201,
        f"{CAPTIONING} | captioning_vidor": 213,
        f"{CAPTIONING} | external_coin_clearcut": 152,
        f"{CAPTIONING} | external_ucf101_clearcut": 1,
        f"{CAPTIONING} | external_ucf101ds_clearcut": 33,
        f"{VIDEO_QA} | external_coin_clearcut": 143,
        f"{VIDEO_QA} | external_ucf101_clearcut": 1,
        f"{VIDEO_QA} | external_ucf101ds_clearcut": 27,
        f"{VIDEO_QA} | videoqa_nextqa": 338,
        f"{VIDEO_QA} | videoqa_perception": 91,
    }

    passed = all(
        (
            len(active) == 1200,
            len(core) == 1100,
            len(reserve) == 100,
            len(excluded) == 1400,
            unique_original_ids == 2600,
            unique_active_ids == 1200,
            unique_active_hashes == 1200,
            partition_ok,
            all_files_exist,
            every_batch_balanced,
            active_camera == expected_active_camera,
            core_camera == expected_core_camera,
            reserve_camera == expected_reserve_camera,
            active_groups == expected_active_groups,
        )
    )

    per_video_aud = FULL_2600_AUD_INCL_GST / 2600
    audit_payload = {
        "schema_version": "vidhalloc_budget500_selection_audit_1.0",
        "generated_at": utc_now(),
        "passed": passed,
        "checks": {
            "base_selection_unchanged": True,
            "physical_sources_deleted": False,
            "active_total_is_1200": len(active) == 1200,
            "core_total_is_1100": len(core) == 1100,
            "reserve_total_is_100": len(reserve) == 100,
            "excluded_total_is_1400": len(excluded) == 1400,
            "original_ids_are_unique": unique_original_ids == 2600,
            "active_ids_are_unique": unique_active_ids == 1200,
            "active_hashes_are_unique": unique_active_hashes == 1200,
            "active_and_excluded_partition_original": partition_ok,
            "all_source_files_exist": all_files_exist,
            "every_ten_video_batch_is_5_plus_5": every_batch_balanced,
            "active_camera_distribution_exact": (
                active_camera == expected_active_camera
            ),
            "core_camera_distribution_exact": (
                core_camera == expected_core_camera
            ),
            "reserve_camera_distribution_exact": (
                reserve_camera == expected_reserve_camera
            ),
            "active_allocation_distribution_exact": (
                active_groups == expected_active_groups
            ),
        },
        "counts": {
            "original": 2600,
            "active": 1200,
            "core": 1100,
            "reserve": 100,
            "excluded": 1400,
            "active_by_task": counts_by(active, ("task_type",)),
            "active_by_task_camera": active_camera,
            "core_by_task_camera": core_camera,
            "reserve_by_task_camera": reserve_camera,
            "active_by_task_allocation_group": active_groups,
            "active_by_task_source_dataset": counts_by(
                active, ("task_type", "source_dataset")
            ),
            "active_by_duration_quartile": {
                str(index + 1): sum(
                    1
                    for row in active
                    if duration_bins[row["video_id"]] == index
                )
                for index in range(4)
            },
            "active_by_resolution_tier": dict(
                sorted(Counter(resolution_tier(row) for row in active).items())
            ),
        },
        "distribution_shift_percentage_points": {
            "task_allocation_group_max_abs": round(
                distribution_shift_pp(
                    original_rows,
                    active,
                    lambda row: (
                        row["task_type"],
                        row["allocation_group"],
                    ),
                ),
                6,
            ),
            "task_camera_max_abs": round(
                distribution_shift_pp(
                    original_rows,
                    active,
                    lambda row: (
                        row["task_type"],
                        bool(row["_clearcut"]),
                    ),
                ),
                6,
            ),
            "task_duration_quartile_max_abs": round(
                distribution_shift_pp(
                    original_rows,
                    active,
                    lambda row: (
                        row["task_type"],
                        duration_bins[row["video_id"]],
                    ),
                ),
                6,
            ),
            "task_resolution_tier_max_abs": round(
                distribution_shift_pp(
                    original_rows,
                    active,
                    lambda row: (
                        row["task_type"],
                        resolution_tier(row),
                    ),
                ),
                6,
            ),
        },
        "budget_projection_aud_including_gst": {
            "per_video": round(per_video_aud, 6),
            "core_1100": round(per_video_aud * 1100, 2),
            "expected_target_near_1150": round(per_video_aud * 1150, 2),
            "entire_active_1200": round(per_video_aud * 1200, 2),
            "live_cost_stop": LIVE_COST_STOP_AUD,
            "hard_budget": HARD_BUDGET_AUD,
        },
        "yield_projection": {
            "observed_pairs_per_video": EXPECTED_PAIRS_PER_VIDEO,
            "core_1100_expected_pairs": round(
                1100 * EXPECTED_PAIRS_PER_VIDEO
            ),
            "near_1150_expected_pairs": round(
                1150 * EXPECTED_PAIRS_PER_VIDEO
            ),
            "active_1200_expected_pairs": round(
                1200 * EXPECTED_PAIRS_PER_VIDEO
            ),
            "target_accepted_pairs": TARGET_ACCEPTED_PAIRS,
        },
        "outputs": {
            "selection": str(OUTPUT_SELECTION),
            "full_input": str(FULL_INPUT),
            "core_input": str(CORE_INPUT),
            "reserve_input": str(RESERVE_INPUT),
            "schedule": str(SCHEDULE),
            "excluded": str(EXCLUDED),
            "budget_policy": str(BUDGET_POLICY),
            "budget_guard_script": str(GUARD_SCRIPT),
        },
    }
    if not passed:
        raise RuntimeError(
            "Budget selection audit failed:\n"
            + json.dumps(audit_payload, ensure_ascii=False, indent=2)
        )

    selection_document = {
        "schema_version": "videohalo_vidhalloc_budget500_selection_3.7.5",
        "selection_id": "VidHalLoc_1200_budget500_v1",
        "created_at": utc_now(),
        "base_selection": str(BASE_SELECTION),
        "status": "frozen_budget_candidate_pool",
        "policy": {
            "taxonomy": "VHal-Fixed8-3.7",
            "selection_seed": SEED,
            "physical_source_mutation": False,
            "target_accepted_pairs": TARGET_ACCEPTED_PAIRS,
            "hard_budget_aud": HARD_BUDGET_AUD,
            "live_cost_stop_aud": LIVE_COST_STOP_AUD,
            "active_video_count": 1200,
            "core_video_count": 1100,
            "reserve_video_count": 100,
            "task_targets": {
                CAPTIONING: 600,
                VIDEO_QA: 600,
            },
            "active_clearcut_targets": {
                CAPTIONING: 210,
                VIDEO_QA: 210,
            },
            "active_clearcut_ratio": 0.35,
            "sampling_dimensions": [
                "task_type",
                "audited_clear_scene_cut",
                "allocation_group",
                "source_dataset",
                "duration_quartile_within_task",
                "resolution_tier",
            ],
            "run_policy": (
                "Run the 1,100-video core first, then consume ten-video "
                "reserve batches until 2,000 accepted pairs are reached. "
                "Stop automatically if the live GST-inclusive estimate "
                "reaches 480 AUD."
            ),
        },
        "selection_summary": audit_payload["counts"],
        "videos": selection_rows,
        "frozen_at": utc_now(),
        "audit": str(AUDIT),
        "runtime": {
            "full_input_jsonl": str(FULL_INPUT),
            "core_input_jsonl": str(CORE_INPUT),
            "reserve_input_jsonl": str(RESERVE_INPUT),
            "run_schedule_jsonl": str(SCHEDULE),
            "excluded_jsonl": str(EXCLUDED),
            "budget_policy_json": str(BUDGET_POLICY),
            "budget_guard_script": str(GUARD_SCRIPT),
            "source_root": str(
                ROOT
                / "video_dataset_staging"
                / "VidHalLoc_2600_clean"
            ),
        },
    }
    budget_policy = {
        "schema_version": "vidhalloc_budget_guard_1.0",
        "currency": "AUD",
        "gst_included": True,
        "target_accepted_pairs": TARGET_ACCEPTED_PAIRS,
        "live_cost_stop_aud": LIVE_COST_STOP_AUD,
        "hard_budget_aud": HARD_BUDGET_AUD,
        "reserve_batch_size": 10,
        "reserve_batch_task_counts": {
            CAPTIONING: 5,
            VIDEO_QA: 5,
        },
        "estimated_cost_per_video_aud": round(per_video_aud, 6),
        "stop_conditions": [
            "accepted_pair_count >= 2000",
            "live_estimated_cost_aud_including_gst >= 480",
        ],
        "billing_formula": {
            "model": "gemini-3.6-flash",
            "service_tier": "flex",
            "usd_per_million_noncached_input": 0.75,
            "usd_per_million_cached_input": 0.075,
            "usd_per_million_output_including_thought": 3.75,
            "aud_usd_reference": 0.6975,
            "gst_rate": 0.10,
            "formula": (
                "AUD = (((input-cached)*0.75 + cached*0.075 + "
                "(output+thought)*3.75)/1e6)/0.6975*1.10"
            ),
        },
        "guard": {
            "script": str(GUARD_SCRIPT),
            "poll_seconds": 5,
            "command_template": (
                "python tools/monitor_vidhalloc_budget_guard.py "
                "--run-dir <RUN_DIR> --policy "
                "VidHalLoc_1200_budget500_build/budget_policy.json "
                "--poll-seconds 5"
            ),
        },
    }

    write_json(OUTPUT_SELECTION, selection_document)
    write_jsonl(FULL_INPUT, active_public)
    write_jsonl(CORE_INPUT, core_public)
    write_jsonl(RESERVE_INPUT, reserve_public)
    write_jsonl(SCHEDULE, schedule_rows)
    write_jsonl(EXCLUDED, excluded_rows)
    write_json(AUDIT, audit_payload)
    write_json(BUDGET_POLICY, budget_policy)
    print(json.dumps(audit_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
