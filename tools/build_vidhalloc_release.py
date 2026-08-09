"""Package the completed VidHalLoc 2K release with leakage-safe splits.

The split unit is the source video, not the individual sample.  Every sample
derived from one video is therefore assigned to the same split.  The script
also verifies content hashes across the packaged videos so duplicate video
content cannot silently leak across Main/Eval/Test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "VidHalLoc_1200_budget500_build" / "formal_run_2000_enterprise"
SOURCE_ITEMS = RUN_ROOT / "public_probe_items.jsonl"
SOURCE_STATUS = RUN_ROOT / "status.json"
RELEASE_ROOT = ROOT / "VidHalLoc"
STAGING_ROOT = ROOT / "VidHalLoc.__staging__"

LEAVES = [
    "EntityExistence",
    "EntityCategory",
    "EntityQuantity",
    "AttributeValue",
    "StaticRelation",
    "ActionPredicate",
    "TemporalRelation",
    "CameraPredicate",
]
SPLITS = ["Main_set", "Eval_set", "Test_set"]
RATIOS = [0.6, 0.2, 0.2]
TASK_CONFIG = {
    "video_qa": {
        "video_dir": "videoqa",
        "dataset_dir": "Videoqa_set",
        "dataset_file": "Videoqa_set.jsonl",
    },
    "video_captioning": {
        "video_dir": "video caption",
        "dataset_dir": "Video_caption_set",
        "dataset_file": "Video_caption_set.jsonl",
    },
}
SEED = 37062026


@dataclass(frozen=True)
class VideoGroup:
    video_id: str
    task_type: str
    rows: tuple[dict[str, Any], ...]
    leaf_counts: tuple[int, ...]
    source_path: Path

    @property
    def size(self) -> int:
        return len(self.rows)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def target_totals(total: int) -> tuple[int, int, int]:
    raw = [total * ratio for ratio in RATIOS]
    values = [math.floor(value) for value in raw]
    remaining = total - sum(values)
    order = sorted(range(3), key=lambda i: (-(raw[i] - values[i]), i))
    for index in order[:remaining]:
        values[index] += 1
    return tuple(values)  # type: ignore[return-value]


def allocate_leaf_targets(
    leaf_totals: dict[str, int], split_totals: tuple[int, int, int]
) -> dict[str, tuple[int, int, int]]:
    """Find integer per-leaf targets with exact global split totals."""

    candidates: dict[str, list[tuple[float, tuple[int, int, int]]]] = {}
    for leaf in LEAVES:
        total = leaf_totals[leaf]
        ideal = [total * ratio for ratio in RATIOS]
        values: list[tuple[float, tuple[int, int, int]]] = []
        main_low = max(0, math.floor(ideal[0]) - 3)
        main_high = min(total, math.ceil(ideal[0]) + 3)
        eval_low = max(0, math.floor(ideal[1]) - 3)
        eval_high = min(total, math.ceil(ideal[1]) + 3)
        for main_count in range(main_low, main_high + 1):
            for eval_count in range(eval_low, eval_high + 1):
                test_count = total - main_count - eval_count
                if test_count < 0 or abs(test_count - ideal[2]) > 4:
                    continue
                allocation = (main_count, eval_count, test_count)
                score = sum(
                    (allocation[i] - ideal[i]) ** 2 for i in range(3)
                )
                values.append((score, allocation))
        candidates[leaf] = sorted(values)

    states: dict[tuple[int, int], tuple[float, list[tuple[int, int, int]]]] = {
        (0, 0): (0.0, [])
    }
    for leaf in LEAVES:
        next_states: dict[
            tuple[int, int], tuple[float, list[tuple[int, int, int]]]
        ] = {}
        for (main_so_far, eval_so_far), (score_so_far, allocations) in states.items():
            for score, allocation in candidates[leaf]:
                new_main = main_so_far + allocation[0]
                new_eval = eval_so_far + allocation[1]
                if new_main > split_totals[0] or new_eval > split_totals[1]:
                    continue
                key = (new_main, new_eval)
                candidate = (score_so_far + score, allocations + [allocation])
                if key not in next_states or candidate[0] < next_states[key][0]:
                    next_states[key] = candidate
        states = next_states

    key = (split_totals[0], split_totals[1])
    if key not in states:
        raise RuntimeError("Could not derive exact integer leaf targets")
    allocations = states[key][1]
    return {leaf: allocations[index] for index, leaf in enumerate(LEAVES)}


def group_size_quotas(
    groups: list[VideoGroup], split_totals: tuple[int, int, int]
) -> dict[int, tuple[int, int, int]]:
    by_size = Counter(group.size for group in groups)
    if set(by_size) - {1, 2}:
        raise ValueError(f"Unexpected samples-per-video values: {dict(by_size)}")
    single_total = by_size[1]
    double_total = by_size[2]
    group_total = len(groups)
    ideal_groups = [group_total * ratio for ratio in RATIOS]
    best: tuple[float, tuple[int, int, int], tuple[int, int, int]] | None = None
    for single_main in range(single_total + 1):
        for single_eval in range(single_total - single_main + 1):
            single_test = single_total - single_main - single_eval
            singles = (single_main, single_eval, single_test)
            doubles: list[int] = []
            valid = True
            for split_index, split_total in enumerate(split_totals):
                remainder = split_total - singles[split_index]
                if remainder < 0 or remainder % 2:
                    valid = False
                    break
                doubles.append(remainder // 2)
            if not valid or sum(doubles) != double_total:
                continue
            group_counts = [singles[i] + doubles[i] for i in range(3)]
            score = sum(
                (group_counts[i] - ideal_groups[i]) ** 2 for i in range(3)
            )
            candidate = (score, singles, tuple(doubles))
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise RuntimeError("Could not derive exact group-size quotas")
    return {1: best[1], 2: best[2]}


def leaf_matrix(
    assignment: dict[str, int], groups_by_id: dict[str, VideoGroup]
) -> list[list[int]]:
    matrix = [[0 for _ in LEAVES] for _ in SPLITS]
    for video_id, split_index in assignment.items():
        group = groups_by_id[video_id]
        for leaf_index, count in enumerate(group.leaf_counts):
            matrix[split_index][leaf_index] += count
    return matrix


def matrix_score(
    matrix: list[list[int]], target_matrix: list[list[int]]
) -> int:
    return sum(
        (matrix[split_index][leaf_index] - target_matrix[split_index][leaf_index])
        ** 2
        for split_index in range(3)
        for leaf_index in range(len(LEAVES))
    )


def optimize_assignment(
    groups: list[VideoGroup],
    split_totals: tuple[int, int, int],
    leaf_targets: dict[str, tuple[int, int, int]],
    seed: int,
) -> tuple[dict[str, int], int, list[list[int]], dict[int, tuple[int, int, int]]]:
    """Use quota-preserving annealed swaps to minimize leaf deviations."""

    quotas = group_size_quotas(groups, split_totals)
    groups_by_id = {group.video_id: group for group in groups}
    target_matrix = [
        [leaf_targets[leaf][split_index] for leaf in LEAVES]
        for split_index in range(3)
    ]
    groups_by_size = {
        size: [group.video_id for group in groups if group.size == size]
        for size in (1, 2)
    }
    best_assignment: dict[str, int] | None = None
    best_matrix: list[list[int]] | None = None
    best_score = 10**9
    rng = random.Random(seed)

    for restart in range(80):
        buckets: dict[int, dict[int, list[str]]] = {
            size: {split_index: [] for split_index in range(3)} for size in (1, 2)
        }
        assignment: dict[str, int] = {}
        for size in (1, 2):
            ids = list(groups_by_size[size])
            rng.shuffle(ids)
            cursor = 0
            for split_index, quota in enumerate(quotas[size]):
                selected = ids[cursor : cursor + quota]
                cursor += quota
                buckets[size][split_index].extend(selected)
                for video_id in selected:
                    assignment[video_id] = split_index
            if cursor != len(ids):
                raise AssertionError("Group quota allocation did not consume all groups")

        matrix = leaf_matrix(assignment, groups_by_id)
        score = matrix_score(matrix, target_matrix)
        temperature = 8.0
        iterations = 160_000
        for iteration in range(iterations):
            if score == 0:
                break
            size = 1 if rng.random() < 0.25 else 2
            split_a, split_b = rng.sample(range(3), 2)
            if not buckets[size][split_a] or not buckets[size][split_b]:
                continue
            index_a = rng.randrange(len(buckets[size][split_a]))
            index_b = rng.randrange(len(buckets[size][split_b]))
            video_a = buckets[size][split_a][index_a]
            video_b = buckets[size][split_b][index_b]
            vector_a = groups_by_id[video_a].leaf_counts
            vector_b = groups_by_id[video_b].leaf_counts

            delta = 0
            for leaf_index in range(len(LEAVES)):
                old_a = matrix[split_a][leaf_index]
                old_b = matrix[split_b][leaf_index]
                new_a = old_a - vector_a[leaf_index] + vector_b[leaf_index]
                new_b = old_b - vector_b[leaf_index] + vector_a[leaf_index]
                target_a = target_matrix[split_a][leaf_index]
                target_b = target_matrix[split_b][leaf_index]
                delta += (new_a - target_a) ** 2 - (old_a - target_a) ** 2
                delta += (new_b - target_b) ** 2 - (old_b - target_b) ** 2

            progress = iteration / iterations
            temperature = max(0.08, 8.0 * (1.0 - progress) ** 2)
            accept = delta <= 0 or rng.random() < math.exp(-delta / temperature)
            if not accept:
                continue
            buckets[size][split_a][index_a] = video_b
            buckets[size][split_b][index_b] = video_a
            assignment[video_a] = split_b
            assignment[video_b] = split_a
            for leaf_index in range(len(LEAVES)):
                matrix[split_a][leaf_index] += (
                    vector_b[leaf_index] - vector_a[leaf_index]
                )
                matrix[split_b][leaf_index] += (
                    vector_a[leaf_index] - vector_b[leaf_index]
                )
            score += delta

        if score < best_score:
            best_score = score
            best_assignment = dict(assignment)
            best_matrix = [row[:] for row in matrix]
        if best_score == 0:
            break

    if best_assignment is None or best_matrix is None:
        raise RuntimeError("Split optimizer did not produce an assignment")
    return best_assignment, best_score, best_matrix, quotas


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "duration_seconds": None,
        "width": None,
        "height": None,
        "fps": None,
        "frame_count": None,
    }
    try:
        import cv2  # type: ignore

        capture = cv2.VideoCapture(str(path))
        if capture.isOpened():
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            metadata.update(
                {
                    "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    "fps": round(fps, 6) if fps > 0 else None,
                    "frame_count": int(frame_count) if frame_count >= 0 else None,
                    "duration_seconds": (
                        round(frame_count / fps, 6)
                        if fps > 0 and frame_count >= 0
                        else None
                    ),
                }
            )
        capture.release()
    except Exception:
        pass
    return metadata


def create_hardlink_or_copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def build_groups(
    rows: list[dict[str, Any]], status: dict[str, Any]
) -> dict[str, list[VideoGroup]]:
    grouped_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        task_type = row["task_type"]
        video_id = row["media"]["video_id"]
        grouped_rows[(task_type, video_id)].append(row)

    result: dict[str, list[VideoGroup]] = {task: [] for task in TASK_CONFIG}
    for (task_type, video_id), video_rows in grouped_rows.items():
        if task_type not in TASK_CONFIG:
            raise ValueError(f"Unknown task type: {task_type}")
        status_result = status["results"].get(video_id)
        if status_result is None:
            raise ValueError(f"Missing status result for {video_id}")
        source_path = Path(status_result["source_path"])
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        counts = Counter(row["leaf_label"] for row in video_rows)
        unknown_leaves = set(counts) - set(LEAVES)
        if unknown_leaves:
            raise ValueError(f"Unknown leaves for {video_id}: {unknown_leaves}")
        result[task_type].append(
            VideoGroup(
                video_id=video_id,
                task_type=task_type,
                rows=tuple(video_rows),
                leaf_counts=tuple(counts[leaf] for leaf in LEAVES),
                source_path=source_path,
            )
        )
    for groups in result.values():
        groups.sort(key=lambda group: group.video_id)
    return result


def split_task(
    task_type: str, groups: list[VideoGroup], seed: int
) -> dict[str, Any]:
    total_rows = sum(group.size for group in groups)
    split_totals = target_totals(total_rows)
    leaf_totals_counter = Counter(
        row["leaf_label"] for group in groups for row in group.rows
    )
    leaf_totals = {leaf: leaf_totals_counter[leaf] for leaf in LEAVES}
    leaf_targets = allocate_leaf_targets(leaf_totals, split_totals)
    assignment, score, matrix, quotas = optimize_assignment(
        groups, split_totals, leaf_targets, seed
    )

    groups_by_id = {group.video_id: group for group in groups}
    split_rows: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    split_videos: dict[str, list[str]] = {split: [] for split in SPLITS}
    for group in groups:
        split = SPLITS[assignment[group.video_id]]
        split_rows[split].extend(group.rows)
        split_videos[split].append(group.video_id)

    for split in SPLITS:
        split_rows[split].sort(
            key=lambda row: (row["media"]["video_id"], row["pair_id"])
        )
        split_videos[split].sort()

    return {
        "task_type": task_type,
        "total_rows": total_rows,
        "total_videos": len(groups),
        "split_totals": dict(zip(SPLITS, split_totals)),
        "leaf_totals": leaf_totals,
        "leaf_targets": {
            leaf: dict(zip(SPLITS, values)) for leaf, values in leaf_targets.items()
        },
        "assignment_score": score,
        "actual_leaf_matrix": {
            split: {leaf: matrix[split_index][leaf_index] for leaf_index, leaf in enumerate(LEAVES)}
            for split_index, split in enumerate(SPLITS)
        },
        "group_size_quotas": {
            str(size): dict(zip(SPLITS, values)) for size, values in quotas.items()
        },
        "assignment": {video_id: SPLITS[index] for video_id, index in assignment.items()},
        "split_rows": split_rows,
        "split_videos": split_videos,
        "groups_by_id": groups_by_id,
    }


def summarize_release(
    task_results: dict[str, dict[str, Any]],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    inventory_by_task_split: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in inventory:
        inventory_by_task_split[(row["task_type"], row["split"])].append(row)

    tasks: dict[str, Any] = {}
    for task_type, result in task_results.items():
        split_stats: dict[str, Any] = {}
        for split in SPLITS:
            rows = result["split_rows"][split]
            videos = inventory_by_task_split[(task_type, split)]
            durations = [
                row["duration_seconds"]
                for row in videos
                if row["duration_seconds"] is not None
            ]
            split_stats[split] = {
                "sample_count": len(rows),
                "sample_share": round(len(rows) / result["total_rows"], 6),
                "source_video_count": len(videos),
                "source_video_share": round(len(videos) / result["total_videos"], 6),
                "leaf_distribution": {
                    leaf: sum(row["leaf_label"] == leaf for row in rows)
                    for leaf in LEAVES
                },
                "source_bytes": sum(row["bytes"] for row in videos),
                "source_gib": round(sum(row["bytes"] for row in videos) / 2**30, 6),
                "total_duration_seconds": round(sum(durations), 6),
                "mean_duration_seconds": (
                    round(sum(durations) / len(durations), 6) if durations else None
                ),
                "samples_per_video": dict(
                    sorted(Counter(row["sample_count"] for row in videos).items())
                ),
            }
        tasks[task_type] = {
            "sample_count": result["total_rows"],
            "source_video_count": result["total_videos"],
            "leaf_distribution": result["leaf_totals"],
            "assignment_score": result["assignment_score"],
            "splits": split_stats,
        }
    return {
        "schema_version": "vidhalloc_release_statistics_1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split_policy": {
            "ratios": dict(zip(SPLITS, RATIOS)),
            "grouping_unit": "source video",
            "stratification": "task_type + eight-leaf distribution",
            "seed": SEED,
        },
        "tasks": tasks,
    }


def cross_split_audit(
    task_results: dict[str, dict[str, Any]], inventory: list[dict[str, Any]]
) -> dict[str, Any]:
    pair_sets: dict[str, set[str]] = {split: set() for split in SPLITS}
    video_sets: dict[str, set[str]] = {split: set() for split in SPLITS}
    path_sets: dict[str, set[str]] = {split: set() for split in SPLITS}
    hash_sets: dict[str, set[str]] = {split: set() for split in SPLITS}
    for result in task_results.values():
        for split in SPLITS:
            pair_sets[split].update(row["pair_id"] for row in result["split_rows"][split])
            video_sets[split].update(result["split_videos"][split])
    for row in inventory:
        split = row["split"]
        path_sets[split].add(row["source_path"])
        hash_sets[split].add(row["sha256"])

    def overlaps(sets: dict[str, set[str]]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for left_index, left in enumerate(SPLITS):
            for right in SPLITS[left_index + 1 :]:
                result[f"{left}__{right}"] = sorted(sets[left] & sets[right])
        return result

    pair_overlaps = overlaps(pair_sets)
    video_overlaps = overlaps(video_sets)
    path_overlaps = overlaps(path_sets)
    hash_overlaps = overlaps(hash_sets)
    passed = not any(
        values
        for overlap_map in (
            pair_overlaps,
            video_overlaps,
            path_overlaps,
            hash_overlaps,
        )
        for values in overlap_map.values()
    )
    return {
        "schema_version": "vidhalloc_release_split_audit_1.0",
        "passed": passed,
        "pair_id_overlaps": pair_overlaps,
        "video_id_overlaps": video_overlaps,
        "source_path_overlaps": path_overlaps,
        "content_sha256_overlaps": hash_overlaps,
        "split_counts": {
            split: {
                "pair_ids": len(pair_sets[split]),
                "video_ids": len(video_sets[split]),
                "source_paths": len(path_sets[split]),
                "content_hashes": len(hash_sets[split]),
            }
            for split in SPLITS
        },
    }


def validate_source(rows: list[dict[str, Any]], status: dict[str, Any]) -> None:
    if status.get("state") != "completed_target":
        raise ValueError(f"Run is not completed_target: {status.get('state')}")
    if len(rows) != 2000 or status.get("total_pair_count") != 2000:
        raise ValueError(
            f"Expected exactly 2000 rows, found rows={len(rows)}, "
            f"status={status.get('total_pair_count')}"
        )
    pair_ids = [row["pair_id"] for row in rows]
    if len(pair_ids) != len(set(pair_ids)):
        raise ValueError("Duplicate pair_id values exist in source data")
    for row in rows:
        if row.get("leaf_label") not in LEAVES:
            raise ValueError(f"Unexpected leaf label: {row.get('leaf_label')}")
        if row.get("task_type") not in TASK_CONFIG:
            raise ValueError(f"Unexpected task type: {row.get('task_type')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute split assignments without hashing, linking, or writing files.",
    )
    args = parser.parse_args()

    rows = read_jsonl(SOURCE_ITEMS)
    status = read_json(SOURCE_STATUS)
    validate_source(rows, status)
    groups_by_task = build_groups(rows, status)
    task_results = {
        task_type: split_task(task_type, groups, SEED + index * 1000)
        for index, (task_type, groups) in enumerate(groups_by_task.items())
    }

    plan = {
        task_type: {
            "sample_count": result["total_rows"],
            "source_video_count": result["total_videos"],
            "split_sample_counts": {
                split: len(result["split_rows"][split]) for split in SPLITS
            },
            "split_video_counts": {
                split: len(result["split_videos"][split]) for split in SPLITS
            },
            "leaf_targets": result["leaf_targets"],
            "actual_leaf_matrix": result["actual_leaf_matrix"],
            "assignment_score": result["assignment_score"],
            "group_size_quotas": result["group_size_quotas"],
        }
        for task_type, result in task_results.items()
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    if RELEASE_ROOT.exists():
        raise FileExistsError(f"Release root already exists: {RELEASE_ROOT}")
    if STAGING_ROOT.exists():
        raise FileExistsError(f"Staging root already exists: {STAGING_ROOT}")

    datasets_root = STAGING_ROOT / "Datasets"
    original_root = datasets_root / "2000_Orign"
    original_root.mkdir(parents=True)
    shutil.copy2(SOURCE_ITEMS, original_root / "2000_Orign.jsonl")
    shutil.copy2(SOURCE_STATUS, original_root / "source_build_status.json")

    inventory: list[dict[str, Any]] = []
    hashes_to_video_ids: dict[str, list[str]] = defaultdict(list)
    link_modes = Counter()
    for task_type, result in task_results.items():
        config = TASK_CONFIG[task_type]
        task_dataset_root = datasets_root / config["dataset_dir"]
        all_task_rows = [
            row
            for row in rows
            if row["task_type"] == task_type
        ]
        write_jsonl(task_dataset_root / config["dataset_file"], all_task_rows)
        for split in SPLITS:
            write_jsonl(
                task_dataset_root / f"{split}.jsonl",
                result["split_rows"][split],
            )

        for group in groups_by_task[task_type]:
            split = result["assignment"][group.video_id]
            digest = sha256_file(group.source_path)
            hashes_to_video_ids[digest].append(group.video_id)
            metadata = video_metadata(group.source_path)
            destination = (
                STAGING_ROOT / config["video_dir"] / group.source_path.name
            )
            link_mode = create_hardlink_or_copy(group.source_path, destination)
            link_modes[link_mode] += 1
            inventory.append(
                {
                    "video_id": group.video_id,
                    "task_type": task_type,
                    "split": split,
                    "source_path": str(group.source_path),
                    "packaged_path": str(
                        Path(config["video_dir"]) / group.source_path.name
                    ),
                    "sha256": digest,
                    "sample_count": group.size,
                    "leaf_labels": ";".join(
                        row["leaf_label"] for row in group.rows
                    ),
                    "link_mode": link_mode,
                    **metadata,
                }
            )

    duplicate_hashes = {
        digest: sorted(video_ids)
        for digest, video_ids in hashes_to_video_ids.items()
        if len(video_ids) > 1
    }
    if duplicate_hashes:
        raise ValueError(
            "Duplicate source-video content detected; release not finalized: "
            + json.dumps(duplicate_hashes, ensure_ascii=False)
        )

    inventory.sort(key=lambda row: (row["task_type"], row["video_id"]))
    write_jsonl(datasets_root / "source_video_inventory.jsonl", inventory)
    write_csv(
        datasets_root / "source_video_inventory.csv",
        inventory,
        [
            "video_id",
            "task_type",
            "split",
            "source_path",
            "packaged_path",
            "sha256",
            "sample_count",
            "leaf_labels",
            "link_mode",
            "bytes",
            "duration_seconds",
            "width",
            "height",
            "fps",
            "frame_count",
        ],
    )

    statistics = summarize_release(task_results, inventory)
    statistics["packaging"] = {
        "release_root": str(RELEASE_ROOT),
        "video_file_count": len(inventory),
        "link_modes": dict(sorted(link_modes.items())),
        "unique_content_hash_count": len(hashes_to_video_ids),
    }
    write_json(datasets_root / "dataset_statistics.json", statistics)

    distribution_rows: list[dict[str, Any]] = []
    video_distribution_rows: list[dict[str, Any]] = []
    for task_type, task_stats in statistics["tasks"].items():
        for split in SPLITS:
            split_stats = task_stats["splits"][split]
            for leaf in LEAVES:
                distribution_rows.append(
                    {
                        "task_type": task_type,
                        "split": split,
                        "leaf_label": leaf,
                        "sample_count": split_stats["leaf_distribution"][leaf],
                    }
                )
            video_distribution_rows.append(
                {
                    "task_type": task_type,
                    "split": split,
                    "sample_count": split_stats["sample_count"],
                    "sample_share": split_stats["sample_share"],
                    "source_video_count": split_stats["source_video_count"],
                    "source_video_share": split_stats["source_video_share"],
                    "source_gib": split_stats["source_gib"],
                    "total_duration_seconds": split_stats["total_duration_seconds"],
                    "mean_duration_seconds": split_stats["mean_duration_seconds"],
                }
            )
    write_csv(
        datasets_root / "distribution_by_task_split_leaf.csv",
        distribution_rows,
        ["task_type", "split", "leaf_label", "sample_count"],
    )
    write_csv(
        datasets_root / "source_video_distribution.csv",
        video_distribution_rows,
        [
            "task_type",
            "split",
            "sample_count",
            "sample_share",
            "source_video_count",
            "source_video_share",
            "source_gib",
            "total_duration_seconds",
            "mean_duration_seconds",
        ],
    )

    audit = cross_split_audit(task_results, inventory)
    if not audit["passed"]:
        raise ValueError("Cross-split leakage audit failed")
    audit["source_dataset_sha256"] = sha256_file(SOURCE_ITEMS)
    audit["packaged_original_sha256"] = sha256_file(
        original_root / "2000_Orign.jsonl"
    )
    audit["all_source_videos_content_unique"] = len(hashes_to_video_ids) == len(inventory)
    write_json(datasets_root / "split_integrity_audit.json", audit)

    split_manifest = {
        "schema_version": "vidhalloc_release_split_manifest_1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "policy": {
            "sample_ratio": dict(zip(SPLITS, RATIOS)),
            "group_by_source_video": True,
            "content_hash_leakage_check": True,
            "pair_id_leakage_check": True,
            "leaf_stratification": True,
        },
        "tasks": {
            task_type: {
                "assignment_score": result["assignment_score"],
                "video_to_split": dict(sorted(result["assignment"].items())),
            }
            for task_type, result in task_results.items()
        },
    }
    write_json(datasets_root / "split_manifest.json", split_manifest)

    readme = f"""VidHalLoc 2K release
=====================

Completed samples: 2000
VideoQA samples: 1020
Video Captioning samples: 980
Source videos contributing accepted samples: {len(inventory)}

Directory layout
----------------
videoqa/                 VideoQA source videos
video caption/           Video-captioning source videos
Datasets/2000_Orign/     Exact completed 2000-sample source dataset
Datasets/Videoqa_set/    Full VideoQA set and Main/Eval/Test splits
Datasets/Video_caption_set/ Full captioning set and Main/Eval/Test splits

Split policy
------------
Main/Eval/Test use a 60/20/20 sample ratio inside each task.  All samples from
the same source video remain in one split.  Pair IDs, video IDs, source paths,
and video-content SHA-256 hashes are checked for zero cross-split overlap.

See Datasets/dataset_statistics.json and Datasets/split_integrity_audit.json.
"""
    (STAGING_ROOT / "README.txt").write_text(readme, encoding="utf-8")
    write_json(STAGING_ROOT / "release_plan.json", plan)

    STAGING_ROOT.rename(RELEASE_ROOT)
    print(
        json.dumps(
            {
                "release_root": str(RELEASE_ROOT),
                "statistics": statistics,
                "audit": audit,
                "plan": plan,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
