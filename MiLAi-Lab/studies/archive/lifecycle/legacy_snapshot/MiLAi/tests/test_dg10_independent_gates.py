from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import dg10_authorization as authorization
from scripts import dg10_independent_gates as gates
from scripts import dg10_remediation as remediation


def test_test_access_importer_cli_parser_starts() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/import_dg10_ai_test_access.py", "--help"],
        cwd=remediation.ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert sum(
        line.startswith("  --attempt-ledger ")
        for line in completed.stdout.splitlines()
    ) == 1


def _annotation(identity: str, values: dict[str, str]) -> dict[str, object]:
    return {
        "annotator_id_hash": identity,
        "evidence_class": "HUMAN",
        "independent": True,
        "blind_package_sha256": "a" * 64,
        "arm_labels_visible": False,
        "model_judge_used": False,
        "ratings": values,
    }


def test_two_humans_and_third_conflict_adjudicator_are_enforced() -> None:
    result = gates.validate_tier2_human_audit(
        annotations=[
            _annotation("1" * 64, {"case-1": "PASS", "case-2": "FAIL"}),
            _annotation("2" * 64, {"case-1": "PASS", "case-2": "PASS"}),
        ],
        adjudication={
            "annotator_id_hash": "3" * 64,
            "evidence_class": "HUMAN",
            "resolutions": {"case-2": "PASS"},
        },
        blind_package_sha256="a" * 64,
    )
    assert result["primary_annotator_count"] == 2
    assert result["adjudicated_conflict_count"] == 1
    assert result["independent_acceptance"] is False


def test_model_judge_or_same_human_fails_tier2() -> None:
    first = _annotation("1" * 64, {"case-1": "PASS"})
    second = _annotation("1" * 64, {"case-1": "PASS"})
    second["model_judge_used"] = True
    with pytest.raises(gates.IndependentGateError):
        gates.validate_tier2_human_audit(
            annotations=[first, second], adjudication=None, blind_package_sha256="a" * 64
        )


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return path


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": remediation.sha256_file(path),
    }


def _ai_run(root: Path, name: str, *, thread: str, verdict: str) -> Path:
    raw = root / f"docs/reviews/{name}-raw"
    prompt = raw / "prompt.md"
    schema = raw / "response.schema.json"
    output = raw / "output.json"
    events = raw / "events.jsonl"
    stderr = raw / "stderr.log"
    process = raw / "process.json"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("audit\n")
    schema.write_text("{}\n")
    output_value = {"decision": "PASS"}
    output.write_text(json.dumps(output_value, sort_keys=True) + "\n")
    events.write_text(
        "\n".join(
            json.dumps(value, sort_keys=True)
            for value in (
                {"type": "thread.started", "thread_id": thread},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(output_value)},
                },
                {"type": "turn.completed"},
            )
        )
        + "\n"
    )
    stderr.write_bytes(b"")
    process_value = {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "process_exit_code": 0,
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_rules": True,
        "prompt_sha256": remediation.sha256_file(prompt),
        "response_schema_sha256": remediation.sha256_file(schema),
        "output_sha256": remediation.sha256_file(output),
        "events_sha256": remediation.sha256_file(events),
        "stderr_sha256": remediation.sha256_file(stderr),
    }
    _write(process, process_value)
    raw_paths = {
        "prompt": prompt,
        "response_schema": schema,
        "output": output,
        "events": events,
        "stderr": stderr,
        "process": process,
    }
    return _write(
        root / f"docs/reviews/{name}.json",
        {
            "schema": "milai.dg10.ai-review-run-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "scope": "TIER2_PRIMARY",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "cli_version": "codex-cli 0.147.0",
            "process_exit_code": 0,
            "provider_thread_id": thread,
            "provider_thread_count": 1,
            "turn_completed_count": 1,
            "error_count": 0,
            "output_schema_validation": "PASS",
            "boundary_validation": "PASS",
            "decision": "PASS",
            "open_p0": 0,
            "open_p1": 0,
            "verdict_sha256": verdict,
            "raw_evidence_hashes": {
                key: remediation.sha256_file(path)
                for key, path in raw_paths.items()
                if key != "process"
            },
            "raw_evidence": {key: _ref(root, path) for key, path in raw_paths.items()},
        },
    )


def test_two_locally_fabricated_sol_threads_cannot_replace_tier2_humans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    monkeypatch.setattr(authorization, "ROOT", tmp_path)
    policy = _write(
        tmp_path / "docs/contracts/DG-10-ai-audit-reasoning-amendment-candidate.4.2.json",
        {"candidate_id": remediation.CANDIDATE, "status": "USER_AUTHORIZED_POLICY_OVERRIDE_FROZEN"},
    )
    monkeypatch.setattr(remediation, "AI_POLICY_OVERRIDE", policy)
    first = _ai_run(tmp_path, "first", thread="thread-1", verdict="a" * 64)
    second = _ai_run(tmp_path, "second", thread="thread-2", verdict="a" * 64)
    receipt = _write(
        tmp_path / "docs/reports/tier2-ai.json",
        {
            "schema": "milai.dg10.tier2-ai-audit.v1",
            "candidate_id": remediation.CANDIDATE,
            "status": "AI_AUDIT_COMPLETE",
            "evidence_class": "AI_INDEPENDENT",
            "policy_override_sha256": remediation.sha256_file(policy),
            "blind_package_sha256": "b" * 64,
            "primary_audits": [_ref(tmp_path, first), _ref(tmp_path, second)],
            "adjudication": None,
        },
    )
    with pytest.raises(
        gates.IndependentGateError,
        match="raw process provenance drift",
    ):
        gates.validate_tier2_ai_audit(receipt)


def test_same_ai_thread_or_hand_constructed_pass_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    monkeypatch.setattr(authorization, "ROOT", tmp_path)
    policy = _write(
        tmp_path / "docs/contracts/DG-10-ai-audit-reasoning-amendment-candidate.4.2.json",
        {"candidate_id": remediation.CANDIDATE, "status": "USER_AUTHORIZED_POLICY_OVERRIDE_FROZEN"},
    )
    monkeypatch.setattr(remediation, "AI_POLICY_OVERRIDE", policy)
    first = _ai_run(tmp_path, "first", thread="same", verdict="a" * 64)
    second = _ai_run(tmp_path, "second", thread="same", verdict="a" * 64)
    receipt = _write(
        tmp_path / "docs/reports/tier2-ai.json",
        {
            "schema": "milai.dg10.tier2-ai-audit.v1",
            "candidate_id": remediation.CANDIDATE,
            "status": "AI_AUDIT_COMPLETE",
            "evidence_class": "AI_INDEPENDENT",
            "policy_override_sha256": remediation.sha256_file(policy),
            "blind_package_sha256": "b" * 64,
            "primary_audits": [_ref(tmp_path, first), _ref(tmp_path, second)],
            "adjudication": None,
        },
    )
    with pytest.raises(
        gates.IndependentGateError,
        match="raw process provenance drift",
    ):
        gates.validate_tier2_ai_audit(receipt)
    with pytest.raises(gates.IndependentGateError, match="release is disabled"):
        gates.authorize_release(
            {
                "schema": "milai.dg10.remediation-controlled-decision.v2",
                "candidate_id": remediation.CANDIDATE,
                "result": "PASS",
                "release_authorized": True,
                "independent_acceptance": True,
            }
        )


def test_full_test_ai_capability_is_consumed_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    approval = _write(tmp_path / "docs/reports/approval.json", {"decision": "PASS"})
    monkeypatch.setattr(
        gates,
        "validate_ai_test_access_approval",
        lambda path, expected_inputs: {
            "receipt": _ref(tmp_path, path),
            "primary_audits": [],
        },
    )
    consumption = tmp_path / (
        "docs/reports/DG-10-full-test-access-consumption-candidate.4-2026-08-22.json"
    )
    first = gates.consume_ai_test_access_capability(
        approval,
        expected_inputs={},
        consumption_path=consumption,
    )
    assert first["remaining_full_test_uses"] == 0
    with pytest.raises(gates.IndependentGateError, match="already consumed"):
        gates.consume_ai_test_access_capability(
            approval,
            expected_inputs={},
            consumption_path=consumption,
        )
