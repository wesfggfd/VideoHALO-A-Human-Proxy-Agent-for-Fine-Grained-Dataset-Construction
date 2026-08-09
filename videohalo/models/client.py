"""Gemini Enterprise structured model boundary for VideoHALO."""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Mapping, Optional, Protocol

from ..providers.gemini import build_enterprise_client
from ..providers.safety import (
    PROVIDER_CIRCUIT,
    ProviderCircuitOpenError,
    redact_sensitive,
    request_pacer,
)


FIXED_TEMPERATURE = 0.0
DEFAULT_THINKING_LEVEL = "low"
HIGH_THINKING_ROLES = frozenset(
    {
        "LEAF_OPPORTUNITY_SCOUT",
        "LEAF_FACT_EXTRACTOR",
        "FACT_REFLECTION",
        "CANDIDATE_REFLECTION",
    }
)
DEFAULT_ROLE_MODELS = {
    "LEAF_OPPORTUNITY_SCOUT": "gemini-3.6-flash",
    "LEAF_FACT_EXTRACTOR": "gemini-3.6-flash",
    "FACT_REFLECTION": "gemini-3.6-flash",
    "LANGUAGE_REALIZER": "gemini-3.6-flash",
    "PAIR_BACKPARSER": "gemini-3.6-flash",
    "CANDIDATE_REFLECTION": "gemini-3.6-flash",
}
_TEMPERATURE_DEPRECATED_MODEL_PREFIXES = ("gemini-3.6-",)


class FlexCapacityError(RuntimeError):
    """Raised after bounded Flex-capacity retries are exhausted."""


class GeminiNativeModelClient(Protocol):
    def invoke(self, *, role: str, request: Mapping[str, object]) -> Mapping[str, object]: ...


class GeminiEnterpriseModelClient:
    """Use Gemini Enterprise v1 GenerateContent with one private GCS video."""

    def __init__(
        self,
        client=None,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = FIXED_TEMPERATURE,
        service_tier: Optional[str] = None,
        flex_max_attempts: Optional[int] = None,
        flex_retry_base_seconds: Optional[float] = None,
        enable_pacing: Optional[bool] = None,
    ):
        from ..settings import get_settings

        settings = get_settings()
        self.explicit_model_override = model is not None
        injected_client = client is not None
        if client is None:
            client = build_enterprise_client(settings)
        self.client = client
        self.model = model or settings.gemini_model
        if temperature is None:
            temperature = FIXED_TEMPERATURE
        if float(temperature) != FIXED_TEMPERATURE:
            raise ValueError("VideoHALO temperature is frozen at 0.0 for reproducibility")
        self.temperature = FIXED_TEMPERATURE
        self.service_tier = service_tier or settings.gemini_service_tier
        if self.service_tier not in {"flex", "standard"}:
            raise ValueError("Unsupported Enterprise service tier: %s" % self.service_tier)
        self.request_timeout_seconds = float(settings.node_timeout_seconds)
        self.flex_max_attempts = int(
            flex_max_attempts
            if flex_max_attempts is not None
            else settings.flex_max_attempts
        )
        self.flex_retry_base_seconds = float(
            flex_retry_base_seconds
            if flex_retry_base_seconds is not None
            else settings.flex_retry_base_seconds
        )
        if self.flex_max_attempts < 1:
            raise ValueError("Flex max attempts must be positive")
        if self.flex_retry_base_seconds < 0:
            raise ValueError("Flex retry base seconds cannot be negative")
        if enable_pacing is None:
            enable_pacing = not injected_client
        self.pacer = (
            request_pacer(settings.model_requests_per_minute)
            if enable_pacing
            else None
        )
        self.last_call_metadata: dict = {}

    @staticmethod
    def _contains_key(value, forbidden) -> bool:
        if isinstance(value, Mapping):
            return bool(set(value).intersection(forbidden)) or any(
                GeminiEnterpriseModelClient._contains_key(child, forbidden)
                for child in value.values()
            )
        if isinstance(value, list):
            return any(
                GeminiEnterpriseModelClient._contains_key(child, forbidden)
                for child in value
            )
        return False

    @staticmethod
    def _is_verifier(role: str) -> bool:
        return (
            role.endswith("_VERIFIER_A")
            or role.endswith("_VERIFIER_B")
            or role in {"FACT_REFLECTION", "CANDIDATE_REFLECTION"}
        )

    @staticmethod
    def _is_flex_capacity_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            status_code = getattr(exc, "code", None)
        if status_code is None:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {408, 429, 500, 502, 503, 504}:
            text = str(exc).lower()
            return status_code in {408, 429, 502, 503, 504} or any(
                marker in text
                for marker in (
                    "high demand",
                    "service unavailable",
                    "resource exhausted",
                    "spikes in demand",
                )
            )
        return False

    @staticmethod
    def _usage_metadata(response) -> dict:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return {}

        def value(name: str):
            if isinstance(usage, Mapping):
                return usage.get(name)
            return getattr(usage, name, None)

        mapping = {
            "total_input_tokens": "prompt_token_count",
            "total_output_tokens": "candidates_token_count",
            "total_thought_tokens": "thoughts_token_count",
            "total_cached_tokens": "cached_content_token_count",
            "total_tool_use_tokens": "tool_use_prompt_token_count",
            "total_tokens": "total_token_count",
        }
        return {
            output_name: item
            for output_name, provider_name in mapping.items()
            if (item := value(provider_name)) is not None
        }

    def _generate_content(self, *, model: str, contents: list, config: dict):
        attempts = self.flex_max_attempts if self.service_tier == "flex" else 1
        for attempt in range(attempts):
            PROVIDER_CIRCUIT.raise_if_open()
            if self.pacer is not None:
                self.pacer.wait()
            try:
                return self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except ProviderCircuitOpenError:
                raise
            except Exception as exc:
                PROVIDER_CIRCUIT.inspect(exc)
                retryable = self.service_tier == "flex" and self._is_flex_capacity_error(exc)
                if not retryable:
                    raise RuntimeError(
                        "Gemini Enterprise inference failed: %s"
                        % redact_sensitive(exc)
                    ) from exc
                if attempt == attempts - 1:
                    raise FlexCapacityError(
                        "Flex capacity unavailable after %d attempts" % attempts
                    ) from exc
                time.sleep(self.flex_retry_base_seconds * (2**attempt))
        raise AssertionError("Unreachable Flex retry state")

    def invoke(self, *, role: str, request: Mapping[str, object]) -> Mapping[str, object]:
        role_contract = dict(request["role_contract"])
        payload = dict(request["task_payload"])
        hidden = set(role_contract.get("hidden", []))
        if self._is_verifier(role):
            hidden.update(
                {
                    "other_verifier_report",
                    "other_role_observations",
                    "other_role_verdicts",
                    "peer_report",
                    "fact_verifier_reports",
                    "candidate_verifier_reports",
                    "verifier_reports",
                }
            )
        if self._contains_key(payload, hidden):
            raise ValueError("Role payload contains fields hidden by the frozen independence contract")

        schema = request.get("output_json_schema")
        media_uri = payload.pop("native_media_ref", None)
        mime_type = str(payload.pop("native_media_mime_type", "video/mp4"))
        resolution = str(payload.pop("media_resolution", "low"))
        reads_media = role_contract.get("video_access") is not False
        contents: list = []
        if reads_media:
            if not isinstance(media_uri, str) or not media_uri.startswith("gs://"):
                raise ValueError("Media-reading roles require one private GCS URI")
            if resolution not in {"low", "medium", "high"}:
                raise ValueError("Unsupported VideoHALO media resolution")
            contents.append(
                {
                    "file_data": {
                        "file_uri": media_uri,
                        "mime_type": mime_type,
                    }
                }
            )
        elif media_uri is not None:
            raise ValueError("Text-only roles must not receive raw media")
        contents.append(json.dumps({"role": role, "task": payload}, ensure_ascii=False))

        configured_model = os.getenv("VIDEOHALO_MODEL_" + role)
        selected_model = (
            configured_model
            or (self.model if self.explicit_model_override else None)
            or DEFAULT_ROLE_MODELS.get(role)
            or self.model
        )
        thinking_level = "high" if role in HIGH_THINKING_ROLES else DEFAULT_THINKING_LEVEL
        config = {
            "system_instruction": str(request["system"])
            + "\n\nROLE CONTRACT:\n"
            + json.dumps(role_contract, ensure_ascii=False),
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            "thinking_config": {"thinking_level": thinking_level.upper()},
        }
        if reads_media:
            config["media_resolution"] = "MEDIA_RESOLUTION_" + resolution.upper()
        temperature_supported = not selected_model.startswith(
            _TEMPERATURE_DEPRECATED_MODEL_PREFIXES
        )
        if temperature_supported:
            config["temperature"] = FIXED_TEMPERATURE

        response = self._generate_content(
            model=selected_model,
            contents=contents,
            config=config,
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini Enterprise response contained no text")
        self.last_call_metadata = {
            "backend": "gemini_enterprise_agent_platform",
            "endpoint": "global",
            "authentication": "adc",
            "model": selected_model,
            "service_tier": self.service_tier,
            "media_attached": bool(reads_media and media_uri),
            "media_ref_fingerprint": (
                hashlib.sha256(media_uri.encode("utf-8")).hexdigest()
                if reads_media and isinstance(media_uri, str)
                else None
            ),
            "media_mime_type": mime_type if reads_media else None,
            "media_resolution": resolution if reads_media else None,
            "requested_temperature": FIXED_TEMPERATURE,
            "effective_temperature": FIXED_TEMPERATURE if temperature_supported else None,
            "temperature_policy": (
                "fixed_zero" if temperature_supported else "model_default_unconfigurable"
            ),
            "temperature_sent": temperature_supported,
            "thinking_level": thinking_level,
            "usage": self._usage_metadata(response),
        }
        value = json.loads(str(text))
        if not isinstance(value, dict):
            raise RuntimeError("Gemini structured output must be a JSON object")
        return value


# Transitional import alias for callers compiled against VideoHALO 3.7.0.
GeminiInteractionsClient = GeminiEnterpriseModelClient
