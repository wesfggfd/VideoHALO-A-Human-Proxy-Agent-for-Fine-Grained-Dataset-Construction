"""Resume the frozen VidHalLoc build through Enterprise ADC and private GCS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from videohalo.settings import get_settings
from videohalo.windowed_build import WindowedBuildOrchestrator


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "VidHalLoc_1200_budget500_build"
FORMAL_ROOT = BUILD_ROOT / "formal_run_2000_enterprise"
FORMAL_CONFIG = BUILD_ROOT / "formal_run_config_enterprise.json"
def validate_frozen_formal_args(args, config_path: Path) -> dict:
    frozen = json.loads(config_path.read_text(encoding="utf-8-sig"))
    for key in ("selection", "output", "status_json", "budget_policy"):
        frozen[key] = str(Path(frozen[key]).resolve())
    observed = {
        "selection": str(Path(args.selection).resolve()),
        "output": str(Path(args.output).resolve()),
        "status_json": str(Path(args.status).resolve()),
        "dataset_id": args.dataset_id,
        "run_id": args.run_id,
        "target_pairs": args.target_pairs,
        "window_size": args.window_size,
        "video_workers": args.video_workers,
        "upload_workers": args.upload_workers,
        "per_video_pair_cap": args.per_video_pair_cap,
        "selection_seed": args.selection_seed,
        "max_video_attempts": args.max_video_attempts,
        "process_all_videos": args.process_all_videos,
        "budget_policy": str(Path(args.budget_policy).resolve()),
    }
    mismatches = {
        key: {"expected": frozen[key], "observed": value}
        for key, value in observed.items()
        if frozen[key] != value
    }
    if mismatches:
        raise RuntimeError(
            "Enterprise run arguments differ from frozen config: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    return frozen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=FORMAL_CONFIG)
    parser.add_argument(
        "--selection", default=str(ROOT / "VidHalLoc_1200_budget500.json")
    )
    parser.add_argument(
        "--output", default=str(FORMAL_ROOT / "public_probe_items.jsonl")
    )
    parser.add_argument("--status", default=str(FORMAL_ROOT / "status.json"))
    parser.add_argument("--dataset-id", default="vidhalloc_enterprise_2000")
    parser.add_argument("--run-id", default="vidhalloc_enterprise_2000_001")
    parser.add_argument("--target-pairs", type=int, default=2000)
    parser.add_argument("--window-size", type=int, default=100)
    parser.add_argument("--video-workers", type=int, default=5)
    parser.add_argument("--upload-workers", type=int, default=3)
    parser.add_argument("--per-video-pair-cap", type=int, default=2)
    parser.add_argument("--selection-seed", type=int, default=42)
    parser.add_argument("--max-video-attempts", type=int, default=2)
    parser.add_argument(
        "--budget-policy", default=str(BUILD_ROOT / "budget_policy.json")
    )
    parser.add_argument("--process-all-videos", action="store_true")
    args = parser.parse_args()
    frozen = validate_frozen_formal_args(args, args.config.resolve())

    settings = get_settings()
    settings.validate_enterprise_runtime()
    settings.require_google_cloud_project()
    settings.require_gcs_bucket()
    if settings.model_requests_per_minute != float(
        frozen["provider"]["model_requests_per_minute"]
    ):
        raise RuntimeError(
            "Runtime request rate differs from the frozen Enterprise config"
        )
    status_path = Path(args.status).resolve()
    if not status_path.is_file():
        raise RuntimeError(
            "Prepare the isolated Enterprise resume before starting production"
        )
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    if status.get("migration", {}).get("legacy_run_immutable") is not True:
        raise RuntimeError("Enterprise resume provenance is missing")
    if status.get("total_pair_count", frozen["preserved_pair_count"]) < frozen[
        "preserved_pair_count"
    ]:
        raise RuntimeError("Preserved baseline is incomplete")
    preflight_path = status_path.parent / "runtime_preflight.json"
    if not preflight_path.is_file():
        raise RuntimeError("Runtime ADC/GCS/Flex preflight has not passed")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8-sig"))
    required_preflight = {
        "ok": True,
        "project": settings.require_google_cloud_project(),
        "bucket": settings.require_gcs_bucket(),
        "runtime_storage_check": "passed",
        "live_model_check": "passed",
        "traffic_type": "TrafficType.ON_DEMAND_FLEX",
    }
    for key, expected in required_preflight.items():
        observed = preflight.get(key)
        if key == "traffic_type":
            if not str(observed or "").endswith("ON_DEMAND_FLEX"):
                raise RuntimeError("Runtime preflight did not prove Flex-only routing")
        elif observed != expected:
            raise RuntimeError("Runtime preflight gate failed: %s" % key)

    smoke_gate_path = status_path.parent / "smoke_gate.json"
    if not smoke_gate_path.is_file():
        raise RuntimeError("Frozen Enterprise smoke gate is missing")
    smoke_gate = json.loads(smoke_gate_path.read_text(encoding="utf-8-sig"))
    required_smoke_gate = {
        "ok": True,
        "fixed8_leaf_coverage": True,
        "faithful_relative_not_forced_uniform": True,
        "videoqa_open_and_polar_forms": True,
        "captioning_yes_no_prefix_forbidden": True,
        "concurrent_artifact_write_safe": True,
        "shared_pacer_not_multiplied_by_workers": True,
        "model_requests_per_minute": frozen["provider"][
            "model_requests_per_minute"
        ],
    }
    for key, expected in required_smoke_gate.items():
        if smoke_gate.get(key) != expected:
            raise RuntimeError("Enterprise smoke gate failed: %s" % key)

    result = WindowedBuildOrchestrator(
        selection_path=Path(args.selection),
        output_path=Path(args.output),
        status_path=status_path,
        dataset_id=args.dataset_id,
        run_id=args.run_id,
        target_pairs=args.target_pairs,
        window_size=args.window_size,
        video_workers=args.video_workers,
        upload_workers=args.upload_workers,
        per_video_pair_cap=args.per_video_pair_cap,
        selection_seed=args.selection_seed,
        max_video_attempts=args.max_video_attempts,
        process_all_videos=args.process_all_videos,
        budget_policy_path=Path(args.budget_policy),
    ).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
