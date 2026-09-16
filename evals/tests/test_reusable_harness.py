from __future__ import annotations

from pathlib import Path

import pytest

from evals.harness import (
    ArtifactCache,
    BoundedLeasePool,
    BuildReceipt,
    CheckpointLedger,
    CheckpointRecord,
    EvaluationResourceProvisioner,
    EvaluationRuntimeLease,
    HistoryItem,
    OneBuildManyQuestionPlan,
    TemporaryResourceSpec,
    WorkloadHistory,
    WorkloadQuestion,
    seeded_counterbalanced_schedule,
)


def _history() -> WorkloadHistory:
    return WorkloadHistory(
        "workload",
        "SYNTHETIC",
        (HistoryItem("item", "session", "user", "memory"),),
    )


def _lease(name: str, closed: list[str]) -> EvaluationRuntimeLease:
    return EvaluationRuntimeLease(
        name,
        Path(f"/tmp/{name}.sock"),
        "a" * 64,
        lambda history: BuildReceipt(history.fingerprint, "READY", 1, {}),
        lambda: closed.append(name),
    )


def test_one_build_many_question_plan_preserves_question_order() -> None:
    history = _history()
    questions = tuple(
        WorkloadQuestion(f"q-{index}", history.workload_id, f"query {index}")
        for index in range(3)
    )

    plan = OneBuildManyQuestionPlan.create(history, questions)

    assert plan.workload.fingerprint == history.fingerprint
    assert [question.question_id for question in plan.questions] == [
        "q-0",
        "q-1",
        "q-2",
    ]


def test_temporary_resource_provisioner_closes_and_destroys_exact_resource(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    closed: list[str] = []
    spec = TemporaryResourceSpec(
        "lease-1",
        "milai_eval_lease_1",
        tmp_path / "lease-1" / "blobs",
        tmp_path / "lease-1",
    )
    provisioner = EvaluationResourceProvisioner(
        lambda value: (
            events.append(f"create:{value.lease_id}") or _lease(value.lease_id, closed)
        ),
        lambda value: events.append(f"destroy:{value.lease_id}"),
    )

    with provisioner.provision(spec) as lease:
        assert lease.lease_id == "lease-1"

    assert events == ["create:lease-1", "destroy:lease-1"]
    assert closed == ["lease-1"]


def test_temporary_resource_spec_rejects_broad_or_unmarked_targets(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="temporary prefix"):
        TemporaryResourceSpec(
            "lease", "production", tmp_path / "x" / "blobs", tmp_path / "x"
        )
    with pytest.raises(ValueError, match="inside"):
        TemporaryResourceSpec("lease", "milai_eval_x", tmp_path, tmp_path)


def test_bounded_pool_reuses_only_declared_capacity() -> None:
    closed: list[str] = []
    leases = [_lease(f"lease-{index}", closed) for index in range(3)]
    pool = BoundedLeasePool(leases, capacity=2)

    with pool.acquire() as first, pool.acquire() as second:
        assert {first.lease_id, second.lease_id} == {"lease-0", "lease-1"}
    with pool.acquire() as reused:
        assert reused.lease_id in {"lease-0", "lease-1"}
    pool.close()

    assert closed == ["lease-0", "lease-1"]


def test_public_artifact_cache_round_trips_bounded_json(tmp_path: Path) -> None:
    cache = ArtifactCache(tmp_path / "cache")

    path = cache.put("case-1", {"score": 1}, classification="DEIDENTIFIED")

    assert path.stat().st_mode & 0o777 == 0o600
    assert cache.get("case-1") == {"score": 1}
    assert cache.get("missing") is None


def test_seeded_schedule_is_reproducible_and_rotates_first_method() -> None:
    first = seeded_counterbalanced_schedule(
        ["case-1", "case-2", "case-3"], ["A", "B", "C"], seed=17
    )
    second = seeded_counterbalanced_schedule(
        ["case-1", "case-2", "case-3"], ["A", "B", "C"], seed=17
    )

    assert first == second
    assert len({row.method_order[0] for row in first}) == 3


def test_checkpoint_resume_and_terminal_accounting_include_failures(
    tmp_path: Path,
) -> None:
    ledger = CheckpointLedger(tmp_path / "checkpoint.jsonl")
    ledger.append(CheckpointRecord("case-1:A", "PASS", "one.json", None))
    ledger.append(CheckpointRecord("case-2:A", "FAIL", None, "TIMEOUT"))

    accounting = ledger.terminal_accounting(["case-1:A", "case-2:A", "case-3:A"])

    assert accounting == {
        "expected": 3,
        "passed": 1,
        "failed": 1,
        "missing": ["case-3:A"],
    }
