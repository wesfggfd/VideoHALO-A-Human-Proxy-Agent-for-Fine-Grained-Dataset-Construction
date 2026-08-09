"""Normalize the frozen VidHalLoc corpus into readable task-local video IDs."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_LAYOUT = {
    "video_captioning": ("captioning", "captioning"),
    "video_qa": ("videoqa", "videoqa"),
}

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def remux_to_mp4(source: Path, destination: Path, ffmpeg: Path) -> None:
    completed = subprocess.run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"ffmpeg remux failed for {source}: {completed.stderr[-2000:]}"
        )


def probe_media(path: Path, ffprobe: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"ffprobe failed for {path}: {completed.stderr[-2000:]}"
        )
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    audio_streams = [
        stream for stream in streams if stream.get("codec_type") == "audio"
    ]
    if not video_stream:
        raise RuntimeError(f"No video stream after normalization: {path}")
    format_info = payload.get("format") or {}
    return {
        "format_name": str(format_info.get("format_name") or ""),
        "duration_seconds": float(format_info.get("duration") or 0.0),
        "bytes": int(format_info.get("size") or path.stat().st_size),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "audio_stream_count": len(audio_streams),
    }


def normalize(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve()
    input_path = args.input_jsonl.resolve()
    target_root = args.target_root.resolve()
    staging_root = target_root.with_name(target_root.name + ".building")
    backup_manifest = manifest_path.with_name(
        "VidHalLoc_pre_readable_ids_20260730.json"
    )
    backup_input = input_path.with_name(
        "input_2600_pre_readable_ids_20260730.jsonl"
    )

    for forbidden in (target_root, staging_root, backup_manifest, backup_input):
        if forbidden.exists():
            raise FileExistsError(f"Refusing to overwrite existing path: {forbidden}")
    if not args.ffmpeg.is_file() or not args.ffprobe.is_file():
        raise FileNotFoundError("ffmpeg/ffprobe executable is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_records = sorted(
        (copy.deepcopy(record) for record in manifest["videos"]),
        key=lambda record: (int(record["sequence"]), str(record["video_id"])),
    )
    if len(source_records) != 2600:
        raise ValueError(f"Expected 2600 records, found {len(source_records)}")
    if len({record["video_id"] for record in source_records}) != 2600:
        raise ValueError("Source video IDs are not unique")
    if len({record["sha256"] for record in source_records}) != 2600:
        raise ValueError("Source SHA-256 values are not unique")

    staging_root.mkdir(parents=True)
    for directory, _prefix in TASK_LAYOUT.values():
        (staging_root / directory).mkdir()

    task_counters: Counter[str] = Counter()
    normalized_records: list[dict[str, Any]] = []
    build_inputs: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    method_counts: Counter[str] = Counter()

    try:
        for source_record in source_records:
            task_type = str(source_record["task_type"])
            if task_type not in TASK_LAYOUT:
                raise ValueError(f"Unexpected task_type: {task_type}")
            task_counters[task_type] += 1
            task_index = task_counters[task_type]
            directory, prefix = TASK_LAYOUT[task_type]
            new_video_id = f"{prefix}_{task_index:04d}"
            source = Path(source_record["source_path"]).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)

            staged_destination = staging_root / directory / f"{new_video_id}.mp4"
            final_destination = target_root / directory / f"{new_video_id}.mp4"
            original_sha256 = str(source_record["sha256"])

            if source.suffix.lower() == ".mp4":
                try:
                    os.link(source, staged_destination)
                    method = "ntfs_hardlink"
                except OSError:
                    shutil.copy2(source, staged_destination)
                    method = "byte_copy_fallback"
                normalized_sha256 = original_sha256
                media_info = {
                    "format_name": "mp4",
                    "duration_seconds": float(
                        source_record["duration_seconds"]
                    ),
                    "bytes": staged_destination.stat().st_size,
                    "width": source_record.get("width"),
                    "height": source_record.get("height"),
                    "audio_stream_count": source_record.get(
                        "audio_stream_count"
                    ),
                }
            else:
                remux_to_mp4(source, staged_destination, args.ffmpeg)
                method = "stream_copy_remux_to_mp4"
                normalized_sha256 = sha256_file(staged_destination)
                media_info = probe_media(staged_destination, args.ffprobe)
            if "mp4" not in media_info["format_name"]:
                raise ValueError(
                    f"Normalized file is not MP4: {staged_destination} "
                    f"({media_info['format_name']})"
                )
            if (
                media_info["audio_stream_count"] is not None
                and int(media_info["audio_stream_count"]) < 1
            ):
                raise ValueError(f"Normalized file lacks audio: {staged_destination}")

            record = copy.deepcopy(source_record)
            record["video_id"] = new_video_id
            record["source_path"] = str(final_destination)
            record["original_video_id"] = str(source_record["video_id"])
            record["original_source_path"] = str(source)
            record["original_sha256"] = original_sha256
            record["normalization_method"] = method
            record["task_sequence"] = task_index
            record["sha256"] = normalized_sha256
            record["bytes"] = media_info["bytes"]
            record["duration_seconds"] = media_info["duration_seconds"]
            if media_info["width"] is not None:
                record["width"] = int(media_info["width"])
            if media_info["height"] is not None:
                record["height"] = int(media_info["height"])
            if media_info["audio_stream_count"] is not None:
                record["audio_stream_count"] = int(
                    media_info["audio_stream_count"]
                )
            normalized_records.append(record)

            build_inputs.append(
                {
                    "video_id": new_video_id,
                    "source_path": str(final_destination),
                    "task_type": task_type,
                    "sequence": int(source_record["sequence"]),
                }
            )
            mapping_rows.append(
                {
                    "sequence": int(source_record["sequence"]),
                    "task_type": task_type,
                    "task_sequence": task_index,
                    "new_video_id": new_video_id,
                    "new_source_path": str(final_destination),
                    "original_video_id": str(source_record["video_id"]),
                    "original_source_path": str(source),
                    "source_dataset": str(source_record.get("source_dataset") or ""),
                    "original_sha256": original_sha256,
                    "normalized_sha256": normalized_sha256,
                    "normalization_method": method,
                }
            )
            method_counts[method] += 1

        if task_counters != Counter(
            {"video_captioning": 1300, "video_qa": 1300}
        ):
            raise ValueError(f"Unexpected task counts: {dict(task_counters)}")
        if len({record["video_id"] for record in normalized_records}) != 2600:
            raise ValueError("Normalized video IDs are not unique")
        if len({record["sha256"] for record in normalized_records}) != 2600:
            raise ValueError("Normalized SHA-256 values are not unique")
        if len(list(staging_root.rglob("*.mp4"))) != 2600:
            raise ValueError("Normalized directory does not contain 2600 MP4 files")

        normalized_at = datetime.now(timezone.utc).isoformat()
        normalized_manifest = copy.deepcopy(manifest)
        normalized_manifest["selection_id"] = "VidHalLoc_2600_readable_ids_v1"
        normalized_manifest["videos"] = normalized_records
        normalized_manifest["frozen_at"] = normalized_at
        normalized_manifest["normalization"] = {
            "schema_version": "videohalo_readable_video_ids_1.0",
            "normalized_at": normalized_at,
            "target_root": str(target_root),
            "captioning_pattern": "captioning_0001.mp4..captioning_1300.mp4",
            "videoqa_pattern": "videoqa_0001.mp4..videoqa_1300.mp4",
            "ordering": "original frozen global sequence, numbered within task",
            "source_assets_mutated": False,
            "method_counts": dict(sorted(method_counts.items())),
            "mapping_jsonl": str(target_root / "video_id_mapping.jsonl"),
            "mapping_csv": str(target_root / "video_id_mapping.csv"),
            "backup_manifest": str(backup_manifest),
            "backup_build_input": str(backup_input),
        }
        normalized_manifest.setdefault("selection_summary", {})[
            "unique_video_ids"
        ] = 2600
        normalized_manifest["selection_summary"]["unique_sha256"] = 2600
        normalized_manifest.setdefault("policy", {})[
            "readable_video_id_patterns"
        ] = {
            "video_captioning": "captioning_####",
            "video_qa": "videoqa_####",
        }
        normalized_manifest["policy"][
            "original_identity_preserved_in"
        ] = ["original_video_id", "original_source_path", "original_sha256"]
        normalized_manifest.setdefault("runtime", {})[
            "normalized_video_root"
        ] = str(target_root)

        write_jsonl(staging_root / "video_id_mapping.jsonl", mapping_rows)
        with (staging_root / "video_id_mapping.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(mapping_rows[0]))
            writer.writeheader()
            writer.writerows(mapping_rows)

        report = {
            "schema_version": "videohalo_readable_video_ids_report_1.0",
            "status": "PASS",
            "normalized_at": normalized_at,
            "total": len(normalized_records),
            "by_task": dict(sorted(task_counters.items())),
            "method_counts": dict(sorted(method_counts.items())),
            "unique_video_ids": len(
                {record["video_id"] for record in normalized_records}
            ),
            "unique_normalized_sha256": len(
                {record["sha256"] for record in normalized_records}
            ),
            "all_mp4": True,
            "all_have_audio": all(
                int(
                    record.get("audio_stream_count")
                    or (1 if record.get("audio_mean_db") is not None else 0)
                )
                > 0
                for record in normalized_records
            ),
            "source_assets_mutated": False,
        }
        write_json(staging_root / "normalization_report.json", report)

        staged_manifest = manifest_path.with_suffix(".json.readable_ids_new")
        staged_input = input_path.with_suffix(".jsonl.readable_ids_new")
        write_json(staged_manifest, normalized_manifest)
        write_jsonl(staged_input, build_inputs)

        staging_root.replace(target_root)
        shutil.copy2(manifest_path, backup_manifest)
        shutil.copy2(input_path, backup_input)
        os.replace(staged_manifest, manifest_path)
        os.replace(staged_input, input_path)
        return report
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "VidHalLoc.json"
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=ROOT / "VidHalLoc_2600_build" / "input_2600.jsonl",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=ROOT / "data" / "VidHalLoc_2600_clean",
    )
    parser.add_argument(
        "--ffmpeg",
        type=Path,
        default=Path("ffmpeg"),
    )
    parser.add_argument(
        "--ffprobe",
        type=Path,
        default=Path("ffprobe"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(normalize(parse_args()), ensure_ascii=False, indent=2))
