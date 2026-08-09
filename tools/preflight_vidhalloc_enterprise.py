"""Fail-closed ADC, IAM, private-GCS, and optional model preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid

from videohalo.providers.gemini import build_enterprise_client
from videohalo.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-model-check", action="store_true")
    parser.add_argument("--runtime-access-check", action="store_true")
    parser.add_argument("--security-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    settings.validate_enterprise_runtime()
    project = settings.require_google_cloud_project()
    bucket_name = settings.require_gcs_bucket()

    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from google.auth.transport.requests import Request
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError(
            "Install VideoHALO Enterprise dependencies before preflight"
        ) from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        quota_project_id=project,
    )
    if adc_project and adc_project != project:
        raise RuntimeError(
            "ADC project differs from GOOGLE_CLOUD_PROJECT"
        )
    quota_project = getattr(credentials, "quota_project_id", None)
    if quota_project != project:
        raise RuntimeError(
            "ADC quota project must exactly match GOOGLE_CLOUD_PROJECT"
        )
    credentials.refresh(Request())

    storage_client = storage.Client(project=project, credentials=credentials)
    security_report_sha256 = None
    if args.security_report:
        security_path = args.security_report.resolve()
        security_bytes = security_path.read_bytes()
        security_report_sha256 = hashlib.sha256(security_bytes).hexdigest()
        security = json.loads(security_bytes.decode("utf-8-sig"))
        required = {
            "ok": True,
            "project": project,
            "bucket": bucket_name,
            "bucket_uniform_access": True,
            "bucket_public_access_prevention": "enforced",
            "public_member_count": 0,
        }
        mismatches = {
            key: {"expected": expected, "observed": security.get(key)}
            for key, expected in required.items()
            if security.get(key) != expected
        }
        if mismatches:
            raise RuntimeError("Saved GCS security preflight is invalid")
        project_number = str(security["project_number"])
        ubla = True
        prevention = "enforced"
        public_members = set()
    else:
        resource_session = AuthorizedSession(credentials)
        project_response = resource_session.get(
            "https://cloudresourcemanager.googleapis.com/v3/projects/%s" % project,
            timeout=30,
        )
        if project_response.status_code != 200:
            raise RuntimeError("Could not verify the approved Google Cloud project")
        project_resource = project_response.json()
        project_number = str(project_resource.get("name", "")).rsplit("/", 1)[-1]
        if not project_number.isdigit():
            raise RuntimeError("Google Cloud project number could not be verified")

        bucket = storage_client.get_bucket(bucket_name)
        if str(bucket.project_number) != project_number:
            raise RuntimeError(
                "GCS bucket must belong to the same project as Gemini Enterprise"
            )
        iam = bucket.get_iam_policy(requested_policy_version=3)
        public_members = {
            member
            for binding in iam.bindings
            for member in binding.get("members", [])
            if member in {"allUsers", "allAuthenticatedUsers"}
        }
        if public_members:
            raise RuntimeError("GCS bucket grants public access")
        ubla = bool(
            bucket.iam_configuration.uniform_bucket_level_access_enabled
        )
        prevention = str(
            bucket.iam_configuration.public_access_prevention or ""
        ).lower()
        if not ubla or prevention != "enforced":
            raise RuntimeError(
                "GCS bucket must enforce uniform access and public prevention"
            )

    runtime_storage_check = "not_requested"
    if args.runtime_access_check:
        bucket = storage_client.bucket(bucket_name)
        object_name = (
            settings.google_cloud_storage_prefix
            + "/_preflight/"
            + uuid.uuid4().hex
            + ".txt"
        )
        blob = bucket.blob(object_name)
        uploaded = False
        try:
            blob.upload_from_string(
                b"videohalo-enterprise-adc-preflight\n",
                content_type="text/plain",
                if_generation_match=0,
                checksum="auto",
                timeout=60,
            )
            uploaded = True
            blob.reload(timeout=60)
            if blob.download_as_bytes(timeout=60) != (
                b"videohalo-enterprise-adc-preflight\n"
            ):
                raise RuntimeError("Private GCS runtime readback differed")
            runtime_storage_check = "passed"
        finally:
            if uploaded:
                blob.delete(
                    if_generation_match=int(blob.generation), timeout=60
                )

    model_check = "not_requested"
    traffic_type = None
    if args.live_model_check:
        client = build_enterprise_client(settings)
        try:
            response = None
            for attempt in range(settings.flex_max_attempts):
                try:
                    response = client.models.generate_content(
                        model=settings.gemini_model,
                        contents='Return exactly: {"ok":true}',
                        config={
                            "response_mime_type": "application/json",
                            "response_json_schema": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"}},
                                "required": ["ok"],
                                "additionalProperties": False,
                            },
                            "thinking_config": {"thinking_level": "LOW"},
                        },
                    )
                    break
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    if code is None:
                        code = getattr(exc, "status_code", None)
                    if (
                        code not in {408, 429, 500, 502, 503, 504}
                        or attempt == settings.flex_max_attempts - 1
                    ):
                        raise
                    time.sleep(settings.flex_retry_base_seconds * (2**attempt))
            if response is None:
                raise RuntimeError("Gemini Enterprise preflight returned no response")
        finally:
            client.close()
        payload = json.loads(response.text)
        if payload != {"ok": True}:
            raise RuntimeError("Gemini Enterprise preflight returned unexpected data")
        usage = getattr(response, "usage_metadata", None)
        traffic_type = getattr(usage, "traffic_type", None)
        if traffic_type is None and isinstance(usage, dict):
            traffic_type = usage.get("traffic_type")
        traffic_type = str(traffic_type or "")
        if not traffic_type.endswith("ON_DEMAND_FLEX"):
            raise RuntimeError("Gemini request was not routed through Flex-only PayGo")
        model_check = "passed"

    result = {
        "ok": True,
        "authentication": "adc",
        "adc_quota_project": quota_project,
        "project": project,
        "project_number": project_number,
        "location": settings.google_cloud_location,
        "bucket": bucket_name,
        "bucket_uniform_access": ubla,
        "bucket_public_access_prevention": prevention,
        "public_member_count": len(public_members),
        "security_report_sha256": security_report_sha256,
        "runtime_storage_check": runtime_storage_check,
        "model": settings.gemini_model,
        "service_tier": settings.gemini_service_tier,
        "model_requests_per_minute": settings.model_requests_per_minute,
        "live_model_check": model_check,
        "traffic_type": traffic_type or None,
    }
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
