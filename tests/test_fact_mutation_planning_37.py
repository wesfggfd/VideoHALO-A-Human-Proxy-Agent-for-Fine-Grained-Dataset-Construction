import pytest

from videohalo.graph import compiled_graph
from videohalo.mutations.eligibility import evaluate_eligibility
from videohalo.mutations.engine import MutationError, validate_mutation
from videohalo.planning import select_faithful_relative
from videohalo.resolvers.taxonomy import Fixed8OutOfScopeError


def test_fact_graph_accepts_only_isolated_unanimous_fixed8_facts():
    proposed = [
        {
            "source_fact_id": "f1",
            "fact_kind": "action_predicate",
            "natural_language_fact": "A person runs.",
            "time_scope": {"start_sec": 0, "end_sec": 1},
        },
        {
            "source_fact_id": "f2",
            "fact_kind": "action_binding",
            "natural_language_fact": "A person opens the door.",
            "time_scope": {"start_sec": 0, "end_sec": 1},
        },
    ]
    reports = [
        {
            "source_fact_id": "f1",
            "agent_role": role,
            "verdict": "supported",
            "unique_grounding": True,
                "leaf_correct": True,
                "mutation_viable": True,
                "evidence_interval": {"start_sec": 0, "end_sec": 1},
                "evidence_summary": "The person is visibly running.",
                "shares_observations": False,
        }
        for role in ("reflection_agent",)
    ]
    state = compiled_graph("fact_graph_build").invoke(
        {
            "video_id": "v1",
            "proposed_facts": proposed,
            "reflection_reports": reports,
        }
    )
    assert [item["source_fact_id"] for item in state["fact_graph"]["facts"]] == [
        "f1"
    ]


def test_removed_fact_cannot_enter_eligibility():
    with pytest.raises(Fixed8OutOfScopeError):
        evaluate_eligibility(
            {"source_fact_id": "f", "fact_kind": "causal_relation"},
            video_id="v",
            task_type="video_qa",
            reflection_accepted=True,
            dependency_evaluable=True,
            alternative_count=1,
        )


def test_mutation_must_change_the_operator_slot():
    original = {"fact_kind": "attribute_value", "attribute_value": "red"}
    mutated = {"fact_kind": "attribute_value", "attribute_value": "blue"}
    result = validate_mutation("replace_attribute_value", original, mutated)
    assert result["graph_diff"]["changed_slot_count"] == 1
    wrong = {"fact_kind": "attribute_value", "category": "blue"}
    with pytest.raises(Exception):
        validate_mutation("replace_attribute_value", original, wrong)


def test_faithful_relative_selection_does_not_fabricate_or_duplicate_cells():
    records = [
        {
            "video_id": "v1",
            "source_fact_id": "f1",
            "leaf_label": "AttributeValue",
            "eligible": True,
        },
        {
            "video_id": "v1",
            "source_fact_id": "f2",
            "leaf_label": "AttributeValue",
            "eligible": True,
        },
        {
            "video_id": "v1",
            "source_fact_id": "f3",
            "leaf_label": "ActionPredicate",
            "eligible": True,
        },
        {
            "video_id": "v2",
            "source_fact_id": "f4",
            "leaf_label": "EntityQuantity",
            "eligible": False,
        },
    ]
    selected = select_faithful_relative(records, per_video_pair_cap=2)
    assert len(selected) == 2
    assert {item["leaf_label"] for item in selected} == {
        "AttributeValue",
        "ActionPredicate",
    }


def test_selection_softly_prefers_a_real_underrepresented_leaf():
    records = [
        {
            "video_id": "v1",
            "source_fact_id": "f1",
            "leaf_label": "AttributeValue",
            "eligible": True,
        },
        {
            "video_id": "v1",
            "source_fact_id": "f2",
            "leaf_label": "CameraPredicate",
            "eligible": True,
        },
    ]
    selected = select_faithful_relative(
        records,
        target_pairs=1,
        per_video_pair_cap=1,
        current_leaf_counts={
            "AttributeValue": 30,
            "CameraPredicate": 2,
        },
    )
    assert [item["leaf_label"] for item in selected] == ["CameraPredicate"]
