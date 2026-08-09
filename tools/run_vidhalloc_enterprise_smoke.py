"""Run an isolated Enterprise smoke without mutating the formal resume."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from videohalo.settings import get_settings
from videohalo.windowed_build import WindowedBuildOrchestrator


ROOT = Path(__file__).resolve().parents[1]
SMOKE_ROOT = ROOT / "VidHalLoc_1200_budget500_build" / "enterprise_smoke"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("one", "six", "caption_fix"))
    args = parser.parse_args()
    settings = get_settings()
    settings.validate_enterprise_runtime()
    settings.require_google_cloud_project()
    settings.require_gcs_bucket()

    root = SMOKE_ROOT / args.stage
    selection_path = root / "selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8-sig"))
    video_count = len(selection["videos"])
    expected_count = {"one": 1, "six": 6, "caption_fix": 2}[args.stage]
    if video_count != expected_count:
        raise RuntimeError("Frozen smoke selection has the wrong size")
    result = WindowedBuildOrchestrator(
        selection_path=selection_path,
        output_path=root / "public_probe_items.jsonl",
        status_path=root / "status.json",
        dataset_id="vidhalloc_enterprise_smoke_" + args.stage,
        run_id="vidhalloc_enterprise_smoke_" + args.stage + "_001",
        target_pairs=video_count * 2,
        window_size=video_count,
        video_workers={"one": 1, "six": 3, "caption_fix": 2}[args.stage],
        upload_workers={"one": 1, "six": 3, "caption_fix": 2}[args.stage],
        per_video_pair_cap=2,
        selection_seed=42,
        max_video_attempts=2,
        process_all_videos=True,
        budget_policy_path=None,
    ).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
