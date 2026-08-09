"""Multimodal evidence-contract gates."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence


class EvidenceGateError(ValueError):
    pass


def validate_evidence_contract(
    contract: Mapping[str, object], *, registered_modalities: Iterable[str],
    cross_modal_status: str = "consistent"
) -> None:
    registered = set(registered_modalities)
    allowed = set(contract.get("allowed_modalities", []))
    required = set(contract.get("required_modalities", []))
    supporting = set(contract.get("supporting_modalities", []))
    if not required.issubset(registered):
        raise EvidenceGateError("Required modalities are not registered: %s" % sorted(required - registered))
    if not required.issubset(allowed):
        raise EvidenceGateError("Required modalities must be allowed")
    if not supporting.issubset(allowed):
        raise EvidenceGateError("Supporting modalities must be allowed")
    if cross_modal_status in {"conflicting", "unreliable", "unknown"}:
        raise EvidenceGateError("Cross-modal evidence is unresolved")


def validate_evidence_windows(windows: Sequence[Mapping[str, object]], duration_ms: int) -> None:
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        if start < 0 or end <= start or end > duration_ms:
            raise EvidenceGateError("Evidence window lies outside the registered timeline")
