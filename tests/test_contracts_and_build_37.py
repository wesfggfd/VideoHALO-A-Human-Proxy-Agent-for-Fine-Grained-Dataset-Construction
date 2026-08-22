import json

import pytest

from videohalo.contracts.leakage import PUBLIC_PAIR_FIELDS, assert_public_item_safe
from videohalo.contracts.registry import ContractRegistry
from videohalo.graph import compiled_graph
from videohalo.graphs.pair_construction import project_direct_record
from videohalo.stores.jsonl import append_pair_jsonl


def test_document_examples_validate():
    registry = ContractRegistry()
    path = (
        registry.schema_root.parent
        / "examples"
        / "public_probe_items_fixed8_examples.jsonl"
    )
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 8
    for record in records:
        assert_public_item_safe(record)


def test_direct_projection_is_exact_nine_fields(candidate):
    record = project_direct_record(candidate)
    assert set(record) == PUBLIC_PAIR_FIELDS
    assert record["leaf_label"] == "AttributeValue"
    assert "source_fact_id" not in record
    assert "monitor_reports" not in record


def test_comprehensive_reliability_validation_is_required(candidate):
    candidate["monitor_reports"][0]["accepted"] = False
    with pytest.raises(
        ValueError,
        match="Comprehensive reliability validation rejected: accepted",
    ):
        project_direct_record(candidate)


def test_candidate_requires_natural_answer_to_match_verified_source(candidate):
    candidate["monitor_reports"][0][
        "natural_answer_matches_source_fact"
    ] = False
    with pytest.raises(
        ValueError,
        match=(
            "Comprehensive reliability validation rejected: "
            "natural answer grounding"
        ),
    ):
        project_direct_record(candidate)


def test_build_emits_immediately_without_audit_artifacts(
    tmp_path, candidate, manifest, fact_graph, reflection_reports, eligibility,
    leaf_search_plan, opportunity_matrix, leaf_conditioned_fact_records
):
    output = tmp_path / "pairs.jsonl"
    state = compiled_graph("probe_build").invoke(
        {
            "run_id": "test",
            "dataset_id": "test",
            "profile": "probe_build",
            "output_path": str(output),
            "video_manifests": [manifest],
            "leaf_search_plan": leaf_search_plan,
            "leaf_opportunity_matrices": [opportunity_matrix],
            "leaf_conditioned_facts": leaf_conditioned_fact_records,
            "fact_graphs": [fact_graph],
            "reflection_reports": reflection_reports,
            "eligibility_records": [eligibility],
            "candidates": [candidate],
        }
    )
    assert state["status"] == "emitted"
    assert state["emitted_pair_count"] == 1
    record = json.loads(output.read_text(encoding="utf-8"))
    assert set(record) == PUBLIC_PAIR_FIELDS
    forbidden = {"human_audit_ref", "private_reference", "batch_unlock_ref"}
    assert not forbidden.intersection(record)


def test_build_rejects_candidate_without_verified_source(
    tmp_path, candidate, manifest, fact_graph, reflection_reports, eligibility,
    leaf_search_plan, opportunity_matrix, leaf_conditioned_fact_records
):
    candidate["source_fact_id"] = "missing"
    with pytest.raises(ValueError, match="verified source fact"):
        compiled_graph("probe_build").invoke(
            {
                "profile": "probe_build",
                "output_path": str(tmp_path / "pairs.jsonl"),
                "video_manifests": [manifest],
                "leaf_search_plan": leaf_search_plan,
                "leaf_opportunity_matrices": [opportunity_matrix],
                "leaf_conditioned_facts": leaf_conditioned_fact_records,
                "fact_graphs": [fact_graph],
                "reflection_reports": reflection_reports,
                "eligibility_records": [eligibility],
                "candidates": [candidate],
            }
        )


def test_build_rejects_fact_evidence_outside_source_scope(
    tmp_path,
    candidate,
    manifest,
    fact_graph,
    reflection_reports,
    eligibility,
    leaf_search_plan,
    opportunity_matrix,
    leaf_conditioned_fact_records,
):
    reflection_reports[0]["evidence_interval"] = {
        "start_sec": 10.0,
        "end_sec": 12.0,
    }
    with pytest.raises(ValueError, match="high-thinking reflection"):
        compiled_graph("probe_build").invoke(
            {
                "profile": "probe_build",
                "output_path": str(tmp_path / "pairs.jsonl"),
                "video_manifests": [manifest],
                "leaf_search_plan": leaf_search_plan,
                "leaf_opportunity_matrices": [opportunity_matrix],
                "leaf_conditioned_facts": leaf_conditioned_fact_records,
                "fact_graphs": [fact_graph],
                "reflection_reports": reflection_reports,
                "eligibility_records": [eligibility],
                "candidates": [candidate],
            }
        )


def test_public_append_enforces_only_the_global_pair_target(
    tmp_path, candidate
):
    output = tmp_path / "pairs.jsonl"
    record = project_direct_record(candidate)
    append_pair_jsonl(output, record, max_records=1)
    second = {
        **record,
        "pair_id": "pair_002",
        "leaf_label": "CameraPredicate",
        "conflict_slot": "camera_predicate",
    }
    with pytest.raises(RuntimeError, match="target"):
        append_pair_jsonl(output, second, max_records=1)
