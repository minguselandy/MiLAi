"""Matched-public-information controls; C1/C2 retain their frozen E1 wording."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import v0218_host as common
from v0218_policy_host import AUDIT, BASE_SYSTEM
from v0218_policy_host import POLICIES as E1_POLICIES

REVIEW = (
    "After obtaining relevant observations and before the first business mutation, save one "
    "brief free-text review using save_note. Summarize task-relevant information and review "
    "the work needed to complete this task. Use this ordinary review to guide execution; "
    "do not treat saving it as completion. This is a concise working summary, not a hidden "
    "reasoning transcript. No extra calls are available for this review: it uses the same "
    "remaining generation opportunities."
)
STATE_REVIEW = (
    "After obtaining relevant observations and before the first business mutation, save one "
    "brief free-text state summary using save_note. Trace relevant source values in order "
    "and identify their source references. Later authorized replacements supersede earlier "
    "values; standing rules apply to current inputs rather than merely repeating past "
    "instances. Recompute derived values when their inputs change. Retire a constraint "
    "only on explicit replacement or expiry, and keep genuine conflicts unresolved. "
    "Conclude the summary with the currently operative values and constraints, then use "
    "them to perform the requested work. This is a concise evidence summary, not a hidden "
    "reasoning transcript. Saving is not task completion. No extra calls are available: "
    "this uses the same remaining generation opportunities."
)
POLICIES = {
    **E1_POLICIES,
    "R1": {
        "carry_note": True,
        "append": AUDIT + "\n" + REVIEW,
        "kind": "ORDINARY_REVIEW_CHECKPOINT_CONTROL_V1",
    },
    "P1": {
        "carry_note": True,
        "append": AUDIT + "\n" + STATE_REVIEW,
        "kind": "STATEMEM_WRAPPER_CONCEPT_ADAPTATION_NOT_OFFICIAL_V1",
    },
}


def system_for(arm: str) -> str:
    addition = POLICIES[arm]["append"]
    return BASE_SYSTEM + ("\n" + addition if addition else "")


def run(config_path: Path):
    config = json.loads(config_path.read_text())
    common.validate_prefetch(config)
    if "public_prefetch" not in config or config["policy"] != config["arm"]:
        raise ValueError("E2_REQUIRES_MATCHED_PUBLIC_INFORMATION_B_POLICY")
    expected = system_for(config["arm"])
    if config["policy_system"] != expected:
        raise ValueError("FROZEN_E2_POLICY_SYSTEM_MISMATCH")
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
