"""Bounded, schema-validated calls through an injected model client."""
from __future__ import annotations

from typing import Mapping, Optional

from ..contracts.registry import ContractRegistry
from ..memory.prompt_assembler import assemble_role_prompt
from .client import FlexCapacityError


def structured_call(
    client,
    *,
    role: str,
    payload: Mapping[str, object],
    schema_name: Optional[str] = None,
    schema: Optional[dict] = None,
    attempts: int = 3,
) -> dict:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if (schema_name is None) == (schema is None):
        raise ValueError("Provide exactly one of schema_name or schema")
    request = assemble_role_prompt(role, payload)
    registry = ContractRegistry()
    output_schema = registry.load(schema_name) if schema_name else dict(schema)
    request["output_json_schema"] = output_schema
    last_error = None
    for _ in range(attempts):
        try:
            result = dict(client.invoke(role=role, request=request))
            if schema_name:
                registry.validate(schema_name, result)
            else:
                import jsonschema

                jsonschema.Draft202012Validator(output_schema).validate(result)
            return result
        except FlexCapacityError as exc:
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:  # provider failures are retried only at this boundary
            last_error = exc
    raise RuntimeError("Structured model call failed after %d attempts: %s" % (attempts, last_error))
