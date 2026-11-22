"""Versioned, masked decision-time features for finite memory menus."""

from __future__ import annotations

from collections.abc import Sequence
from math import log1p
from typing import Any

from milai_lab.datasets.memory_control_protocols import NUMERIC_SCHEMA

MATERIAL_UNIT = 2048
STATE_FIELDS = (
    "budget", "remaining_budget", "delivered_tokens", "successful_reads",
    "remaining_steps", "action_count", "opened_objects", "exact_host_preflight",
)
OPERATION_FIELDS = ("SEARCH", "READ", "USE_VIEW", "REFRESH_VIEW", "HANDOFF")
ACTION_FIELDS = (
    *OPERATION_FIELDS, "r2", "r3", "expandable", "focus_tokens", "context_tokens",
    "focus_ranges", "context_ranges", "new_fraction", "overlap_fraction",
    "expansion_new_fraction", "expansion_overlap_fraction",
    "incremental_tokens", "cost_exact", "cost_estimated",
)
STATE_WIDTH = 2 * len(STATE_FIELDS)
ACTION_WIDTH = 2 * len(ACTION_FIELDS)


def masked(values: Sequence[float | None]) -> list[float]:
    """Concatenate values with per-field availability. Missing has all-zero encoding."""
    return [0.0 if x is None else float(x) for x in values] + [
        float(x is not None) for x in values
    ]


def material_units(tokens: int | None) -> float | None:
    return None if tokens is None else tokens / MATERIAL_UNIT


def log_count(value: int | None) -> float | None:
    return None if value is None else log1p(value)


def numeric_rows(row: dict[str, Any]) -> tuple[list[float], list[list[float]]]:
    features = row.get("control_numeric")
    if (not features or features.get("schema") != NUMERIC_SCHEMA
            or len(features["state"]) != STATE_WIDTH
            or len(features["actions"]) != len(row["actions"])
            or any(len(a) != ACTION_WIDTH for a in features["actions"])):
        raise ValueError("The checkpoint requires complete, action-aligned numeric observations")
    return features["state"], features["actions"]
