"""Fail-closed validator for the exact nine-field public pair contract."""
from __future__ import annotations

from typing import Mapping

from .registry import ContractRegistry

PUBLIC_PAIR_FIELDS = frozenset(
    {
        "schema_version",
        "pair_id",
        "media",
        "task_type",
        "question",
        "answer",
        "counterfactual_answer",
        "leaf_label",
        "conflict_slot",
    }
)


class PublicLeakageError(ValueError):
    pass


def assert_public_item_safe(item: Mapping[str, object]) -> None:
    fields = set(item)
    missing = PUBLIC_PAIR_FIELDS - fields
    extra = fields - PUBLIC_PAIR_FIELDS
    if missing or extra:
        raise PublicLeakageError(
            "Direct pair fields mismatch; missing=%s extra=%s"
            % (sorted(missing), sorted(extra))
        )
    try:
        ContractRegistry().validate(
            "videohalo_probe_pair_sample_fixed8.schema.json", dict(item)
        )
    except ValueError as exc:
        raise PublicLeakageError(str(exc)) from exc
