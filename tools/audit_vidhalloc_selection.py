"""Independently audit VidHalLoc selection isolation and source integrity."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIOR_MANIFESTS = (
    ROOT / "probe_build_round1" / "video_manifest.jsonl",
    ROOT
    / "probe_build_expansion_200"
    / "append_run_160"
    / "video_manifest.jsonl",
)
PRIOR_SOURCE_SELECTION = (
    ROOT
    / "probe_build_full11_expansion_400"
    / "source_selection_400.json"
)
FINAL_ROOT = ROOT / "video_dataset_staging" / "final_10000"
FINAL_MANIFEST = FINAL_ROOT / "final_manifest.csv"


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selection", type=Path, default=ROOT / "VidHalLoc.json"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT
        / "VidHalLoc_2600_build"
        / "selection_audit.json",
    )
    args = parser.parse_args()

    selection = json.loads(
        args.selection.read_text(encoding="utf-8-sig")
    )
    selected = selection["videos"]

    prior: list[dict] = []
    for manifest in PRIOR_MANIFESTS:
        for item in read_jsonl(manifest):
            prior.append(
                {
                    "video_id": str(item["video_id"]),
                    "sha256": str(item["source_asset"]["sha256"]),
                }
            )
    full11 = json.loads(
        PRIOR_SOURCE_SELECTION.read_text(encoding="utf-8-sig")
    )
    prior.extend(
        {
            "video_id": str(item["video_id"]),
            "sha256": str(item["sha256"]),
        }
        for item in full11["videos"]
    )
    prior_ids = {item["video_id"] for item in prior}
    prior_hashes = {item["sha256"] for item in prior}

    with FINAL_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        final_rows = list(csv.DictReader(handle))
    final_by_id = {"f10000_" + row["target_id"]: row for row in final_rows}

    selected_ids = [str(item["video_id"]) for item in selected]
    selected_hashes = [str(item["sha256"]) for item in selected]
    expected_root = str(FINAL_ROOT.resolve()).casefold() + "\\"
    missing_files = [
        item["source_path"]
        for item in selected
        if not Path(item["source_path"]).is_file()
    ]
    outside_root = [
        item["source_path"]
        for item in selected
        if not str(Path(item["source_path"]).resolve())
        .casefold()
        .startswith(expected_root)
    ]
    manifest_mismatches = []
    for item in selected:
        canonical = final_by_id.get(item["video_id"])
        if canonical is None:
            manifest_mismatches.append(
                {"video_id": item["video_id"], "reason": "missing_from_manifest"}
            )
            continue
        if canonical["sha256"] != item["sha256"]:
            manifest_mismatches.append(
                {"video_id": item["video_id"], "reason": "sha256_mismatch"}
            )
        if (
            str(Path(canonical["final_path"]).resolve()).casefold()
            != str(Path(item["source_path"]).resolve()).casefold()
        ):
            manifest_mismatches.append(
                {"video_id": item["video_id"], "reason": "path_mismatch"}
            )

    checks = {
        "selected_total_is_2600": len(selected) == 2600,
        "captioning_count_is_1300": sum(
            item["task_type"] == "video_captioning" for item in selected
        )
        == 1300,
        "videoqa_count_is_1300": sum(
            item["task_type"] == "video_qa" for item in selected
        )
        == 1300,
        "selected_ids_are_unique": len(set(selected_ids)) == len(selected_ids),
        "selected_hashes_are_unique": len(set(selected_hashes))
        == len(selected_hashes),
        "prior_source_rows_are_600": len(prior) == 600,
        "prior_hashes_are_600_unique": len(prior_hashes) == 600,
        "zero_prior_video_id_overlap": not prior_ids.intersection(selected_ids),
        "zero_prior_sha256_overlap": not prior_hashes.intersection(
            selected_hashes
        ),
        "all_sources_under_final_10000": not outside_root,
        "all_source_files_exist": not missing_files,
        "all_rows_match_final_manifest": not manifest_mismatches,
    }
    report = {
        "schema_version": "vidhalloc_selection_audit_1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": str(args.selection.resolve()),
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "selected_total": len(selected),
            "selected_by_task": dict(
                Counter(item["task_type"] for item in selected)
            ),
            "selected_by_allocation_group": dict(
                Counter(item["allocation_group"] for item in selected)
            ),
            "selected_unique_video_ids": len(set(selected_ids)),
            "selected_unique_sha256": len(set(selected_hashes)),
            "prior_source_rows": len(prior),
            "prior_unique_video_ids": len(prior_ids),
            "prior_unique_sha256": len(prior_hashes),
            "prior_video_id_overlap": len(
                prior_ids.intersection(selected_ids)
            ),
            "prior_sha256_overlap": len(
                prior_hashes.intersection(selected_hashes)
            ),
            "missing_source_files": len(missing_files),
            "outside_final_10000": len(outside_root),
            "final_manifest_mismatches": len(manifest_mismatches),
        },
        "failures": {
            "missing_source_files": missing_files,
            "outside_final_10000": outside_root,
            "final_manifest_mismatches": manifest_mismatches,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
