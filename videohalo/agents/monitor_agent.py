"""Monitor agent for comprehensive reliability validation."""
from .base import AgentSpec

ROLE = "monitor_agent"
SPEC = AgentSpec(
    role=ROLE,
    stage="comprehensive_reliability_validation",
    thinking_level="high",
    video_access=True,
    purpose=(
        "Re-read the original video and evaluate the complete adversarial "
        "pair for factual support, contradiction, category correctness, and "
        "single-error reliability."
    ),
)
