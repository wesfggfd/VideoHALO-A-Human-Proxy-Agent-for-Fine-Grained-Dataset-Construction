"""Taxonomy-first planning, opportunity, and one-slot mutation contracts."""
from __future__ import annotations

import copy
from collections import Counter
from typing import Iterable, Mapping

from .contracts.internal_schemas import (
    CAMERA_COUNTERFACTUAL_PREDICATES,
    CAMERA_SOURCE_PREDICATES,
    NORMALIZED_FACT_CONTRACTS,
)
from .policy.loader import load_core_memory
from .resolvers.taxonomy import FACT_KIND_TO_LEAF, LEAF_TO_SLOT


CONSTRUCTIBILITY = {
    "constructible",
    "not_constructible",
    "uncertain",
}


def build_leaf_search_plan() -> dict:
    """Load and cross-check the frozen eight-leaf search prior."""
    core = load_core_memory()
    plan = core.json("leaf_search_plan")
    taxonomy = core.json("taxonomy_json")
    operators = core.json("mutation_operators_json")["operators"]
    taxonomy_rows = {
        item["leaf"]: (
            item["fact_kind"],
            item["conflict_slot"],
        )
        for item in taxonomy["leaves"]
    }
    plan_rows = {
        item["leaf_label"]: (
            item["fact_kind"],
            item["conflict_slot"],
        )
        for item in plan["leaves"]
    }
    operator_rows = {
        item["target_leaf"]: (item["fact_kind"], item["slot"])
        for item in operators
    }
    if taxonomy_rows != plan_rows or taxonomy_rows != operator_rows:
        raise ValueError(
            "Taxonomy, leaf-search plan, and mutation operators disagree"
        )
    if set(plan_rows) != set(LEAF_TO_SLOT):
        raise ValueError("Leaf-search plan must contain every Fixed-8 leaf")
    for leaf, (fact_kind, slot) in plan_rows.items():
        if FACT_KIND_TO_LEAF.get(fact_kind) != leaf:
            raise ValueError("Leaf-search plan contains a resolver mismatch")
        contract = NORMALIZED_FACT_CONTRACTS.get(fact_kind)
        if contract is None or slot not in contract["required"]:
            raise ValueError("Leaf-search plan contains an invalid slot")
    camera_rule = next(
        item
        for item in plan["leaves"]
        if item["leaf_label"] == "CameraPredicate"
    )
    if camera_rule.get("source_predicates") != CAMERA_SOURCE_PREDICATES:
        raise ValueError(
            "CameraPredicate source predicates disagree with the runtime schema"
        )
    if (
        camera_rule.get("counterfactual_predicates")
        != CAMERA_COUNTERFACTUAL_PREDICATES
    ):
        raise ValueError(
            "CameraPredicate counterfactual predicates disagree with the "
            "runtime schema"
        )
    return copy.deepcopy(plan)


def validate_opportunity_matrix(
    value: Mapping[str, object],
    *,
    plan: Mapping[str, object],
) -> dict:
    rows = [dict(item) for item in value.get("opportunities", [])]
    expected = {
        item["leaf_label"]: item for item in plan["leaves"]
    }
    if len(rows) != len(expected):
        raise ValueError("Opportunity matrix must contain exactly eight rows")
    observed = Counter(str(item.get("leaf_label")) for item in rows)
    if set(observed) != set(expected) or any(count != 1 for count in observed.values()):
        raise ValueError(
            "Opportunity matrix must scan every Fixed-8 leaf exactly once"
        )
    normalized = []
    for item in rows:
        rule = expected[item["leaf_label"]]
        if (
            item.get("fact_kind") != rule["fact_kind"]
            or item.get("conflict_slot") != rule["conflict_slot"]
        ):
            raise ValueError("Opportunity row disagrees with frozen taxonomy")
        status = str(item.get("constructibility"))
        if status not in CONSTRUCTIBILITY:
            raise ValueError("Unknown constructibility status")
        intervals = [dict(interval) for interval in item.get("evidence_intervals", [])]
        if status == "constructible" and not intervals:
            raise ValueError(
                "Constructible opportunity requires an evidence interval"
            )
        if status != "constructible":
            # Non-constructible rows never enter fact extraction.  Some
            # structured-output models still populate an optional evidence
            # field after correctly deciding that a leaf is unavailable.
            # Canonicalize that dead field away so it cannot become a source
            # claim or trigger a costly whole-video retry.
            intervals = []
            item = {**item, "anchor_summary": ""}
        if status == "constructible" and not str(
            item.get("anchor_summary", "")
        ).strip():
            raise ValueError(
                "Constructible opportunity requires a canonical anchor"
            )
        normalized.append(
            {
                **item,
                "evidence_intervals": intervals,
            }
        )
    return {
        "schema_version": "videohalo_leaf_opportunity_matrix_3.7.2",
        "video_id": str(value["video_id"]),
        "opportunities": normalized,
    }


def leaf_conditioned_facts(
    facts: Iterable[Mapping[str, object]],
    *,
    matrix: Mapping[str, object],
) -> list[dict]:
    """Keep at most one well-scoped fact for each constructible leaf."""
    constructible = {
        item["leaf_label"]: item
        for item in matrix["opportunities"]
        if item["constructibility"] == "constructible"
    }
    accepted = []
    seen_leaves = set()
    for raw in facts:
        fact = dict(raw)
        fact_kind = str(fact.get("fact_kind"))
        leaf = FACT_KIND_TO_LEAF.get(fact_kind)
        opportunity = constructible.get(leaf)
        if opportunity is None or leaf in seen_leaves:
            continue
        scope = dict(fact.get("time_scope") or {})
        start = scope.get("start_sec")
        end = scope.get("end_sec")
        if start is None or end is None or float(end) < float(start):
            continue
        overlaps = any(
            float(start) <= float(interval["end_sec"])
            and float(end) >= float(interval["start_sec"])
            for interval in opportunity["evidence_intervals"]
        )
        if not overlaps:
            continue
        normalized = dict(fact.get("normalized_fact") or {})
        contract = NORMALIZED_FACT_CONTRACTS[fact_kind]
        if (
            normalized.get("fact_kind") != fact_kind
            or set(normalized) != set(contract["required"])
        ):
            continue
        if (
            fact_kind == "camera_predicate"
            and normalized.get("camera_predicate")
            not in CAMERA_SOURCE_PREDICATES
        ):
            continue
        accepted.append(
            {
                **fact,
                "planned_leaf_label": leaf,
                "planned_conflict_slot": LEAF_TO_SLOT[leaf],
                "opportunity_anchor": opportunity["anchor_summary"],
            }
        )
        seen_leaves.add(leaf)
    return accepted


def apply_slot_replacement(
    original: Mapping[str, object],
    *,
    replacement_value: object,
) -> dict:
    """Copy an atomic fact and replace only its frozen conflict slot."""
    fact_kind = str(original.get("fact_kind"))
    leaf = FACT_KIND_TO_LEAF.get(fact_kind)
    if leaf is None:
        raise ValueError("Cannot mutate an out-of-scope fact kind")
    slot = LEAF_TO_SLOT[leaf]
    if replacement_value == original.get(slot):
        raise ValueError("Replacement value must differ from the source value")
    if (
        fact_kind == "camera_predicate"
        and replacement_value not in CAMERA_COUNTERFACTUAL_PREDICATES
    ):
        raise ValueError(
            "CameraPredicate replacement must be a controlled camera/edit "
            "change or the explicit denial no_camera_change"
        )
    mutated = copy.deepcopy(dict(original))
    mutated[slot] = replacement_value
    if set(mutated) != set(original):
        raise ValueError("Mutation changed the normalized fact structure")
    return mutated
