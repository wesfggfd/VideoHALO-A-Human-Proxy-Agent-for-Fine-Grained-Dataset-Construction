"""Windowed, resumable VideoHALO construction for large local video sets.

The pipeline keeps the semantic dependency chain serial inside each video,
while processing independent videos with bounded concurrency. Canonical source
videos are materialized as immutable private GCS objects one window ahead.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from uuid import uuid4

from .contracts.registry import ContractRegistry
from .live_build import LiveBuildRunner
from .media.gcs import acquire_or_reuse_gcs_object
from .media.lease_registry import ProviderLeaseRegistry
from .media.register import detect_mime, register_media
from .observability import RuntimeEventLogger
from .providers.gcs import GoogleCloudStorageAdapter
from .providers.safety import (
    PROVIDER_CIRCUIT,
    ProviderCircuitOpenError,
    redact_sensitive,
)
from .resolvers.taxonomy import LEAF_TO_SLOT
from .runtime_metrics import collect_event_metrics, estimate_cost
from .settings import get_settings
from .stores.artifacts import LocalArtifactStore
from .stores.jsonl import read_jsonl


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(
            descriptor, "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Windows scanners/indexers can briefly hold the previous status file
        # open, causing an otherwise valid atomic replace to fail with
        # ``WinError 5``.  Keep the atomic-write guarantee, but tolerate that
        # short-lived lock instead of aborting a long build.
        for attempt in range(8):
            try:
                os.replace(temporary_name, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (2**attempt))
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _process_is_alive(pid: int) -> bool:
    if pid < 1:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(
        synchronize, False, int(pid)
    )
    if not handle:
        return False
    try:
        return (
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
            == wait_timeout
        )
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


@contextmanager
def exclusive_run_lock(path: Path, metadata: dict):
    """Reject a second process for the same formal output/status pair."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    owner_token = uuid4().hex
    payload = {
        **metadata,
        "pid": os.getpid(),
        "owner_token": owner_token,
        "acquired_at": utc_now(),
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    while True:
        try:
            descriptor = os.open(
                str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
        except FileExistsError:
            try:
                existing = json.loads(
                    path.read_text(encoding="utf-8-sig")
                )
            except (OSError, json.JSONDecodeError):
                existing = {}
            existing_pid = int(existing.get("pid", 0) or 0)
            if _process_is_alive(existing_pid):
                raise RuntimeError(
                    "Another VideoHALO run owns %s (pid=%d, run_id=%s)"
                    % (
                        path,
                        existing_pid,
                        existing.get("run_id", "unknown"),
                    )
                )
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
        break
    try:
        yield payload
    finally:
        try:
            current = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            current = {}
        if current.get("owner_token") == owner_token:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def split_windows(values: list[dict], size: int) -> list[list[dict]]:
    if size < 1:
        raise ValueError("window size must be positive")
    return [values[index : index + size] for index in range(0, len(values), size)]


def submission_plan(
    *,
    current_pairs: int,
    target_pairs: int,
    workers: int,
    per_video_pair_cap: int,
    in_flight: int,
) -> tuple[int, Optional[int]]:
    """Return desired concurrency and cap for the next submitted video.

    Near the global target the scheduler drains parallel work and switches to
    one video at a time, reducing the last video's cap when necessary.  This
    guarantees that concurrent videos cannot overshoot the public pair target.
    """
    remaining = target_pairs - current_pairs
    if remaining <= 0:
        return 0, None
    full_parallel_capacity = workers * per_video_pair_cap
    desired = workers if remaining >= full_parallel_capacity else 1
    if in_flight >= desired:
        return desired, None
    if desired == 1:
        return desired, min(per_video_pair_cap, remaining)
    if remaining < (in_flight + 1) * per_video_pair_cap:
        return desired, None
    return desired, per_video_pair_cap


class WindowedBuildOrchestrator:
    """Run a large selection with rolling media windows and video workers."""

    def __init__(
        self,
        *,
        selection_path: Path,
        output_path: Path,
        status_path: Path,
        dataset_id: str,
        run_id: str,
        target_pairs: int = 800,
        window_size: int = 400,
        video_workers: int = 2,
        upload_workers: int = 6,
        per_video_pair_cap: int = 2,
        selection_seed: int = 42,
        max_video_attempts: int = 2,
        process_all_videos: bool = False,
        budget_policy_path: Optional[Path] = None,
        runner_factory: Optional[Callable[..., LiveBuildRunner]] = None,
    ):
        if target_pairs < 1:
            raise ValueError("target_pairs must be positive")
        if video_workers < 1 or upload_workers < 1:
            raise ValueError("worker counts must be positive")
        if per_video_pair_cap < 1 or max_video_attempts < 1:
            raise ValueError("caps and attempts must be positive")
        self.selection_path = selection_path.resolve()
        self.output_path = output_path.resolve()
        self.status_path = status_path.resolve()
        self.dataset_id = dataset_id
        self.run_id = run_id
        self.target_pairs = target_pairs
        self.window_size = window_size
        self.video_workers = video_workers
        self.upload_workers = upload_workers
        self.per_video_pair_cap = per_video_pair_cap
        self.selection_seed = selection_seed
        self.max_video_attempts = max_video_attempts
        self.process_all_videos = process_all_videos
        self.budget_policy_path = (
            budget_policy_path.resolve()
            if budget_policy_path is not None
            else None
        )
        self.budget_policy = (
            json.loads(
                self.budget_policy_path.read_text(encoding="utf-8-sig")
            )
            if self.budget_policy_path is not None
            else None
        )
        if (
            self.budget_policy is not None
            and int(self.budget_policy["target_accepted_pairs"])
            != self.target_pairs
        ):
            raise ValueError(
                "Budget policy target does not match --target-pairs"
            )
        self.budget_stop_reached = False
        self._last_metric_refresh_monotonic = 0.0
        self._metric_cache: dict = {}
        self.run_lock_path = self.status_path.with_suffix(
            self.status_path.suffix + ".run.lock"
        )
        self.runner_factory = runner_factory or LiveBuildRunner
        self.settings = get_settings()
        self.artifact_store = LocalArtifactStore(
            self.settings.artifact_root, self.dataset_id
        )
        self.lease_registry = ProviderLeaseRegistry(
            self.settings.artifact_root
            / self.dataset_id
            / "ledgers"
            / "provider_media_leases.sqlite"
        )
        self.preload_events = RuntimeEventLogger(
            self.output_path.parent / "preupload.events.jsonl"
        )
        self._thread_local = threading.local()
        self._upload_thread_local = threading.local()

        document = json.loads(
            self.selection_path.read_text(encoding="utf-8-sig")
        )
        self.videos = list(document["videos"])
        targets = {
            str(key): int(value)
            for key, value in document["policy"]["task_targets"].items()
        }
        if len(self.videos) != sum(targets.values()):
            raise RuntimeError("Selection count does not match task targets")
        if Counter(item["task_type"] for item in self.videos) != targets:
            raise RuntimeError("Selection task allocation is inconsistent")
        if len({item["video_id"] for item in self.videos}) != len(self.videos):
            raise RuntimeError("Selection contains duplicate video IDs")
        self.selection_sha256 = sha256_path(self.selection_path)
        self.windows = split_windows(self.videos, self.window_size)
        self.status = self._load_status()

    def _load_status(self) -> dict:
        if self.status_path.exists():
            value = json.loads(
                self.status_path.read_text(encoding="utf-8-sig")
            )
            if value.get("selection_sha256") != self.selection_sha256:
                raise RuntimeError("Existing status belongs to another selection")
            if value.get("total_video_count") != len(self.videos):
                raise RuntimeError("Existing status has another video count")
            value["state"] = "running"
            value["resumed_at"] = utc_now()
            value["run_id"] = self.run_id
            value["target_pair_count"] = self.target_pairs
            value["window_size"] = self.window_size
            value["video_workers"] = self.video_workers
            value["upload_workers"] = self.upload_workers
            value["process_all_videos"] = self.process_all_videos
            value["budget_policy_path"] = (
                str(self.budget_policy_path)
                if self.budget_policy_path is not None
                else None
            )
            return value
        return {
            "schema_version": "videohalo_windowed_run_status_3.7.1",
            "run_id": self.run_id,
            "state": "initialized",
            "selection_path": str(self.selection_path),
            "selection_sha256": self.selection_sha256,
            "total_video_count": len(self.videos),
            "target_pair_count": self.target_pairs,
            "window_size": self.window_size,
            "window_count": len(self.windows),
            "video_workers": self.video_workers,
            "upload_workers": self.upload_workers,
            "process_all_videos": self.process_all_videos,
            "budget_policy_path": (
                str(self.budget_policy_path)
                if self.budget_policy_path is not None
                else None
            ),
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "current_window": None,
            "current_videos": {},
            "results": {},
            "windows": {},
        }

    def _pair_count(self) -> int:
        return len(read_jsonl(self.output_path))

    def _refresh_status(self) -> None:
        results = list(self.status["results"].values())
        completed = [item for item in results if item["status"] == "completed"]
        failed = [item for item in results if item["status"] == "failed"]
        self.status["completed_video_count"] = len(completed)
        self.status["failed_video_count"] = len(failed)
        self.status["pending_video_count"] = (
            len(self.videos) - len(completed) - len(failed)
        )
        pairs = read_jsonl(self.output_path)
        self.status["total_pair_count"] = len(pairs)
        leaf_counts = Counter(
            str(item["leaf_label"]) for item in pairs
        )
        task_counts = Counter(
            str(item["task_type"]) for item in pairs
        )
        task_leaf_counts = Counter(
            "%s::%s" % (item["task_type"], item["leaf_label"])
            for item in pairs
        )
        self.status["pair_distribution"] = {
            "by_leaf": {
                leaf: leaf_counts[leaf] for leaf in LEAF_TO_SLOT
            },
            "by_task": dict(task_counts),
            "by_task_and_leaf": dict(task_leaf_counts),
            "nonzero_leaf_count": sum(
                leaf_counts[leaf] > 0 for leaf in LEAF_TO_SLOT
            ),
            "maximum_leaf_share": (
                max(leaf_counts.values()) / len(pairs)
                if pairs
                else 0.0
            ),
        }
        self.status["completed_by_task"] = dict(
            Counter(item["task_type"] for item in completed)
        )
        self.status["failed_by_task"] = dict(
            Counter(item["task_type"] for item in failed)
        )
        now = datetime.now(timezone.utc)
        started = datetime.fromisoformat(
            str(
                self.status.get("enterprise_run_started_at")
                or self.status["started_at"]
            ).replace("Z", "+00:00")
        )
        elapsed_seconds = max(0.0, (now - started).total_seconds())
        completed_durations = []
        legacy_completed_ids = set(
            self.status.get("migration", {}).get(
                "preserved_completed_video_ids", []
            )
        )
        for video_id, item in self.status["results"].items():
            if item.get("status") != "completed" or video_id in legacy_completed_ids:
                continue
            completed_durations.append(
                (
                    datetime.fromisoformat(
                        str(item["completed_at"]).replace("Z", "+00:00")
                    )
                    - datetime.fromisoformat(
                        str(item["started_at"]).replace("Z", "+00:00")
                    )
                ).total_seconds()
            )
        monotonic_now = time.monotonic()
        if (
            not self._metric_cache
            or monotonic_now - self._last_metric_refresh_monotonic >= 5.0
        ):
            self._metric_cache = collect_event_metrics(self.output_path)
            self._last_metric_refresh_monotonic = monotonic_now
        runtime_metrics = {
            **self._metric_cache,
            "wall_seconds": round(elapsed_seconds, 6),
            "accepted_pairs_per_hour": (
                round(
                    max(
                        0,
                        len(pairs)
                        - int(
                            self.status.get(
                                "resume_baseline_pair_count", 0
                            )
                        ),
                    )
                    / (elapsed_seconds / 3600.0),
                    6,
                )
                if elapsed_seconds > 0
                else 0.0
            ),
            "completed_videos_per_hour": (
                round(
                    max(
                        0,
                        len(completed)
                        - int(
                            self.status.get(
                                "resume_baseline_completed_video_count", 0
                            )
                        ),
                    )
                    / (elapsed_seconds / 3600.0),
                    6,
                )
                if elapsed_seconds > 0
                else 0.0
            ),
            "mean_video_inference_seconds": (
                round(
                    sum(completed_durations) / len(completed_durations),
                    6,
                )
                if completed_durations
                else None
            ),
        }
        if self.budget_policy is not None:
            runtime_metrics["estimated_cost"] = estimate_cost(
                runtime_metrics["usage"],
                self.budget_policy["billing_formula"],
            )
            runtime_metrics["live_cost_stop_aud"] = float(
                self.budget_policy["live_cost_stop_aud"]
            )
            if (
                runtime_metrics["estimated_cost"]["aud_including_gst"]
                >= runtime_metrics["live_cost_stop_aud"]
            ):
                self.budget_stop_reached = True
        runtime_metrics["budget_stop_reached"] = self.budget_stop_reached
        self.status["runtime_metrics"] = runtime_metrics
        self.status["updated_at"] = utc_now()

    def _write_status(self) -> None:
        self._refresh_status()
        atomic_json_write(self.status_path, self.status)

    def _preload_one(self, record: dict) -> dict:
        source = Path(record["source_path"]).resolve()
        manifest = register_media(
            source=source,
            video_id=record["video_id"],
            ffprobe_bin=self.settings.ffprobe_bin,
            ffmpeg_bin=self.settings.ffmpeg_bin,
            provider_state="pending",
        )
        ContractRegistry().validate("video_manifest.schema.json", manifest)
        self.artifact_store.put_json("video_manifest", manifest)
        adapter = getattr(self._upload_thread_local, "adapter", None)
        if adapter is None:
            adapter = GoogleCloudStorageAdapter()
            self._upload_thread_local.adapter = adapter
        lease = acquire_or_reuse_gcs_object(
            registry=self.lease_registry,
            adapter=adapter,
            project=self.settings.require_google_cloud_project(),
            bucket=self.settings.require_gcs_bucket(),
            prefix=self.settings.google_cloud_storage_prefix,
            source_path=source,
            manifest=manifest,
            mime_type=detect_mime(source),
        )
        active_manifest = dict(manifest)
        active_manifest["provider_state"] = "active"
        ContractRegistry().validate(
            "video_manifest.schema.json", active_manifest
        )
        self.artifact_store.put_json("video_manifest", active_manifest)
        self.artifact_store.put_json("provider_media_lease", lease)
        self.preload_events.emit(
            "PrivateGCS",
            "video_materialized",
            {
                "video_id": record["video_id"],
                "upload_bytes": lease["upload_bytes"],
                "reused": bool(lease.get("reuse_count")),
            },
        )
        return {
            "manifest": active_manifest,
            "native_media_ref": lease["provider_media_uri"],
            "lease": lease,
        }

    def _preload_window(
        self, window_index: int, records: Iterable[dict]
    ) -> dict:
        records = [
            item
            for item in records
            if self.status["results"].get(item["video_id"], {}).get("status")
            != "completed"
        ]
        started = utc_now()
        media: dict[str, dict] = {}
        failures: dict[str, str] = {}
        with ThreadPoolExecutor(
            max_workers=self.upload_workers,
            thread_name_prefix=f"upload_w{window_index + 1}",
        ) as executor:
            future_to_record = {
                executor.submit(self._preload_one, record): record
                for record in records
            }
            for future, record in list(future_to_record.items()):
                try:
                    media[record["video_id"]] = future.result()
                except Exception as exc:
                    failures[record["video_id"]] = type(exc).__name__ + ": " + redact_sensitive(exc)
                    self.preload_events.emit(
                        "PrivateGCS",
                        "video_materialization_failed",
                        {
                            "video_id": record["video_id"],
                            "reason": failures[record["video_id"]],
                        },
                    )
        PROVIDER_CIRCUIT.raise_if_open()
        return {
            "window_index": window_index,
            "started_at": started,
            "completed_at": utc_now(),
            "requested_count": len(records),
            "active_count": len(media),
            "failed_count": len(failures),
            "failures": failures,
            "media": media,
        }

    def _worker_runner(self) -> LiveBuildRunner:
        runner = getattr(self._thread_local, "runner", None)
        if runner is None:
            worker_name = re.sub(
                r"[^0-9A-Za-z_]+",
                "_",
                threading.current_thread().name,
            )
            runner = self.runner_factory(
                output_path=self.output_path,
                dataset_id=self.dataset_id,
                profile="probe_build",
                target_pairs=self.target_pairs,
                per_video_pair_cap=self.per_video_pair_cap,
                selection_seed=self.selection_seed,
                run_id=self.run_id,
                event_log_path=(
                    self.output_path.parent
                    / "events"
                    / (worker_name + ".jsonl")
                ),
            )
            self._thread_local.runner = runner
        return runner

    def _process_one(self, record: dict, pair_cap: int) -> dict:
        runner = self._worker_runner()
        runner.per_video_pair_cap = pair_cap
        return runner.run([record])

    def _prepared_record(self, record: dict, media: dict[str, dict]) -> dict:
        prepared = dict(record)
        materialized = media.get(record["video_id"])
        if materialized:
            prepared["_preloaded_video_manifest"] = materialized["manifest"]
            prepared["_preloaded_native_media_ref"] = materialized[
                "native_media_ref"
            ]
            prepared["_preloaded_media_lease"] = materialized["lease"]
        return prepared

    def _process_window(
        self, window_index: int, records: list[dict], media: dict[str, dict]
    ) -> bool:
        pending = deque()
        for record in records:
            prior = self.status["results"].get(record["video_id"])
            if prior and prior.get("status") == "completed":
                continue
            if prior and int(prior.get("attempts", 0)) >= self.max_video_attempts:
                continue
            pending.append(record)
        in_flight: dict[Future, tuple[dict, int, int]] = {}
        self.status["state"] = "running"
        self.status["current_window"] = window_index + 1
        self._write_status()

        with ThreadPoolExecutor(
            max_workers=self.video_workers,
            thread_name_prefix="video_worker",
        ) as executor:
            while pending or in_flight:
                current_pairs = self._pair_count()
                if self.budget_stop_reached:
                    desired, next_cap = 0, None
                elif self.process_all_videos:
                    desired = self.video_workers
                    next_cap = (
                        self.per_video_pair_cap
                        if len(in_flight) < desired
                        else None
                    )
                else:
                    desired, next_cap = submission_plan(
                        current_pairs=current_pairs,
                        target_pairs=self.target_pairs,
                        workers=self.video_workers,
                        per_video_pair_cap=self.per_video_pair_cap,
                        in_flight=len(in_flight),
                    )
                while pending and next_cap is not None and len(in_flight) < desired:
                    record = pending.popleft()
                    prior = self.status["results"].get(record["video_id"], {})
                    attempts = int(prior.get("attempts", 0)) + 1
                    prepared = self._prepared_record(record, media)
                    future = executor.submit(
                        self._process_one, prepared, next_cap
                    )
                    in_flight[future] = (record, attempts, next_cap)
                    started = utc_now()
                    self.status["results"][record["video_id"]] = {
                        "sequence": record["sequence"],
                        "task_type": record["task_type"],
                        "source_path": record["source_path"],
                        "status": "running",
                        "attempts": attempts,
                        "started_at": started,
                        "window": window_index + 1,
                    }
                    self.status["current_videos"][record["video_id"]] = {
                        "sequence": record["sequence"],
                        "attempt": attempts,
                        "pair_cap": next_cap,
                        "started_at": started,
                    }
                    self._write_status()
                    current_pairs = self._pair_count()
                    if self.budget_stop_reached:
                        desired, next_cap = 0, None
                    elif self.process_all_videos:
                        desired = self.video_workers
                        next_cap = (
                            self.per_video_pair_cap
                            if len(in_flight) < desired
                            else None
                        )
                    else:
                        desired, next_cap = submission_plan(
                            current_pairs=current_pairs,
                            target_pairs=self.target_pairs,
                            workers=self.video_workers,
                            per_video_pair_cap=self.per_video_pair_cap,
                            in_flight=len(in_flight),
                        )

                if not in_flight:
                    break
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    record, attempts, pair_cap = in_flight.pop(future)
                    video_id = record["video_id"]
                    self.status["current_videos"].pop(video_id, None)
                    try:
                        result = future.result()
                        self.status["results"][video_id].update(
                            {
                                "status": "completed",
                                "completed_at": utc_now(),
                                "verified_fact_count": result[
                                    "verified_fact_count"
                                ],
                                "selected_fact_count": result[
                                    "selected_fact_count"
                                ],
                                "emitted_pair_count": result[
                                    "emitted_pair_count"
                                ],
                                "skipped_existing_pair_count": result[
                                    "skipped_existing_pair_count"
                                ],
                                "rejection_reasons": result[
                                    "rejection_reasons"
                                ],
                                "pair_cap": pair_cap,
                            }
                        )
                    except Exception as exc:
                        if PROVIDER_CIRCUIT.is_open:
                            # Authentication/project failures are operational,
                            # not video failures.  Preserve this source as pending
                            # and do not consume its bounded quality attempt.
                            self.status["results"][video_id].update(
                                {
                                    "status": "pending_provider_stop",
                                    "attempts": max(0, attempts - 1),
                                    "interrupted_at": utc_now(),
                                    "error_type": type(exc).__name__,
                                    "error": redact_sensitive(exc),
                                }
                            )
                        else:
                            self.status["results"][video_id].update(
                                {
                                    "status": "failed",
                                    "failed_at": utc_now(),
                                    "error_type": type(exc).__name__,
                                    "error": redact_sensitive(exc),
                                }
                            )
                            if attempts < self.max_video_attempts:
                                pending.append(record)
                    self._write_status()
                if PROVIDER_CIRCUIT.is_open:
                    pending.clear()
                    for outstanding in in_flight:
                        outstanding.cancel()
                    PROVIDER_CIRCUIT.raise_if_open()

        return self._pair_count() >= self.target_pairs

    def run(self) -> dict:
        with exclusive_run_lock(
            self.run_lock_path,
            {
                "run_id": self.run_id,
                "selection_path": str(self.selection_path),
                "output_path": str(self.output_path),
                "status_path": str(self.status_path),
            },
        ):
            try:
                return self._run_locked()
            except ProviderCircuitOpenError as exc:
                self.status["state"] = "stopped_provider_auth"
                self.status["provider_stop_reason"] = redact_sensitive(exc)
                self.status["current_window"] = None
                self.status["current_videos"] = {}
                self.status["completed_at"] = utc_now()
                self._write_status()
                return {
                    "ok": False,
                    "state": self.status["state"],
                    "completed_video_count": self.status["completed_video_count"],
                    "failed_video_count": self.status["failed_video_count"],
                    "total_pair_count": self.status["total_pair_count"],
                    "output": str(self.output_path),
                    "status": str(self.status_path),
                }

    def _run_locked(self) -> dict:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.status.setdefault("enterprise_run_started_at", utc_now())
        self.status["state"] = "preloading"
        self._write_status()
        preload_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="window_prefetch"
        )
        current_preload = self._preload_window(0, self.windows[0])
        self.status["windows"]["1"] = {
            key: value
            for key, value in current_preload.items()
            if key != "media"
        }
        next_future: Optional[Future] = None
        if len(self.windows) > 1:
            next_future = preload_executor.submit(
                self._preload_window, 1, self.windows[1]
            )
        target_reached = False
        try:
            for window_index, records in enumerate(self.windows):
                if window_index:
                    if next_future is None:
                        current_preload = self._preload_window(
                            window_index, records
                        )
                    else:
                        current_preload = next_future.result()
                    self.status["windows"][str(window_index + 1)] = {
                        key: value
                        for key, value in current_preload.items()
                        if key != "media"
                    }
                    next_future = None
                if (
                    next_future is None
                    and window_index + 1 < len(self.windows)
                ):
                    next_future = preload_executor.submit(
                        self._preload_window,
                        window_index + 1,
                        self.windows[window_index + 1],
                    )
                target_reached = self._process_window(
                    window_index, records, current_preload["media"]
                )
                self.status["windows"][str(window_index + 1)][
                    "retained_private_gcs_objects"
                ] = len(current_preload["media"])
                self._write_status()
                if self.budget_stop_reached:
                    if next_future is not None:
                        unused_preload = next_future.result()
                        self.status["windows"][
                            str(window_index + 2)
                        ] = {
                            key: value
                            for key, value in unused_preload.items()
                            if key != "media"
                        }
                        self.status["windows"][str(window_index + 2)][
                            "retained_private_gcs_objects"
                        ] = len(unused_preload["media"])
                    break
                if target_reached and not self.process_all_videos:
                    if next_future is not None:
                        unused_preload = next_future.result()
                        self.status["windows"][
                            str(window_index + 2)
                        ] = {
                            key: value
                            for key, value in unused_preload.items()
                            if key != "media"
                        }
                        self.status["windows"][str(window_index + 2)][
                            "retained_private_gcs_objects"
                        ] = len(unused_preload["media"])
                    break
        finally:
            preload_executor.shutdown(wait=True, cancel_futures=False)

        exhausted = [
            item
            for item in self.status["results"].values()
            if item["status"] == "failed"
            and int(item.get("attempts", 0)) >= self.max_video_attempts
        ]
        self.status["state"] = (
            "completed_target"
            if target_reached
            else "stopped_budget"
            if self.budget_stop_reached
            else "completed_sources"
            if self.process_all_videos and not exhausted
            else "completed_with_failures"
            if exhausted
            else "completed_sources"
        )
        self.status["current_window"] = None
        self.status["current_videos"] = {}
        self.status["completed_at"] = utc_now()
        self._last_metric_refresh_monotonic = 0.0
        self._write_status()
        ok = (
            not self.budget_stop_reached
            and (target_reached or not exhausted)
        )
        return {
            "ok": ok,
            "state": self.status["state"],
            "completed_video_count": self.status["completed_video_count"],
            "failed_video_count": self.status["failed_video_count"],
            "total_pair_count": self.status["total_pair_count"],
            "output": str(self.output_path),
            "status": str(self.status_path),
        }
