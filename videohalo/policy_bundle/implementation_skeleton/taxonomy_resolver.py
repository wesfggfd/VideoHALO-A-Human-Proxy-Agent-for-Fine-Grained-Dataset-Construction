FACT_KIND_TO_LEAF = {
    "entity_existence": "EntityExistence",
    "entity_category": "EntityCategory",
    "entity_quantity": "EntityQuantity",
    "attribute_value": "AttributeValue",
    "static_relation": "StaticRelation",
    "action_predicate": "ActionPredicate",
    "temporal_relation": "TemporalRelation",
    "camera_predicate": "CameraPredicate",
}
LEAF_TO_SLOT = {
    "EntityExistence": "existence",
    "EntityCategory": "category",
    "EntityQuantity": "count",
    "AttributeValue": "attribute_value",
    "StaticRelation": "relation_predicate",
    "ActionPredicate": "predicate",
    "TemporalRelation": "order",
    "CameraPredicate": "camera_predicate",
}

class Fixed8OutOfScopeError(ValueError):
    pass

def resolve_leaf(fact_kind: str) -> str:
    try:
        return FACT_KIND_TO_LEAF[fact_kind]
    except KeyError as exc:
        raise Fixed8OutOfScopeError(f"Fact kind is outside Fixed-8: {fact_kind}") from exc

def validate_leaf_slot(leaf: str, slot: str) -> None:
    if LEAF_TO_SLOT.get(leaf) != slot:
        raise ValueError(f"Invalid Fixed-8 leaf/slot pair: {leaf}/{slot}")
