from pathlib import Path

import jsonschema
import pytest

from videohalo.contracts.internal_schemas import (
    paired_backparse_schema_for,
    realization_schema_for,
)
from videohalo.answer_alignment import validate_question_answer_alignment
from videohalo.graphs.build_orchestrator import answer_pair_realization
from videohalo.live_build import LiveBuildRunner, _require_complete_sentence
from videohalo.taxonomy_first import build_leaf_search_plan


class FakeStructuredModel:
    def __init__(self):
        self.requests = []

    def invoke(self, *, role, request):
        task = request["task_payload"]
        self.requests.append((role, dict(task)))
        if role == "LEAF_OPPORTUNITY_SCOUT":
            return {
                "video_id": task["video_id"],
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
                            [{"start_sec": 0, "end_sec": 2}]
                            if item["leaf_label"] == "AttributeValue"
                            else []
                        ),
                        "anchor_summary": (
                            "The same cup and its color."
                            if item["leaf_label"] == "AttributeValue"
                            else ""
                        ),
                        "decision_reason": "The video evidence was checked.",
                    }
                    for item in task["leaf_checks"]
                ],
            }
        if role == "LEAF_FACT_EXTRACTOR":
            return {
                "facts": [
                    {
                        "source_fact_id": "ignored",
                        "fact_kind": "attribute_value",
                        "natural_language_fact": "The cup is red.",
                        "time_scope": {"start_sec": 0, "end_sec": 2},
                        "normalized_fact": {
                            "fact_kind": "attribute_value",
                            "entity": "cup",
                            "attribute_key": "color",
                            "attribute_value": "red",
                        },
                    }
                ]
            }
        if role == "FACT_REFLECTION":
            return {
                "verdict": "supported",
                "unique_grounding": True,
                "leaf_correct": True,
                "mutation_viable": True,
                "evidence_interval": {"start_sec": 0, "end_sec": 2},
                "evidence_summary": "The red cup is visible.",
                "recoverable_reason": None,
            }
        if role == "LANGUAGE_REALIZER":
            return {
                "replacement_value": "blue",
                "question": task["fixed_question"],
                "answer": "The cup is red.",
                "counterfactual_answer": "The cup is blue.",
            }
        if role == "PAIR_BACKPARSER":
            return {
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
            }
        if role == "CANDIDATE_REFLECTION":
            return {
                "accepted": True,
                "answer_verdict": "supported",
                "counterfactual_verdict": "contradicted",
                "natural_answer_matches_source_fact": True,
                "leaf_boundary_correct": True,
                "counterfactual_targets_planned_leaf": True,
                "single_target_slot": True,
                "additional_error_count": 0,
                "answer_evidence_interval": {
                    "start_sec": 0,
                    "end_sec": 2,
                },
                "evidence_summary": "Only the color is wrong.",
                "recoverable_reason": None,
            }
        raise AssertionError(role)


class OfflineBuildRunner(LiveBuildRunner):
    def _register_and_materialize(self, record):
        return (
            {
                "schema_version": "videohalo_video_manifest_3.7.1",
                "video_id": record["video_id"],
                "source_sha256": "a" * 64,
                "canonical_media_uri": "media://%s/original"
                % record["video_id"],
                "registered_modalities": [
                    "visual",
                    "speech_audio",
                    "non_speech_audio",
                    "on_screen_text",
                    "camera_editing",
                    "container_metadata",
                ],
                "provider_transport": "private_gcs_uri",
                "provider_state": "active",
            },
            "gs://private-bucket/video.mp4",
        )


def test_live_build_runs_source_to_direct_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOHALO_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    source = tmp_path / "video.mp4"
    source.write_bytes(b"fake")
    output = tmp_path / "pairs.jsonl"
    model = FakeStructuredModel()
    result = OfflineBuildRunner(
        output_path=output,
        dataset_id="test",
        profile="probe_build",
        model_client=model,
        media_adapter=object(),
        target_pairs=1,
    ).run(
        [
            {
                "video_id": "video_001",
                "source_path": str(source),
                "task_type": "video_qa",
            }
        ]
    )
    assert result["emitted_pair_count"] == 1
    assert '"leaf_label":"AttributeValue"' in output.read_text(
        encoding="utf-8"
    )
    video_roles = {
        "LEAF_OPPORTUNITY_SCOUT",
        "LEAF_FACT_EXTRACTOR",
        "FACT_REFLECTION",
        "CANDIDATE_REFLECTION",
    }
    assert {
        payload["media_resolution"]
        for role, payload in model.requests
        if role in video_roles
    } == {"high"}


def test_realization_schema_requires_complete_sentence_answers():
    schema = realization_schema_for("attribute_value")
    assert schema["properties"]["answer"]["pattern"] == r"^\S+\s+.+[.!?]$"
    assert (
        schema["properties"]["counterfactual_answer"]["pattern"]
        == r"^\S+\s+.+[.!?]$"
    )


def test_existence_realization_schema_requires_explained_binary_answers():
    schema = realization_schema_for(
        "entity_existence", task_type="video_qa"
    )
    valid = {
        "replacement_value": False,
        "question": "Is the dog present?",
        "answer": "Yes, the dog is present.",
        "counterfactual_answer": "No, the dog is not present.",
    }
    jsonschema.Draft202012Validator(schema).validate(valid)
    valid["answer"] = "The dog is present."
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(valid)


def test_caption_existence_schema_requires_direct_complete_sentences():
    schema = realization_schema_for(
        "entity_existence", task_type="video_captioning"
    )
    valid = {
        "replacement_value": False,
        "question": "Describe one fact visible in the video.",
        "answer": "A gold paint bottle is present on the green background.",
        "counterfactual_answer": (
            "A gold paint bottle is absent from the green background."
        ),
    }
    jsonschema.Draft202012Validator(schema).validate(valid)
    valid["answer"] = "Yes, a gold paint bottle is present."
    jsonschema.Draft202012Validator(schema).validate(valid)
    with pytest.raises(ValueError, match="without a Yes/No prefix"):
        validate_question_answer_alignment(
            task_type="video_captioning",
            fact_kind="entity_existence",
            question=valid["question"],
            answer=valid["answer"],
            counterfactual_answer=valid["counterfactual_answer"],
            supported_fact={
                "fact_kind": "entity_existence",
                "entity": "gold paint bottle",
                "existence": True,
            },
            counterfactual_fact={
                "fact_kind": "entity_existence",
                "entity": "gold paint bottle",
                "existence": False,
            },
        )


def test_existence_question_requires_matching_answer_polarities():
    kwargs = {
        "task_type": "video_qa",
        "fact_kind": "entity_existence",
        "question": "Can the dog be observed here?",
        "answer": "Yes, the dog is present.",
        "counterfactual_answer": "No, the dog is not present.",
        "supported_fact": {
            "fact_kind": "entity_existence",
            "entity": "dog",
            "existence": True,
        },
        "counterfactual_fact": {
            "fact_kind": "entity_existence",
            "entity": "dog",
            "existence": False,
        },
    }
    assert (
        validate_question_answer_alignment(**kwargs)
        == "polar_explained_sentence"
    )
    kwargs["answer"] = "No, the dog is not present."
    with pytest.raises(ValueError, match="polarity disagrees"):
        validate_question_answer_alignment(**kwargs)


def test_nonpolar_videoqa_rejects_yes_no_response_form():
    with pytest.raises(ValueError, match="without a Yes/No prefix"):
        validate_question_answer_alignment(
            task_type="video_qa",
            fact_kind="attribute_value",
            question="What color is the cup?",
            answer="Yes, the cup is red.",
            counterfactual_answer="No, the cup is blue.",
            supported_fact={
                "fact_kind": "attribute_value",
                "entity": "cup",
                "attribute_key": "color",
                "attribute_value": "red",
            },
            counterfactual_fact={
                "fact_kind": "attribute_value",
                "entity": "cup",
                "attribute_key": "color",
                "attribute_value": "blue",
            },
        )


def test_final_realization_gate_rechecks_question_answer_form():
    candidate = {
        "task_type": "video_qa",
        "fact_kind": "entity_existence",
        "question": "Is the dog present?",
        "answer": "The dog is present.",
        "counterfactual_answer": "The dog is not present.",
        "supported_fact": {
            "fact_kind": "entity_existence",
            "entity": "dog",
            "existence": True,
        },
        "counterfactual_fact": {
            "fact_kind": "entity_existence",
            "entity": "dog",
            "existence": False,
        },
    }
    with pytest.raises(ValueError, match="explained Yes/No"):
        answer_pair_realization({"candidates": [candidate]})


def test_camera_realization_requires_a_canonical_predicate_value():
    schema = realization_schema_for("camera_predicate")
    replacement = schema["properties"]["replacement_value"]
    assert "zoom_in" in replacement["enum"]
    assert "no_camera_change" in replacement["enum"]
    assert "stationary" not in replacement["enum"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(
            {
                "replacement_value": "zooms in",
                "question": "Describe one directly observable fact.",
                "answer": "The camera zooms in.",
                "counterfactual_answer": "The camera pans right.",
            }
        )


def test_camera_backparse_allows_denial_only_on_counterfactual_side():
    schema = paired_backparse_schema_for("camera_predicate")
    value = {
        "supported_fact": {
            "fact_kind": "camera_predicate",
            "camera_event": "the opening shot",
            "camera_predicate": "zoom_in",
        },
        "counterfactual_fact": {
            "fact_kind": "camera_predicate",
            "camera_event": "the opening shot",
            "camera_predicate": "no_camera_change",
        },
    }
    jsonschema.Draft202012Validator(schema).validate(value)
    value["supported_fact"]["camera_predicate"] = "no_camera_change"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize("value", ["yellow", "yellow.", "The bib is yellow"])
def test_runtime_rejects_non_sentence_answers(value):
    with pytest.raises(ValueError, match="at least two words"):
        _require_complete_sentence(value, "answer")


@pytest.mark.parametrize(
    "value",
    ["The bib is yellow.", "A dog runs!", "Is the cup red?"],
)
def test_runtime_accepts_complete_sentence_answers(value):
    _require_complete_sentence(value, "answer")


def test_realizer_cannot_change_the_verified_natural_answer():
    runner = object.__new__(LiveBuildRunner)
    runner.selection_seed = 42
    runner.operator_by_leaf = {
        "AttributeValue": {
            "operator_id": "replace_attribute_value",
            "target_leaf": "AttributeValue",
            "fact_kind": "attribute_value",
            "slot": "attribute_value",
        }
    }

    def call(role, payload, schema):
        return {
            "replacement_value": "blue",
            "question": payload["fixed_question"],
            "answer": "The cup is green.",
            "counterfactual_answer": "The cup is blue.",
        }

    runner._call = call
    discovered = {
        "record": {
            "video_id": "video_001",
            "task_type": "video_qa",
        }
    }
    fact = {
        "source_fact_id": "fact_001",
        "fact_kind": "attribute_value",
        "natural_language_fact": "The cup is red.",
        "normalized_fact": {
            "fact_kind": "attribute_value",
            "entity": "the cup",
            "attribute_key": "color",
            "attribute_value": "red",
        },
    }
    with pytest.raises(ValueError, match="verified natural answer"):
        runner._realize(discovered, fact)


def test_realizer_formats_existence_pair_as_explained_polar_answers():
    runner = object.__new__(LiveBuildRunner)
    runner.selection_seed = 42
    runner.operator_by_leaf = {
        "EntityExistence": {
            "operator_id": "toggle_entity_existence",
            "target_leaf": "EntityExistence",
            "fact_kind": "entity_existence",
            "slot": "existence",
        }
    }
    observed = {}

    def call(role, payload, schema):
        observed.update(payload)
        return {
            "replacement_value": False,
            "question": payload["fixed_question"],
            "answer": "Yes, the dog is present.",
            "counterfactual_answer": "No, the dog is not present.",
        }

    runner._call = call
    realized = runner._realize(
        {
            "record": {
                "video_id": "video_001",
                "task_type": "video_qa",
            }
        },
        {
            "source_fact_id": "fact_001",
            "fact_kind": "entity_existence",
            "natural_language_fact": "The dog is present.",
            "normalized_fact": {
                "fact_kind": "entity_existence",
                "entity": "dog",
                "existence": True,
            },
        },
    )
    assert observed["required_answer_form"] == "polar_explained_sentence"
    assert realized["answer_form"] == "polar_explained_sentence"
    assert realized["answer"].startswith("Yes, ")
    assert realized["counterfactual_answer"].startswith("No, ")


def test_realizer_keeps_caption_existence_answers_declarative():
    runner = object.__new__(LiveBuildRunner)
    runner.selection_seed = 42
    runner.operator_by_leaf = {
        "EntityExistence": {
            "operator_id": "toggle_entity_existence",
            "target_leaf": "EntityExistence",
            "fact_kind": "entity_existence",
            "slot": "existence",
        }
    }
    observed = {}

    def call(role, payload, schema):
        observed["payload"] = payload
        observed["schema"] = schema
        return {
            "replacement_value": False,
            "question": payload["fixed_question"],
            "answer": payload["fixed_natural_answer"],
            "counterfactual_answer": (
                "A gold paint bottle is absent from the green background."
            ),
        }

    runner._call = call
    realized = runner._realize(
        {
            "record": {
                "video_id": "captioning_001",
                "task_type": "video_captioning",
            }
        },
        {
            "source_fact_id": "fact_001",
            "fact_kind": "entity_existence",
            "natural_language_fact": (
                "A gold paint bottle is present on the green background."
            ),
            "normalized_fact": {
                "fact_kind": "entity_existence",
                "entity": "gold paint bottle on the green background",
                "existence": True,
            },
        },
    )
    assert observed["payload"]["required_answer_form"] == (
        "caption_complete_sentence"
    )
    assert observed["schema"]["properties"]["answer"]["pattern"] == (
        r"^\S+\s+.+[.!?]$"
    )
    assert realized["answer_form"] == "caption_complete_sentence"
    assert realized["answer"].startswith("A gold paint bottle")


def test_build_reflections_require_high_resolution(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"fake")
    runner = object.__new__(LiveBuildRunner)
    observed = []

    def call(role, payload, schema):
        observed.append((role, payload["media_resolution"]))
        if role == "FACT_REFLECTION":
            return {
                "verdict": "supported",
                "unique_grounding": True,
                "leaf_correct": True,
                "mutation_viable": True,
                "evidence_interval": {"start_sec": 0, "end_sec": 1},
                "evidence_summary": "Visible.",
                "recoverable_reason": None,
            }
        return {
            "accepted": True,
            "answer_verdict": "supported",
            "counterfactual_verdict": "contradicted",
            "natural_answer_matches_source_fact": True,
            "leaf_boundary_correct": True,
            "counterfactual_targets_planned_leaf": True,
            "single_target_slot": True,
            "additional_error_count": 0,
            "answer_evidence_interval": {"start_sec": 0, "end_sec": 1},
            "evidence_summary": "Visible.",
            "recoverable_reason": None,
        }

    runner._call = call
    runner._focused_retry = lambda role, payload, schema, first: first
    runner.leaf_search_plan = build_leaf_search_plan()
    record = {
        "video_id": "video_001",
        "source_path": str(source),
        "task_type": "video_qa",
        "_canonical_source_sha256": "a" * 64,
    }
    fact = {
        "source_fact_id": "fact_001",
        "planned_leaf_label": "AttributeValue",
        "time_scope": {"start_sec": 0, "end_sec": 1},
    }
    runner._verify_fact(
        record,
        "gs://private-bucket/video.mp4",
        fact,
        "FACT_REFLECTION",
    )
    runner._verify_candidate(
        {
            "record": record,
            "native_media_ref": "gs://private-bucket/video.mp4",
        },
        {
            "pair_id": "pair_001",
            "time_scope": {"start_sec": 0, "end_sec": 1},
        },
        "CANDIDATE_REFLECTION",
    )

    assert observed == [
        ("FACT_REFLECTION", "high"),
        ("CANDIDATE_REFLECTION", "high"),
    ]


def test_native_media_ingestion_preserves_dataset_id(monkeypatch):
    from videohalo.graphs import native_media_ingestion

    observed = []

    def materialize(state):
        observed.append(("materialize", state["dataset_id"]))
        return {
            "provider_media_lease": {"provider_media_uri": "gs://bucket/test"},
            "native_media_ref": "gs://bucket/test",
        }

    def persist(state):
        observed.append(("persist", state["dataset_id"]))
        return {"provider_media_lease_ref": {"uri": "artifact://test"}}

    monkeypatch.setattr(
        native_media_ingestion, "materialize_original_video", materialize
    )
    monkeypatch.setattr(native_media_ingestion, "persist_lease", persist)
    result = native_media_ingestion.build_native_media_ingestion_graph().compile().invoke(
        {
            "run_id": "run",
            "dataset_id": "dataset",
            "profile": "probe_build",
            "video_id": "video",
            "source_path": "video.mp4",
            "video_manifest": {},
        }
    )

    assert observed == [("materialize", "dataset"), ("persist", "dataset")]
    assert result["dataset_id"] == "dataset"
