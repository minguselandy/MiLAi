"""External controls consume real Store sources; all provider callbacks are synthetic."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langgraph.store.sqlite import SqliteStore
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from milai_lab.datasets.edit_benchmarks import ObservedSession
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_external import (
    EmbeddingTransport,
    ExternalRun,
    bound_author_context,
    reader_payload,
    run_external,
)


@pytest.mark.parametrize("phase", ["all", "predict", "score"])
def test_external_embedding_configuration_keeps_its_original_transport(
    tmp_path, monkeypatch, phase
):
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer.save(str(tokenizer_path))
    monkeypatch.setattr(
        "milai_lab.runners.edit_benchmarks.AutoTokenizer.from_pretrained",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    budget_path = tmp_path / "budget.json"
    write_json(budget_path, RunBudget(RunLimits(), budget_path).state)
    settings = {
        "experiment_name": "synthetic-external",
        "tokenizer_path": "synthetic",
        "budget_path": str(budget_path),
        "model": {"base_url": "http://synthetic.invalid/v1", "model": "synthetic"},
        "embedding": {"base_url": "http://synthetic.invalid/v1", "model": "synthetic"},
        "embedding_tokenizer_path": str(tokenizer_path),
        "embedding_context_tokens": 128,
        "embedding_batch_size": 2,
    }
    execution = ExternalRun(settings, tmp_path / "run", phase=phase)
    try:
        assert execution.embedding.execution is execution
        assert execution.retrieval_embedding_client is None
        assert execution._semantic_retriever() is None
    finally:
        execution.close()
    end = "accounting-end.json" if phase == "all" else f"accounting-{phase}-end.json"
    assert read_json(tmp_path / "run" / end) == read_json(
        tmp_path / "run/accounting-start.json"
    )


def test_author_expansion_limit_retains_complete_occurrences_and_reports_omissions():
    result = {
        "status": "COMPLETED",
        "context": "one\ntwo\nthree\n",
        "occurrences": [
            {"note_id": "one", "start": 0, "end": 4},
            {"note_id": "two", "start": 4, "end": 8},
            {"note_id": "three", "start": 8, "end": 14},
        ],
        "retrieved_note_ids": ["one"],
        "expanded_note_ids": ["two", "three"],
    }
    delivered = bound_author_context(result, 2)
    assert delivered["context"] == "one\n\ntwo\n"
    assert delivered["native_context"] == result["context"]
    assert delivered["omitted_occurrences"] == result["occurrences"][2:]
    assert delivered["native_occurrence_count"] == 3
    missing = bound_author_context({"status": "INCOMPLETE", "context": None}, 10)
    assert missing["context"] == "" and missing["delivered_occurrences"] == []
    messages = reader_payload(
        "Actual question",
        "T1",
        [{"id": "metadata-only", "revision": 1, "scope": {}, "content": "actual text"}],
    )
    payload = json.loads(messages[1]["content"])
    assert payload == {
        "question": "Actual question",
        "date": "T1",
        "memory_view": "retained_state",
        "memories": [{"revision": 1, "scope": {}, "content": "actual text"}],
    }


@pytest.mark.parametrize("thinking", [False, True])
def test_author_request_uses_configured_template_and_exact_context_boundary(tmp_path, thinking):
    execution = object.__new__(ExternalRun)
    execution.root = tmp_path
    tokens = 32 if thinking else 34
    execution.settings = {
        "model": {"enable_thinking": thinking, "max_tokens": 8192},
        "context_tokens": tokens + 8192 + 512,
    }
    execution.completion_key, execution.completion_serial = "formation", 0
    template_modes = []

    def apply_template(messages, *, tokenize, add_generation_prompt, enable_thinking):
        assert tokenize and add_generation_prompt
        template_modes.append(enable_thinking)
        return list(range(32 if enable_thinking else 34))

    execution.tokenizer = SimpleNamespace(apply_chat_template=apply_template)
    calls = []

    def chat(messages, *, response_format):
        calls.append((messages, response_format))
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"label":"blue"}'}}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": 5, "total_tokens": tokens + 5},
        }

    execution.client = SimpleNamespace(chat=chat)
    schema = {"type": "object", "properties": {"label": {"type": "string"}}}
    assert execution._completion("Give the note a short label.", schema) == '{"label":"blue"}'
    folder = tmp_path / "http/formation/author/1"
    request, response = read_json(folder / "request.json"), read_json(folder / "response.json")
    assert request["prompt_tokens"] == response["usage"]["prompt_tokens"] == tokens
    assert request["messages"] == calls[0][0]
    assert calls[0][1]["json_schema"]["schema"] == schema
    execution.settings["context_tokens"] -= 1
    with pytest.raises(ValueError, match="Author context unavailable"):
        execution._completion("Give the note a short label.", schema)
    assert len(calls) == 1
    assert template_modes == [thinking, thinking]
    assert not (tmp_path / "http/formation/author/2/request.json").exists()


@pytest.mark.parametrize("unknown", [False, True])
def test_embedding_resume_uses_confirmed_vectors_and_never_repeats_unknown_dispatch(
    tmp_path, unknown
):
    calls = []

    def embed(inputs, model):
        calls.append((inputs, model))
        if unknown:
            raise OSError("synthetic original response missing")
        return [[0.5, 0.5]]

    execution = SimpleNamespace(root=tmp_path, embedding_client=SimpleNamespace(embed=embed))
    first = EmbeddingTransport(execution)
    first.begin("occurred")
    if unknown:
        with pytest.raises(OSError):
            first.embed(["source"], "same")
    else:
        assert first.embed(["source"], "same") == [[0.5, 0.5]]
    restarted = EmbeddingTransport(execution)
    restarted.begin("occurred")
    if unknown:
        with pytest.raises(RuntimeError, match="Unconfirmed embedding"):
            restarted.embed(["source"], "same")
    else:
        assert restarted.embed(["source"], "same") == [[0.5, 0.5]]
    assert len(calls) == 1


@pytest.mark.parametrize("arm", ["RawRAG", "RollingSummary"])
def test_control_reopen_after_state_commit_preserves_one_opportunity_and_full_source(tmp_path, arm):
    callbacks = []
    execution = object.__new__(ExternalRun)
    execution.root = tmp_path / "run"
    execution.settings = {"arm": arm, "source_tokens": 30, "retrieval_limit": 10}
    execution.tokenizer = SimpleNamespace(encode=lambda text, **kwargs: list(text))

    def call(key, messages, *, structured):
        callbacks.append((key, messages))
        return json.dumps({"summary": "Preserve the actual condition."})

    execution.call = call
    execution.embedding = SimpleNamespace(
        begin=lambda key: None, encode=lambda texts: [[1.0, 0.0] for _ in texts]
    )
    observed = ObservedSession(
        "actual-session",
        "T1",
        (
            {
                "role": "user",
                "content": "条件甲。 Preserve beta outside nights.",
                "timestamp": "T1",
            },
            {"role": "assistant", "content": "Recorded the condition.", "timestamp": "T2"},
        ),
    )
    bank = tmp_path / "bank.sqlite"
    with SqliteStore.from_conn_string(str(bank)) as store:
        service = MemoryService(
            store,
            ("external", "alice"),
            "alice",
            tmp_path / "lock",
            mutation_contract="event_bound_v1",
        )
        formed = execution.maintain(service, observed, "actual-session")
        state = read_json(execution._state_path(service))
        revision = state["revision"]
        folder = execution.root / "maintenance" / "actual-session"
        coverage = read_json(folder / "source-coverage.json")
        assert coverage["original_characters"] == coverage["covered_characters"]
        assert len(service.sources()) == 2
        # Simulate the state commit preceding the outer checkpoint. Consumed
        # batches must recover from their receipts, without another writer call.
        (folder / "complete.json").unlink()
        for file in folder.glob("batch-*-complete.json"):
            file.unlink()
        callback_count = len(callbacks)
        assert execution.maintain(service, observed, "actual-session") == formed
        assert read_json(execution._state_path(service))["revision"] == revision
        assert len(callbacks) == callback_count
    with SqliteStore.from_conn_string(str(bank)) as store:
        service = MemoryService(
            store,
            ("external", "alice"),
            "alice",
            tmp_path / "lock",
            mutation_contract="event_bound_v1",
        )
        assert execution.maintain(service, observed, "actual-session") == formed
        assert len(service.sources()) == 2


@pytest.mark.parametrize("arm", ["RawRAG", "RollingSummary", "A-MEM", "B0", "B1", "B2", "M"])
def test_repeated_author_session_id_keeps_every_dated_occurrence_and_reopens(tmp_path, arm):
    execution = object.__new__(ExternalRun)
    execution.root = tmp_path / "run"
    execution.settings = {"arm": arm, "source_tokens": 1000, "retrieval_limit": 10}
    execution.tokenizer = SimpleNamespace(encode=lambda text, **kwargs: list(text))
    callbacks = []

    def call(key, messages, *, structured):
        callbacks.append(key)
        return json.dumps({"summary": "Actual observed text.", "proposals": []})

    execution.call = call
    execution.embedding = SimpleNamespace(
        begin=lambda key: None, encode=lambda texts: [[1.0, 0.0] for _ in texts]
    )
    execution._native = lambda service, key: SimpleNamespace(
        ingest=lambda batch, body, **kwargs: {"status": "COMPLETED"}
    )
    histories = [
        ObservedSession(
            "repeated-author-id",
            date,
            ({"role": "user", "content": text, "timestamp": date},),
        )
        for date, text in (
            ("T1", "Same original text."),
            ("T2", "Same original text."),
            ("T3", "Different observed text."),
        )
    ]
    bank = tmp_path / "bank.sqlite"
    with SqliteStore.from_conn_string(str(bank)) as store:
        service = MemoryService(
            store,
            ("external", "alice"),
            "alice",
            tmp_path / "lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        for ordinal, observed in enumerate(histories):
            key = f"longmemeval/question/session/{ordinal}"
            execution.maintain(service, observed, key)
            metadata = read_json(execution.root / "maintenance" / key / "source-occurrence.json")
            assert metadata["original_session_id"] == "repeated-author-id"
            assert metadata["original_date"] == observed.date
            actual = service.sources(metadata["source_session_id"])
            assert len(actual) == 1 and actual[0]["content"] == observed.turns[0]["content"]
            if arm not in {"B0", "B1", "B2", "M"}:
                batches = read_json(execution.root / "maintenance" / key / "batches.json")
                assert batches[0]["fragments"][0]["timestamp"] == observed.date
            else:
                delivery = read_json(
                    execution.root / "maintenance" / key / "batch-0000" / "delivery.json"
                )
                assert delivery["sources"][0]["timestamp"] == observed.date
        assert len({row["event_id"] for row in service.sources()}) == 3
        callback_count = len(callbacks)
    with SqliteStore.from_conn_string(str(bank)) as store:
        service = MemoryService(
            store,
            ("external", "alice"),
            "alice",
            tmp_path / "lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        for ordinal, observed in enumerate(histories):
            execution.maintain(service, observed, f"longmemeval/question/session/{ordinal}")
        assert len(service.sources()) == 3
        assert len(callbacks) == callback_count


@pytest.mark.parametrize("arm,interface", [
    (arm, interface) for arm in ["B0", "B1", "B2", "M"] for interface in ["I1", "I2"]
] + [("Append-only", "I2")])
def test_external_selected_edit_candidate_forms_own_state_and_common_reader(
    tmp_path, arm, interface
):
    execution = object.__new__(ExternalRun)
    execution.root = tmp_path / "run"
    execution.settings = {
        "arm": arm, "interface_version": interface, "source_tokens": 1000,
        "retrieval_limit": 10, "working_sets": False, "context_tokens": 65536,
        "model": {"max_tokens": 8192},
    }
    if arm == "Append-only":
        execution.settings["maintenance_recipe"] = "single_pass"
    execution.tokenizer = SimpleNamespace(encode=lambda text, **kwargs: list(text))
    execution.input_tokens = lambda messages: 100
    callbacks = []

    def call(key, messages, *, structured, **kwargs):
        callbacks.append(key)
        body = json.loads(messages[-1]["content"])
        if structured:
            assert kwargs["response_format"]["type"] == "json_schema"
            return json.dumps({"proposals": [{"action": "create", "units": [
                {"text": "Harbor labels use lowercase.", "evidence": ["e1"]}
            ]}]})
        assert body["question"] == "What case do Harbor labels use?"
        assert len(body["memories"]) == 1
        assert "Harbor labels use lowercase." in body["memories"][0]["content"]
        return "Lowercase."

    execution.call = call
    observed = ObservedSession("original-session", "2030-01-01", (
        {"role": "user", "content": "Harbor labels use lowercase.", "timestamp": "2030-01-01"},
    ))
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(
            store, ("external", arm, "owner"), "owner", tmp_path / "lock",
            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
        )
        assert service.records() == []
        formed = execution.maintain(service, observed, "observed/0")
        assert len(formed) == 1
        assert service.records()[0]["value"]["method_arm"] == arm
        assert service.records()[0]["value"]["method_version"] == (
            "milai_fact_append_v1" if arm == "Append-only" else "milai_edit_v2")
        before = service.records()
        assert execution.answer(service, "What case do Harbor labels use?", "2030-01-02", "qa/0") \
            == "Lowercase."
        assert service.records() == before
        assert len(callbacks) == 2


def test_external_deferred_score_reopens_saved_prediction_without_retrieval(tmp_path, monkeypatch):
    from milai_lab.runners import edit_benchmarks

    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer.save(str(tokenizer_path))
    monkeypatch.setattr(
        edit_benchmarks.AutoTokenizer, "from_pretrained",
        lambda *args, **kwargs: SimpleNamespace(encode=lambda text, **kw: list(text)),
    )
    budget_path = tmp_path / "budget.json"
    write_json(budget_path, RunBudget(RunLimits(), budget_path).state)
    dataset = tmp_path / "input.json"
    write_json(dataset, [{
        "question_id": "case", "question": "Marker?", "answer": "blue",
        "question_type": "single-session-user", "question_date": "2030-01-02",
        "haystack_sessions": [[{"role": "user", "content": "The marker is blue."}]],
        "haystack_dates": ["2030-01-01"], "haystack_session_ids": ["first"],
    }])
    settings = {
        "experiment_name": "external-deferred-fixture", "arm": "RawRAG",
        "tokenizer_path": "synthetic", "budget_path": str(budget_path),
        "model": {"base_url": "http://synthetic.invalid/v1", "model": "synthetic"},
        "embedding": {"base_url": "http://synthetic.invalid/v1", "model": "synthetic"},
        "embedding_tokenizer_path": str(tokenizer_path), "embedding_context_tokens": 128,
        "embedding_batch_size": 2, "source_tokens": 1000, "retrieval_limit": 10,
        "longmemeval": {"path": str(dataset), "questions": ["case"],
                       "official_checkout": "fixture"},
    }
    calls = []

    def call(self, key, messages, *, structured, **kwargs):
        calls.append(key)
        if key.endswith("/reader"):
            payload = json.loads(messages[1]["content"])
            assert "The marker is blue." in payload["memories"][0]["content"]
            return "Blue."
        assert messages == [{"role": "user", "content": "Score saved Blue."}]
        return "yes"

    class AuthorFixture:
        def __init__(self, checkout):
            pass

        def make_prompt(self, case, answer):
            assert answer == "Blue."
            return "Score saved Blue."

        def label(self, verdict):
            return verdict == "yes"

    monkeypatch.setattr(ExternalRun, "call", call)
    monkeypatch.setattr(EmbeddingTransport, "encode", lambda self, texts: [[1.0, 0.0]] * len(texts))
    monkeypatch.setattr(edit_benchmarks, "LongMemEvalOfficial", AuthorFixture)
    root = tmp_path / "run"
    run_external(settings, root, "predict")
    assert calls == ["longmemeval/case/answer/reader"]
    saved = root / "predictions/longmemeval/case/complete.json"
    original = saved.read_bytes()
    assert read_json(root / "terminal-predict.json")["status"] == "PREDICTIONS_SAVED"

    def forbidden(*args, **kwargs):
        raise AssertionError("Scoring cannot maintain, answer or encode again")

    monkeypatch.setattr(ExternalRun, "maintain", forbidden)
    monkeypatch.setattr(ExternalRun, "answer", forbidden)
    monkeypatch.setattr(EmbeddingTransport, "encode", forbidden)
    run_external(settings, root, "score")
    assert calls == ["longmemeval/case/answer/reader", "longmemeval/case/judge"]
    assert saved.read_bytes() == original
    assert read_json(root / "longmemeval-predictions.json")[0]["autoeval_label"] is True
    assert read_json(root / "terminal-score.json")["status"] == "COMPLETED_EXTERNAL_PHASE"
    assert not (root / "terminal.json").exists()
