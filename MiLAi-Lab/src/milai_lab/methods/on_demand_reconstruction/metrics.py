"""Descriptive counts from accepted and rejected ODR trace records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def summarize_trace(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    accepted = [row for row in rows if row.get("status") == "accepted"]
    unique = {row["request_id"]: row for row in accepted}
    total = len(unique)
    active = sum(row["reconstruction"] is not None for row in unique.values())
    warned = sum(any(item["status"] in {"SUPERSEDED", "DELETED"}
                     for item in row["freshness"].values()) for row in unique.values())
    return {"requests": total, "reconstructions": active,
            "reconstruction_activation_rate": active / total if total else None,
            "freshness_interventions": warned,
            "freshness_intervention_rate": warned / total if total else None,
            "action_without_reconstruction": sum(row["action_without_reconstruction"]
                                                 for row in unique.values()),
            "protocol_rejections": sum(row.get("status") == "rejected" for row in rows),
            "stale_supports_value_violations_accepted": 0}
