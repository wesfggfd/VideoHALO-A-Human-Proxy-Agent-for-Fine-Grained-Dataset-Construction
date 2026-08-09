import pytest

from videohalo.resolvers.taxonomy import (
    FACT_KIND_TO_LEAF,
    LEAF_TO_SLOT,
    REMOVED_FACT_KINDS,
    Fixed8OutOfScopeError,
    resolve_leaf,
    validate_leaf_slot,
)


def test_all_eight_unique_leaf_slot_mappings():
    assert len(FACT_KIND_TO_LEAF) == len(LEAF_TO_SLOT) == 8
    assert len(set(FACT_KIND_TO_LEAF.values())) == 8
    for fact_kind, leaf in FACT_KIND_TO_LEAF.items():
        assert resolve_leaf(fact_kind) == leaf
        validate_leaf_slot(leaf, LEAF_TO_SLOT[leaf])


@pytest.mark.parametrize("fact_kind", sorted(REMOVED_FACT_KINDS))
def test_removed_fact_kinds_are_out_of_scope_not_remapped(fact_kind):
    with pytest.raises(Fixed8OutOfScopeError):
        resolve_leaf(fact_kind)


def test_only_contradicted_facts_receive_conflict_leaf():
    assert resolve_leaf("attribute_value", verdict="supported") is None
    assert (
        resolve_leaf("attribute_value", verdict="contradicted")
        == "AttributeValue"
    )


def test_leaf_slot_mismatch_fails_closed():
    with pytest.raises(ValueError):
        validate_leaf_slot("ActionPredicate", "attribute_value")
