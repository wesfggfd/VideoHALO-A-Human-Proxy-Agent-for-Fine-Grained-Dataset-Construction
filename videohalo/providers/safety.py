"""Provider error hygiene, global auth circuit breaking, and traffic pacing."""
from __future__ import annotations

import re
import threading
import time
from typing import Optional


_SECRET_PATTERNS = (
    re.compile(r"AQ\.[A-Za-z0-9_-]+"),
    re.compile(r"AIza[A-Za-z0-9_-]+"),
    re.compile(r"(?i)(x-goog-api-key\s*[:=]\s*)[^\s,;\"']+"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+"),
)


def redact_sensitive(value: object) -> str:
    """Return a log-safe error string without API keys or bearer tokens."""
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def _status_code(exc: BaseException) -> Optional[int]:
    value = getattr(exc, "status_code", None)
    if value is None:
        # google.genai.errors.APIError exposes the HTTP status as ``code``.
        value = getattr(exc, "code", None)
    if value is None:
        value = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def is_auth_or_project_failure(exc: BaseException) -> bool:
    status = _status_code(exc)
    text = str(exc).lower()
    if status == 401:
        return True
    if status != 403:
        return False
    markers = (
        "account_state_invalid",
        "consumer_suspended",
        "permission_denied",
        "unauthenticated",
        "service account",
        "credentials",
        "billing",
        "project",
        "iam",
    )
    return any(marker in text for marker in markers)


class ProviderCircuitOpenError(RuntimeError):
    """Raised once provider authentication or project access is unsafe."""


class ProviderCircuitBreaker:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""

    @property
    def is_open(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or "Google Cloud provider circuit is open"

    def reset_for_tests(self) -> None:
        with self._lock:
            self._reason = ""
            self._event.clear()

    def trip(self, exc: BaseException) -> ProviderCircuitOpenError:
        status = _status_code(exc)
        with self._lock:
            if not self._event.is_set():
                suffix = "" if status is None else " (HTTP %d)" % status
                self._reason = (
                    "Google Cloud authentication, billing, IAM, or project "
                    "access was rejected%s; all provider traffic has been "
                    "stopped and requires operator review" % suffix
                )
                self._event.set()
        return ProviderCircuitOpenError(self.reason)

    def inspect(self, exc: BaseException) -> None:
        if is_auth_or_project_failure(exc):
            raise self.trip(exc) from exc

    def raise_if_open(self) -> None:
        if self._event.is_set():
            raise ProviderCircuitOpenError(self.reason)


class SmoothRequestPacer:
    """Reserve evenly spaced request slots across all worker threads."""

    def __init__(self, requests_per_minute: float) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.interval = 60.0 / float(requests_per_minute)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> float:
        with self._lock:
            now = time.monotonic()
            scheduled = max(now, self._next)
            self._next = scheduled + self.interval
        delay = max(0.0, scheduled - now)
        if delay:
            time.sleep(delay)
        return delay


PROVIDER_CIRCUIT = ProviderCircuitBreaker()
_PACERS: dict[float, SmoothRequestPacer] = {}
_PACERS_LOCK = threading.Lock()


def request_pacer(requests_per_minute: float) -> SmoothRequestPacer:
    key = float(requests_per_minute)
    with _PACERS_LOCK:
        pacer = _PACERS.get(key)
        if pacer is None:
            pacer = SmoothRequestPacer(key)
            _PACERS[key] = pacer
        return pacer
