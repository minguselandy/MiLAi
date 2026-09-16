from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from scripts import dg10_independent_gates as independent_gates
from scripts import dg10_remediation as remediation

ACTIVE_FULL_TEST_APPROVAL = remediation.ROOT / (
    "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json"
)
ACTIVE_FULL_TEST_CONSUMPTION = remediation.ROOT / (
    "docs/reports/DG-10-full-test-access-consumption-candidate.4-2026-08-22.json"
)
APPROVED_INPUT_KEYS = {
    "results",
    "case_manifest",
    "attempt_ledger",
    "topology",
    "hard_safety",
}


class FullTestExecutionError(remediation.RemediationError):
    pass


def _fixed_paths() -> tuple[Path, Path]:
    approval = ACTIVE_FULL_TEST_APPROVAL.absolute()
    consumption = ACTIVE_FULL_TEST_CONSUMPTION.absolute()
    fixed_approval = remediation.ROOT / (
        "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json"
    )
    fixed_consumption = remediation.ROOT / (
        "docs/reports/DG-10-full-test-access-consumption-candidate.4-2026-08-22.json"
    )
    if (
        approval != fixed_approval.absolute()
        or consumption != fixed_consumption.absolute()
        or remediation.has_symlink_component(approval)
        or remediation.has_symlink_component(consumption)
    ):
        raise FullTestExecutionError("fixed AI full-test paths are unsafe")
    return approval, consumption


def _approved_inputs(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FullTestExecutionError("fixed AI full-test approval is absent or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullTestExecutionError("fixed AI full-test approval is invalid") from exc
    inputs = value.get("inputs") if isinstance(value, Mapping) else None
    if not isinstance(inputs, Mapping) or set(inputs) != APPROVED_INPUT_KEYS:
        raise FullTestExecutionError("fixed AI full-test approval input set drift")
    return dict(inputs)


def execute_full_test(
    full_test_runner: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Sole candidate.4 boundary for opening or running the protected full test.

    The independently imported fixed approval is consumed atomically before the
    callback can access any protected input. A failed callback still burns the
    capability, so every later invocation fails closed.
    """

    approval_path, consumption_path = _fixed_paths()
    expected_inputs = _approved_inputs(approval_path)
    try:
        independent_gates.consume_ai_test_access_capability(
            approval_path,
            expected_inputs=expected_inputs,
            consumption_path=consumption_path,
        )
    except independent_gates.IndependentGateError as exc:
        raise FullTestExecutionError(str(exc)) from exc
    result = full_test_runner(expected_inputs)
    if not isinstance(result, Mapping):
        raise FullTestExecutionError("full-test runner returned a non-object result")
    try:
        independent_gates.validate_ai_test_access_approval(
            approval_path,
            expected_inputs=expected_inputs,
        )
    except independent_gates.IndependentGateError as exc:
        raise FullTestExecutionError(
            "approved full-test inputs drifted during protected execution"
        ) from exc
    return result
