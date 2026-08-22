"""Six canonical VideoHALO agent roles."""
from .extraction_agent import ROLE as EXTRACTION_AGENT
from .generation_agent import ROLE as GENERATION_AGENT
from .monitor_agent import ROLE as MONITOR_AGENT
from .planner_agent import ROLE as PLANNER_AGENT
from .reflection_agent import ROLE as REFLECTION_AGENT
from .registry import AGENT_ROLES, AGENT_SPECS, agent_spec
from .verification_agent import ROLE as VERIFICATION_AGENT

__all__ = [
    "PLANNER_AGENT",
    "EXTRACTION_AGENT",
    "REFLECTION_AGENT",
    "GENERATION_AGENT",
    "VERIFICATION_AGENT",
    "MONITOR_AGENT",
    "AGENT_ROLES",
    "AGENT_SPECS",
    "agent_spec",
]
