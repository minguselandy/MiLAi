"""Existing Agent/provider composition with MockHTTP, real SQLite SDK/checkpoint/world."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.harness.artifact_io import write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.runners import v13_1_d0 as runner


def prepared(tmp_path: Path, **config_updates: Any) -> Path:
    RunBudget(RunLimits(1, 1, None, None, None), tmp_path / "budget.json").reserve(
        "chat/completions", {"messages": [], "max_tokens": 1}
    )
    fixture = {
        "kind": "MILAI_V13_1_D0_NORMAL_USE",
        "cases": [
            {
                "case_id": "mechanical",
                "owner": "alice",
                "category": "object_continue",
                "initial_world": {"label_available": False},
                "messages": [
                    {
                        "message_id": "m1",
                        "session_id": "s1",
                        "content": "Reserve parcel and save result",
                        "new_process_before": False,
                    },
                    {
                        "message_id": "m2",
                        "session_id": "s2",
                        "content": "FUTURE_USER_MESSAGE",
                        "new_process_before": True,
                    },
                ],
            }
        ],
    }
    config = {
        "host": {
            "base_url": "http://mock/v1/",
            "model": "mechanical-model",
            "tool_mode": "json_action",
            "max_tokens": 2048,
        },
        "capacity": {},
        "budget_path": str(tmp_path / "budget.json"),
    }
    config.update(config_updates)
    write_json(tmp_path / "public.json", fixture)
    write_json(tmp_path / "config.json", config)
    root = tmp_path / "run"
    runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    return root


@pytest.mark.parametrize("configured_prompt", [None, "  Configured prompt sentinel.\n"])
@pytest.mark.parametrize("receipt_contract", ["optional", "explicit_receipt_v1"])
def test_existing_agent_loop_captures_real_partial_receipt_and_only_seen_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_prompt: str | None,
    receipt_contract: str,
) -> None:
    root = prepared(
        tmp_path, memory_receipt_contract=receipt_contract,
        **({"system_prompt": configured_prompt} if configured_prompt else {}),
    )
    expected_prompt = runner.SYSTEM_PROMPT if configured_prompt is None else configured_prompt
    expected_hash = hashlib.sha256(expected_prompt.encode()).hexdigest()
    assert runner._frozen(root)["prompt_sha256"] == expected_hash
    assert runner._frozen(root)["memory_receipt_contract"] == receipt_contract
    explicit = receipt_contract == "explicit_receipt_v1"
    fields = {"status": "reserved_label_failed", "label_status": "not_created"}
    proposed_content = (
        json.dumps(fields) if explicit else "Raw Host proposal: reserved, label unavailable"
    )
    wires = []
    actions = [
        {
            "calls": [
                {
                    "name": "reserve_and_label",
                    "arguments": {
                        "item_key": "parcel",
                        "quantity": 1,
                        "destination": "desk",
                        "packing": "box",
                    },
                }
            ]
        },
        {
            "calls": [
                {
                    "name": "manage_memory",
                    "arguments": {
                        "content": proposed_content,
                        "kind": "episodic",
                        "basis": "tool_observation",
                        "fields": fields,
                        **({"content_format": "receipt_json_v1"} if explicit else {}),
                    },
                }
            ]
        },
        {"answer": "The reservation exists. Label pending. Memory save committed."},
        {"calls": [{"name": "search_memory", "arguments": {"query": "reserved"}}]},
        {"answer": "Prior actual receipt reported label not created."},
    ]
    original_client = runner.VLLMClient

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        return httpx.Response(
            200,
            json={
                "id": f"g-{len(wires)}",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(actions[len(wires) - 1]),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            },
        )

    monkeypatch.setattr(runner, "HostCapacity", lambda config: None)
    monkeypatch.setattr(
        runner,
        "VLLMClient",
        lambda *args, **kwargs: original_client(
            *args, transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    first = runner.step(root, "mechanical", 0)
    assert first["status"] == "completed", first
    assert "FUTURE_USER_MESSAGE" not in json.dumps(wires)
    assert first["records"][0]["value"]["fields"]["label_status"] == "not_created"
    assert first["records"][0]["value"]["content_verification"] == "unchecked"
    assert first["records"][0]["value"]["content"] == proposed_content
    if explicit:
        assert first["records"][0]["value"]["body_fields_verification"] == "matches_proposed_fields"
    else:
        assert "body_fields_verification" not in first["records"][0]["value"]
    assert len(first["world"]["attempts"]) == 1
    assert (
        first["execution_wall_ns"] > 0 and first["persistent_resource_bytes"]["memory.sqlite"] > 0
    )
    trace_path = next(root.glob("*/message-0.jsonl"))
    trace = [json.loads(line) for line in trace_path.read_text().splitlines()]
    discovery = [row for row in trace if row["event"] == "v13_ref_discovery"]
    assert len(discovery) == 1 and discovery[0]["lookup_calls"] == 1
    assert discovery[0]["original_lookup_result"]["status"] == "found"
    observed = next(row for row in trace if row["event"] == "v13_business_receipt")
    assert json.loads(observed["original_receipt"]["content"])["status"] == "reserved_label_failed"
    second = runner.step(root, "mechanical", 1)
    assert second["status"] == "completed", second
    assert second["records"] == first["records"]
    assert len(second["world"]["attempts"]) == 1
    second_trace = [
        json.loads(line) for line in next(root.glob("*/message-1.jsonl")).read_text().splitlines()
    ]
    relation = [row for row in second_trace if row["event"] == "v13_memory_source_relation"]
    if explicit:
        assert len(relation) == 1 and relation[0]["query"] == "reserved"
        assert relation[0]["store_get_calls"] == 0 and relation[0]["lookups"] == []
        assert relation[0]["joined_records"] == 1
    else:
        assert relation == []
    # Resubmission of a completed public message spends no further generation.
    assert runner.step(root, "mechanical", 0) == first
    assert len(wires) == 5
    for wire in wires:
        assert wire["messages"][0]["role"] == "system"
        # The existing JSON-action provider prefixes its wire protocol; the
        # effective Agent prompt must still be passed through verbatim.
        assert wire["messages"][0]["content"].endswith(expected_prompt)
        if configured_prompt is not None:
            assert runner.SYSTEM_PROMPT not in wire["messages"][0]["content"]
    # JSON-action catalog is sent in the actual provider system wire, and the
    # configured contract must also be enforced by the constructed service.
    assert ("receipt_json_v1" in wires[0]["messages"][0]["content"]) == explicit


@pytest.mark.parametrize("invalid_contract", [None, True, 123, [], {}, "", "explicit_receipt_v2"])
def test_prepare_rejects_invalid_supplied_memory_receipt_contract(
    tmp_path: Path, invalid_contract: Any
) -> None:
    with pytest.raises(ValueError, match="V13_MEMORY_RECEIPT_CONTRACT_INVALID"):
        prepared(tmp_path, memory_receipt_contract=invalid_contract)
    assert not (tmp_path / "run/input-freeze.json").exists()


def test_optional_catalog_matches_pre_contract_frozen_catalog_exactly(tmp_path: Path) -> None:
    catalog = runner._catalog(tmp_path, "field_grounded")
    assert catalog == runner._catalog(tmp_path, "field_grounded", receipt_contract="optional")
    serialized = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()
    # Captured from the actual pre-change R9 tool composition, not synthesized
    # by removing fields from the candidate catalog.
    assert hashlib.sha256(serialized).hexdigest() == (
        "a8e94be08e0b4114a215289a4cd612993bddf85a59b1e3b2bae3cd43a5c30926"
    )
    explicit = runner._catalog(tmp_path, "field_grounded", receipt_contract="explicit_receipt_v1")
    assert explicit[1:] == catalog[1:]
    legacy_manage = catalog[0]["function"]
    explicit_manage = explicit[0]["function"]
    properties = explicit_manage["parameters"]["properties"]
    assert "content_format" in properties
    assert "content_format" not in legacy_manage["parameters"]["properties"]
    assert {key: value for key, value in properties.items() if key != "content_format"} == (
        legacy_manage["parameters"]["properties"]
    )
    assert explicit_manage["description"].startswith(legacy_manage["description"])
    assert "notes" in explicit_manage["description"]
    assert "unchecked" in explicit_manage["description"]
    root = prepared(tmp_path)
    assert runner._frozen(root)["memory_receipt_contract"] == "optional"
    assert runner._frozen(root)["tool_catalog"] == catalog


@pytest.mark.parametrize("invalid_prompt", [None, True, 123, [], {}, "", " \t\n"])
def test_prepare_rejects_invalid_supplied_system_prompt(
    tmp_path: Path, invalid_prompt: Any
) -> None:
    with pytest.raises(ValueError, match="V13_D0_SYSTEM_PROMPT_INVALID"):
        prepared(tmp_path, system_prompt=invalid_prompt)
    assert not (tmp_path / "run/input-freeze.json").exists()


def test_pre_host_capture_failure_has_first_terminal_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def failed_capture(*args: Any, **kwargs: Any) -> None:
        raise OSError("capture storage failed before Host")

    monkeypatch.setattr(runner.MemoryService, "capture_user", failed_capture)
    output = runner.step(root, "mechanical", 0)
    assert output["status"] == "interrupted"
    assert output["capture_status"] == "unconfirmed"
    assert output["error"] == "capture storage failed before Host"
    assert runner.step(root, "mechanical", 0) == output


def test_freeze_preserves_wire_source_identity_and_rejects_input_drift(tmp_path: Path) -> None:
    root = prepared(tmp_path)
    frozen = runner._frozen(root)
    assert {
        "src/milai_lab/memory/service.py",
        "src/milai_lab/application/refs.py",
        "src/milai_lab/providers/chat_bridge.py",
        "src/milai_lab/methods/langmem_recipe.py",
        "src/milai_lab/providers/request_pipeline.py",
        "src/milai_lab/methods/local_state_attention/integration.py",
        "src/milai_lab/baselines/langmem_instrumentation.py",
    } <= frozen["source_sha256"].keys()
    assert {tool["function"]["name"] for tool in frozen["tool_catalog"]} == {
        "manage_memory",
        "search_memory",
        "read_memory",
        "reserve_and_label",
        "get_reservation",
        "complete_label",
    }
    assert frozen["tool_catalog_sha256"] and frozen["memory_retrieval"] == "raw_keyword"
    (tmp_path / "public.json").write_text("{}")
    with pytest.raises(ValueError, match="INPUT_CHANGED_AFTER_FREEZE"):
        runner._frozen(root)
