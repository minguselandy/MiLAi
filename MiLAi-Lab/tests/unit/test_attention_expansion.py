import multiprocessing
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock

import pytest
from test_state_attention import fixture

from milai_lab.methods.attention_expansion import AttentionExpansion, RetrievedSources
from milai_lab.methods.state_attention import AttentionLimits
from milai_lab.methods.state_focus import SourceUnit


def capture(path, **changes):
    binding = dict(
        admission_sha256="a" * 64,
        execution_id="arm:1",
        task_id="task",
        scope="scope",
        question="question",
    )
    binding.update(changes)
    return AttentionExpansion(path, **binding)


def inputs(**changes):
    args = fixture(coverage="GAP")
    for key in ("task_id", "question", "expansion_attempts"):
        args.pop(key)
    args.update(before_dispatch=lambda: None, retrieve=lambda _: result())
    args.update(changes)
    return args


def result():
    return RetrievedSources((SourceUnit("d", "1", "scope", "new"),), "cost:1")


def test_capture_recovery_and_fresh_review(tmp_path):
    path = tmp_path / "attention.sqlite"
    journal = capture(path)

    def retrieve(intent):
        observer = capture(path)
        assert observer.receipt()["status"] == "DISPATCHING"
        assert observer.receipt()["dispatch_started"] is True
        observer.close()
        assert intent["query"] == "question"
        assert intent["exclude_source_ids"] == ["a", "b", "c"]
        intent["query"] = "mutated by backend"
        return result()

    args = inputs(retrieve=retrieve)
    decision, merged = journal.step(**args)
    assert decision["retrieval"]["query"] == "question"
    assert decision["action"] == "RETRIEVE_ONCE"  # Not Actor-ready context.
    assert [s.source_id for s in merged.units] == ["a", "b", "c", "d"]
    assert journal.receipt()["status"] == "COMPLETED"
    assert journal.receipt()["receipt_ref"] == "cost:1"
    assert journal.receipt()["external_usage"] == "UNKNOWN_UNTIL_JOINED_TO_GLOBAL_LEDGER"
    assert journal.receipt()["elapsed_seconds"] >= 0
    assert path.stat().st_mode & 0o777 == 0o600
    journal.close()
    journal = capture(path)
    assert journal.restored_snapshot() == merged
    forbidden = Mock(side_effect=AssertionError("no second dispatch"))
    args.update(snapshot=merged, retrieve=forbidden, before_dispatch=forbidden)
    stale, _ = journal.step(**args)
    assert stale["coverage"] == "UNKNOWN"
    args["state"] = replace(args["state"], snapshot_sha256=merged.sha256)
    args["coverage"] = replace(
        args["coverage"],
        snapshot_sha256=merged.sha256,
        state_sha256=args["state"].sha256,
        status="SUFFICIENT",
    )
    fresh, _ = journal.step(**args)
    assert (fresh["action"], fresh["coverage"]) == ("CONTEXT", "SUFFICIENT")
    forbidden.assert_not_called()
    journal.close()


@pytest.mark.parametrize("stage", ["before_dispatch", "retrieve"])
def test_failure_consumes_attempt_and_never_retries_after_recovery(tmp_path, stage):
    path = tmp_path / "attention.sqlite"
    journal = capture(path)
    args = inputs(**{stage: Mock(side_effect=RuntimeError("private message"))})
    with pytest.raises(RuntimeError):
        journal.step(**args)
    receipt = journal.receipt()
    assert receipt["status"] == "FAILED"
    assert receipt["dispatch_started"] == (stage == "retrieve")
    assert receipt["error_type"] == "RuntimeError"
    assert "private message" not in str(receipt)
    assert journal.restored_snapshot() is None
    journal.close()
    journal = capture(path)
    decision, _ = journal.step(**args)
    assert decision["reason"] == "EXPANSION_EXHAUSTED"
    args[stage].assert_called_once()
    journal.close()


def test_revocation_between_reservation_and_dispatch_cancels(tmp_path):
    journal = capture(tmp_path / "attention.sqlite")
    allowed = True

    def revoke():
        nonlocal allowed
        assert journal.receipt()["status"] == "RESERVED"
        allowed = False

    retrieve = Mock()
    decision, _ = journal.step(
        **inputs(
            check_source=lambda _: "ELIGIBLE" if allowed else "DENIED",
            before_dispatch=revoke,
            retrieve=retrieve,
        )
    )
    assert decision["retrieval"] is None
    assert journal.receipt()["status"] == "CANCELLED_PRE_DISPATCH"
    assert journal.receipt()["dispatch_started"] is False
    retrieve.assert_not_called()
    journal.close()


@pytest.mark.parametrize(
    "violation", ["count", "bytes", "excluded", "duplicate", "scope", "receipt", "revoked"]
)
def test_invalid_result_retains_failure_cost_join_and_consumes_attempt(tmp_path, violation):
    journal = capture(tmp_path / "attention.sqlite")
    returned = result()
    source = returned.sources[0]
    if violation == "count":
        returned = replace(
            returned, sources=tuple(replace(source, source_id=f"new{i}") for i in range(5))
        )
    elif violation == "bytes":
        returned = replace(returned, sources=(replace(source, content="é" * 32768),))
    elif violation == "excluded":
        returned = replace(returned, sources=(replace(source, source_id="a"),))
    elif violation == "duplicate":
        returned = replace(returned, sources=(source, source))
    elif violation == "scope":
        returned = replace(returned, sources=(replace(source, scope="other"),))
    elif violation == "receipt":
        returned = replace(returned, receipt_ref="")
    allowed = True

    def retrieve(_):
        nonlocal allowed
        allowed = violation != "revoked"
        return returned

    args = inputs(retrieve=retrieve, check_source=lambda _: "ELIGIBLE" if allowed else "DENIED")
    with pytest.raises(ValueError):
        journal.step(**args)
    row = journal.receipt()
    assert row["status"] == "FAILED"
    assert row["receipt_ref"] == (None if violation == "receipt" else "cost:1")
    assert "sources" not in row
    assert journal.restored_snapshot() is None
    assert journal.step(**args)[0]["retrieval"] is None
    journal.close()


def crash_after_dispatch(path):
    journal = capture(path)
    journal.step(**inputs(retrieve=lambda _: os._exit(17)))


def test_hard_process_exit_leaves_unknown_attempt_not_retry_permission(tmp_path):
    path = tmp_path / "attention.sqlite"
    process = multiprocessing.get_context("fork").Process(target=crash_after_dispatch, args=(path,))
    process.start()
    process.join(5)
    if process.is_alive():
        process.terminate()
        process.join(5)
        pytest.fail("capture subprocess did not finish")
    assert process.exitcode == 17
    journal = capture(path)
    row = journal.receipt()
    assert row["status"] == "DISPATCHING"
    assert row["elapsed_seconds"] is None
    assert row["external_usage"].startswith("UNKNOWN")
    forbidden = Mock(side_effect=AssertionError("no retry"))
    assert journal.step(**inputs(retrieve=forbidden))[0]["reason"] == "EXPANSION_EXHAUSTED"
    forbidden.assert_not_called()
    journal.close()


def test_concurrent_reservation_dispatches_once(tmp_path):
    path = tmp_path / "attention.sqlite"
    barrier = threading.Barrier(2)
    calls = []

    def run():
        journal = capture(path)
        observed = 0

        def eligible(_):
            nonlocal observed
            observed += 1
            if observed == 3:  # Both read no receipt before their initial decision.
                barrier.wait(timeout=5)
            return "ELIGIBLE"

        def retrieve(_):
            calls.append("dispatch")
            return result()

        try:
            return journal.step(**inputs(check_source=eligible, retrieve=retrieve))[0]["action"]
        finally:
            journal.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        actions = [f.result(timeout=10) for f in futures]
    assert calls == ["dispatch"]
    assert sorted(actions) == ["ABSTAIN_MEMORY", "RETRIEVE_ONCE"]


@pytest.mark.parametrize(
    "change",
    [
        {"admission_sha256": "b" * 64},
        {"execution_id": "arm:2"},
        {"task_id": "other"},
        {"scope": "other"},
        {"question": "other"},
        {"limits": AttentionLimits(max_sources=2)},
    ],
)
def test_identity_is_immutable(tmp_path, change):
    path = tmp_path / "attention.sqlite"
    capture(path).close()
    with pytest.raises(ValueError, match="BINDING_CHANGED"):
        capture(path, **change)
    capture(path).close()


def test_foreign_database_is_not_adopted(tmp_path):
    path = tmp_path / "foreign.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE foreign_data(value TEXT)")
    with pytest.raises(ValueError, match="DATABASE_NOT_OWNED"):
        capture(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("foreign_data",)
        ]


@pytest.mark.parametrize("conflict", [False, True])
def test_context_decisions_do_not_reserve_or_dispatch(tmp_path, conflict):
    journal = capture(tmp_path / "attention.sqlite")
    reviewed = fixture(conflict=conflict)
    forbidden = Mock(side_effect=AssertionError("not an expansion"))
    decision, _ = journal.step(
        **inputs(
            state=reviewed["state"],
            coverage=reviewed["coverage"],
            before_dispatch=forbidden,
            retrieve=forbidden,
        )
    )
    assert decision["action"] == "CONTEXT"
    assert journal.receipt() is None
    forbidden.assert_not_called()
    journal.close()
