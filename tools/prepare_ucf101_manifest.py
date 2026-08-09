"""Inventory extracted UCF101 clips for VideoHALO dynamic-source screening."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_ROOT = (
    ROOT / "video_dataset_staging" / "UCF-101"
)
OUTPUT_ROOT = (
    ROOT / "video_dataset_staging" / "ucf101_videohalo"
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
FILENAME_RE = re.compile(
    r"^v_(?P<label>.+)_g(?P<group>\d+)_c(?P<clip>\d+)$"
)


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
    return {
        "source_path": str(path.resolve()),
        "duration_seconds": float(document["format"]["duration"]),
        "bytes": int(
            document["format"].get("size") or path.stat().st_size
        ),
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


def prior_probe_hashes() -> set[str]:
    hashes: set[str] = set()
    for manifest in PRIOR_MANIFESTS:
        for line in manifest.read_text(
            encoding="utf-8-sig"
        ).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            hashes.add(str(row["source_asset"]["sha256"]))
    full11 = json.loads(
        PRIOR_SOURCE_SELECTION.read_text(encoding="utf-8-sig")
    )
    hashes.update(str(row["sha256"]) for row in full11["videos"])
    return hashes


def locate_extract_root() -> Path:
    if EXTRACTED_ROOT.exists():
        return EXTRACTED_ROOT
    staging = ROOT / "video_dataset_staging"
    candidates = [
        path
        for path in staging.iterdir()
        if path.is_dir()
        and path.name.casefold() in {"ucf101", "ucf-101"}
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(
        f"Cannot locate extracted UCF101 root: {candidates}"
    )


def main() -> int:
    extract_root = locate_extract_root()
    files = sorted(extract_root.rglob("*.avi"))
    if not files:
        raise RuntimeError("No extracted UCF101 AVI videos found")

    current = json.loads(
        CURRENT_SELECTION.read_text(encoding="utf-8-sig")
    )["videos"]
    duration_cap = max(
        float(row["duration_seconds"]) for row in current
    )
    byte_cap = max(int(row["bytes"]) for row in current)
    pixel_cap = 1920 * 1080
    current_hashes = {row["sha256"] for row in current}
    prior_hashes = prior_probe_hashes()

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
            if completed % 1000 == 0 or completed == len(futures):
                print(
                    json.dumps(
                        {
                            "event": "ucf101_probe_progress",
                            "completed": completed,
                            "total": len(futures),
                        }
                    ),
                    flush=True,
                )

    rows = []
    filename_errors = []
    for path, media in probes:
        match = FILENAME_RE.match(path.stem)
        if not match:
            filename_errors.append(path.name)
            continue
        label = match.group("label")
        group = int(match.group("group"))
        clip = int(match.group("clip"))
        row = {
            "video_id": "ucf101_" + path.stem.casefold(),
            "task_type": "unassigned",
            "source_dataset": "UCF101",
            "allocation_group": "external_ucf101",
            "source_parent_video_id": (
                f"UCF101::{label}::g{group:02d}"
            ),
            "source_label": label,
            "source_group": group,
            "source_clip": clip,
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
            row["overlap_with_prior_probe_sha256"] = (
                row["sha256"] in prior_hashes
            )
            row["eligible_for_camera_screen"] = (
                row["audio_stream_count"] >= 1
                and row["within_caps"]
                and not row["overlap_with_current_sha256"]
                and not row["overlap_with_prior_probe_sha256"]
            )
        else:
            row["within_caps"] = False
            row["overlap_with_current_sha256"] = False
            row["overlap_with_prior_probe_sha256"] = False
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
        "schema_version": "videohalo_ucf101_media_summary_1.0",
        "extract_root": str(extract_root.resolve()),
        "total_video_files": len(rows),
        "filename_parse_errors": filename_errors,
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
            }
        ),
        "eligible_unique_parent_video_ids": len(
            {
                row["source_parent_video_id"]
                for row in eligible
            }
        ),
        "overlap_with_current_sha256": sum(
            row["overlap_with_current_sha256"] for row in rows
        ),
        "overlap_with_prior_probe_sha256": sum(
            row["overlap_with_prior_probe_sha256"] for row in rows
        ),
        "by_label": dict(
            Counter(row["source_label"] for row in eligible)
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
