import json
from pathlib import Path
from typing import Any

class ContractValidationError(ValueError):
    pass

class ContractRegistry:
    def __init__(self, schema_root: Path):
        self.schema_root = schema_root.resolve()

    def load(self, name: str) -> dict:
        path = (self.schema_root / Path(name).name).resolve()
        if self.schema_root not in path.parents or not path.is_file():
            raise ContractValidationError(f"Unknown schema: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def validate(self, name: str, value: Any) -> None:
        import jsonschema
        jsonschema.Draft202012Validator(self.load(name)).validate(value)
