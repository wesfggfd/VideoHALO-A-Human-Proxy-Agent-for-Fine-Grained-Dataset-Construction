"""Private Google Cloud Storage transport for original VideoHALO media."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .safety import PROVIDER_CIRCUIT, redact_sensitive
from ..settings import get_settings


class GoogleCloudStorageError(RuntimeError):
    pass


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class GoogleCloudStorageAdapter:
    """Upload immutable source videos to one private, project-scoped bucket."""

    def __init__(self, client=None, *, bucket_name: Optional[str] = None):
        settings = get_settings()
        settings.validate_enterprise_runtime()
        self.project = settings.require_google_cloud_project()
        self.bucket_name = bucket_name or settings.require_gcs_bucket()
        if client is None:
            try:
                from google.cloud import storage
            except ImportError as exc:
                raise GoogleCloudStorageError(
                    "google-cloud-storage is required for Enterprise media"
                ) from exc
            client = storage.Client(project=self.project)
        self.client = client
        self.bucket = client.bucket(self.bucket_name)

    @staticmethod
    def _metadata_matches(blob, *, source_sha256: str, size: int) -> bool:
        metadata = getattr(blob, "metadata", None) or {}
        return (
            metadata.get("videohalo-source-sha256") == source_sha256
            and int(getattr(blob, "size", -1) or -1) == int(size)
        )

    def upload_or_reuse(
        self,
        *,
        path: str,
        object_name: str,
        mime_type: str,
        source_sha256: str,
        video_id: str,
    ) -> dict:
        PROVIDER_CIRCUIT.raise_if_open()
        source = Path(path).resolve()
        started = time.monotonic()
        blob = self.bucket.blob(object_name)
        try:
            if blob.exists(client=self.client):
                blob.reload(client=self.client)
                if not self._metadata_matches(
                    blob,
                    source_sha256=source_sha256,
                    size=source.stat().st_size,
                ):
                    raise GoogleCloudStorageError(
                        "Existing GCS object does not match canonical source"
                    )
                reused = True
            else:
                blob.metadata = {
                    "videohalo-source-sha256": source_sha256,
                    "videohalo-video-id": video_id,
                    "videohalo-immutable": "true",
                }
                blob.upload_from_filename(
                    str(source),
                    content_type=mime_type,
                    checksum="auto",
                    if_generation_match=0,
                    timeout=900,
                )
                blob.reload(client=self.client)
                reused = False
        except Exception as exc:
            PROVIDER_CIRCUIT.inspect(exc)
            if isinstance(exc, GoogleCloudStorageError):
                raise
            raise GoogleCloudStorageError(
                "Private GCS materialization failed: %s"
                % redact_sensitive(exc)
            ) from exc
        return {
            "object_name": object_name,
            "uri": "gs://%s/%s" % (self.bucket_name, object_name),
            "bucket": self.bucket_name,
            "generation": str(getattr(blob, "generation", "") or ""),
            "crc32c": str(getattr(blob, "crc32c", "") or ""),
            "size": int(getattr(blob, "size", source.stat().st_size)),
            "created_at": _iso(getattr(blob, "time_created", None)),
            "updated_at": _iso(getattr(blob, "updated", None)),
            "reused": reused,
            "upload_latency_ms": round((time.monotonic() - started) * 1000),
        }
