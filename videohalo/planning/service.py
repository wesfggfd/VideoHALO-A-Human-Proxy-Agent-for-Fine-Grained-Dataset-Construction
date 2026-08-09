"""Faithful-relative selection without class fabrication or forced balancing."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Iterable, Optional

def _stable_rank(record: dict, seed: int) -> str:
    value = "%s|%s|%s|%d" % (
        record["video_id"],
        record["source_fact_id"],
        record["leaf_label"],
        seed,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def select_faithful_relative(
    eligibility_records: Iterable[dict],
    *,
    target_pairs: Optional[int] = None,
    per_video_pair_cap: int = 2,
    seed: int = 42,
    current_leaf_counts: Optional[dict[str, int]] = None,
) -> list[dict]:
    """Select real eligible supply while gently preferring rare leaves.

    A video can contribute at most one pair to a given leaf.  No record is
    relabelled, and an absent leaf is never synthesized.
    """
    if per_video_pair_cap < 1:
        raise ValueError("per_video_pair_cap must be positive")
    eligible = [dict(item) for item in eligibility_records if item.get("eligible")]
    supply = Counter(item["leaf_label"] for item in eligible)
    current_leaves = Counter(current_leaf_counts or {})
    ordered = sorted(
        eligible,
        key=lambda item: (
            current_leaves[item["leaf_label"]],
            supply[item["leaf_label"]],
            _stable_rank(item, seed),
        ),
    )
    selected: list[dict] = []
    video_counts: Counter = Counter()
    video_leaves: dict[str, set[str]] = defaultdict(set)
    limit = len(ordered) if target_pairs is None else max(0, target_pairs)
    for item in ordered:
        video_id = item["video_id"]
        leaf = item["leaf_label"]
        if video_counts[video_id] >= per_video_pair_cap:
            continue
        if leaf in video_leaves[video_id]:
            continue
        selected.append(item)
        video_counts[video_id] += 1
        video_leaves[video_id].add(leaf)
        if len(selected) >= limit:
            break
    return selected


def build_dataset_plan(
    *,
    dataset_id: str,
    profile: str,
    planning_round_id: str,
    eligibility_records: Iterable[dict],
    target_pairs: Optional[int] = None,
    per_video_pair_cap: int = 2,
    selection_seed: int = 42,
    **_: object,
) -> dict:
    selected = select_faithful_relative(
        eligibility_records,
        target_pairs=target_pairs,
        per_video_pair_cap=per_video_pair_cap,
        seed=selection_seed,
    )
    return {
        "schema_version": "videohalo_faithful_relative_plan_3.7.0",
        "dataset_id": dataset_id,
        "profile": profile,
        "planning_round_id": planning_round_id,
        "selection_seed": selection_seed,
        "selection_count": len(selected),
        "observed_leaf_distribution": dict(
            Counter(item["leaf_label"] for item in selected)
        ),
        "reservations": selected,
    }
