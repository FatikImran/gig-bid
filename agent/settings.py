from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def agent_config() -> dict[str, Any]:
    path = ROOT / "agent" / "config.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Unable to load agent configuration: {path.name}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("thresholds"), dict):
        raise TypeError("agent/config.yaml must contain a thresholds mapping")
    return value


@lru_cache(maxsize=1)
def marketplace_policy() -> dict[str, Any]:
    path = ROOT / "data" / "policy_pack" / "policy.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Unable to load marketplace policy: {path.name}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("risk_signals"), dict):
        raise TypeError("policy.yaml must define risk_signals")
    for name, config in value["risk_signals"].items():
        if not isinstance(name, str) or not isinstance(config, dict):
            raise TypeError("risk signal entries must be named mappings")
        if not isinstance(config.get("terms"), list) or not config["terms"]:
            raise ValueError(f"risk signal {name!r} must have non-empty terms")
    return value
