"""Append-safe runtime event logger.

Events are operational telemetry only and are never policy memory or a human
review artifact.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


class RuntimeEventLogger:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(
        self, node_name: str, event_type: str, payload: Mapping[str, object]
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_name": node_name,
            "event_type": event_type,
            "payload": dict(payload),
        }
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            )
