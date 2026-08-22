"""Production Gemini-native VideoHALO 3.8 Build runner."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from .agents import (
    EXTRACTION_AGENT,
    GENERATION_AGENT,
    MONITOR_AGENT,
    PLANNER_AGENT,
    REFLECTION_AGENT,
    VERIFICATION_AGENT,
)
from .agents.registry import agent_spec
from .contracts.internal_schemas import (
    CANDIDATE_VERIFICATION_SCHEMA,
    FACT_PROPOSAL_SCHEMA,
    FACT_VERIFICATION_SCHEMA,
    LEAF_OPPORTUNITY_SCHEMA,
    NORMALIZED_FACT_CONTRACTS,
    paired_backparse_schema_for,
    realization_schema_for,
)
from .contracts.stage_outputs import (
    COMPREHENSIVE_RELIABILITY_VALIDATION,
    FACT_EXTRACTION_AND_REFLECTION,
    GENERATION_AND_VERIFICATION,
    HALLUCINATION_CATEGORY_RETRIEVAL,
    make_stage_output,
)
from .contracts.registry import ContractRegistry
from .answer_alignment import (
    answer_alignment_instruction,
    answer_form_for,
    validate_question_answer_alignment,
)
from .graph import compiled_graph
from .media.register import detect_mime, sha256_path
from .models.client import GeminiEnterpriseModelClient
from .models.structured_call import structured_call
from .memory import DualLayerMemory
from .mutations.eligibility import evaluate_eligibility
from .mutations.engine import validate_mutation
from .observability import RuntimeEventLogger
from .planning import select_faithful_relative
from .policy.loader import load_core_memory
from .resolvers.graph_diff import assert_single_slot_change
from .resolvers.taxonomy import FACT_KIND_TO_LEAF, LEAF_TO_SLOT
from .stores.jsonl import read_jsonl
from .stores.artifacts import LocalArtifactStore
from .surface_templates import question_for_fact
from .taxonomy_first import (
    apply_slot_replacement,
    build_leaf_search_plan,
    leaf_conditioned_facts,
    validate_opportunity_matrix,
)
from .settings import get_settings
from .providers.safety import redact_sensitive

_COMPLETE_SENTENCE_RE = re.compile(r"^\S+\s+.+[.!?]$")


def _safe_id(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_")


def _require_complete_sentence(value: str, field_name: str) -> None:
    if not _COMPLETE_SENTENCE_RE.fullmatch(value.strip()):
        raise ValueError(
            f"{field_name} must contain at least two words and end with "
            "sentence punctuation"
        )


def _intervals_overlap(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    try:
        left_start = float(left["start_sec"])
        left_end = float(left["end_sec"])
        right_start = float(right["start_sec"])
        right_end = float(right["end_sec"])
    except (KeyError, TypeError, ValueError):
        return False
    if left_end < left_start or right_end < right_start:
        return False
    return left_start <= right_end and left_end >= right_start


def _has_grounded_evidence(
    report: dict,
    source_scope: object,
    *,
    interval_field: str,
) -> bool:
    return (
        _intervals_overlap(report.get(interval_field), source_scope)
        and bool(str(report.get("evidence_summary") or "").strip())
    )


class LiveBuildRunner:
    """Execute all model-bearing phases before the deterministic BuildGraph."""

    def __init__(
        self,
        *,
        output_path: Path,
        dataset_id: str,
        profile: str,
        model_client=None,
        media_adapter=None,
        target_pairs: Optional[int] = None,
        per_video_pair_cap: int = 2,
        selection_seed: int = 42,
        run_id: str = "videohalo_live_build_3_7",
        event_log_path: Optional[Path] = None,
    ):
        if profile not in {"probe_build", "evalbench_build"}:
            raise ValueError("Unsupported build profile: %s" % profile)
        self.output_path = output_path.resolve()
        self.dataset_id = dataset_id
        self.profile = profile
        self.target_pairs = target_pairs
        self.per_video_pair_cap = per_video_pair_cap
        self.selection_seed = selection_seed
        self.run_id = run_id
        self.model_client = model_client or GeminiEnterpriseModelClient()
        self.media_adapter = media_adapter
        self.core = load_core_memory()
        self.memory = DualLayerMemory()
        self.leaf_search_plan = build_leaf_search_plan()
        self.artifact_store = LocalArtifactStore(
            get_settings().artifact_root,
            self.dataset_id,
        )
        self.artifact_store.put_json(
            "leaf_search_plan",
            self.leaf_search_plan,
        )
        operators = self.core.json("mutation_operators_json")["operators"]
        self.operator_by_leaf = {
            item["target_leaf"]: item for item in operators
        }
        self.events = RuntimeEventLogger(
            event_log_path
            or self.output_path.with_suffix(self.output_path.suffix + ".events.jsonl")
        )

    @staticmethod
    def _memory_categories(*values: object) -> tuple[str, ...]:
        categories: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"leaf_label", "planned_leaf_label"} and item:
                        categories.append(str(item))
                    elif key in {
                        "leaf_checks",
                        "constructible_opportunities",
                        "opportunities",
                        "facts",
                        "source_fact",
                        "planned_leaf_rule",
                    }:
                        visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)

        for value in values:
            visit(value)
        return tuple(dict.fromkeys(categories)) or ("global",)

    def _call(self, role: str, payload: dict, schema: dict) -> dict:
        call_payload = dict(payload)
        source_sha256 = call_payload.pop(
            "_audit_canonical_source_sha256",
            None,
        )
        media_ref = call_payload.get("native_media_ref")
        media_ref_fingerprint = (
            hashlib.sha256(str(media_ref).encode("utf-8")).hexdigest()
            if media_ref is not None
            else None
        )
        if media_ref is not None and (
            not isinstance(source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        ):
            raise ValueError(
                "Every media-bearing call requires an audited canonical "
                "source SHA-256"
            )
        call_audit = {
            "role": role,
            "video_id": call_payload.get("video_id"),
            "media_attached": media_ref is not None,
            "canonical_source_sha256": source_sha256,
            "media_ref_fingerprint": media_ref_fingerprint,
        }
        self.events.emit(
            role,
            "structured_call_started",
            call_audit,
        )
        categories = self._memory_categories(call_payload)
        memory_snapshot = self.memory.snapshot(
            categories,
            video_id=str(call_payload.get("video_id") or ""),
        )
        result = structured_call(
            self.model_client,
            role=role,
            payload=call_payload,
            schema=schema,
            attempts=3,
            memory_snapshot=memory_snapshot,
        )
        categories = self._memory_categories(call_payload, result)
        self.memory.contribute(
            agent_role=role,
            stage=agent_spec(role).stage,
            video_id=str(call_payload.get("video_id") or ""),
            categories=categories,
            content={"structured_output": result},
        )
        self.artifact_store.put_json(
            "dual_layer_memory_snapshot",
            self.memory.snapshot(
                categories,
                video_id=str(call_payload.get("video_id") or ""),
            ),
        )
        metadata = getattr(self.model_client, "last_call_metadata", {})
        observed_fingerprint = metadata.get("media_ref_fingerprint")
        if (
            media_ref_fingerprint is not None
            and observed_fingerprint is not None
            and observed_fingerprint != media_ref_fingerprint
        ):
            raise RuntimeError(
                "Gemini request media URI disagrees with the audited lease"
            )
        self.events.emit(
            role,
            "structured_call_completed",
            {**call_audit, **dict(metadata)},
        )
        return result

    def _focused_retry(
        self, role: str, payload: dict, schema: dict, first: dict
    ) -> dict:
        recoverable = first.get("recoverable_reason")
        if recoverable not in {
            "fine_visual_detail",
            "visible_text",
            "prompt_scope",
            "recoverable_review_disagreement",
        }:
            return first
        retry_payload = {
            **payload,
            "media_resolution": "high",
            "focused_native_retry": True,
            "recoverable_reason": recoverable,
        }
        return self._call(role, retry_payload, schema)

    def _register_and_materialize(self, record: dict) -> tuple[dict, str]:
        source = Path(record["source_path"]).resolve()
        preloaded_manifest = record.get("_preloaded_video_manifest")
        preloaded_media_ref = record.get("_preloaded_native_media_ref")
        preloaded_lease = record.get("_preloaded_media_lease")
        if (
            preloaded_manifest is not None
            or preloaded_media_ref is not None
            or preloaded_lease is not None
        ):
            if not isinstance(preloaded_manifest, dict) or not isinstance(
                preloaded_media_ref, str
            ) or not isinstance(preloaded_lease, dict):
                raise ValueError(
                    "Preloaded media requires a manifest, media URI, and lease"
                )
            manifest = dict(preloaded_manifest)
            lease = dict(preloaded_lease)
            if manifest.get("video_id") != record["video_id"]:
                raise ValueError("Preloaded media belongs to another video")
            if manifest.get("provider_state") != "active":
                raise ValueError("Preloaded media is not active")
            canonical_sha256 = sha256_path(source)
            if manifest.get("source_sha256") != canonical_sha256:
                raise ValueError(
                    "Preloaded media no longer matches canonical source bytes"
                )
            if (
                lease.get("state") != "active"
                or lease.get("source_sha256") != canonical_sha256
                or lease.get("provider_media_uri") != preloaded_media_ref
                or not preloaded_media_ref.startswith("gs://")
            ):
                raise ValueError(
                    "Preloaded private-GCS lease does not match the canonical "
                    "video or media URI"
                )
            source_ref = lease.get("source_ref")
            if not isinstance(source_ref, dict) or (
                source_ref.get("sha256") != canonical_sha256
                or source_ref.get("uri") != source.as_uri()
            ):
                raise ValueError(
                    "Preloaded private-GCS lease source identity is invalid"
                )
            ContractRegistry().validate(
                "video_manifest.schema.json", manifest
            )
            return manifest, preloaded_media_ref
        registered = compiled_graph("register").invoke(
            {
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "video_id": record["video_id"],
                "source_path": str(source),
                "provider_state": "pending",
            }
        )
        materialized = compiled_graph("native_media_ingestion").invoke(
            {
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "profile": self.profile,
                "video_id": record["video_id"],
                "source_path": str(source),
                "video_manifest": registered["video_manifest"],
                "adapter": self.media_adapter,
            }
        )
        return materialized["video_manifest"], materialized["native_media_ref"]

    def _scan_leaf_opportunities(
        self, record: dict, native_media_ref: str
    ) -> dict:
        output = self._call(
            PLANNER_AGENT,
            {
                "native_media_ref": native_media_ref,
                "native_media_mime_type": detect_mime(
                    Path(record["source_path"])
                ),
                "_audit_canonical_source_sha256": record[
                    "_canonical_source_sha256"
                ],
                "media_resolution": "high",
                "video_id": record["video_id"],
                "task_type": record["task_type"],
                "leaf_checks": self.leaf_search_plan["leaves"],
                "instruction": (
                    "Before proposing any fact, scan all eight frozen leaves in "
                    "the supplied order. Return exactly one opportunity row per "
                    "leaf. Mark a leaf constructible only when the "
                    "high-resolution original video provides a decisive "
                    "evidence interval, a stable "
                    "atomic anchor, and a viable one-slot counterfactual. "
                    "Explicitly return not_constructible or uncertain rather "
                    "than forcing coverage. FIELD RULE: evidence_intervals "
                    "must contain one or two decisive intervals only when "
                    "constructibility is constructible; for both "
                    "not_constructible and uncertain it must be exactly [], "
                    "and anchor_summary must be an empty string. Distribution "
                    "targets are not evidence and must not affect these "
                    "decisions."
                ),
            },
            LEAF_OPPORTUNITY_SCHEMA,
        )
        if output["video_id"] != record["video_id"]:
            raise ValueError("Opportunity matrix belongs to another video")
        matrix = validate_opportunity_matrix(
            output,
            plan=self.leaf_search_plan,
        )
        self.artifact_store.put_json("leaf_opportunity_matrix", matrix)
        return matrix

    def _extract_leaf_conditioned_facts(
        self,
        record: dict,
        native_media_ref: str,
        matrix: dict,
    ) -> list[dict]:
        constructible = [
            item
            for item in matrix["opportunities"]
            if item["constructibility"] == "constructible"
        ]
        if not constructible:
            return []
        output = self._call(
            EXTRACTION_AGENT,
            {
                "native_media_ref": native_media_ref,
                "native_media_mime_type": detect_mime(
                    Path(record["source_path"])
                ),
                "_audit_canonical_source_sha256": record[
                    "_canonical_source_sha256"
                ],
                "media_resolution": "high",
                "video_id": record["video_id"],
                "task_type": record["task_type"],
                "constructible_opportunities": constructible,
                "normalized_fact_contracts": {
                    fact_kind: contract["required"]
                    for fact_kind, contract in NORMALIZED_FACT_CONTRACTS.items()
                },
                "instruction": (
                    "Reread every supplied evidence interval in the "
                    "high-resolution original video. Extract at most one best "
                    "atomic fact for each supplied constructible opportunity. "
                    "Every fact must use that "
                    "opportunity's exact planned leaf, fact kind, conflict "
                    "slot, evidence interval, and canonical anchor. Do not emit "
                    "facts for leaves absent from constructible_opportunities. "
                    "Do not relabel a natural fact to satisfy coverage."
                ),
            },
            FACT_PROPOSAL_SCHEMA,
        )
        facts = leaf_conditioned_facts(
            output["facts"],
            matrix=matrix,
        )
        for index, fact in enumerate(facts, 1):
            fact["source_fact_id"] = "fact_%03d" % index
        return facts

    def _reflect_on_fact(
        self, record: dict, native_media_ref: str, fact: dict, role: str
    ) -> dict:
        rule = next(
            item
            for item in self.leaf_search_plan["leaves"]
            if item["leaf_label"] == fact["planned_leaf_label"]
        )
        payload = {
            "native_media_ref": native_media_ref,
            "native_media_mime_type": detect_mime(Path(record["source_path"])),
            "_audit_canonical_source_sha256": record[
                "_canonical_source_sha256"
            ],
            "media_resolution": "high",
            "video_id": record["video_id"],
            "source_fact": fact,
            "planned_leaf_rule": rule,
            "instruction": (
                "Independently reread the high-resolution original video and "
                "decide whether this exact atomic fact is supported and "
                "uniquely grounded. Return the decisive evidence interval; it "
                "must overlap source_fact.time_scope and the evidence summary "
                "must be non-empty. Confirm that the fact belongs to the exact "
                "planned leaf under every hard boundary and has a viable "
                "alternative for its single frozen conflict slot. Do not infer "
                "another agent's result."
            ),
        }
        report = self._call(role, payload, FACT_VERIFICATION_SCHEMA)
        if report["verdict"] == "insufficient":
            report = self._focused_retry(
                role, payload, FACT_VERIFICATION_SCHEMA, report
            )
        if report["verdict"] == "supported" and not _has_grounded_evidence(
            report,
            fact.get("time_scope"),
            interval_field="evidence_interval",
        ):
            report = {
                **report,
                "verdict": "insufficient",
                "unique_grounding": False,
                "leaf_correct": False,
                "mutation_viable": False,
                "evidence_interval": None,
                "evidence_summary": (
                    "Rejected: the supported verdict lacked a non-empty "
                    "evidence summary and an interval overlapping "
                    "source_fact.time_scope."
                ),
                "recoverable_reason": None,
            }
        return {
            **report,
            "video_id": record["video_id"],
            "source_fact_id": fact["source_fact_id"],
            "agent_role": role,
            "shares_observations": False,
        }

    def _discover_video(self, record: dict) -> dict:
        if record.get("task_type") not in {"video_qa", "video_captioning"}:
            raise ValueError("Source record requires a valid task_type")
        manifest, native_media_ref = self._register_and_materialize(record)
        record = {
            **record,
            "_canonical_source_sha256": manifest["source_sha256"],
        }
        opportunity_matrix = self._scan_leaf_opportunities(
            record,
            native_media_ref,
        )
        category_retrieval_output = make_stage_output(
            stage=HALLUCINATION_CATEGORY_RETRIEVAL,
            video_id=record["video_id"],
            payload={"opportunity_matrix": opportunity_matrix},
            memory_snapshot=self.memory.snapshot(
                self._memory_categories(opportunity_matrix),
                video_id=record["video_id"],
            ),
        )
        self.artifact_store.put_json(
            "stage_hallucination_category_retrieval",
            category_retrieval_output,
        )
        proposed = self._extract_leaf_conditioned_facts(
            record,
            native_media_ref,
            opportunity_matrix,
        )
        self.artifact_store.put_json(
            "leaf_conditioned_factbank_candidates",
            {
                "video_id": record["video_id"],
                "facts": proposed,
            },
        )
        reports = [
            self._reflect_on_fact(
                record,
                native_media_ref,
                fact,
                REFLECTION_AGENT,
            )
            for fact in proposed
        ]
        graph_state = compiled_graph("fact_graph_build").invoke(
            {
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "video_id": record["video_id"],
                "proposed_facts": proposed,
                "reflection_reports": reports,
            }
        )
        accepted_ids = {
            item["source_fact_id"] for item in graph_state["fact_graph"]["facts"]
        }
        facts = {
            item["source_fact_id"]: item
            for item in proposed
            if item["source_fact_id"] in accepted_ids
        }
        report_by_fact = {
            fact_id: [
                item for item in reports if item["source_fact_id"] == fact_id
            ]
            for fact_id in accepted_ids
        }
        self.artifact_store.put_json(
            "verified_factbank",
            {
                "video_id": record["video_id"],
                "facts": list(facts.values()),
                "reflection_reports": [
                    report
                    for fact_reports in report_by_fact.values()
                    for report in fact_reports
                ],
            },
        )
        fact_extraction_output = make_stage_output(
            stage=FACT_EXTRACTION_AND_REFLECTION,
            video_id=record["video_id"],
            upstream=[category_retrieval_output],
            payload={
                "proposed_facts": proposed,
                "reflection_reports": reports,
                "fact_graph": graph_state["fact_graph"],
            },
            memory_snapshot=self.memory.snapshot(
                self._memory_categories(opportunity_matrix, proposed),
                video_id=record["video_id"],
            ),
        )
        self.artifact_store.put_json(
            "stage_fact_extraction_and_reflection",
            fact_extraction_output,
        )
        return {
            "record": record,
            "manifest": manifest,
            "native_media_ref": native_media_ref,
            "opportunity_matrix": opportunity_matrix,
            "fact_graph": graph_state["fact_graph"],
            "facts": facts,
            "reports": report_by_fact,
            "stage_outputs": {
                HALLUCINATION_CATEGORY_RETRIEVAL: category_retrieval_output,
                FACT_EXTRACTION_AND_REFLECTION: fact_extraction_output,
            },
        }

    def _realize(self, discovered: dict, fact: dict) -> dict:
        leaf = FACT_KIND_TO_LEAF[fact["fact_kind"]]
        operator = self.operator_by_leaf[leaf]
        task_type = discovered["record"]["task_type"]
        fixed_natural_answer = str(fact["natural_language_fact"]).strip()
        _require_complete_sentence(
            fixed_natural_answer,
            "natural_language_fact",
        )
        fixed_question, template_id = question_for_fact(
            task_type=task_type,
            video_id=discovered["record"]["video_id"],
            source_fact_id=fact["source_fact_id"],
            normalized_fact=fact["normalized_fact"],
            seed=self.selection_seed,
        )
        answer_form = answer_form_for(
            task_type=task_type,
            fact_kind=fact["fact_kind"],
        )
        form_instruction = answer_alignment_instruction(
            task_type=task_type,
            fact_kind=fact["fact_kind"],
            supported_fact=fact["normalized_fact"],
        )
        output = self._call(
            GENERATION_AGENT,
            {
                "video_id": discovered["record"]["video_id"],
                "leaf_label": leaf,
                "task_type": task_type,
                "source_fact": fact,
                "mutation_operator": operator,
                "fixed_question": fixed_question,
                "fixed_natural_answer": fixed_natural_answer,
                "question_template_id": template_id,
                "required_answer_form": answer_form,
                "instruction": (
                    "Use the fixed question exactly. Choose one plausible false "
                    "replacement_value for the frozen operator slot. Do not "
                    "change or restate any anchor field. Verbalize the "
                    "resulting one-slot mutation as the counterfactual answer. "
                    "The question template is immutable. "
                    + form_instruction
                ),
            },
            realization_schema_for(
                fact["fact_kind"], task_type=task_type
            ),
        )
        if output["question"] != fixed_question:
            raise ValueError("Language realization changed the frozen question")
        if (
            answer_form != "polar_explained_sentence"
            and output["answer"] != fixed_natural_answer
        ):
            raise ValueError(
                "Language realization changed the verified natural answer"
            )
        _require_complete_sentence(output["answer"], "answer")
        _require_complete_sentence(
            output["counterfactual_answer"], "counterfactual_answer"
        )
        mutated_fact = apply_slot_replacement(
            fact["normalized_fact"],
            replacement_value=output["replacement_value"],
        )
        mutation = validate_mutation(
            operator["operator_id"],
            fact["normalized_fact"],
            mutated_fact,
        )
        validate_question_answer_alignment(
            task_type=task_type,
            fact_kind=fact["fact_kind"],
            question=output["question"],
            answer=output["answer"],
            counterfactual_answer=output["counterfactual_answer"],
            supported_fact=fact["normalized_fact"],
            counterfactual_fact=mutated_fact,
        )
        return {
            **output,
            "mutated_fact": mutated_fact,
            "mutation": mutation,
            "question_template_id": template_id,
            "answer_form": answer_form,
        }

    def _backparse_pair(
        self,
        *,
        question: str,
        answer: str,
        counterfactual_answer: str,
        video_id: str,
        leaf_label: str,
        fact_kind: str,
        conflict_slot: str,
        canonical_anchor: dict,
        answer_form: str,
    ) -> dict:
        output = self._call(
            VERIFICATION_AGENT,
            {
                "video_id": video_id,
                "leaf_label": leaf_label,
                "question": question,
                "answer": answer,
                "counterfactual_answer": counterfactual_answer,
                "fact_kind": fact_kind,
                "required_conflict_slot": conflict_slot,
                "canonical_non_target_fields": canonical_anchor,
                "answer_form": answer_form,
                "instruction": (
                    "Jointly recover exactly one supported and one "
                    "counterfactual normalized atomic fact. Copy every supplied "
                    "canonical_non_target_field exactly into both facts. Parse "
                    "only the target conflict-slot value from each answer. "
                    "Treat any required Yes/No prefix as the polarity of the "
                    "existence slot, not as an additional claim. Include no "
                    "additional claim."
                ),
            },
            paired_backparse_schema_for(fact_kind),
        )
        for key in ("supported_fact", "counterfactual_fact"):
            fact = output[key]
            if fact.get("fact_kind") != fact_kind or conflict_slot not in fact:
                raise ValueError("Pair backparser returned the wrong structure")
            for anchor_key, anchor_value in canonical_anchor.items():
                if fact.get(anchor_key) != anchor_value:
                    raise ValueError(
                        "Pair backparser changed a canonical anchor"
                    )
        return output

    def _monitor_candidate(
        self,
        discovered: dict,
        candidate_payload: dict,
        role: str,
    ) -> dict:
        record = discovered["record"]
        payload = {
            "native_media_ref": discovered["native_media_ref"],
            "native_media_mime_type": detect_mime(Path(record["source_path"])),
            "_audit_canonical_source_sha256": record[
                "_canonical_source_sha256"
            ],
            "media_resolution": "high",
            "video_id": record["video_id"],
            "pair": candidate_payload,
            "instruction": (
                "Independently reread the high-resolution original video. "
                "First verify the natural answer against the video and confirm "
                "that it exactly verbalizes pair.authoritative_supported_fact "
                "within pair.time_scope; do not accept a merely well-formed "
                "pair whose natural answer is unsupported. Return a non-empty "
                "answer evidence summary and an overlapping answer evidence "
                "interval. Then verify the planned leaf boundary, confirm that "
                "the counterfactual is contradicted specifically under that "
                "leaf, exactly the declared target slot differs from the "
                "authoritative counterfactual structure, and no additional "
                "error exists."
            ),
        }
        report = self._call(role, payload, CANDIDATE_VERIFICATION_SCHEMA)
        if (
            report["answer_verdict"] == "insufficient"
            or report["counterfactual_verdict"] == "insufficient"
        ):
            report = self._focused_retry(
                role, payload, CANDIDATE_VERIFICATION_SCHEMA, report
            )
        if report["accepted"] and not _has_grounded_evidence(
            report,
            candidate_payload.get("time_scope"),
            interval_field="answer_evidence_interval",
        ):
            report = {
                **report,
                "accepted": False,
                "answer_verdict": "insufficient",
                "natural_answer_matches_source_fact": False,
                "answer_evidence_interval": None,
                "evidence_summary": (
                    "Rejected: the accepted candidate lacked a non-empty "
                    "natural-answer evidence summary and an interval "
                    "overlapping the authoritative source fact."
                ),
                "recoverable_reason": None,
            }
        return {
            **report,
            "agent_role": role,
            "shares_observations": False,
        }

    def _construct_candidate(self, discovered: dict, fact: dict) -> dict:
        leaf = FACT_KIND_TO_LEAF[fact["fact_kind"]]
        slot = LEAF_TO_SLOT[leaf]
        realization = self._realize(discovered, fact)
        source_fact = fact["normalized_fact"]
        mutated_fact = realization["mutated_fact"]
        authoritative_diff = assert_single_slot_change(
            source_fact,
            mutated_fact,
        )
        canonical_anchor = {
            key: value
            for key, value in source_fact.items()
            if key != slot
        }
        parsed = self._backparse_pair(
            question=realization["question"],
            answer=realization["answer"],
            counterfactual_answer=realization["counterfactual_answer"],
            video_id=discovered["record"]["video_id"],
            leaf_label=leaf,
            fact_kind=fact["fact_kind"],
            conflict_slot=slot,
            canonical_anchor=canonical_anchor,
            answer_form=realization["answer_form"],
        )
        supported = parsed["supported_fact"]
        counterfactual = parsed["counterfactual_fact"]
        structure_audit = {
            "video_id": discovered["record"]["video_id"],
            "source_fact_id": fact["source_fact_id"],
            "fact_kind": fact["fact_kind"],
            "leaf_label": leaf,
            "conflict_slot": slot,
            "question_template_id": realization["question_template_id"],
            "answer_form": realization["answer_form"],
            "question": realization["question"],
            "answer": realization["answer"],
            "counterfactual_answer": realization["counterfactual_answer"],
            "authoritative_supported_fact": source_fact,
            "authoritative_counterfactual_fact": mutated_fact,
            "backparsed_supported_fact": supported,
            "backparsed_counterfactual_fact": counterfactual,
        }
        self.artifact_store.put_json(
            "pair_structure_audit",
            structure_audit,
        )
        if supported != source_fact or counterfactual != mutated_fact:
            mismatches = sorted(
                key
                for key in set(source_fact)
                | set(mutated_fact)
                | set(supported)
                | set(counterfactual)
                if (
                    source_fact.get(key) != supported.get(key)
                    or mutated_fact.get(key) != counterfactual.get(key)
                )
            )
            self.artifact_store.put_json(
                "pair_structure_rejection",
                {
                    **structure_audit,
                    "mismatched_fields": mismatches,
                },
            )
            raise ValueError(
                "Joint backparse disagrees with the authoritative one-slot "
                "pair at fields: %s" % ", ".join(mismatches)
            )
        parsed_diff = assert_single_slot_change(supported, counterfactual)
        if parsed_diff != authoritative_diff:
            raise ValueError("Joint backparse changed the authoritative GraphDiff")
        changed_slot = authoritative_diff["changed_paths"][0].rsplit(".", 1)[-1]
        if changed_slot != slot:
            raise ValueError("Backparsed answer pair changed the wrong slot")
        public_media = {
            "video_id": discovered["manifest"]["video_id"],
            "canonical_media_uri": discovered["manifest"][
                "canonical_media_uri"
            ],
            "registered_modalities": discovered["manifest"][
                "registered_modalities"
            ],
            "evidence_policy_id": "gemini_native_original_video_v1",
        }
        pair_id = "pair_%s_%s" % (
            _safe_id(discovered["record"]["video_id"]),
            _safe_id(fact["source_fact_id"]),
        )
        verification_payload = {
            "pair_id": pair_id,
            "question": realization["question"],
            "answer": realization["answer"],
            "counterfactual_answer": realization["counterfactual_answer"],
            "answer_form": realization["answer_form"],
            "leaf_label": leaf,
            "conflict_slot": slot,
            "time_scope": fact["time_scope"],
            "authoritative_supported_fact": source_fact,
            "authoritative_counterfactual_fact": mutated_fact,
            "planned_leaf_rule": next(
                item
                for item in self.leaf_search_plan["leaves"]
                if item["leaf_label"] == leaf
            ),
        }
        pair_generation_output = make_stage_output(
            stage=GENERATION_AND_VERIFICATION,
            video_id=discovered["record"]["video_id"],
            upstream=[
                discovered["stage_outputs"][FACT_EXTRACTION_AND_REFLECTION]
            ],
            payload={
                "pair": verification_payload,
                "supported_fact": supported,
                "counterfactual_fact": counterfactual,
                "graph_diff": authoritative_diff,
            },
            memory_snapshot=self.memory.snapshot(
                (leaf,),
                video_id=discovered["record"]["video_id"],
            ),
        )
        self.artifact_store.put_json(
            "stage_generation_and_verification_of_adversarial_pairs",
            pair_generation_output,
        )
        verification_payload["upstream_stage_output"] = pair_generation_output
        monitor_reports = [
            self._monitor_candidate(
                discovered,
                verification_payload,
                MONITOR_AGENT,
            )
        ]
        reliability_output = make_stage_output(
            stage=COMPREHENSIVE_RELIABILITY_VALIDATION,
            video_id=discovered["record"]["video_id"],
            upstream=[pair_generation_output],
            payload={
                "pair_id": pair_id,
                "monitor_reports": monitor_reports,
                "accepted": all(
                    item.get("accepted") is True for item in monitor_reports
                ),
            },
            memory_snapshot=self.memory.snapshot(
                (leaf,),
                video_id=discovered["record"]["video_id"],
            ),
        )
        self.artifact_store.put_json(
            "stage_comprehensive_reliability_validation",
            reliability_output,
        )
        return {
            **verification_payload,
            "source_fact_id": fact["source_fact_id"],
            "fact_kind": fact["fact_kind"],
            "media": public_media,
            "task_type": discovered["record"]["task_type"],
            "graph_diff": authoritative_diff,
            "question_template_id": realization["question_template_id"],
            "answer_form": realization["answer_form"],
            "supported_fact": supported,
            "counterfactual_fact": counterfactual,
            "supported_contradicted_count": 0,
            "counterfactual_contradicted_count": 1,
            "additional_error_count": max(
                item["additional_error_count"] for item in monitor_reports
            ),
            "monitor_reports": monitor_reports,
            "stage_outputs": {
                GENERATION_AND_VERIFICATION: pair_generation_output,
                COMPREHENSIVE_RELIABILITY_VALIDATION: reliability_output,
            },
        }

    def run(self, source_records: Iterable[dict]) -> dict:
        discovered = [
            self._discover_video(dict(record)) for record in source_records
        ]
        by_video = {
            item["record"]["video_id"]: item for item in discovered
        }
        eligibility = []
        for item in discovered:
            for fact in item["facts"].values():
                eligibility.append(
                    evaluate_eligibility(
                        fact,
                        video_id=item["record"]["video_id"],
                        task_type=item["record"]["task_type"],
                        reflection_accepted=True,
                        dependency_evaluable=True,
                        alternative_count=1,
                    )
                )
        existing_records = read_jsonl(self.output_path)
        current_leaf_counts = Counter(
            str(item["leaf_label"]) for item in existing_records
        )
        remaining = (
            None
            if self.target_pairs is None
            else max(0, self.target_pairs - len(existing_records))
        )
        selected = select_faithful_relative(
            eligibility,
            target_pairs=remaining,
            per_video_pair_cap=self.per_video_pair_cap,
            seed=self.selection_seed,
            current_leaf_counts=current_leaf_counts,
        )
        emitted = 0
        skipped_existing = 0
        rejection_reasons = {}
        existing_pair_ids = {
            str(item["pair_id"]) for item in existing_records
        }
        for selection in selected:
            item = by_video[selection["video_id"]]
            fact = item["facts"][selection["source_fact_id"]]
            expected_pair_id = "pair_%s_%s" % (
                _safe_id(selection["video_id"]),
                _safe_id(selection["source_fact_id"]),
            )
            if expected_pair_id in existing_pair_ids:
                skipped_existing += 1
                self.events.emit(
                    "BuildGraph",
                    "candidate_skipped_existing_pair",
                    {"pair_id": expected_pair_id},
                )
                continue
            try:
                candidate = self._construct_candidate(item, fact)
                compiled_graph(self.profile).invoke(
                    {
                        "run_id": self.run_id,
                        "dataset_id": self.dataset_id,
                        "profile": self.profile,
                        "output_path": str(self.output_path),
                        "video_manifests": [item["manifest"]],
                        "fact_graphs": [item["fact_graph"]],
                        "leaf_search_plan": self.leaf_search_plan,
                        "leaf_opportunity_matrices": [
                            item["opportunity_matrix"]
                        ],
                        "leaf_conditioned_facts": list(
                            item["facts"].values()
                        ),
                        "reflection_reports": [
                            report
                            for reports in item["reports"].values()
                            for report in reports
                        ],
                        "eligibility_records": [selection],
                        "candidates": [candidate],
                        "total_pair_limit": self.target_pairs,
                    }
                )
                emitted += 1
                existing_pair_ids.add(candidate["pair_id"])
            except Exception as exc:
                reason = type(exc).__name__ + ": " + redact_sensitive(exc)
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                self.events.emit(
                    "BuildGraph",
                    "candidate_rejected",
                    {
                        "video_id": selection["video_id"],
                        "source_fact_id": selection["source_fact_id"],
                        "reason": reason,
                    },
                )
        return {
            "source_video_count": len(discovered),
            "verified_fact_count": len(eligibility),
            "selected_fact_count": len(selected),
            "emitted_pair_count": emitted,
            "skipped_existing_pair_count": skipped_existing,
            "rejection_reasons": rejection_reasons,
            "output": str(self.output_path),
        }
