"""Reflection agent for independent source-fact review."""
from .base import AgentSpec

ROLE = "reflection_agent"
SPEC = AgentSpec(
    role=ROLE,
    stage="fact_extraction_and_reflection",
    thinking_level="high",
    video_access=True,
    purpose=(
        "Independently re-observe the original video and reflect on factual "
        "support, grounding, category boundaries, and mutation viability."
    ),
)
