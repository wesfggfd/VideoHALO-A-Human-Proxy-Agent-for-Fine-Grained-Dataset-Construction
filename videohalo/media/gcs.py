"""Idempotent private-GCS materialization for canonical source videos."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .lease_registry import ProviderLeaseRegistry
from ..providers.safety import redact_sensitive


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_component(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("._")
    return normalized or "video"


def gcs_object_name(
    *, prefix: str, video_id: str, source_sha256: str, source_path: Path
) -> str:
    suffix = source_path.suffix.lower() or ".mp4"
    return "%s/%s/%s/%s%s" % (
        prefix.strip("/"),
        source_sha256[:2],
        source_sha256,
        _safe_component(video_id),
        suffix,
    )


def _project_hash(project: str) -> str:
    return hashlib.sha256(("videohalo-gcp:" + project).encode("utf-8")).hexdigest()[:24]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_or_reuse_gcs_object(
    *,
    registry: ProviderLeaseRegistry,
    adapter,
    project: str,
    bucket: str,
    prefix: str,
    source_path: Path,
    manifest: dict,
    mime_type: str,
) -> dict:
    """Materialize one immutable source object and return a durable lease."""
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_sha256 = str(manifest["source_sha256"])
    if _sha256_path(source_path) != source_sha256:
        raise ValueError("Canonical source bytes no longer match the video manifest")
    project_hash = _project_hash(project)
    key = {
        "provider": "google_cloud_storage",
        "project_hash": project_hash,
        "source_sha256": source_sha256,
        "mime_type": mime_type,
    }
    existing = registry.get(**key)
    if existing and existing.get("state") == "active":
        uri = str(existing.get("provider_media_uri", ""))
        expected_prefix = "gs://%s/" % bucket
        if not uri.startswith(expected_prefix):
            raise ValueError("Stored GCS lease belongs to another bucket")
        existing["reuse_count"] = int(existing.get("reuse_count", 0)) + 1
        existing["last_used_at"] = _now().isoformat()
        registry.upsert(existing)
        return existing

    object_name = gcs_object_name(
        prefix=prefix,
        video_id=str(manifest["video_id"]),
        source_sha256=source_sha256,
        source_path=source_path,
    )
    created_at = _now()
    lease_id = "gcs_" + hashlib.sha256(
        (project_hash + bucket + object_name).encode("utf-8")
    ).hexdigest()[:24]
    pending = {
        "schema_version": "provider_media_lease_3.0",
        "lease_id": lease_id,
        **key,
        "source_ref": {
            "uri": source_path.as_uri(),
            "sha256": source_sha256,
        },
        "transport": "private_gcs_uri",
        "provider_bucket": bucket,
        "provider_object_name": object_name,
        "provider_media_uri": "gs://%s/%s" % (bucket, object_name),
        "state": "pending",
        "created_at": created_at.isoformat(),
        "activated_at": None,
        "expires_at": None,
        "last_used_at": None,
        "upload_latency_ms": 0,
        "reuse_count": 0,
        "upload_bytes": source_path.stat().st_size,
        "generation": None,
        "crc32c": None,
        "failure_history": [],
    }
    pending, _ = registry.claim_pending(key=key, pending=pending)
    try:
        uploaded = adapter.upload_or_reuse(
            path=str(source_path),
            object_name=object_name,
            mime_type=mime_type,
            source_sha256=source_sha256,
            video_id=str(manifest["video_id"]),
        )
        pending.update(
            {
                "provider_bucket": uploaded["bucket"],
                "provider_object_name": uploaded["object_name"],
                "provider_media_uri": uploaded["uri"],
                "state": "active",
                "activated_at": _now().isoformat(),
                "last_used_at": _now().isoformat(),
                "upload_latency_ms": int(uploaded["upload_latency_ms"]),
                "generation": uploaded.get("generation"),
                "crc32c": uploaded.get("crc32c"),
                "reuse_count": int(pending.get("reuse_count", 0))
                + int(bool(uploaded.get("reused"))),
            }
        )
    except Exception as exc:
        pending["state"] = "failed"
        pending.setdefault("failure_history", []).append(
            {
                "at": _now().isoformat(),
                "error_type": type(exc).__name__,
                "message": redact_sensitive(exc),
            }
        )
        registry.upsert(pending)
        raise
    registry.upsert(pending)
    return pending
