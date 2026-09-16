from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts import dg10_memory_quality as memory_quality
from scripts import dg10_quality_stats as stats
from scripts import dg10_remediation as remediation


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return path


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": remediation.sha256_file(path),
    }


def _ai_test_access_run(root: Path, name: str, thread: str) -> Path:
    raw = root / f"docs/reviews/{name}-raw"
    raw.mkdir(parents=True)
    paths = {
        "prompt": raw / "prompt.md",
        "response_schema": raw / "response.schema.json",
        "output": raw / "output.json",
        "events": raw / "events.jsonl",
        "stderr": raw / "stderr.log",
        "process": raw / "process.json",
    }
    paths["prompt"].write_text("audit\n")
    paths["response_schema"].write_text("{}\n")
    output = {"decision": "APPROVE_ONE_FULL_TEST"}
    paths["output"].write_text(json.dumps(output, sort_keys=True) + "\n")
    paths["events"].write_text(
        "\n".join(
            json.dumps(value, sort_keys=True)
            for value in (
                {"type": "thread.started", "thread_id": thread},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(output)},
                },
                {"type": "turn.completed"},
            )
        )
        + "\n"
    )
    paths["stderr"].write_bytes(b"")
    _write(
        paths["process"],
        {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "process_exit_code": 0,
            "sandbox": "read-only",
            "ephemeral": True,
            "ignore_user_config": True,
            "ignore_rules": True,
            "prompt_sha256": remediation.sha256_file(paths["prompt"]),
            "response_schema_sha256": remediation.sha256_file(paths["response_schema"]),
            "output_sha256": remediation.sha256_file(paths["output"]),
            "events_sha256": remediation.sha256_file(paths["events"]),
            "stderr_sha256": remediation.sha256_file(paths["stderr"]),
        },
    )
    return _write(
        root / f"docs/reviews/{name}.json",
        {
            "schema": "milai.dg10.ai-review-run-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "scope": "TEST_ACCESS_PRIMARY",
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
            "verdict_sha256": "a" * 64,
            "raw_evidence_hashes": {
                key: remediation.sha256_file(path)
                for key, path in paths.items()
                if key != "process"
            },
            "raw_evidence": {key: _ref(root, path) for key, path in paths.items()},
        },
    )


def _rows() -> list[stats.QualityCase]:
    rows: list[stats.QualityCase] = []
    for stage, prefix in (
        ("CURRENT_50_DIAGNOSTIC", "current"),
        ("DISJOINT_CONFIRMATION_DEV", "confirmation"),
    ):
        for index in range(50):
            rows.append(
                stats.QualityCase(
                    case_id=f"{prefix}-{index}",
                    stage=stage,
                    category="knowledge_update" if index % 2 else "temporal",
                    rag_f1=0.5,
                    milai_f1=0.6,
                    rag_exact_match=0.4,
                    milai_exact_match=0.5,
                    rag_recall_at_1=0.5,
                    milai_recall_at_1=0.6,
                    milai_false_certainty=False,
                    topology_pass=True,
                    ledger_attempt_ids={
                        arm: f"quality-{prefix}-{index}-{arm.lower()}"
                        for arm in memory_quality.ARMS
                    },
                )
            )
    return rows


def _safety() -> dict[str, int]:
    return {
        "cross_tenant_returns": 0,
        "revoked_or_stale_returns": 0,
        "authority_escalations": 0,
        "live_open_issue_false_closures": 0,
        "unsupported_action_safe_answers": 0,
        "canonical_unavailable_false_certainty": 0,
        "hidden_or_extra_model_calls": 0,
        "secret_dsn_or_raw_data_leaks": 0,
    }


def _ledger(path: Path, rows: list[stats.QualityCase]) -> None:
    usage = {
        "input_tokens": 10,
        "output_tokens": 2,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
    }
    with remediation.AttemptLedger(path) as ledger:
        for row in rows:
            for arm in ("NO_MEMORY", "NAIVE_RAG", "MILAI_RETRIEVAL"):
                with_mcp = arm == "MILAI_RETRIEVAL"
                attempt = ledger.start_attempt(
                    phase="TRACK_A_MEMORY_QUALITY",
                    arm=arm,
                    case_id=row.case_id,
                    planned_model_calls=1,
                    planned_mcp_calls=int(with_mcp),
                    attempt_id=row.ledger_attempt_ids[arm],
                )
                if with_mcp:
                    ledger.record_mcp_accepted(attempt, f"mcp-{row.case_id}")
                    ledger.record_mcp_terminal(attempt, raw_sidecar_digest="a" * 64)
                ledger.record_provider_accepted(attempt, f"model-{row.case_id}-{arm}")
                ledger.record_provider_terminal(
                    attempt,
                    usage=usage,
                    raw_sidecar_digest="b" * 64,
                )
                ledger.finalize(
                    attempt,
                    agent_terminal=True,
                    parser_terminal=True,
                    retention_state="retained",
                    failure_reason_code="SUCCESS",
                    redacted_public_receipt_digest="c" * 64,
                )


def _topology_records(rows: list[stats.QualityCase]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in rows:
        query_sha256 = hashlib.sha256(row.case_id.encode()).hexdigest()
        for arm in memory_quality.ARMS:
            no_memory = arm == "NO_MEMORY"
            milai = arm == "MILAI_RETRIEVAL"
            memory_text = "" if no_memory else "context"
            evidence_ids = [] if no_memory else [f"evidence-{row.case_id}-{arm}"]
            records.append(
                {
                    "schema": "milai.dg10.memory-quality-arm-record.v1",
                    "candidate_id": remediation.CANDIDATE,
                    "attempt_id": row.ledger_attempt_ids[arm],
                    "case_id": row.case_id,
                    "arm": arm,
                    "host_runner": "TrackAHarness",
                    "renderer_sha256": memory_quality._renderer_sha256(),
                    "system_prompt_sha256": hashlib.sha256(
                        memory_quality.SYSTEM_PROMPT.encode()
                    ).hexdigest(),
                    "generation": {
                        "temperature": memory_quality.TEMPERATURE,
                        "seed": memory_quality.SEED,
                        "max_output_tokens": memory_quality.MAX_OUTPUT_TOKENS,
                    },
                    "answer_model_calls": 1,
                    "mcp_calls": int(milai),
                    "native_request_id_sha256": hashlib.sha256(
                        f"model-{row.case_id}-{arm}".encode()
                    ).hexdigest(),
                    "finish_reason": "stop",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "memory_target_tokens": 0 if no_memory else 1,
                    "memory_context_sha256": hashlib.sha256(
                        memory_text.encode()
                    ).hexdigest(),
                    "answer_sha256": "d" * 64,
                    "score_field": "answer",
                    "retrieval": {
                        "query_sha256": query_sha256,
                        "query_equals_original_question": True,
                        "ranking_source": (
                            "NONE"
                            if no_memory
                            else "MILAI_RUNTIME_CANONICAL_GATE"
                            if milai
                            else "NAIVE_RAG_FROZEN_BASELINE"
                        ),
                        "governed_ingest": milai,
                        "canonical_gate": milai,
                        "full_session_corpus": milai,
                        "artificial_marker": False,
                        "shared_naive_ranking": False,
                        "evidence_ids_sha256": hashlib.sha256(
                            json.dumps(sorted(evidence_ids)).encode()
                        ).hexdigest(),
                    },
                }
            )
    return records


def _artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    monkeypatch.setattr(stats.independent_gates.authorization, "ROOT", tmp_path)
    rows = _rows()
    policy = _write(
        tmp_path / "docs/contracts/DG-10-ai-audit-reasoning-amendment-candidate.4.2.json",
        {"candidate_id": remediation.CANDIDATE, "status": "USER_AUTHORIZED_POLICY_OVERRIDE_FROZEN"},
    )
    monkeypatch.setattr(remediation, "AI_POLICY_OVERRIDE", policy)
    identity = _write(
        tmp_path
        / "docs/reports/DG-10-authorization-identities-candidate.4.4-2026-08-22.json",
        {"candidate_id": remediation.CANDIDATE},
    )
    monkeypatch.setattr(
        stats.independent_gates.authorization,
        "ACTIVE_IDENTITIES",
        identity,
    )
    monkeypatch.setattr(
        stats.independent_gates.authorization,
        "_verify_identity_receipt",
        lambda _path: {"receipt": _ref(tmp_path, identity)},
    )
    acceptance = tmp_path / "docs/contracts/acceptance.yaml"
    acceptance.write_text("frozen: true\n")
    evidence = tmp_path / "docs/reports/evidence.json"
    _write(evidence, {"status": "PASS"})
    manifest = _write(
        tmp_path / "docs/contracts/case-manifest.json",
        {
            "schema": "milai.dg10.memory-quality-case-manifest.v1",
            "candidate_id": remediation.CANDIDATE,
            "frozen_at": "2026-08-21T00:00:00+00:00",
            "acceptance_contract": _ref(tmp_path, acceptance),
            "stages": {
                "CURRENT_50_DIAGNOSTIC": [f"current-{index}" for index in range(50)],
                "DISJOINT_CONFIRMATION_DEV": [f"confirmation-{index}" for index in range(50)],
            },
            "required_categories": ["knowledge_update", "temporal"],
        },
    )
    ledger = tmp_path / "docs/reports/attempts.jsonl"
    _ledger(ledger, rows)
    results = _write(
        tmp_path / "docs/reports/results.json",
        {
            "schema": "milai.dg10.memory-quality-results.v1",
            "candidate_id": remediation.CANDIDATE,
            "case_manifest_sha256": remediation.sha256_file(manifest),
            "accessed_at": "2026-08-23T00:00:00+00:00",
            "rows": [asdict(row) for row in rows],
        },
    )
    records = _topology_records(rows)
    record_document = _write(
        tmp_path / "docs/reports/topology-records.json",
        {
            "schema": "milai.dg10.memory-quality-record-set.v1",
            "candidate_id": remediation.CANDIDATE,
            "case_manifest_sha256": remediation.sha256_file(manifest),
            "attempt_ledger_sha256": remediation.sha256_file(ledger),
            "records": records,
        },
    )
    topology = _write(
        tmp_path / "docs/reports/topology.json",
        {
            "schema": "milai.dg10.topology-validation-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "result": "PASS",
            "case_manifest_sha256": remediation.sha256_file(manifest),
            "attempt_ledger_sha256": remediation.sha256_file(ledger),
            "records": _ref(tmp_path, record_document),
            "validation": memory_quality.validate_topology(records),
            "evidence": [_ref(tmp_path, evidence)],
        },
    )
    hard_safety = _write(
        tmp_path / "docs/reports/hard-safety.json",
        {
            "schema": "milai.dg10.hard-safety-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "result": "PASS",
            "case_manifest_sha256": remediation.sha256_file(manifest),
            "results_sha256": remediation.sha256_file(results),
            "attempt_ledger_sha256": remediation.sha256_file(ledger),
            "topology_receipt_sha256": remediation.sha256_file(topology),
            "counters": _safety(),
            "evidence": [_ref(tmp_path, evidence)],
        },
    )
    first = _ai_test_access_run(tmp_path, "test-access-ai-1", "thread-1")
    second = _ai_test_access_run(tmp_path, "test-access-ai-2", "thread-2")
    bundle_receipt = _write(
        tmp_path / "docs/reports/test-access-bundle.json", {"status": "BOUND"}
    )
    approval = _write(
        tmp_path
        / "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json",
        {
            "schema": "milai.dg10.ai-test-access-approval.v2",
            "candidate_id": remediation.CANDIDATE,
            "decision": "APPROVE_ONE_FULL_TEST",
            "evidence_class": "AI_INDEPENDENT",
            "policy_override_sha256": remediation.sha256_file(policy),
            "identity_receipt": _ref(tmp_path, identity),
            "open_p0": 0,
            "open_p1": 0,
            "inputs": {
                "results": _ref(tmp_path, results),
                "case_manifest": _ref(tmp_path, manifest),
                "attempt_ledger": _ref(tmp_path, ledger),
                "topology": _ref(tmp_path, topology),
                "hard_safety": _ref(tmp_path, hard_safety),
            },
            "bundle_receipt": _ref(tmp_path, bundle_receipt),
            "primary_audits": [_ref(tmp_path, first), _ref(tmp_path, second)],
            "provider_thread_count": 2,
            "semantic_verdict_sha256": "a" * 64,
        },
    )

    # Protected provider provenance is covered by the independent-gate tests.
    # Keep this quality-statistics unit test focused on the gate's bound-input
    # contract without minting a fake provider execution attestation.
    def validate_test_access(
        receipt_path: Path, *, expected_inputs: object
    ) -> dict[str, object]:
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("inputs") != expected_inputs:
            raise stats.independent_gates.IndependentGateError(
                "AI test-access approval semantic drift"
            )
        return {"receipt": _ref(tmp_path, receipt_path), "primary_audits": []}

    monkeypatch.setattr(
        stats.independent_gates,
        "validate_ai_test_access_approval",
        validate_test_access,
    )
    return {
        "manifest": manifest,
        "results": results,
        "hard_safety": hard_safety,
        "topology": topology,
        "ledger": ledger,
        "approval": approval,
    }


def _build(paths: dict[str, Path]) -> dict[str, object]:
    return stats.build_quality_gate(
        results_path=paths["results"],
        case_manifest_path=paths["manifest"],
        hard_safety_receipt_path=paths["hard_safety"],
        attempt_ledger_path=paths["ledger"],
        topology_receipt_path=paths["topology"],
        ai_test_access_receipt_path=paths["approval"],
    )


def test_quality_gate_uses_bound_artifacts_and_ai_test_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _build(_artifacts(tmp_path, monkeypatch))
    current = result["stage_reports"]["CURRENT_50_DIAGNOSTIC"]
    assert current["overall"]["paired_f1"] == {"better": 50, "equal": 0, "worse": 0}
    assert set(current["ability"]) == {"knowledge_update", "temporal"}
    assert result["attempt_ledger_complete"] is True
    assert result["ai_test_access_approval"] is True
    assert result["full_test_authorized"] is True


def test_confirmation_denominator_and_required_strata_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _artifacts(tmp_path, monkeypatch)
    manifest = json.loads(paths["manifest"].read_text())
    manifest["stages"]["DISJOINT_CONFIRMATION_DEV"].pop()
    paths["manifest"].write_text(json.dumps(manifest) + "\n")
    with pytest.raises(stats.QualityStatsError, match="confirmation denominator"):
        _build(paths)


def test_ai_approval_cannot_be_reused_after_input_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _artifacts(tmp_path, monkeypatch)
    results = json.loads(paths["results"].read_text())
    results["rows"][50]["category"] = "other"
    paths["results"].write_text(json.dumps(results) + "\n")
    with pytest.raises(
        stats.QualityStatsError,
        match=r"required ability stratum|approval semantic drift|input binding drift",
    ):
        _build(paths)


def test_quality_rows_reject_boolean_spoofs_and_ledger_splicing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _artifacts(tmp_path, monkeypatch)
    results = json.loads(paths["results"].read_text())
    results["rows"][0]["milai_false_certainty"] = 0
    paths["results"].write_text(json.dumps(results) + "\n")
    with pytest.raises(stats.QualityStatsError, match="row type drift"):
        _build(paths)

    paths = _artifacts(tmp_path / "splice", monkeypatch)
    results = json.loads(paths["results"].read_text())
    results["rows"][0]["ledger_attempt_ids"]["NO_MEMORY"] = results["rows"][1][
        "ledger_attempt_ids"
    ]["NO_MEMORY"]
    paths["results"].write_text(json.dumps(results) + "\n")
    with pytest.raises(stats.QualityStatsError, match="attempt ID repeats"):
        _build(paths)
