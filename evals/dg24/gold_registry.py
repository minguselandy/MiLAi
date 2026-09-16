"""Scorer-only DG-24 gold registry access; Runtime must never import this module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def open_gold_registry(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("scorer_only") is not True:
        raise ValueError("invalid scorer-only gold registry")
    return value


__all__ = ["open_gold_registry"]
