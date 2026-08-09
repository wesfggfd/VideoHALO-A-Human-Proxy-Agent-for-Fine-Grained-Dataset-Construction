from pathlib import Path

import pytest

import videohalo
from videohalo.graph import build_graph
from videohalo.graph import compiled_graph
from videohalo.cli import build_parser
from videohalo.models.registry import ModelRegistry
from videohalo.policy.loader import load_core_memory


def test_frozen_37_policy_and_exact_fixed8():
    core = load_core_memory()
    taxonomy = core.json("taxonomy_json")
    assert videohalo.__version__ == "3.7.0"
    assert core.manifest["core_memory_version"] == "3.7.5"
    assert core.manifest["taxonomy_version"] == "VHal-Fixed8-3.7"
    assert len(core.asset_paths) == 10
    assert len(taxonomy["leaves"]) == 8
    assert set(taxonomy["excluded_fact_kinds"]) == {
        "entity_reference",
        "action_binding",
        "causal_relation",
    }


def test_model_roles_use_build_reflection():
    registry = ModelRegistry()
    assert registry.version == "3.7.3"
    for role in ("FACT_REFLECTION", "CANDIDATE_REFLECTION"):
        assert registry.role(role)["thinking_level"] == "high"


def test_deleted_runtime_graphs_are_not_registered():
    for name in ("review_packaging", "human_audit_unlock", "freeze_batch"):
        with pytest.raises(ValueError):
            build_graph(name)


def test_build_graph_exposes_documented_phases():
    build_nodes = set(compiled_graph("probe_build").get_graph().nodes)
    assert {
        "canonical_media_registration",
        "private_gcs_materialization",
        "taxonomy_first_plan",
        "eight_leaf_opportunity_scan",
        "leaf_conditioned_fact_extraction",
        "fact_reflection",
        "fixed8_eligibility_scan",
        "one_slot_mutation",
        "backparse_both_answers",
        "graph_diff",
        "candidate_reflection",
        "direct_pair_projection",
        "append_public_pair_jsonl",
    }.issubset(build_nodes)


def test_cli_has_no_deleted_review_or_unlock_commands():
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if getattr(action, "choices", None)
    )
    assert set(subparsers.choices) == {
        "policy-validate",
        "register",
        "build",
        "validate",
    }
