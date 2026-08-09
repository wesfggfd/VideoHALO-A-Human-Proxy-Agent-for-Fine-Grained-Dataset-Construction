"""Inventory extracted UCF101-DS clips for VideoHALO source screening."""
from __future__ import annotations

import concurrent.futures
import csv
import gzip
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_ROOT = (
    ROOT / "video_dataset_staging" / "UCF101-DS"
)
ANNOTATIONS = (
    ROOT
    / "video_dataset_staging"
    / "ucf101-DS_eval.csv.gz"
)
OUTPUT_ROOT = (
    ROOT
    / "video_dataset_staging"
    / "ucf101ds_videohalo"
)
INVENTORY = OUTPUT_ROOT / "media_inventory.jsonl"
ELIGIBLE = OUTPUT_ROOT / "eligible_audio_within_caps.jsonl"
SUMMARY = OUTPUT_ROOT / "media_summary.json"
FFPROBE = (
    ROOT
    / "video_dataset_staging"
    / "tools"
    / "ffmpeg"
    / "ffmpeg-8.1.2-essentials_build"
    / "bin"
    / "ffprobe.exe"
)
CURRENT_SELECTION = ROOT / "VidHalLoc.json"
VIDEO_SUFFIXES = {".mp4", ".avi", ".mkv", ".mov", ".webm"}


def read_annotations() -> dict[tuple[str, str], dict]:
    with gzip.open(
        ANNOTATIONS, "rt", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    return {
        (row["label"], row["filename"]): row
        for row in rows
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    completed = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,size:"
                "stream=codec_type,width,height,codec_name"
            ),
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        return {
            "source_path": str(path.resolve()),
            "probe_error": completed.stderr.decode(
                "utf-8", errors="replace"
            ),
        }
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
        return {
            "source_path": str(path.resolve()),
            "probe_error": "No video stream",
        }
    video = video_streams[0]
    width = int(video["width"])
    height = int(video["height"])
    duration = float(document["format"]["duration"])
    size = int(document["format"].get("size") or path.stat().st_size)
    return {
        "source_path": str(path.resolve()),
        "duration_seconds": duration,
        "bytes": size,
        "width": width,
        "height": height,
        "pixel_count": width * height,
        "video_codec": video.get("codec_name"),
        "audio_stream_count": len(audio_streams),
        "audio_codecs": [
            stream.get("codec_name") for stream in audio_streams
        ],
        "sha256": sha256_file(path),
        "probe_error": None,
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def locate_extract_root() -> Path:
    if EXTRACTED_ROOT.exists():
        return EXTRACTED_ROOT
    candidates = [
        path
        for path in (
            ROOT / "video_dataset_staging"
        ).iterdir()
        if path.is_dir()
        and path.name.casefold().startswith("ucf101-ds")
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(
        f"Cannot locate extracted UCF101-DS root: {candidates}"
    )


def main() -> int:
    extract_root = locate_extract_root()
    annotations = read_annotations()
    files = sorted(
        path
        for path in extract_root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )
    if not files:
        raise RuntimeError("No extracted UCF101-DS videos found")

    current = json.loads(
        CURRENT_SELECTION.read_text(encoding="utf-8-sig")
    )["videos"]
    duration_cap = max(
        float(row["duration_seconds"]) for row in current
    )
    byte_cap = max(int(row["bytes"]) for row in current)
    pixel_cap = 1920 * 1080
    current_hashes = {row["sha256"] for row in current}

    probes = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=16
    ) as executor:
        futures = {
            executor.submit(probe, path): path for path in files
        }
        for completed, future in enumerate(
            concurrent.futures.as_completed(futures), 1
        ):
            probes.append((futures[future], future.result()))
            if completed % 500 == 0 or completed == len(futures):
                print(
                    json.dumps(
                        {
                            "event": "ucf101ds_probe_progress",
                            "completed": completed,
                            "total": len(futures),
                        }
                    ),
                    flush=True,
                )

    rows = []
    for path, media in probes:
        label = path.parent.name
        annotation = annotations.get((label, path.name), {})
        parent_video_id = annotation.get("video_id", "")
        row = {
            "video_id": (
                "ucf101ds_"
                + label.casefold()
                + "_"
                + path.stem.casefold()
            ),
            "task_type": "unassigned",
            "source_dataset": "UCF101-DS",
            "allocation_group": "external_ucf101ds",
            "source_parent_video_id": parent_video_id,
            "source_label": label,
            "source_shift": annotation.get("shift", ""),
            "source_shift_category": annotation.get("category", ""),
            **media,
        }
        if not row["probe_error"]:
            row["within_caps"] = (
                row["duration_seconds"] <= duration_cap
                and row["bytes"] <= byte_cap
                and row["pixel_count"] <= pixel_cap
            )
            row["overlap_with_current_sha256"] = (
                row["sha256"] in current_hashes
            )
            row["eligible_for_camera_screen"] = (
                row["audio_stream_count"] >= 1
                and row["within_caps"]
                and not row["overlap_with_current_sha256"]
            )
        else:
            row["within_caps"] = False
            row["overlap_with_current_sha256"] = False
            row["eligible_for_camera_screen"] = False
        rows.append(row)
    rows.sort(key=lambda row: row["video_id"])
    eligible = [
        row for row in rows if row["eligible_for_camera_screen"]
    ]

    atomic_write(
        INVENTORY,
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in rows
        ),
    )
    atomic_write(
        ELIGIBLE,
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in eligible
        ),
    )
    summary = {
        "schema_version": "videohalo_ucf101ds_media_summary_1.0",
        "extract_root": str(extract_root.resolve()),
        "total_video_files": len(rows),
        "probe_errors": sum(bool(row["probe_error"]) for row in rows),
        "with_audio": sum(
            not row["probe_error"]
            and row["audio_stream_count"] >= 1
            for row in rows
        ),
        "within_caps": sum(row["within_caps"] for row in rows),
        "eligible_for_camera_screen": len(eligible),
        "unique_sha256": len(
            {
                row["sha256"]
                for row in rows
                if not row["probe_error"]
            }
        ),
        "unique_parent_video_ids": len(
            {
                row["source_parent_video_id"]
                for row in rows
                if row["source_parent_video_id"]
            }
        ),
        "by_label": dict(
            Counter(row["source_label"] for row in eligible)
        ),
        "by_shift_category": dict(
            Counter(
                row["source_shift_category"] for row in eligible
            )
        ),
        "caps": {
            "duration_seconds": duration_cap,
            "bytes": byte_cap,
            "pixel_count": pixel_cap,
        },
    }
    atomic_write(
        SUMMARY,
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
