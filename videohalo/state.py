"""Reducer-safe state contracts for VideoHALO 3.7."""
from __future__ import annotations

import operator
from typing import Annotated, List, TypedDict


class ErrorRecord(TypedDict, total=False):
    node_name: str
    error_type: str
    message: str
    retryable: bool


class MediaRegistrationState(TypedDict, total=False):
    run_id: str
    dataset_id: str
    video_id: str
    source_path: str
    ffprobe_bin: str
    ffmpeg_bin: str
    provider_state: str
    video_manifest: dict
    video_manifest_ref: dict
    errors: Annotated[List[ErrorRecord], operator.add]


class FactGraphState(TypedDict, total=False):
    run_id: str
    dataset_id: str
    video_id: str
    proposed_facts: List[dict]
    fact_verifier_reports: Annotated[List[dict], operator.add]
    fact_graph: dict
    fact_graph_ref: dict
    errors: Annotated[List[ErrorRecord], operator.add]


class NativeMediaState(TypedDict, total=False):
    run_id: str
    dataset_id: str
    profile: str
    video_id: str
    source_path: str
    video_manifest: dict
    provider_media_lease: dict
    provider_media_lease_ref: dict
    native_media_ref: str
    adapter: object
    errors: Annotated[List[ErrorRecord], operator.add]


class NativeEvidenceState(TypedDict, total=False):
    mode: str
    role: str
    native_media_ref: str
    normalized_claim: dict
    time_scope: dict
    first_report: dict
    retry_report: dict
    retry_count: int
    retry_request: dict
    route: str
    native_evidence_status: str


class BuildState(TypedDict, total=False):
    run_id: str
    dataset_id: str
    profile: str
    output_path: str
    video_manifests: List[dict]
    fact_graphs: List[dict]
    eligibility_records: List[dict]
    candidates: List[dict]
    output_records: List[dict]
    errors: Annotated[List[ErrorRecord], operator.add]
