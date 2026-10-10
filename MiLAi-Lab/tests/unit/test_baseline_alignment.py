"""The aligned entry reuses the online loop and never sends evaluator fields to backends."""

from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.contracts.memory_backend import IngestionResult, MemorySession, RetrievalResult
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.runners import edit_benchmarks
from milai_lab.runners.baseline_alignment import (
    BACKENDS,
    AlignmentRun,
    alignment_settings,
    prepare_alignment,
    run_alignment_arm,
)


def configuration() -> dict[str, Any]:
    return read_json(Path(__file__).parents[2] / "configs/milai-baseline-alignment-local-v1.json")


def source_user() -> dict[str, Any]:
    sessions = []
    for index in (1, 0):
        clock = f"Jan 0{index + 1}, 2025, 12:00:00"
        sessions.append({
            "start_time": clock, "end_time": clock,
            "dialogue": [{"role": "user", "content": f"actual source {index}",
                          "timestamp": clock, "has_answer": True}],
            "memory_points": [{"memory_content": "PRIVATE REFERENCE", "is_update": "False",
                               "memory_type": "event", "memory_source": "dialogue",
                               "importance": 1, "original_memories": []}],
            "questions": [{"question": f"query {index}", "answer": "PRIVATE ANSWER",
                           "evidence": []}],
        })
    return {"uuid": "opaque-owner", "persona_info": "PRIVATE PERSONA", "sessions": sessions}


class ActualReturnBackend:
    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.events: list[tuple[str, int]] = []

    def ingest(self, session: MemorySession, *, key: str) -> IngestionResult:
        self.history.append({"session_id": session.session_id, "date": session.date,
                             "turns": session.turns})
        self.events.append(("ingest", len(self.history)))
        return {"session_id": session.session_id, "completed": True,
                "native_return": {"settled": True}, "session_output": None,
                "usage": {"status": "unobserved"}}

    def retrieve(self, question: str, date: str, *, key: str, limit: int) -> RetrievalResult:
        assert limit == 20
        self.events.append((question, len(self.history)))
        return {"materials": copy.deepcopy(self.history), "native_return": self.history,
                "returned_count": len(self.history), "source_mapping": "original-sessions",
                "usage": {"status": "unobserved"}}

    def close(self) -> None:
        pass


def test_prepare_keeps_qa_and_update_budgets_and_opaque_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.runners import baseline_alignment

    monkeypatch.setattr(baseline_alignment, "halumem_users", lambda *_: [source_user()])
    config = configuration()
    root = tmp_path / "prepared"
    first = prepare_alignment(config, root)
    assert first["per_backend_opportunities"] == {"sessions": 2, "qa": 2, "native_updates": 0}
    assert first["per_user_opportunities"]["opaque-owner"]["session_ordinals"] == [1, 0]
    banks = [first["bank_ids"][backend]["opaque-owner"] for backend in BACKENDS]
    assert len(set(banks)) == 3
    assert all("opaque-owner" not in bank for bank in banks)
    assert first == prepare_alignment(config, root)
    assert not (root / "banks").exists() and not (root / "http").exists()
    other = prepare_alignment(config, tmp_path / "independent")
    assert other["bank_ids"] != first["bank_ids"]
    settings = alignment_settings(config, "MiLAi-memory-only")
    assert (settings["retrieval_limit"]
            == config["entrypoints"]["benchmark"]["retrieval_limit"] == 10)
    assert settings["alignment"]["qa_top_k"] == 20
    assert settings["alignment"]["update_top_k"] == 10
    assert settings["memory_view_mode"] == "direct"
    assert settings["maintenance_recipe"] == "extract_then_edit"


def test_native_completion_wait_is_forwarded_separately_from_model_http_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.integrations.memory import hindsight

    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings = alignment_settings(configuration(), BACKENDS[1])
    execution.settings["alignment_bank_ids"] = {"opaque-owner": "h-u1-r1"}
    execution.root, execution.backends = tmp_path, {}
    backend, received = ActualReturnBackend(), []

    def construct(root: Path, **kwargs: Any) -> ActualReturnBackend:
        received.append((root, kwargs))
        return backend

    monkeypatch.setattr(hindsight, "HindsightBackend", construct)
    monkeypatch.setattr(execution, "_start_native_service", lambda: None)
    assert execution._backend(SimpleNamespace(owner="opaque-owner")) is backend
    assert received == [(tmp_path / "native-banks/opaque-owner", {
        "bank_id": "h-u1-r1", **execution.settings["alignment"]["hindsight"],
    })]
    assert received[0][1]["completion_timeout"] == 1800
    assert execution.settings["model"]["timeout"] == 300
    assert execution.settings["alignment"]["hindsight_service"]["environment"][
        "HINDSIGHT_API_LLM_TIMEOUT"] == "300"


def test_native_persistence_restores_identity_only_after_successful_closure(tmp_path: Path) -> None:
    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings = alignment_settings(configuration(), "Hindsight-native-local-recall")
    native = execution.settings["alignment"]["hindsight_service"]
    previous = tmp_path / "old-arm/native-service"
    home = tmp_path / "home"
    database = "pg0://milai_saved?unix_socket_directories=%2Fcra%2Fsocket"
    write_json(previous.parent / "terminal-predict.json", {
        "status": "PREDICTIONS_SAVED", "resources_settled": True,
    })
    write_json(previous / "closed.json", {
        "processes_closed": True, "remaining_uid_processes": [],
    })
    deployment = {"uid": 996, "home": str(home), "version": native["version"],
                  "distribution": native["distribution"], "environment": {
                      **native["environment"], "HINDSIGHT_API_DATABASE_URL": database,
                      "HINDSIGHT_API_DATABASE_SCHEMA": "milai_saved",
                      "HINDSIGHT_API_LLM_MODEL": execution.settings["model"]["model"],
                      "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL": (
                          execution.settings["embedding"]["model"]),
                  }}
    write_json(previous / "configuration.json", deployment)
    write_json(previous / "started.json", {"instance": "milai_saved"})
    assert execution._restored_native_database(previous, 996, home) == ("milai_saved", database)
    with pytest.raises(ValueError, match="owner or version"):
        execution._restored_native_database(previous, 997, home)
    deployment["environment"]["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"] = "another-model"
    write_json(previous / "configuration.json", deployment)
    with pytest.raises(ValueError, match="model changed"):
        execution._restored_native_database(previous, 996, home)
    deployment["environment"]["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"] = (
        execution.settings["embedding"]["model"])
    deployment["environment"]["HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS"] = "1024"
    write_json(previous / "configuration.json", deployment)
    with pytest.raises(ValueError, match="configuration changed"):
        execution._restored_native_database(previous, 996, home)
    deployment["environment"].pop("HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS")
    deployment["environment"]["HINDSIGHT_API_DATABASE_SCHEMA"] = "different"
    write_json(previous / "configuration.json", deployment)
    with pytest.raises(ValueError, match="instance and schema"):
        execution._restored_native_database(previous, 996, home)
    write_json(previous.parent / "terminal-predict.json", {
        "status": "FAILED", "resources_settled": True,
    })
    with pytest.raises(ValueError, match="confirmed predictions and closure"):
        execution._restored_native_database(previous, 996, home)


def test_existing_online_loop_delivers_only_current_observed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration()
    settings = alignment_settings(config, "RawRAG-local")
    settings["halumem"]["users"] = ["opaque-owner"]
    monkeypatch.setattr(edit_benchmarks, "halumem_users", lambda *_: [source_user()])
    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings, execution.root, execution.phase = settings, tmp_path, "predict"
    execution.backends = {}
    backend = ActualReturnBackend()
    monkeypatch.setattr(execution, "_backend", lambda _: backend)
    monkeypatch.setattr(execution, "_semantic_retriever", lambda: None)
    delivered = []

    def answer(question: str, date: str, key: str, materials: list[dict[str, Any]]) -> Any:
        delivered.append(copy.deepcopy(materials))
        return "scripted answer", materials

    monkeypatch.setattr(execution, "answer_material", answer)
    result = execution.halumem("predict")
    assert result["sessions"] == 2 and result["complete_answers"] == 2
    assert result["judge_calls"] == 0
    assert backend.events == [("ingest", 1), ("query 0", 1), ("ingest", 2), ("query 1", 2)]
    assert len(delivered[0]) == 1 and len(delivered[1]) == 2
    for session in backend.history:
        assert set(session) == {"session_id", "date", "turns"}
        assert set(session["turns"][0]) == {"role", "content", "timestamp"}
    assert "PRIVATE" not in repr(backend.history)
    assert "query" not in repr(backend.history) and "scripted answer" not in repr(backend.history)
    saved = read_json(tmp_path / "halumem-predictions.json")
    assert [row["session"] for row in saved] == [1, 0]
    assert all(row["extracted_memories"] == [] for row in saved)
    assert not (tmp_path / "http").exists()
    prior_events = copy.deepcopy(backend.events)

    class OfficialLabels:
        def __init__(self, *_: Any) -> None:
            pass

        def score(self, name: str, *_: str) -> dict[str, str]:
            assert name == "question", "Unsupported extraction/update must not be invented"
            return {"evaluation_result": "Correct"}

        def aggregate_results(self, records: dict[str, Any]) -> dict[str, Any]:
            assert records["memory_integrity_records"] == []
            assert records["memory_accuracy_records"] == []
            assert records["memory_update_records"] == []
            return {**records, "overall_score": {}}

    monkeypatch.setattr(edit_benchmarks, "HaluMemOfficial", OfficialLabels)
    scored = execution.halumem("score")
    assert scored["correct"] == 2 and scored["opportunities"] == 2
    assert scored["labels"] == {"Correct": 2}
    assert scored["backend_capabilities"] == {"session_output": "N/A",
                                               "reference_update_state": "N/A"}
    assert backend.events == prior_events and len(delivered) == 2
    official = read_json(tmp_path / "halumem-official-results.json")
    assert official["overall_score"]["memory_extraction_f1"] is None


def test_score_requires_all_declared_predictions(tmp_path: Path) -> None:
    config = configuration()
    write_json(tmp_path / "alignment-prepared.json", {
        "configuration": config,
        "bank_ids": {backend: {} for backend in BACKENDS},
    })
    write_json(tmp_path / BACKENDS[0] / "terminal-predict.json", {"status": "PREDICTIONS_SAVED"})
    with pytest.raises(ValueError, match="Every declared backend"):
        run_alignment_arm(config, tmp_path, BACKENDS[0], "score")
    assert not (tmp_path / BACKENDS[0] / "actual-config.json").exists()


def test_success_terminal_requires_resource_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.runners import baseline_alignment

    config = configuration()
    write_json(tmp_path / "alignment-prepared.json", {
        "configuration": config, "bank_ids": {backend: {} for backend in BACKENDS},
    })
    terminal = tmp_path / BACKENDS[0] / "terminal-predict.json"
    events = []

    class Execution:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def halumem(self, _: str) -> dict[str, int]:
            events.append("predicted")
            return {"complete_answers": 2}

        def close(self) -> None:
            assert not terminal.exists()
            events.append("closed")

    monkeypatch.setattr(baseline_alignment, "AlignmentRun", Execution)
    run_alignment_arm(config, tmp_path, BACKENDS[0], "predict")
    assert events == ["predicted", "closed"]
    assert read_json(terminal)["status"] == "PREDICTIONS_SAVED"


@pytest.mark.parametrize("primary_failure", [False, True])
def test_unsettled_close_retains_errors_and_stops_next_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary_failure: bool,
) -> None:
    from milai_lab.runners import baseline_alignment

    config = configuration()
    write_json(tmp_path / "alignment-prepared.json", {
        "configuration": config, "bank_ids": {backend: {} for backend in BACKENDS},
    })
    started = []

    class Execution:
        def __init__(self, *_: Any, **__: Any) -> None:
            started.append(True)

        def halumem(self, _: str) -> dict[str, int]:
            if primary_failure:
                raise ValueError("ingestion result unknown")
            return {"complete_answers": 2}

        def close(self) -> None:
            raise RuntimeError("native status unconfirmed")

    monkeypatch.setattr(baseline_alignment, "AlignmentRun", Execution)
    with pytest.raises(ValueError if primary_failure else RuntimeError):
        run_alignment_arm(config, tmp_path, BACKENDS[0], "predict")
    terminal = read_json(tmp_path / BACKENDS[0] / "terminal-predict.json")
    assert terminal["status"] == "RESOURCE_UNSETTLED"
    assert terminal["close_error"]["message"] == "native status unconfirmed"
    assert (terminal["error"]["message"] == "ingestion result unknown"
            if primary_failure else terminal["error"] is None)
    with pytest.raises(ValueError, match="resource closure is unconfirmed"):
        run_alignment_arm(config, tmp_path, BACKENDS[1], "predict")
    assert started == [True]


@pytest.mark.parametrize("settled", [False, True])
def test_native_close_attempts_all_banks_and_releases_only_settled_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settled: bool,
) -> None:
    from milai_lab.integrations.memory.hindsight import HindsightIngestionIncomplete

    execution = AlignmentRun.__new__(AlignmentRun)
    execution.root = tmp_path
    closed, released = [], []

    class Bank:
        def __init__(self, owner: str, fail: bool) -> None:
            self.owner, self.fail = owner, fail

        def close(self) -> None:
            closed.append(self.owner)
            if self.fail:
                raise HindsightIngestionIncomplete("native completion failed",
                                                  resources_settled=settled)

    execution.backends = {"one": Bank("one", True), "two": Bank("two", False)}
    monkeypatch.setattr(edit_benchmarks.BenchmarkRun, "close", lambda _: released.append(True))
    with pytest.raises(HindsightIngestionIncomplete, match="native completion failed"):
        execution.close()
    assert closed == ["one", "two"]
    assert execution._resources_settled is settled
    if settled:
        assert released == [True] and not (tmp_path / "resource-unsettled.json").exists()
    else:
        assert not released
        receipt = read_json(tmp_path / "resource-unsettled.json")
        assert receipt["original_lease_released"] is False
        assert [row["owner"] for row in receipt["backend_errors"]] == ["one"]


@pytest.mark.parametrize("operation", ["ingest", "retrieve"])
def test_native_usage_failure_stops_before_common_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    from milai_lab.datasets.edit_benchmarks import ObservedSession
    from milai_lab.integrations.memory.hindsight import HindsightIngestionIncomplete

    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings = alignment_settings(configuration(), BACKENDS[1])
    execution.root = tmp_path
    execution._native_bridge = SimpleNamespace(failure={
        "reason": "native_usage_unconfirmed", "resources_settled": True,
    })
    backend = ActualReturnBackend()
    monkeypatch.setattr(execution, "_backend", lambda _: backend)
    reader_calls = []
    monkeypatch.setattr(execution, "answer_material", lambda *_: reader_calls.append(True))
    with pytest.raises(HindsightIngestionIncomplete, match="native_usage_unconfirmed"):
        if operation == "ingest":
            execution.maintain(None, ObservedSession("s1", "2025-01-01", []), "first")
        else:
            execution.answer(None, "question", "2025-01-01", "first")
    assert not reader_calls
    receipt = "ingestion.json" if operation == "ingest" else "retrieval.json"
    assert (tmp_path / "native/first" / receipt).exists()


def test_detached_native_database_process_prevents_resource_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.integrations.memory.hindsight import HindsightIngestionIncomplete

    execution = AlignmentRun.__new__(AlignmentRun)
    execution.root = tmp_path
    execution.backends = {}
    execution._native_uid = 12345
    execution._native_process = SimpleNamespace(
        poll=lambda: 0, wait=lambda **_: 0, returncode=0,
    )
    released = []
    monkeypatch.setattr(execution, "_uid_processes", lambda _: [98765])
    monkeypatch.setattr(edit_benchmarks.BenchmarkRun, "close", lambda _: released.append(True))
    with pytest.raises(HindsightIngestionIncomplete, match="database_processes_still_running"):
        execution.close()
    assert not released and execution._resources_settled is False
    saved = read_json(tmp_path / "native-service/closed.json")
    assert saved["remaining_uid_processes"] == [98765] and not saved["processes_closed"]
    assert read_json(tmp_path / "resource-unsettled.json")["original_lease_released"] is False


def test_cached_dispatch_does_not_skip_unclosed_native_service(tmp_path: Path) -> None:
    config = configuration()
    write_json(tmp_path / "alignment-prepared.json", {
        "configuration": config, "bank_ids": {backend: {} for backend in BACKENDS},
    })
    write_json(tmp_path / BACKENDS[1] / "native-service/started.json", {"pid": 98765})
    with pytest.raises(ValueError, match="Previous native service closure is unconfirmed"):
        run_alignment_arm(config, tmp_path, BACKENDS[0], "predict")
    assert not (tmp_path / BACKENDS[0] / "actual-config.json").exists()


def test_native_readiness_checks_actual_listener_owner() -> None:
    execution = AlignmentRun.__new__(AlignmentRun)
    execution._native_process = SimpleNamespace(pid=os.getpid())
    execution._native_uid = os.getuid()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert execution._native_listener_is_owned(port)
        execution._native_uid += 1
        assert not execution._native_listener_is_owned(port)


def test_native_database_socket_path_rejects_before_creating_directories(tmp_path: Path) -> None:
    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings = alignment_settings(configuration(), BACKENDS[1])
    socket_root = tmp_path / ("long-directory-" * 12)
    execution.settings["alignment"]["hindsight_service"]["socket_root"] = str(socket_root)
    with pytest.raises(ValueError, match="Unix socket path is too long"):
        execution._native_database_url("test-instance", os.getuid(), os.getgid())
    assert not socket_root.exists()


def test_reference_query_effects_and_later_state_stay_outside_session_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings = alignment_settings(configuration(), "MiLAi-memory-only")
    execution.root, execution._evaluation_key = tmp_path, "session/current"
    monkeypatch.setattr(execution, "_semantic_retriever", lambda: None)
    namespace = ("edit", "aligned", "M", "opaque-owner")
    cache = (*namespace, "reference-query-cache")
    observed_stores = []

    def reference_search(self: Any, service: MemoryService, query: str) -> list[str]:
        observed_stores.append(service.store)
        row = service.store.get(namespace, "source-version")
        assert row is not None
        service.store.put(cache, query, {"reference_only": True}, index=False)
        return [row.value["body"]]

    monkeypatch.setattr(edit_benchmarks.BenchmarkRun, "_score_retrieval", reference_search)
    with SqliteStore.from_conn_string(str(tmp_path / "actual.sqlite")) as store:
        original = MemoryService(store, namespace, "opaque-owner", tmp_path / "actual.lock",
                                 mutation_contract="event_bound_v1",
                                 candidate_contract="read_handle_v1")
        store.put(namespace, "source-version", {"body": "actual current source"}, index=False)
        assert execution._score_retrieval(original, "reference A") == ["actual current source"]
        assert store.get(cache, "reference A") is None
        store.put(namespace, "source-version", {"body": "later arrived source"}, index=False)
        assert execution._score_retrieval(original, "reference B") == ["actual current source"]
        assert store.get(cache, "reference B") is None
        assert all(observed is not store for observed in observed_stores)
