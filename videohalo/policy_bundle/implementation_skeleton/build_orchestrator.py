from langgraph.graph import END, START, StateGraph
from pair_construction import project_direct_record
from direct_output_writer import append_pair_jsonl
from pathlib import Path

def load_policy(state: dict) -> dict:
    return {**state, "taxonomy_version": "VHal-Fixed8-3.7"}

def require_verified_pair(state: dict) -> dict:
    if not state.get("candidate_verifier_consensus"):
        raise ValueError("Candidate A/B consensus required")
    return state

def emit_direct_pair(state: dict) -> dict:
    record = project_direct_record(state["candidate"])
    append_pair_jsonl(Path(state["output_path"]), record)
    return {**state, "output_record": record, "status": "emitted"}

def build_dataset_construction_graph():
    graph = StateGraph(dict)
    graph.add_node("load_fixed8_policy", load_policy)
    graph.add_node("require_verified_pair", require_verified_pair)
    graph.add_node("emit_direct_pair_jsonl", emit_direct_pair)
    graph.add_edge(START, "load_fixed8_policy")
    graph.add_edge("load_fixed8_policy", "require_verified_pair")
    graph.add_edge("require_verified_pair", "emit_direct_pair_jsonl")
    graph.add_edge("emit_direct_pair_jsonl", END)
    return graph
