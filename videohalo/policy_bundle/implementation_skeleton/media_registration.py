from pathlib import Path
import hashlib

from langgraph.graph import END, START, StateGraph

def register_native_media(state: dict) -> dict:
    source = Path(state["source_path"])
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "videohalo_video_manifest_3.7.1",
        "video_id": state["video_id"],
        "source_sha256": sha,
        "canonical_media_uri": f"media://{state['video_id']}/original",
        "registered_modalities": ["visual", "speech_audio", "non_speech_audio", "on_screen_text", "camera_editing", "container_metadata"],
        "provider_transport": "private_gcs_uri",
        "provider_state": state.get("provider_state", "pending"),
    }
    return {**state, "video_manifest": manifest}

def build_media_registration_graph():
    graph = StateGraph(dict)
    graph.add_node("register_native_media", register_native_media)
    graph.add_edge(START, "register_native_media")
    graph.add_edge("register_native_media", END)
    return graph
