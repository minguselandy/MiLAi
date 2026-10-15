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
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import (
    _maintain_with_output_budget,
    diagnostic_costs,
    prepare_diagnostic,
    promote_plain_version,
    run_pair,
    run_seed,
)
from milai_lab.runners.method_architecture_factorial import prepare_factorial, run_factorial
from milai_lab.runners.method_architecture_lifecycle import prepare_lifecycle, run_lifecycle


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
                if self.settings["arm"] == "M":
                    clause["conditions"] = []
                return {"creates": [{"action": "create", "matter": "test source",
                                     "clauses": [clause]}], "records": {}}
            text = before[0]["value"]["edit_state"]["units"][0]["text"]
            if self.settings.get("maintenance_mode") == "semantic_delta_v2":
                return {"changes": {"r1": {"replace": {"u1": {
                    "text": text + "\n" + observed.turns[0]["content"],
                    "basis": "e1", "also": ["e2"], "kind": "reported"}}}}}
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


@pytest.mark.parametrize("failure", [False, True])
def test_maintenance_ceiling_does_not_change_reader_or_survive_failure(tmp_path, failure):
    config = VLLMConfig(base_url="http://localhost/v1", model="test", max_tokens=8192)
    run = SimpleNamespace(root=tmp_path, client=SimpleNamespace(config=config),
                          settings={"model": {"max_tokens": 8192}})

    def maintain(*args):
        assert run.client.config.max_tokens == 2048
        assert run.settings["model"]["max_tokens"] == 2048
        if failure:
            raise ValueError("known test failure")

    run.maintain_recipe = maintain
    if failure:
        with pytest.raises(ValueError, match="known test failure"):
            _maintain_with_output_budget(run, None, None, 2048)
    else:
        _maintain_with_output_budget(run, None, None, 2048)
    assert run.client.config == config and run.settings["model"]["max_tokens"] == 8192


@pytest.mark.parametrize("with_delta", [False, True])
def test_common_actual_seed_is_not_reformed_or_repaired_for_candidate(tmp_path: Path, with_delta):
    lab = Path(__file__).resolve().parents[2]
    config = read_json(lab / "configs/milai-method-architecture-paired-v1.json")
    for key in ("plain_config", "candidate_config", "sources"):
        config[key] = str(lab / config[key])
    if with_delta:
        delta = read_json(Path(config["candidate_config"]))
        settings = delta["entrypoints"]["benchmark"]
        settings["maintenance_mode"] = "semantic_delta_v2"
        settings["edit_features"].update(dependency_updates=False, dependency_groups=True)
        config["delta_config"] = str(tmp_path / "delta.json")
        write_json(Path(config["delta_config"]), delta)
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
    if with_delta:
        delta = summary["arms"]["delta"]
        assert delta["before"] == candidate["before"] and delta["engineered_ok"]
    assert read_json(root / "seed/result.json") == saved_seed
    for name in ("seed", *protocol["settings"]):
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


class FactorialStubRun(StubRun):
    read_inputs: ClassVar[list] = []
    selector_calls: ClassVar[list] = []

    def call(self, stage, messages, **kwargs):
        self.selector_calls.append((str(self.root), stage))
        schema = kwargs["response_format"]["json_schema"]["schema"]
        return json.dumps({key: {"roots": [0], "excluded": [], "history_revisions":
            row["properties"]["history_revisions"]["items"]["enum"]}
            for key, row in schema["properties"].items()})

    def answer_material(self, question, date, key, memories, *, snapshot_id, material_reader):
        opened = material_reader(memories)
        self.read_inputs.append({"cell": self.root.name, "key": key,
            "versions": [(m["record_id"], m["revision"]) for m in opened
                         if m["kind"] == "semantic_view"],
            "sources": [m["source_ranges"] for m in opened if m["kind"] == "original_source"],
            "pre_read_calls": memories[0].get("pre_read_calls", 0)})
        return "Test response to: " + question, opened


def test_factorial_shares_actual_formation_update_and_read_pools(tmp_path: Path):
    lab = Path(__file__).resolve().parents[2]
    config = read_json(lab / "configs/milai-method-architecture-factorial-v1.json")
    config["base_config"] = str(lab / "configs/milai-method-architecture-dev-v2.json")
    config["sources"] = str(lab / "data/fixtures/milai-method-architecture-screening-v1.jsonl")
    config["cases"] = config["cases"][:1]
    config["cases"][0]["queries"][0]["gold"] = "FACTORIAL_EVALUATOR_SECRET"
    root = tmp_path / "factorial"
    protocol = prepare_factorial(config, root)
    FactorialStubRun.requests = []
    FactorialStubRun.read_inputs = []
    FactorialStubRun.selector_calls = []
    result = run_factorial(protocol, root, run_class=FactorialStubRun)
    case = result["cases"]["exception-withdrawal"]
    seed = case["seed"]["actual_state"]
    assert seed and seed[0]["value"]["edit_state"]["representation"] == "conditioned_v1"
    assert len(FactorialStubRun.requests) == 5  # two seed events, two edits, one Impact
    assert len(FactorialStubRun.selector_calls) == 6
    assert len(FactorialStubRun.read_inputs) == 12
    assert "FACTORIAL_EVALUATOR_SECRET" not in json.dumps(FactorialStubRun.requests)
    for u in (0, 1):
        assert case["updates"][f"U{u}"]["before"] == seed
        for query in protocol["cases"][0]["queries"]:
            a, b = [next(row for row in FactorialStubRun.read_inputs
                         if row["cell"] == f"Y{u}{r}" and row["key"].endswith(query["id"]))
                    for r in (0, 1)]
            assert a["versions"] == b["versions"]
            assert a["sources"] == b["sources"]
            assert (a["pre_read_calls"], b["pre_read_calls"]) == (0, 1)
        for r in (0, 1):
            cell = case["cells"][f"Y{u}{r}"]
            assert cell["record_values_unchanged"]
            assert cell["state_correct"] is None and cell["answer_correct"] is None
    after = [case["updates"][f"U{u}"]["after"][0]["value"] for u in (0, 1)]
    assert after[0]["source_ref"] == after[1]["source_ref"]
    count = len(FactorialStubRun.requests)
    reads = len(FactorialStubRun.read_inputs)
    run_factorial(protocol, root, run_class=FactorialStubRun)
    assert len(FactorialStubRun.requests) == count
    assert len(FactorialStubRun.read_inputs) == reads


class LifecycleStubRun(StubRun):
    maintenance_calls: ClassVar[list] = []
    rebuild_inputs: ClassVar[list] = []

    def __init__(self, settings, root, *, phase):
        super().__init__(settings, root, phase=phase)
        self.client = SimpleNamespace(config=SimpleNamespace(max_calls=12))

    def _fits(self, messages, **kwargs):
        return True

    def maintain_recipe(self, service, observed, key):
        self.maintenance_calls.append((self.root.name, key))
        result = super().maintain_recipe(service, observed, key)
        write_json(self.root / "http/maintenance" / key / "edit/response.json",
                   {"usage": {"total_tokens": 11}})
        return result

    def call(self, stage, messages, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        if stage.startswith("maintenance-policy/"):
            ordinal = int(stage.rsplit("-", 1)[-1])
            response = {"maintain": ordinal not in {1, 3}, "reason": "Test scheduling decision"}
            tokens = 7
        else:
            payload = json.loads(messages[1]["content"])
            evidence = [*payload["delivery"]["evidence"],
                        *payload["delivery"]["redelivered_support"]]
            self.rebuild_inputs.append([item["text"] for item in evidence])
            response = {"creates": [{"action": "create", "matter": "prefix rebuild",
                "clauses": [{"text": "\n".join(item["text"] for item in evidence),
                    "evidence": [item["id"] for item in evidence], "conditions": [],
                    "assertion": {"source_evidence": evidence[-1]["id"], "kind": "reported"}}]}],
                "records": {}}
            tokens = 13
        write_json(self.root / "http" / stage / "response.json",
                   {"usage": {"total_tokens": tokens}})
        return json.dumps(response)

    def answer(self, service, question, date, key):
        assert self.settings["read_usage_updates"] is False
        write_json(self.root / "http" / key / "response.json",
                   {"usage": {"total_tokens": 15}})
        return "Test response to: " + question


def test_lifecycle_captures_skipped_sources_and_rebuilds_only_arrived_prefix(tmp_path: Path):
    lab = Path(__file__).resolve().parents[2]
    config = read_json(lab / "configs/milai-method-architecture-lifecycle-v1.json")
    config["base_config"] = str(lab / "configs/milai-method-architecture-dev-v2.json")
    config["sources"] = str(lab / "data/fixtures/milai-method-architecture-lifecycle-v1.jsonl")
    config["queries"] = [{"id": str(i), "question": "READER_ONLY_" + str(i),
                           "gold": "LIFECYCLE_EVALUATOR_SECRET"} for i in range(4)]
    root = tmp_path / "lifecycle"
    protocol = prepare_lifecycle(config, root)
    LifecycleStubRun.requests = []
    LifecycleStubRun.maintenance_calls = []
    LifecycleStubRun.rebuild_inputs = []
    result = run_lifecycle(protocol, root, run_class=LifecycleStubRun)
    policies = result["policies"]
    assert [len([x for x in LifecycleStubRun.maintenance_calls if x[0] == name])
            for name in ("event", "explicit_change", "query_rebuild")] == [6, 4, 0]
    assert [len(items) for items in LifecycleStubRun.rebuild_inputs] == [1, 3, 5, 6]
    assert "LIFECYCLE_EVALUATOR_SECRET" not in json.dumps(LifecycleStubRun.requests)
    assert "READER_ONLY_" not in json.dumps(LifecycleStubRun.requests)
    for name, policy in policies.items():
        assert policy["captured_sources"] == 6
        assert len(policy["arrivals"]) == 6
        assert all(c["record_values_unchanged"] for c in policy["checkpoints"])
        if name == "query_rebuild":
            assert all(not row["state"] for row in policy["arrivals"])
            assert all(not c["rebuild_before"] for c in policy["checkpoints"])
            assert all(c["rebuild_receipt"]["status"] == "completed"
                       for c in policy["checkpoints"])
            owner = config["owner"]
            namespace = ("edit", "method-architecture-diagnostic", owner)
            bank = root / name / "bank"
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as source_store:
                original = MemoryService(source_store, namespace, owner, bank / "memory.lock",
                                         functional_contract="functional_v1")
                for ordinal in config["query_after_sessions"]:
                    rebuilt = root / name / "rebuilds" / f"prefix-{ordinal}"
                    with SqliteStore.from_conn_string(str(rebuilt / "memory.sqlite")) as copied:
                        actual = MemoryService(copied, namespace, owner, rebuilt / "memory.lock",
                                               functional_contract="functional_v1")
                        sources = actual.sources()
                        assert len(sources) == ordinal + 1
                        assert all(actual.source(source["event_id"]) == original.source(
                            source["event_id"])
                                   for source in sources)
        for count in (1, 4):
            curve = policy["reuse_curves"][str(count)]
            assert curve["query_opportunities"] == 4 * count
            assert curve["reading"]["generation_known_tokens"] == 4 * count * 15
        curves = policy["reuse_curves"]
        assert curves["1"]["maintenance"] == curves["4"]["maintenance"]
        assert curves["4"]["lifecycle"] == policy["total_costs"]
    assert policies["explicit_change"]["costs"]["stages"]["policy_selection"] == {
        "responses": 5, "known_tokens": 35, "unknown_usage_responses": 0}
    assert [row["decision"]["maintain"] for row in policies["explicit_change"]["arrivals"]] == [
        True, False, True, False, True, True]
