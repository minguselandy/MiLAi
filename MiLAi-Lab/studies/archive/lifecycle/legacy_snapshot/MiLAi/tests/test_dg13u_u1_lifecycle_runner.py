from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import dg13u_u1_openworker as runner


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _paths(tmp_path: Path, run_id: str) -> runner.RunPaths:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    return runner.RunPaths(run_id, durable, temporary, uds)


def _coordinator(tmp_path: Path) -> runner.RecoveryPlanCoordinator:
    paths = _paths(tmp_path, "dg13u-u1-recovery-replace")
    coordinator = runner.RecoveryPlanCoordinator(
        paths.run_id,
        paths.durable,
        paths.temporary,
        paths.uds,
    )
    coordinator.sha256 = "a" * 64
    return coordinator


def _add_recovery_process(
    coordinator: runner.RecoveryPlanCoordinator,
    role: str = "mcp-broker",
    pid: int = 101,
    marker: str = "9001",
) -> None:
    coordinator._resources.append(
        {
            "kind": "process",
            "ownership": "RUN_OWNED",
            "role": role,
            "pid": pid,
            "proc_start_marker": marker,
        }
    )


def test_recovery_plan_replace_process_updates_exact_row_and_checkpoint_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _coordinator(tmp_path)
    _add_recovery_process(coordinator)
    calls: list[str | None] = []

    def checkpoint() -> None:
        calls.append(coordinator.sha256)
        coordinator.sha256 = "b" * 64

    monkeypatch.setattr(coordinator, "checkpoint", checkpoint)

    coordinator.replace_process("mcp-broker", 101, "9001", 202, "9002")

    process_rows = [
        row for row in coordinator._resources if row.get("kind") == "process"
    ]
    assert process_rows == [
        {
            "kind": "process",
            "ownership": "RUN_OWNED",
            "role": "mcp-broker",
            "pid": 202,
            "proc_start_marker": "9002",
        }
    ]
    assert calls == ["a" * 64]
    assert coordinator.sha256 == "b" * 64


@pytest.mark.parametrize(
    (
        "registered",
        "expected_pid",
        "expected_marker",
        "new_pid",
        "new_marker",
        "reason",
    ),
    [
        (False, 101, "9001", 202, "9002", "not registered exactly once"),
        (True, 999, "9001", 202, "9002", "generation CAS mismatch"),
        (True, 101, "9999", 202, "9002", "generation CAS mismatch"),
        (True, 101, "9001", 101, "9001", "generation is unchanged"),
    ],
)
def test_recovery_plan_replace_process_rejects_missing_wrong_or_unchanged(
    tmp_path: Path,
    registered: bool,
    expected_pid: int,
    expected_marker: str,
    new_pid: int,
    new_marker: str,
    reason: str,
) -> None:
    coordinator = _coordinator(tmp_path)
    if registered:
        _add_recovery_process(coordinator)
    before = copy.deepcopy(coordinator._resources)

    with pytest.raises(runner.RunError, match=reason):
        coordinator.replace_process(
            "mcp-broker",
            expected_pid,
            expected_marker,
            new_pid,
            new_marker,
        )

    assert coordinator._resources == before
    assert coordinator.sha256 == "a" * 64


def test_recovery_plan_replace_checkpoint_failure_rolls_back_row_and_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _coordinator(tmp_path)
    _add_recovery_process(coordinator, "host-adapter", 301, "7001")
    before = copy.deepcopy(coordinator._resources)

    def fail_checkpoint() -> None:
        coordinator.sha256 = "f" * 64
        raise runner.RunError("synthetic checkpoint failure")

    monkeypatch.setattr(coordinator, "checkpoint", fail_checkpoint)

    with pytest.raises(runner.RunError, match="synthetic checkpoint failure"):
        coordinator.replace_process("host-adapter", 301, "7001", 302, "7002")

    assert coordinator._resources == before
    assert coordinator.sha256 == "a" * 64


class _FailingRecovery:
    plan_path = Path("/tmp/dg13u-u1-never-read-plan.json")
    sha256 = "a" * 64

    def replace_process(self, *_args: object) -> None:
        raise RuntimeError("synthetic durable CAS failure")

    def binding(self) -> dict[str, str]:
        return {
            "schema": "synthetic",
            "path": str(self.plan_path),
            "sha256": self.sha256,
        }


def test_resource_registry_facade_uses_current_generation_and_stale_cleanup_is_noop() -> (
    None
):
    present = {("mcp-broker", 401, "8001")}
    cleaned: list[runner.ProcessGeneration] = []

    def cleanup(generation: runner.ProcessGeneration) -> None:
        cleaned.append(generation)
        present.discard((generation.role, generation.pid, generation.marker))

    def absent(generation: runner.ProcessGeneration) -> bool:
        return (generation.role, generation.pid, generation.marker) not in present

    registry = runner.ResourceRegistry("dg13u-u1-runner-generation")
    old = registry.register_process("mcp-broker", 401, "8001", cleanup, absent)
    stale = registry.snapshot()[0]
    present.remove((old.role, old.pid, old.marker))
    present.add(("mcp-broker", 402, "8002"))

    current = registry.replace_process(
        "mcp-broker",
        401,
        "8001",
        402,
        "8002",
        cleanup,
        absent,
    )

    assert current == runner.ProcessGeneration("mcp-broker", 402, "8002", 2)
    assert stale.cleanup is not None
    stale.cleanup()
    assert cleaned == []
    assert ("mcp-broker", 402, "8002") in present
    receipt = registry.cleanup_all()
    assert cleaned == [current]
    assert receipt["status"] == "PASS"
    assert receipt["items"] == [
        {
            "kind": "process",
            "identity": "process/mcp-broker:402",
            "ownership": "RUN_OWNED",
            "state": "removed",
        }
    ]


def test_resource_registry_facade_cas_failure_preserves_current_generation() -> None:
    registry = runner.ResourceRegistry(
        "dg13u-u1-runner-cas-fail",
        _FailingRecovery(),  # type: ignore[arg-type]
    )
    registry.register_process(
        "host-adapter",
        501,
        "8101",
        lambda _generation: None,
        lambda _generation: True,
    )

    with pytest.raises(runner.RunError, match="recovery process replacement failed"):
        registry.replace_process(
            "host-adapter",
            501,
            "8101",
            502,
            "8102",
            lambda _generation: None,
            lambda _generation: True,
        )

    current = runner.resource_registry.process_snapshot_by_role(registry.snapshot())
    assert current == {
        "host-adapter": runner.ProcessGeneration("host-adapter", 501, "8101", 1)
    }


def _vllm_identity(*, container_id: str = "vllm-current") -> dict[str, Any]:
    return {
        "endpoint": runner.VLLM_ORIGIN,
        "completion_calls": 0,
        "lifecycle_mutated": False,
        "container": {"id": container_id, "started_at": "2026-08-26T00:00:00Z"},
        "image": {"id": "sha256:image"},
        "model_byte_closure": {"sha256": "1" * 64},
        "tokenizer": {"sha256": "2" * 64},
        "tokenizer_config": {"sha256": "3" * 64},
        "chat_template": {"sha256": "4" * 64},
    }


def _broker_partial_measurement() -> dict[str, object]:
    scenario = runner.lifecycle_scenarios.scenario_for_case("U1-BROKER-INODE-RECREATE")
    return {
        "schema": runner.lifecycle_scenarios.MEASUREMENT_SCHEMA,
        "case_id": scenario.case_id,
        "execution_class": scenario.execution_class,
        "steps": [
            {
                "step_id": step.step_id,
                "status": "COMPLETED",
                "attempts": 1,
                "receipt_sha256": _hash(f"receipt:{step.step_id}"),
            }
            for step in scenario.steps[:-1]
        ],
        "mcp_calls": 0,
        "provider_calls": 0,
        "automatic_retries": 0,
        "readiness_calls": {"host_health": 0, "mcp_catalog": 1},
        "vllm": None,
        "cleanup": None,
        "identity": {
            "old_policy_sha256": _hash("policy"),
            "replacement_policy_sha256": _hash("policy"),
            "old_broker_process_sha256": _hash("broker-old"),
            "replacement_broker_process_sha256": _hash("broker-new"),
            "old_socket_identity_sha256": _hash("socket-old"),
            "old_worker_bind_identity_sha256": _hash("socket-old"),
            "replacement_socket_identity_sha256": _hash("socket-new"),
            "recreated_worker_bind_identity_sha256": _hash("socket-new"),
            "old_broker_stopped": True,
            "old_worker_bind_unavailable_after_stop": True,
            "old_worker_followed_replacement": False,
            "worker_recreated_and_remounted": True,
            "mcp_catalog_readiness_restored": True,
        },
    }


def _cleanup(paths: runner.RunPaths, *, state: str = "removed") -> dict[str, object]:
    return {
        "schema": "milai.dg13u.u1-cleanup-receipt.v1",
        "run_id": paths.run_id,
        "status": "PASS",
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
        "items": [
            {
                "kind": "process",
                "identity": "process/mcp-broker:202",
                "ownership": "RUN_OWNED",
                "state": state,
            },
            {
                "kind": "external_vllm",
                "identity": "127.0.0.1:7860",
                "ownership": "PRESERVED_EXTERNAL",
                "state": "preserved_external",
                "attempts": 0,
            },
        ],
    }


def test_lifecycle_finalizer_requires_persisted_pass_cleanup_and_is_not_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path, "dg13u-u1-lifecycle-final")
    vllm = _vllm_identity()
    finalizer = runner.LifecycleScenarioFinalizer(
        paths,
        "U1-BROKER-INODE-RECREATE",
        _broker_partial_measurement(),
        vllm,
    )
    cleanup = _cleanup(paths)
    monkeypatch.setattr(runner.u0, "_probe_vllm", lambda: copy.deepcopy(vllm))

    with pytest.raises(runner.RunError, match="not persisted"):
        finalizer.finalize(cleanup)
    runner._atomic_write(paths.durable / "cleanup-receipt.json", cleanup)
    evidence = finalizer.finalize(cleanup)

    assert evidence["status"] == "PASS"
    assert len(evidence["steps"]) == 8
    assert evidence["cleanup"]["run_owned_resources_absent"] is True
    assert evidence["vllm"]["lifecycle_attempts"] == 0
    assert (paths.durable / "lifecycle-evidence.json").is_file()
    with pytest.raises(runner.RunError, match="not repeatable"):
        finalizer.finalize(cleanup)


def test_lifecycle_finalizer_rejects_nonremoved_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path, "dg13u-u1-lifecycle-nonremoved")
    vllm = _vllm_identity()
    cleanup = _cleanup(paths, state="cleanup_failed")
    runner._atomic_write(paths.durable / "cleanup-receipt.json", cleanup)
    monkeypatch.setattr(runner.u0, "_probe_vllm", lambda: copy.deepcopy(vllm))
    finalizer = runner.LifecycleScenarioFinalizer(
        paths,
        "U1-BROKER-INODE-RECREATE",
        _broker_partial_measurement(),
        vllm,
    )

    with pytest.raises(runner.RunError, match="cleanup is incomplete"):
        finalizer.finalize(cleanup)


def test_lifecycle_finalizer_rejects_persisted_failed_cleanup_before_vllm_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path, "dg13u-u1-lifecycle-cleanup-fail")
    vllm = _vllm_identity()
    cleanup = {**_cleanup(paths), "status": "FAIL"}
    runner._atomic_write(paths.durable / "cleanup-receipt.json", cleanup)
    monkeypatch.setattr(
        runner.u0,
        "_probe_vllm",
        lambda: (_ for _ in ()).throw(AssertionError("vLLM probe must not run")),
    )
    finalizer = runner.LifecycleScenarioFinalizer(
        paths,
        "U1-BROKER-INODE-RECREATE",
        _broker_partial_measurement(),
        vllm,
    )

    with pytest.raises(runner.RunError, match="cleanup is incomplete"):
        finalizer.finalize(cleanup)


def test_lifecycle_finalizer_rejects_external_vllm_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path, "dg13u-u1-lifecycle-vllm-drift")
    initial = _vllm_identity()
    cleanup = _cleanup(paths)
    runner._atomic_write(paths.durable / "cleanup-receipt.json", cleanup)
    monkeypatch.setattr(
        runner.u0,
        "_probe_vllm",
        lambda: _vllm_identity(container_id="vllm-restarted"),
    )
    finalizer = runner.LifecycleScenarioFinalizer(
        paths,
        "U1-BROKER-INODE-RECREATE",
        _broker_partial_measurement(),
        initial,
    )

    with pytest.raises(runner.RunError, match="external vLLM identity changed"):
        finalizer.finalize(cleanup)


class _SnapshotRegistry:
    def __init__(self, role: str, pid: int, marker: str, generation: int) -> None:
        self.current = runner.ProcessGeneration(role, pid, marker, generation)

    def snapshot(self) -> tuple[runner.ResourceHandle, ...]:
        return (
            runner.ResourceHandle(
                "process",
                f"process/{self.current.role}:{self.current.pid}",
                runner.ResourceOwnership.RUN_OWNED,
                cleanup=lambda: None,
                absent=lambda: True,
                process_generation=self.current,
            ),
        )


def _broker_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stale_follows: bool = False
) -> runner.OpenWorkerU1Lifecycle:
    lifecycle = object.__new__(runner.OpenWorkerU1Lifecycle)
    lifecycle.paths = _paths(tmp_path, "dg13u-u1-broker-lifecycle")
    lifecycle.case = runner.CASES["U1-BROKER-INODE-RECREATE"]
    lifecycle.provider_ledger = lifecycle.paths.durable / "provider-ledger.jsonl"
    lifecycle.host_trace = lifecycle.paths.durable / "host-trace.jsonl"
    lifecycle.policy_path = lifecycle.paths.durable / "policy.json"
    lifecycle.provider_ledger.write_text("", encoding="utf-8")
    lifecycle.host_trace.write_text("", encoding="utf-8")
    lifecycle.policy_path.write_text("same-policy", encoding="utf-8")
    old_process = SimpleNamespace(pid=101)
    new_process = SimpleNamespace(pid=202)
    lifecycle.broker_process = old_process
    lifecycle.broker_marker = "9001"
    lifecycle.broker_generation = 1
    lifecycle.socket_identity = (10, 100)
    registry = _SnapshotRegistry("mcp-broker", 101, "9001", 1)
    lifecycle._resources = registry
    mounts = iter(
        [(10, 100), (20, 200), (20, 200)]
        if stale_follows
        else [(10, 100), (10, 100), (20, 200)]
    )
    workers = iter([_hash("worker-old"), _hash("worker-new")])
    unavailability = iter([True, True])
    monkeypatch.setattr(lifecycle, "_worker_mount_identity", lambda: next(mounts))
    monkeypatch.setattr(
        lifecycle, "_worker_process_identity_sha256", lambda: next(workers)
    )
    monkeypatch.setattr(
        lifecycle,
        "_stop_broker_for_replacement",
        lambda: (old_process, "9001"),
    )

    def start_replacement(
        _resources: object, _old: object, _marker: str
    ) -> tuple[int, int]:
        lifecycle.broker_process = new_process
        lifecycle.broker_marker = "9002"
        lifecycle.broker_generation = 2
        lifecycle.socket_identity = (20, 200)
        registry.current = runner.ProcessGeneration("mcp-broker", 202, "9002", 2)
        return (20, 200)

    monkeypatch.setattr(lifecycle, "_start_broker_replacement", start_replacement)
    monkeypatch.setattr(
        lifecycle,
        "_worker_bound_socket_unavailable",
        lambda: next(unavailability),
    )
    monkeypatch.setattr(lifecycle, "_recreate_worker", lambda: None)
    monkeypatch.setattr(lifecycle, "_wait_worker_health", lambda: _hash("health"))
    monkeypatch.setattr(lifecycle, "_mcp_catalog_readiness", lambda: _hash("catalog"))
    return lifecycle


def test_broker_lifecycle_smoke_records_exact_recreate_plan_and_current_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _broker_lifecycle(tmp_path, monkeypatch)

    evidence = lifecycle._smoke_broker_lifecycle()

    measurement = lifecycle.lifecycle_measurement
    assert len(measurement["steps"]) == 7
    assert [row["step_id"] for row in measurement["steps"]] == [
        step.step_id
        for step in runner.lifecycle_scenarios.scenario_for_case(
            lifecycle.case.case_id
        ).steps[:-1]
    ]
    assert measurement["mcp_calls"] == 0
    assert measurement["provider_calls"] == 0
    assert measurement["readiness_calls"] == {"host_health": 0, "mcp_catalog": 1}
    identity = measurement["identity"]
    assert (
        identity["old_socket_identity_sha256"]
        != identity["replacement_socket_identity_sha256"]
    )
    assert (
        identity["recreated_worker_bind_identity_sha256"]
        == identity["replacement_socket_identity_sha256"]
    )
    assert evidence["observed_mcp_calls"] == 0
    assert evidence["observed_provider_calls"] == 0
    current = runner.resource_registry.process_snapshot_by_role(
        lifecycle._resources.snapshot()
    )
    assert current["mcp-broker"].generation == 2


def test_broker_lifecycle_rejects_old_worker_silently_following_new_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _broker_lifecycle(tmp_path, monkeypatch, stale_follows=True)

    with pytest.raises(runner.RunError, match="silently followed"):
        lifecycle._smoke_broker_lifecycle()


def _exact_turn(
    run_id: str,
    index: int,
    *,
    session_sha256: str,
    task_sha256: str,
    slot_key: str,
    retained_slot_present: bool,
) -> dict[str, Any]:
    return {
        "known_sessions": {"A": "session-A"},
        "ledger": [{"logical_request_id": f"{run_id}-ow-{index:02d}"}],
        "logical_request_id": f"{run_id}-ow-{index:02d}",
        "native_request_id": f"native-{index}",
        "access_outcome": {"status": "CONTEXT_READY_CURRENT"},
        "recall_execution_trace": {"terminal_route": "L0"},
        "trace_id": f"trace-{index}",
        "session_sha256": session_sha256,
        "task_sha256": task_sha256,
        "operation_sha256": _hash(f"operation-{index}"),
        "slot_key": slot_key,
        "context_sha256": _hash(f"context-{index}"),
        "task_relation": "TASK_START",
        "prepare_status": "READY",
        "route": "EXACT",
        "compiled_memory_tokens": 40 + index,
        "current_state_status": "HIT",
        "current_state_claim_count": 1,
        "registry_revision_before": 0,
        "retained_slot_present": retained_slot_present,
        "output_sha256": _hash(f"output-{index}"),
        "output_bytes": 10 + index,
        "latencies_ms": {
            "openworker": 1.0,
            "adapter": 2.0,
            "mcp": 3.0,
            "runtime": 4.0,
            "compile": 5.0,
            "provider": 6.0,
        },
    }


def _adapter_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reuse_cache: bool = False,
) -> runner.OpenWorkerU1Lifecycle:
    lifecycle = object.__new__(runner.OpenWorkerU1Lifecycle)
    lifecycle.paths = _paths(tmp_path, "dg13u-u1-adapter-lifecycle")
    lifecycle.case = runner.CASES["U1-ADAPTER-RESTART"]
    lifecycle.provider_ledger = lifecycle.paths.durable / "provider-ledger.jsonl"
    lifecycle.host_trace = lifecycle.paths.durable / "host-trace.jsonl"
    lifecycle.provider_ledger.write_text("", encoding="utf-8")
    lifecycle.host_trace.write_text("", encoding="utf-8")
    lifecycle.gateway = "172.30.0.1"
    lifecycle.host_port = 49152
    lifecycle.host_generation = 1
    old_process = SimpleNamespace(pid=301)
    new_process = SimpleNamespace(pid=302)
    lifecycle.host_process = old_process
    lifecycle.host_marker = "7001"
    registry = _SnapshotRegistry("host-adapter", 301, "7001", 1)
    lifecycle._resources = registry
    worker_identity = _hash("same-openworker")
    monkeypatch.setattr(
        lifecycle, "_worker_process_identity_sha256", lambda: worker_identity
    )
    monkeypatch.setattr(
        lifecycle,
        "_stop_host_for_replacement",
        lambda: (old_process, "7001"),
    )
    replacement_trace = lifecycle.paths.durable / "host-trace.g2.jsonl"
    replacement_trace.write_text("", encoding="utf-8")

    def start_replacement(_resources: object, _old: object, _marker: str) -> Path:
        lifecycle.host_process = new_process
        lifecycle.host_marker = "7002"
        lifecycle.host_generation = 2
        lifecycle.host_trace = replacement_trace
        registry.current = runner.ProcessGeneration("host-adapter", 302, "7002", 2)
        return replacement_trace

    monkeypatch.setattr(lifecycle, "_start_host_replacement", start_replacement)
    monkeypatch.setattr(lifecycle, "_wait_host_ready", lambda: None)
    session_sha256 = _hash("session-A")
    task_sha256 = _hash("task-A")
    warm = _exact_turn(
        lifecycle.paths.run_id,
        1,
        session_sha256=session_sha256,
        task_sha256=task_sha256,
        slot_key=_hash("slot-old"),
        retained_slot_present=False,
    )
    continuation = _exact_turn(
        lifecycle.paths.run_id,
        2,
        session_sha256=session_sha256,
        task_sha256=task_sha256,
        slot_key=_hash("slot-old" if reuse_cache else "slot-new"),
        retained_slot_present=reuse_cache,
    )
    turns: list[dict[str, Any]] = [warm, continuation]

    def execute(turn: Any, **kwargs: Any) -> dict[str, Any]:
        expected_index = len(turns) - 1
        assert kwargs["expected_relation"] == "TASK_START"
        if expected_index == 1:
            assert turn.session_action == "NEW"
            assert kwargs["known_sessions"] == {}
        else:
            assert turn.session_action == "CONTINUE"
            assert kwargs["known_sessions"] == {"A": "session-A"}
        return turns.pop(0)

    monkeypatch.setattr(lifecycle, "_execute_lifecycle_exact_turn", execute)
    return lifecycle


def test_adapter_lifecycle_smoke_restarts_task_exact_and_preserves_joined_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _adapter_lifecycle(tmp_path, monkeypatch)

    evidence = lifecycle._smoke_adapter_lifecycle()

    measurement = lifecycle.lifecycle_measurement
    assert len(measurement["steps"]) == 7
    identity = measurement["identity"]
    assert (
        identity["warm_task_session_sha256"]
        == identity["continuation_task_session_sha256"]
    )
    assert identity["warm_task_id_sha256"] == identity["continuation_task_id_sha256"]
    assert identity["warm_task_relation"] == "TASK_START"
    assert identity["continuation_task_relation"] == "TASK_START"
    assert identity["warm_prepare_status"] == "READY"
    assert identity["continuation_prepare_status"] == "READY"
    assert identity["warm_route"] == "EXACT"
    assert identity["continuation_route"] == "EXACT"
    assert identity["old_cache_slot_reused"] is False
    assert evidence["observed_mcp_calls"] == 2
    assert evidence["observed_provider_calls"] == 2
    assert evidence["context_tokens"] > 0
    assert evidence["context_in_prompt"] is True
    assert evidence["access_id_sha256"] == lifecycle._scenario_digest(
        [
            f"{lifecycle.paths.run_id}-ow-01",
            f"{lifecycle.paths.run_id}-ow-02",
        ]
    )
    assert all(
        isinstance(evidence[name], str) and len(evidence[name]) == 64
        for name in (
            "access_id_sha256",
            "mcp_receipt_sha256",
            "runtime_trace_sha256",
            "trace_id_sha256",
            "native_request_id_sha256",
        )
    )
    assert set(evidence["latencies_ms"]) == {
        "openworker",
        "adapter",
        "mcp",
        "runtime",
        "compile",
        "provider",
    }
    assert evidence["latencies_ms"] == {
        "openworker": 2.0,
        "adapter": 4.0,
        "mcp": 6.0,
        "runtime": 8.0,
        "compile": 10.0,
        "provider": 12.0,
    }


def test_adapter_lifecycle_rejects_replacement_host_cache_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _adapter_lifecycle(tmp_path, monkeypatch, reuse_cache=True)

    with pytest.raises(runner.RunError, match="reused old task cache"):
        lifecycle._smoke_adapter_lifecycle()
