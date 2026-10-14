"""Controlled seed cloning uses actual stored values and the normal maintenance core."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.activation import ActivationIndex
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import maintain_event
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import (
    diagnostic_costs,
    prepare_diagnostic,
    promote_plain_version,
    run_pair,
    run_seed,
)


class StubRun(BenchmarkRun):
    """Deterministic model responses; actual source, mapping and SQLite commits."""

    requests: ClassVar[list] = []

    def __init__(self, settings, root, *, phase):
        self.settings, self.root = settings, root
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / "actual-config.json", settings)

    def close(self):
        write_json(self.root / "closed.json", {"test_only": True})

    def maintain_recipe(self, service, observed, key):
        method = EditMemory(service, self.settings["arm"], interface_version="I2",
                            features=EditFeatures.from_settings(self.settings["edit_features"]),
                            maintenance_mode=self.settings.get("maintenance_mode", "legacy"))
        source = service.capture_user(observed.session_id, "turn:0", observed.turns[0]["content"],
                                      occurred_at=observed.turns[0]["timestamp"],
                                      calendar_context=self.settings.get("calendar_context"))[
                                          "source_ref"]
        service.bind_public_turn(observed.session_id, "turn:0", source,
                                 config_version=self.settings["config_version"], phase="start")
        before = service.records()
        delivery = method.prepare([source], "", selected_records=[], redelivered_ranges=[])
        delivery["materialize_selected_support"] = True

        def model_call(stage, messages, schema):
            self.requests.append(copy.deepcopy(messages))
            if stage == "impact":
                return {"roots": ["u1"], "preserve": []}
            assertion = {"source_evidence": "e1", "kind": "reported"}
            if not before:
                clause = {"text": observed.turns[0]["content"], "evidence": ["e1"],
                          "assertion": assertion}
                return {"creates": [{"action": "create", "matter": "test source",
                                     "clauses": [clause]}], "records": {}}
            text = before[0]["value"]["edit_state"]["units"][0]["text"]
            return {"creates": [], "records": {"r1": {"action": "edit", "edits": [{
                "operation": "replace", "target_unit": "u1",
                "text": text + "\n" + observed.turns[0]["content"],
                "evidence": ["e1", "e2"], "assertion": assertion}]}}}

        result = maintain_event(method, delivery, session=observed.session_id, request_id=key,
            date=observed.date, recipe="single_pass", model_call=model_call,
            selected_record_ids=[row["id"] for row in before])
        write_json(self.root / "maintenance" / key / "complete.json", result)
        return []

    def answer(self, service, question, date, key):
        assert self.settings["read_usage_updates"] is False
        return "Test response to: " + question


def test_common_actual_seed_is_not_reformed_or_repaired_for_candidate(tmp_path: Path):
    lab = Path(__file__).resolve().parents[2]
    config = read_json(lab / "configs/milai-method-architecture-paired-v1.json")
    for key in ("plain_config", "candidate_config", "sources"):
        config[key] = str(lab / config[key])
    # This evaluator-only sentinel must never reach any maintenance call.
    config["queries"][0]["gold"] = "EVALUATOR_SECRET"
    root = tmp_path / "diagnostic"
    protocol = prepare_diagnostic(config, root)
    assert protocol["status"] == "PREPARED_ZERO_MODEL"
    StubRun.requests = []
    seed = run_seed(protocol, root, run_class=StubRun)
    saved_seed = copy.deepcopy(seed)
    first_count = len(StubRun.requests)
    summary = run_pair(protocol, root, run_class=StubRun)
    assert len(StubRun.requests) > first_count
    assert summary["independent_system_result"] is False
    plain, candidate = (summary["arms"][name] for name in ("plain", "candidate"))
    initial = seed["actual_state"][0]["value"]
    assert plain["before"][0]["value"] == initial
    assert candidate["before"][0]["value"] == promote_plain_version(initial)
    assert candidate["before"][0]["value"]["edit_state"]["relations"] == []
    assert plain["engineered_ok"] and candidate["engineered_ok"]
    assert candidate["state_correct"] is None and candidate["answer_correct"] is None
    assert read_json(root / "seed/result.json") == saved_seed
    for name in ("seed", "plain", "candidate"):
        with SqliteStore.from_conn_string(str(root / name / "bank/memory.sqlite")) as store:
            owner = config["owner"]
            service = MemoryService(store, ("edit", "method-architecture-diagnostic", owner), owner,
                                    root / name / "bank/memory.lock",
                                    functional_contract="functional_v1",
                                    memory_profile="unified_v1")
            if name == "seed":
                assert len(service.sources()) == 1
                assert service.records()[0]["value"] == initial
            else:
                assert len(service.sources()) == 2
                source = summary["common_arrival"]["sources"][0]
                assert service.source(source["event_id"]) == source
    assert "EVALUATOR_SECRET" not in json.dumps(StubRun.requests)
    assert all(query["question"] not in json.dumps(StubRun.requests)
               for query in protocol["queries"])
    count = len(StubRun.requests)
    run_seed(protocol, root, run_class=StubRun)
    run_pair(protocol, root, run_class=StubRun)
    assert len(StubRun.requests) == count


@pytest.mark.parametrize("feedback", [False, True])
def test_read_usage_switch_is_independent_of_answer_generation(tmp_path, monkeypatch, feedback):
    run = BenchmarkRun.__new__(BenchmarkRun)
    run.root = tmp_path
    run.settings = {"read_usage_updates": feedback}
    run.retrieve_material = lambda *args: []
    run.answer_material = lambda *args: ("answer", [{"record_id": "actual-record"}])
    calls = []
    monkeypatch.setattr(ActivationIndex, "__init__", lambda self, service: None)
    monkeypatch.setattr(ActivationIndex, "record_use",
                        lambda self, identity, **kwargs: calls.append(identity))
    assert run.answer(SimpleNamespace(memory_profile="unified_v1"), "q", "d", "question") == (
        "answer")
    assert calls == (["actual-record"] if feedback else [])


@pytest.mark.parametrize("backend", [None, "MiLAi-memory-only"])
@pytest.mark.parametrize("finish,content,message", [
    ("length", "partial", "Provider output incomplete: length"),
    ("stop", None, "Provider returned no textual answer"),
])
def test_dependency_selection_records_confirmed_readonly_failure(
    tmp_path, backend, finish, content, message,
):
    run = BenchmarkRun.__new__(BenchmarkRun)
    run.root = tmp_path
    run.settings = {"dependency_reading": True, "halumem": {
        "reader_failure_policy": "record_known_readonly_failure"}}
    if backend:
        run.settings["alignment_backend"] = backend
    pool = ("native/questions/q1/retrieval.json" if backend else
            "http/questions/q1/retrieval-materials.json")
    path = tmp_path / "http/dependency-selection" / pool / "response.json"
    write_json(path, {"choices": [{"finish_reason": finish, "message": {"content": content}}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    failure = run._known_reader_failure(ValueError(message), "questions/q1")
    assert failure["phase"] == "confirmed_response"
    assert failure["response_ref"] == str(path.relative_to(tmp_path))
    path.unlink()
    assert run._known_reader_failure(ValueError(message), "questions/q1") is None


def test_cost_inventory_keeps_unknown_usage_and_separates_shared_components(tmp_path):
    write_json(tmp_path / "http/maintenance/update/impact/response.json", {
        "usage": {"total_tokens": 7}})
    write_json(tmp_path / "http/embedding/1/response.json", {"usage": {"total_tokens": 4}})
    write_json(tmp_path / "http/questions/q1/response.json", {"usage": None})
    write_json(tmp_path / "http/questions/q2/request.json", {"messages": []})
    result = diagnostic_costs(tmp_path)
    assert result["stages"]["impact"]["known_tokens"] == 7
    assert result["stages"]["embedding"]["known_tokens"] == 4
    assert result["stages"]["reader"]["unknown_usage_responses"] == 1
    assert result["requests_without_response"] == ["http/questions/q2/request.json"]
