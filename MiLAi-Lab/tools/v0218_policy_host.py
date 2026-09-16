"""Explicit Lab-only consumption policies around the unchanged common v4 Host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import v0218_host as common

BASE_SYSTEM = common.SYSTEM
AUDIT = (
    "Separate remembered intentions, source facts, and executed business records. "
    "For each task requirement, compare the applicable authoritative observations with the "
    "actual work already recorded. Preserve satisfied requirements; act on supported gaps "
    "or changes, and request specific clarification only for genuinely unresolved facts. "
    "Before finishing, check that intended writes really executed and that required work "
    "is present. A notebook or a source description is not the business work product."
)
CHECKPOINT = (
    "After obtaining relevant observations and before the first business mutation, save one "
    "brief free-text working checkpoint using save_note. Preserve still-useful prior facts, "
    "and distinguish the old premise, its current scope or authority, any observed change, "
    "the actual existing work, and the next supported action or unresolved question. "
    "This is a concise evidence/action handoff, not a hidden reasoning transcript. "
    "Use it to guide execution; do not treat saving it as completion. No extra calls are "
    "available for this checkpoint: it uses the same remaining generation opportunities."
)
POLICIES = {
    "N1": {"carry_note": True, "append": "", "kind": "STRONG_SIMPLE_BASELINE"},
    "C1": {"carry_note": True, "append": AUDIT, "kind": "EVIDENCE_ACTION_AUDIT_PROMPT_V1"},
    "C2": {
        "carry_note": True,
        "append": AUDIT + "\n" + CHECKPOINT,
        "kind": "EVIDENCE_ACTION_AUDIT_WITH_FREE_CHECKPOINT_V1",
    },
}


def system_for(arm: str) -> str:
    policy = POLICIES[arm]
    return BASE_SYSTEM + ("\n" + policy["append"] if policy["append"] else "")


def run(config_path: Path):
    config = json.loads(config_path.read_text())
    if config["phase"] != "B" or config["policy"] != config["arm"]:
        raise ValueError("CONSUMPTION_POLICY_ONLY_MATCHING_B_ARM")
    expected = system_for(config["policy"])
    if config["policy_system"] != expected:
        raise ValueError("FROZEN_POLICY_SYSTEM_MISMATCH")
    # This explicit wrapper changes only the system policy in a fresh process.
    # Common v4 action parsing, public Note transport, tools and capacity are untouched.
    previous = common.SYSTEM
    try:
        common.SYSTEM = expected
        return common.run(config_path)
    finally:
        common.SYSTEM = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    run(parser.parse_args().config)
