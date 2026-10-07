"""Actual SQLite/accounted transport integration, with synthetic model responses."""

from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from langgraph.store.sqlite import SqliteStore

from milai_lab.datasets.edit_benchmarks import ObservedSession
from milai_lab.harness.artifact_io import read_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.edit_benchmarks import (
    BenchmarkRun,
    adjacent_source_context,
    natural_source_batches,
    parse_object,
)


class Tokenizer:
    def encode(self, text: str, **kwargs: Any) -> list[int]:
        return [1] * len(text)

    def apply_chat_template(self, messages: list[dict[str, str]], **kwargs: Any) -> list[int]:
        return [1] * (12 + sum(len(m["content"]) for m in messages))


def test_record_container_rejects_duplicate_keys_before_json_overwrites_intent() -> None:
    text = (
        '{"creates": [], "records": {"r1": {"action": "rewrite"}, '
        '"r1": {"action": "retract_record"}}}'
    )
    with pytest.raises(ValueError, match="Duplicate JSON object key: r1"):
        parse_object(text, reject_duplicate_keys=True)
    # The opt-in contract must not retrospectively alter the old parser.
    assert parse_object(text)["records"]["r1"] == {"action": "retract_record"}
    assert parse_object('{"creates": [], "records": {}}', reject_duplicate_keys=True) == {
        "creates": [], "records": {}
    }


def test_stage_a_rejects_withdrawal_evidence_outside_actual_packet() -> None:
    tool = Path(__file__).parents[2] / "tools/run_edit_interface_checks.py"
    inspect = runpy.run_path(str(tool))["alias_errors"]
    packet = {
        "records": [{"id": "r1", "units": []}],
        "evidence": [{"id": "e1"}],
        "historical_support": [],
    }
    envelope = {
        "proposals": [
            {"action": "rewrite", "target": "r1", "units": [], "withdrawal_evidence": ["e2"]}
        ]
    }
    assert inspect(envelope, packet) == ["withdrawal_evidence: e2"]
    envelope["proposals"][0]["withdrawal_evidence"] = ["e1"]
    assert inspect(envelope, packet) == []


def execution(root: Path, arm: str) -> BenchmarkRun:
    run = BenchmarkRun.__new__(BenchmarkRun)
    run.root, run.tokenizer = root, Tokenizer()
    run.settings = {
        "arm": arm,
        "interface_version": "I2",
        "working_sets": True,
        "retrieval_limit": 10,
        "source_tokens": 4096,
        "source_context_tokens": 0,
        "context_tokens": 65536,
        "model": {"max_tokens": 100},
    }
    return run


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_temporary_changes_locate_then_use_existing_editor_without_becoming_memory(
    tmp_path: Path, arm: str
) -> None:
    """Real SQLite and accounted synthetic HTTP; no model semantic-success claim."""
    calls = []

    def provider(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        payload = json.loads(wire["messages"][1]["content"])
        calls.append(payload)
        packet = payload["delivery"]
        if len(calls) == 1:
            assert packet["records"] == [] and packet["historical_support"] == []
            assert [e["delivery_kind"] for e in packet["evidence"]] == ["current", "current"]
            envelope = {"changes": [
                {"subject": "Review schedule", "statement": "User reports review Thursday.",
                 "evidence": ["e1"], "time": None, "scope": None},
                {"subject": "Ceramics plan", "statement": "User plans ceramics Friday.",
                 "evidence": ["e1"], "time": "Friday", "scope": None},
            ]}
        else:
            # Delivery order changed: User evidence is now e2, not extraction e1.
            assert all(c["evidence"] == ["e2"] for c in payload["change_candidates"])
            assert packet["evidence"][1]["text"].startswith("Review Thursday")
            record = next(r for r in packet["records"] if r["matter"] == "Review schedule")
            clause = {"text": "User reports review Thursday.", "evidence": ["e2"],
                      "assertion": {"source": "e2", "kind": "reported"}}
            if arm in {"B0", "B2"}:
                change = {"action": "rewrite", "clauses": [
                    {**clause, **({"conditions": []} if arm == "B2" else {})}
                ]}
            else:
                change = {"action": "edit", "edits": [{
                    **clause, "operation": "change_value" if arm == "M" else "replace",
                    "target_unit": record["clauses"][0]["id"],
                }]}
            envelope = {"creates": [{
                "action": "create", "matter": "Ceramics plan", "clauses": [{
                    "text": "User plans ceramics Friday.", "evidence": ["e2"],
                    "assertion": {"source": "e2", "kind": "reported"},
                    **({"conditions": []} if arm in {"B2", "M"} else {}),
                }],
            }], "records": {record["id"]: change}}
        Draft202012Validator(wire["response_format"]["json_schema"]["schema"]).validate(envelope)
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(envelope)}}],
            "usage": {"total_tokens": 8},
        })

    run = execution(tmp_path, arm)
    run.settings["context_tokens"] = 100000
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
        budget=budget, transport=httpx.MockTransport(provider),
    ) as client, SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        run.client = client
        service = MemoryService(
            store, ("changes", arm, "owner"), "owner", tmp_path / "bank.lock",
            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
        )
        method = EditMemory(service, arm, interface_version="I2",
                            features=EditFeatures(True, True, True, True, True))
        seed = service.capture_user("old", "u", "Review Monday; tea jasmine.")["source_ref"]
        service.bind_source_boundary("old", "seed", [seed])
        initial = method.writer_request(method.prepare([seed], "", selected_records=[]))
        for i, (matter, text) in enumerate((
            ("Review schedule", "User reports review Monday."),
            ("Tea preference", "User reports tea jasmine."),
        )):
            create = {"action": "create", "matter": matter, "clauses": [{
                "text": text, "evidence": ["e1"],
                "assertion": {"source": "e1", "kind": "reported"},
                **({"conditions": []} if arm in {"B2", "M"} else {}),
            }]}
            assert method.apply("old", f"seed:{i}",
                                method.decode_proposal(create, initial["mapping"]))["ok"]
        before = {r["value"]["edit_state"]["matter_description"]: r for r in service.records()}
        user = service.capture_user("new", "u", "Review Thursday; I plan ceramics Friday.",
                                    occurred_at="2030-01-02")["source_ref"]
        assistant = service.capture_assistant("new", "a", "An unconfirmed extra suggestion.",
                                             occurred_at="2030-01-02")["source_ref"]
        service.bind_source_boundary("new", "event", [user, assistant])
        raw = method.prepare([user, assistant], "", selected_records=[], redelivered_ranges=[])
        extraction = method.change_request(raw, "2030-01-02")
        result = run.call("changes", extraction["messages"], structured=True,
                          response_format={"type": "json_schema", "json_schema": {
                              "name": "milai_changes", "schema": extraction["schema"],
                          }})
        changes = method.decode_changes(parse_object(result), extraction)
        assert service.records() == list(before.values())
        assert changes[0]["evidence"] == [raw["sources"][0]["evidence_id"]]
        query = method.changes_query(changes, "original event")
        selected = service.search(query, limit=10, include_raw=False)["records"]
        assert before["Review schedule"]["id"] in [r["id"] for r in selected]
        delivery = method.prepare([assistant, user], query, selected_records=selected,
                                  redelivered_ranges=[])
        view = method.writer_request(delivery)
        hints = method.writer_changes(changes, view["mapping"])
        messages = run._edit_messages(method, view["packet"], "2030-01-02", allow_create=True,
                                     schema=view["schema"], change_candidates=hints)
        result = run.call("writer", messages, structured=True,
                          response_format={"type": "json_schema", "json_schema": {
                              "name": "milai_edit", "schema": view["schema"],
                          }})
        for i, decoded in enumerate(method.decode_envelope(parse_object(result), view["mapping"])):
            assert method.apply("new", f"change:{i}", decoded)["ok"]
        after = {r["value"]["edit_state"]["matter_description"]: r for r in service.records()}
        assert len(after) == 3
        assert after["Tea preference"] == before["Tea preference"]
        assert after["Review schedule"]["id"] == before["Review schedule"]["id"]
        assert after["Review schedule"]["value"]["revision"] == 2
        assert "Thursday" in after["Review schedule"]["value"]["content"]
        assert "plans" in after["Ceramics plan"]["value"]["content"]
        assert method.decode_changes({"changes": []}, extraction) == []
        assert method.changes_query([], "original event") == "original event"
        # Even nonempty candidates are not a compulsory write or an executable proposal.
        assert method.decode_envelope({"creates": [], "records": {}}, view["mapping"]) == []
        assert service.records() == list(after.values())
    assert len(calls) == budget.state["generation_requests"] == 2


def test_context_admission_matches_transported_thinking_mode(tmp_path: Path) -> None:
    from tokenizers import Tokenizer as FastTokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import PreTrainedTokenizerFast

    core = FastTokenizer(WordLevel(
        {"[UNK]": 0, "input": 1, "assistant": 2, "think": 3, "closed": 4},
        unk_token="[UNK]",
    ))
    core.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=core, unk_token="[UNK]")
    tokenizer.chat_template = (
        "{% for message in messages %}{{ message.content }} {% endfor %}"
        "{% if add_generation_prompt %}assistant think "
        "{% if enable_thinking is defined and enable_thinking is false %}closed{% endif %}"
        "{% endif %}"
    )
    messages = [{"role": "user", "content": "input"}]
    thinking_count = len(tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, enable_thinking=True,
    ))
    nonthinking_count = len(tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
    ))
    assert nonthinking_count > thinking_count
    sent: list[dict[str, Any]] = []

    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent.append(payload)
        tokens = len(tokenizer.apply_chat_template(
            payload["messages"], tokenize=True, add_generation_prompt=True,
            **payload.get("chat_template_kwargs", {}),
        ))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "answer"}}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": 1,
                      "total_tokens": tokens + 1},
        })

    run = execution(tmp_path, "M")
    run.tokenizer = tokenizer
    run.settings["context_tokens"] = thinking_count + 1 + 512
    for mode in (False, True, None):
        run.settings["model"] = {"max_tokens": 1, "enable_thinking": mode}
        with VLLMClient(
            VLLMConfig("http://local.invalid/v1", "synthetic", max_tokens=1,
                       enable_thinking=mode),
            transport=httpx.MockTransport(provider),
        ) as client:
            run.client = client
            if mode is False:
                assert not run._fits(messages)
                with pytest.raises(ValueError, match="Context unavailable without loss"):
                    run.call("nonthinking", messages, structured=False)
                assert sent == []
            else:
                assert run._fits(messages)
                key = "thinking" if mode else "provider-default"
                assert run.call(key, messages, structured=False) == "answer"
                saved = read_json(tmp_path / "http" / key / "request.json")
                response = read_json(tmp_path / "http" / key / "response.json")
                assert saved["prompt_tokens"] == response["usage"]["prompt_tokens"]


def observation(session: str, text: str) -> ObservedSession:
    return ObservedSession(
        session, "2030-01-01", ({"role": "user", "content": text, "timestamp": "2030-01-01"},)
    )


def response(proposal: dict[str, Any], *, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": finish,
                    "message": {"content": json.dumps({"proposals": [proposal]})},
                }
            ],
            "usage": {"total_tokens": 8},
        },
    )


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_actual_four_arm_requests_use_schema_and_same_id_cas(tmp_path: Path, arm: str) -> None:
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        delivery = json.loads(payload["messages"][1]["content"])["delivery"]
        evidence = delivery["evidence"][0]["id"]
        text = delivery["evidence"][0]["text"]
        if not delivery["records"]:
            return response(
                {
                    "action": "create",
                    "units": [{"text": text, "evidence": [evidence], "role": "content"}],
                }
            )
        record = delivery["records"][0]
        if arm in {"B0", "B2"}:
            return response(
                {
                    "action": "rewrite",
                    "target": record["id"],
                    "units": [{"text": text, "evidence": [evidence], "role": "content"}],
                }
            )
        return response(
            {
                "action": "edit",
                "target": record["id"],
                "edits": [
                    {
                        "operation": "replace",
                        "target_unit": record["units"][0]["id"],
                        "text": text,
                        "evidence": [evidence],
                    }
                ],
            }
        )

    run = execution(tmp_path, arm)
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
        budget=budget,
        transport=httpx.MockTransport(provider),
    ) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
            service = MemoryService(
                store,
                ("synthetic", arm, "owner"),
                "owner",
                tmp_path / "bank.lock",
                mutation_contract="event_bound_v1",
                candidate_contract="read_handle_v1",
            )
            assert run.maintain(service, observation("s1", "Project weekly Monday"), "1")
            original = service.records()[0]["id"]
            assert run.maintain(service, observation("s2", "Project weekly Thursday"), "2")
            rows = service.records()
            assert len(rows) == 1 and rows[0]["id"] == original
            assert rows[0]["value"]["revision"] == 2
            assert "Thursday" in rows[0]["value"]["content"]
            run.maintain(service, observation("s2", "Project weekly Thursday"), "2")
    assert len(requests) == 2 and budget.state["generation_requests"] == 2
    assert all(r["response_format"]["type"] == "json_schema" for r in requests)
    complete = read_json(tmp_path / "maintenance/2/complete.json")
    assert complete["unprocessed"] == []
    coverage = read_json(tmp_path / "maintenance/2/source-coverage.json")
    assert coverage["complete_parsed_core_characters_union"] == len("Project weekly Thursday")


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_next_contract_uses_actual_schema_and_keeps_separate_matter_state(
    tmp_path: Path, arm: str
) -> None:
    """A synthetic transport verifies wiring, never the model's semantic choices."""
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        material = json.loads(payload["messages"][1]["content"])
        packet, schema = material["delivery"], material["response_schema"]
        generation_contract = payload["response_format"]["json_schema"]["schema"]
        assert "$defs" not in generation_contract
        requests.append(packet)
        evidence = packet["evidence"][0]["id"]
        assertion = {"source": evidence, "kind": "reported"}
        if not packet["records"]:
            assert schema["properties"]["records"]["properties"] == {}
            envelope = {
                "creates": [
                    {"action": "create", "matter": matter,
                     "clauses": [{"text": text, "evidence": [evidence],
                                  "assertion": assertion,
                                  **({"conditions": []} if arm in {"B2", "M"} else {})}]}
                    for matter, text in (("Project schedule", "Project schedule Monday"),
                                         ("Tea preference", "Tea preference jasmine"))
                ],
                "records": {},
            }
        else:
            record = next(r for r in packet["records"]
                          if "Monday" in r["clauses"][0]["text"])
            unit = record["clauses"][0]
            assert record["matter"] == "Project schedule"
            if arm in {"B0", "B2"}:
                change = {"action": "rewrite", "clauses": [
                    {"text": "Project schedule Thursday",
                     "evidence": [evidence], "assertion": assertion,
                     **({"conditions": []} if arm == "B2" else {})}
                ]}
            else:
                change = {"action": "edit", "edits": [
                    {"operation": "change_value" if arm == "M" else "replace",
                     "target_unit": unit["id"], "text": "Project schedule Thursday",
                     "evidence": [evidence], "assertion": assertion}
                ]}
            envelope = {"creates": [], "records": {record["id"]: change}}
        Draft202012Validator(schema).validate(envelope)
        Draft202012Validator(generation_contract).validate(envelope)
        invalid = copy.deepcopy(envelope)
        if not packet["records"]:
            clause = invalid["creates"][0]["clauses"][0]
        elif arm in {"B0", "B2"}:
            clause = next(iter(invalid["records"].values()))["clauses"][0]
        else:
            clause = next(iter(invalid["records"].values()))["edits"][0]
        clause["evidence"] = ["e999"]
        assert not Draft202012Validator(schema).is_valid(invalid)
        assert not Draft202012Validator(generation_contract).is_valid(invalid)
        if "$defs" in schema:
            assert len(json.dumps(schema)) < len(json.dumps(generation_contract))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(envelope)}}],
            "usage": {"total_tokens": 8},
        })

    run = execution(tmp_path, arm)
    run.settings["edit_features"] = {name: True for name in (
        "matter_organization", "semantic_operations", "bound_references",
        "single_record_changes", "source_metadata",
    )}
    run.settings["source_body_tokens"] = 4096
    # This fake tokenizer counts characters; allow the actual bound schema too.
    run.settings["context_tokens"] = 100000
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
        budget=RunBudget(RunLimits(), tmp_path / "budget.json"),
        transport=httpx.MockTransport(provider),
    ) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
            service = MemoryService(
                store, ("next-contract", arm, "owner"), "owner", tmp_path / "bank.lock",
                mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
            )
            run.maintain(service, observation("s1", "Project schedule Monday; tea jasmine"), "1")
            old = {r["value"]["edit_state"]["matter_description"]: r for r in service.records()}
            assert len(old) == 2
            run.maintain(service, observation("s2", "Project schedule Thursday"), "2")
            current = {r["value"]["edit_state"]["matter_description"]: r
                       for r in service.records()}
            assert current["Tea preference"] == old["Tea preference"]
            project = current["Project schedule"]
            assert project["id"] == old["Project schedule"]["id"]
            assert project["value"]["revision"] == 2
            assert "Thursday" in project["value"]["content"]
            assert "reported" in project["value"]["content"]
            assert all(source["occurred_at"] == "2030-01-01" for source in service.sources())
    assert len(requests) == 2
    assert [e["delivery_kind"] for e in requests[0]["evidence"]] == ["current"]
    assert [e["delivery_kind"] for e in requests[1]["evidence"]] == [
        "current", "redelivered_support"
    ]
    assert requests[1]["evidence"][1]["text"] == "Project schedule Monday; tea jasmine"
    old_plan = read_json(tmp_path / "maintenance/2/batch-0000/old-support-delivery-plan.json")
    assert len(old_plan["selected_ranges"]) == 1 and old_plan["omitted_ranges"] == []
    assert old_plan["current_body_tokens"] + old_plan["selected_old_body_tokens"] <= 4096
    complete = read_json(tmp_path / "maintenance/2/complete.json")
    assert complete["unprocessed"] == []
    assert read_json(tmp_path / "maintenance/2/batch-0000/writer-envelope.json")["records"]


def test_old_support_preflight_omits_unaffordable_ranges_without_store_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from milai_lab.methods.edit_features import EditFeatures

    run = execution(tmp_path, "B0")
    features = EditFeatures.from_settings({name: True for name in (
        "matter_organization", "semantic_operations", "bound_references",
        "single_record_changes", "source_metadata",
    )})
    old_text, current_text = "Quiet reminders only on weekdays.", "Now use bright reminders."
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(
            store, ("old-support-budget", "owner"), "owner", tmp_path / "bank.lock",
            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
        )
        method = EditMemory(service, "B0", interface_version="I2", features=features)
        old_ref = service.capture_user(
            "s0", "old", old_text, occurred_at="2030-01-01"
        )["source_ref"]
        service.bind_source_boundary("s0", "old", [old_ref])
        old_view = method.writer_request(method.prepare([old_ref], "reminders"), request_id="old")
        saved = method.apply("s0", "form", method.decode_proposal({
            "action": "create", "matter": "Reminder tone", "clauses": [{
                "text": old_text, "evidence": ["e1"],
                "assertion": {"source": "e1", "kind": "reported"},
            }],
        }, old_view["mapping"]))
        assert saved["ok"]
        current_ref = service.capture_user(
            "s1", "new", current_text, occurred_at="2030-01-02"
        )["source_ref"]
        service.bind_source_boundary("s1", "new", [current_ref])
        rows = [service.read(saved["id"])]
        delivery = method.prepare(
            [current_ref], "reminders", selected_records=rows, redelivered_ranges=[]
        )
        boundary = dict(service._source_boundaries)
        before = service.records()

        def denied(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("PREFLIGHT_GRANTED_DELIVERY_OR_MUTATED_STORE")

        def plan() -> tuple[dict[str, Any], dict[str, Any]]:
            with monkeypatch.context() as scoped:
                scoped.setattr(service.store, "put", denied)
                return run._old_support_plan(
                    method, delivery, delivery["records"], "2030-01-02", allow_create=True
                )

        run.settings["source_body_tokens"] = len(current_text) + len(old_text) - 1
        run.settings["context_tokens"] = 100000
        subset, metadata = plan()
        assert subset["redelivered_sources"] == [] and metadata["selected_ranges"] == []
        assert metadata["omitted_ranges"][0]["reason"] == "shared_source_body_budget"
        assert len(method.preview_writer_request(subset)["packet"]["evidence"]) == 1

        run.settings["source_body_tokens"] = 4096
        preview = method.preview_writer_request(subset)
        base_messages = run._edit_messages(
            method, preview["packet"], "2030-01-02", allow_create=True, schema=preview["schema"]
        )
        run.settings["context_tokens"] = run.input_tokens(base_messages) + 100 + 512
        subset, metadata = plan()
        assert subset["redelivered_sources"] == []
        assert metadata["omitted_ranges"][0]["reason"] == "complete_request_capacity"

        run.settings["context_tokens"] = 100000
        subset, metadata = plan()
        assert len(metadata["selected_ranges"]) == 1
        assert subset["redelivered_sources"][0]["text"] == old_text
        assert metadata["omitted_ranges"] == []
        executable = method.prepare(
            [current_ref], "reminders", selected_records=rows,
            redelivered_ranges=metadata["selected_ranges"],
        )
        assert method.preview_writer_request(subset) == method.preview_writer_request(executable)
        assert service._source_boundaries == boundary
        assert service.records() == before


def test_truncated_response_has_no_commit_and_no_repeat_on_resume(tmp_path: Path) -> None:
    run = execution(tmp_path, "B0")
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
        budget=budget,
        transport=httpx.MockTransport(lambda r: response({}, finish="length")),
    ) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
            service = MemoryService(
                store,
                ("synthetic", "owner"),
                "owner",
                tmp_path / "bank.lock",
                mutation_contract="event_bound_v1",
            )
            for _ in range(2):
                assert run.maintain(service, observation("s", "Project note"), "1") == []
            assert service.records() == []
    complete = read_json(tmp_path / "maintenance/1/complete.json")
    assert complete["status"] == "COMPLETE_WITH_GAPS"
    assert complete["unprocessed"][0]["source_opportunity_consumed"] is False
    assert budget.state["generation_requests"] == 1


def test_capacity_failure_separates_prepared_sources_from_model_exposure(tmp_path: Path) -> None:
    run = execution(tmp_path, "M")
    run.settings.update(working_sets=False, context_tokens=700)
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response({})

    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100), budget=budget,
        transport=httpx.MockTransport(provider),
    ) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
            service = MemoryService(
                store, ("fixture", "owner"), "owner", tmp_path / "memory.lock",
                mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
            )
            assert run.maintain(service, observation("s1", "Actual source " * 30), "1") == []
            assert service.records() == []
    assert requests == [] and budget.state["generation_requests"] == 0
    views = read_json(tmp_path / "maintenance/1/batch-0000/maintenance-views.json")
    assert views["new_sources_in_prepared_packet"]
    assert views["new_sources_actually_delivered"] == []
    assert not any(views["writer_exposure"].values())


def test_natural_core_and_adjacent_context_preserve_original_ranges() -> None:
    observed = observation("s", "On weekdays.\nThree reviewers.\nHolidays are paused.")
    batches = natural_source_batches(observed, Tokenizer(), 25)
    assert (
        "".join(
            observed.turns[0]["content"][p["start"] : p["end"]] for batch in batches for p in batch
        )
        == observed.turns[0]["content"]
    )
    context = adjacent_source_context(observed, batches[1], Tokenizer(), 25)
    body = "".join(observed.turns[p["turn"]]["content"][p["start"] : p["end"]] for p in context)
    assert "On weekdays" in body and "Three reviewers" in body and "Holidays" in body


def test_oversized_whole_target_remains_gap_while_affordable_target_updates(tmp_path: Path) -> None:
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        packet = json.loads(json.loads(request.content)["messages"][1]["content"])["delivery"]
        requests.append(packet)
        assert len(packet["records"]) == 1
        assert "small" in packet["records"][0]["units"][0]["text"]
        return response(
            {
                "action": "rewrite",
                "target": packet["records"][0]["id"],
                "units": [
                    {"text": "Project corrected small", "evidence": [packet["evidence"][0]["id"]]}
                ],
            }
        )

    run = execution(tmp_path, "B0")
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
        budget=budget,
        transport=httpx.MockTransport(provider),
    ) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
            service = MemoryService(
                store,
                ("synthetic", "owner"),
                "owner",
                tmp_path / "bank.lock",
                mutation_contract="event_bound_v1",
                candidate_contract="read_handle_v1",
            )
            method = EditMemory(service, "B0")
            ids = []
            for ordinal, text in enumerate(("Project " + "x" * 5000, "Project original small")):
                source = service.capture_user("old", str(ordinal), text)
                service.bind_source_boundary("old", str(ordinal), [source["source_ref"]])
                evidence = method.prepare([source["source_ref"]], "Project")["sources"][0][
                    "evidence_id"
                ]
                ids.append(
                    method.apply(
                        "old",
                        f"create:{ordinal}",
                        {
                            "action": "create",
                            "units": [{"text": text, "evidence": [evidence]}],
                        },
                    )["id"]
                )
            observed = observation("s", "Project corrected small")
            source = service.capture_user("s", "turn:0", observed.turns[0]["content"])
            service.bind_source_boundary("s", "prepare", [source["source_ref"]])
            current = EditMemory(service, "B0", interface_version="I2")
            delivery = current.prepare([source["source_ref"]], "Project", selected_records=[])
            packet = current.preview_writer_view(delivery)["packet"]
            minimum = run.input_tokens(
                run._edit_messages(current, packet, observed.date, allow_create=True)
            )
            run.settings["context_tokens"] = minimum + 100 + 512 + 1200
            assert run.maintain(service, observed, "1")
            assert service.read(ids[0])["value"]["revision"] == 1
            assert service.read(ids[1])["value"]["revision"] == 2
    complete = read_json(tmp_path / "maintenance/1/complete.json")
    assert len(requests) == 1 and budget.state["generation_requests"] == 1
    assert complete["status"] == "COMPLETE_WITH_GAPS"
    assert any(gap["reason"] == "whole_target_exceeds_capacity" for gap in complete["unprocessed"])


def test_unknown_response_stops_without_completion_or_blind_retry(tmp_path: Path) -> None:
    run = execution(tmp_path, "B0")
    attempts = []

    def provider(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(200, content=b"unconfirmed invalid transport response")

    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
        transport=httpx.MockTransport(provider),
    ) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
            service = MemoryService(
                store,
                ("synthetic", "owner"),
                "owner",
                tmp_path / "bank.lock",
                mutation_contract="event_bound_v1",
            )
            with pytest.raises(RuntimeError, match="unconfirmed"):
                run.maintain(service, observation("s", "Project note"), "1")
            with pytest.raises(RuntimeError, match="do not blindly repeat"):
                run.maintain(service, observation("s", "Project note"), "1")
            assert service.records() == []
    assert len(attempts) == 1
    assert not (tmp_path / "maintenance/1/complete.json").exists()


@pytest.mark.parametrize("recipe", ["single_pass", "extract_then_edit"])
def test_shared_recipe_benchmark_persists_predictions_without_repeating_calls(tmp_path, recipe):
    run = execution(tmp_path, "B1")
    run.settings["maintenance_recipe"] = recipe
    calls = []

    def provider(request):
        wire = json.loads(request.content)
        payload = json.loads(wire["messages"][1]["content"])
        calls.append(payload)
        if "changes" in payload["response_schema"]["properties"]:
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps({"changes": []})}}], "usage": {"total_tokens": 8}})
        return response({"action": "create", "units": [
            {"text": "The marker is blue.", "evidence": ["e1"]}]})

    with VLLMClient(VLLMConfig("http://local.invalid/v1", "synthetic", max_tokens=100),
                    transport=httpx.MockTransport(provider)) as client:
        run.client = client
        with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
            service = MemoryService(store, ("shared", "alice"), "alice", tmp_path / "memory.lock")
            event = observation("s", "Remember the marker is blue.")
            first = run.maintain(service, event, "event")
            assert len(first) == 1 and "The marker is blue." in first[0]
            assert len(service.records()) == 1
            assert len(calls) == (2 if recipe == "extract_then_edit" else 1)
            before = len(calls)
            assert run.maintain(service, event, "event") == first and len(calls) == before
            assert read_json(tmp_path / "maintenance/event/complete.json")["status"] == "completed"



def test_predict_then_score_reuses_saved_answers_and_diagnostic_retrieval(tmp_path, monkeypatch):
    from milai_lab.runners import edit_benchmarks

    session = {
        "start_time": "Jan 01, 2030, 09:00:00", "end_time": "Jan 01, 2030, 10:00:00",
        "dialogue": [{"role": "user", "content": "The marker is blue.",
                      "timestamp": "Jan 01, 2030, 09:00:00"}],
        "memory_points": [{"memory_content": "The marker is blue.", "memory_type": "preference",
                           "is_update": "True", "original_memories": ["The marker was red."],
                           "memory_source": "user"}],
        "questions": [{"question": "What color is the marker?", "answer": "blue",
                       "evidence": [{"memory_content": "The marker is blue."}]}],
    }
    dataset = tmp_path / "input.jsonl"
    dataset.write_text(json.dumps({"uuid": "alice", "sessions": [session]}) + "\n")
    run = execution(tmp_path / "run", "B1")
    run.retrieval_embeddings = None
    run.settings.update(maintenance_recipe="extract_then_edit", halumem={
        "path": str(dataset), "users": ["alice"], "session_prefix": 1,
        "official_checkout": "unused-by-this-engineering-fixture"})
    judge_calls = []

    class AuthorFixture:
        def __init__(self, checkout, judge):
            pass

        def score(self, name, *args):
            judge_calls.append((name, args))
            return {"evaluation_result": "unexpected_original_label", "accuracy_score": 1}

        def aggregate_results(self, records):
            return dict(records)

    monkeypatch.setattr(edit_benchmarks, "HaluMemOfficial", AuthorFixture)

    def provider(request):
        wire = json.loads(request.content)
        if wire["messages"][0]["content"].startswith("Answer the current question"):
            content = "The marker is blue."
        elif wire["messages"][0]["content"].startswith("Extract brief candidate"):
            content = json.dumps({"changes": []})
        else:
            content = json.dumps({"proposals": [{"action": "create", "units": [
                {"text": "The marker is blue.", "evidence": ["e1"]}]}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": content}}], "usage": {"total_tokens": 8}})

    with VLLMClient(VLLMConfig("http://local.invalid/v1", "synthetic", max_tokens=100),
                    transport=httpx.MockTransport(provider)) as client:
        run.client = client
        predicted = run.halumem("predict")
        assert predicted == {"status": "PREDICTIONS_SAVED", "sessions": 1, "judge_calls": 0}
        assert judge_calls == []
        snapshot = run.root / "predictions/halumem/alice/0/complete.json"
        original = snapshot.read_bytes()
        saved = read_json(snapshot)
        assert saved["update_retrieval"] == [["The marker is blue."]]
        assert saved["state"] and saved["prediction"]["questions"][0]["hypothesis"]

        def forbidden(*args, **kwargs):
            raise AssertionError("Scoring must not invoke prediction or retrieval again")

        monkeypatch.setattr(run, "maintain", forbidden)
        monkeypatch.setattr(run, "answer", forbidden)
        monkeypatch.setattr(run, "_score_retrieval", forbidden)
        result = run.halumem("score")
        assert snapshot.read_bytes() == original
        assert [name for name, _ in judge_calls] == [
            "update_memory", "memory_accuracy", "question"]
        assert judge_calls[-1][1][-1] == saved["prediction"]["questions"][0]["hypothesis"]
        assert result["memory_update_records"][0]["memory_update_type"] == (
            "unexpected_original_label")
        assert result["question_answering_records"][0]["result_type"] == (
            "unexpected_original_label")
        assert result["supplemental_denominators"]["invalid_update_judgements"] == 1


def test_longmemeval_deferred_score_uses_saved_hypothesis(tmp_path, monkeypatch):
    from milai_lab.runners import edit_benchmarks

    dataset = tmp_path / "long.json"
    dataset.write_text(json.dumps([{
        "question_id": "case", "question": "Marker?", "answer": "blue",
        "question_type": "single-session-user", "question_date": "2030-01-02",
        "haystack_sessions": [[{"role": "user", "content": "Blue marker."}]],
        "haystack_dates": ["2030-01-01"], "haystack_session_ids": ["first"],
    }]))
    run = execution(tmp_path / "run", "B1")
    run.retrieval_embeddings = None
    run.settings["longmemeval"] = {
        "path": str(dataset), "questions": ["case"], "official_checkout": "fixture"}
    calls = []
    monkeypatch.setattr(run, "maintain", lambda *args: calls.append("maintain"))
    monkeypatch.setattr(run, "answer", lambda *args: calls.append("answer") or "blue")
    monkeypatch.setattr(run, "call", lambda *args, **kwargs: calls.append("judge") or "yes")

    class AuthorFixture:
        def __init__(self, checkout):
            calls.append("author_loaded")

        def make_prompt(self, case, answer):
            assert answer == "blue"
            return "judge fixture"

        def label(self, verdict):
            return verdict == "yes"

    monkeypatch.setattr(edit_benchmarks, "LongMemEvalOfficial", AuthorFixture)
    assert run.longmemeval("predict")[0]["hypothesis"] == "blue"
    assert calls == ["maintain", "answer"]
    snapshot = run.root / "predictions/longmemeval/case/complete.json"
    original = snapshot.read_bytes()
    assert run.longmemeval("score")[0]["autoeval_label"] is True
    assert calls == ["maintain", "answer", "author_loaded", "judge"]
    assert snapshot.read_bytes() == original
