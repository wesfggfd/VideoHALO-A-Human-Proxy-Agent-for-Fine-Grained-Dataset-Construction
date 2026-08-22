"""Assemble prompts from frozen policy and filtered dual-layer memory."""
from __future__ import annotations

import json
from typing import Mapping, Optional

from ..agents import AGENT_ROLES
from .core_loader import load_core_memory
from ..models.registry import ModelRegistry


_TAXONOMY_FIRST_ROLES = set(AGENT_ROLES)


def assemble_role_prompt(
    role: str,
    task_payload: Mapping[str, object],
    *,
    memory_snapshot: Optional[Mapping[str, object]] = None,
    extra_policy: Optional[str] = None,
) -> dict:
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
    memory = dict(memory_snapshot or {})
    if memory:
        system += (
            "\n\nSHARED TWO-LAYER MEMORY (structured, append-only):\n"
            + json.dumps(memory, ensure_ascii=False, sort_keys=True)
        )
    return {
        "system": system,
        "role": role,
        "role_contract": role_contract,
        "task_payload": dict(task_payload),
        "memory_snapshot": memory,
        "core_memory_version": core.manifest["core_memory_version"],
        "core_memory_hash": core.manifest_sha256,
    }
