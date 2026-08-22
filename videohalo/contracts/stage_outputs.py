"""Structured communication contract for the four VideoHALO subtasks."""
from __future__ import annotations

import copy
from typing import Iterable, Mapping, Optional

from ..agents import (
    EXTRACTION_AGENT,
    GENERATION_AGENT,
    MONITOR_AGENT,
    PLANNER_AGENT,
    REFLECTION_AGENT,
    VERIFICATION_AGENT,
)

STAGE_OUTPUT_SCHEMA_VERSION = "videohalo_structured_stage_output_1.0"
HALLUCINATION_CATEGORY_RETRIEVAL = "hallucination_category_retrieval"
FACT_EXTRACTION_AND_REFLECTION = "fact_extraction_and_reflection"
GENERATION_AND_VERIFICATION = (
    "generation_and_verification_of_adversarial_pairs"
)
COMPREHENSIVE_RELIABILITY_VALIDATION = (
    "comprehensive_reliability_validation"
)

STAGE_PRODUCERS: dict[str, tuple[str, ...]] = {
    HALLUCINATION_CATEGORY_RETRIEVAL: (PLANNER_AGENT,),
    FACT_EXTRACTION_AND_REFLECTION: (
        EXTRACTION_AGENT,
        REFLECTION_AGENT,
    ),
    GENERATION_AND_VERIFICATION: (
        GENERATION_AGENT,
        VERIFICATION_AGENT,
    ),
    COMPREHENSIVE_RELIABILITY_VALIDATION: (MONITOR_AGENT,),
}
STAGES = tuple(STAGE_PRODUCERS)


def make_stage_output(
    *,
    stage: str,
    video_id: str,
    payload: Mapping[str, object],
    upstream: Optional[Iterable[Mapping[str, object]]] = None,
    memory_snapshot: Optional[Mapping[str, object]] = None,
) -> dict:
    """Create one serializable stage envelope for downstream agents."""
    if stage not in STAGE_PRODUCERS:
        raise ValueError("Unknown VideoHALO stage: %s" % stage)
    if not video_id:
        raise ValueError("Stage output requires video_id")
    envelope = {
        "schema_version": STAGE_OUTPUT_SCHEMA_VERSION,
        "stage": stage,
        "video_id": video_id,
        "producer_agents": list(STAGE_PRODUCERS[stage]),
        "upstream_stages": [
            str(item.get("stage")) for item in (upstream or ())
        ],
        "payload": copy.deepcopy(dict(payload)),
        "memory_snapshot": copy.deepcopy(dict(memory_snapshot or {})),
    }
    return validate_stage_output(envelope, expected_stage=stage)


def validate_stage_output(
    value: Mapping[str, object], *, expected_stage: Optional[str] = None
) -> dict:
    output = copy.deepcopy(dict(value))
    stage = str(output.get("stage") or "")
    if expected_stage is not None and stage != expected_stage:
        raise ValueError("Structured stage output has an unexpected stage")
    if output.get("schema_version") != STAGE_OUTPUT_SCHEMA_VERSION:
        raise ValueError("Structured stage output has an unknown schema")
    if stage not in STAGE_PRODUCERS:
        raise ValueError("Structured stage output has an unknown stage")
    if output.get("producer_agents") != list(STAGE_PRODUCERS[stage]):
        raise ValueError("Structured stage output has incorrect producers")
    if not str(output.get("video_id") or ""):
        raise ValueError("Structured stage output requires video_id")
    if not isinstance(output.get("payload"), dict):
        raise ValueError("Structured stage output payload must be an object")
    if not isinstance(output.get("memory_snapshot"), dict):
        raise ValueError("Structured stage memory snapshot must be an object")
    if not isinstance(output.get("upstream_stages"), list):
        raise ValueError("Structured stage upstream_stages must be an array")
    return output
