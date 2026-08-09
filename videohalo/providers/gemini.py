"""Gemini Enterprise Agent Platform client factory using ADC and IAM."""
from __future__ import annotations

from .safety import PROVIDER_CIRCUIT
from ..settings import get_settings


class GeminiEnterpriseConfigurationError(RuntimeError):
    pass


def build_enterprise_client(settings=None):
    settings = settings or get_settings()
    settings.validate_enterprise_runtime()
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise GeminiEnterpriseConfigurationError(
            "google-genai is required for Gemini Enterprise calls"
        ) from exc

    headers = {}
    if settings.gemini_service_tier == "flex":
        # Force PayGo routing so an unrelated Provisioned Throughput reservation
        # is never consumed before Flex.  Both headers are required by Google's
        # current "Flex only" contract.
        headers["X-Vertex-AI-LLM-Request-Type"] = "shared"
        headers["X-Vertex-AI-LLM-Shared-Request-Type"] = "flex"
    PROVIDER_CIRCUIT.raise_if_open()
    return genai.Client(
        enterprise=True,
        project=settings.require_google_cloud_project(),
        location=settings.google_cloud_location,
        http_options=types.HttpOptions(
            api_version="v1",
            headers=headers,
            timeout=int(settings.node_timeout_seconds * 1000),
            # Keep retries observable and bounded in GeminiEnterpriseModelClient.
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
