"""Canonical public contracts for VideoHALO agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ThinkingLevel = Literal["low", "high"]


@dataclass(frozen=True)
class AgentSpec:
    """Describe one agent without binding it to a provider implementation."""

    role: str
    stage: str
    thinking_level: ThinkingLevel
    video_access: bool
    purpose: str
    contributes_to: tuple[str, str] = (
        "system_cognitive_memory",
        "category_memory",
    )
