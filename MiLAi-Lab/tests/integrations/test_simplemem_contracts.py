"""Actual cached native SDK replay against the frozen pre-move contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from external_contract_probe import capture

LAB = Path(__file__).resolve().parents[2]


@pytest.mark.local_artifacts
def test_native_simplemem_contract_matches_frozen_baseline() -> None:
    fixture = json.loads(
        (LAB / "data/diagnostics/code-architecture-v12/simplemem-contract-deterministic-golden.json")
        .read_text()
    )
    assert capture("simplemem", canonical=True) == fixture["contracts"]
