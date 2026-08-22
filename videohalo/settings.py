"""Environment-only runtime settings for VideoHALO 3.8.

Frozen semantic policy lives in ``policy_bundle``.  This module contains only
deployment values and never embeds credentials.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
POLICY_BUNDLE_ROOT = PACKAGE_ROOT / "policy_bundle"
CORE_MEMORY_MANIFEST = POLICY_BUNDLE_ROOT / "config" / "core_memory_manifest.json"


def _media_tool_path(name: str) -> str:
    override = os.getenv(f"VIDEOHALO_{name.upper()}")
    if override:
        return override
    bundled = (
        PROJECT_ROOT
        / "video_dataset_staging"
        / "tools"
        / "ffmpeg"
        / "ffmpeg-8.1.2-essentials_build"
        / "bin"
        / f"{name}.exe"
    )
    return str(bundled) if bundled.is_file() else name


@dataclass(frozen=True)
class Settings:
    artifact_root: Path = Path(os.getenv("VIDEOHALO_ARTIFACT_ROOT", PROJECT_ROOT / "artifacts"))
    ffprobe_bin: str = _media_tool_path("ffprobe")
    ffmpeg_bin: str = _media_tool_path("ffmpeg")
    google_cloud_project: Optional[str] = os.getenv("GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = os.getenv(
        "GOOGLE_CLOUD_LOCATION", "global"
    )
    google_cloud_storage_bucket: Optional[str] = os.getenv(
        "VIDEOHALO_GCS_BUCKET"
    )
    google_cloud_storage_prefix: str = os.getenv(
        "VIDEOHALO_GCS_PREFIX", "videohalo/original-video"
    ).strip("/")
    google_genai_use_enterprise: bool = os.getenv(
        "GOOGLE_GENAI_USE_ENTERPRISE", "true"
    ).strip().lower() in {"1", "true", "yes"}
    gemini_model: str = os.getenv("VIDEOHALO_GEMINI_MODEL", "gemini-3.6-flash")
    gemini_service_tier: str = os.getenv(
        "VIDEOHALO_GEMINI_SERVICE_TIER", "flex"
    )
    selection_seed: int = int(os.getenv("VIDEOHALO_SELECTION_SEED", "42"))
    # Google currently permits up to 30 minutes for Flex PayGo requests.
    node_timeout_seconds: int = int(os.getenv("VIDEOHALO_NODE_TIMEOUT", "1800"))
    flex_max_attempts: int = int(
        os.getenv("VIDEOHALO_FLEX_MAX_ATTEMPTS", "3")
    )
    flex_retry_base_seconds: float = float(
        os.getenv("VIDEOHALO_FLEX_RETRY_BASE_SECONDS", "5")
    )
    model_requests_per_minute: float = float(
        os.getenv("VIDEOHALO_MODEL_REQUESTS_PER_MINUTE", "8")
    )

    def validate_enterprise_runtime(self) -> None:
        if not self.google_genai_use_enterprise:
            raise RuntimeError(
                "VideoHALO production runtime requires "
                "GOOGLE_GENAI_USE_ENTERPRISE=true"
            )
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError(
                "API-key environment variables must be unset for the "
                "Enterprise ADC runtime"
            )
        credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if credential_path:
            try:
                credential_descriptor = json.loads(
                    Path(credential_path).read_text(encoding="utf-8-sig")
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    "GOOGLE_APPLICATION_CREDENTIALS is unreadable or invalid"
                ) from exc
            if credential_descriptor.get("type") == "service_account":
                raise RuntimeError(
                    "Long-lived service-account key files are forbidden; use "
                    "user ADC, service-account impersonation, or an attached "
                    "Google Cloud service identity"
                )
        if self.google_cloud_location != "global":
            raise RuntimeError(
                "VideoHALO Flex production is frozen to the global endpoint"
            )
        if self.gemini_service_tier not in {"flex", "standard"}:
            raise RuntimeError(
                "Enterprise runtime supports only flex or standard tiers"
            )
        if self.model_requests_per_minute <= 0:
            raise RuntimeError(
                "VIDEOHALO_MODEL_REQUESTS_PER_MINUTE must be positive"
            )
        if not 1 <= self.node_timeout_seconds <= 1800:
            raise RuntimeError(
                "VIDEOHALO_NODE_TIMEOUT must be between 1 and 1800 seconds"
            )

    def require_google_cloud_project(self) -> str:
        if not self.google_cloud_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")
        return self.google_cloud_project

    def require_gcs_bucket(self) -> str:
        if not self.google_cloud_storage_bucket:
            raise RuntimeError("VIDEOHALO_GCS_BUCKET is required")
        value = self.google_cloud_storage_bucket.strip()
        if value.startswith("gs://") or "/" in value:
            raise RuntimeError(
                "VIDEOHALO_GCS_BUCKET must contain only the bucket name"
            )
        return value


def get_settings() -> Settings:
    return Settings()
