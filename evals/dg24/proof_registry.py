"""Scorer-only DG-24 proof registry access; Runtime must not import this module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def open_proof_registry(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("scorer_only") is not True:
        raise ValueError("invalid scorer-only proof registry")
    return value


__all__ = ["open_proof_registry"]
