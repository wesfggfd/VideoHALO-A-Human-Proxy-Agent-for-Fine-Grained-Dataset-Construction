"""Append-only two-layer memory shared by all six VideoHALO agents."""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from ..agents import AGENT_ROLES

SYSTEM_COGNITIVE_MEMORY = "system_cognitive_memory"
CATEGORY_MEMORY = "category_memory"
MEMORY_LAYERS = (SYSTEM_COGNITIVE_MEMORY, CATEGORY_MEMORY)


@dataclass
class DualLayerMemory:
    """Keep global cognitive traces and category-conditioned traces separate."""

    system_cognitive_memory: list[dict] = field(default_factory=list)
    category_memory: dict[str, list[dict]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def contribute(
        self,
        *,
        agent_role: str,
        stage: str,
        video_id: str,
        categories: Iterable[str],
        content: Mapping[str, object],
    ) -> None:
        if agent_role not in AGENT_ROLES:
            raise ValueError("Unknown memory contributor: %s" % agent_role)
        normalized_categories = tuple(
            dict.fromkeys(str(item) for item in categories if str(item))
        ) or ("global",)
        base = {
            "agent_role": agent_role,
            "stage": stage,
            "video_id": video_id,
            "content": copy.deepcopy(dict(content)),
        }
        self.system_cognitive_memory.append(
            {**base, "memory_layer": SYSTEM_COGNITIVE_MEMORY}
        )
        for category in normalized_categories:
            self.category_memory[category].append(
                {
                    **base,
                    "memory_layer": CATEGORY_MEMORY,
                    "category": category,
                }
            )

    def snapshot(
        self,
        categories: Iterable[str] = (),
        *,
        video_id: str | None = None,
        limit: int = 8,
    ) -> dict:
        """Return a bounded, task-relevant view for the next agent call."""
        if limit < 1:
            raise ValueError("Memory snapshot limit must be positive")
        selected = tuple(
            dict.fromkeys(str(item) for item in categories if str(item))
        )
        system_entries = self.system_cognitive_memory
        if video_id:
            system_entries = [
                item
                for item in system_entries
                if item.get("video_id") == video_id
            ]
        category_entries = {
            category: copy.deepcopy(
                self.category_memory.get(category, [])[-limit:]
            )
            for category in selected
        }
        if not selected and self.category_memory:
            category_entries = {
                category: copy.deepcopy(entries[-limit:])
                for category, entries in self.category_memory.items()
            }
        return {
            SYSTEM_COGNITIVE_MEMORY: copy.deepcopy(
                system_entries[-limit:]
            ),
            CATEGORY_MEMORY: category_entries,
        }
