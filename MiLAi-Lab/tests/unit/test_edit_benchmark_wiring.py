"""Synthetic engineering checks; these are never public benchmark samples."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.analysis.edit_official import LongMemEvalOfficial, author_functions
from milai_lab.datasets.edit_benchmarks import (
    ObservedSession,
    halumem_session,
    history_components,
    longmemeval_history,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.service import MemoryService
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.edit_benchmarks import BenchmarkRun, source_batches


def test_observed_input_excludes_reference_and_future_material() -> None:
    observed = halumem_session(
        "u",
        0,
        {
            "start_time": "Jan 01, 2025, 10:00:00",
            "dialogue": [{"role": "user", "content": "actual speech", "timestamp": "now"}],
            "persona_info": "secret persona",
            "memory_points": ["gold"],
            "questions": [{"question": "future question", "answer": "gold answer"}],
        },
    )
    assert observed.turns == ({"role": "user", "content": "actual speech", "timestamp": "now"},)
    assert "gold" not in repr(observed)


def test_long_history_is_complete_chronological_and_strips_answer_markers() -> None:
    observed = longmemeval_history(
        {
            "haystack_session_ids": ["late", "early"],
            "haystack_dates": ["2025/02/01", "2025/01/01"],
            "haystack_sessions": [
                [{"role": "user", "content": "later", "has_answer": True}],
                [{"role": "assistant", "content": "earlier"}],
            ],
            "question": "not observed",
            "answer": "gold",
        }
    )
    assert [row.session_id for row in observed] == ["early", "late"]
    assert sum(len(row.turns) for row in observed) == 2
    assert "has_answer" not in repr(observed)
    assert "gold" not in repr(observed)


def test_source_clusters_follow_transitive_history_overlap() -> None:
    groups = history_components(
        [
            {"question_id": "a", "haystack_session_ids": ["x"]},
            {"question_id": "b", "haystack_session_ids": ["x", "y"]},
            {"question_id": "c", "haystack_session_ids": ["y"]},
            {"question_id": "d", "haystack_session_ids": ["z"]},
        ]
    )
    assert {frozenset(g) for g in groups} == {frozenset("abc"), frozenset("d")}


def test_author_function_body_and_prompt_execute_without_cloud_import(tmp_path: Path) -> None:
    path = tmp_path / "author.py"
    path.write_text(
        'import nonexistent_cloud_client\nPROMPT = "Author prompt: {}"\n'
        "def score(value):\n    return callback(PROMPT.format(value))\n"
    )
    functions = author_functions(path, {"score"}, {"callback": lambda text: text})
    assert functions["score"]("answer") == "Author prompt: answer"
    assert LongMemEvalOfficial.label("YES")
    assert not LongMemEvalOfficial.label("no")


def test_real_store_formation_revision_and_restart_without_replaying_writer(tmp_path: Path) -> None:
    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root, execution.settings = tmp_path, {"retrieval_limit": 10}
    calls = []

    def writer(key: str, messages: list[dict[str, str]], *, structured: bool) -> str:
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        old = payload["old_records"]
        return json.dumps(
            {
                "operations": [
                    {
                        "target_record": old[0]["id"] if old else None,
                        "content": payload["new_sources"][0]["content"],
                        "kind": "semantic",
                        "scope": {},
                        "source_refs": [payload["new_sources"][0]["source_ref"]],
                    }
                ]
            }
        )

    execution.call = writer
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(
            store,
            ("synthetic-edit", "u"),
            "u",
            tmp_path / "bank.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        first = ObservedSession(
            "s1",
            "today",
            ({"role": "user", "content": "BlueProject Monday", "timestamp": "today"},),
        )
        second = ObservedSession(
            "s2",
            "tomorrow",
            ({"role": "user", "content": "BlueProject Tuesday", "timestamp": "tomorrow"},),
        )
        execution.maintain(service, first, "1")
        first_id = service.records()[0]["id"]
        execution.maintain(service, second, "2")
        assert service.records()[0]["id"] == first_id
        assert service.records()[0]["value"]["revision"] == 2
        assert len(service.records()[0]["value"]["source_refs"]) == 2
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(
            store,
            ("synthetic-edit", "u"),
            "u",
            tmp_path / "bank.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        assert execution.maintain(service, second, "2") == ["BlueProject Tuesday"]
        assert service.read(first_id)["value"]["revision"] == 2
    assert len(calls) == 2


def test_incomplete_response_remains_failed_and_charged_on_resume(tmp_path: Path) -> None:
    class Tokenizer:
        def apply_chat_template(self, *args: object, **kwargs: object) -> list[int]:
            return [1, 2]

    attempts = []

    def provider(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "length", "message": {"content": "partial"}}],
                "usage": {"total_tokens": 9},
            },
        )

    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root = tmp_path
    execution.settings = {"context_tokens": 1024, "model": {"max_tokens": 100}}
    execution.tokenizer = Tokenizer()
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test"),
        transport=httpx.MockTransport(provider),
        budget=budget,
    ) as client:
        execution.client = client
        for _ in range(2):
            with pytest.raises(ValueError, match="incomplete"):
                execution.call("a", [{"role": "user", "content": "test"}], structured=False)
        write_json(tmp_path / "http" / "b" / "request.json", {"attempt": "original"})
        with pytest.raises(RuntimeError, match="do not blindly repeat"):
            execution.call("b", [], structured=False)
    assert len(attempts) == 1
    assert budget.state["generation_requests"] == 1
    assert budget.state["generation"]["known_tokens"] == 9
    assert read_json(tmp_path / "http" / "a" / "failure.json")["type"] == "ValueError"


class CharacterTokenizer:
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return list(range(len(text)))


def test_bounded_source_batches_reassemble_every_original_character() -> None:
    observed = ObservedSession(
        "s",
        "date",
        (
            {"role": "user", "content": "甲乙丙丁戊abcdefg", "timestamp": "date"},
            {"role": "assistant", "content": "0123456789", "timestamp": "date"},
        ),
    )
    batches = source_batches(observed, CharacterTokenizer(), 6)
    for batch in batches:
        assert sum(part["end"] - part["start"] for part in batch) <= 6
    for ordinal, turn in enumerate(observed.turns):
        parts = [p for batch in batches for p in batch if p["turn"] == ordinal]
        assert "".join(turn["content"][p["start"] : p["end"]] for p in parts) == turn["content"]
        assert parts[0]["start"] == 0 and parts[-1]["end"] == len(turn["content"])


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_four_arm_runner_forms_updates_and_reopens_actual_bank(tmp_path: Path, arm: str) -> None:
    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root = tmp_path
    execution.settings = {"retrieval_limit": 10, "source_tokens": 4096, "arm": arm}
    execution.tokenizer = CharacterTokenizer()
    calls = []

    def writer(key: str, messages: list[dict[str, str]], *, structured: bool) -> str:
        payload = json.loads(messages[1]["content"])["delivery"]
        calls.append(payload)
        source = payload["sources"][0]
        record = payload["records"][0] if payload["records"] else None
        if record is None or arm in {"B0", "B2"}:
            proposal = {
                "action": "create" if record is None else "rewrite",
                "units": [{"text": source["text"], "evidence": [source["evidence_id"]]}],
            }
        else:
            proposal = {
                "action": "edit",
                "edits": [
                    {
                        "operation": "replace",
                        "target_unit": record["edit_state"]["units"][0]["unit_id"],
                        "text": source["text"],
                        "evidence": [source["evidence_id"]],
                    }
                ],
            }
        if record is not None:
            proposal.update(target_record=record["record_id"], base_revision=record["revision"])
        return json.dumps({"proposals": [proposal]})

    execution.call = writer
    path = tmp_path / "bank.sqlite"
    second = ObservedSession(
        "s2", "later", ({"role": "user", "content": "BlueProject Tuesday", "timestamp": "later"},)
    )
    with SqliteStore.from_conn_string(str(path)) as store:
        service = MemoryService(
            store,
            ("synthetic-edit-runner", arm, "u"),
            "u",
            tmp_path / "bank.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        execution.maintain(
            service,
            ObservedSession(
                "s1",
                "earlier",
                ({"role": "user", "content": "BlueProject Monday", "timestamp": "earlier"},),
            ),
            "first",
        )
        first = service.records()[0]
        assert "BlueProject Monday" in first["value"]["content"]
        execution.maintain(service, second, "second")
        current = service.records()[0]
        assert current["id"] == first["id"] and current["value"]["revision"] == 2
        assert "BlueProject Tuesday" in current["value"]["content"]
        assert "Monday" not in current["value"]["content"]
    with SqliteStore.from_conn_string(str(path)) as store:
        service = MemoryService(
            store,
            ("synthetic-edit-runner", arm, "u"),
            "u",
            tmp_path / "bank.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        assert "Tuesday" in execution.maintain(service, second, "second")[0]
        assert service.read(first["id"])["value"]["revision"] == 2
    assert len(calls) == 2
    assert "Monday" not in repr(calls[1]["sources"])
