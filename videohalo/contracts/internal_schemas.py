"""Internal structured-output schemas for production Gemini adapters.

These are runtime implementation contracts, not public dataset contracts and
not additions to the frozen semantic policy bundle.
"""
from __future__ import annotations

from typing import Optional

FACT_KINDS = [
    "entity_existence",
    "entity_category",
    "entity_quantity",
    "attribute_value",
    "static_relation",
    "action_predicate",
    "temporal_relation",
    "camera_predicate",
]
CAMERA_SOURCE_PREDICATES = [
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "zoom_in",
    "zoom_out",
    "cut",
    "focus_change",
    "framing_change",
    "viewpoint_change",
]
CAMERA_COUNTERFACTUAL_PREDICATES = CAMERA_SOURCE_PREDICATES + [
    "no_camera_change",
]

LEAF_BY_FACT_KIND = {
    "entity_existence": "EntityExistence",
    "entity_category": "EntityCategory",
    "entity_quantity": "EntityQuantity",
    "attribute_value": "AttributeValue",
    "static_relation": "StaticRelation",
    "action_predicate": "ActionPredicate",
    "temporal_relation": "TemporalRelation",
    "camera_predicate": "CameraPredicate",
}

SLOT_BY_FACT_KIND = {
    "entity_existence": "existence",
    "entity_category": "category",
    "entity_quantity": "count",
    "attribute_value": "attribute_value",
    "static_relation": "relation_predicate",
    "action_predicate": "predicate",
    "temporal_relation": "order",
    "camera_predicate": "camera_predicate",
}

NORMALIZED_FACT_CONTRACTS = {
    "entity_existence": {
        "required": ["fact_kind", "entity", "existence"],
        "properties": {
            "fact_kind": {"const": "entity_existence"},
            "entity": {"type": "string", "minLength": 1},
            "existence": {"type": "boolean"},
        },
    },
    "entity_category": {
        "required": ["fact_kind", "entity", "category"],
        "properties": {
            "fact_kind": {"const": "entity_category"},
            "entity": {"type": "string", "minLength": 1},
            "category": {"type": "string", "minLength": 1},
        },
    },
    "entity_quantity": {
        "required": ["fact_kind", "entity_set", "count"],
        "properties": {
            "fact_kind": {"const": "entity_quantity"},
            "entity_set": {"type": "string", "minLength": 1},
            "count": {"type": "integer", "minimum": 0},
        },
    },
    "attribute_value": {
        "required": [
            "fact_kind",
            "entity",
            "attribute_key",
            "attribute_value",
        ],
        "properties": {
            "fact_kind": {"const": "attribute_value"},
            "entity": {"type": "string", "minLength": 1},
            "attribute_key": {"type": "string", "minLength": 1},
            "attribute_value": {
                "type": ["string", "number", "boolean"],
            },
        },
    },
    "static_relation": {
        "required": [
            "fact_kind",
            "subject",
            "relation_predicate",
            "object",
        ],
        "properties": {
            "fact_kind": {"const": "static_relation"},
            "subject": {"type": "string", "minLength": 1},
            "relation_predicate": {"type": "string", "minLength": 1},
            "object": {"type": "string", "minLength": 1},
        },
    },
    "action_predicate": {
        "required": ["fact_kind", "subject", "predicate", "object"],
        "properties": {
            "fact_kind": {"const": "action_predicate"},
            "subject": {"type": "string", "minLength": 1},
            "predicate": {"type": "string", "minLength": 1},
            "object": {"type": ["string", "null"]},
        },
    },
    "temporal_relation": {
        "required": ["fact_kind", "event_a", "order", "event_b"],
        "properties": {
            "fact_kind": {"const": "temporal_relation"},
            "event_a": {"type": "string", "minLength": 1},
            "order": {"enum": ["before", "after"]},
            "event_b": {"type": "string", "minLength": 1},
        },
    },
    "camera_predicate": {
        "required": ["fact_kind", "camera_event", "camera_predicate"],
        "properties": {
            "fact_kind": {"const": "camera_predicate"},
            "camera_event": {"type": "string", "minLength": 1},
            "camera_predicate": {"enum": CAMERA_SOURCE_PREDICATES},
        },
    },
}
TIME_SCOPE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["start_sec", "end_sec"],
    "properties": {
        "start_sec": {"type": "number", "minimum": 0},
        "end_sec": {"type": "number", "minimum": 0},
    },
}

COMPLETE_SENTENCE_SCHEMA = {
    "type": "string",
    "minLength": 4,
    "pattern": r"^\S+\s+.+[.!?]$",
}
EXPLAINED_BINARY_SENTENCE_SCHEMA = {
    "type": "string",
    "minLength": 8,
    "pattern": r"^(?:Yes|No),\s+\S+\s+.+[.!?]$",
}


def _fact_proposal_branch(fact_kind: str) -> dict:
    normalized = NORMALIZED_FACT_CONTRACTS[fact_kind]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_fact_id",
            "fact_kind",
            "natural_language_fact",
            "time_scope",
            "normalized_fact",
        ],
        "properties": {
            "source_fact_id": {"type": "string", "minLength": 1},
            "fact_kind": {"const": fact_kind},
            "natural_language_fact": dict(COMPLETE_SENTENCE_SCHEMA),
            "time_scope": TIME_SCOPE,
            "normalized_fact": {
                "type": "object",
                "additionalProperties": False,
                "required": normalized["required"],
                "properties": normalized["properties"],
            },
        },
    }


FACT_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "oneOf": [
                    _fact_proposal_branch(fact_kind)
                    for fact_kind in FACT_KINDS
                ]
            },
        }
    },
}

LEAF_OPPORTUNITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["video_id", "opportunities"],
    "properties": {
        "video_id": {"type": "string", "minLength": 1},
        "opportunities": {
            "type": "array",
            "minItems": 8,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "leaf_label",
                    "fact_kind",
                    "conflict_slot",
                    "constructibility",
                    "evidence_intervals",
                    "anchor_summary",
                    "decision_reason",
                ],
                "properties": {
                    "leaf_label": {
                        "enum": list(LEAF_BY_FACT_KIND.values())
                    },
                    "fact_kind": {"enum": FACT_KINDS},
                    "conflict_slot": {
                        "enum": list(SLOT_BY_FACT_KIND.values())
                    },
                    "constructibility": {
                        "enum": [
                            "constructible",
                            "not_constructible",
                            "uncertain",
                        ]
                    },
                    "evidence_intervals": {
                        "type": "array",
                        "maxItems": 2,
                        "items": TIME_SCOPE,
                    },
                    "anchor_summary": {"type": "string"},
                    "decision_reason": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}

FACT_VERIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "unique_grounding",
        "leaf_correct",
        "mutation_viable",
        "evidence_interval",
        "evidence_summary",
        "recoverable_reason",
    ],
    "properties": {
        "verdict": {"enum": ["supported", "contradicted", "insufficient"]},
        "unique_grounding": {"type": "boolean"},
        "leaf_correct": {"type": "boolean"},
        "mutation_viable": {"type": "boolean"},
        "evidence_interval": {"anyOf": [TIME_SCOPE, {"type": "null"}]},
        "evidence_summary": {"type": "string"},
        "recoverable_reason": {
            "type": ["string", "null"],
            "enum": [
                "fine_visual_detail",
                "visible_text",
                "prompt_scope",
                "recoverable_review_disagreement",
                None,
            ],
        },
    },
}

def normalized_fact_schema(
    fact_kind: str,
    *,
    counterfactual: bool = False,
) -> dict:
    try:
        contract = NORMALIZED_FACT_CONTRACTS[fact_kind]
    except KeyError as exc:
        raise ValueError(f"Unknown Fixed-8 fact kind: {fact_kind}") from exc
    properties = dict(contract["properties"])
    if fact_kind == "camera_predicate" and counterfactual:
        properties["camera_predicate"] = {
            "enum": CAMERA_COUNTERFACTUAL_PREDICATES
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(contract["required"]),
        "properties": properties,
    }


def realization_schema_for(
    fact_kind: str,
    *,
    task_type: Optional[str] = None,
) -> dict:
    if task_type not in {None, "video_captioning", "video_qa"}:
        raise ValueError("Unsupported task type for realization schema")
    slot = SLOT_BY_FACT_KIND[fact_kind]
    if fact_kind == "camera_predicate":
        replacement_schema = {
            "enum": CAMERA_COUNTERFACTUAL_PREDICATES
        }
    else:
        replacement_schema = dict(
            NORMALIZED_FACT_CONTRACTS[fact_kind]["properties"][slot]
        )
    replacement_schema.pop("const", None)
    answer_schema = (
        EXPLAINED_BINARY_SENTENCE_SCHEMA
        if fact_kind == "entity_existence"
        and task_type != "video_captioning"
        else COMPLETE_SENTENCE_SCHEMA
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "replacement_value",
            "question",
            "answer",
            "counterfactual_answer",
        ],
        "properties": {
            "replacement_value": replacement_schema,
            "question": {"type": "string", "minLength": 1},
            "answer": dict(answer_schema),
            "counterfactual_answer": dict(answer_schema),
        },
    }


def backparse_schema_for(fact_kind: str) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["fact"],
        "properties": {"fact": normalized_fact_schema(fact_kind)},
    }


def paired_backparse_schema_for(fact_kind: str) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["supported_fact", "counterfactual_fact"],
        "properties": {
            "supported_fact": normalized_fact_schema(fact_kind),
            "counterfactual_fact": normalized_fact_schema(
                fact_kind,
                counterfactual=True,
            ),
        },
    }


# Full unions remain available to contract introspection, while live calls use
# the smaller fact-kind-specific schemas above.
REALIZATION_SCHEMA = {
    "oneOf": [realization_schema_for(fact_kind) for fact_kind in FACT_KINDS]
}
BACKPARSE_SCHEMA = {
    "oneOf": [backparse_schema_for(fact_kind) for fact_kind in FACT_KINDS]
}

CANDIDATE_VERIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "accepted",
        "answer_verdict",
        "counterfactual_verdict",
        "natural_answer_matches_source_fact",
        "leaf_boundary_correct",
        "counterfactual_targets_planned_leaf",
        "single_target_slot",
        "additional_error_count",
        "answer_evidence_interval",
        "evidence_summary",
        "recoverable_reason",
    ],
    "properties": {
        "accepted": {"type": "boolean"},
        "answer_verdict": {
            "enum": ["supported", "contradicted", "insufficient"]
        },
        "counterfactual_verdict": {
            "enum": ["supported", "contradicted", "insufficient"]
        },
        "natural_answer_matches_source_fact": {"type": "boolean"},
        "leaf_boundary_correct": {"type": "boolean"},
        "counterfactual_targets_planned_leaf": {"type": "boolean"},
        "single_target_slot": {"type": "boolean"},
        "additional_error_count": {"type": "integer", "minimum": 0},
        "answer_evidence_interval": {
            "anyOf": [TIME_SCOPE, {"type": "null"}]
        },
        "evidence_summary": {"type": "string"},
        "recoverable_reason": {
            "type": ["string", "null"],
            "enum": [
                "fine_visual_detail",
                "visible_text",
                "prompt_scope",
                "recoverable_review_disagreement",
                None,
            ],
        },
    },
}
