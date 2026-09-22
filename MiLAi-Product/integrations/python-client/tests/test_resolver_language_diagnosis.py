"""Frozen desired-behavior probes; strict XFAIL preserves diagnosed gaps."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

_PRODUCT = Path(__file__).resolve().parents[3]
_FAILURES = {"C06", "C21"}


@pytest.fixture(scope="module")
def client_diagnosis() -> dict[str, Any]:
    corpus = json.loads(
        (_PRODUCT / "docs/revalidation/resolver-language/corpus.json").read_text()
    )
    evaluate = runpy.run_path(str(_PRODUCT / "tools/run_resolver_language_diagnostic.py"))[
        "evaluate"
    ]
    result: dict[str, Any] = evaluate(corpus, "client_typed")
    if {row["case_id"] for row in result["cases"]} != {f"C{i:02}" for i in range(1, 23)}:
        raise ValueError("DIAGNOSTIC_CLIENT_CASE_COVERAGE_CHANGED")
    return result


@pytest.mark.parametrize(
    "case_id",
    [
        pytest.param(
            case_id,
            id=case_id,
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="Unresolved semantic synonym/translation capability; corpus not rewritten",
            )
            if case_id in _FAILURES
            else (),
        )
        for case_id in (f"C{i:02}" for i in range(1, 23))
    ],
)
def test_client_resolver_frozen_language_expectation(
    client_diagnosis: dict[str, Any], case_id: str
) -> None:
    row = next(row for row in client_diagnosis["cases"] if row["case_id"] == case_id)
    assert row["status"] == "PASS", json.dumps(row, ensure_ascii=False, sort_keys=True)
