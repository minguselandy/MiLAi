from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import dg10_agent_terminal as terminal
from scripts import dg10_memory_quality as quality
from scripts import dg10_remediation as remediation


class Counter:
    def count(self, text: str) -> int:
        return len(text.split())


class Provider:
    def __init__(self, arm: str) -> None:
        self.arm = arm

    def retrieve(self, *, case_id: str, question: str) -> quality.MemoryContext:
        del case_id
        if self.arm == "NO_MEMORY":
            text = ""
            source = "NONE"
            request_id = None
        elif self.arm == "NAIVE_RAG":
            text = "baseline memory"
            source = "NAIVE_RAG_FROZEN_BASELINE"
            request_id = None
        else:
            text = "governed canonical memory"
            source = "MILAI_RUNTIME_CANONICAL_GATE"
            request_id = "mcp-recall-1"
        return quality.MemoryContext(
            arm=self.arm,
            text=text,
            target_token_count=len(text.split()),
            evidence_ids=() if not text else (f"evidence-{self.arm}",),
            retrieval_request_id=request_id,
            retrieval_receipt_sha256=("c" * 64 if request_id is not None else None),
            query_sha256=quality._sha256_text(question),
            query_equals_original_question=True,
            ranking_source=source,
            governed_ingest=self.arm == "MILAI_RETRIEVAL",
            canonical_gate=self.arm == "MILAI_RETRIEVAL",
            full_session_corpus=self.arm == "MILAI_RETRIEVAL",
            artificial_marker=False,
            shared_naive_ranking=False,
        )


class Client:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_kwargs: object) -> quality.Completion:
        self.calls += 1
        return quality.Completion(
            native_request_id=f"native-{self.calls}",
            content=json.dumps({"answer": "answer"}),
            input_tokens=20,
            output_tokens=3,
            cached_input_tokens=0,
            reasoning_tokens=0,
            finish_reason="stop",
            raw_receipt_sha256=f"{self.calls:x}".rjust(64, "0"),
        )


def _providers() -> dict[str, Provider]:
    return {arm: Provider(arm) for arm in quality.ARMS}


def test_frozen_topology_contract_is_one_answer_call_for_all_arms() -> None:
    result = quality.validate_frozen_topology_contract()
    assert result["status"] == "PASS"


def test_same_harness_runs_three_arms_with_one_call_and_separate_sidecars(
    tmp_path: Path,
) -> None:
    client = Client()
    ledger_path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        harness = quality.TrackAHarness(
            answer_client=client,
            token_counter=Counter(),
            providers=_providers(),
            ledger=ledger,
        )
        outputs = [
            harness.run_arm(case_id="case-1", question="original question", arm=arm)
            for arm in quality.ARMS
        ]
    records = [record for record, _sidecar in outputs]
    sidecars = [sidecar for _record, sidecar in outputs]
    proof = quality.validate_topology(records)
    assert proof["status"] == "PASS"
    assert proof["answer_calls_per_arm_case"] == 1
    assert client.calls == 3
    assert all("answer_sha256" in record and "answer" not in record for record in records)
    assert all(sidecar["answer"] == "answer" for sidecar in sidecars)
    summary = remediation.reconcile_attempt_ledger(ledger_path)
    assert summary["known_completed_calls"] == 3
    assert summary["retained_successful_calls"] == 3


def test_milai_marker_shared_ranking_and_question_substitution_are_rejected() -> None:
    context = Provider("MILAI_RETRIEVAL").retrieve(
        case_id="case-1", question="original question"
    )
    for modified in (
        replace(context, artificial_marker=True),
        replace(context, shared_naive_ranking=True),
        replace(context, query_equals_original_question=False),
    ):
        with pytest.raises(
            quality.MemoryQualityError,
            match=r"governance/topology|query substitution|artificial marker",
        ):
            quality.validate_memory_context(
                modified,
                arm="MILAI_RETRIEVAL",
                question="original question",
                token_counter=Counter(),
            )


def test_memory_over_512_target_tokens_is_rejected() -> None:
    context = Provider("MILAI_RETRIEVAL").retrieve(
        case_id="case-1", question="original question"
    )
    text = "x " * 513
    with pytest.raises(quality.MemoryQualityError, match="ceiling"):
        quality.validate_memory_context(
            replace(context, text=text, target_token_count=513),
            arm="MILAI_RETRIEVAL",
            question="original question",
            token_counter=Counter(),
        )


def test_second_answer_call_and_cross_arm_runner_drift_are_rejected(tmp_path: Path) -> None:
    client = Client()
    with remediation.AttemptLedger(tmp_path / "ledger.jsonl") as ledger:
        harness = quality.TrackAHarness(
            answer_client=client,
            token_counter=Counter(),
            providers=_providers(),
            ledger=ledger,
        )
        records = [
            harness.run_arm(case_id="case-1", question="question", arm=arm)[0]
            for arm in quality.ARMS
        ]
    records[0]["answer_model_calls"] = 2
    with pytest.raises(quality.MemoryQualityError, match="answer-call"):
        quality.validate_topology(records)


def test_answer_schema_failure_keeps_native_usage(tmp_path: Path) -> None:
    class BadClient(Client):
        def complete(self, **kwargs: object) -> quality.Completion:
            return replace(super().complete(**kwargs), content="not-json")

    path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(path) as ledger:
        harness = quality.TrackAHarness(
            answer_client=BadClient(),
            token_counter=Counter(),
            providers=_providers(),
            ledger=ledger,
        )
        with pytest.raises(quality.MemoryQualityError, match="not JSON"):
            harness.run_arm(case_id="case-1", question="question", arm="NO_MEMORY")
    summary = remediation.reconcile_attempt_ledger(path)
    assert summary["known_completed_calls"] == 1
    assert summary["known_failed_calls"] == 1
    latest = remediation.read_attempt_ledger(path)[-1]
    public = terminal.public_terminal_record(latest)
    assert public["provider_status"] == "TERMINAL"
    assert public["native_usage_all_attempts"]["input_tokens"] == 20


def test_invalid_retrieval_is_journaled_and_finalized_fail_closed(
    tmp_path: Path,
) -> None:
    class InvalidProvider(Provider):
        def retrieve(self, *, case_id: str, question: str) -> quality.MemoryContext:
            return replace(
                super().retrieve(case_id=case_id, question=question),
                artificial_marker=True,
            )

    path = tmp_path / "ledger.jsonl"
    providers = _providers()
    providers["MILAI_RETRIEVAL"] = InvalidProvider("MILAI_RETRIEVAL")
    with remediation.AttemptLedger(path) as ledger:
        harness = quality.TrackAHarness(
            answer_client=Client(),
            token_counter=Counter(),
            providers=providers,
            ledger=ledger,
        )
        with pytest.raises(quality.MemoryQualityError, match="artificial marker"):
            harness.run_arm(
                case_id="case-1",
                question="question",
                arm="MILAI_RETRIEVAL",
            )
    latest = remediation.read_attempt_ledger(path)[-1]
    assert latest["attempt_state"] == "FINALIZED"
    assert latest["native_mcp_request_ids"] == ["mcp-recall-1"]
    assert latest["failure_reason_code"] == "AGENT_POLICY_REJECTED"


def test_topology_rejects_forged_mcp_call_count(tmp_path: Path) -> None:
    with remediation.AttemptLedger(tmp_path / "ledger.jsonl") as ledger:
        harness = quality.TrackAHarness(
            answer_client=Client(),
            token_counter=Counter(),
            providers=_providers(),
            ledger=ledger,
        )
        records = [
            harness.run_arm(case_id="case-1", question="question", arm=arm)[0]
            for arm in quality.ARMS
        ]
    records[0]["mcp_calls"] = 1
    with pytest.raises(quality.MemoryQualityError, match="MCP-call"):
        quality.validate_topology(records)


def test_provider_accounting_failure_is_finalized_fail_closed(tmp_path: Path) -> None:
    class InvalidIdentityClient(Client):
        def complete(self, **kwargs: object) -> quality.Completion:
            return replace(super().complete(**kwargs), native_request_id="")

    path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(path) as ledger:
        harness = quality.TrackAHarness(
            answer_client=InvalidIdentityClient(),
            token_counter=Counter(),
            providers=_providers(),
            ledger=ledger,
        )
        with pytest.raises(remediation.RemediationError, match="native request ID"):
            harness.run_arm(
                case_id="case-1",
                question="question",
                arm="NO_MEMORY",
            )
    latest = remediation.read_attempt_ledger(path)[-1]
    assert latest["attempt_state"] == "FINALIZED"
    assert latest["failure_reason_code"] == "PROVIDER_TERMINAL_MISSING"
    summary = remediation.reconcile_attempt_ledger(path)
    assert summary["unfinalized_attempt_count"] == 0
    assert summary["complete"] is False
