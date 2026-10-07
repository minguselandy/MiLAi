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
    history_components,
    longmemeval_history,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, RunLimits
from milai_lab.memory.edit_units import render_revision_view
from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.memory.service import MemoryService
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners.edit_benchmarks import BenchmarkRun, reader_messages, source_batches


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
        assert actual["evidence_status"] == "insufficient"
        assert actual["semantic_support"] == "unchecked"
    assert "including null" in messages[0]["content"]
    assert "unlimited validity" in messages[0]["content"]


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
