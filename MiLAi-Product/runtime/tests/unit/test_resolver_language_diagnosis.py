"""Runtime interpretation is separate from legacy client prefetch routing."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

_PRODUCT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def runtime_diagnosis() -> dict[str, Any]:
    corpus = json.loads(
        (_PRODUCT / "docs/revalidation/resolver-language/corpus.json").read_text()
    )
    evaluate = runpy.run_path(str(_PRODUCT / "tools/run_resolver_language_diagnostic.py"))[
        "evaluate"
    ]
    result: dict[str, Any] = evaluate(corpus, "runtime_interpreter")
    if {row["case_id"] for row in result["cases"]} != {f"R{i:02}" for i in range(1, 9)}:
        raise ValueError("DIAGNOSTIC_RUNTIME_CASE_COVERAGE_CHANGED")
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
                reason="3A-3D Chinese automatic no-memory gap; no retrieval was measured",
            )
            if case_id in {"R03", "R04"}
            else (),
        )
        for case_id in (f"R{i:02}" for i in range(1, 9))
    ],
)
def test_runtime_interpreter_frozen_language_expectation(
    runtime_diagnosis: dict[str, Any], case_id: str
) -> None:
    row = next(row for row in runtime_diagnosis["cases"] if row["case_id"] == case_id)
    assert row["status"] == "PASS", json.dumps(row, ensure_ascii=False, sort_keys=True)
