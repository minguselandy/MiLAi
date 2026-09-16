from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dg10_full_test_executor as executor
from scripts import dg10_remediation as remediation


def test_full_test_boundary_consumes_before_access_and_rejects_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    approval = tmp_path / (
        "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json"
    )
    approval.parent.mkdir(parents=True)
    inputs = {
        name: {"path": f"sealed/{name}", "sha256": name[0] * 64}
        for name in executor.APPROVED_INPUT_KEYS
    }
    approval.write_text(json.dumps({"inputs": inputs}) + "\n", encoding="utf-8")
    consumption = tmp_path / (
        "docs/reports/DG-10-full-test-access-consumption-candidate.4-2026-08-22.json"
    )
    monkeypatch.setattr(executor, "ACTIVE_FULL_TEST_APPROVAL", approval)
    monkeypatch.setattr(executor, "ACTIVE_FULL_TEST_CONSUMPTION", consumption)
    calls = 0

    def validate(path: Path, *, expected_inputs: object) -> dict[str, object]:
        assert path == approval
        assert expected_inputs == inputs
        return {
            "receipt": {
                "path": approval.relative_to(tmp_path).as_posix(),
                "sha256": remediation.sha256_file(approval),
            },
            "primary_audits": [],
        }

    monkeypatch.setattr(
        executor.independent_gates,
        "validate_ai_test_access_approval",
        validate,
    )

    def run(bound_inputs: object) -> dict[str, str]:
        nonlocal calls
        calls += 1
        assert consumption.is_file()
        assert bound_inputs == inputs
        return {"status": "PASS"}

    assert executor.execute_full_test(run) == {"status": "PASS"}
    with pytest.raises(executor.FullTestExecutionError, match="already consumed"):
        executor.execute_full_test(run)
    assert calls == 1
    receipt = json.loads(consumption.read_text(encoding="utf-8"))
    assert receipt["approved_inputs"] == inputs
    assert receipt["remaining_full_test_uses"] == 0


def test_full_test_boundary_rejects_symlinked_fixed_approval_before_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    target = tmp_path / "sealed/approval.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"inputs": {}}) + "\n", encoding="utf-8")
    approval = tmp_path / (
        "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json"
    )
    approval.parent.mkdir(parents=True)
    approval.symlink_to(target)
    consumption = tmp_path / (
        "docs/reports/DG-10-full-test-access-consumption-candidate.4-2026-08-22.json"
    )
    monkeypatch.setattr(executor, "ACTIVE_FULL_TEST_APPROVAL", approval)
    monkeypatch.setattr(executor, "ACTIVE_FULL_TEST_CONSUMPTION", consumption)

    called = False

    def run(_inputs: object) -> dict[str, str]:
        nonlocal called
        called = True
        return {"status": "PASS"}

    with pytest.raises(executor.FullTestExecutionError, match="paths are unsafe"):
        executor.execute_full_test(run)
    assert called is False
    assert not consumption.exists()
