"""Canonical six-agent registry."""
from __future__ import annotations

from .base import AgentSpec
from .extraction_agent import SPEC as EXTRACTION_AGENT_SPEC
from .generation_agent import SPEC as GENERATION_AGENT_SPEC
from .monitor_agent import SPEC as MONITOR_AGENT_SPEC
from .planner_agent import SPEC as PLANNER_AGENT_SPEC
from .reflection_agent import SPEC as REFLECTION_AGENT_SPEC
from .verification_agent import SPEC as VERIFICATION_AGENT_SPEC

AGENT_SPECS: dict[str, AgentSpec] = {
    spec.role: spec
    for spec in (
        PLANNER_AGENT_SPEC,
        EXTRACTION_AGENT_SPEC,
        REFLECTION_AGENT_SPEC,
        GENERATION_AGENT_SPEC,
        VERIFICATION_AGENT_SPEC,
        MONITOR_AGENT_SPEC,
    )
}
AGENT_ROLES = tuple(AGENT_SPECS)


def agent_spec(role: str) -> AgentSpec:
    try:
        return AGENT_SPECS[role]
    except KeyError as exc:
        raise KeyError("Unknown VideoHALO agent role: %s" % role) from exc
