import hashlib

import pytest

from videohalo.media.gcs import (
    acquire_or_reuse_gcs_object,
    gcs_object_name,
)
from videohalo.media.lease_registry import ProviderLeaseRegistry
from videohalo.providers.safety import (
    PROVIDER_CIRCUIT,
    SmoothRequestPacer,
    redact_sensitive,
)
from videohalo.settings import Settings


@pytest.fixture(autouse=True)
def reset_provider_circuit():
    PROVIDER_CIRCUIT.reset_for_tests()
    yield
    PROVIDER_CIRCUIT.reset_for_tests()


class FakeGCSAdapter:
    def __init__(self):
        self.calls = []

    def upload_or_reuse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "object_name": kwargs["object_name"],
            "uri": "gs://private-bucket/" + kwargs["object_name"],
            "bucket": "private-bucket",
            "generation": "7",
            "crc32c": "abcd",
            "size": 9,
            "reused": False,
            "upload_latency_ms": 12,
        }


def test_enterprise_runtime_rejects_api_key_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.exposed")
    settings = Settings(
        google_cloud_project="approved-project",
        google_cloud_storage_bucket="private-bucket",
    )
    with pytest.raises(RuntimeError, match="must be unset"):
        settings.validate_enterprise_runtime()


def test_secret_redaction_covers_auth_key_and_bearer_token():
    value = redact_sensitive(
        "x-goog-api-key=<redacted> Authorization: Bearer <redacted>"
    )
    assert "AQ.secret" not in value
    assert "token-value" not in value
    assert value.count("[REDACTED]") >= 2


def test_gcs_object_name_is_deterministic_and_content_addressed(tmp_path):
    source = tmp_path / "clip.mp4"
    digest = "a" * 64
    assert gcs_object_name(
        prefix="videohalo/original-video",
        video_id="videoqa 001",
        source_sha256=digest,
        source_path=source,
    ) == "videohalo/original-video/aa/%s/videoqa_001.mp4" % digest


def test_private_gcs_lease_is_persistent_and_reused(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"canonical")
    digest = hashlib.sha256(b"canonical").hexdigest()
    registry = ProviderLeaseRegistry(tmp_path / "leases.sqlite")
    adapter = FakeGCSAdapter()
    manifest = {
        "video_id": "videoqa_0001",
        "source_sha256": digest,
    }
    first = acquire_or_reuse_gcs_object(
        registry=registry,
        adapter=adapter,
        project="approved-project",
        bucket="private-bucket",
        prefix="videohalo/original-video",
        source_path=source,
        manifest=manifest,
        mime_type="video/mp4",
    )
    second = acquire_or_reuse_gcs_object(
        registry=registry,
        adapter=adapter,
        project="approved-project",
        bucket="private-bucket",
        prefix="videohalo/original-video",
        source_path=source,
        manifest=manifest,
        mime_type="video/mp4",
    )
    assert first["state"] == "active"
    assert first["expires_at"] is None
    assert first["provider_media_uri"].startswith("gs://private-bucket/")
    assert second["reuse_count"] == 1
    assert len(adapter.calls) == 1


def test_smooth_pacer_reserves_even_slots(monkeypatch):
    observed = iter([10.0, 10.0, 10.0, 10.0])
    sleeps = []
    monkeypatch.setattr("videohalo.providers.safety.time.monotonic", lambda: next(observed))
    monkeypatch.setattr("videohalo.providers.safety.time.sleep", sleeps.append)
    pacer = SmoothRequestPacer(10)
    assert pacer.wait() == 0
    assert pacer.wait() == 6
    assert sleeps == [6]
