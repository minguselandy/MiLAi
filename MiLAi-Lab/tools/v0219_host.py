"""V0219 baseline-only wrapper: unchanged Note/tool loop, complete pending exposure.

Run each episode in a fresh process. No candidate policies or checker imports.
The old Host source and its four-resource historical profile remain unchanged.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path

import v0218_host as common
from v0218_e2_host import system_for as e2_system
from v0218_policy_host import BASE_SYSTEM

PUBLIC_PREFETCH = ["current", "policy", "records", "history", "pending"]


def system_for(arm: str) -> str:
    if arm in {"A", "N0", "N1"}:
        return BASE_SYSTEM
    if arm == "R1":
        return e2_system("R1")
    raise ValueError("V0219_F2_BASELINES_ONLY")


def validate(config: dict) -> None:
    expected = system_for(config["arm"])
    if config.get("policy_system") != expected:
        raise ValueError("EXACT_FROZEN_BASELINE_SYSTEM_REQUIRED")
    if config["arm"] == "A":
        if config["phase"] != "A" or "public_prefetch" in config or config.get("note_commit"):
            raise ValueError("NATURAL_A_WITHOUT_INHERITED_NOTE_REQUIRED")
    elif config["phase"] != "B" or config.get("public_prefetch") != PUBLIC_PREFETCH:
        raise ValueError("B_REQUIRES_FIVE_FULL_PUBLIC_RESOURCES")
    if config["arm"] == "N0" and config.get("note_commit") is not None:
        raise ValueError("N0_MUST_NOT_INHERIT_A_NOTE")


@contextmanager
def configured(config: dict):
    validate(config)
    previous_system, previous_prefetch = common.SYSTEM, common.PUBLIC_PREFETCH
    try:
        common.SYSTEM = system_for(config["arm"])
        common.PUBLIC_PREFETCH = list(PUBLIC_PREFETCH)
        yield
    finally:
        common.SYSTEM, common.PUBLIC_PREFETCH = previous_system, previous_prefetch


def run(config_path: Path):
    config = json.loads(config_path.read_text())
    with configured(config):
        return common.run(config_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    run(parser.parse_args().config)
