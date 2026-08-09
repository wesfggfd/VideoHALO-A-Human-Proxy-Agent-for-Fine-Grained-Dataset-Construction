"""Command-line interface for the VideoHALO 3.7 Fixed-8 runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from .contracts.leakage import assert_public_item_safe
from .contracts.registry import ContractRegistry
from .graph import compiled_graph
from .models.registry import ModelRegistry
from .policy.loader import load_core_memory
from .resolvers.taxonomy import FACT_KIND_TO_LEAF, LEAF_TO_SLOT
from .stores.jsonl import read_jsonl


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _input_path(value: Optional[str], environment_name: str) -> Path:
    candidate = value or os.environ.get(environment_name)
    if not candidate:
        raise ValueError(
            "Input is required via --input or %s" % environment_name
        )
    path = Path(candidate).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _policy_validate(_: argparse.Namespace) -> dict:
    core = load_core_memory()
    taxonomy = core.json("taxonomy_json")
    configured = {
        item["fact_kind"]: (item["leaf"], item["conflict_slot"])
        for item in taxonomy["leaves"]
    }
    runtime = {
        kind: (leaf, LEAF_TO_SLOT[leaf])
        for kind, leaf in FACT_KIND_TO_LEAF.items()
    }
    if configured != runtime:
        raise RuntimeError("Frozen Fixed-8 taxonomy and resolver disagree")
    ModelRegistry()
    return {
        "ok": True,
        "core_memory_version": core.manifest["core_memory_version"],
        "taxonomy_version": core.manifest["taxonomy_version"],
        "output_contract_version": core.manifest["output_contract_version"],
        "manifest_sha256": core.manifest_sha256,
        "verified_asset_count": len(core.asset_paths),
        "leaf_count": len(configured),
    }


def _register(args: argparse.Namespace) -> dict:
    records = read_jsonl(_input_path(args.input, "VIDEOHALO_REGISTER_INPUT"))
    output = Path(args.output or "video_manifests.jsonl").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            state = compiled_graph("register").invoke(
                {
                    "run_id": record.get("run_id", args.run_id),
                    "dataset_id": record.get("dataset_id", args.dataset_id),
                    "video_id": record["video_id"],
                    "source_path": record["source_path"],
                    "provider_state": record.get("provider_state", "pending"),
                    "ffprobe_bin": args.ffprobe,
                    "ffmpeg_bin": args.ffmpeg,
                }
            )
            handle.write(
                json.dumps(
                    state["video_manifest"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    return {"ok": True, "manifest_count": count, "output": str(output)}


def _build(args: argparse.Namespace) -> dict:
    records = read_jsonl(_input_path(args.input, "VIDEOHALO_BUILD_INPUT"))
    live_flags = [
        "source_path" in record and not {
            "candidate",
            "candidates",
        }.intersection(record)
        for record in records
    ]
    if any(live_flags):
        if not all(live_flags):
            raise ValueError("Do not mix source-video and candidate-envelope inputs")
        from .live_build import LiveBuildRunner

        result = LiveBuildRunner(
            output_path=Path(args.output),
            dataset_id=args.dataset_id,
            profile=args.profile,
            target_pairs=args.target_pairs,
            per_video_pair_cap=args.per_video_pair_cap,
            selection_seed=args.selection_seed,
            run_id=args.run_id,
        ).run(records)
        return {"ok": True, "profile": args.profile, **result}
    candidates: list[dict] = []
    video_manifests: list[dict] = []
    fact_graphs: list[dict] = []
    eligibility_records: list[dict] = []
    fact_verifier_reports: list[dict] = []
    for record in records:
        if "candidate" in record:
            candidates.append(record["candidate"])
        elif "candidates" in record:
            candidates.extend(record["candidates"])
        else:
            candidates.append(record)
        video_manifests.extend(record.get("video_manifests", []))
        fact_graphs.extend(record.get("fact_graphs", []))
        eligibility_records.extend(record.get("eligibility_records", []))
        fact_verifier_reports.extend(record.get("fact_verifier_reports", []))
    state = compiled_graph(args.profile).invoke(
        {
            "run_id": args.run_id,
            "dataset_id": args.dataset_id,
            "profile": args.profile,
            "output_path": str(Path(args.output).resolve()),
            "video_manifests": video_manifests,
            "fact_graphs": fact_graphs,
            "eligibility_records": eligibility_records,
            "fact_verifier_reports": fact_verifier_reports,
            "candidates": candidates,
        }
    )
    return {
        "ok": True,
        "profile": args.profile,
        "emitted_pair_count": state["emitted_pair_count"],
        "output": str(Path(args.output).resolve()),
        "observed_leaf_yield": state["observed_leaf_yield"],
    }


def _validate(args: argparse.Namespace) -> dict:
    records = read_jsonl(_input_path(args.input, "VIDEOHALO_VALIDATE_INPUT"))
    pair_ids: set[str] = set()
    for record in records:
        assert_public_item_safe(record)
        pair_id = str(record["pair_id"])
        if pair_id in pair_ids:
            raise ValueError("Duplicate pair_id: %s" % pair_id)
        pair_ids.add(pair_id)
    return {"ok": True, "pair_count": len(records)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videohalo",
        description="VideoHALO 3.7 Fixed-8 direct-output runtime",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy-validate", help="verify frozen 3.7 policy")
    policy.set_defaults(handler=_policy_validate)

    register = sub.add_parser("register", help="register source videos from JSONL")
    register.add_argument("--input", required=True)
    register.add_argument("--output", default="video_manifests.jsonl")
    register.add_argument("--dataset-id", default="videohalo")
    register.add_argument("--run-id", default="register_cli")
    register.add_argument("--ffprobe", default="ffprobe")
    register.add_argument("--ffmpeg", default="ffmpeg")
    register.set_defaults(handler=_register)

    build = sub.add_parser("build", help="validate and emit direct pair JSONL")
    build.add_argument("--input", help="internal candidate JSONL")
    build.add_argument(
        "--profile",
        choices=["probe_build", "evalbench_build"],
        required=True,
    )
    build.add_argument("--output", required=True)
    build.add_argument("--dataset-id", default="videohalo")
    build.add_argument("--run-id", default="build_cli")
    build.add_argument("--target-pairs", type=int)
    build.add_argument("--per-video-pair-cap", type=int, default=2)
    build.add_argument("--selection-seed", type=int, default=42)
    build.set_defaults(handler=_build)

    validate = sub.add_parser("validate", help="validate direct pair JSONL")
    validate.add_argument("--input", required=True)
    validate.set_defaults(handler=_validate)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _print(args.handler(args))
    return 0
