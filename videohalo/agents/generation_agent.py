"""Generation agent for adversarial question-answer pairs."""
from .base import AgentSpec

ROLE = "generation_agent"
SPEC = AgentSpec(
    role=ROLE,
    stage="generation_and_verification_of_adversarial_pairs",
    thinking_level="low",
    video_access=False,
    purpose=(
        "Consume verified structured facts, select the category-conditioned "
        "question template, mutate one conflict slot, and generate the full "
        "factual/counterfactual question-answer pair."
    ),
)
