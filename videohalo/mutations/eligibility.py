"""Deterministic Fixed-8 build eligibility gate."""
from __future__ import annotations

from typing import Mapping

from ..contracts.registry import ContractRegistry
from ..resolvers.taxonomy import FACT_KIND_TO_LEAF, Fixed8OutOfScopeError


def evaluate_eligibility(
    fact: Mapping[str, object],
    *,
    video_id: str,
    task_type: str,
    reflection_accepted: bool,
    dependency_evaluable: bool,
    alternative_count: int,
) -> dict:
    fact_kind = str(fact.get("fact_kind"))
    if fact_kind not in FACT_KIND_TO_LEAF:
        raise Fixed8OutOfScopeError(
            "Excluded fact kinds do not enter the Fixed-8 eligibility census"
        )
    reasons = []
    if not reflection_accepted:
        reasons.append("fact_reflection_missing")
    if not dependency_evaluable:
        reasons.append("dependency_not_evaluable")
    if alternative_count < 1:
        reasons.append("no_grounded_counterfactual_alternative")
    if fact.get("verdict", "supported") != "supported":
        reasons.append("source_fact_not_supported")
    record = {
        "video_id": video_id,
        "source_fact_id": str(
            fact.get("source_fact_id") or fact.get("fact_id")
        ),
        "task_type": task_type,
        "leaf_label": FACT_KIND_TO_LEAF[fact_kind],
        "eligible": not reasons,
        "reason": "eligible" if not reasons else ";".join(reasons),
    }
    ContractRegistry().validate("eligibility_record_fixed8.schema.json", record)
    return record
