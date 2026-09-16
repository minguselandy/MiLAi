from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import dg10_bfcl_scoring as scoring
from scripts import dg10_remediation as remediation


def _rows(*, ledger_sha256: str = "c" * 64) -> list[scoring.BfclCase]:
    categories = ["multi_turn"] * 80 + ["irrelevance_no_call"] * 24 + ["supported_single_turn"] * 112
    return [
        scoring.BfclCase(
            case_id=f"case-{index}",
            attempt_id=f"attempt-{index}",
            ledger_attempt_ids=tuple(
                f"attempt-{index}-model-{step}"
                for step in range(1 if category != "multi_turn" else 3)
            ),
            category=category,
            passed=True,
            terminal=True,
            steps=1 if category != "multi_turn" else 3,
            candidate_id="candidate.4",
            worker_environment_sha256="a" * 64,
            adapter_sha256="b" * 64,
            ledger_sha256=ledger_sha256,
            language=("javascript" if index % 11 == 0 else "java" if index % 13 == 0 else "python"),
        )
        for index, category in enumerate(categories)
    ]


def _focused() -> dict[str, object]:
    return scoring.validate_focused_results({name: True for name in scoring.FOCUSED_CASES})


def _capability() -> dict[str, object]:
    return scoring.capability_gate(
        native_protocol_supported=False,
        native_probe_terminal=False,
        native_probe_tool_calls_valid=False,
        adapted_protocol_frozen=True,
    )


def _manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(scoring.remediation, "ROOT", tmp_path)
    execution_identity = tmp_path / "execution-identity.json"
    execution_identity.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(scoring, "ACTIVE_EXECUTION_IDENTITY", execution_identity)
    acceptance = tmp_path / "acceptance.yaml"
    acceptance.write_text("frozen: true\n", encoding="utf-8")
    monkeypatch.setattr(scoring, "ACTIVE_ACCEPTANCE_CONTRACT", acceptance)
    relative = Path("deps/python.lock")
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("coherent-worker-dependency-closure\n", encoding="utf-8")
    dependency = {
        "path": relative.as_posix(),
        "sha256": scoring.remediation.sha256_file(target),
    }
    dependencies = {
        language: dict(dependency) for language in ("python", "javascript", "java")
    }
    rows = _rows()
    manifest = {
        "schema": "milai.dg10.bfcl-case-manifest.v2",
        "candidate_id": "candidate.4",
        "frozen_at": "2026-08-22T00:00:00+00:00",
        "acceptance_contract": {
            "path": "acceptance.yaml",
            "sha256": scoring.remediation.sha256_file(acceptance),
        },
        "case_count": len(rows),
        "cases": [
            {
                "case_id": row.case_id,
                "supported_single_turn": index >= 94,
                "multi_turn": index < 80,
                "irrelevance_no_call": 80 <= index < 104,
                "language": row.language,
            }
            for index, row in enumerate(rows)
        ],
        "execution_identity": {"path": "execution-identity.json", "sha256": "d" * 64},
        "dependency_closure": dependencies,
    }
    path = tmp_path / "bfcl-case-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(scoring, "ACTIVE_CASE_MANIFEST", path)
    monkeypatch.setattr(
        scoring,
        "ACTIVE_CASE_MANIFEST_SHA256",
        scoring.remediation.sha256_file(path),
    )
    ledger_path = tmp_path / f"attempts-{len(list(tmp_path.glob('attempts-*.jsonl')))}.jsonl"
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
    }
    with remediation.AttemptLedger(ledger_path) as ledger:
        for row in rows:
            for ledger_attempt_id in row.ledger_attempt_ids:
                attempt_id = ledger.start_attempt(
                    phase="BFCL_DEV",
                    arm="ADAPTED_LOCAL_NON_LIVE",
                    case_id=row.case_id,
                    planned_model_calls=1,
                    planned_mcp_calls=0,
                    attempt_id=ledger_attempt_id,
                )
                ledger.record_provider_accepted(
                    attempt_id,
                    f"native-{ledger_attempt_id}",
                )
                ledger.record_provider_terminal(
                    attempt_id,
                    usage=usage,
                    raw_sidecar_digest="e" * 64,
                )
                ledger.finalize(
                    attempt_id,
                    agent_terminal=True,
                    parser_terminal=True,
                    retention_state="retained",
                    failure_reason_code="SUCCESS",
                    redacted_public_receipt_digest="f" * 64,
                )
    monkeypatch.setattr(scoring, "ACTIVE_BFCL_ATTEMPT_LEDGER", ledger_path)
    monkeypatch.setattr(
        scoring,
        "_execution_identity",
        lambda _reference, *, manifest_frozen_at: {
            "worker_environment_sha256": "a" * 64,
            "adapter_sha256": "b" * 64,
            "ledger_path": ledger_path,
            "worker_closure_path": target.resolve(),
            "worker_closure_sha256": scoring.remediation.sha256_file(target),
        },
    )
    return path


def _bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[scoring.BfclCase]]:
    manifest = _manifest(tmp_path, monkeypatch)
    return manifest, _rows(ledger_sha256=remediation.sha256_file(scoring.ACTIVE_BFCL_ATTEMPT_LEDGER))


def test_homogeneous_216_case_gate_checks_all_four_thresholds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = _bound(tmp_path, monkeypatch)
    report = scoring.build_homogeneous_dev_gate(
        rows,
        capability=_capability(),
        focused=_focused(),
        case_manifest_path=manifest,
        results_accessed_at="2026-08-22T00:01:00+00:00",
    )
    assert report["case_count"] == 216
    assert report["multi_turn_case_count"] == 80
    assert report["attempt_ledger_model_call_count"] == 376
    assert all(report["threshold_results"].values())
    assert report["gate_pass"] is True
    assert report["official_leaderboard_claim_allowed"] is False


def test_mixed_candidate_or_environment_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = _bound(tmp_path, monkeypatch)
    rows[-1] = replace(rows[-1], candidate_id="candidate.2", worker_environment_sha256="9" * 64)
    with pytest.raises(scoring.BfclScoringError, match="candidate splice"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=manifest,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )


def test_step_ceiling_cannot_be_raised_or_exceeded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = _bound(tmp_path, monkeypatch)
    rows[0] = replace(rows[0], steps=21)
    with pytest.raises(scoring.BfclScoringError, match="step ceiling"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=manifest,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )


def test_each_bfcl_model_step_requires_a_distinct_ledger_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = _bound(tmp_path, monkeypatch)
    rows[0] = replace(rows[0], ledger_attempt_ids=rows[0].ledger_attempt_ids[:1])
    with pytest.raises(scoring.BfclScoringError, match="model-call ledger binding"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=manifest,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )


def test_bfcl_boolean_and_integer_fields_cannot_be_spoofed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = _bound(tmp_path, monkeypatch)
    rows[0] = replace(rows[0], passed=1)
    with pytest.raises(scoring.BfclScoringError, match="field type drift"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=manifest,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )


def test_manifest_denominators_and_dependency_hashes_are_recomputed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, rows = _bound(tmp_path, monkeypatch)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["cases"][94]["supported_single_turn"] = False
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        scoring,
        "ACTIVE_CASE_MANIFEST_SHA256",
        scoring.remediation.sha256_file(path),
    )
    with pytest.raises(scoring.BfclScoringError, match="denominator must be 122"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=path,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )

    path, rows = _bound(tmp_path, monkeypatch)
    dependency = tmp_path / "deps" / "python.lock"
    dependency.write_text("mutated\n", encoding="utf-8")
    with pytest.raises(scoring.BfclScoringError, match="dependency closure hash drift"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=path,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )


def test_manifest_must_be_frozen_before_result_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, rows = _bound(tmp_path, monkeypatch)
    with pytest.raises(scoring.BfclScoringError, match="before preregistration freeze"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused=_focused(),
            case_manifest_path=path,
            results_accessed_at="2026-08-21T23:59:59+00:00",
        )


def test_native_capability_failure_cannot_fall_through_to_adapted_pass() -> None:
    result = scoring.capability_gate(
        native_protocol_supported=True,
        native_probe_terminal=False,
        native_probe_tool_calls_valid=False,
        adapted_protocol_frozen=True,
    )
    assert result["gate_pass"] is False
    assert result["execution_mode"] == "NATIVE_PROBE_FAILED"


def test_forged_capability_or_focused_summary_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows = _bound(tmp_path, monkeypatch)
    with pytest.raises(scoring.BfclScoringError, match="capability receipt key set"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability={"gate_pass": True},
            focused=_focused(),
            case_manifest_path=manifest,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )
    with pytest.raises(scoring.BfclScoringError, match="focused receipt key set"):
        scoring.build_homogeneous_dev_gate(
            rows,
            capability=_capability(),
            focused={"gate_pass": True},
            case_manifest_path=manifest,
            results_accessed_at="2026-08-22T00:01:00+00:00",
        )
