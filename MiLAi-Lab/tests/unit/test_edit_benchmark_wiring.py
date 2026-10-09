"""Synthetic engineering checks; these are never public benchmark samples."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.embeddings import Embeddings
from langgraph.store.sqlite import SqliteStore
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from milai_lab.analysis.edit_official import LongMemEvalOfficial, author_functions
from milai_lab.datasets.edit_benchmarks import (
    ObservedSession,
    halumem_session,
    halumem_users,
    history_components,
    longmemeval_history,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, RunLimits
from milai_lab.memory.edit_units import evidence_status, render_revision_view, writer_projection
from milai_lab.memory.retrieval import SemanticRetriever, semantic_keys
from milai_lab.memory.service import MemoryService
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners.edit_benchmarks import (
    BenchmarkRun,
    UnconfirmedModelOutcome,
    reader_messages,
    run,
    source_batches,
)


def test_reader_shared_metadata_preserves_each_actual_source_and_time() -> None:
    clock = {"value": "2026-02-01T12:00:00", "precision": "second",
             "timezone_known": False, "calendar_context": "example-calendar"}

    def unit(key: str, role: str, end: str | None) -> dict[str, Any]:
        return {
            "unit_id": key, "text": "Same words, independently scoped.",
            "assertion": {"source_ref": "actual-source", "source_revision": 1,
                          "role": role, "kind": "reported", "occurred_at": "2026-01-01"},
            "temporal": {"effective_until": end, "query_time": "2026-02-01",
                         "time_values": {"effective_from": copy.deepcopy(clock)},
                         "bound_effective_limits": [{"from_time": copy.deepcopy(clock),
                                                     "until_time": None}],
                         "comparison_basis": {"effective_limits": "shared_floating_calendar"},
                         "status": "expired" if end else "effective_limits_unspecified"},
            "applies_under": ["condition-1"],
        }

    memories = [{
        "record_id": "actual-record", "revision": 2, "content": "Original retained text",
        "revision_evidence": [{"role": "assistant", "content": "Original witness"}],
        "applicability": {"units": [unit("u1", "user", None), unit("u2", "user", None),
                                    unit("u3", "assistant", "2026-01-31")],
                          "time_values": {"query_time": copy.deepcopy(clock)},
                          "source_table": {source: {"role": "user", "occurred_at": "same",
                                                     "time_values": {"reported_at": clock}}
                                           for source in ("source-a", "source-b")},
                          "relations": [{"source_unit": "condition-1", "target_unit": "u1"}]},
    }]
    before = copy.deepcopy(memories)
    messages = reader_messages("Current and historical?", "2026-02-01", memories)
    payload = json.loads(messages[1]["content"])

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                index = int(value["$ref"].removeprefix("#/shared/"))
                return expand(payload["shared"][index])
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    assert expand(payload["memories"]) == before
    assert memories == before
    delivered = payload["memories"][0]["applicability"]["units"]
    assert "$ref" in delivered[0]["assertion"]
    assert delivered[0]["assertion"] == delivered[1]["assertion"]
    assert delivered[2]["assertion"]["role"] == "assistant"
    assert delivered[2]["temporal"]["status"] == "expired"
    table = payload["memories"][0]["applicability"]["source_table"]
    assert set(table) == {"source-a", "source-b"}
    assert table["source-a"] == table["source-b"] and "$ref" in table["source-a"]
    assert any(isinstance(value, dict) and "precision" in value
               for value in payload["shared"])


def test_source_history_reader_retains_original_messages_without_metadata_refs() -> None:
    memories = [{"content": "Actual archived speech", "role": "assistant", "revision": 1}]
    payload = json.loads(reader_messages(
        "Who said this?", "2026-02-01", memories, memory_view="source_history",
    )[1]["content"])
    assert payload == {"question": "Who said this?", "date": "2026-02-01",
                       "memory_view": "source_history", "memories": memories}


def test_reader_semantic_projection_keeps_limits_and_explicit_unknown_overrides() -> None:
    source = {
        "source_ref": "actual-user-source", "source_revision": 1, "role": "user",
        "occurred_at": "2026-01-01T12:00:00", "observed_at": "2026-01-01T12:01:00Z",
        "calendar_context": "example-calendar", "kind": "reported",
    }
    state = {
        "representation": "conditioned_v1", "matter_description": "A scoped training plan",
        "units": [
            {"unit_id": "u1", "role": "content", "text": "Plan two rounds per shift.",
             "assertion": {**source, "applicability": {"scope": "each shift"}}},
            {"unit_id": "u2", "role": "condition", "text": "Only during January.",
             "assertion": {**source, "applicability": {
                 "effective_from": "2026-01-01", "effective_until": "2026-02-01"}}},
        ],
        "relations": [{"source_unit": "u2", "target_unit": "u1", "relation_type": "modifies"}],
    }
    view = render_revision_view(
        state, query_time="2026-02-02", query_calendar_context="example-calendar",
        version_time="2026-01-01T12:02:00Z",
    )
    # Nonmatching input remains explicit, including unknown overriding a known
    # parent clock/calendar and a differently precise parsed description.
    override = view["units"][1]
    override["assertion"].update(role="assistant", source_revision=None, occurred_at=None,
                                 calendar_context=None)
    override["temporal"].update(reported_at=None, captured_at="2026-01-01T12:03:00Z",
                                query_time=None, query_calendar_context=None)
    different_precision = {**view["time_values"]["query_time"], "precision": "hour"}
    override["temporal"]["time_values"]["query_time"] = different_precision
    unknown_precision = {**view["time_values"]["version_time"], "precision": None, "value": None}
    override["temporal"]["time_values"]["version_time"] = unknown_precision
    override["temporal"]["time_values"]["reported_at"] = None
    memories = [{
        "record_id": "actual-record", "revision": 1,
        "content": "Plan two rounds per shift. Only during January.",
        "revision_evidence": [{"role": "user", "content": "Original plan with its limits."}],
        "applicability": view,
    }]
    before = copy.deepcopy(memories)
    messages = reader_messages("Current or historical training plan?", "2026-02-02", memories)
    payload = json.loads(messages[1]["content"])

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                return expand(payload["shared"][int(value["$ref"].removeprefix("#/shared/"))])
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    row = expand(payload["memories"])[0]
    projected = row["applicability"]
    assert memories == before
    assert row["content"] == before[0]["content"]
    assert row["revision_evidence"] == before[0]["revision_evidence"]
    assert [unit["text"] for unit in projected["units"]] == [unit["text"] for unit in view["units"]]
    for key in ("relations", "historical_units", "future_units", "unresolved_units"):
        assert projected[key] == view[key]
    assert projected["semantic_support"] == "unchecked"
    origin = projected["source_table"][source["source_ref"]]
    original_source = view["source_table"][source["source_ref"]]
    assert origin == {key: value for key, value in original_source.items() if key != "time_values"}
    assert projected["units"][0]["assertion"] == {"source_ref": source["source_ref"],
                                                   "kind": "reported",
                                                   "applicability": {"scope": "each shift"}}
    actual_override = projected["units"][1]
    for key in ("role", "source_revision", "occurred_at", "calendar_context"):
        assert actual_override["assertion"][key] == override["assertion"][key]
    for key in ("reported_at", "captured_at", "query_time", "query_calendar_context"):
        assert actual_override["temporal"][key] == override["temporal"][key]
    assert actual_override["temporal"]["time_values"]["query_time"] == different_precision
    assert actual_override["temporal"]["time_values"]["version_time"] == unknown_precision
    assert actual_override["temporal"]["time_values"]["reported_at"] is None
    for actual, old in zip(projected["units"], view["units"], strict=True):
        for key in ("status", "comparison_basis", "retrospective", "reported_after_query"):
            assert actual["temporal"][key] == old["temporal"][key]
        bound = actual["temporal"]["bound_effective_limits"][0]
        assert bound["from"] == "2026-01-01" and bound["until"] == "2026-02-01"
        assert bound["from_time"]["precision"] == "day"
        assert bound["from_time"]["timezone_known"] is False
        assert "evidence_status" not in actual
        assert actual["semantic_support"] == "unchecked"
    assert "including null" in messages[0]["content"]
    assert "unlimited validity" in messages[0]["content"]

    # Optional stance links do not replace an actual report's primary Source or
    # retained support. Missing links are undeclared, not evidence against it.
    original_text = "Plan two rounds per shift. Only during January."
    support = {"evidence_id": "actual-user-fragment",
               "source_ref": source["source_ref"], "source_revision": 1,
               "start": 0, "end": len(original_text)}
    retained = copy.deepcopy(state)
    for item in [*retained["units"], *retained["relations"]]:
        item["evidence_refs"] = [support]

    def writer_input() -> tuple[dict[str, Any], dict[str, Any]]:
        return writer_projection({
            "records": [{"edit_state": retained}],
            "redelivered_sources": [{**source, **support, "text": original_text}],
        }, "I2", "M", allow_create=False,
            features={"source_metadata": True, "temporal_scope": True})

    packet, mapping = writer_input()
    assert packet["records"][0]["clauses"][0]["assertion"] == {
        "kind": "reported", "source": "s1", "applicability": {"scope": "each shift"},
    }
    assert packet["source_table"][0]["role"] == "user"
    assert packet["source_table"][0]["occurred_at"] == source["occurred_at"]
    assert mapping["units"]["u1"]["assertion"] == state["units"][0]["assertion"]
    assert mapping["units"]["u1"]["evidence_refs"] == [support]
    assert packet["historical_support"][0]["ranges"] == [{
        "source": "s1", "range": [0, len(original_text)],
    }]
    assert evidence_status(source) == "insufficient"  # Existing helper contract stays.
    for links, status in [
        ({"supports": [support]}, "supported"),
        ({"opposes": [support]}, "opposed"),
        ({"supports": [support], "opposes": [support]}, "both"),
        ({}, "insufficient"),
    ]:
        retained["units"][0]["assertion"]["evidence_links"] = links
        linked = render_revision_view(retained, query_time="2026-02-02")
        assert linked["units"][0]["evidence_status"] == status
        assert linked["units"][0]["assertion"]["source_ref"] == source["source_ref"]
        packet, mapping = writer_input()
        assert packet["records"][0]["clauses"][0]["assertion"]["evidence_status"] == status
        assert mapping["units"]["u1"]["evidence_refs"] == [support]


def test_observed_input_excludes_reference_and_future_material(tmp_path: Path) -> None:
    raw = {
        "start_time": "Jan 01, 2025, 10:00:00",
        "dialogue": [{"role": "user", "content": "actual speech", "timestamp": "now"}],
        "persona_info": "secret persona",
        "memory_points": ["gold"],
        "questions": [{"question": "future question", "answer": "gold answer"}],
    }
    first = {"uuid": "u", "sessions": [raw]}
    second = {"uuid": "later", "sessions": [{**raw, "start_time": "Jan 02, 2025, 10:00:00"}]}
    dataset = tmp_path / "selected.jsonl"
    # The unselected body is deliberately not JSON: even decoding it would fail.
    dataset.write_text('{"uuid":"other","body":UNSELECTED_BODY_WITH_u}\n'
                       + json.dumps(first) + "\n" + json.dumps(second) + "\n")
    users = halumem_users(dataset, ["later", "u"])
    assert users == [first, second]  # Original file order and full selected values.
    with pytest.raises(ValueError, match="HaluMem users missing") as error:
        halumem_users(dataset, ["missing-z", "u", "missing-a"])
    assert str(error.value) == "HaluMem users missing: ['missing-a', 'missing-z']"
    observed = halumem_session(users[0]["uuid"], 0, users[0]["sessions"][0])
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


def test_incomplete_response_remains_failed_and_charged_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Tokenizer:
        def apply_chat_template(self, *args: object, **kwargs: object) -> list[int]:
            return [1, 2]

        def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
            return list(range(len(text)))

    attempts = []

    def provider(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        messages = json.loads(request.read())["messages"]
        payload = json.loads(messages[-1]["content"]) if len(messages) > 1 else {}
        if "delivery" in payload:
            assert "synthetic-answer" not in str(payload)
            delivery = payload["delivery"]
            source = delivery["sources"][0]
            old = delivery["records"][0] if delivery["records"] else None
            proposal = {
                "action": "rewrite" if old else "create",
                "units": [{"text": source["text"], "evidence": [source["evidence_id"]]}],
            }
            if old:
                proposal.update(target_record=old["record_id"], base_revision=old["revision"])
            content = json.dumps({"proposals": [proposal]})
            finish = "stop"
        else:
            finish = (
                "length" if not payload or payload["question"] == "BlueProject first?" else "stop"
            )
            content = "partial" if finish == "length" else payload["memories"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": finish, "message": {"content": content}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 7, "total_tokens": 9},
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

        sessions = []
        for ordinal, day in enumerate(("Monday", "Tuesday")):
            stamp = f"Jan 0{ordinal + 1}, 2030, 09:00:00"
            questions = ["BlueProject first?", "BlueProject second?"] if ordinal == 0 else [
                "BlueProject after?",
            ]
            sessions.append({
                "start_time": stamp, "end_time": stamp,
                "dialogue": [{"role": "user", "content": "BlueProject " + day,
                              "timestamp": stamp}],
                "memory_points": [],
                "questions": [{"question": question, "answer": "synthetic-answer", "evidence": []}
                              for question in questions],
            })
        dataset = tmp_path / "synthetic.jsonl"
        dataset.write_text(json.dumps({"uuid": "synthetic", "sessions": sessions}) + "\n")
        execution.root = tmp_path / "history"
        execution.settings.update(arm="B0", source_tokens=4096, retrieval_limit=10,
            halumem={"path": str(dataset), "users": ["synthetic"],
                     "official_checkout": str(tmp_path / "synthetic-author")})
        with pytest.raises(ValueError, match="incomplete: length"):
            execution.halumem("predict")
        assert not (execution.root / "predictions/halumem/synthetic/0/complete.json").exists()
        assert len(attempts) == 3  # Initial check, committed Writer, failed first Reader.
        execution.settings["halumem"]["reader_failure_policy"] = "record_confirmed_length"
        assert execution.halumem("predict") == {
            "status": "PREDICTIONS_SAVED", "sessions": 2, "judge_calls": 0,
            "complete_answers": 2, "known_reader_failures": 1,
        }
        assert len(attempts) == 6
        prediction_path = execution.root / "predictions/halumem/synthetic/0/complete.json"
        first_prediction = read_json(prediction_path)
        failed = first_prediction["prediction"]["questions"][0]
        assert failed["hypothesis"] is None
        assert failed["reader_failure"]["finish_reason"] == "length"
        for key in ("response_ref", "failure_ref"):
            assert (execution.root / failed["reader_failure"][key]).exists()
        final_prediction = read_json(
            execution.root / "predictions/halumem/synthetic/1/complete.json"
        )
        assert len(final_prediction["state"]) == 1
        assert final_prediction["state"][0]["value"]["revision"] == 2
        assert "Tuesday" in final_prediction["state"][0]["value"]["content"]

        scored_questions = []

        class Official:
            def __init__(self, *args: Any) -> None:
                pass

            def score(self, name: str, *args: str) -> dict[str, Any]:
                if name == "question":
                    assert isinstance(args[-1], str)
                    scored_questions.append(args[0])
                    return {"evaluation_result": "Correct" if len(scored_questions) == 1
                            else "original-invalid-label"}
                return {"accuracy_score": 2}

            def aggregate_results(self, records: dict[str, Any]) -> dict[str, Any]:
                return copy.deepcopy(records)

        monkeypatch.setattr("milai_lab.runners.edit_benchmarks.HaluMemOfficial", Official)
        original = prediction_path.read_bytes()
        unmarked = copy.deepcopy(first_prediction)
        unmarked["prediction"]["questions"][0].pop("reader_failure")
        write_json(prediction_path, unmarked)
        with pytest.raises(ValueError, match="lacks a complete answer or failure"):
            execution.halumem("score")
        assert not scored_questions
        prediction_path.write_bytes(original)
        scored = execution.halumem("score")["question_answering_records"]
        assert len(scored) == 3 and scored[0]["result_type"] is None
        assert scored[0]["system_response"] is None
        assert scored[0]["reader_failure"] == failed["reader_failure"]
        assert scored[1]["result_type"] == "Correct"
        assert scored[2]["result_type"] == "original-invalid-label"
        assert scored_questions == ["BlueProject second?", "BlueProject after?"]
        assert len(attempts) == 6 and prediction_path.read_bytes() == original

        execution.budget = budget
        execution.before = copy.deepcopy(budget.state)
        monkeypatch.setattr(execution, "close", lambda: None)
        monkeypatch.setattr("milai_lab.runners.edit_benchmarks.BenchmarkRun",
                            lambda *args, **kwargs: execution)
        execution.settings["experiment_name"] = "synthetic-length"
        run(execution.settings, execution.root, "halumem", "predict")
        assert read_json(execution.root / "terminal-predict.json")["prediction_summary"] == {
            "status": "PREDICTIONS_SAVED", "sessions": 2, "judge_calls": 0,
            "complete_answers": 2, "known_reader_failures": 1,
        }
        assert len(attempts) == 6

        execution.root = tmp_path / "stopped"
        monkeypatch.setattr(execution, "maintain", lambda *args: [])
        selection_response = (
            execution.root / "http/halumem/synthetic/0/qa/0/view/select-0/response.json"
        )
        write_json(selection_response, {
            "choices": [{"finish_reason": "length"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 7, "total_tokens": 9},
        })
        for error in (ValueError("Provider output incomplete: length"),
                      ValueError("Context unavailable without loss: 2048 input tokens"),
                      BudgetExceeded("synthetic budget"), UnconfirmedModelOutcome("unknown")):
            def failed_answer(*args: Any, error: Exception = error) -> str:
                raise error

            monkeypatch.setattr(execution, "answer", failed_answer)
            with pytest.raises(type(error), match=str(error)):
                execution.halumem("predict")
        incomplete_usage = {
            "choices": [{"finish_reason": "length", "message": {"content": "partial"}}],
            "usage": {"total_tokens": 9},
        }
        final_response = execution.root / "http/halumem/synthetic/0/qa/0/response.json"
        write_json(final_response, incomplete_usage)
        monkeypatch.setattr(execution, "answer",
                            lambda *args: execution.completed_content(incomplete_usage))
        with pytest.raises(ValueError, match="incomplete: length"):
            execution.halumem("predict")
        assert not final_response.with_name("failure.json").exists()
        assert not (execution.root / "predictions/halumem/synthetic/0/complete.json").exists()
        assert len(attempts) == 6
    assert budget.state["generation_requests"] == 6
    assert budget.state["generation"]["known_tokens"] == 54
    assert read_json(tmp_path / "http" / "a" / "failure.json")["type"] == "ValueError"


def test_shared_reader_switches_reloads_fixed_pool_without_capturing_qa(tmp_path: Path) -> None:
    class ReaderTokenizer:
        def apply_chat_template(self, *args: object, **kwargs: object) -> list[int]:
            return [1, 2]

    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root, execution.settings = tmp_path, {"retrieval_limit": 10}

    def seed_call(key: str, messages: list[dict[str, str]], *, structured: bool) -> str:
        source = json.loads(messages[1]["content"])["new_sources"][0]["source_ref"]
        return json.dumps({"operations": [
            {"target_record": None, "content": body, "kind": "semantic",
             "scope": {}, "source_refs": [source]}
            for body in ("The marker is blue.", "The alarm is soft.")
        ]})

    execution.call = seed_call
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(
            store, ("reader-view-example", "owner"), "owner", tmp_path / "bank.lock",
            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
        )
        execution.maintain(service, ObservedSession(
            "save", "2030-01-01", ({"role": "user", "content":
            "The marker is blue. The alarm is soft.", "timestamp": "2030-01-01"},),
        ), "save")
        before, source_count = copy.deepcopy(service.records()), len(service.sources())
        identifiers = {row["value"]["content"]: row["id"] for row in before}
        marker, alarm = identifiers["The marker is blue."], identifiers["The alarm is soft."]
        execution.settings = {"retrieval_limit": 10, "memory_view_mode": "state_driven",
                              "context_tokens": 4096, "model": {"max_tokens": 100}}
        execution.tokenizer = ReaderTokenizer()
        execution.call = BenchmarkRun.call.__get__(execution)
        payloads = []
        question = (
            "Describe the current marker and alarm, and distinguish original wording "
            "from what was saved earlier."
        )
        date = "2030-01-02"
        history_goal = "Identify actual saved history relevant to this question."
        mixed_goal = "Compare current arrangements, original wording and actual saved history."

        def provider(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            payload = json.loads(wire["messages"][1]["content"])
            payloads.append(payload)
            assert payload["question"] == question and payload["date"] == date
            assert payload["memory_view"] == "retained_state"
            bodies = [memory["content"] for memory in payload["memories"]]
            index = len(payloads)
            if index == 1:
                assert bodies == []
                assert payload["memory_view_state"]["read_goal"] is None
                selected, keep, done = [marker], False, False
            elif index == 2:
                assert bodies == ["The marker is blue."]
                assert payload["memory_view_state"]["read_goal"] == history_goal
                selected, keep, done = [alarm], False, False
            elif index == 3:
                assert bodies == ["The alarm is soft."]
                assert payload["memory_view_state"]["read_goal"] == history_goal
                selected, keep, done = [marker, alarm], False, False
            elif index == 4:
                assert set(bodies) == set(identifiers)
                assert payload["memory_view_state"]["read_goal"] == mixed_goal
                selected, keep, done = [], True, True
            else:
                assert index == 5 and set(bodies) == set(identifiers)
                assert payload["read_goal"] == mixed_goal
                assert {memory["revision"] for memory in payload["memories"]} == {1}
            if index < 5:
                selection = {"record_ids": selected, "keep_resident": keep, "done": done}
                if index == 1:
                    selection["read_goal"] = history_goal
                elif index == 3:
                    selection["read_goal"] = mixed_goal
                elif index == 4:
                    selection["read_goal"] = None
                content = json.dumps(selection)
            else:
                content = (
                    "The marker is blue and the alarm is soft; older saved versions are absent."
                )
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": content}}], "usage": {"total_tokens": 9}})

        budget = RunBudget(RunLimits(generation_requests=5), tmp_path / "budget.json")
        with VLLMClient(VLLMConfig("http://synthetic/v1", "test", max_tokens=100, max_calls=5),
                         transport=httpx.MockTransport(provider), budget=budget) as client:
            execution.client = client
            answer = execution.answer(service, question, date, "qa")
            assert execution.answer(service, question, date, "qa") == answer
        assert len(payloads) == 5 and budget.state["generation_requests"] == 5
        assert service.records() == before and len(service.sources()) == source_count
        state = read_json(tmp_path / "http/qa/memory-view.json")
        assert state["steps"] == 4 and state["complete"]
        assert state["read_goal"] == mixed_goal
        assert {ref["id"] for ref in state["resident_refs"]} == {marker, alarm}
        assert all(ref["view"] == "current_at_snapshot" for ref in state["resident_refs"])
        assert all("content" not in ref for ref in state["resident_refs"])


def test_shared_reader_staged_accepts_legacy_selection_without_extra_reads(tmp_path: Path) -> None:
    class ReaderTokenizer:
        def apply_chat_template(self, *args: object, **kwargs: object) -> list[int]:
            return [1, 2]

    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root, execution.settings = tmp_path, {
        "memory_view_mode": "staged", "context_tokens": 4096, "model": {"max_tokens": 100},
    }
    execution.tokenizer = ReaderTokenizer()
    question, date, key = "What marker applies on weekdays?", "2030-01-02", "qa"
    memories = [{"record_id": "actual-marker", "revision": 2,
                 "matter_description": "Marker", "content": "The marker is blue on weekdays.",
                 "scope": {"weekday_only": True}, "revision_evidence": []}]
    snapshot = tmp_path / "http" / key / "retrieval.json"
    write_json(snapshot, memories)
    original = snapshot.read_bytes()
    payloads = []

    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.read())["messages"][1]["content"])
        payloads.append(payload)
        assert payload["question"] == question and payload["date"] == date
        assert payload["memory_view"] == "retained_state"
        if len(payloads) == 1:
            assert payload["memories"] == []
            assert payload["memory_view_state"]["read_goal"] is None
            assert set(payload["response_schema"]["required"]) == {
                "record_ids", "keep_resident", "done"}
            content = json.dumps({"record_ids": ["actual-marker"],
                                  "keep_resident": False, "done": False})
        else:
            assert len(payloads) == 2 and payload["memories"] == memories
            assert "read_goal" not in payload
            content = "The marker is blue on weekdays."
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": content}}], "usage": {"total_tokens": 9}})

    budget = RunBudget(RunLimits(generation_requests=2), tmp_path / "budget.json")
    with VLLMClient(VLLMConfig("http://synthetic/v1", "test", max_tokens=100, max_calls=5),
                     transport=httpx.MockTransport(provider), budget=budget) as client:
        execution.client = client
        answer, used = execution.answer_material(question, date, key, memories)
        assert execution.answer_material(question, date, key, memories) == (answer, used)
    assert len(payloads) == 2 and budget.state["generation_requests"] == 2
    assert used == memories and snapshot.read_bytes() == original
    state = read_json(tmp_path / "http" / key / "memory-view.json")
    assert state["steps"] == 1 and state["complete"] and state["read_goal"] is None
    assert len(state["resident_refs"]) == 1
    assert state["resident_refs"][0]["view"] == "current_at_snapshot"
    assert state["resident_refs"][0]["revision"] == 2


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


class Vectors(Embeddings):
    def __init__(self) -> None:
        self.documents: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [[1.0, 0.0] if "tea" in text else [0.0, 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0, 1.0] if "2030" in text else [1.0, 0.0]


def seed(service: MemoryService, key: str, body: str, *, render: str = "") -> None:
    source = service.capture_user("synthetic", key, body)["source_ref"]
    current = {
        "revision": 1,
        "content": render or body,
        "source_ref": source,
        "source_refs": [source],
        "edit_state": {"matter_description": "", "units": [{"text": body}]},
    }
    service.store.put(
        service.namespace,
        key,
        {
            "_v13_1": {"owner": service.owner, "current": current, "history": [current]},
        },
        index=False,
    )


def test_metadata_misses_and_full_lexical_page_use_the_same_visible_bank(tmp_path: Path) -> None:
    vectors = Vectors()
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(store, ("memory", "alice"), "alice", tmp_path / "lock")
        seed(service, "food", "Green tea is preferred.", render="Unmatched display metadata")
        seed(service, "travel", "Airplane travel.", render="Collection date 14")
        before = service.records()
        frozen = service.search("14 refreshment", include_raw=False)["records"]
        assert [row["id"] for row in frozen] == ["travel"]
        service.semantic_retriever = SemanticRetriever(vectors, 2)
        result = service.search("14 refreshment", limit=1, include_raw=False)
        assert result["retrieval"] == "dense_cosine"
        assert [row["id"] for row in result["records"]] == ["food"]
        # Store timestamps can tie; dense retrieval must encode both whole bodies
        # exactly once and keep their vectors aligned, regardless of corpus order.
        assert sorted(vectors.documents) == ["\nAirplane travel.", "\nGreen tea is preferred."]
        assert service.records() == before
        seed(service, "dated", "Tea only on 2030-02-01.")
        dated = service.search("2030", limit=1, include_raw=False)["records"]
        assert dated[0]["id"] == "dated"
        assert dated[0]["value"]["edit_state"]["units"][0]["text"] == "Tea only on 2030-02-01."
        for ordinal in range(10):
            seed(service, f"a{ordinal}", "slot information")
        other = MemoryService(store, ("memory", "bob"), "bob", tmp_path / "other-lock")
        seed(other, "foreign", "Green tea is preferred.")
        rows = service.search("slot refreshment", limit=4, include_raw=False)["records"]
        assert len(rows) == 4 and len({row["id"] for row in rows}) == 4
        assert "food" in {row["id"] for row in rows}
        assert "foreign" not in {row["id"] for row in rows}


def test_cache_tracks_current_body_and_withdrawal_without_erasing_history(tmp_path: Path) -> None:
    vectors = Vectors()
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(
            store,
            ("memory", "alice"),
            "alice",
            tmp_path / "lock",
            functional_contract="functional_v1",
            semantic_retriever=SemanticRetriever(vectors, 2),
        )
        seed(service, "a", "Green tea is preferred.")
        seed(service, "b", "Music interests.")
        assert service.search("refreshment", limit=1, include_raw=False)["records"][0]["id"] == "a"
        service.search("refreshment", limit=1, include_raw=False)
        assert len(vectors.documents) == 2
        item = store.get(service.namespace, "a")
        assert item is not None
        value = item.value
        old = value["_v13_1"]["current"]
        current = {
            **old,
            "revision": 2,
            "edit_state": {"matter_description": "", "units": [{"text": "Music instead."}]},
        }
        value["_v13_1"]["current"] = current
        value["_v13_1"]["history"] = [old, current]
        store.put(service.namespace, "a", value, index=False)
        service.search("refreshment", limit=1, include_raw=False)
        assert vectors.documents[-1] == "\nMusic instead."
        current["retracted"] = True
        store.put(service.namespace, "a", value, index=False)
        rows = service.search("refreshment", limit=2, include_raw=False)["records"]
        assert [row["id"] for row in rows] == ["b"]
        assert (
            service.read("a", 1)["value"]["edit_state"]["units"][0]["text"]
            == "Green tea is preferred."
        )

        class GranularVectors(Vectors):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                self.documents.extend(texts)
                return [
                    [0.0, 1.0] if "FILLER" in text else
                    [1.0, 0.0] if "Green tea." in text else [0.6, 0.8]
                    for text in texts
                ]

        def qualified(key: str) -> None:
            seed(service, key, "Green tea. Only on weekdays. FILLER")
            item = store.get(service.namespace, key)
            assert item is not None
            current = item.value["_v13_1"]["current"]
            current["edit_state"] = {
                "matter_description": "Refreshment choice",
                "units": [
                    {"unit_id": "u1", "role": "content", "text": "Green tea."},
                    {"unit_id": "u2", "role": "condition", "text": "Only on weekdays."},
                    {"unit_id": "u3", "role": "content", "text": "FILLER"},
                ],
                "relations": [{"source_unit": "u2", "target_unit": "u1",
                               "relation_type": "modifies"}],
            }
            item.value["_v13_1"]["history"] = [current]
            store.put(service.namespace, key, item.value, index=False)

        qualified("z")
        granular_vectors = GranularVectors()
        service.semantic_retriever = SemanticRetriever(granular_vectors, 2)
        assert [row["id"] for row in service.search(
            "refreshment", limit=2, include_raw=False,
        )["records"]] == ["b", "z"]

        service.semantic_retriever = SemanticRetriever(
            granular_vectors, 2, granularity="record_units",
        )
        rows = service.search("refreshment", limit=2, include_raw=False)["records"]
        assert [row["id"] for row in rows] == ["z", "b"]
        assert rows[0] == service.read("z")  # Complete revision, including the other clauses.
        keys = semantic_keys(rows[0]["value"], granularity="record_units")
        assert len(keys) == 4
        assert keys[1] == (
            "Refreshment choice\nGreen tea.\nmodifies: Only on weekdays. -> Green tea."
        )
        embedded = len(granular_vectors.documents)
        service.search("refreshment", limit=2, include_raw=False)
        assert len(granular_vectors.documents) == embedded

        qualified("c")
        rows = service.search("refreshment", limit=2, include_raw=False)["records"]
        assert [row["id"] for row in rows] == ["c", "z"]  # Ties use record IDs; K counts records.
        item = store.get(service.namespace, "z")
        assert item is not None
        old = item.value["_v13_1"]["current"]
        current = copy.deepcopy(old)
        current["revision"] = 2
        current["edit_state"]["units"][0]["text"] = "Music interests."
        item.value["_v13_1"]["current"] = current
        item.value["_v13_1"]["history"] = [old, current]
        store.put(service.namespace, "z", item.value, index=False)
        embedded = len(granular_vectors.documents)
        rows = service.search("refreshment", limit=3, include_raw=False)["records"]
        assert [row["id"] for row in rows] == ["c", "b", "z"]
        # Refresh whole + both linked unit keys; retain the unaffected unit's vector.
        assert len(granular_vectors.documents) - embedded == 3
        assert rows[-1] == service.read("z") and rows[-1]["value"]["revision"] == 2
        assert service.read("z", 1)["value"]["edit_state"]["units"][0]["text"] == "Green tea."


def test_embedding_failure_is_not_silent_lexical_success_or_a_memory_write(tmp_path: Path) -> None:
    class Failed(Vectors):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise ConnectionError("synthetic embedding failure")

    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(
            store,
            ("memory", "alice"),
            "alice",
            tmp_path / "lock",
            semantic_retriever=SemanticRetriever(Failed(), 2),
        )
        seed(service, "a", "Green tea is preferred.")
        before, sources = service.records(), service.sources()
        with pytest.raises(ConnectionError, match="synthetic embedding failure"):
            service.search("tea", include_raw=False)
        assert service.records() == before and service.sources() == sources


def test_each_embedding_batch_is_recorded_before_http_and_billed_once(tmp_path: Path) -> None:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    trace = BenchmarkRun.__new__(BenchmarkRun)
    trace.root, trace._embedding_serial = tmp_path, 0
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    sent: list[dict[str, Any]] = []

    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        path = tmp_path / "http/embedding" / f"{len(sent) + 1:06d}" / "request.json"
        assert json.loads(path.read_text()) == body
        sent.append(body)
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": [1, 0]} for i, _ in enumerate(body["input"])],
                "usage": {"total_tokens": len(body["input"])},
            },
        )

    with VLLMClient(
        VLLMConfig("http://synthetic.invalid/v1", "synthetic"),
        emit=trace._embedding_trace,
        transport=httpx.MockTransport(provider),
        budget=budget,
    ) as client:
        embeddings = MeteredEmbeddings(
            client,
            "synthetic",
            {"tokenizer_path": str(tmp_path / "tokenizer.json"), "context_tokens": 128},
            dimension=2,
            batch_size=2,
        )
        assert len(embeddings.embed_documents(["a", "b", "c"])) == 3
    assert len(sent) == 2 and budget.state["embedding"]["known_tokens"] == 3
    assert budget.state["embedding"]["unknown_usage"] == 0
    assert budget.state["generation_requests"] == 0
    assert len(list((tmp_path / "http/embedding").glob("*/response.json"))) == 2


def test_embedding_budget_rejection_is_recorded_as_not_sent(tmp_path: Path) -> None:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    trace = BenchmarkRun.__new__(BenchmarkRun)
    trace.root, trace._embedding_serial = tmp_path, 0
    budget = RunBudget(RunLimits(embedding_tokens=0), tmp_path / "budget.json")

    def denied(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Budget rejected input must not reach HTTP")

    with VLLMClient(
        VLLMConfig("http://synthetic.invalid/v1", "synthetic"),
        emit=trace._embedding_trace,
        transport=httpx.MockTransport(denied),
        budget=budget,
    ) as client:
        embeddings = MeteredEmbeddings(
            client,
            "synthetic",
            {"tokenizer_path": str(tmp_path / "tokenizer.json"), "context_tokens": 128},
            dimension=2,
            batch_size=2,
        )
        with pytest.raises(BudgetExceeded):
            embeddings.embed_query("input")
    failure = json.loads((tmp_path / "http/embedding/000001/failure.json").read_text())
    assert failure["event"] == "vllm_budget_rejected" and failure["request_sent"] is False
    assert budget.state["embedding"]["charged_tokens"] == 0
    assert budget.state["embedding"]["unknown_usage"] == 0
