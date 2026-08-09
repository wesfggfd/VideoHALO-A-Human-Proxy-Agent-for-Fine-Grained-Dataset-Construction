"""Frozen-operator, one-fact/one-slot mutation enforcement."""
from __future__ import annotations

from typing import Mapping

from ..policy.loader import load_core_memory
from ..resolvers.graph_diff import assert_single_slot_change
from ..resolvers.taxonomy import FACT_KIND_TO_LEAF


class MutationError(ValueError):
    pass


def validate_mutation(operator_id: str, original: Mapping[str, object], mutated: Mapping[str, object]) -> dict:
    config = load_core_memory().json("mutation_operators_json")
    operators = config.get("operators", config.get("mutation_operators", []))
    operator = next((item for item in operators if item.get("operator_id") == operator_id), None)
    if operator is None:
        raise MutationError("Unknown frozen mutation operator: %s" % operator_id)
    diff = assert_single_slot_change(original, mutated)
    fact_kind = str(mutated.get("fact_kind") or original.get("fact_kind"))
    leaf = FACT_KIND_TO_LEAF.get(fact_kind)
    expected = operator.get("target_leaf") or operator.get("target_leaf_label") or operator.get("leaf_label")
    if expected and leaf != expected:
        raise MutationError("Mutation operator/leaf mismatch")
    changed_path = diff["changed_paths"][0]
    changed_slot = changed_path.rsplit(".", 1)[-1]
    if changed_slot != operator.get("slot"):
        raise MutationError(
            "Mutation changed %s but operator requires %s"
            % (changed_slot, operator.get("slot"))
        )
    return {"operator_id": operator_id, "target_leaf_label": leaf, "graph_diff": diff}
