"""Build a provisional 35%-dynamic VidHalLoc selection without overwriting it.

The replacement plan keeps 2,600 total videos and 1,300 videos per task.
For each task it adds 180 persistent-cut candidates and 120 global-camera-
motion candidates from the unused, clean-room VidOR-origin pool.  It removes
300 low-change Perception Test videos and greedily pairs each replacement by
orientation, aspect ratio, duration, pixel count, and file size.
"""
from __future__ import annotations

import concurrent.futures
import csv
import json
import math
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_SELECTION = ROOT / "VidHalLoc.json"
FINAL_MANIFEST = (
    ROOT / "video_dataset_staging" / "final_10000" / "final_manifest.csv"
)
SCREEN = (
    ROOT
    / "VidHalLoc_2600_build"
    / "dynamic_candidate_pool_screen.jsonl"
)
OUTPUT = ROOT / "VidHalLoc_dynamic35_provisional.json"
BUILD_ROOT = ROOT / "VidHalLoc_dynamic35_build"
BUILD_INPUT = BUILD_ROOT / "input_2600.jsonl"
PAIR_OUTPUT = BUILD_ROOT / "replacement_pairs.jsonl"
SUMMARY_OUTPUT = BUILD_ROOT / "selection_summary.json"
FFPROBE = (
    ROOT
    / "video_dataset_staging"
    / "tools"
    / "ffmpeg"
    / "ffmpeg-8.1.2-essentials_build"
    / "bin"
    / "ffprobe.exe"
)

TASKS = ("video_captioning", "video_qa")
CUTS_PER_TASK = 180
MOTION_PER_TASK = 120
REMOVE_PER_TASK = CUTS_PER_TASK + MOTION_PER_TASK
REMOVAL_POOL_PER_TASK = 450
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


def max_adjacent_phash_distance(serialized: str) -> int:
    hashes = [int(value, 16) for value in serialized.split(";") if value]
    if len(hashes) < 2:
        return 0
    return max(
        bin(left ^ right).count("1")
        for left, right in zip(hashes, hashes[1:])
    )


def probe_media(path: str) -> dict:
    completed = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            completed.stderr.decode("utf-8", errors="replace")
        )
    document = json.loads(completed.stdout.decode("utf-8"))
    video_streams = [
        stream
        for stream in document.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    audio_streams = [
        stream
        for stream in document.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    if not video_streams:
        raise RuntimeError("No video stream")
    stream = video_streams[0]
    width = int(stream["width"])
    height = int(stream["height"])
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid video dimensions")
    return {
        "width": width,
        "height": height,
        "pixel_count": width * height,
        "aspect_ratio": width / height,
        "orientation": (
            "landscape"
            if width > height
            else "portrait"
            if height > width
            else "square"
        ),
        "audio_stream_count": len(audio_streams),
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def candidate_rank(row: dict, candidate_type: str) -> tuple:
    if candidate_type == "cut":
        return (
            -min(int(row["persistent_cut_count"]), 4),
            -int(row["strong_global_motion_pair_count"]),
            -int(row["robust_global_motion_pair_count"]),
            -int(row["maximum_pair_phash_distance"]),
            -int(row["max_adjacent_phash_distance"]),
            row["video_id"],
        )
    return (
        -int(row["strong_global_motion_pair_count"]),
        -int(row["robust_global_motion_pair_count"]),
        -float(row["maximum_corner_displacement"]),
        -int(row["maximum_pair_phash_distance"]),
        -int(row["max_adjacent_phash_distance"]),
        row["video_id"],
    )


def match_cost(candidate: dict, removal: dict) -> float:
    candidate_media = candidate["media"]
    removal_media = removal["media"]
    orientation_penalty = (
        0.0
        if candidate_media["orientation"] == removal_media["orientation"]
        else 10.0
    )
    aspect_penalty = abs(
        math.log(
            candidate_media["aspect_ratio"]
            / removal_media["aspect_ratio"]
        )
    )
    duration_penalty = abs(
        math.log(
            max(0.25, float(candidate["duration_seconds"]))
            / max(0.25, float(removal["duration_seconds"]))
        )
    )
    pixel_penalty = abs(
        math.log(
            candidate_media["pixel_count"]
            / removal_media["pixel_count"]
        )
    )
    byte_penalty = abs(
        math.log(
            max(1, int(candidate["bytes"]))
            / max(1, int(removal["bytes"]))
        )
    )
    return (
        orientation_penalty
        + 3.0 * aspect_penalty
        + 1.5 * duration_penalty
        + 0.35 * pixel_penalty
        + 0.20 * byte_penalty
    )


def main() -> int:
    current_document = json.loads(
        CURRENT_SELECTION.read_text(encoding="utf-8-sig")
    )
    current = list(current_document["videos"])
    screened = read_jsonl(SCREEN)
    with FINAL_MANIFEST.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        manifest_rows = list(csv.DictReader(handle))
    manifest_by_hash = {row["sha256"]: row for row in manifest_rows}

    current_ids = {row["video_id"] for row in current}
    current_hashes = {row["sha256"] for row in current}
    current_paths = {
        str(Path(row["source_path"]).resolve()).casefold()
        for row in current
    }
    selected_additions: list[dict] = []
    for task in TASKS:
        eligible = [
            row
            for row in screened
            if row["task_type"] == task
            and row["camera_dynamic_candidate"]
            and row["video_id"] not in current_ids
            and row["sha256"] not in current_hashes
            and str(Path(row["source_path"]).resolve()).casefold()
            not in current_paths
        ]
        cuts = sorted(
            (
                row
                for row in eligible
                if int(row["persistent_cut_count"]) > 0
            ),
            key=lambda row: candidate_rank(row, "cut"),
        )
        motions = sorted(
            (
                row
                for row in eligible
                if int(row["persistent_cut_count"]) == 0
                and (
                    int(row["robust_global_motion_pair_count"]) >= 2
                    or int(row["strong_global_motion_pair_count"]) >= 1
                )
            ),
            key=lambda row: candidate_rank(row, "motion"),
        )
        if len(cuts) < CUTS_PER_TASK or len(motions) < MOTION_PER_TASK:
            raise RuntimeError(
                f"Insufficient {task}: cuts={len(cuts)}, "
                f"motions={len(motions)}"
            )
        for row in cuts[:CUTS_PER_TASK]:
            row["replacement_camera_stratum"] = "persistent_cut"
            selected_additions.append(row)
        for row in motions[:MOTION_PER_TASK]:
            row["replacement_camera_stratum"] = (
                "global_camera_motion"
            )
            selected_additions.append(row)

    removal_pools: dict[str, list[dict]] = {}
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
                row["duration_seconds"],
                row["video_id"],
            )
        )
        if len(rows) < REMOVAL_POOL_PER_TASK:
            raise RuntimeError(
                f"Insufficient removal pool for {task}: {len(rows)}"
            )
        removal_pools[task] = rows[:REMOVAL_POOL_PER_TASK]

    probe_rows = [
        *selected_additions,
        *[
            row
            for task_rows in removal_pools.values()
            for row in task_rows
        ],
    ]
    media_by_path: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=16
    ) as executor:
        futures = {
            executor.submit(probe_media, row["source_path"]): row
            for row in probe_rows
        }
        for completed, future in enumerate(
            concurrent.futures.as_completed(futures), 1
        ):
            row = futures[future]
            media_by_path[row["source_path"]] = future.result()
            if completed % 250 == 0 or completed == len(futures):
                print(
                    json.dumps(
                        {
                            "event": "media_probe_progress",
                            "completed": completed,
                            "total": len(futures),
                        }
                    ),
                    flush=True,
                )
    for row in probe_rows:
        row["media"] = media_by_path[row["source_path"]]
        if row["media"]["audio_stream_count"] < 1:
            raise RuntimeError(
                f"Replacement media lacks audio: {row['source_path']}"
            )

    current_max_duration = max(
        float(row["duration_seconds"]) for row in current
    )
    current_max_bytes = max(int(row["bytes"]) for row in current)
    current_media = [
        row["media"]
        for task_rows in removal_pools.values()
        for row in task_rows
    ]
    current_max_pixels = max(
        media["pixel_count"] for media in current_media
    )
    for row in selected_additions:
        if float(row["duration_seconds"]) > current_max_duration:
            raise RuntimeError("Candidate exceeds current duration cap")
        if int(row["bytes"]) > current_max_bytes:
            raise RuntimeError("Candidate exceeds current file-size cap")
        if row["media"]["pixel_count"] > current_max_pixels:
            raise RuntimeError(
                "Candidate exceeds probed current resolution cap"
            )

    replacement_pairs: list[dict] = []
    selected_removals: list[dict] = []
    for task in TASKS:
        available = list(removal_pools[task])
        additions = [
            row
            for row in selected_additions
            if row["task_type"] == task
        ]
        additions.sort(
            key=lambda row: (
                row["replacement_camera_stratum"],
                candidate_rank(
                    row,
                    (
                        "cut"
                        if row["replacement_camera_stratum"]
                        == "persistent_cut"
                        else "motion"
                    ),
                ),
            )
        )
        for addition in additions:
            best = min(
                available,
                key=lambda removal: (
                    match_cost(addition, removal),
                    removal["max_adjacent_phash_distance"],
                    removal["video_id"],
                ),
            )
            available.remove(best)
            selected_removals.append(best)
            replacement_pairs.append(
                {
                    "task_type": task,
                    "camera_stratum": addition[
                        "replacement_camera_stratum"
                    ],
                    "removed_video_id": best["video_id"],
                    "removed_source_path": best["source_path"],
                    "removed_sha256": best["sha256"],
                    "removed_allocation_group": best[
                        "allocation_group"
                    ],
                    "removed_duration_seconds": best[
                        "duration_seconds"
                    ],
                    "removed_bytes": best["bytes"],
                    "removed_max_adjacent_phash_distance": best[
                        "max_adjacent_phash_distance"
                    ],
                    "removed_media": best["media"],
                    "added_video_id": addition["video_id"],
                    "added_source_path": addition["source_path"],
                    "added_sha256": addition["sha256"],
                    "added_allocation_group": addition[
                        "allocation_group"
                    ],
                    "added_duration_seconds": addition[
                        "duration_seconds"
                    ],
                    "added_bytes": addition["bytes"],
                    "added_max_adjacent_phash_distance": addition[
                        "max_adjacent_phash_distance"
                    ],
                    "added_media": addition["media"],
                    "match_cost": round(
                        match_cost(addition, best), 8
                    ),
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

    removal_ids = {row["video_id"] for row in selected_removals}
    retained = [
        row for row in current if row["video_id"] not in removal_ids
    ]
    additions_for_selection = []
    for row in selected_additions:
        additions_for_selection.append(
            {
                "video_id": row["video_id"],
                "source_path": row["source_path"],
                "task_type": row["task_type"],
                "source_pool": "final_10000",
                "source_dataset": row["source_dataset"],
                "allocation_group": row["allocation_group"],
                "source_video_id": row["source_video_id"],
                "duration_seconds": row["duration_seconds"],
                "audio_mean_db": row["audio_mean_db"],
                "audio_peak_db": row["audio_peak_db"],
                "sha256": row["sha256"],
                "bytes": row["bytes"],
                "nextqa_questions": 0,
                "camera_source_evidence": {
                    "stratum": row[
                        "replacement_camera_stratum"
                    ],
                    "persistent_cut_count": row[
                        "persistent_cut_count"
                    ],
                    "robust_global_motion_pair_count": row[
                        "robust_global_motion_pair_count"
                    ],
                    "strong_global_motion_pair_count": row[
                        "strong_global_motion_pair_count"
                    ],
                    "maximum_corner_displacement": row[
                        "maximum_corner_displacement"
                    ],
                    "screen_schema": row["screen_schema"],
                },
            }
        )
    combined = retained + additions_for_selection
    by_task = {
        task: sorted(
            (row for row in combined if row["task_type"] == task),
            key=lambda row: row["video_id"],
        )
        for task in TASKS
    }
    if any(len(rows) != 1300 for rows in by_task.values()):
        raise RuntimeError("Task count changed during replacement")
    final_rows = [
        by_task[task][index]
        for index in range(1300)
        for task in TASKS
    ]
    for sequence, row in enumerate(final_rows, 1):
        row["sequence"] = sequence

    if len(final_rows) != 2600:
        raise RuntimeError("Final selection count is not 2,600")
    if len({row["video_id"] for row in final_rows}) != 2600:
        raise RuntimeError("Duplicate final video_id")
    if len({row["sha256"] for row in final_rows}) != 2600:
        raise RuntimeError("Duplicate final content hash")

    summary = {
        "schema_version": "videohalo_vidhalloc_dynamic35_summary_1.0",
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
        "final_by_task": dict(
            Counter(row["task_type"] for row in final_rows)
        ),
        "final_by_allocation_group": dict(
            Counter(row["allocation_group"] for row in final_rows)
        ),
        "final_by_source_dataset": dict(
            Counter(row["source_dataset"] for row in final_rows)
        ),
        "unique_video_ids": len(
            {row["video_id"] for row in final_rows}
        ),
        "unique_sha256": len(
            {row["sha256"] for row in final_rows}
        ),
        "media_caps": {
            "maximum_duration_seconds": current_max_duration,
            "maximum_bytes": current_max_bytes,
            "maximum_probed_pixel_count": current_max_pixels,
            "all_additions_have_audio": True,
            "all_additions_within_caps": True,
        },
        "match_cost": {
            "mean": sum(
                pair["match_cost"] for pair in replacement_pairs
            )
            / len(replacement_pairs),
            "maximum": max(
                pair["match_cost"] for pair in replacement_pairs
            ),
        },
        "current_selection_overwritten": False,
        "model_smoke_started": False,
    }
    document = {
        "schema_version": "videohalo_vidhalloc_selection_3.7.1",
        "selection_id": (
            "VidHalLoc_2600_dynamic35_provisional_pending_human_audit"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_selection": str(CURRENT_SELECTION),
        "status": "provisional_pending_human_camera_audit",
        "policy": {
            **current_document["policy"],
            "camera_source_target_ratio": 0.35,
            "camera_source_replacement_count": 600,
            "camera_source_replacement_per_task": 300,
            "camera_source_strata_per_task": {
                "persistent_cut": CUTS_PER_TASK,
                "global_camera_motion": MOTION_PER_TASK,
            },
            "replacement_is_one_to_one": True,
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
            json.dumps(pair, ensure_ascii=False) + "\n"
            for pair in replacement_pairs
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
