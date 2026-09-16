from __future__ import annotations

from pathlib import Path

import evals.ml_closure.longmemeval_contexts as context_runner
from evals.ml_closure.longmemeval_contexts import (
    ContextExecutionSpec,
    _case_snapshot_identity,
    _valid_checkpoint,
    _wait_for_namespace_cleanup,
    run_context_shard,
)
from evals.ml_closure.longmemeval_contract import (
    SCHEMA_VERSION,
    STATEFUL_SHARDS,
    atomic_json,
    case_seed,
    history_events,
    padded_source_ref,
    parse_source_ref,
    runtime_case_id,
    shard_case_ids,
    smoke_case_ids,
)
from evals.ml_closure.longmemeval_providers import (
    _cell_key,
    _official_prompt_function,
    _records_digest,
)
from evals.paper.datasets.longmemeval import (
    LongMemEvalCase,
    LongMemEvalSession,
    LongMemEvalTurn,
)


def _case(case_id: str) -> LongMemEvalCase:
    return LongMemEvalCase(
        source_id=case_id,
        category="single-session-user",
        question="What is the private target?",
        question_at="2025/01/02 (Thu) 12:00",
        sessions=(
            LongMemEvalSession(
                session_id=f"session-{case_id}",
                observed_at="2025/01/01 (Wed) 12:00",
                turns=(
                    LongMemEvalTurn("user", "I prefer tea."),
                    LongMemEvalTurn("assistant", "Understood."),
                ),
            ),
        ),
    )


def test_history_boundary_contains_only_turn_inputs() -> None:
    events = history_events(_case("case-1"))

    assert len(events) == 2
    assert all("question" not in event.canonical() for event in events)
    assert [event.role for event in events] == ["user", "assistant"]


def test_history_encoding_omits_empty_turns_and_preserves_nonempty_turn() -> None:
    case = LongMemEvalCase(
        source_id="case-chunks",
        category="single-session-user",
        question="What was retained?",
        question_at="2025/01/02 (Thu) 12:00",
        sessions=(
            LongMemEvalSession(
                session_id="session-chunks",
                observed_at="2025/01/01 (Wed) 12:00",
                turns=(
                    LongMemEvalTurn("user", ""),
                    LongMemEvalTurn("assistant", "界" * 30_000),
                ),
            ),
        ),
    )

    events = history_events(case)

    assert len(events) == 1
    assert events[0].turn_ordinal == 1
    assert events[0].content == "界" * 30_000


def test_padded_source_refs_preserve_numeric_order_and_round_trip() -> None:
    event = history_events(_case("case/with space"))[0]
    value = padded_source_ref(event)

    assert "/session/0000/" in value
    assert "/turn/0000?" in value
    assert parse_source_ref(value) == {
        "case_id": runtime_case_id("case/with space"),
        "session_ordinal": 0,
        "session_id": "session-case/with space",
        "turn_ordinal": 0,
        "chunk_ordinal": 0,
    }


def test_runtime_case_identity_removes_benchmark_markers() -> None:
    value = runtime_case_id("public-case_abs")

    assert value == runtime_case_id("public-case_abs")
    assert "public-case" not in value
    assert "abs" not in value


def test_namespace_cleanup_barrier_waits_for_purge_and_primary_terminal() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.calls = 0

        def cleanup_status(self, *, offset: int, limit: int):  # type: ignore[no-untyped-def]
            assert offset == 0
            assert limit == 1
            self.calls += 1
            completed = 2 if self.calls == 2 else 0
            return {
                "accepted_count": 2,
                "failed_count": 0,
                "projection_purged_count": completed,
                "primary_bytes_terminal_count": completed,
                "primary_bytes_erased_count": completed,
            }

    adapter = _Adapter()
    terminal = _wait_for_namespace_cleanup(
        adapter,  # type: ignore[arg-type]
        {"cleanup_accepted": True, "accepted_count": 2},
        timeout_ms=1_000,
        poll_interval_ms=0,
    )

    assert adapter.calls == 2
    assert terminal["cleanup_terminal"] is True
    assert terminal["projection_purged_count"] == 2
    assert terminal["primary_bytes_terminal_count"] == 2
    assert terminal["primary_bytes_erased_count"] == 2


def test_v03_snapshot_binds_receipts_and_one_raw_formed_resolve() -> None:
    snapshot = _case_snapshot_identity(
        project_id="project-1",
        receipts=(
            {
                "evidence_id": "evidence-1",
                "outbox_id": "outbox-1",
                "source_ref": "source-1",
            },
        ),
        finalize={"target_watermark": 7},
        raw_resolve={
            "canonical_position": {"evidence_watermark": 7},
            "search_trace": {
                "formation_projection": {
                    "status": "NO_MATCH",
                    "source_snapshot_digest": "a" * 64,
                    "source_watermark_digest": "b" * 64,
                    "access_snapshot_digest": "c" * 64,
                }
            },
        },
        formation_mode="CANARY",
    )

    assert snapshot["watermark_identity_exact"] is True
    assert snapshot["raw_baseline_and_formation_single_resolve"] is True
    assert len(str(snapshot["identity_sha256"])) == 64


def test_shard_terminal_cleanup_requires_bound_protocol_amendment() -> None:
    try:
        ContextExecutionSpec(
            shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
            cleanup_barrier_timeout_ms=120_000,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unbound shard-terminal cleanup protocol was accepted")


def test_v03_checkpoint_recovery_reuses_only_successes(tmp_path: Path) -> None:
    path = tmp_path / "case-1.json"
    record = {
        "schema": f"{SCHEMA_VERSION}.context-terminal",
        "arm": "MLR01-F",
        "case_id": "case-1",
        "run_lock_digest": "r" * 64,
        "shard_lifecycle_mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
        "protocol_amendment_digest": "a" * 64,
        "terminal_status": "FAILED",
    }
    atomic_json(path, record)

    failed = _valid_checkpoint(
        path,
        arm="MLR01-F",
        case_id="case-1",
        run_lock_digest="r" * 64,
        shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
        protocol_amendment_digest="a" * 64,
    )

    assert failed is None
    record["terminal_status"] = "SUCCEEDED"
    atomic_json(path, record)
    succeeded = _valid_checkpoint(
        path,
        arm="MLR01-F",
        case_id="case-1",
        run_lock_digest="r" * 64,
        shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
        protocol_amendment_digest="a" * 64,
    )
    assert succeeded is not None


def test_resumed_shard_uses_technical_cleanup_without_repeating_case(
    tmp_path: Path, monkeypatch: object
) -> None:
    case = _case("case-resumed")
    spec = ContextExecutionSpec(
        run_id="run-resumed",
        checkpoint_root=tmp_path,
        arms=("MLR01-F",),
        arm_modes=(("MLR01-F", "CANARY"),),
        run_lock_digest="r" * 64,
        stateful_shards=1,
        cleanup_barrier_timeout_ms=300_000,
        shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
        protocol_amendment_digest="a" * 64,
    )
    checkpoint = (
        tmp_path
        / "r2-b-v03"
        / "contexts"
        / "MLR01-F"
        / "case-resumed.json"
    )
    atomic_json(
        checkpoint,
        {
            "schema": f"{SCHEMA_VERSION}.context-terminal",
            "arm": "MLR01-F",
            "case_id": case.source_id,
            "run_lock_digest": "r" * 64,
            "shard_lifecycle_mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
            "protocol_amendment_digest": "a" * 64,
            "terminal_status": "SUCCEEDED",
        },
    )

    starts: list[str] = []

    class _Session:
        def __init__(self, *, output_root: Path, **_kwargs: object) -> None:
            self.output_root = output_root

        def start(self, run_id: str):  # type: ignore[no-untyped-def]
            starts.append(run_id)
            return {"status": "STARTED", "database": "fresh-test-database"}

        def worker_status(self):  # type: ignore[no-untyped-def]
            return {"status": "RUNNING", "worker_starts": 1}

        def projection_metrics(self):  # type: ignore[no-untyped-def]
            return {"deliveries": [], "watermarks": {}}

        def close(self):  # type: ignore[no-untyped-def]
            return {"status": "PASS", "database": "fresh-test-database"}

    monkeypatch.setattr(  # type: ignore[attr-defined]
        context_runner, "load_inputs", lambda _path: ("test", (case,))
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        context_runner, "LocalDG15RuntimeSession", _Session
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        context_runner,
        "_technical_shard_cleanup_witness",
        lambda **_kwargs: {
            "status": "PASS",
            "technical_witness": True,
            "benchmark_denominator_effect": 0,
        },
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        context_runner,
        "_run_case",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("successful benchmark checkpoint was repeated")
        ),
    )

    terminal = run_context_shard(
        phase="r2-b-v03",
        arm="MLR01-F",
        shard=0,
        requested_case_ids=(case.source_id,),
        require_lock=False,
        spec=spec,
    )

    assert starts == ["run-resumed-MLR01-F-shard-0"]
    assert terminal["resumed"] == 1
    assert terminal["succeeded"] == 1
    assert terminal["shard_cleanup_witness"] == {
        "status": "PASS",
        "technical_witness": True,
        "benchmark_denominator_effect": 0,
    }


def test_smoke_selection_is_one_case_per_frozen_shard() -> None:
    cases = tuple(_case(f"case-{index:03d}") for index in range(20))
    selected = smoke_case_ids(cases)

    assert len(selected) == STATEFUL_SHARDS
    assert len(set(selected)) == STATEFUL_SHARDS
    for shard, case_id in enumerate(selected):
        assert case_id in shard_case_ids(cases, shard)


def test_provider_seeds_are_arm_independent_and_lane_separated() -> None:
    assert case_seed("case-1", "answer") == case_seed("case-1", "answer")
    assert case_seed("case-1", "answer") != case_seed("case-1", "judge")


def test_provider_completion_identity_uses_each_pending_cell() -> None:
    assert _cell_key({"case_id": "case-1", "arm": "LME-R"}) == (
        "case-1",
        "LME-R",
    )
    assert _cell_key({"case_id": "case-1", "arm": "LME-C"}) == (
        "case-1",
        "LME-C",
    )


def test_provider_terminal_digest_is_schedule_independent() -> None:
    raw = {"case_id": "case-1", "arm": "LME-R", "value": 1}
    candidate = {"case_id": "case-1", "arm": "LME-C", "value": 2}

    assert _records_digest([raw, candidate]) == _records_digest([candidate, raw])


def test_official_prompt_function_is_executed_from_upstream_source() -> None:
    prompt = _official_prompt_function()(
        "single-session-user",
        "What drink?",
        "tea",
        "The user prefers tea.",
        abstention=False,
    )

    assert "Correct Answer: tea" in prompt
    assert prompt.endswith("Answer yes or no only.")
