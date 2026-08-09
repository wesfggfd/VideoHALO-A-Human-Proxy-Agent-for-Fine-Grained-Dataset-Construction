from __future__ import annotations

import pytest

from videohalo.taxonomy_first import (
    build_leaf_search_plan,
    leaf_conditioned_facts,
)


@pytest.fixture
def media():
    return {
        "video_id": "video_001",
        "canonical_media_uri": "media://video_001/original",
        "registered_modalities": [
            "visual",
            "speech_audio",
            "non_speech_audio",
            "on_screen_text",
            "camera_editing",
            "container_metadata",
        ],
        "evidence_policy_id": "gemini_native_original_video_v1",
    }


@pytest.fixture
def manifest(media):
    return {
        "schema_version": "videohalo_video_manifest_3.7.1",
        "video_id": media["video_id"],
        "source_sha256": "a" * 64,
        "canonical_media_uri": media["canonical_media_uri"],
        "registered_modalities": media["registered_modalities"],
        "provider_transport": "private_gcs_uri",
        "provider_state": "active",
    }


@pytest.fixture
def fact_graph():
    return {
        "schema_version": "videohalo_fact_graph_fixed8_3.7.0",
        "video_id": "video_001",
        "status": "surrogate_verified",
        "facts": [
            {
                "source_fact_id": "fact_001",
                "fact_kind": "attribute_value",
                "leaf_label": "AttributeValue",
                "conflict_slot": "attribute_value",
                "natural_language_fact": "The cup is red.",
                "time_scope": {"start_sec": 0.0, "end_sec": 2.0},
                "verifier_consensus": {
                    "accepted": True,
                    "verifier_count": 1,
                },
            }
        ],
    }


@pytest.fixture
def fact_verifier_reports():
    return [
        {
            "video_id": "video_001",
            "source_fact_id": "fact_001",
            "verifier_role": role,
            "verdict": "supported",
            "unique_grounding": True,
            "leaf_correct": True,
            "mutation_viable": True,
            "evidence_interval": {"start_sec": 0.0, "end_sec": 2.0},
            "evidence_summary": "The red cup is visible.",
            "shares_observations": False,
        }
        for role in ("FACT_REFLECTION",)
    ]


@pytest.fixture
def leaf_search_plan():
    return build_leaf_search_plan()


@pytest.fixture
def opportunity_matrix(leaf_search_plan):
    return {
        "schema_version": "videohalo_leaf_opportunity_matrix_3.7.2",
        "video_id": "video_001",
        "opportunities": [
            {
                "leaf_label": item["leaf_label"],
                "fact_kind": item["fact_kind"],
                "conflict_slot": item["conflict_slot"],
                "constructibility": (
                    "constructible"
                    if item["leaf_label"] == "AttributeValue"
                    else "not_constructible"
                ),
                "evidence_intervals": (
                    [{"start_sec": 0.0, "end_sec": 2.0}]
                    if item["leaf_label"] == "AttributeValue"
                    else []
                ),
                "anchor_summary": (
                    "The same cup and its color."
                    if item["leaf_label"] == "AttributeValue"
                    else ""
                ),
                "decision_reason": "Fixture decision.",
            }
            for item in leaf_search_plan["leaves"]
        ],
    }


@pytest.fixture
def leaf_conditioned_fact_records(opportunity_matrix):
    raw = [
        {
            "source_fact_id": "fact_001",
            "fact_kind": "attribute_value",
            "natural_language_fact": "The cup is red.",
            "time_scope": {"start_sec": 0.0, "end_sec": 2.0},
            "normalized_fact": {
                "fact_kind": "attribute_value",
                "entity": "cup",
                "attribute_key": "color",
                "attribute_value": "red",
            },
        }
    ]
    return leaf_conditioned_facts(raw, matrix=opportunity_matrix)


@pytest.fixture
def eligibility():
    return {
        "video_id": "video_001",
        "source_fact_id": "fact_001",
        "task_type": "video_qa",
        "leaf_label": "AttributeValue",
        "eligible": True,
        "reason": "eligible",
    }


@pytest.fixture
def candidate(media):
    reports = [
        {
            "verifier_role": role,
            "accepted": True,
            "answer_verdict": "supported",
            "counterfactual_verdict": "contradicted",
            "natural_answer_matches_source_fact": True,
            "leaf_boundary_correct": True,
            "counterfactual_targets_planned_leaf": True,
            "single_target_slot": True,
            "additional_error_count": 0,
            "answer_evidence_interval": {
                "start_sec": 0.0,
                "end_sec": 2.0,
            },
            "evidence_summary": "The natural answer matches the red cup.",
            "shares_observations": False,
        }
        for role in ("CANDIDATE_REFLECTION",)
    ]
    return {
        "pair_id": "pair_001",
        "source_fact_id": "fact_001",
        "fact_kind": "attribute_value",
        "media": media,
        "task_type": "video_qa",
        "question": "What color is the cup?",
        "answer": "The cup is red.",
        "counterfactual_answer": "The cup is blue.",
        "supported_fact": {
            "fact_kind": "attribute_value",
            "entity": "cup",
            "attribute_key": "color",
            "attribute_value": "red",
        },
        "counterfactual_fact": {
            "fact_kind": "attribute_value",
            "entity": "cup",
            "attribute_key": "color",
            "attribute_value": "blue",
        },
        "leaf_label": "AttributeValue",
        "conflict_slot": "attribute_value",
        "time_scope": {"start_sec": 0.0, "end_sec": 2.0},
        "graph_diff": {
            "changed_atomic_fact_count": 1,
            "changed_slot_count": 1,
            "changed_paths": ["attribute_value"],
        },
        "supported_contradicted_count": 0,
        "counterfactual_contradicted_count": 1,
        "additional_error_count": 0,
        "candidate_verifier_reports": reports,
    }
