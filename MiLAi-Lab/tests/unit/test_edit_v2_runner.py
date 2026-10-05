"""Actual SQLite/accounted transport integration, with synthetic model responses."""

from __future__ import annotations

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
        assert schema == payload["response_format"]["json_schema"]["schema"]
        requests.append(packet)
        evidence = packet["evidence"][0]["id"]
        assertion = {"source": evidence, "kind": "reported"}
        if not packet["records"]:
            assert schema["properties"]["records"]["properties"] == {}
            envelope = {
                "creates": [
                    {"action": "create", "matter": matter,
                     "units": [{"text": text, "role": "content", "evidence": [evidence],
                                "assertion": assertion}]}
                    for matter, text in (("Project schedule", "Project schedule Monday"),
                                         ("Tea preference", "Tea preference jasmine"))
                ],
                "records": {},
            }
        else:
            record = next(r for r in packet["records"]
                          if "Monday" in r["units"][0]["text"])
            unit = record["units"][0]
            assert record["matter"] == "Project schedule"
            if arm in {"B0", "B2"}:
                change = {"action": "rewrite", "units": [
                    {"text": "Project schedule Thursday", "role": "content",
                     "evidence": [evidence], "assertion": assertion}
                ]}
            else:
                change = {"action": "edit", "edits": [
                    {"operation": "change_value" if arm == "M" else "replace",
                     "target_unit": unit["id"], "text": "Project schedule Thursday",
                     "evidence": [evidence], "assertion": assertion}
                ]}
            envelope = {"creates": [], "records": {record["id"]: change}}
        Draft202012Validator(schema).validate(envelope)
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(envelope)}}],
            "usage": {"total_tokens": 8},
        })

    run = execution(tmp_path, arm)
    run.settings["edit_features"] = {name: True for name in (
        "matter_organization", "semantic_operations", "bound_references",
        "single_record_changes", "source_metadata",
    )}
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
    complete = read_json(tmp_path / "maintenance/2/complete.json")
    assert complete["unprocessed"] == []
    assert read_json(tmp_path / "maintenance/2/batch-0000/writer-envelope.json")["records"]


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
