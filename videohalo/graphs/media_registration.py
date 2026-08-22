"""VideoHALO 3.8 non-semantic media-registration graph."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..contracts.registry import ContractRegistry
from ..media.register import register_media
from ..settings import get_settings
from ..state import MediaRegistrationState
from ..stores.artifacts import LocalArtifactStore


def register_native_streams(state: MediaRegistrationState) -> dict:
    settings = get_settings()
    manifest = register_media(
        source=Path(state["source_path"]), video_id=state["video_id"],
        ffprobe_bin=state.get("ffprobe_bin", settings.ffprobe_bin),
        ffmpeg_bin=state.get("ffmpeg_bin", settings.ffmpeg_bin),
        provider_state=state.get("provider_state", "pending"),
    )
    ContractRegistry().validate("video_manifest.schema.json", manifest)
    return {"video_manifest": manifest}


def persist_manifest(state: MediaRegistrationState) -> dict:
    store = LocalArtifactStore(get_settings().artifact_root, state["dataset_id"])
    return {"video_manifest_ref": asdict(store.put_json("video_manifest", state["video_manifest"]))}


def build_media_registration_graph():
    graph = StateGraph(MediaRegistrationState)
    graph.add_node("register_original_video", register_native_streams)
    graph.add_node("persist_video_manifest", persist_manifest)
    graph.add_edge(START, "register_original_video")
    graph.add_edge("register_original_video", "persist_video_manifest")
    graph.add_edge("persist_video_manifest", END)
    return graph
