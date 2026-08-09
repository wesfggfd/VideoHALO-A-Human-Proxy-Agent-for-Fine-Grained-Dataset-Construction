"""Bounded same-video native adequacy and focused retry routing."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..media.ingestion_policy import ACCEPTED_NATIVE_STATUSES, NativeEvidenceStatus
from ..state import NativeEvidenceState

RECOVERABLE_REASONS = {
    "fine_visual_detail", "visible_text", "prompt_scope", "recoverable_verifier_disagreement",
}
FORBIDDEN_RETRY_KEYS = {"target_leaf", "target_leaf_label", "mutation", "pair_role", "other_role_verdicts"}


def _contains_forbidden(value) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_RETRY_KEYS.intersection(value)) or any(_contains_forbidden(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden(child) for child in value)
    return False


def assess_first_pass(state: NativeEvidenceState) -> dict:
    report = state["first_report"]
    status = report.get("native_evidence_status")
    if status in ACCEPTED_NATIVE_STATUSES or report.get("evidence_adequate") is True:
        return {"route": "accept", "native_evidence_status": NativeEvidenceStatus.SUFFICIENT.value}
    if status == NativeEvidenceStatus.CONFLICT.value:
        return {"route": "insufficient", "native_evidence_status": NativeEvidenceStatus.CONFLICT.value}
    if int(state.get("retry_count", 0)) == 0 and report.get("recoverable_reason") in RECOVERABLE_REASONS:
        return {"route": "retry"}
    return {"route": "insufficient", "native_evidence_status": NativeEvidenceStatus.INSUFFICIENT.value}


def route_after_assessment(state: NativeEvidenceState) -> str:
    return state["route"]


def prepare_focused_retry(state: NativeEvidenceState) -> dict:
    reason = state["first_report"]["recoverable_reason"]
    if _contains_forbidden(state["normalized_claim"]) or _contains_forbidden(state["time_scope"]):
        raise ValueError("Focused retry request contains hidden construction fields")
    request = {
        "media": state["native_media_ref"], "same_original_uri": True,
        "video_before_text": True,
        "resolution": "high" if reason in {"fine_visual_detail", "visible_text"} else "medium",
        "timestamp_focus": True, "time_scope": state["time_scope"],
        "claim": state["normalized_claim"], "recoverable_reason": reason,
    }
    if state.get("retry_report") is None:
        return {"retry_request": request, "retry_count": 1, "route": "awaiting_focused_retry"}
    retry = state["retry_report"]
    status = retry.get("native_evidence_status")
    if status in ACCEPTED_NATIVE_STATUSES or retry.get("evidence_adequate") is True:
        final = NativeEvidenceStatus.SUFFICIENT_AFTER_RETRY.value
        route = "accept"
    elif status == NativeEvidenceStatus.CONFLICT.value:
        final, route = NativeEvidenceStatus.CONFLICT.value, "insufficient"
    else:
        final, route = NativeEvidenceStatus.INSUFFICIENT.value, "insufficient"
    return {"retry_request": request, "retry_count": 1,
            "native_evidence_status": final, "route": route}


def finalize_decision(state: NativeEvidenceState) -> dict:
    route = state["route"]
    if route == "insufficient":
        route = "reconstruct_or_reject"
    return {"route": route}


def build_native_evidence_retry_graph():
    graph = StateGraph(NativeEvidenceState)
    graph.add_node("assess_native_general_pass", assess_first_pass)
    graph.add_node("prepare_or_reassess_same_video_focused_retry", prepare_focused_retry)
    graph.add_node("finalize_native_evidence_decision", finalize_decision)
    graph.add_edge(START, "assess_native_general_pass")
    graph.add_conditional_edges("assess_native_general_pass", route_after_assessment, {
        "retry": "prepare_or_reassess_same_video_focused_retry",
        "accept": "finalize_native_evidence_decision",
        "insufficient": "finalize_native_evidence_decision",
    })
    graph.add_edge("prepare_or_reassess_same_video_focused_retry", "finalize_native_evidence_decision")
    graph.add_edge("finalize_native_evidence_decision", END)
    return graph


graph = build_native_evidence_retry_graph().compile()
