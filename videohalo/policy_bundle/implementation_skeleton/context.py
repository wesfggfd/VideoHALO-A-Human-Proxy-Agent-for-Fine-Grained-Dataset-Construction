from dataclasses import dataclass
from typing import Literal, Optional

Profile = Literal["probe_build", "evalbench_build"]

@dataclass(frozen=True)
class VideoHALORuntimeContext:
    run_id: str
    profile: Profile
    dataset_id: Optional[str]
    taxonomy_version: str = "VHal-Fixed8-3.7"
    output_schema_version: str = "videohalo_probe_pair_sample_fixed8_3.6.1"
    evidence_policy_id: str = "gemini_native_original_video_v1"
    artifact_root: str = "artifacts"
