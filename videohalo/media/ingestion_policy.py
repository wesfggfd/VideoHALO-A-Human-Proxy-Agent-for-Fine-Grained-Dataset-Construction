"""Frozen Gemini-native media and evidence policy primitives."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..policy.loader import load_core_memory


class Transport(str, Enum):
    PRIVATE_GCS_URI = "private_gcs_uri"


class NativeEvidenceStatus(str, Enum):
    SUFFICIENT = "native_sufficient"
    SUFFICIENT_AFTER_RETRY = "native_sufficient_after_focused_retry"
    INSUFFICIENT = "native_insufficient"
    CONFLICT = "native_conflict"


ACCEPTED_NATIVE_STATUSES = {NativeEvidenceStatus.SUFFICIENT.value, NativeEvidenceStatus.SUFFICIENT_AFTER_RETRY.value}


@dataclass(frozen=True)
class NativeMediaPolicy:
    proposer_resolution: str = "low"
    review_resolution: str = "medium"
    retry_resolution: str = "high"
    max_focused_retries: int = 1
    external_semantic_artifacts_enabled: bool = False
    transport: Transport = Transport.PRIVATE_GCS_URI

    def validate(self) -> None:
        if self.max_focused_retries != 1:
            raise ValueError("Exactly one focused native retry is permitted")
        if self.external_semantic_artifacts_enabled:
            raise ValueError("External semantic artifacts are forbidden in VideoHALO")
        if self.transport is not Transport.PRIVATE_GCS_URI:
            raise ValueError("Private GCS URI is the only production transport")


def load_media_ingestion_policy() -> dict:
    policy = load_core_memory().json("media_ingestion_policy_json")
    if policy.get("transport") != "private_gcs_uri":
        raise ValueError("Private GCS URI is the only 3.7 production transport")
    if policy.get("external_semantic_tools_enabled") is not False:
        raise ValueError("External semantic tools are forbidden")
    if policy.get("focused_native_retry_max") != 1:
        raise ValueError("Exactly one focused native retry is allowed")
    return policy
