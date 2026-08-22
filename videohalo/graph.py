"""Facade for the VideoHALO 3.8 Fixed-8 runtime graphs."""
from __future__ import annotations

from functools import lru_cache

from .graphs.four_stage_orchestrator import build_four_stage_orchestrator_graph
from .graphs.fact_graph_build import build_fact_graph
from .graphs.media_registration import build_media_registration_graph
from .graphs.native_media_ingestion import build_native_media_ingestion_graph
from .graphs.native_evidence_retry import build_native_evidence_retry_graph
from .graphs.pair_construction import build_pair_construction_graph


def build_graph(profile: str = "build"):
    builders = {
        "register": build_media_registration_graph,
        "build": build_four_stage_orchestrator_graph,
        "probe_build": build_four_stage_orchestrator_graph,
        "evalbench_build": build_four_stage_orchestrator_graph,
        # Internal deterministic components, not user-facing operations.
        "fact_graph_build": build_fact_graph,
        "pair_construction": build_pair_construction_graph,
        "native_media_ingestion": build_native_media_ingestion_graph,
        "native_evidence_retry": build_native_evidence_retry_graph,
    }
    try:
        return builders[profile]()
    except KeyError as exc:
        raise ValueError("Unknown VideoHALO 3.8 graph: %s" % profile) from exc


@lru_cache(maxsize=8)
def compiled_graph(profile: str = "build"):
    return build_graph(profile).compile()
