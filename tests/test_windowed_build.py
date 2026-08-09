import json
from pathlib import Path

import pytest

from videohalo.live_build import LiveBuildRunner
from videohalo.runtime_metrics import collect_event_metrics
from videohalo.windowed_build import (
    exclusive_run_lock,
    split_windows,
    submission_plan,
)


def test_split_windows_preserves_order_and_tail():
    values = [{"sequence": value} for value in range(1, 11)]
    windows = split_windows(values, 4)
    assert [[item["sequence"] for item in window] for window in windows] == [
        [1, 2, 3, 4],
        [5, 6, 7, 8],
        [9, 10],
    ]


@pytest.mark.parametrize(
    ("current", "in_flight", "desired", "cap"),
    [
        (796, 0, 2, 2),
        (796, 1, 2, 2),
        (797, 0, 1, 2),
        (799, 0, 1, 1),
        (800, 0, 0, None),
    ],
)
def test_submission_plan_cannot_overshoot_target(
    current, in_flight, desired, cap
):
    assert submission_plan(
        current_pairs=current,
        target_pairs=800,
        workers=2,
        per_video_pair_cap=2,
        in_flight=in_flight,
    ) == (desired, cap)


@pytest.mark.parametrize(
    ("current", "in_flight", "desired", "cap"),
    [
        (1994, 0, 3, 2),
        (1994, 2, 3, 2),
        (1995, 0, 1, 2),
        (1999, 0, 1, 1),
        (2000, 0, 0, None),
    ],
)
def test_three_worker_submission_plan_cannot_overshoot_2000(
    current, in_flight, desired, cap
):
    assert submission_plan(
        current_pairs=current,
        target_pairs=2000,
        workers=3,
        per_video_pair_cap=2,
        in_flight=in_flight,
    ) == (desired, cap)


def test_preloaded_media_shortcut_checks_canonical_bytes(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"canonical")
    import hashlib

    digest = hashlib.sha256(b"canonical").hexdigest()
    manifest = {
        "schema_version": "videohalo_video_manifest_3.7.1",
        "video_id": "video_001",
        "source_sha256": digest,
        "canonical_media_uri": "media://video_001/original",
        "registered_modalities": [
            "visual",
            "speech_audio",
            "non_speech_audio",
            "on_screen_text",
            "camera_editing",
            "container_metadata",
        ],
        "provider_transport": "private_gcs_uri",
        "provider_state": "active",
    }
    runner = object.__new__(LiveBuildRunner)
    lease = {
        "state": "active",
        "source_sha256": digest,
        "provider_media_uri": "gs://private-bucket/files/1",
        "source_ref": {
            "sha256": digest,
            "uri": source.resolve().as_uri(),
        },
    }
    observed, media_ref = runner._register_and_materialize(
        {
            "video_id": "video_001",
            "source_path": str(source),
            "_preloaded_video_manifest": manifest,
            "_preloaded_native_media_ref": "gs://private-bucket/files/1",
            "_preloaded_media_lease": lease,
        }
    )
    assert observed == manifest
    assert media_ref == "gs://private-bucket/files/1"

    wrong_lease = {
        **lease,
        "provider_media_uri": "gs://private-bucket/files/wrong",
    }
    with pytest.raises(ValueError, match="lease does not match"):
        runner._register_and_materialize(
            {
                "video_id": "video_001",
                "source_path": str(source),
                "_preloaded_video_manifest": manifest,
                "_preloaded_native_media_ref": (
                    "gs://private-bucket/files/1"
                ),
                "_preloaded_media_lease": wrong_lease,
            }
        )

    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="canonical source bytes"):
        runner._register_and_materialize(
            {
                "video_id": "video_001",
                "source_path": str(source),
                "_preloaded_video_manifest": manifest,
                "_preloaded_native_media_ref": (
                    "gs://private-bucket/files/1"
                ),
                "_preloaded_media_lease": lease,
            }
        )


def test_exclusive_run_lock_rejects_second_owner_and_recovers_stale(tmp_path):
    lock = tmp_path / "status.json.run.lock"
    with exclusive_run_lock(lock, {"run_id": "run_a"}):
        assert lock.exists()
        with pytest.raises(RuntimeError, match="Another VideoHALO run"):
            with exclusive_run_lock(lock, {"run_id": "run_b"}):
                pass
    assert not lock.exists()

    lock.write_text(
        json.dumps({"pid": 99999999, "run_id": "stale"}),
        encoding="utf-8",
    )
    with exclusive_run_lock(lock, {"run_id": "recovered"}):
        value = json.loads(lock.read_text(encoding="utf-8"))
        assert value["run_id"] == "recovered"
    assert not lock.exists()


def test_runtime_metrics_aggregate_windowed_worker_event_logs(tmp_path):
    output = tmp_path / "public_probe_items.jsonl"
    events = tmp_path / "events"
    events.mkdir()
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "node_name": "LEAF_FACT_EXTRACTOR",
            "event_type": "structured_call_started",
            "payload": {"role": "LEAF_FACT_EXTRACTOR"},
        },
        {
            "timestamp": "2026-01-01T00:00:02+00:00",
            "node_name": "LEAF_FACT_EXTRACTOR",
            "event_type": "structured_call_completed",
            "payload": {
                "role": "LEAF_FACT_EXTRACTOR",
                "usage": {
                    "total_input_tokens": 100,
                    "total_output_tokens": 10,
                    "total_thought_tokens": 20,
                    "total_cached_tokens": 30,
                    "total_tokens": 130,
                },
            },
        },
    ]
    (events / "video_worker_0.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    metrics = collect_event_metrics(output)
    assert metrics["completed_call_count"] == 1
    assert metrics["usage"]["total_tokens"] == 130
    assert metrics["latency"]["mean_seconds"] == 2.0
