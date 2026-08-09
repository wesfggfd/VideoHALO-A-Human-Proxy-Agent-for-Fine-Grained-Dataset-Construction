"""Deterministic atomic-fact graph diff and single-error validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class SlotChange:
    fact_index: int
    slot_path: str
    before: Any
    after: Any


@dataclass(frozen=True)
class GraphDiffResult:
    changed_atomic_fact_count: int
    changed_slot_count: int
    changes: Tuple[SlotChange, ...]


class GraphDiffError(ValueError):
    pass


def _flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
    output = {}
    if isinstance(value, Mapping):
        for key in sorted(value):
            path = "%s.%s" % (prefix, key) if prefix else str(key)
            output.update(_flatten(value[key], path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            output.update(_flatten(item, "%s[%d]" % (prefix, index)))
    else:
        output[prefix] = value
    return output


def diff_atomic_facts(
    supported: Sequence[Mapping[str, Any]], counterfactual: Sequence[Mapping[str, Any]]
) -> GraphDiffResult:
    if len(supported) != len(counterfactual):
        raise GraphDiffError("Variant fact counts differ")
    changes = []
    changed_facts = set()
    for index, pair in enumerate(zip(supported, counterfactual)):
        left, right = pair
        left_flat, right_flat = _flatten(left), _flatten(right)
        if set(left_flat) != set(right_flat):
            raise GraphDiffError("Fact %d has different slot structure" % index)
        for path in sorted(left_flat):
            if left_flat[path] != right_flat[path]:
                changed_facts.add(index)
                changes.append(SlotChange(index, path, left_flat[path], right_flat[path]))
    return GraphDiffResult(len(changed_facts), len(changes), tuple(changes))


def assert_single_slot_change(
    original: Mapping[str, Any], mutated: Mapping[str, Any]
) -> dict:
    """Validate and serialize the frozen one-fact/one-slot mutation invariant."""
    diff = diff_atomic_facts([original], [mutated])
    if diff.changed_atomic_fact_count != 1 or diff.changed_slot_count != 1:
        raise GraphDiffError("Mutation must change exactly one atomic fact and one slot")
    return {
        "changed_atomic_fact_count": diff.changed_atomic_fact_count,
        "changed_slot_count": diff.changed_slot_count,
        "changed_paths": [change.slot_path for change in diff.changes],
    }


def assert_core_single_error(
    *, diff: GraphDiffResult, supported_contradicted_claim_count: int,
    counterfactual_contradicted_claim_count: int, additional_error_count: int,
    blocked_dependency_count: int, unresolved_modality_conflict_count: int = 0,
    true_elsewhere: bool = False
) -> None:
    checks = {
        "changed_atomic_fact_count": diff.changed_atomic_fact_count == 1,
        "changed_slot_count": diff.changed_slot_count == 1,
        "supported_contradicted_claim_count": supported_contradicted_claim_count == 0,
        "counterfactual_contradicted_claim_count": counterfactual_contradicted_claim_count == 1,
        "additional_error_count": additional_error_count == 0,
        "blocked_dependency_count": blocked_dependency_count == 0,
        "unresolved_modality_conflict_count": unresolved_modality_conflict_count == 0,
        "true_elsewhere": true_elsewhere is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise GraphDiffError("Single-error invariant failed: %s" % ", ".join(failed))
