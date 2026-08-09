"""Build and validate a Fixed-8 FactGraph from high-thinking reflection."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from langgraph.graph import END, START, StateGraph

from ..contracts.registry import ContractRegistry
from ..resolvers.taxonomy import FACT_KIND_TO_LEAF, LEAF_TO_SLOT
from ..settings import get_settings
from ..stores.artifacts import LocalArtifactStore

FACT_GRAPH_SCHEMA = "fact_graph_fixed8.schema.json"
_FACT_REFLECTION_ROLE = "FACT_REFLECTION"


def _intervals_overlap(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    try:
        left_start = float(left["start_sec"])
        left_end = float(left["end_sec"])
        right_start = float(right["start_sec"])
        right_end = float(right["end_sec"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        left_end >= left_start
        and right_end >= right_start
        and left_start <= right_end
        and left_end >= right_start
    )


def _accepted_reflection(reports: list[dict], time_scope: object) -> bool:
    return (
        len(reports) == 1
        and reports[0].get("verifier_role") == _FACT_REFLECTION_ROLE
        and all(item.get("verdict") == "supported" for item in reports)
        and all(item.get("unique_grounding") is True for item in reports)
        and all(item.get("leaf_correct") is True for item in reports)
        and all(item.get("mutation_viable") is True for item in reports)
        and all(
            _intervals_overlap(item.get("evidence_interval"), time_scope)
            and bool(str(item.get("evidence_summary") or "").strip())
            for item in reports
        )
        and all(item.get("shares_observations", False) is False for item in reports)
    )


def assemble_fact_graph(state: dict) -> dict:
    if state.get("fact_graph") is not None:
        return state
    by_fact: dict[str, list[dict]] = defaultdict(list)
    for report in state.get("fact_verifier_reports", []):
        by_fact[str(report.get("source_fact_id"))].append(report)
    accepted: list[dict] = []
    for fact in state.get("proposed_facts", []):
        fact_kind = fact.get("fact_kind")
        if fact_kind not in FACT_KIND_TO_LEAF:
            continue
        reports = by_fact.get(str(fact.get("source_fact_id")), [])
        if not _accepted_reflection(reports, fact.get("time_scope")):
            continue
        leaf = FACT_KIND_TO_LEAF[fact_kind]
        accepted.append(
            {
                "source_fact_id": str(fact["source_fact_id"]),
                "fact_kind": fact_kind,
                "leaf_label": leaf,
                "conflict_slot": LEAF_TO_SLOT[leaf],
                "natural_language_fact": str(fact["natural_language_fact"]),
                "time_scope": dict(fact["time_scope"]),
                "verifier_consensus": {"accepted": True, "verifier_count": 1},
            }
        )
    return {
        **state,
        "fact_graph": {
            "schema_version": "videohalo_fact_graph_fixed8_3.7.0",
            "video_id": state["video_id"],
            "status": "surrogate_verified",
            "facts": accepted,
        },
    }


def validate_fact_graph(state: dict) -> dict:
    graph = state["fact_graph"]
    ContractRegistry().validate(FACT_GRAPH_SCHEMA, graph)
    for fact in graph["facts"]:
        expected_leaf = FACT_KIND_TO_LEAF[fact["fact_kind"]]
        if fact["leaf_label"] != expected_leaf:
            raise ValueError("Fact kind/leaf mismatch")
        if fact["conflict_slot"] != LEAF_TO_SLOT[expected_leaf]:
            raise ValueError("Fact leaf/slot mismatch")
    return {**state, "fact_graph_validated": True}


def persist_fact_graph(state: dict) -> dict:
    if not state.get("dataset_id"):
        return state
    store = LocalArtifactStore(get_settings().artifact_root, state["dataset_id"])
    return {
        **state,
        "fact_graph_ref": asdict(store.put_json("fact_graph", state["fact_graph"])),
    }


def build_fact_graph():
    graph = StateGraph(dict)
    graph.add_node("assemble_reflected_fixed8_facts", assemble_fact_graph)
    graph.add_node("validate_fixed8_fact_graph", validate_fact_graph)
    graph.add_node("persist_internal_fact_graph", persist_fact_graph)
    graph.add_edge(START, "assemble_reflected_fixed8_facts")
    graph.add_edge("assemble_reflected_fixed8_facts", "validate_fixed8_fact_graph")
    graph.add_edge("validate_fixed8_fact_graph", "persist_internal_fact_graph")
    graph.add_edge("persist_internal_fact_graph", END)
    return graph
