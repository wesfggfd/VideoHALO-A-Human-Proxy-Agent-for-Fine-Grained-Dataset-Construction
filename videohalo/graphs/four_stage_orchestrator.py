"""Four-stage VideoHALO orchestration with direct Fixed-8 JSONL output."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ..agents import REFLECTION_AGENT
from ..answer_alignment import validate_question_answer_alignment
from ..contracts.registry import ContractRegistry
from ..contracts.stage_outputs import (
    COMPREHENSIVE_RELIABILITY_VALIDATION,
    FACT_EXTRACTION_AND_REFLECTION,
    GENERATION_AND_VERIFICATION,
    HALLUCINATION_CATEGORY_RETRIEVAL,
    make_stage_output,
    validate_stage_output,
)
from ..policy.loader import load_core_memory
from ..resolvers.taxonomy import validate_leaf_slot
from ..stores.jsonl import append_pair_jsonl
from ..taxonomy_first import (
    build_leaf_search_plan,
    leaf_conditioned_facts,
    validate_opportunity_matrix,
)
from .fact_graph_build import validate_fact_graph
from .pair_construction import project_direct_record, validate_internal_pair

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


def _candidates(state: dict) -> list[dict]:
    values = list(state.get("candidates", []))
    if not values and state.get("candidate"):
        values = [state["candidate"]]
    if not values:
        raise ValueError("Build requires at least one candidate")
    return values


def load_fixed8_policy(state: dict) -> dict:
    core = load_core_memory()
    profiles = core.yaml("runtime_profiles")
    profile = state.get("profile", "probe_build")
    profile_spec = profiles["profiles"].get(profile)
    if not profile_spec or profile_spec.get("graph") != "build":
        raise ValueError("Not a 3.7 build profile: %s" % profile)
    return {
        **state,
        "taxonomy_version": core.manifest["taxonomy_version"],
        "core_memory_hash": core.manifest_sha256,
        "profile_spec": profile_spec,
    }


def canonical_media_registration(state: dict) -> dict:
    manifests = list(state.get("video_manifests", []))
    if not manifests:
        raise ValueError("Build requires canonical video manifests")
    registry = ContractRegistry()
    by_video = {}
    for manifest in manifests:
        registry.validate("video_manifest.schema.json", manifest)
        video_id = manifest["video_id"]
        if video_id in by_video:
            raise ValueError("Duplicate video manifest: %s" % video_id)
        by_video[video_id] = manifest
    return {**state, "video_manifest_by_id": by_video}


def private_gcs_materialization(state: dict) -> dict:
    for manifest in state["video_manifest_by_id"].values():
        if manifest["provider_transport"] != "private_gcs_uri":
            raise ValueError("Build requires private Google Cloud Storage transport")
        if manifest["provider_state"] != "active":
            raise ValueError("Build requires an active provider URI")
    return {**state, "native_media_ready": True}


def taxonomy_first_plan(state: dict) -> dict:
    expected = build_leaf_search_plan()
    supplied = state.get("leaf_search_plan")
    if supplied != expected:
        raise ValueError("Build requires the frozen Fixed-8 leaf-search plan")
    return {**state, "taxonomy_first_plan_validated": True}


def eight_leaf_opportunity_scan(state: dict) -> dict:
    matrices = list(state.get("leaf_opportunity_matrices", []))
    if not matrices:
        raise ValueError("Build requires an eight-leaf opportunity matrix")
    expected_videos = set(state["video_manifest_by_id"])
    observed_videos = set()
    validated = []
    for matrix in matrices:
        normalized = validate_opportunity_matrix(
            matrix,
            plan=state["leaf_search_plan"],
        )
        video_id = normalized["video_id"]
        if video_id in observed_videos:
            raise ValueError("Duplicate leaf-opportunity matrix: %s" % video_id)
        if video_id not in expected_videos:
            raise ValueError("Opportunity matrix has no canonical video")
        observed_videos.add(video_id)
        validated.append(normalized)
    if observed_videos != expected_videos:
        raise ValueError("Every canonical video requires an opportunity matrix")
    return {
        **state,
        "leaf_opportunity_matrices": validated,
        "opportunity_scan_validated": True,
    }


def leaf_conditioned_fact_extraction(state: dict) -> dict:
    matrices = list(state["leaf_opportunity_matrices"])
    facts = list(state.get("leaf_conditioned_facts", []))
    if len(matrices) != 1:
        raise ValueError(
            "Flat leaf-conditioned fact validation requires one video"
        )
    accepted = leaf_conditioned_facts(facts, matrix=matrices[0])
    if accepted != facts:
        raise ValueError(
            "Facts must be extracted only from their planned leaf opportunities"
        )
    return {**state, "leaf_conditioned_fact_extraction_validated": True}


def require_fact_proposal(state: dict) -> dict:
    if not state.get("fact_graphs") and not state.get("proposed_facts"):
        raise ValueError("Build requires proposed facts or verified FactGraphs")
    return {**state, "fact_proposal_present": True}


def require_reflection_agent_validation(state: dict) -> dict:
    by_fact: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for report in state.get("reflection_reports", []):
        key = (str(report.get("video_id")), str(report.get("source_fact_id")))
        by_fact[key].append(report)
    for graph in state.get("fact_graphs", []):
        for fact in graph.get("facts", []):
            key = (str(graph["video_id"]), str(fact["source_fact_id"]))
            reports = by_fact.get(key, [])
            if (
                len(reports) != 1
                or reports[0].get("agent_role") != REFLECTION_AGENT
                or any(item.get("verdict") != "supported" for item in reports)
                or any(item.get("unique_grounding") is not True for item in reports)
                or any(item.get("leaf_correct") is not True for item in reports)
                or any(item.get("mutation_viable") is not True for item in reports)
                or any(
                    not _intervals_overlap(
                        item.get("evidence_interval"),
                        fact.get("time_scope"),
                    )
                    or not str(item.get("evidence_summary") or "").strip()
                    for item in reports
                )
                or any(
                    item.get("shares_observations", False) is not False
                    for item in reports
                )
            ):
                raise ValueError(
                    "Every FactGraph fact requires high-thinking reflection"
                )
    return {**state, "reflection_reports_by_id": dict(by_fact)}


def fact_consensus(state: dict) -> dict:
    fact_graphs = list(state.get("fact_graphs", []))
    if not fact_graphs:
        raise ValueError(
            "Provider adapters must assemble FactGraphs before consensus"
        )
    facts_by_id = {}
    for graph in fact_graphs:
        validate_fact_graph({"fact_graph": graph})
        for fact in graph["facts"]:
            key = (graph["video_id"], fact["source_fact_id"])
            if key in facts_by_id:
                raise ValueError("Duplicate verified source fact: %r" % (key,))
            facts_by_id[key] = fact
    return {**state, "verified_facts_by_id": facts_by_id}


def fixed8_eligibility_scan(state: dict) -> dict:
    registry = ContractRegistry()
    eligible_keys = set()
    for record in state.get("eligibility_records", []):
        registry.validate("eligibility_record_fixed8.schema.json", record)
        if record["eligible"]:
            eligible_keys.add(
                (
                    record["video_id"],
                    record["source_fact_id"],
                    record["task_type"],
                    record["leaf_label"],
                )
            )
    if not eligible_keys:
        raise ValueError("Build requires a non-empty Fixed-8 eligibility census")
    return {**state, "eligible_keys": eligible_keys}


def faithful_relative_selection(state: dict) -> dict:
    candidates = _candidates(state)
    for candidate in candidates:
        video_id = candidate["media"]["video_id"]
        source_fact_id = candidate.get("source_fact_id")
        if video_id not in state["video_manifest_by_id"]:
            raise ValueError("Candidate has no canonical video manifest")
        fact = state["verified_facts_by_id"].get((video_id, source_fact_id))
        if fact is None:
            raise ValueError("Candidate has no verified source fact")
        if (
            fact["leaf_label"] != candidate["leaf_label"]
            or fact["conflict_slot"] != candidate["conflict_slot"]
        ):
            raise ValueError("Candidate disagrees with its verified source fact")
        key = (
            video_id,
            source_fact_id,
            candidate["task_type"],
            candidate["leaf_label"],
        )
        if key not in state["eligible_keys"]:
            raise ValueError("Candidate is absent from the eligible census")
    return {
        **state,
        "candidates": candidates,
        "observed_leaf_yield": dict(
            Counter(item["leaf_label"] for item in candidates)
        ),
    }


def one_slot_mutation(state: dict) -> dict:
    for candidate in state["candidates"]:
        validate_leaf_slot(candidate["leaf_label"], candidate["conflict_slot"])
        diff = candidate.get("graph_diff", {})
        if (
            diff.get("changed_atomic_fact_count") != 1
            or diff.get("changed_slot_count") != 1
        ):
            raise ValueError("One-fact/one-slot mutation invariant failed")
    return {**state, "mutation_validated": True}


def answer_pair_realization(state: dict) -> dict:
    for candidate in state["candidates"]:
        for field in ("question", "answer", "counterfactual_answer"):
            if not str(candidate.get(field, "")).strip():
                raise ValueError("Candidate realization is missing %s" % field)
        if candidate["answer"].strip() == candidate["counterfactual_answer"].strip():
            raise ValueError("Supported and counterfactual answers must differ")
        validate_question_answer_alignment(
            task_type=candidate["task_type"],
            fact_kind=candidate["fact_kind"],
            question=candidate["question"],
            answer=candidate["answer"],
            counterfactual_answer=candidate["counterfactual_answer"],
            supported_fact=candidate["supported_fact"],
            counterfactual_fact=candidate["counterfactual_fact"],
        )
    return {**state, "realization_validated": True}


def backparse_both_answers(state: dict) -> dict:
    for candidate in state["candidates"]:
        if not isinstance(candidate.get("graph_diff"), dict):
            raise ValueError("Both answers must be back-parsed before GraphDiff")
    return {**state, "backparse_validated": True}


def graph_diff_validation(state: dict) -> dict:
    for candidate in state["candidates"]:
        paths = candidate["graph_diff"].get("changed_paths", [])
        if paths:
            changed_slot = str(paths[0]).rsplit(".", 1)[-1]
            if changed_slot != candidate["conflict_slot"]:
                raise ValueError("GraphDiff slot disagrees with mutation target")
    return {**state, "graph_diff_validated": True}


def single_error_validation(state: dict) -> dict:
    for candidate in state["candidates"]:
        if (
            candidate.get("supported_contradicted_count") != 0
            or candidate.get("counterfactual_contradicted_count") != 1
            or candidate.get("additional_error_count", 0) != 0
        ):
            raise ValueError("Single-error invariant failed")
    return {**state, "single_error_validated": True}


def comprehensive_monitor_gate(state: dict) -> dict:
    for candidate in state["candidates"]:
        validate_internal_pair(candidate)
    return {**state, "comprehensive_reliability_validated": True}


def direct_pair_projection(state: dict) -> dict:
    return {
        **state,
        "output_records": [
            project_direct_record(candidate) for candidate in state["candidates"]
        ],
    }


def append_public_jsonl(state: dict) -> dict:
    output_path = Path(state["output_path"])
    for record in state["output_records"]:
        append_pair_jsonl(
            output_path,
            record,
            max_records=state.get("total_pair_limit"),
        )
    return {
        **state,
        "status": "emitted",
        "emitted_pair_count": len(state["output_records"]),
    }


def hallucination_category_retrieval(state: dict) -> dict:
    current = load_fixed8_policy(state)
    current = canonical_media_registration(current)
    current = private_gcs_materialization(current)
    current = taxonomy_first_plan(current)
    current = eight_leaf_opportunity_scan(current)
    video_ids = sorted(current["video_manifest_by_id"])
    stage_output = make_stage_output(
        stage=HALLUCINATION_CATEGORY_RETRIEVAL,
        video_id=video_ids[0] if len(video_ids) == 1 else "batch",
        payload={
            "leaf_search_plan": current["leaf_search_plan"],
            "leaf_opportunity_matrices": current[
                "leaf_opportunity_matrices"
            ],
        },
        memory_snapshot=current.get("memory_snapshot", {}),
    )
    return {**current, "hallucination_category_retrieval_output": stage_output}


def fact_extraction_and_reflection(state: dict) -> dict:
    upstream = validate_stage_output(
        state["hallucination_category_retrieval_output"],
        expected_stage=HALLUCINATION_CATEGORY_RETRIEVAL,
    )
    current = leaf_conditioned_fact_extraction(state)
    current = require_fact_proposal(current)
    current = require_reflection_agent_validation(current)
    current = fact_consensus(current)
    current = fixed8_eligibility_scan(current)
    current = faithful_relative_selection(current)
    stage_output = make_stage_output(
        stage=FACT_EXTRACTION_AND_REFLECTION,
        video_id=str(upstream["video_id"]),
        upstream=[upstream],
        payload={
            "fact_graphs": current["fact_graphs"],
            "reflection_reports": current.get("reflection_reports", []),
            "eligibility_records": current.get("eligibility_records", []),
        },
        memory_snapshot=current.get("memory_snapshot", {}),
    )
    return {**current, "fact_extraction_and_reflection_output": stage_output}


def generation_and_verification_of_adversarial_pairs(state: dict) -> dict:
    upstream = validate_stage_output(
        state["fact_extraction_and_reflection_output"],
        expected_stage=FACT_EXTRACTION_AND_REFLECTION,
    )
    current = one_slot_mutation(state)
    current = answer_pair_realization(current)
    current = backparse_both_answers(current)
    current = graph_diff_validation(current)
    current = single_error_validation(current)
    stage_output = make_stage_output(
        stage=GENERATION_AND_VERIFICATION,
        video_id=str(upstream["video_id"]),
        upstream=[upstream],
        payload={"candidates": current["candidates"]},
        memory_snapshot=current.get("memory_snapshot", {}),
    )
    return {
        **current,
        "generation_and_verification_output": stage_output,
    }


def comprehensive_reliability_validation(state: dict) -> dict:
    upstream = validate_stage_output(
        state["generation_and_verification_output"],
        expected_stage=GENERATION_AND_VERIFICATION,
    )
    current = comprehensive_monitor_gate(state)
    current = direct_pair_projection(current)
    current = append_public_jsonl(current)
    stage_output = make_stage_output(
        stage=COMPREHENSIVE_RELIABILITY_VALIDATION,
        video_id=str(upstream["video_id"]),
        upstream=[upstream],
        payload={
            "accepted_records": current["output_records"],
            "emitted_pair_count": current["emitted_pair_count"],
        },
        memory_snapshot=current.get("memory_snapshot", {}),
    )
    return {
        **current,
        "comprehensive_reliability_validation_output": stage_output,
    }


def build_four_stage_orchestrator_graph():
    graph = StateGraph(dict)
    nodes = [
        (
            HALLUCINATION_CATEGORY_RETRIEVAL,
            hallucination_category_retrieval,
        ),
        (FACT_EXTRACTION_AND_REFLECTION, fact_extraction_and_reflection),
        (
            GENERATION_AND_VERIFICATION,
            generation_and_verification_of_adversarial_pairs,
        ),
        (
            COMPREHENSIVE_RELIABILITY_VALIDATION,
            comprehensive_reliability_validation,
        ),
    ]
    for name, function in nodes:
        graph.add_node(name, function)
    graph.add_edge(START, nodes[0][0])
    for (left, _), (right, _) in zip(nodes, nodes[1:]):
        graph.add_edge(left, right)
    graph.add_edge(nodes[-1][0], END)
    return graph


build_dataset_construction_graph = build_four_stage_orchestrator_graph
