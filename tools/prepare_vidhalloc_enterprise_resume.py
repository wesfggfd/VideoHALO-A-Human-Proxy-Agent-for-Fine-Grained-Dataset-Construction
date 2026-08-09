"""Create a clean Enterprise resume run without mutating the legacy run."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from videohalo.contracts.leakage import assert_public_item_safe
from videohalo.contracts.registry import ContractRegistry
from videohalo.providers.safety import redact_sensitive


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pairs(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        assert_public_item_safe(row)
        ContractRegistry().validate(
            "videohalo_probe_pair_sample_fixed8.schema.json", row
        )
        rows.append(row)
    pair_ids = [str(row["pair_id"]) for row in rows]
    if len(pair_ids) != len(set(pair_ids)):
        raise RuntimeError("Legacy output contains duplicate pair IDs")
    return rows


def assert_secret_free(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if redact_sensitive(text) != text:
        raise RuntimeError("Refusing to copy credential-bearing event log: %s" % path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-run", type=Path, required=True)
    parser.add_argument("--enterprise-run", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--run-id", default="vidhalloc_enterprise_2000_001")
    args = parser.parse_args()

    legacy = args.legacy_run.resolve()
    target = args.enterprise_run.resolve()
    selection_path = args.selection.resolve()
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("Enterprise resume directory must be empty: %s" % target)
    target.mkdir(parents=True, exist_ok=True)

    legacy_output = legacy / "public_probe_items.jsonl"
    legacy_status_path = legacy / "status.json"
    pairs = read_pairs(legacy_output)
    legacy_status = json.loads(
        legacy_status_path.read_text(encoding="utf-8-sig")
    )
    selection = json.loads(selection_path.read_text(encoding="utf-8-sig"))
    selection_sha256 = sha256_path(selection_path)
    if legacy_status.get("selection_sha256") != selection_sha256:
        raise RuntimeError("Legacy status and selected source list differ")

    completed = {
        video_id: value
        for video_id, value in legacy_status.get("results", {}).items()
        if value.get("status") == "completed"
    }
    known_ids = {str(item["video_id"]) for item in selection["videos"]}
    if not set(completed).issubset(known_ids):
        raise RuntimeError("Legacy completed status references another selection")
    preserved_completed_ids = sorted(completed)

    shutil.copy2(legacy_output, target / "public_probe_items.jsonl")
    legacy_events = legacy / "events"
    if legacy_events.is_dir():
        destination = target / "events"
        destination.mkdir()
        for source in sorted(legacy_events.glob("*.jsonl")):
            assert_secret_free(source)
            shutil.copy2(source, destination / source.name)

    now = utc_now()
    status = {
        "schema_version": "videohalo_windowed_run_status_3.7.1",
        "run_id": args.run_id,
        "state": "initialized_enterprise_resume",
        "selection_path": str(selection_path),
        "selection_sha256": selection_sha256,
        "total_video_count": len(selection["videos"]),
        "target_pair_count": int(selection["policy"]["target_accepted_pairs"]),
        "window_size": 100,
        "window_count": (len(selection["videos"]) + 99) // 100,
        "video_workers": 3,
        "upload_workers": 3,
        "process_all_videos": False,
        "budget_policy_path": str(
            selection_path.parent
            / "VidHalLoc_1200_budget500_build"
            / "budget_policy.json"
        ),
        "started_at": now,
        "updated_at": now,
        "current_window": None,
        "current_videos": {},
        "results": completed,
        "windows": {},
        "resume_baseline_pair_count": len(pairs),
        "resume_baseline_completed_video_count": len(completed),
        "migration": {
            "from_backend": "gemini_developer_api_files_api",
            "to_backend": "gemini_enterprise_adc_private_gcs",
            "legacy_run": str(legacy),
            "legacy_status_sha256": sha256_path(legacy_status_path),
            "legacy_output_sha256": sha256_path(legacy_output),
            "prepared_at": now,
            "legacy_run_immutable": True,
            "preserved_completed_video_ids": preserved_completed_ids,
        },
    }
    (target / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report = {
        "ok": True,
        "enterprise_run": str(target),
        "preserved_pair_count": len(pairs),
        "preserved_completed_video_count": len(completed),
        "pending_video_count": len(selection["videos"]) - len(completed),
        "legacy_run_modified": False,
    }
    (target / "migration_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
