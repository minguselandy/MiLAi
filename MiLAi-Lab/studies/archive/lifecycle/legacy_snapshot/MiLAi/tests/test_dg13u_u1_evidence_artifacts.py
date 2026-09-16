from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from scripts import dg13u_u1_aggregate as aggregate
from scripts import dg13u_u1_evidence_artifacts as evidence

RUN_ID = "dg13u-u1-evidence-test"
CASE_ID = "U1-EXACT-TARGET-EN"
HASHES = {
    "access_id_sha256": "a" * 64,
    "mcp_receipt_sha256": "b" * 64,
    "runtime_trace_sha256": "c" * 64,
    "provider_native_request_id_sha256": "d" * 64,
}


def _run_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / RUN_ID
    path.mkdir(mode=0o700)
    return path


def _readiness() -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "status": "PASS",
        "components": {
            "runtime": "PASS",
            "broker": "PASS",
            "host": "PASS",
            "openworker": "PASS",
            "provider": "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS",
        },
        "provider_completion_calls": 0,
        "security": {
            "status": "PASS",
            "network_internal": True,
            "network_mode_sha256": "e" * 64,
            "cap_drop_all": True,
            "no_new_privileges": True,
            "reader_lite_socket_read_only": True,
            "docker_socket_mounted": False,
            "forbidden_environment_names": [],
        },
        "latencies_ms": {
            "runtime": 1.0,
            "broker": 2.0,
            "host": 3.0,
            "openworker": 4.0,
            "provider": 5.0,
        },
        "worker_health_sha256": "f" * 64,
        "mcp_list_sha256": "0" * 64,
    }


def _calls() -> dict[str, object]:
    return {
        "mcp": {
            "expected": 1,
            "observed": 1,
            "unaccounted": 0,
            "automatic_retries": 0,
        },
        "provider": {
            "expected": 1,
            "observed": 1,
            "unaccounted": 0,
            "automatic_retries": 0,
            "maximum_per_model_round": 1,
            "model_rounds": 1,
            "calls_per_task_operation": 1,
            "case_maximum": 1,
        },
    }


def _latencies() -> dict[str, object]:
    return {
        "openworker": 1.0,
        "adapter": 2.0,
        "mcp": 3.0,
        "runtime": 4.0,
        "compile": 5.0,
        "provider": 6.0,
    }


def _smoke() -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "status": "PASS",
        "calls": _calls(),
        "joined_identities": dict(HASHES),
        "latencies_ms": _latencies(),
        "context_tokens": 42,
        "model_visible_memory_tool_events": 0,
        "raw_prompt_or_answer_persisted": False,
        "provider_terminal_status": "SUCCEEDED",
        "worker_exit_code": 0,
        "worker_output_sha256": "1" * 64,
        "worker_output_bytes": 128,
        "memory_route": "EXACT",
    }


def _reconciliation() -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "status": "PASS",
        "calls": _calls(),
        "joined_identities": dict(HASHES),
        "latencies_ms": {**_latencies(), "reconciliation": 7.0},
        "unaccounted_calls": 0,
        "durable_credentials_found": 0,
        "broker_socket_inode_preserved": True,
        "host_process_preserved": True,
        "broker_process_preserved": True,
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
    }


def _bind_case(measured: dict[str, object], case_id: str) -> None:
    measured["case_id"] = case_id
    contract = aggregate.CASE_CONTRACTS[case_id]
    calls = measured["calls"]
    assert isinstance(calls, dict)
    for name, expected in (
        ("mcp", contract.expected_mcp_calls),
        ("provider", contract.expected_provider_calls),
    ):
        record = calls[name]
        assert isinstance(record, dict)
        record["expected"] = expected
        record["observed"] = expected
        if name == "provider":
            record["model_rounds"] = expected
            record["calls_per_task_operation"] = expected
            record["case_maximum"] = expected


def test_strict_producers_write_atomic_private_aggregator_artifacts(
    tmp_path: Path,
) -> None:
    run_dir = _run_dir(tmp_path)

    rows = [
        evidence.write_readiness_artifact(run_dir, _readiness()),
        evidence.write_smoke_evidence_artifact(run_dir, _smoke()),
        evidence.write_reconciliation_artifact(run_dir, _reconciliation()),
    ]

    assert [row["path"] for row in rows] == [
        "readiness.json",
        "smoke-evidence.json",
        "reconciliation.json",
    ]
    for row in rows:
        path = run_dir / row["path"]
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["schema"] == aggregate.REQUIRED_ARTIFACT_SCHEMAS[row["path"]]
        assert value["run_id"] == RUN_ID
        assert value["case_id"] == CASE_ID
        assert value["status"] == "PASS"
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert row["bytes"] == path.stat().st_size
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (
        json.loads((run_dir / "readiness.json").read_text())[
            "provider_completion_calls"
        ]
        == 0
    )
    assert (
        json.loads((run_dir / "smoke-evidence.json").read_text())["calls"] == _calls()
    )
    assert (
        json.loads((run_dir / "reconciliation.json").read_text())["unaccounted_calls"]
        == 0
    )
    assert not list(run_dir.glob(".*.tmp"))


@pytest.mark.parametrize(
    ("writer", "factory", "missing_key"),
    (
        (evidence.write_readiness_artifact, _readiness, "provider_completion_calls"),
        (evidence.write_smoke_evidence_artifact, _smoke, "calls"),
        (evidence.write_reconciliation_artifact, _reconciliation, "unaccounted_calls"),
    ),
)
def test_explicit_measured_fields_are_never_defaulted(
    tmp_path: Path,
    writer,
    factory,
    missing_key: str,  # type: ignore[no-untyped-def]
) -> None:
    measured = factory()
    measured.pop(missing_key)

    with pytest.raises(evidence.EvidenceArtifactError, match="field set is invalid"):
        writer(_run_dir(tmp_path), measured)


def test_readiness_requires_measured_zero_provider_completions_and_real_security(
    tmp_path: Path,
) -> None:
    measured = _readiness()
    measured["provider_completion_calls"] = 1
    with pytest.raises(evidence.EvidenceArtifactError, match="zero completions"):
        evidence.write_readiness_artifact(_run_dir(tmp_path / "calls"), measured)

    measured = _readiness()
    measured["security"]["network_internal"] = False  # type: ignore[index]
    with pytest.raises(evidence.EvidenceArtifactError, match="PASS readiness security"):
        evidence.write_readiness_artifact(_run_dir(tmp_path / "security"), measured)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (
            lambda value: value["joined_identities"].update(access_id_sha256="bad"),
            "SHA-256",
        ),
        (
            lambda value: value["latencies_ms"].update(runtime=True),
            "nonnegative number",
        ),
        (
            lambda value: value["calls"]["provider"].update(maximum_per_model_round=2),
            "model-round call policy",
        ),
        (
            lambda value: value["calls"]["provider"].update(automatic_retries=1),
            "PASS calls",
        ),
    ),
)
def test_smoke_rejects_invalid_join_latency_and_call_measurements(
    tmp_path: Path,
    mutation,
    match: str,  # type: ignore[no-untyped-def]
) -> None:
    measured = _smoke()
    mutation(measured)

    with pytest.raises(evidence.EvidenceArtifactError, match=match):
        evidence.write_smoke_evidence_artifact(_run_dir(tmp_path), measured)


def _provider_fault_smoke() -> dict[str, object]:
    measured = _smoke()
    measured["case_id"] = "U1-PROVIDER-DOWN"
    measured["calls"]["mcp"].update(expected=0, observed=0)  # type: ignore[index]
    measured["joined_identities"] = {name: None for name in HASHES}
    measured["context_tokens"] = 0
    measured["provider_terminal_status"] = "FAILED"
    measured["memory_route"] = "NONE"
    return measured


def test_provider_fault_pass_preserves_failed_terminal_and_nullable_native_join(
    tmp_path: Path,
) -> None:
    run_dir = _run_dir(tmp_path)

    row = evidence.write_smoke_evidence_artifact(run_dir, _provider_fault_smoke())
    written = json.loads((run_dir / row["path"]).read_text(encoding="utf-8"))

    assert written["status"] == "PASS"
    assert written["provider_terminal_status"] == "FAILED"
    assert written["joined_identities"]["provider_native_request_id_sha256"] is None
    assert written["calls"]["provider"]["observed"] == 1


def test_provider_fault_pass_rejects_a_fabricated_success_terminal(
    tmp_path: Path,
) -> None:
    measured = _provider_fault_smoke()
    measured["provider_terminal_status"] = "SUCCEEDED"

    with pytest.raises(evidence.EvidenceArtifactError, match="must be FAILED"):
        evidence.write_smoke_evidence_artifact(_run_dir(tmp_path), measured)


def test_reconciliation_requires_explicit_consistent_numeric_closure(
    tmp_path: Path,
) -> None:
    measured = _reconciliation()
    measured["status"] = "FAIL"
    measured["calls"]["mcp"]["unaccounted"] = 1  # type: ignore[index]
    with pytest.raises(evidence.EvidenceArtifactError, match="unaccounted_calls"):
        evidence.write_reconciliation_artifact(
            _run_dir(tmp_path / "unaccounted"), measured
        )

    measured = _reconciliation()
    measured["durable_credentials_found"] = 1
    with pytest.raises(evidence.EvidenceArtifactError, match="PASS reconciliation"):
        evidence.write_reconciliation_artifact(
            _run_dir(tmp_path / "credentials"), measured
        )


@pytest.mark.parametrize(
    ("case_id", "expected_changes"),
    (
        (
            "U1-BROKER-INODE-RECREATE",
            {
                "broker_socket_inode_preserved": False,
                "broker_process_preserved": False,
            },
        ),
        (
            "U1-ADAPTER-RESTART",
            {"host_process_preserved": False},
        ),
    ),
)
def test_reconciliation_accepts_only_the_contracted_lifecycle_replacement(
    tmp_path: Path,
    case_id: str,
    expected_changes: dict[str, bool],
) -> None:
    measured = _reconciliation()
    _bind_case(measured, case_id)
    measured.update(expected_changes)

    run_dir = _run_dir(tmp_path / case_id.lower())
    artifact = evidence.write_reconciliation_artifact(run_dir, measured)
    written = json.loads((run_dir / artifact["path"]).read_text())
    assert all(written[name] is value for name, value in expected_changes.items())

    unexpected = dict(measured)
    unexpected["existing_vllm_preserved"] = False
    with pytest.raises(evidence.EvidenceArtifactError, match="PASS reconciliation"):
        evidence.write_reconciliation_artifact(
            _run_dir(tmp_path / f"{case_id.lower()}-drift"), unexpected
        )


@pytest.mark.parametrize(
    ("case_id", "changes"),
    (
        ("U1-BROKER-INODE-RECREATE", {}),
        ("U1-BROKER-INODE-RECREATE", {"broker_socket_inode_preserved": False}),
        (
            "U1-BROKER-INODE-RECREATE",
            {
                "broker_socket_inode_preserved": False,
                "broker_process_preserved": False,
                "host_process_preserved": False,
            },
        ),
        ("U1-ADAPTER-RESTART", {}),
        (
            "U1-ADAPTER-RESTART",
            {
                "host_process_preserved": False,
                "broker_process_preserved": False,
            },
        ),
        (CASE_ID, {"host_process_preserved": False}),
    ),
)
def test_reconciliation_rejects_missing_or_extra_lifecycle_replacement(
    tmp_path: Path,
    case_id: str,
    changes: dict[str, bool],
) -> None:
    measured = _reconciliation()
    _bind_case(measured, case_id)
    measured.update(changes)

    with pytest.raises(evidence.EvidenceArtifactError, match="PASS reconciliation"):
        evidence.write_reconciliation_artifact(
            _run_dir(tmp_path / f"invalid-{case_id.lower()}-{len(changes)}"),
            measured,
        )


@pytest.mark.parametrize(
    "factory,writer",
    (
        (_readiness, evidence.write_readiness_artifact),
        (_smoke, evidence.write_smoke_evidence_artifact),
        (_reconciliation, evidence.write_reconciliation_artifact),
    ),
)
def test_secret_like_keys_or_values_are_rejected_before_persistence(
    tmp_path: Path,
    factory,
    writer,  # type: ignore[no-untyped-def]
) -> None:
    measured = factory()
    measured["api_token"] = "synthetic-secret-value"
    with pytest.raises(evidence.EvidenceArtifactError, match="secret-like"):
        writer(_run_dir(tmp_path / "key"), measured)

    measured = factory()
    measured["status"] = "Bearer synthetic-secret-value"
    with pytest.raises(evidence.EvidenceArtifactError, match="secret-like"):
        writer(_run_dir(tmp_path / "value"), measured)


def test_writer_rejects_relative_wrong_owner_mode_symlink_and_overwrite(
    tmp_path: Path,
) -> None:
    with pytest.raises(evidence.EvidenceArtifactError, match="absolute"):
        evidence.write_readiness_artifact(Path(RUN_ID), _readiness())

    wrong = tmp_path / "different-run"
    wrong.mkdir(mode=0o700)
    with pytest.raises(evidence.EvidenceArtifactError, match="run_id"):
        evidence.write_readiness_artifact(wrong, _readiness())

    permissive = _run_dir(tmp_path / "mode")
    permissive.chmod(0o755)
    with pytest.raises(evidence.EvidenceArtifactError, match="0700"):
        evidence.write_readiness_artifact(permissive, _readiness())

    real = _run_dir(tmp_path / "real")
    link = tmp_path / "link" / RUN_ID
    link.parent.mkdir()
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(evidence.EvidenceArtifactError, match="symlink"):
        evidence.write_readiness_artifact(link, _readiness())

    run_dir = _run_dir(tmp_path / "overwrite")
    target = run_dir / "readiness.json"
    target.write_text("preserve", encoding="utf-8")
    with pytest.raises(evidence.EvidenceArtifactError, match="already exists"):
        evidence.write_readiness_artifact(run_dir, _readiness())
    assert target.read_text(encoding="utf-8") == "preserve"

    symlink_run = _run_dir(tmp_path / "target-link")
    victim = tmp_path / "victim.json"
    victim.write_text("preserve", encoding="utf-8")
    (symlink_run / "readiness.json").symlink_to(victim)
    with pytest.raises(evidence.EvidenceArtifactError, match="already exists"):
        evidence.write_readiness_artifact(symlink_run, _readiness())
    assert victim.read_text(encoding="utf-8") == "preserve"


def test_input_is_normalized_once_and_caller_mutation_cannot_change_written_bytes(
    tmp_path: Path,
) -> None:
    measured = _smoke()
    run_dir = _run_dir(tmp_path)
    row = evidence.write_smoke_evidence_artifact(run_dir, measured)
    before = (run_dir / row["path"]).read_bytes()

    measured["context_tokens"] = 999
    measured["joined_identities"]["access_id_sha256"] = None  # type: ignore[index]

    assert (run_dir / row["path"]).read_bytes() == before
    assert json.loads(before)["context_tokens"] == 42


def test_explicit_nonpass_measurements_are_preserved_without_pass_promotion(
    tmp_path: Path,
) -> None:
    readiness = _readiness()
    readiness["status"] = "FAIL"
    readiness["components"]["host"] = "FAIL"  # type: ignore[index]
    readiness["security"]["status"] = "FAIL"  # type: ignore[index]
    readiness["security"]["network_internal"] = False  # type: ignore[index]

    smoke = _smoke()
    smoke["status"] = "FAIL"
    smoke["calls"]["provider"]["observed"] = 0  # type: ignore[index]
    smoke["joined_identities"] = {name: None for name in HASHES}
    smoke["context_tokens"] = 0
    smoke["provider_terminal_status"] = None
    smoke["worker_exit_code"] = 1
    smoke["memory_route"] = "TERMINAL"

    reconciliation = _reconciliation()
    reconciliation["status"] = "FAIL"
    reconciliation["calls"]["mcp"]["unaccounted"] = 1  # type: ignore[index]
    reconciliation["unaccounted_calls"] = 1
    reconciliation["durable_credentials_found"] = 1
    reconciliation["broker_process_preserved"] = False
    reconciliation["existing_vllm_preserved"] = False
    reconciliation["external_lifecycle_mutations"] = 1

    run_dirs = [
        _run_dir(tmp_path / "readiness"),
        _run_dir(tmp_path / "smoke"),
        _run_dir(tmp_path / "reconciliation"),
    ]
    rows = [
        evidence.write_readiness_artifact(run_dirs[0], readiness),
        evidence.write_smoke_evidence_artifact(run_dirs[1], smoke),
        evidence.write_reconciliation_artifact(run_dirs[2], reconciliation),
    ]

    for run_dir, row in zip(run_dirs, rows, strict=True):
        assert json.loads((run_dir / row["path"]).read_text())["status"] == "FAIL"
    assert (
        json.loads((run_dirs[2] / rows[2]["path"]).read_text())[
            "durable_credentials_found"
        ]
        == 1
    )
