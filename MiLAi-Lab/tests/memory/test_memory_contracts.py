"""Compare actual canonical memory/application contracts with the pre-move fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from contract_probe import capture_contracts

LAB = Path(__file__).resolve().parents[2]
GOLDEN = json.loads(
    (LAB / "data/diagnostics/code-architecture-v12/memory-contract-golden.json").read_text()
)


@pytest.fixture(scope="module")
def actual_contracts() -> dict[str, Any]:
    return capture_contracts(canonical=True)


@pytest.mark.parametrize("component", ["strict", "mcp", "revision", "application", "scope"])
def test_canonical_contracts_match_frozen_baseline(
    component: str,
    actual_contracts: dict[str, Any],
) -> None:
    assert actual_contracts[component] == GOLDEN["contracts"][component]
