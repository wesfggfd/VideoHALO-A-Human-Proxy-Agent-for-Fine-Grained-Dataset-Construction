"""Atomic local content-addressed artifact storage."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    uri: str
    sha256: str
    media_type: str
    byte_size: int


class LocalArtifactStore:
    def __init__(self, root: Path, dataset_id: str):
        self.root = root.resolve()
        self.dataset_id = dataset_id
        self.root.mkdir(parents=True, exist_ok=True)

    def put_json(self, artifact_type: str, value: Any) -> ArtifactRef:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        directory = self.root / self.dataset_id / artifact_type
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / (digest + ".json")
        # All worker-local runners share one dataset artifact namespace.  On
        # Windows, two simultaneous os.replace calls targeting the same digest
        # can raise WinError 5 even though both payloads are identical.  Keep
        # the content-addressed write atomic while serializing only this very
        # short local filesystem critical section.
        with _WRITE_LOCK:
            if not final.exists():
                handle, temporary = tempfile.mkstemp(
                    prefix=digest + ".",
                    suffix=".tmp",
                    dir=str(directory),
                )
                try:
                    with os.fdopen(handle, "wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    for attempt in range(3):
                        try:
                            os.replace(temporary, final)
                            break
                        except PermissionError:
                            if final.exists() and final.read_bytes() == payload:
                                break
                            if attempt == 2:
                                raise
                            time.sleep(0.05 * (attempt + 1))
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        return ArtifactRef(
            artifact_id=digest, artifact_type=artifact_type,
            uri="artifact://%s/%s/%s" % (self.dataset_id, artifact_type, digest),
            sha256=digest, media_type="application/json", byte_size=len(payload),
        )

    def read_json(self, reference: ArtifactRef) -> Any:
        path = (self.root / self.dataset_id / reference.artifact_type / (reference.sha256 + ".json")).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("Artifact path escapes store root")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != reference.sha256:
            raise ValueError("Artifact hash mismatch")
        return json.loads(payload.decode("utf-8"))

    @staticmethod
    def as_record(reference: ArtifactRef) -> dict:
        return asdict(reference)
