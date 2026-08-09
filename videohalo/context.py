"""Frozen VideoHALO 3.7 runtime context passed to graph nodes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Profile = Literal["probe_build", "evalbench_build"]


@dataclass(frozen=True)
class VideoHALORuntimeContext:
    run_id: str
    profile: Profile
    dataset_id: Optional[str]
    core_memory_version: str
    core_memory_hash: str
    taxonomy_version: str
    output_contract_version: str
    artifact_root: str

    @classmethod
    def from_core_memory(
        cls, *, run_id: str, profile: Profile, dataset_id: Optional[str], core_memory, artifact_root: str
    ) -> "VideoHALORuntimeContext":
        manifest = core_memory.manifest
        return cls(
            run_id=run_id,
            profile=profile,
            dataset_id=dataset_id,
            core_memory_version=manifest["core_memory_version"],
            core_memory_hash=core_memory.manifest_sha256,
            taxonomy_version=manifest["taxonomy_version"],
            output_contract_version=manifest["output_contract_version"],
            artifact_root=artifact_root,
        )
