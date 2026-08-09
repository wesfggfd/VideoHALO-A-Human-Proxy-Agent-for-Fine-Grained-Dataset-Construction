"""Non-semantic canonical media registration for VideoHALO 3.7."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
from pathlib import Path

from ..policy.loader import load_core_memory


class MediaProbeError(RuntimeError):
    pass


def detect_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith("video/"):
        raise MediaProbeError("Source is not a recognized video: %s" % path)
    return mime


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaProbeError("Media probe failed to start: %s" % exc) from exc


def _validate_container(source: Path, ffprobe_bin: str) -> None:
    detect_mime(source)
    result = _run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_type",
            "-of",
            "json",
            str(source),
        ]
    )
    if result.returncode:
        raise MediaProbeError("ffprobe rejected source: %s" % result.stderr[-1000:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProbeError("ffprobe returned invalid JSON") from exc
    if not any(item.get("codec_type") == "video" for item in payload.get("streams", [])):
        raise MediaProbeError("Source contains no video stream")


def _smoke_decode(source: Path, ffmpeg_bin: str, seconds: int) -> None:
    result = _run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-t",
            str(seconds),
            "-i",
            str(source),
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode:
        raise MediaProbeError("Decode smoke test failed: %s" % result.stderr[-1000:])


def register_media(
    *,
    source: Path,
    video_id: str,
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    smoke_seconds: int = 3,
    provider_state: str = "pending",
    **_: object,
) -> dict:
    source = source.resolve()
    if not source.is_file() or source.stat().st_size < 1:
        raise MediaProbeError("Media file does not exist or is empty: %s" % source)
    _validate_container(source, ffprobe_bin)
    _smoke_decode(source, ffmpeg_bin, smoke_seconds)
    policy = load_core_memory().json("media_ingestion_policy_json")
    manifest = {
        "schema_version": "videohalo_video_manifest_3.7.1",
        "video_id": video_id,
        "source_sha256": sha256_path(source),
        "canonical_media_uri": "media://%s/original" % video_id,
        "registered_modalities": list(policy["registered_modalities"]),
        "provider_transport": policy["transport"],
        "provider_state": provider_state,
    }
    return manifest
