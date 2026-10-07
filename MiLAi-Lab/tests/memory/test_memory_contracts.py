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


@pytest.mark.parametrize("component", ["strict", "mcp", "revision", "scope"])
def test_canonical_contracts_match_frozen_baseline(
    component: str,
    actual_contracts: dict[str, Any],
) -> None:
    assert actual_contracts[component] == GOLDEN["contracts"][component]


def test_application_effects_match_baseline_with_ordinary_journal_ids(
    actual_contracts: dict[str, Any],
) -> None:
    actual = actual_contracts["application"]
    baseline = GOLDEN["contracts"]["application"]
    for component in (
        "schemas",
        "receipts",
        "world",
        "schema",
        "world_reopened",
        "unknown_call",
        "real_query_recovery",
        "unknown_world",
    ):
        assert actual[component] == baseline[component]
    complete = json.loads(actual["journal_json_bytes"])
    calls = [row for key, row in complete.items() if key != "_application"]
    assert len(calls) == 4
    assert [row["effect"] for row in calls] == ["partial", "observed", "none", "confirmed"]
    unknown = json.loads(actual["unknown_journal_json_bytes"])
    original = next(row for row in unknown.values() if row.get("call_id") == "unknown-reserve")
    assert original["status"] == "pending" and original["effect"] == "unknown"
    assert "result" not in original
    recovery = next(iter(unknown["_application"]["recoveries"].values()))
    assert recovery["effect"] == "partial"
    assert recovery["original_call_status"] == "UNKNOWN"
    assert recovery["effect_source"] == "query_observation_not_original_execution_receipt"
    assert original["journal_key"] in unknown
    assert recovery["query_journal_key"] in unknown
    updates = actual["recovery_updates"]
    assert len(updates) == 1
    message = updates[0]["messages"][0]
    delivered = json.loads(message["content"])
    assert delivered["original_receipt"] is None
    assert delivered["status"] == "ORIGINAL_CALL_OUTCOME_UNKNOWN"
    assert delivered["observed_effect"] == "partial"
    assert delivered["original_journal_key"] == original["journal_key"]
    assert message["additional_kwargs"]["application_recovery"] == recovery
