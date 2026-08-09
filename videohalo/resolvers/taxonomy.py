"""Normative Fixed-8 fact-kind, leaf and conflict-slot resolver."""
from __future__ import annotations

from typing import Dict, Literal, Optional

LeafLabel = Literal[
    "EntityExistence",
    "EntityCategory",
    "EntityQuantity",
    "AttributeValue",
    "StaticRelation",
    "ActionPredicate",
    "TemporalRelation",
    "CameraPredicate",
]

FACT_KIND_TO_LEAF: Dict[str, LeafLabel] = {
    "entity_existence": "EntityExistence",
    "entity_category": "EntityCategory",
    "entity_quantity": "EntityQuantity",
    "attribute_value": "AttributeValue",
    "static_relation": "StaticRelation",
    "action_predicate": "ActionPredicate",
    "temporal_relation": "TemporalRelation",
    "camera_predicate": "CameraPredicate",
}

LEAF_TO_SLOT: Dict[LeafLabel, str] = {
    "EntityExistence": "existence",
    "EntityCategory": "category",
    "EntityQuantity": "count",
    "AttributeValue": "attribute_value",
    "StaticRelation": "relation_predicate",
    "ActionPredicate": "predicate",
    "TemporalRelation": "order",
    "CameraPredicate": "camera_predicate",
}

REMOVED_FACT_KINDS = frozenset(
    {"entity_reference", "action_binding", "causal_relation"}
)


class Fixed8OutOfScopeError(ValueError):
    """Raised when a structural type is not part of Fixed-8."""


def resolve_leaf(
    fact_kind: Optional[str] = None,
    *,
    verdict: Optional[str] = None,
    dependency_gates_passed: bool = True,
    modality_gate_passed: bool = True,
) -> Optional[LeafLabel]:
    """Resolve a fact kind without semantically remapping excluded structures."""
    if verdict is not None and verdict != "contradicted":
        return None
    if not dependency_gates_passed or not modality_gate_passed:
        raise Fixed8OutOfScopeError("Evidence/dependency gate did not pass")
    try:
        return FACT_KIND_TO_LEAF[str(fact_kind)]
    except KeyError as exc:
        raise Fixed8OutOfScopeError(
            "Fact kind is outside Fixed-8: %r" % fact_kind
        ) from exc


def validate_leaf_slot(leaf_label: str, conflict_slot: str) -> None:
    expected = LEAF_TO_SLOT.get(leaf_label)  # type: ignore[arg-type]
    if expected is None:
        raise Fixed8OutOfScopeError("Unknown Fixed-8 leaf: %r" % leaf_label)
    if conflict_slot != expected:
        raise ValueError(
            "Leaf/slot mismatch: %s requires %s, got %s"
            % (leaf_label, expected, conflict_slot)
        )


# Compatibility alias for non-runtime integrations written against 3.6.
TaxonomyResolutionError = Fixed8OutOfScopeError
