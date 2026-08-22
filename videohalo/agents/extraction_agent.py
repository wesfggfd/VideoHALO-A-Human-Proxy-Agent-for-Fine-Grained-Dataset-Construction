"""Extraction agent for grounded atomic-fact extraction."""
from .base import AgentSpec

ROLE = "extraction_agent"
SPEC = AgentSpec(
    role=ROLE,
    stage="fact_extraction_and_reflection",
    thinking_level="high",
    video_access=True,
    purpose=(
        "Read the original video and extract grounded atomic facts from the "
        "structured category-retrieval output."
    ),
)
