"""Deterministic, task-specific question-template selection."""
from __future__ import annotations

import hashlib
from typing import Mapping

from .policy.loader import load_core_memory
from .resolvers.taxonomy import FACT_KIND_TO_LEAF


_REFERENTIAL_DETERMINERS = {
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "my",
    "your",
    "his",
    "her",
    "its",
    "our",
    "their",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
}
_REFERENTIAL_PRONOUNS = {
    "he",
    "she",
    "it",
    "they",
    "we",
    "you",
    "i",
    "him",
    "her",
    "them",
}


def _referential_phrase(value: object) -> str:
    """Make a normalized video entity grammatical in a fixed question."""
    phrase = str(value).replace("_", " ").strip()
    if not phrase:
        return phrase
    first = phrase.split(maxsplit=1)[0]
    lowered = first.lower()
    if (
        lowered in _REFERENTIAL_DETERMINERS
        or lowered in _REFERENTIAL_PRONOUNS
        or first[:1].isupper()
        or first[:1].isdigit()
    ):
        return phrase
    return "the " + phrase


def _pick(values: list[str], *, key: str) -> str:
    if not values:
        raise ValueError("Question-template bank is empty")
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return values[int.from_bytes(digest[:8], "big") % len(values)]


def question_for_fact(
    *,
    task_type: str,
    video_id: str,
    source_fact_id: str,
    normalized_fact: Mapping[str, object],
    seed: int,
) -> tuple[str, str]:
    """Return the frozen question and its auditable template identifier."""
    templates = load_core_memory().yaml("surface_templates")
    fact_kind = str(normalized_fact["fact_kind"])
    leaf = FACT_KIND_TO_LEAF[fact_kind]
    key = f"{video_id}|{source_fact_id}|{leaf}|{task_type}|{seed}"
    if task_type == "video_captioning":
        values = list(templates["video_captioning"]["questions"])
        template = _pick(values, key=key)
        return template, f"video_captioning:{values.index(template)}"
    if task_type != "video_qa":
        raise ValueError("Unsupported task type for question realization")
    if fact_kind == "action_predicate" and normalized_fact.get("object") is None:
        values = list(templates["video_qa"]["null_object_templates"])
    else:
        values = list(
            templates["video_qa"]["question_templates"][leaf]
        )
    template = _pick(values, key=key)
    fields = {
        name: str(value).replace("_", " ")
        for name, value in normalized_fact.items()
        if name != "fact_kind"
    }
    for name in ("entity", "subject", "object"):
        if name in fields:
            fields[name] = _referential_phrase(fields[name])
    question = template.format(**fields)
    return question, f"video_qa:{leaf}:{values.index(template)}"
