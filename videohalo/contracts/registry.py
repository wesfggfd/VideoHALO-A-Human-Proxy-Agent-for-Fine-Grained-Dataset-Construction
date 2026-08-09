"""Versioned JSON-Schema loader."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..settings import POLICY_BUNDLE_ROOT


class ContractValidationError(ValueError):
    pass


class ContractRegistry:
    def __init__(self, schema_root: Optional[Path] = None):
        self.schema_root = (schema_root or POLICY_BUNDLE_ROOT / "schemas").resolve()

    def load(self, name: str) -> dict:
        safe = Path(name).name
        path = (self.schema_root / safe).resolve()
        if self.schema_root not in path.parents:
            raise ContractValidationError("Schema path escapes registry")
        if not path.is_file():
            raise ContractValidationError("Unknown schema: %s" % name)
        return json.loads(path.read_text(encoding="utf-8"))

    def validate(self, name: str, value: Any) -> None:
        try:
            import jsonschema
        except ImportError as exc:
            raise ContractValidationError(
                "jsonschema is required for contract validation; install project dependencies"
            ) from exc
        try:
            jsonschema.Draft202012Validator(
                self.load(name), format_checker=jsonschema.FormatChecker()
            ).validate(value)
        except jsonschema.ValidationError as exc:
            raise ContractValidationError("%s: %s" % (name, exc.message)) from exc
