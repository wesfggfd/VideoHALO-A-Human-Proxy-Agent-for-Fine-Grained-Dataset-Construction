from types import SimpleNamespace

import pytest

from videohalo.models.client import (
    DEFAULT_THINKING_LEVEL,
    FIXED_TEMPERATURE,
    HIGH_THINKING_ROLES,
    GeminiEnterpriseModelClient,
)
from videohalo.providers.safety import (
    PROVIDER_CIRCUIT,
    ProviderCircuitOpenError,
    redact_sensitive,
)


@pytest.fixture(autouse=True)
def reset_provider_circuit():
    PROVIDER_CIRCUIT.reset_for_tests()
    yield
    PROVIDER_CIRCUIT.reset_for_tests()


class FakeModels:
    def __init__(self, failures=0, failure_factory=None):
        self.failures = failures
        self.failure_factory = failure_factory
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            if self.failure_factory:
                raise self.failure_factory()
            error = RuntimeError("503 service unavailable")
            error.status_code = 503
            raise error
        usage = SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=10,
            thoughts_token_count=20,
            cached_content_token_count=0,
            tool_use_prompt_token_count=0,
            total_token_count=130,
        )
        return SimpleNamespace(text="{}", usage_metadata=usage)


class FakeClient:
    def __init__(self, failures=0, failure_factory=None):
        self.models = FakeModels(
            failures=failures,
            failure_factory=failure_factory,
        )


def request(*, video_access=False):
    payload = {}
    if video_access:
        payload = {
            "native_media_ref": "gs://private-bucket/video.mp4",
            "native_media_mime_type": "video/mp4",
            "media_resolution": "low",
        }
    return {
        "system": "frozen system",
        "role_contract": {
            "video_access": video_access,
            "hidden": [],
        },
        "task_payload": payload,
        "output_json_schema": {
            "type": "object",
            "additionalProperties": False,
        },
    }


def test_primary_roles_use_enterprise_generate_content_and_adc(monkeypatch):
    monkeypatch.delenv("VIDEOHALO_MODEL_LANGUAGE_REALIZER", raising=False)
    fake = FakeClient()
    client = GeminiEnterpriseModelClient(
        client=fake,
        service_tier="flex",
        flex_retry_base_seconds=0,
    )

    client.invoke(role="LANGUAGE_REALIZER", request=request(video_access=False))

    call = fake.models.calls[0]
    assert call["model"] == "gemini-3.6-flash"
    assert call["config"]["thinking_config"]["thinking_level"] == "LOW"
    assert "temperature" not in call["config"]
    assert client.last_call_metadata["backend"] == "gemini_enterprise_agent_platform"
    assert client.last_call_metadata["authentication"] == "adc"
    assert client.last_call_metadata["service_tier"] == "flex"
    assert client.last_call_metadata["usage"]["total_tokens"] == 130


def test_nonzero_temperature_is_rejected():
    with pytest.raises(ValueError, match="frozen at 0.0"):
        GeminiEnterpriseModelClient(client=FakeClient(), temperature=0.1)
    assert FIXED_TEMPERATURE == 0.0
    assert DEFAULT_THINKING_LEVEL == "low"
    assert HIGH_THINKING_ROLES == {
        "LEAF_OPPORTUNITY_SCOUT",
        "LEAF_FACT_EXTRACTOR",
        "FACT_REFLECTION",
        "CANDIDATE_REFLECTION",
    }


@pytest.mark.parametrize(
    "role",
    [
        "LEAF_OPPORTUNITY_SCOUT",
        "LEAF_FACT_EXTRACTOR",
        "FACT_REFLECTION",
        "CANDIDATE_REFLECTION",
    ],
)
def test_extraction_and_build_reflection_use_high_thinking(role):
    fake = FakeClient()
    client = GeminiEnterpriseModelClient(client=fake, service_tier="flex")

    client.invoke(role=role, request=request(video_access=True))

    call = fake.models.calls[0]
    assert call["config"]["thinking_config"]["thinking_level"] == "HIGH"
    assert call["config"]["media_resolution"] == "MEDIA_RESOLUTION_LOW"
    assert call["contents"][0]["file_data"]["file_uri"].startswith("gs://")
    assert client.last_call_metadata["thinking_level"] == "high"


@pytest.mark.parametrize("role", ["LANGUAGE_REALIZER", "PAIR_BACKPARSER"])
def test_non_build_reflection_roles_use_low_thinking(role):
    fake = FakeClient()
    client = GeminiEnterpriseModelClient(client=fake, service_tier="flex")

    client.invoke(role=role, request=request(video_access=False))

    call = fake.models.calls[0]
    assert call["config"]["thinking_config"]["thinking_level"] == "LOW"
    assert client.last_call_metadata["thinking_level"] == "low"


def test_flex_capacity_retries_are_bounded():
    fake = FakeClient(failures=2)
    client = GeminiEnterpriseModelClient(
        client=fake,
        service_tier="flex",
        flex_max_attempts=3,
        flex_retry_base_seconds=0,
    )

    client.invoke(role="LANGUAGE_REALIZER", request=request(video_access=False))

    assert len(fake.models.calls) == 3


def test_flex_retries_gemini_500_high_demand_errors():
    error = RuntimeError(
        "Error code: 500 - gemini-3.5-flash is currently experiencing "
        "high demand; spikes in demand are usually temporary"
    )
    error.status_code = 500
    assert GeminiEnterpriseModelClient._is_flex_capacity_error(error) is True


def test_403_project_failure_opens_global_circuit_and_redacts_key():
    def failure():
        error = RuntimeError(
            "403 CONSUMER_SUSPENDED x-goog-api-key=<redacted>"
        )
        error.status_code = 403
        return error

    client = GeminiEnterpriseModelClient(
        client=FakeClient(failures=1, failure_factory=failure),
        service_tier="flex",
        flex_retry_base_seconds=0,
    )
    with pytest.raises(ProviderCircuitOpenError, match="all provider traffic"):
        client.invoke(role="LANGUAGE_REALIZER", request=request())
    assert PROVIDER_CIRCUIT.is_open
    assert "secretvalue" not in PROVIDER_CIRCUIT.reason
    assert "AQ.secretvalue" not in redact_sensitive(failure())
