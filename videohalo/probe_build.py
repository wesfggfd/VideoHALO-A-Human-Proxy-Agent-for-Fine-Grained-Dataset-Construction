"""Programmatic entry point for VideoHALO 3.7 direct Probe-build output.

The former 3.6 freeze/review/unlock workflow intentionally no longer exists.
Provider-specific generation code supplies fully back-parsed, independently
verified candidates to this fail-closed acceptance boundary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .graph import compiled_graph


class ProbeBuildRunner:
    def __init__(
        self,
        *,
        output_path: Path,
        dataset_id: str = "probe_build",
        run_id: str = "probe_build_3_7",
    ):
        self.output_path = output_path.resolve()
        self.dataset_id = dataset_id
        self.run_id = run_id

    def emit_verified_candidates(
        self,
        candidates: Iterable[dict],
        *,
        video_manifests: Iterable[dict] = (),
        fact_graphs: Iterable[dict] = (),
        eligibility_records: Iterable[dict] = (),
        fact_verifier_reports: Iterable[dict] = (),
    ) -> list[dict]:
        state = compiled_graph("probe_build").invoke(
            {
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "profile": "probe_build",
                "output_path": str(self.output_path),
                "video_manifests": list(video_manifests),
                "fact_graphs": list(fact_graphs),
                "eligibility_records": list(eligibility_records),
                "fact_verifier_reports": list(fact_verifier_reports),
                "candidates": list(candidates),
            }
        )
        return state["output_records"]
