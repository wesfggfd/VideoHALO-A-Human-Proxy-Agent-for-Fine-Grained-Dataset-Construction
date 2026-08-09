"""Persistent private-GCS materialization for VideoHALO 3.7."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..contracts.registry import ContractRegistry
from ..media.gcs import acquire_or_reuse_gcs_object
from ..media.lease_registry import ProviderLeaseRegistry
from ..media.register import detect_mime
from ..providers.gcs import GoogleCloudStorageAdapter
from ..settings import get_settings
from ..state import NativeMediaState
from ..stores.artifacts import LocalArtifactStore


def materialize_original_video(state: NativeMediaState) -> dict:
    settings = get_settings()
    registry = ProviderLeaseRegistry(
        settings.artifact_root
        / state["dataset_id"]
        / "ledgers"
        / "provider_media_leases.sqlite"
    )
    adapter = state.get("adapter") or GoogleCloudStorageAdapter()
    lease = acquire_or_reuse_gcs_object(
        registry=registry,
        adapter=adapter,
        project=settings.require_google_cloud_project(),
        bucket=settings.require_gcs_bucket(),
        prefix=settings.google_cloud_storage_prefix,
        source_path=Path(state["source_path"]),
        manifest=state["video_manifest"],
        mime_type=detect_mime(Path(state["source_path"])),
    )
    manifest = dict(state["video_manifest"])
    manifest["provider_state"] = "active"
    ContractRegistry().validate("video_manifest.schema.json", manifest)
    return {
        **state,
        "provider_media_lease": lease,
        "native_media_ref": lease["provider_media_uri"],
        "video_manifest": manifest,
    }


def persist_lease(state: NativeMediaState) -> dict:
    store = LocalArtifactStore(get_settings().artifact_root, state["dataset_id"])
    ref = store.put_json("provider_media_lease", state["provider_media_lease"])
    return {**state, "provider_media_lease_ref": asdict(ref)}


def build_native_media_ingestion_graph():
    graph = StateGraph(NativeMediaState)
    graph.add_node("materialize_private_gcs_original", materialize_original_video)
    graph.add_node("persist_operational_provider_lease", persist_lease)
    graph.add_edge(START, "materialize_private_gcs_original")
    graph.add_edge(
        "materialize_private_gcs_original", "persist_operational_provider_lease"
    )
    graph.add_edge("persist_operational_provider_lease", END)
    return graph


graph = build_native_media_ingestion_graph().compile()
