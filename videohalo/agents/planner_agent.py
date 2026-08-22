"""Planner agent for Hallucination Category Retrieval."""
from .base import AgentSpec

ROLE = "planner_agent"
SPEC = AgentSpec(
    role=ROLE,
    stage="hallucination_category_retrieval",
    thinking_level="high",
    video_access=True,
    purpose=(
        "Inspect the original video and retrieve constructible opportunities "
        "for every Fixed-8 hallucination category."
    ),
)
