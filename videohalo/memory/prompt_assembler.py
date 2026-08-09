"""Assemble role prompts exclusively from hash-verified frozen policy memory."""
from __future__ import annotations

from typing import Mapping, Optional

from .core_loader import load_core_memory
from ..models.registry import ModelRegistry


_TAXONOMY_FIRST_ROLES = {
    "LEAF_OPPORTUNITY_SCOUT",
    "LEAF_FACT_EXTRACTOR",
    "FACT_REFLECTION",
    "LANGUAGE_REALIZER",
    "PAIR_BACKPARSER",
    "CANDIDATE_REFLECTION",
}


def assemble_role_prompt(role: str, task_payload: Mapping[str, object], *, extra_policy: Optional[str] = None) -> dict:
    if extra_policy:
        raise ValueError("Runtime or empirical policy injection is forbidden")
    core = load_core_memory()
    role_contract = ModelRegistry().role(role)
    system = core.text("system_prompt")
    if role in _TAXONOMY_FIRST_ROLES:
        system += (
            "\n\nFROZEN TAXONOMY-FIRST LEAF SEARCH PLAN:\n"
            + core.text("leaf_search_plan")
        )
    return {
        "system": system,
        "role": role,
        "role_contract": role_contract,
        "task_payload": dict(task_payload),
        "core_memory_version": core.manifest["core_memory_version"],
        "core_memory_hash": core.manifest_sha256,
    }
