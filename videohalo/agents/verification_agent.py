"""Verification agent for adversarial-pair structural back-parsing."""
from .base import AgentSpec

ROLE = "verification_agent"
SPEC = AgentSpec(
    role=ROLE,
    stage="generation_and_verification_of_adversarial_pairs",
    thinking_level="low",
    video_access=False,
    purpose=(
        "Back-parse both answers into supported and counterfactual facts and "
        "verify the one-fact, one-slot structural difference."
    ),
)
