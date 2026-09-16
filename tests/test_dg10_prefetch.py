from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import dg10_memory_quality as quality
from scripts import dg10_prefetch as prefetch
from scripts import dg10_remediation as remediation


class Counter:
    def count(self, text: str) -> int:
        return len(text.split())


class Provider:
    def retrieve(self, *, case_id: str, question: str) -> quality.MemoryContext:
        del case_id
        text = "Thursday afternoon is the approved deployment window."
        return quality.MemoryContext(
            arm="MILAI_RETRIEVAL",
            text=text,
            target_token_count=len(text.split()),
            evidence_ids=("evidence-1",),
            retrieval_request_id="mcp-1",
            retrieval_receipt_sha256="c" * 64,
            query_sha256=hashlib.sha256(question.encode()).hexdigest(),
            query_equals_original_question=True,
            ranking_source="MILAI_RUNTIME_CANONICAL_GATE",
            governed_ingest=True,
            canonical_gate=True,
            full_session_corpus=True,
            artificial_marker=False,
            shared_naive_ranking=False,
        )


class AnswerClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs: object) -> quality.Completion:
        self.calls += 1
        assert kwargs["temperature"] == 0
        return quality.Completion(
            native_request_id="model-1",
            content='{"answer":"Thursday afternoon"}',
            input_tokens=20,
            output_tokens=3,
            cached_input_tokens=0,
            reasoning_tokens=0,
            finish_reason="stop",
            raw_receipt_sha256="a" * 64,
        )


def test_t3a_is_real_prefetch_then_exactly_one_answer_call(tmp_path: Path) -> None:
    client = AnswerClient()
    ledger_path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        harness = prefetch.HostPrefetchHarness(
            provider=Provider(),
            answer_client=client,
            token_counter=Counter(),
            ledger=ledger,
        )
        record, sidecar = harness.run(case_id="case-1", question="What is the deployment window?")
    assert client.calls == 1
    assert record["answer_model_calls"] == 1
    assert record["tool_decision_model_calls"] == 0
    assert record["mcp_calls"] == 1
    assert record["compact_renderer_sha256"] == quality._renderer_sha256()
    assert sidecar["answer"] == "Thursday afternoon"
    summary = remediation.reconcile_attempt_ledger(ledger_path)
    assert summary["retained_successful_calls"] == 1


def test_t3a_rejects_second_answer_or_router_call(tmp_path: Path) -> None:
    client = AnswerClient()
    ledger_path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        record, _ = prefetch.HostPrefetchHarness(
            provider=Provider(), answer_client=client, token_counter=Counter(), ledger=ledger
        ).run(case_id="case-1", question="What is the deployment window?")
    record["answer_model_calls"] = 2
    with pytest.raises(prefetch.PrefetchError, match="one-round"):
        prefetch.validate_prefetch_record(record)


def test_t3b_requires_two_calls_and_separate_schema_transcript_tokens() -> None:
    valid = {
        "tier": "T3b",
        "routing": "MODEL_DECIDES_MCP",
        "model_calls": 2,
        "mcp_calls": 1,
        "tool_decision_model_calls": 1,
        "tool_schema_tokens": 250,
        "tool_transcript_tokens": 80,
        "role": "CHARACTERIZATION_ONLY",
    }
    prefetch.validate_t3b_characterization(valid)
    valid["tool_transcript_tokens"] = 0
    with pytest.raises(prefetch.PrefetchError, match="two-round"):
        prefetch.validate_t3b_characterization(valid)


def test_t3a_provider_accounting_failure_is_finalized(tmp_path: Path) -> None:
    class InvalidUsageClient(AnswerClient):
        def complete(self, **kwargs: object) -> quality.Completion:
            return replace(super().complete(**kwargs), input_tokens=-1)

    path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(path) as ledger:
        harness = prefetch.HostPrefetchHarness(
            provider=Provider(),
            answer_client=InvalidUsageClient(),
            token_counter=Counter(),
            ledger=ledger,
        )
        with pytest.raises(remediation.RemediationError, match="usage value"):
            harness.run(case_id="case-1", question="question")
    latest = remediation.read_attempt_ledger(path)[-1]
    assert latest["attempt_state"] == "FINALIZED"
    assert latest["native_request_ids"] == ["model-1"]
    assert latest["failure_reason_code"] == "PROVIDER_TERMINAL_MISSING"
