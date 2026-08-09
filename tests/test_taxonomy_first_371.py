from __future__ import annotations

import pytest

from videohalo.surface_templates import question_for_fact
from videohalo.taxonomy_first import (
    apply_slot_replacement,
    build_leaf_search_plan,
    leaf_conditioned_facts,
    validate_opportunity_matrix,
)


def _matrix():
    plan = build_leaf_search_plan()
    return plan, {
        "video_id": "video_001",
        "opportunities": [
            {
                "leaf_label": item["leaf_label"],
                "fact_kind": item["fact_kind"],
                "conflict_slot": item["conflict_slot"],
                "constructibility": (
                    "constructible"
                    if item["leaf_label"] in {
                        "AttributeValue",
                        "CameraPredicate",
                    }
                    else "not_constructible"
                ),
                "evidence_intervals": (
                    [{"start_sec": 1.0, "end_sec": 3.0}]
                    if item["leaf_label"] in {
                        "AttributeValue",
                        "CameraPredicate",
                    }
                    else []
                ),
                "anchor_summary": (
                    "A stable atomic anchor."
                    if item["leaf_label"] in {
                        "AttributeValue",
                        "CameraPredicate",
                    }
                    else ""
                ),
                "decision_reason": "Each frozen leaf was checked.",
            }
            for item in plan["leaves"]
        ],
    }


def test_taxonomy_plan_and_matrix_scan_exactly_eight_leaves():
    plan, matrix = _matrix()
    normalized = validate_opportunity_matrix(matrix, plan=plan)
    assert len(plan["leaves"]) == 8
    assert len(normalized["opportunities"]) == 8
    assert len(
        {item["leaf_label"] for item in normalized["opportunities"]}
    ) == 8
    with pytest.raises(ValueError, match="exactly eight"):
        validate_opportunity_matrix(
            {
                **matrix,
                "opportunities": matrix["opportunities"][:-1],
            },
            plan=plan,
        )


def test_non_constructible_rows_discard_dead_evidence_fields():
    plan, matrix = _matrix()
    row = next(
        item
        for item in matrix["opportunities"]
        if item["leaf_label"] == "EntityExistence"
    )
    row["evidence_intervals"] = [{"start_sec": 4.0, "end_sec": 5.0}]
    row["anchor_summary"] = "This must not become a source claim."

    normalized = validate_opportunity_matrix(matrix, plan=plan)
    normalized_row = next(
        item
        for item in normalized["opportunities"]
        if item["leaf_label"] == "EntityExistence"
    )
    assert normalized_row["constructibility"] == "not_constructible"
    assert normalized_row["evidence_intervals"] == []
    assert normalized_row["anchor_summary"] == ""


def test_leaf_conditioned_factbank_does_not_relabel_or_duplicate_a_leaf():
    plan, matrix = _matrix()
    matrix = validate_opportunity_matrix(matrix, plan=plan)
    base = {
        "fact_kind": "attribute_value",
        "natural_language_fact": "The cup is red.",
        "time_scope": {"start_sec": 1.0, "end_sec": 2.0},
        "normalized_fact": {
            "fact_kind": "attribute_value",
            "entity": "cup",
            "attribute_key": "color",
            "attribute_value": "red",
        },
    }
    facts = leaf_conditioned_facts(
        [
            {"source_fact_id": "f1", **base},
            {"source_fact_id": "f2", **base},
            {
                "source_fact_id": "f3",
                "fact_kind": "entity_quantity",
                "natural_language_fact": "Two cups are visible.",
                "time_scope": {"start_sec": 1.0, "end_sec": 2.0},
                "normalized_fact": {
                    "fact_kind": "entity_quantity",
                    "entity_set": "cups",
                    "count": 2,
                },
            },
        ],
        matrix=matrix,
    )
    assert [item["source_fact_id"] for item in facts] == ["f1"]
    assert facts[0]["planned_leaf_label"] == "AttributeValue"


def test_camera_mutation_changes_only_the_frozen_predicate():
    original = {
        "fact_kind": "camera_predicate",
        "camera_event": "the opening shot",
        "camera_predicate": "zoom_in",
    }
    mutated = apply_slot_replacement(
        original,
        replacement_value="pan_left",
    )
    assert mutated == {
        **original,
        "camera_predicate": "pan_left",
    }
    assert original["camera_predicate"] == "zoom_in"


def test_camera_counterfactual_can_deny_an_observed_change():
    original = {
        "fact_kind": "camera_predicate",
        "camera_event": "the opening shot",
        "camera_predicate": "zoom_in",
    }
    assert apply_slot_replacement(
        original,
        replacement_value="no_camera_change",
    ) == {
        **original,
        "camera_predicate": "no_camera_change",
    }


def test_stationary_camera_is_not_an_eligible_supported_source_fact():
    plan, matrix = _matrix()
    matrix = validate_opportunity_matrix(matrix, plan=plan)
    facts = leaf_conditioned_facts(
        [
            {
                "source_fact_id": "camera_stationary",
                "fact_kind": "camera_predicate",
                "natural_language_fact": "The camera remains stationary.",
                "time_scope": {"start_sec": 1.0, "end_sec": 2.0},
                "normalized_fact": {
                    "fact_kind": "camera_predicate",
                    "camera_event": "the opening shot",
                    "camera_predicate": "stationary",
                },
            }
        ],
        matrix=matrix,
    )
    assert facts == []


@pytest.mark.parametrize(
    "fact",
    [
        {
            "fact_kind": "entity_existence",
            "entity": "a dog",
            "existence": True,
        },
        {
            "fact_kind": "entity_category",
            "entity": "the vehicle",
            "category": "car",
        },
        {
            "fact_kind": "entity_quantity",
            "entity_set": "people",
            "count": 2,
        },
        {
            "fact_kind": "attribute_value",
            "entity": "the cup",
            "attribute_key": "color",
            "attribute_value": "red",
        },
        {
            "fact_kind": "static_relation",
            "subject": "the cup",
            "relation_predicate": "left_of",
            "object": "the plate",
        },
        {
            "fact_kind": "action_predicate",
            "subject": "the person",
            "predicate": "opens",
            "object": "the door",
        },
        {
            "fact_kind": "temporal_relation",
            "event_a": "opening the door",
            "order": "before",
            "event_b": "walking outside",
        },
        {
            "fact_kind": "camera_predicate",
            "camera_event": "the opening shot",
            "camera_predicate": "zoom_in",
        },
    ],
)
def test_every_leaf_has_a_renderable_videoqa_template(fact):
    question, template_id = question_for_fact(
        task_type="video_qa",
        video_id="video_001",
        source_fact_id=fact["fact_kind"],
        normalized_fact=fact,
        seed=42,
    )
    assert question.endswith("?") or question.endswith(".")
    assert template_id.startswith("video_qa:")


def test_both_tasks_use_deterministic_but_diverse_question_templates():
    fact = {
        "fact_kind": "attribute_value",
        "entity": "the cup",
        "attribute_key": "color",
        "attribute_value": "red",
    }
    qa = set()
    captioning = set()
    for index in range(64):
        for task, output in (
            ("video_qa", qa),
            ("video_captioning", captioning),
        ):
            first = question_for_fact(
                task_type=task,
                video_id=f"video_{index:03d}",
                source_fact_id="fact_001",
                normalized_fact=fact,
                seed=42,
            )
            second = question_for_fact(
                task_type=task,
                video_id=f"video_{index:03d}",
                source_fact_id="fact_001",
                normalized_fact=fact,
                seed=42,
            )
            assert first == second
            output.add(first)
    assert len(qa) >= 6
    assert len(captioning) >= 10


def test_videoqa_templates_make_bare_entity_phrases_referential():
    fact = {
        "fact_kind": "action_predicate",
        "subject": "young man",
        "predicate": "dribbles",
        "object": "basketball",
    }
    questions = {
        question_for_fact(
            task_type="video_qa",
            video_id=f"video_{index:03d}",
            source_fact_id="fact_001",
            normalized_fact=fact,
            seed=42,
        )[0]
        for index in range(128)
    }
    assert len(questions) == 6
    assert all("the young man" in question for question in questions)
    assert all("the basketball" in question for question in questions)
    assert all(" by young man" not in question for question in questions)
