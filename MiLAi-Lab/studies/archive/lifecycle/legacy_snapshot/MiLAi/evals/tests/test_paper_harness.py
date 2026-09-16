from __future__ import annotations

import array
import base64
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import numpy as np
import pytest

from evals.datasets import retrieval_query, runtime_safe_text
from evals.paper.adapters import (
    DenseAdapter,
    FullHistoryAdapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
    OracleAdapter,
)
from evals.paper.answer_runner import (
    AnswerCompletion,
    PaperAnswerRunner,
    PreparedAnswer,
)
from evals.paper.archive import ArchiveError, scan_archive
from evals.paper.contracts import (
    CapabilityStatus,
    MemoryEvent,
    read_context_archive,
)
from evals.paper.datasets import memora as memora_dataset
from evals.paper.datasets.extended import (
    ExtendedSession,
    ExtendedTurn,
    load_horizon_inputs,
)
from evals.paper.datasets.longmemeval import (
    labels_from_dataset,
    pseudonymize_session_id,
)
from evals.paper.judge_provider import JudgeCompletion, PreparedJudge, messages
from evals.paper.lme_v2_adapter import (
    LMEV2AdapterError,
    MiLAiLMEV2Memory,
    RuntimeRequest,
    RuntimeResult,
    memory_context_identity,
    official_contract_identity,
)
from evals.paper.pe06_finalize import (
    DEFAULT_RESULT as PE06_RESULT,
)
from evals.paper.pe06_finalize import (
    _validate_failure as validate_pe06_failure,
)
from evals.paper.pe06_finalize import (
    _validate_result as validate_pe06_result,
)
from evals.paper.pe06_native_finalize import validate_native_gate
from evals.paper.prepare_extended_inputs import (
    BEAM_CATEGORIES,
    build_beam_inputs,
    build_cupid_inputs,
    build_horizon_inputs,
)
from evals.paper.runners import memora as memora_runner
from evals.paper.runners import milai_contexts as milai_context_runner
from evals.paper.runners.beam_dense_contexts import (
    BeamDenseContextError,
    _official_pair_chunks,
)
from evals.paper.runners.beam_dense_contexts import (
    _fit_prefix as fit_beam_dense_prefix,
)
from evals.paper.runners.longmemeval import (
    LongMemEvalRunnerError,
    _write_generation_once,
)
from evals.paper.runners.memora_judge import MemoraJudgeRunner
from evals.paper.runners.milai_contexts import (
    MiLAiContextError,
    _CountingEmbeddingProvider,
    _EmbeddingCallCounter,
)
from evals.paper.runners.milai_contexts import run as run_milai_contexts
from evals.paper.scorers.horizon import aggregate as aggregate_horizon
from evals.paper.scorers.horizon import extract_letter as extract_horizon_letter
from evals.paper.scorers.memora import (
    MemoraCriterion,
    aggregate_judgments,
    fama_score,
)
from evals.paper.services.controller_gateway import (
    ControllerGateway,
    ControllerGatewayError,
)
from evals.paper.services.embedding_server import (
    MODEL_ALIAS as PAPER_EMBEDDING_MODEL,
)
from evals.paper.services.embedding_server import (
    EmbeddingServerError,
    EmbeddingService,
)
from evals.paper.usage_ledger import LedgerError, UsageLedger


def _event(
    event_id: str,
    content: str,
    *,
    session_id: str = "session-1",
    actor: str = "user",
    observed_at: str = "2026-08-01T00:00:00Z",
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        content=content,
        observed_at=observed_at,
        actor=actor,
        scope="paper-smoke",
        metadata={"session_id": session_id},
    )


def _lme_v2_trajectory(
    root: Path,
    trajectory_id: str,
    *,
    goal: str = "Configure the backup vault",
    tree: str = "button 'Save'\ncombobox 'Vault Alpha'",
) -> dict[str, object]:
    screenshot = Path("screenshots") / trajectory_id / "0000.png"
    path = root / screenshot
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-png-fixture-" + trajectory_id.encode())
    return {
        "id": trajectory_id,
        "domain": "web",
        "environment": "synthetic-settings",
        "goal": goal,
        "outcome": "success",
        "start_url": "https://synthetic.invalid/settings",
        "states": [
            {
                "state_index": 0,
                "step": 7,
                "url": "https://synthetic.invalid/settings/backup",
                "action": "Click Save",
                "thought": "Confirm the selected vault",
                "accessibility_tree": tree,
                "screenshot": str(screenshot),
            }
        ],
    }


def test_adapter_contract_rejects_label_leakage() -> None:
    with pytest.raises(ValueError, match="scorer labels"):
        MemoryEvent(
            event_id="event-1",
            content="content",
            observed_at="2026-08-01T00:00:00Z",
            actor="user",
            scope="paper-smoke",
            metadata={"answer_session_ids": ["session-1"]},
        )


def test_official_bm25_session_query_and_revoke() -> None:
    adapter = OfficialBM25Adapter(granularity="session", top_k=1)
    adapter.reset("paper-smoke", "case-1")
    adapter.ingest(_event("turn-1", "red bicycle", session_id="session-a"))
    adapter.ingest(_event("turn-2", "blue kayak", session_id="session-b"))
    adapter.ingest(
        _event(
            "turn-3",
            "The blue kayak is ready.",
            session_id="session-b",
            actor="assistant",
        )
    )
    adapter.finalize()
    result = adapter.query("blue kayak", "2026-08-02T00:00:00Z", 20, "CONTROLLED")
    assert result.source_ids == ("session-b",)
    assert "Session Date: 2026-08-01T00:00:00Z" in result.context
    assert "assistant: The blue kayak is ready." in result.context
    assert result.usage["documents_scored"] == 2
    assert adapter.revoke("turn-2") is CapabilityStatus.SUPPORTED
    result = adapter.query("blue kayak", "2026-08-02T00:00:00Z", 20, "CONTROLLED")
    assert result.source_ids == ("session-a",)


def test_bm25_ranks_then_renders_selected_context_chronologically() -> None:
    adapter = OfficialBM25Adapter(granularity="session", top_k=2)
    adapter.reset("paper-smoke", "case-1")
    adapter.ingest(
        _event(
            "newer",
            "target target",
            session_id="session-newer",
            observed_at="2026-08-02T00:00:00Z",
        )
    )
    adapter.ingest(
        _event(
            "distractor",
            "unrelated",
            session_id="session-distractor",
            observed_at="2026-07-31T00:00:00Z",
        )
    )
    adapter.ingest(
        _event(
            "older",
            "different",
            session_id="session-older",
            observed_at="2026-08-01T00:00:00Z",
        )
    )
    adapter.finalize()
    result = adapter.query("target", "2026-08-03T00:00:00Z", 100, "CONTROLLED")
    assert result.source_ids == ("session-newer", "session-older")
    assert result.context.index("2026-08-01") < result.context.index("2026-08-02")


def test_no_memory_and_full_history_budget_behavior() -> None:
    none = NoMemoryAdapter()
    none.reset("paper-smoke", "case-1")
    none.finalize()
    assert none.query("question", "now", 0, "CONTROLLED").context == ""

    full = FullHistoryAdapter(truncate=False)
    full.reset("paper-smoke", "case-1")
    full.ingest(_event("event-1", "one two three"))
    full.finalize()
    with pytest.raises(ValueError, match="exceeds"):
        full.query("question", "now", 2, "LONG_CONTEXT")

    truncated = FullHistoryAdapter(truncate=True)
    truncated.reset("paper-smoke", "case-1")
    truncated.ingest(_event("event-1", "one two three"))
    truncated.ingest(_event("event-2", "four", session_id="session-2"))
    truncated.finalize()
    assert truncated.query("question", "now", 3, "CHARACTERIZATION").source_ids == (
        "event-2",
    )


def test_oracle_is_explicit_upper_bound() -> None:
    adapter = OracleAdapter()
    adapter.reset("paper-smoke", "case-1")
    adapter.set_oracle_source_ids(["session-2"])
    adapter.ingest(_event("event-1", "distractor"))
    adapter.ingest(_event("event-2", "evidence", session_id="session-2"))
    adapter.finalize()
    with pytest.raises(ValueError, match="upper-bound"):
        adapter.query("question", "now", 20, "CONTROLLED")
    assert adapter.query("question", "now", 100, "ORACLE_UPPER_BOUND").source_ids == (
        "session-2",
    )


def test_dense_adapter_uses_injected_frozen_embedder() -> None:
    def embed(values: list[str]) -> np.ndarray:
        vectors = {
            "blue": [1.0, 0.0],
            "blue boat": [1.0, 0.0],
            "red bike": [0.0, 1.0],
        }
        return np.asarray([vectors[value] for value in values], dtype=np.float32)

    adapter = DenseAdapter(embed, model_id="fixture-v1", top_k=1)
    adapter.reset("paper-smoke", "case-1")
    adapter.ingest(_event("event-1", "red bike"))
    adapter.ingest(_event("event-2", "blue boat", session_id="session-2"))
    adapter.finalize()
    result = adapter.query("blue", "now", 20, "CONTROLLED")
    assert result.source_ids == ("session-2",)
    assert "Session Date:" in result.context
    assert "user: blue boat" in result.context
    assert result.usage["embedding_items"] == 3


def test_dense_adapter_matches_official_unnormalized_dot_product() -> None:
    def embed(values: list[str]) -> np.ndarray:
        vectors = {
            "query": [1.0, 0.0],
            "cosine winner": [1.0, 1.0],
            "raw dot winner": [2.0, 100.0],
        }
        return np.asarray([vectors[value] for value in values], dtype=np.float32)

    adapter = DenseAdapter(embed, model_id="fixture-v1", top_k=1)
    adapter.reset("paper-smoke", "case-1")
    adapter.ingest(_event("event-1", "cosine winner", session_id="session-1"))
    adapter.ingest(_event("event-2", "raw dot winner", session_id="session-2"))
    adapter.finalize()
    result = adapter.query("query", "now", 100, "CONTROLLED")
    assert result.source_ids == ("session-2",)
    assert result.trace[0]["score"] == 2.0


def test_longmemeval_session_ids_are_nonrevealing_and_scorer_reproducible(
    tmp_path: Path,
) -> None:
    raw_session_id = "answer_gold-session"
    pseudonym = pseudonymize_session_id("case-1", raw_session_id)
    assert pseudonym.startswith("session-")
    assert "answer" not in pseudonym
    assert raw_session_id not in pseudonym

    dataset = tmp_path / "synthetic-labels.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "answer": "gold",
                    "answer_session_ids": [raw_session_id],
                    "haystack_session_ids": [raw_session_id],
                    "question_id": "case-1",
                }
            ]
        )
    )
    labels = labels_from_dataset(dataset, ("case-1",))
    assert labels["case-1"]["answer_session_ids"] == [pseudonym]


def test_memora_inputs_strip_simulator_and_scorer_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        memora_dataset,
        "MINIMUM_SESSIONS_BY_PERIOD",
        {"weekly": 1, "monthly": 1, "quarterly": 1},
    )
    strata = (
        ("weekly", "academic_researcher"),
        ("monthly", "financial_analyst"),
        ("quarterly", "software_engineer"),
    )
    for period, persona in strata:
        root = tmp_path / period / persona
        conversations = root / "conversations"
        conversations.mkdir(parents=True)
        (conversations / "session_0001.json").write_text(
            json.dumps(
                {
                    "session_id": 1,
                    "session_type": "memory_update",
                    "operation": "forbidden",
                    "operation_details": {"gold": "forbidden"},
                    "date": "2026-08-01",
                    "conversation": [
                        {
                            "turn": 1,
                            "speaker": "user_agent",
                            "message": "The visible user statement.",
                            "share_memory": True,
                        },
                        {
                            "turn": 2,
                            "speaker": "ai_agent",
                            "message": "The visible assistant response.",
                            "share_memory": False,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        per_task = 10 if period == "quarterly" else 5
        questions = {}
        for task in memora_dataset.TASKS:
            questions[task] = [
                {
                    "question_id": f"{task}-{index}",
                    "question": f"Question {index}?",
                    "question_date": "2026-08-02",
                    "memory_evidence": {"gold": "forbidden"},
                    "forgetting_evidence": {"gold": "forbidden"},
                    "evaluation": {
                        "evaluation_questions": [
                            {
                                "evaluation_question": "forbidden",
                                "expected_answer": "yes",
                            }
                        ]
                    },
                }
                for index in range(per_task)
            ]
        (root / f"evaluation_questions_{persona}.json").write_text(
            json.dumps({"persona": persona, "questions": questions}),
            encoding="utf-8",
        )
    value = memora_dataset.build_label_free_inputs(data_root=tmp_path, strata=strata)
    assert value["case_count"] == 60
    assert value["cohort_count"] == 3
    assert value["forbidden_label_fields_present"] is False
    serialized = json.dumps(value)
    for forbidden in memora_dataset.FORBIDDEN_INPUT_KEYS:
        assert f'"{forbidden}"' not in serialized
    assert value["cohorts"][0]["sessions"][0]["turns"] == [
        {"actor": "user", "content": "The visible user statement."},
        {"actor": "assistant", "content": "The visible assistant response."},
    ]


def test_memora_controlled_contexts_reuse_one_cohort_index(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps(
            {
                "case_count": 2,
                "cases": [
                    {
                        "case_id": "case-blue",
                        "cohort_id": "synthetic:persona",
                        "question": "Which kayak is ready?",
                        "question_at": "2026-08-02",
                        "source_question_id": "source-blue",
                        "task": "Remembering",
                    },
                    {
                        "case_id": "case-bike",
                        "cohort_id": "synthetic:persona",
                        "question": "Which bicycle is stored?",
                        "question_at": "2026-08-02",
                        "source_question_id": "source-bike",
                        "task": "Remembering",
                    },
                ],
                "cohort_count": 1,
                "cohorts": [
                    {
                        "cohort_id": "synthetic:persona",
                        "period": "synthetic",
                        "persona": "persona",
                        "sessions": [
                            {
                                "observed_at": "2026-08-01",
                                "session_id": "session-one",
                                "turns": [
                                    {
                                        "actor": "user",
                                        "content": "The blue kayak is ready.",
                                    },
                                    {
                                        "actor": "assistant",
                                        "content": "I will remember that.",
                                    },
                                ],
                            },
                            {
                                "observed_at": "2026-08-01",
                                "session_id": "session-two",
                                "turns": [
                                    {
                                        "actor": "user",
                                        "content": "The red bicycle is stored.",
                                    }
                                ],
                            },
                            {
                                "observed_at": "2026-08-01",
                                "session_id": "session-three",
                                "turns": [
                                    {"actor": "user", "content": "The tent is packed."}
                                ],
                            },
                        ],
                    }
                ],
                "forbidden_label_fields_present": False,
                "paper_labels_opened": False,
                "schema": "milai.dg11.paper-memora-inputs.v1",
                "scorer_label_values_accessed": False,
                "test_data_only": True,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "contexts.json"
    value = memora_runner.prepare_contexts(
        run_id="memora-synthetic-smoke",
        input_path=inputs,
        output=output,
        methods=("CTRL-NONE", "LME-BM25-S"),
        token_budget=512,
        tokenizer_path=Path("/cra/qwen36-35B/tokenizer.json"),
        freeze_manifest=tmp_path / "unused-freeze.json",
        allow_unfrozen_smoke=True,
    )
    records = read_context_archive(output)
    assert len(records) == 4
    assert value["paper_labels_opened"] is False
    bm25 = {
        record.case_id: record for record in records if record.method_id == "LME-BM25-S"
    }
    assert bm25["case-blue"].source_ids[0] == "session-one"
    assert bm25["case-bike"].source_ids[0] == "session-two"
    stats = value["cohort_stats"]
    assert len(stats) == 2
    assert {row["ingested_events"] for row in stats} == {4}


def test_memora_fama_and_aggregation_match_released_definition() -> None:
    assert fama_score(2, 2, 1, 1) == 1.0
    assert fama_score(1, 2, 0, 1) == pytest.approx(1 / 6)
    assert fama_score(1, 2, 0, 0) == 0.5
    case = memora_dataset.MemoraCase(
        case_id="case-1",
        cohort_id="weekly:persona",
        question="Question?",
        question_at="2026-08-24",
        source_question_id="source-1",
        task="Remembering",
    )
    criteria = (
        MemoraCriterion(
            case_id="case-1",
            criterion_id="presence-1",
            evaluation_question="Does the answer include the current item?",
            evaluation_type="memory_presence",
            expected_answer="yes",
            source_question_id="source-1",
            task="Remembering",
        ),
        MemoraCriterion(
            case_id="case-1",
            criterion_id="forget-1",
            evaluation_question="Does the answer include the deleted item?",
            evaluation_type="forgetting_absence",
            expected_answer="no",
            source_question_id="source-1",
            task="Remembering",
        ),
    )
    metrics = aggregate_judgments(
        cases=(case,),
        methods=("DG11-FULL",),
        criteria=criteria,
        judgments=(
            {
                "case_id": "case-1",
                "criterion_id": "presence-1",
                "is_correct": True,
                "judge_answer": "yes",
                "method_id": "DG11-FULL",
            },
            {
                "case_id": "case-1",
                "criterion_id": "forget-1",
                "is_correct": True,
                "judge_answer": "no",
                "method_id": "DG11-FULL",
            },
        ),
    )
    assert metrics["by_method"]["DG11-FULL"]["fama"] == 100.0
    assert metrics["by_method"]["DG11-FULL"]["deletion_leak_rate"] == 0.0


def test_memora_independent_judge_runner_is_resumable(tmp_path: Path) -> None:
    prompt_messages = messages(
        model_response="The current item is blue.",
        evaluation_question="Does the response say the current item is blue?",
        evaluation_type="memory_presence",
    )
    assert "AI RESPONSE TO EVALUATE" in prompt_messages[1]["content"]
    ledger = UsageLedger(tmp_path / "judge-ledger.jsonl")
    prepared = (
        PreparedJudge(
            ordinal=0,
            logical_request_id="judge-request-1",
            case_id="case-1",
            method_id="DG11-FULL",
            criterion_id="criterion-1",
            evaluation_type="memory_presence",
            expected_answer="yes",
            prompt="prompt-1",
            prompt_tokens=10,
        ),
        PreparedJudge(
            ordinal=1,
            logical_request_id="judge-request-2",
            case_id="case-1",
            method_id="DG11-FULL",
            criterion_id="criterion-2",
            evaluation_type="forgetting_absence",
            expected_answer="no",
            prompt="prompt-2",
            prompt_tokens=11,
        ),
    )
    calls: list[str] = []

    def judge(item: PreparedJudge) -> JudgeCompletion:
        calls.append(item.logical_request_id)
        return JudgeCompletion(
            judge_answer=item.expected_answer,
            confidence=1.0,
            explanation_sha256="a" * 64,
            native_request_id=f"judge-native-{item.ordinal}",
            prompt_tokens=item.prompt_tokens,
            completion_tokens=5,
            finish_reason="stop",
        )

    runner = MemoraJudgeRunner(ledger, max_workers=2)
    records = runner.execute(prepared, judge)
    assert len(records) == 2
    assert all(record["is_correct"] is True for record in records)
    calls.clear()
    assert runner.execute(prepared, judge) == records
    assert calls == []


def test_usage_ledger_detects_tamper(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = UsageLedger(path)
    ledger.append({"logical_request_id": "request-1", "type": "RESERVED"})
    ledger.append({"logical_request_id": "request-1", "type": "PROVIDER_STARTED"})
    assert len(ledger.verify().events) == 2
    lines = path.read_text().splitlines()
    value = json.loads(lines[0])
    value["event"]["type"] = "CHANGED"
    lines[0] = json.dumps(value)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(LedgerError, match="digest"):
        ledger.verify()


def test_usage_ledger_cached_head_detects_external_drift_before_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = UsageLedger(path)
    ledger.append({"logical_request_id": "request-1", "type": "RESERVED"})
    value = json.loads(path.read_text())
    value["event"]["type"] = "CORRUPTED"
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(LedgerError, match="digest"):
        ledger.append({"logical_request_id": "request-2", "type": "RESERVED"})


def test_answer_runner_eight_workers_and_completed_resume(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "ledger.jsonl")
    runner = PaperAnswerRunner(ledger, max_workers=8, max_memory_tokens=512)
    prepared = tuple(
        PreparedAnswer(
            index, f"request-{index}", f"case-{index}", "CTRL-NONE", "p", 1, 0
        )
        for index in range(4)
    )
    calls: list[str] = []

    def answer(item: PreparedAnswer) -> AnswerCompletion:
        calls.append(item.logical_request_id)
        return AnswerCompletion("ok", f"native-{item.ordinal}", 1, 1, "stop")

    results = runner.execute(prepared, answer)
    assert len(results) == 4
    assert set(calls) == {f"request-{index}" for index in range(4)}
    calls.clear()
    assert runner.execute(prepared, answer) == results
    assert calls == []
    summary = scan_archive(
        ledger.path, tuple(item.logical_request_id for item in prepared)
    )
    assert summary.succeeded == 4


def test_answer_runner_refuses_ambiguous_provider_start(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "ledger.jsonl")
    ledger.append({"logical_request_id": "request-1", "type": "RESERVED"})
    ledger.append({"logical_request_id": "request-1", "type": "PROVIDER_STARTED"})
    runner = PaperAnswerRunner(ledger, max_workers=1, max_memory_tokens=512)
    item = PreparedAnswer(0, "request-1", "case-1", "CTRL-NONE", "p", 1, 0)
    with pytest.raises(ArchiveError, match="ambiguous"):
        runner.execute(
            (item,),
            lambda _: AnswerCompletion("ok", "native-1", 1, 1, "stop"),
        )


def test_completed_generation_archive_is_write_once(tmp_path: Path) -> None:
    path = tmp_path / "raw-generations.json"
    original = {"finished_at": "first", "records": [1], "status": "PASS"}
    resumed = {"finished_at": "second", "records": [1], "status": "PASS"}
    assert _write_generation_once(path, original) == original
    original_bytes = path.read_bytes()
    assert _write_generation_once(path, resumed) == original
    assert path.read_bytes() == original_bytes
    with pytest.raises(LongMemEvalRunnerError, match="differs"):
        _write_generation_once(
            path, {"finished_at": "third", "records": [2], "status": "PASS"}
        )


def test_milai_context_runner_rejects_in_process_case_parallelism(
    tmp_path: Path,
) -> None:
    with pytest.raises(MiLAiContextError, match="exactly one worker per process"):
        run_milai_contexts(
            run_id="paper-smoke",
            input_path=tmp_path / "inputs.json",
            output=tmp_path / "contexts.json",
            env_file=tmp_path / "runtime.env",
            method_id="DG10-FROZEN",
            runtime_wheel=tmp_path / "runtime.whl",
            install_manifest=tmp_path / "install.json",
            workers=2,
            max_case_attempts=1,
            tokenizer_path=tmp_path / "tokenizer.json",
            freeze_manifest=tmp_path / "freeze.json",
            allow_unfrozen_smoke=True,
        )


def test_milai_embedding_counter_is_transparent_and_exact() -> None:
    class FakeEmbedding:
        dimensions = 2
        identity = object()

        def __init__(self) -> None:
            self.warmups = 0
            self.inferences = 0

        def warmup(self) -> str:
            self.warmups += 1
            return "READY"

        def embed(self, text: str) -> list[float]:
            self.inferences += 1
            return [float(len(text)), 0.0]

    inner = FakeEmbedding()
    counter = _EmbeddingCallCounter()
    wrapped = _CountingEmbeddingProvider(inner, counter)
    assert wrapped.identity is inner.identity
    assert wrapped.dimensions == inner.dimensions
    assert wrapped.warmup() == "READY"
    assert wrapped.embed("abc") == [3.0, 0.0]
    assert inner.warmups == 1
    assert inner.inferences == 1
    assert counter.warmup_calls == 1
    assert counter.inference_calls == 1


def test_milai_context_binds_mcp_host_to_isolated_python_and_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEmbedding:
        dimensions = 2
        identity = object()

        def warmup(self) -> str:
            return "READY"

        def embed(self, text: str) -> list[float]:
            return [float(len(text)), 0.0]

    observed: list[str | None] = []
    product_backend = SimpleNamespace()

    def factory(settings: object) -> FakeEmbedding:
        return FakeEmbedding()

    def runtime_context(**kwargs: object) -> tuple[object, dict[str, object]]:
        observed.append(os.environ.get("DG10_MCP_HOST_PYTHON"))
        embedding = product_backend._embedding_provider(object())
        embedding.warmup()
        embedding.embed("fixture")
        return object(), {"retrieved_items": []}

    product_backend._embedding_provider = factory
    product_backend._runtime_context = runtime_context
    monkeypatch.setattr(
        milai_context_runner,
        "load_settings",
        lambda: SimpleNamespace(embedding_prewarm=True),
    )
    monkeypatch.setenv("DG10_MCP_HOST_PYTHON", "prior-host-python")
    _, trace = milai_context_runner._runtime_context_with_embedding_accounting(
        case=SimpleNamespace(),
        env_file=Path("unused.env"),
        product_module=product_backend,
    )
    assert observed == [str(Path(sys.executable).absolute())]
    assert os.environ["DG10_MCP_HOST_PYTHON"] == "prior-host-python"
    assert trace["paper_embedding_accounting"] == {
        "api_query_calls": 1,
        "api_warmup_calls": 1,
        "direct_parent_inference_calls": 1,
        "direct_parent_warmup_calls": 1,
        "total_calls": 4,
    }


def test_lme_v2_adapter_preserves_text_and_selected_screenshot(
    tmp_path: Path,
) -> None:
    requests: list[RuntimeRequest] = []

    def backend(request: RuntimeRequest) -> RuntimeResult:
        requests.append(request)
        return RuntimeResult(
            context="ACTIVE STATE\nVault Alpha is selected.",
            context_status="AVAILABLE",
            retrieved_trajectory_ids=("trajectory-target",),
            usage={"embedding_calls": 3, "retriever_calls": 1},
        )

    memory = MiLAiLMEV2Memory(
        {"trajectories_root_dir": str(tmp_path)}, _backend=backend
    )
    target = _lme_v2_trajectory(tmp_path, "trajectory-target")
    confirmation = tmp_path / "screenshots/trajectory-target/0001.png"
    confirmation.write_bytes(b"synthetic-confirmation-image")
    target["states"].append(
        {
            "state_index": 1,
            "step": 8,
            "url": "https://synthetic.invalid/settings/backup/confirmation",
            "action": None,
            "thought": "Verify the backup confirmation",
            "accessibility_tree": (
                "heading 'Backup confirmation'\nstatus 'Vault Alpha saved'"
            ),
            "screenshot": "screenshots/trajectory-target/0001.png",
        }
    )
    distractor = _lme_v2_trajectory(
        tmp_path,
        "trajectory-distractor",
        goal="Read an unrelated calendar",
        tree="heading 'Calendar'",
    )
    memory.insert(target)
    memory.insert(distractor)
    question_image = tmp_path / "question.png"
    question_image.write_bytes(b"synthetic-question-image")
    memory.set_query_context(query_invocation_id="synthetic-query-1")
    items = memory.query(
        "Which vault appears on the backup confirmation?",
        query_image=str(question_image),
    )
    metadata = memory.post_query_hook(
        query="Which vault appears on the backup confirmation?",
        query_image=str(question_image),
        memory_context=items,
    )

    assert len(requests) == 1
    assert requests[0].logical_query_id == "synthetic-query-1"
    assert requests[0].sessions[0][0] == "trajectory-target"
    assert "ACCESSIBILITY_TREE:\nbutton 'Save'" in requests[0].sessions[0][1]
    assert [item["type"] for item in items] == ["text", "text", "image"]
    assert items[2]["value"].endswith("screenshots/trajectory-target/0001.png")
    assert metadata is not None
    assert metadata["labels_accessed"] is False
    assert metadata["paper_question_rows_read_by_adapter"] == 0
    assert metadata["modality_lossiness"] == {
        "question_image_passed_to_memory_query": True,
        "question_image_used_for_visual_retrieval": False,
        "reader_receives_question_image_independently": True,
        "retrieved_screenshot_pixels_preserved": True,
        "visual_only_retrieval_supported": False,
    }
    assert metadata["retrieved_screenshots"][0]["trajectory_id"] == (
        "trajectory-target"
    )
    assert memory_context_identity(items)["items"][2]["type"] == "image"


def test_lme_v2_adapter_rejects_labels_unknown_results_and_late_insert(
    tmp_path: Path,
) -> None:
    memory = MiLAiLMEV2Memory(
        {"trajectories_root_dir": str(tmp_path)},
        _backend=lambda request: RuntimeResult(
            context="context",
            context_status="AVAILABLE",
            retrieved_trajectory_ids=("unknown-trajectory",),
            usage={},
        ),
    )
    leaked = _lme_v2_trajectory(tmp_path, "trajectory-label")
    leaked["answer"] = "forbidden"
    with pytest.raises(LMEV2AdapterError, match="scorer label fields"):
        memory.insert(leaked)

    memory.insert(_lme_v2_trajectory(tmp_path, "trajectory-safe"))
    with pytest.raises(LMEV2AdapterError, match="unknown trajectory"):
        memory.query("backup vault")
    with pytest.raises(LMEV2AdapterError, match="insert after first query"):
        memory.insert(_lme_v2_trajectory(tmp_path, "trajectory-late"))


def test_lme_v2_adapter_rejects_screenshot_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")
    trajectory = _lme_v2_trajectory(tmp_path, "trajectory-escape")
    trajectory["states"][0]["screenshot"] = "../outside.png"
    memory = MiLAiLMEV2Memory(
        {"trajectories_root_dir": str(tmp_path)},
        _backend=lambda request: RuntimeResult("", "ABSTAINED", (), {}),
    )
    with pytest.raises(LMEV2AdapterError, match="contained relative path"):
        memory.insert(trajectory)


def test_lme_v2_official_contract_identity_does_not_open_paper_rows() -> None:
    identity = official_contract_identity()
    assert identity["commit"] == ("2cc8c540bdb87fe6761629b585e727e1c4704520")
    assert identity["paper_data_opened"] is False
    assert identity["question_rows_read"] == 0
    assert "memory_modules/memory.py" in identity["files"]


def test_pe06_final_adapter_evidence_is_reproducible_and_failure_is_excluded() -> None:
    result = validate_pe06_result(PE06_RESULT)
    failure = validate_pe06_failure()
    assert result["asset_count"] == 5
    assert result["context_item_count"] == 7
    assert result["embedding_calls"] == 6
    assert failure["classification"] == "ADAPTER_STATE_SELECTION_TOKENIZATION_BUG"


def test_pe06_native_baseline_evidence_and_resource_gate_are_freeze_ready() -> None:
    evidence = validate_native_gate()
    assert evidence["status"] == "PASS"
    assert evidence["controller"]["controller_requests"] == 8
    assert evidence["native_rag"]["embedding_requests"] == 4
    assert evidence["method_config"]["memory_context_max_tokens"] == 49152


def test_paper_embedding_service_openai_contract_and_accounting() -> None:
    class FakeProvider:
        dimensions = 2

        def embed(self, text: str) -> list[float]:
            return [float(len(text)), 1.0]

    class FakeTokenizer:
        def encode(self, text: str) -> object:
            return SimpleNamespace(ids=list(text))

    service = EmbeddingService(
        provider=FakeProvider(), tokenizer=FakeTokenizer(), api_key="x" * 32
    )
    assert service.authorized("Bearer " + "x" * 32)
    assert not service.authorized("Bearer wrong")
    response = service.embed(
        {
            "model": PAPER_EMBEDDING_MODEL,
            "input": ["alpha", "beta"],
            "encoding_format": "float",
        }
    )
    assert [item["index"] for item in response["data"]] == [0, 1]
    assert response["data"][0]["embedding"] == [5.0, 1.0]
    assert response["usage"] == {"prompt_tokens": 9, "total_tokens": 9}
    usage = service.usage.snapshot()
    assert usage["inference_ms"] >= 0
    assert {key: usage[key] for key in usage if key != "inference_ms"} == {
        "input_chars": 9,
        "item_count": 2,
        "prompt_tokens": 9,
        "request_count": 1,
    }
    with pytest.raises(EmbeddingServerError, match="model identity"):
        service.embed({"model": "wrong", "input": "alpha"})
    encoded = service.embed(
        {
            "model": PAPER_EMBEDDING_MODEL,
            "input": "abc",
            "encoding_format": "base64",
        }
    )
    raw = base64.b64decode(encoded["data"][0]["embedding"])
    assert array.array("f", raw).tolist() == [3.0, 1.0]


def test_paper_controller_gateway_preserves_response_and_accounts_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "id": "chatcmpl-synthetic-0001",
        "model": "Qwen3.6-35B-A3B-FP8",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"ok":true}'},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
    }
    response_raw = json.dumps(response, separators=(",", ":")).encode()

    class FakeResponse:
        status = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            assert limit > len(response_raw)
            return response_raw

    monkeypatch.setattr(
        "evals.paper.services.controller_gateway.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    gateway = ControllerGateway(api_key="x" * 32, upstream="http://127.0.0.1:7860/v1")
    request_raw = json.dumps(
        {
            "model": "Qwen3.6-35B-A3B-FP8",
            "messages": [{"role": "user", "content": "synthetic"}],
            "max_tokens": 32,
        },
        separators=(",", ":"),
    ).encode()
    assert gateway.complete(request_raw) == response_raw
    metrics = gateway.usage.snapshot()
    assert metrics["request_count"] == 1
    assert metrics["successful_count"] == 1
    assert metrics["failed_count"] == 0
    assert metrics["prompt_tokens"] == 11
    assert metrics["completion_tokens"] == 4
    assert metrics["total_tokens"] == 15
    assert len(metrics["receipts"]) == 1
    assert "content" not in json.dumps(metrics)
    with pytest.raises(ControllerGatewayError, match="model identity"):
        gateway.complete(
            json.dumps(
                {
                    "model": "wrong",
                    "messages": [{"role": "user", "content": "synthetic"}],
                    "max_tokens": 32,
                }
            ).encode()
        )


def test_extended_beam_inputs_strip_all_scorer_fields(tmp_path: Path) -> None:
    for chat_number in range(1, 21):
        root = tmp_path / "chats/100K" / str(chat_number)
        questions_root = root / "probing_questions"
        questions_root.mkdir(parents=True)
        (root / "chat.json").write_text(
            json.dumps(
                [
                    {
                        "turns": [
                            [
                                {
                                    "content": f"visible-{chat_number}",
                                    "id": "gold-source-id",
                                    "question_type": "gold-type",
                                    "role": "user",
                                }
                            ]
                        ]
                    }
                ]
            ),
            encoding="utf-8",
        )
        (questions_root / "probing_questions.json").write_text(
            json.dumps(
                {
                    category: [
                        {
                            "answer": "gold",
                            "question": f"{category}-{ordinal}?",
                            "rubric": "gold-rubric",
                            "source_chat_ids": ["gold-source-id"],
                        }
                        for ordinal in range(2)
                    ]
                    for category in BEAM_CATEGORIES
                }
            ),
            encoding="utf-8",
        )
    value = build_beam_inputs(tmp_path)
    encoded = json.dumps(value)
    assert value["case_count"] == 400
    assert value["history_count"] == 20
    assert value["repository_directory_label"] == "100K"
    assert value["published_scale_label"] == "128K"
    assert "gold-rubric" not in encoded
    assert "gold-source-id" not in encoded
    assert '"answer"' not in encoded


def test_beam_dense_pair_chunks_match_native_role_pair_contract() -> None:
    session = ExtendedSession(
        session_id="beam-smoke-session",
        observed_at="2026-01-01T00:00:00Z",
        turns=(
            ExtendedTurn(role="user", content="quiet lake"),
            ExtendedTurn(role="assistant", content="kayaking noted"),
        ),
    )
    chunks = _official_pair_chunks((session,))
    assert len(chunks) == 1
    assert chunks[0].source_id == "beam-smoke-session:pair-000"
    assert "USER: quiet lake" in chunks[0].text
    assert "ASSISTANT: kayaking noted" in chunks[0].text
    with pytest.raises(BeamDenseContextError, match="odd message count"):
        _official_pair_chunks(
            (
                ExtendedSession(
                    session_id="broken",
                    observed_at="2026-01-01T00:00:00Z",
                    turns=(ExtendedTurn(role="user", content="orphan"),),
                ),
            )
        )


def test_beam_dense_prefix_respects_exact_answer_token_budget() -> None:
    tokenizer = SimpleNamespace(
        encode=lambda value: SimpleNamespace(ids=value.split())
    )
    context, truncated = fit_beam_dense_prefix(
        "one two three four", 3, tokenizer
    )
    assert truncated is True
    assert context == "one two three"


def test_extended_horizon_inputs_are_balanced_and_smoke_disjoint() -> None:
    generators = ("g1", "g2", "g3")
    benchmark = []
    for ordinal in range(4245):
        generator = generators[ordinal % len(generators)]
        evolved = (ordinal // len(generators)) % 2 == 0
        benchmark.append(
            {
                "conversation": f"Conversation History: visible-{ordinal}",
                "correct_letter": "A",
                "distractor_letter": "B",
                "generator": generator,
                "has_evolved": evolved,
                "id": f"benchmark-{ordinal:04d}",
                "options": [
                    {"letter": letter, "option": f"visible-{letter}", "value": "gold"}
                    for letter in "ABCDE"
                ],
                "preference_evolution": "gold",
            }
        )
    sample = [
        {
            "conversation": f"Conversation History: smoke-{ordinal}",
            "correct_letter": "A",
            "distractor_letter": "B",
            "generator": generators[ordinal % len(generators)],
            "has_evolved": ordinal % 2 == 0,
            "id": f"smoke-{ordinal:02d}",
            "options": [
                {"letter": letter, "option": f"smoke-{letter}", "value": "gold"}
                for letter in "ABCDE"
            ],
            "preference_evolution": "gold",
        }
        for ordinal in range(10)
    ]
    formal, smoke = build_horizon_inputs(
        benchmark, sample, source_files=[{"sha256": "fixture"}]
    )
    formal_ids = {case["case_id"] for case in formal["cases"]}
    smoke_ids = {case["case_id"] for case in smoke["cases"]}
    encoded = json.dumps((formal, smoke))
    assert formal["case_count"] == 120
    assert smoke["case_count"] == 10
    assert set(formal["stratum_counts"].values()) == {20}
    assert formal_ids.isdisjoint(smoke_ids)
    assert "correct_letter" not in encoded
    assert "distractor_letter" not in encoded
    assert "preference_evolution" not in encoded
    assert '"value"' not in encoded


def test_extended_cupid_inputs_are_balanced_label_free_and_disjoint() -> None:
    kinds = ("changing", "consistent", "contrastive")
    rows = []
    for ordinal in range(756):
        rows.append(
            {
                "current_checklist": ["gold"],
                "current_context_factor": "gold",
                "current_contextual_preference": "gold",
                "current_request": f"visible request {ordinal}",
                "instance_type": kinds[ordinal % len(kinds)],
                "persona_id": f"persona-{ordinal // 3}",
                "prior_interactions": [
                    {
                        "contextual_preference": "gold",
                        "dialogue": [
                            {"content": f"visible dialogue {ordinal}", "role": "user"}
                        ],
                    }
                ],
            }
        )
    formal, smoke = build_cupid_inputs(rows, source_files=[{"sha256": "fixture"}])
    formal_ids = {case["case_id"] for case in formal["cases"]}
    smoke_ids = {case["case_id"] for case in smoke["cases"]}
    encoded = json.dumps((formal, smoke))
    assert formal["case_count"] == 90
    assert smoke["case_count"] == 6
    assert formal["stratum_counts"] == {
        "changing": 30,
        "consistent": 30,
        "contrastive": 30,
    }
    assert formal_ids.isdisjoint(smoke_ids)
    assert "current_contextual_preference" not in encoded
    assert "current_checklist" not in encoded
    assert "contextual_preference" not in encoded
    assert "instance_type" not in encoded


def test_horizon_runtime_query_is_bounded_and_after_history(tmp_path: Path) -> None:
    path = tmp_path / "horizon-smoke.json"
    path.write_text(
        json.dumps(
            {
                "answer_label_fields_read_by_preparer": False,
                "case_count": 1,
                "cases": [
                    {
                        "case_id": "horizon-1",
                        "history_id": "history-1",
                        "options": [
                            {"letter": letter, "option": letter * 800}
                            for letter in "ABCDE"
                        ],
                        "question": "Which response best matches the preference?",
                    }
                ],
                "forbidden_label_fields_present": False,
                "histories": [
                    {
                        "conversation": (
                            "Conversation History:\n"
                            "Date: 2026-03-06T21:50:12.326930\n"
                            "User: visible preference\n"
                            "Assistant: draft follows\n"
                            "Date: [auto-fill]\n"
                            "Assistant: acknowledged"
                        ),
                        "history_id": "history-1",
                    }
                ],
                "history_count": 1,
                "paper_labels_opened": False,
                "partition": "HORIZON-OFFICIAL-SAMPLE-10-SMOKE",
                "schema": "milai.dg11.paper-horizon-inputs.v1",
                "selection_metadata_read_by_preparer": True,
            }
        ),
        encoding="utf-8",
    )
    _partition, cases = load_horizon_inputs(path)
    case = cases[0]
    query = retrieval_query(case.question, "HORIZON-OFFICIAL-SAMPLE-10-SMOKE")
    assert len(query) <= 2_000
    assert all(f"{letter}:" in query for letter in "ABCDE")
    assert len(case.sessions) == 1
    assert "Date: [auto-fill]" in case.sessions[0].turns[1].content
    assert case.question_at == "2026-03-06T21:51:12.326930Z"


def test_horizon_official_letter_scoring_and_paired_delta() -> None:
    labels = [
        {
            "case_id": "static",
            "correct_letter": "A",
            "distractor_letter": "B",
            "generator": "g1",
            "has_evolved": False,
        },
        {
            "case_id": "evolved",
            "correct_letter": "C",
            "distractor_letter": "D",
            "generator": "g1",
            "has_evolved": True,
        },
    ]
    generations = [
        {"answer": "UNKNOWN", "case_id": case, "method_id": "CTRL-NONE"}
        for case in ("static", "evolved")
    ] + [
        {"answer": "A", "case_id": "static", "method_id": "DG11-FULL"},
        {"answer": "The best choice is C.", "case_id": "evolved", "method_id": "DG11-FULL"},
    ]
    result = aggregate_horizon(
        labels=labels,
        generations=generations,
        methods=("CTRL-NONE", "DG11-FULL"),
        bootstrap_seed=7,
    )
    assert extract_horizon_letter("The best choice is C.") == "C"
    assert result["by_method"]["CTRL-NONE"]["accuracy"] == 0
    assert result["by_method"]["DG11-FULL"]["accuracy"] == 1
    assert result["paired_against_first_method"][
        "DG11-FULL-minus-CTRL-NONE"
    ]["accuracy_delta"] == 1


def test_extended_runtime_text_replaces_only_postgres_forbidden_nul() -> None:
    assert runtime_safe_text("can't\x00stop\x19now") == "can't stop\x19now"
