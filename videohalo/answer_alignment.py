"""Question-to-answer form contracts for direct probe-pair output."""
from __future__ import annotations

import re
from typing import Mapping


_POLAR_QUESTION_RE = re.compile(
    r"^(?:is|are|was|were|does|do|did|can|could|has|have|had)\b",
    re.IGNORECASE,
)
_BINARY_PREFIX_RE = re.compile(r"^(?:yes|no)\b", re.IGNORECASE)
_EXPLAINED_BINARY_RE = re.compile(
    r"^(?:yes|no),\s+\S+\s+.+[.!?]$",
    re.IGNORECASE,
)


def answer_form_for(*, task_type: str, fact_kind: str) -> str:
    """Return the frozen answer-form family for a task/fact combination."""
    if task_type == "video_captioning":
        return "caption_complete_sentence"
    if task_type != "video_qa":
        raise ValueError("Unsupported task type for answer alignment")
    if fact_kind == "entity_existence":
        return "polar_explained_sentence"
    return "direct_complete_sentence"


def answer_alignment_instruction(
    *,
    task_type: str,
    fact_kind: str,
    supported_fact: Mapping[str, object],
) -> str:
    """Give the realizer an explicit, auditable surface-form constraint."""
    answer_form = answer_form_for(
        task_type=task_type,
        fact_kind=fact_kind,
    )
    if answer_form == "caption_complete_sentence":
        return (
            "The prompt requests a caption-like observation. Copy "
            "fixed_natural_answer exactly as the supported answer. Render the "
            "counterfactual as a complete sentence with the same grammatical "
            "frame, changing only the target slot. Neither answer may begin "
            "with Yes or No."
        )
    if answer_form == "polar_explained_sentence":
        supported_prefix = (
            "Yes" if bool(supported_fact.get("existence")) else "No"
        )
        counterfactual_prefix = "No" if supported_prefix == "Yes" else "Yes"
        return (
            "The fixed question is polar. The supported answer must begin "
            f"exactly with '{supported_prefix}, ' and the counterfactual "
            f"answer must begin exactly with '{counterfactual_prefix}, '. "
            "After each prefix, restate the entity and the corresponding "
            "presence or absence as a self-contained complete sentence. Bare "
            "Yes/No answers and a declarative answer without the polarity "
            "prefix are forbidden."
        )
    return (
        "The fixed question requests a value, relation, action, order, or "
        "camera/edit operation. Copy fixed_natural_answer exactly as the "
        "supported answer. Render the counterfactual in the same direct "
        "complete-sentence frame, changing only the target slot. Neither "
        "answer may begin with Yes or No."
    )


def validate_question_answer_alignment(
    *,
    task_type: str,
    fact_kind: str,
    question: str,
    answer: str,
    counterfactual_answer: str,
    supported_fact: Mapping[str, object],
    counterfactual_fact: Mapping[str, object],
) -> str:
    """Reject pairs whose response form does not match the frozen question."""
    answer_form = answer_form_for(
        task_type=task_type,
        fact_kind=fact_kind,
    )
    question = question.strip()
    answer = answer.strip()
    counterfactual_answer = counterfactual_answer.strip()

    if answer_form == "polar_explained_sentence":
        if not _POLAR_QUESTION_RE.match(question):
            raise ValueError(
                "EntityExistence VideoQA must use a polar question"
            )
        for field_name, value, fact in (
            ("answer", answer, supported_fact),
            (
                "counterfactual_answer",
                counterfactual_answer,
                counterfactual_fact,
            ),
        ):
            if not _EXPLAINED_BINARY_RE.fullmatch(value):
                raise ValueError(
                    f"{field_name} must be an explained Yes/No sentence"
                )
            expected = "Yes" if bool(fact.get("existence")) else "No"
            actual = value.split(",", 1)[0].title()
            if actual != expected:
                raise ValueError(
                    f"{field_name} polarity disagrees with entity existence"
                )
        return answer_form

    for field_name, value in (
        ("answer", answer),
        ("counterfactual_answer", counterfactual_answer),
    ):
        if _BINARY_PREFIX_RE.match(value):
            raise ValueError(
                f"{field_name} must directly answer the non-polar prompt "
                "without a Yes/No prefix"
            )
    return answer_form
