"""Hash-verifying loader for the frozen VideoHALO 3.8 policy bundle."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from ..settings import CORE_MEMORY_MANIFEST, POLICY_BUNDLE_ROOT


class CoreMemoryError(RuntimeError):
    """Raised when frozen policy memory is missing, mutable, or hash-invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CoreMemory:
    root: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str
    asset_paths: Mapping[str, Path]
    asset_hashes: Mapping[str, str]

    def text(self, asset_id: str) -> str:
        try:
            path = self.asset_paths[asset_id]
        except KeyError as exc:
            raise CoreMemoryError("Unknown policy asset: %s" % asset_id) from exc
        return path.read_text(encoding="utf-8")

    def json(self, asset_id: str) -> Any:
        return json.loads(self.text(asset_id))

    def yaml(self, asset_id: str) -> Any:
        try:
            import yaml
        except ImportError as exc:
            raise CoreMemoryError("PyYAML is required to load YAML policy assets") from exc
        return yaml.safe_load(self.text(asset_id))


_ASSET_ALIASES = {
    "01_VHal_Fixed8_Atomic_Fact_Taxonomy.md": "taxonomy_doc",
    "02_VideoHALO_Core_System_Prompt.md": "system_prompt",
    "config/taxonomy.json": "taxonomy_json",
    "config/resolver_rules.json": "resolver_rules",
    "config/mutation_operators.json": "mutation_operators_json",
    "config/leaf_search_plan.json": "leaf_search_plan",
    "config/runtime_profiles.yaml": "runtime_profiles",
    "config/surface_templates.yaml": "surface_templates",
    "config/media_ingestion_policy.json": "media_ingestion_policy_json",
    "schemas/videohalo_probe_pair_sample_fixed8.schema.json": "direct_pair_schema",
}


def load_core_memory(
    bundle_root: Optional[Path] = None, manifest_path: Optional[Path] = None
) -> CoreMemory:
    root = (bundle_root or POLICY_BUNDLE_ROOT).resolve()
    manifest_file = (manifest_path or CORE_MEMORY_MANIFEST).resolve()
    if root not in manifest_file.parents:
        raise CoreMemoryError("Core-memory manifest must be inside the policy bundle")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("frozen") is not True:
        raise CoreMemoryError("Core-memory manifest is not frozen")

    paths = {}
    hashes = {}
    for asset in manifest.get("assets", []):
        package_path = str(asset.get("package_path", "")).replace("\\", "/")
        asset_id = asset.get("asset_id") or _ASSET_ALIASES.get(package_path)
        if not asset_id or asset.get("read_only") is not True:
            raise CoreMemoryError(
                "Every policy asset must have a known package path and be read-only"
            )
        path = (root / package_path).resolve()
        if root != path and root not in path.parents:
            raise CoreMemoryError("Policy asset escapes bundle root: %s" % path)
        if not path.is_file():
            raise CoreMemoryError("Missing policy asset: %s" % path)
        actual = sha256_file(path)
        if actual != asset["sha256"]:
            raise CoreMemoryError("Hash mismatch for %s" % asset_id)
        paths[asset_id] = path
        hashes[asset_id] = actual

    return CoreMemory(
        root=root,
        manifest=MappingProxyType(manifest),
        manifest_sha256=sha256_file(manifest_file),
        asset_paths=MappingProxyType(paths),
        asset_hashes=MappingProxyType(hashes),
    )
