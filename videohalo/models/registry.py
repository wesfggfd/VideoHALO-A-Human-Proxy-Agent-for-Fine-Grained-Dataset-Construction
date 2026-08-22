"""VideoHALO canonical six-agent registry and isolation checks."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from ..agents import (
    AGENT_ROLES,
    GENERATION_AGENT,
    MONITOR_AGENT,
    REFLECTION_AGENT,
    VERIFICATION_AGENT,
)
from ..settings import POLICY_BUNDLE_ROOT


class RoleIsolationError(ValueError):
    pass


class ModelRegistry:
    def __init__(self, path: Optional[Path] = None):
        self.path = (
            path or POLICY_BUNDLE_ROOT / "config" / "model_roles.yaml"
        ).resolve()
        payload = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.version = payload["model_roles_version"]
        self.roles = {
            item["role"]: dict(item) for item in payload.get("roles", [])
        }
        self.validate()

    def validate(self) -> None:
        if set(self.roles) != set(AGENT_ROLES):
            raise RoleIsolationError(
                "Model registry must expose exactly the six canonical agents"
            )
        for role in (REFLECTION_AGENT, MONITOR_AGENT):
            contract = self.roles.get(role)
            if contract is None:
                raise RoleIsolationError("Missing build reflection role")
            if contract.get("thinking_level") != "high":
                raise RoleIsolationError(
                    "%s must use high thinking" % role
                )
        for role in (GENERATION_AGENT, VERIFICATION_AGENT):
            if self.roles.get(role, {}).get("video_access") is not False:
                raise RoleIsolationError("%s must not access video" % role)
        for role, contract in self.roles.items():
            if contract.get("contributes_to") != [
                "system_cognitive_memory",
                "category_memory",
            ]:
                raise RoleIsolationError(
                    "%s must contribute to both memory layers" % role
                )

    def role(self, role: str) -> dict:
        try:
            return dict(self.roles[role])
        except KeyError as exc:
            raise KeyError("Unknown model role: %s" % role) from exc
