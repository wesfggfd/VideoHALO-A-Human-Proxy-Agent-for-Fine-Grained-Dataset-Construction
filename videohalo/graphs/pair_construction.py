"""Fixed-8 candidate acceptance and nine-field direct projection."""
from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..agents import MONITOR_AGENT
from ..contracts.registry import ContractRegistry
from ..resolvers.taxonomy import validate_leaf_slot
from ..resolvers.taxonomy import FACT_KIND_TO_LEAF
from ..stores.jsonl import append_pair_jsonl

OUTPUT_SCHEMA_VERSION = "videohalo_probe_pair_sample_fixed8_3.6.1"
PAIR_SCHEMA = "videohalo_probe_pair_sample_fixed8.schema.json"


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


def _monitor_rejection_reason(candidate: dict) -> str | None:
    reports = candidate.get("monitor_reports")
    if reports is None:
        if candidate.get("monitor_accepted") is True:
            return None
        return "Comprehensive reliability validation is missing"
    if not isinstance(reports, list) or len(reports) != 1:
        return "Exactly one monitor report is required"
    report = reports[0]
    if report.get("agent_role") != MONITOR_AGENT:
        return "Monitor agent role is invalid"
    checks = (
        ("accepted", report.get("accepted") is True),
        ("answer verdict", report.get("answer_verdict") == "supported"),
        (
            "counterfactual verdict",
            report.get("counterfactual_verdict") == "contradicted",
        ),
        (
            "natural answer grounding",
            report.get("natural_answer_matches_source_fact") is True,
        ),
        ("leaf boundary", report.get("leaf_boundary_correct") is True),
        (
            "planned leaf target",
            report.get("counterfactual_targets_planned_leaf") is True,
        ),
        ("single target slot", report.get("single_target_slot") is True),
        ("additional error count", report.get("additional_error_count", 0) == 0),
        (
            "evidence interval overlap",
            _intervals_overlap(
                report.get("answer_evidence_interval"),
                candidate.get("time_scope"),
            ),
        ),
        (
            "evidence summary",
            bool(str(report.get("evidence_summary") or "").strip()),
        ),
        (
            "independent observations",
            report.get("shares_observations", False) is False,
        ),
    )
    for label, passed in checks:
        if not passed:
            return f"Comprehensive reliability validation rejected: {label}"
    return None


def _monitor_accepted(candidate: dict) -> bool:
    return _monitor_rejection_reason(candidate) is None


def validate_internal_pair(candidate: dict) -> None:
    diff = candidate.get("graph_diff", {})
    if (
        diff.get("changed_atomic_fact_count") != 1
        or diff.get("changed_slot_count") != 1
    ):
        raise ValueError("One-fact/one-slot invariant failed")
    if (
        candidate.get("supported_contradicted_count") != 0
        or candidate.get("counterfactual_contradicted_count") != 1
        or candidate.get("additional_error_count", 0) != 0
    ):
        raise ValueError("Single-error invariant failed")
    monitor_rejection = _monitor_rejection_reason(candidate)
    if monitor_rejection is not None:
        raise ValueError(monitor_rejection)
    validate_leaf_slot(candidate["leaf_label"], candidate["conflict_slot"])
    changed_paths = diff.get("changed_paths", [])
    if changed_paths:
        changed_slot = str(changed_paths[0]).rsplit(".", 1)[-1]
        if changed_slot != candidate["conflict_slot"]:
            raise ValueError("GraphDiff changed slot disagrees with target slot")
    fact_kind = candidate.get("fact_kind")
    if fact_kind is not None and FACT_KIND_TO_LEAF.get(fact_kind) != candidate["leaf_label"]:
        raise ValueError("Candidate fact kind disagrees with target leaf")


def project_direct_record(candidate: dict) -> dict:
    validate_internal_pair(candidate)
    record = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "pair_id": candidate["pair_id"],
        "media": candidate["media"],
        "task_type": candidate["task_type"],
        "question": candidate["question"],
        "answer": candidate["answer"],
        "counterfactual_answer": candidate["counterfactual_answer"],
        "leaf_label": candidate["leaf_label"],
        "conflict_slot": candidate["conflict_slot"],
    }
    ContractRegistry().validate(PAIR_SCHEMA, record)
    return record


def validate_candidate_pair(state: dict) -> dict:
    validate_internal_pair(state["candidate"])
    return {**state, "candidate_validated": True}


def project_pair(state: dict) -> dict:
    return {**state, "output_record": project_direct_record(state["candidate"])}


def persist_pair(state: dict) -> dict:
    output_path = state.get("output_path")
    if output_path:
        append_pair_jsonl(
            Path(output_path),
            state["output_record"],
            max_records=state.get("total_pair_limit"),
        )
    return {**state, "status": "emitted" if output_path else "validated"}


def build_pair_construction_graph():
    graph = StateGraph(dict)
    graph.add_node("validate_graph_diff_and_monitor", validate_candidate_pair)
    graph.add_node("project_exact_nine_field_record", project_pair)
    graph.add_node("atomic_append_jsonl", persist_pair)
    graph.add_edge(START, "validate_graph_diff_and_monitor")
    graph.add_edge("validate_graph_diff_and_monitor", "project_exact_nine_field_record")
    graph.add_edge("project_exact_nine_field_record", "atomic_append_jsonl")
    graph.add_edge("atomic_append_jsonl", END)
    return graph
