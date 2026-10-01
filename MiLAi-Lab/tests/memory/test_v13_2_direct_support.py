"""Synthetic actual Store/tools/bridge/writer paths, denied sockets, no semantic oracle."""

from __future__ import annotations

import json
import runpy
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.store.sqlite import SqliteStore
from pydantic import ValidationError

from milai_lab.contracts.memory import VerifiedObjectRef
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory import service as service_module
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.memory.support_display import encode_field_support, expand_field_support
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_d0 as d0
from milai_lab.runners import v13_1_p5 as p5

FIELDS = ("content", "scope", "basis", "kind")
CONFIG_HASH = "a" * 64


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SOCKET_FORBIDDEN")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, denied)
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)

    class FixedClock:
        @staticmethod
        def now(*args: Any, **kwargs: Any) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(service_module, "datetime", FixedClock)


@contextmanager
def opened(
    root: Path, *, owner: str = "alice", profile: str = "direct_support_v1"
) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "store.sqlite")) as store:
        yield MemoryService(
            store,
            ("synthetic", owner),
            owner,
            root / "service.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
            support_contract=profile,
        )


def cfg(
    service: MemoryService, message: str = "u", config_hash: str = CONFIG_HASH
) -> dict[str, Any]:
    return {
        "configurable": {
            "user_id": service.owner,
            "v13_session": "s",
            "v13_turn_id": message,
            "v13_support_config_sha256": config_hash,
        }
    }


def turn(
    service: MemoryService,
    message: str = "u",
    text: str = "Actual public trigger",
    phase: str = "start",
    config_hash: str = CONFIG_HASH,
) -> str:
    source = service.capture_user("s", message, text)["source_ref"]
    service.bind_source_boundary("s", message, [source])
    if service.support_contract == "direct_support_v1":
        service.bind_public_turn("s", message, source, config_sha256=config_hash, phase=phase)
    return str(source)


def selected(refs: list[str]) -> dict[str, Any]:
    return {name: {"source_refs": refs} for name in FIELDS}


def reused(handle: str) -> dict[str, Any]:
    return {name: {"reuse_support_from": handle} for name in FIELDS}


def invoke(
    service: MemoryService,
    name: str,
    args: dict[str, Any],
    key: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool = next(t for t in create_service_tools(service, replay_requested=True) if t.name == name)
    result = tool.invoke(
        {"type": "tool_call", "name": name, "args": args, "id": key}, config=config or cfg(service)
    )
    return json.loads(result.content)


def save(
    service: MemoryService, refs: list[str], key: str = "save", **extra: Any
) -> dict[str, Any]:
    args = {
        "content": "Actual retained content / texto real",
        "source_refs": refs,
        "field_support": selected(refs),
        **extra,
    }
    return invoke(service, "manage_memory", args, key)


@pytest.mark.parametrize(
    "mutation,candidate",
    [("legacy", "read_handle_v1"), ("event_bound_v1", None), ("event_bound_v1", "id_revision_v1")],
)
def test_explicit_contract_requirement(
    tmp_path: Path, mutation: str, candidate: str | None
) -> None:
    with SqliteStore.from_conn_string(":memory:") as store:
        with pytest.raises(ValueError, match="REQUIRES_EVENT_BOUND_READ_HANDLE"):
            MemoryService(
                store,
                ("synthetic", "alice"),
                "alice",
                tmp_path / "lock",
                mutation_contract=mutation,
                candidate_contract=candidate,
                support_contract="direct_support_v1",
            )


def test_question_trigger_is_separate_from_selected_historical_support(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        old = service.capture_user("s", "old", "真实偏好 / Preferencia expresa")["source_ref"]
        current = turn(service)
        result = save(service, [old])
        assert result["ok"] and result["source_refs"] == [old]
        assert current not in result["source_refs"]
        assert result["trigger_binding"]["source_ref"] == current
        assert result["field_support"]["content"]["source_refs"] == [old]
        assert result["content_verification"] == "unchecked"
        omitted = invoke(
            service, "manage_memory", {"content": "Cannot guess", "source_ref": old}, "omitted"
        )
        assert omitted["reason"] == "source_selection_required"
        assert omitted["formation_status"] == "pending"
        assert len(service.records()) == 1
        assert (
            invoke(
                service,
                "manage_memory",
                {"content": "No field map", "source_refs": [old]},
                "no-map",
            )["reason"]
            == "field_support_required"
        )


def test_explicit_legacy_whole_version_reuse_and_selected_leaf_inclusion(tmp_path: Path) -> None:
    with opened(tmp_path, profile="legacy") as service:
        original = turn(service)
        created = invoke(
            service,
            "manage_memory",
            {
                "content": "Exact body",
                "source_refs": [original],
                "scope": {"project": "draft", "nullable": None},
            },
            "legacy",
        )
        handle = service.read(created["id"])["candidate_handle"]
    with opened(tmp_path) as service:
        trigger = turn(service, "next", "Current question")
        field_support = reused(handle)
        field_support["scope"] = {"source_refs": [trigger]}
        args = {
            "candidate_handle": handle,
            "semantic_patch": {"scope": {"phase": "review"}},
            "source_refs": [original, trigger],
            "field_support": field_support,
        }
        result = invoke(service, "revise_memory", args, "patch", cfg(service, "next"))
        assert result["revision"] == 2
        assert (
            result["field_support"]["content"]["reused_from"]["lineage_scope"]
            == "legacy_whole_version_set"
        )
        assert result["field_support"]["content"]["source_refs"] == [original]
        assert service.read(created["id"])["value"]["content"] == "Exact body"
        assert invoke(service, "revise_memory", args, "patch", cfg(service, "next"))["replayed"]
        next_handle = service.read(created["id"])["candidate_handle"]
        args.update(
            candidate_handle=next_handle, field_support=reused(next_handle), source_refs=[trigger]
        )
        assert invoke(service, "revise_memory", args, "missing-old", cfg(service, "next"))[
            "reason"
        ] == ("field_support_selected_leaves_required")


@pytest.mark.parametrize(
    "patch,field,equal",
    [
        ({"content": "Exact body"}, "content", True),
        ({"content": "Exact body "}, "content", False),
        ({"content": "Exact\nbody"}, "content", False),
        ({"content": "e\u0301"}, "content", False),
        ({"scope": {"flag": 1}}, "scope", False),
        ({"scope": {"flag": True}}, "scope", True),
        ({"scope": {"absent": None}}, "scope", False),
        ({"scope": {"ordered": [2, 1]}}, "scope", False),
        ({"scope": {"ordered": [1, 2], "flag": True}}, "scope", True),
        ({"kind": "episodic"}, "kind", False),
        ({"basis": "inference"}, "basis", False),
    ],
)
def test_exact_whole_field_comparison(
    tmp_path: Path, patch: dict[str, Any], field: str, equal: bool
) -> None:
    with opened(tmp_path) as service:
        source = turn(service)
        created = save(
            service, [source], content="Exact body", scope={"flag": True, "ordered": [1, 2]}
        )
        handle = service.read(created["id"])["candidate_handle"]
        support = selected([source])
        support[field] = {"reuse_support_from": handle}
        result = invoke(
            service,
            "revise_memory",
            {
                "candidate_handle": handle,
                "semantic_patch": patch,
                "source_refs": [source],
                "field_support": support,
            },
            "patch",
        )
        assert result["ok"] == equal
        if not equal:
            assert result["reason"] == "field_support_changed_field"
            assert service.read(created["id"])["value"]["revision"] == 1


def test_unicode_and_whole_field_not_subclaim(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = turn(service)
        created = save(service, [source], content="é / 成功完成操作")
        handle = service.read(created["id"])["candidate_handle"]
        args = {
            "candidate_handle": handle,
            "source_refs": [source],
            "field_support": reused(handle),
            "semantic_patch": {"content": "e\u0301 / 成功完成操作"},
        }
        assert (
            invoke(service, "revise_memory", args, "normalized")["reason"]
            == "field_support_changed_field"
        )
        args["semantic_patch"] = {"content": "é / 成功完成操作; new status"}
        assert (
            invoke(service, "revise_memory", args, "subclaim")["reason"]
            == "field_support_changed_field"
        )
        later = service.capture_user("s", "explicit", "Explicit new statement")["source_ref"]
        args["source_refs"] = [source, later]
        args["field_support"] = selected([source, later])
        assert invoke(service, "revise_memory", args, "selected")["ok"]


def test_reopen_resume_identity_exact_replay_and_trigger_conflict(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = turn(service)
        result = save(service, [source])
        bound = result["trigger_binding"]
    with opened(tmp_path) as service:
        assert service.public_turn("s") is None
        assert turn(service, phase="resume") == source
        assert service.public_turn("s") == bound
        assert save(service, [source])["replayed"]
        row = service.store.get(service.turns_namespace, service_module._hash(["s", "u"]))
        assert row.value["last_binding_phase"] == "resume"
        with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
            turn(service, phase="resume", config_hash="b" * 64)
        other = service.capture_user("s", "missing", "No persisted trigger")["source_ref"]
        with pytest.raises(ValueError, match="RESUME_MISSING"):
            service.bind_public_turn(
                "s", "missing", other, config_sha256=CONFIG_HASH, phase="resume"
            )
        turn(service, "next", "Different public trigger")
        conflict = invoke(
            service,
            "manage_memory",
            {
                "content": "Actual retained content / texto real",
                "source_refs": [source],
                "field_support": selected([source]),
            },
            "save",
            cfg(service, "next"),
        )
        assert conflict["reason"] == "proposal_id_conflict"
        assert service.read(result["id"])["value"]["revision"] == 1


def test_config_owner_trigger_and_stale_cas(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = turn(service)
        bad = invoke(
            service,
            "manage_memory",
            {"content": "Actual", "source_refs": [source], "field_support": selected([source])},
            "config",
            cfg(service, config_hash="b" * 64),
        )
        assert bad["reason"] == "public_turn_required_or_mismatched"
        with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
            invoke(
                service,
                "manage_memory",
                {"content": "Actual"},
                "foreign",
                {"configurable": {**cfg(service)["configurable"], "user_id": "bob"}},
            )
        first = save(service, [source])
        handle = service.read(first["id"])["candidate_handle"]
        args = {
            "candidate_handle": handle,
            "semantic_patch": {"content": "Explicit replacement"},
            "source_refs": [source],
            "field_support": selected([source]),
        }
        assert invoke(service, "revise_memory", args, "advance")["revision"] == 2
        assert invoke(service, "revise_memory", args, "stale")["reason"] == "revision_conflict"
        assert service.read(first["id"], 1)["value"]["content"] != "Explicit replacement"


def test_hash_change_wrong_owner_and_unbound_trigger_preserve_pending(tmp_path: Path) -> None:
    with opened(tmp_path, owner="bob") as foreign:
        other = turn(foreign)
    with opened(tmp_path) as service:
        source = turn(service)
        assert save(service, [other], "other")["reason"] == "source_not_found_or_not_owned"
        created = save(service, [source])
        handle = service.read(created["id"])["candidate_handle"]
        event = service.store.get(service.sources_namespace, source).value
        event["content"] = "changed bytes with old hash"
        service.store.put(service.sources_namespace, source, event, index=False)
        result = invoke(
            service,
            "revise_memory",
            {
                "candidate_handle": handle,
                "semantic_patch": {},
                "source_refs": [source],
                "field_support": reused(handle),
            },
            "tamper",
        )
        assert not result["ok"] and result["raw_preserved"]
        assert service.store.get(service.namespace, created["id"]).value["_v13_1"]["revision"] == 1


def tool_source(service: MemoryService) -> tuple[str, str]:
    source = service.event_id("s", "actual-tool", "tool")
    ref = VerifiedObjectRef(
        id=source + ":O",
        external_id="O",
        application="synthetic.object",
        owner=service.owner,
        source_ref=source,
        fields={"status": "ready", "label_status": "created"},
    )
    return str(
        service.capture_tool(
            "s",
            "actual-tool",
            "synthetic_lookup",
            '{"status":"ready","label_status":"created"}',
            ref,
        )["source_ref"]
    ), ref.id


def test_object_dto_unchanged_string_contract_and_receipt_consumption(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        turn(service)
        source, object_id = tool_source(service)
        before = service.source(source)
        args = {
            "content": "Actual tool observation",
            "source_refs": [source],
            "field_support": selected([source]),
            "basis": "tool_observation",
            "object_ref": object_id,
            "fields": {"status": "ready", "label_status": "created"},
        }
        assert invoke(service, "manage_memory", {**args, "object_ref": "wrong"}, "wrong")[
            "reason"
        ] == ("object_ref_not_found_or_not_owned")
        with pytest.raises(ValidationError):
            invoke(service, "manage_memory", {**args, "object_ref": before["object_ref"]}, "dto")
        assert service.argument_ids(before)["tool_argument_ids"]["object_ref"] == object_id
        result = invoke(service, "manage_memory", args, "tool")
        assert result["ok"]
        assert service.source(source) == before
        assert service.semantic_receipts(before["event_id"])
        assert service.semantic_receipts_for_turn("s") == [result]
        assert not service.semantic_receipts(service.public_turn("s")["source_ref"])
        assert invoke(service, "manage_memory", args, "repeat")["status"] == "no_change"
        assert invoke(service, "manage_memory", {**args, "content": "Different"}, "consume")[
            "reason"
        ] == ("receipt_already_consumed")


def model(
    tmp_path: Path, actions: list[dict[str, Any]], *, communication: str = "legacy"
) -> tuple[Any, list[dict[str, Any]]]:
    wires = []

    def response(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {"calls": actions} if actions else {"answer": "No change."}
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    budget = RunBudget(RunLimits(1, 1, 20, 1000000, 0), tmp_path / "local-budget.json")
    client = VLLMClient(
        VLLMConfig("http://mock/v1", "mock", max_tokens=256),
        budget=budget,
        transport=httpx.MockTransport(response),
    )
    result = LangMemRecipeChatModel(
        client=client,
        capacity_path=tmp_path / "local-capacity.json",
        max_calls_per_message=12,
        tool_schema_communication=communication,
    )
    result.begin_public_message("u")
    return result, wires


def test_actual_host_invoke_tool_only_support_suppresses_writer_by_trigger(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        public = turn(service)
        source, object_id = tool_source(service)
        args = {
            "content": "Actual observation",
            "basis": "tool_observation",
            "source_refs": [source],
            "object_ref": object_id,
            "field_support": selected([source]),
        }
        host, wires = model(tmp_path, [{"name": "manage_memory", "arguments": args}])
        tools = create_service_tools(service, replay_requested=True)
        response = host.bind_tools(list(tools)).invoke(
            [HumanMessage("actual public input")], config=cfg(service)
        )
        action = response.tool_calls[0]
        receipt = invoke(service, action["name"], action["args"], action["id"])
        assert receipt["ok"] and public not in receipt["source_refs"]
        recipe = GroundedMemoryRecipe(service, len)
        maintenance = recipe.maintain(
            host,
            session="s",
            turn_id="u",
            source_refs=[public, source],
            config=cfg(service),
            instruction="Use explicit supporting leaves.",
            repairs=0,
        )
        assert maintenance["status"] == "skipped_host_committed" and len(wires) == 1
        assert (
            maintenance["generation_calls"] == 0
            and maintenance["whole_turn_coverage"] == "unchecked"
        )
        host.client.close()


@pytest.mark.parametrize("communication", ["legacy", "shape_feedback_v1"])
def test_actual_writer_raw_capture_failure_and_partial_batch_preserved(
    tmp_path: Path, communication: str
) -> None:
    with opened(tmp_path) as service:
        public = turn(service)
        source, _ = tool_source(service)
        dto = service.source(source)["object_ref"]
        assert service.semantic_receipts_for_turn("s") == []
        actions = [
            {
                "name": "manage_memory",
                "arguments": {
                    "content": "Selected user fact",
                    "source_refs": [public],
                    "field_support": selected([public]),
                },
            },
            {
                "name": "manage_memory",
                "arguments": {
                    "content": "Invalid DTO",
                    "basis": "tool_observation",
                    "source_refs": [source],
                    "field_support": selected([source]),
                    "object_ref": dto,
                },
            },
        ]
        writer, wires = model(tmp_path, actions, communication=communication)
        recipe = GroundedMemoryRecipe(service, len, tool_schema_communication=communication)
        result = recipe.maintain(
            writer,
            session="s",
            turn_id="u",
            source_refs=[public, source],
            config=cfg(service),
            instruction="Use explicit supporting leaves.",
            repairs=0,
        )
        assert result["status"] == "partial" and result["error_type"] == "ValidationError"
        assert result["committed_actions"] == 1 and len(result["attempted_actions"]) == 2
        if communication != "legacy":
            assert json.loads(result["error"])["origin"] == "pydantic"
            assert "input" not in json.loads(result["error"])
        assert result["attempted_actions"][1]["args"]["object_ref"] == dto
        assert len(wires) == result["generation_calls"] == 1
        request = json.loads(wires[0]["messages"][-1]["content"])
        assert request["actual_events"][1]["object_ref"] == dto
        assert request["source_argument_ids"][1]["tool_argument_ids"]["object_ref"] == dto["id"]
        if communication != "legacy":
            assert "corresponding actual Human Source body" in request["support_policy"]
        assert recipe.maintain(
            writer,
            session="s",
            turn_id="u",
            source_refs=[public, source],
            config=cfg(service),
            instruction="Use explicit supporting leaves.",
            repairs=0,
        )["replayed"]
        assert len(wires) == 1
        writer.client.close()


def test_runner_options_default_and_explicit_support_boundary() -> None:
    assert "support_contract" not in p5._service_options({})
    with pytest.raises(ValueError, match="REQUIRES_EVENT_BOUND_READ_HANDLE"):
        p5._service_options({"memory_support_contract": "direct_support_v1"})
    settings = {
        "memory_support_contract": "direct_support_v1",
        "memory_mutation_contract": "event_bound_v1",
        "memory_candidate_contract": "read_handle_v1",
    }
    assert p5._service_options(settings)["support_contract"] == "direct_support_v1"


def test_absent_corrupt_trigger_and_wrong_public_identity(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = service.capture_user("s", "u", "Actual public trigger")["source_ref"]
        args = {"content": "Actual", "source_refs": [source], "field_support": selected([source])}
        assert invoke(service, "manage_memory", args, "absent")["reason"] == (
            "public_turn_required_or_mismatched"
        )
        turn(service)
        assert (
            invoke(service, "manage_memory", args, "wrong-message", cfg(service, "other"))["reason"]
            == "public_turn_required_or_mismatched"
        )
        service.store.put(
            service.turns_namespace, service_module._hash(["s", "u"]), {"binding": {}}, index=False
        )
        assert invoke(service, "manage_memory", args, "corrupt")["reason"] == (
            "public_turn_required_or_mismatched"
        )
        assert service.records() == []


def test_reuse_must_be_same_actual_record_and_field_set(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = turn(service)
        first = save(service, [source], "first")
        second = save(service, [source], "second")
        first_handle = service.read(first["id"])["candidate_handle"]
        other_handle = service.read(second["id"])["candidate_handle"]
        args = {
            "candidate_handle": first_handle,
            "semantic_patch": {},
            "source_refs": [source],
            "field_support": reused(other_handle),
        }
        assert invoke(service, "revise_memory", args, "other-read")["reason"] == (
            "field_support_candidate_mismatch"
        )
        args["field_support"] = {"content": {"reuse_support_from": first_handle}}
        assert invoke(service, "revise_memory", args, "missing-fields")["reason"] == (
            "field_support_required"
        )
        assert service.read(first["id"])["value"]["revision"] == 1


def test_delivery_metadata_does_not_change_raw_rank_documents(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = turn(service)
        created = save(service, [source])
        recipe = GroundedMemoryRecipe(service, len, material_profile="compact_v1")
        row = service.read(created["id"])
        assert "field_support" not in recipe._record(row)
        delivered = recipe._record(row, delivery=True)
        assert (
            expand_field_support(
                delivered["field_support"],
                delivered["source_bindings"],
                delivered.get("field_support_parents", []),
            )
            == (row["value"]["field_support"])
        )
        assert delivered["trigger_binding"] == row["value"]["trigger_binding"]


@pytest.mark.parametrize("invalid", [True, False, 0.0, -1, 9, "0"])
def test_display_indices_are_explicit_and_never_tool_args(invalid: Any) -> None:
    bindings = [{"source_ref": "actual-id", "role": "user", "content_sha256": "a" * 64}]
    fields = {
        "content": {
            "source_refs": ["actual-id"],
            "source_bindings": bindings,
            "attribution": "model_selected",
        }
    }
    encoded, parents = encode_field_support(fields, bindings)
    assert expand_field_support(encoded, bindings, parents) == fields
    encoded["content"]["record_source_indices"] = [invalid]
    with pytest.raises(ValueError, match="DISPLAY_INDEX_INVALID"):
        expand_field_support(encoded, bindings, parents)


def test_display_preserves_order_full_parent_hashes_and_literal_types() -> None:
    bindings = [
        {"source_ref": "leaf-a", "role": "user", "content_sha256": "a" * 64},
        {"source_ref": "leaf-b", "role": "user", "content_sha256": "b" * 64},
    ]
    parent = {
        "candidate_handle": "actual-handle",
        "record_id": "actual-record",
        "revision": 1,
        "version_sha256": "c" * 64,
        "field_sha256": "d" * 64,
        "lineage_scope": "legacy_whole_version_set",
    }
    fields = {
        field: {
            "source_refs": ["leaf-b", "leaf-a"],
            "source_bindings": bindings[::-1],
            "attribution": "reused_equal_whole_field",
            "reused_from": {**parent},
        }
        for field in FIELDS
    }
    fields["scope"]["reused_from"]["revision"] = 1.0
    encoded, parents = encode_field_support(fields, bindings)
    assert len(parents) == 2
    assert encoded["content"]["record_source_indices"] == [1, 0]
    assert expand_field_support(encoded, bindings, parents) == fields
    assert parents[0]["version_sha256"] == "c" * 64
    encoded["content"]["reused_from_index"] = True
    with pytest.raises(ValueError, match="DISPLAY_INDEX_INVALID"):
        expand_field_support(encoded, bindings, parents)


@pytest.mark.parametrize("communication", ["legacy", "shape_feedback_v1"])
def test_actual_runner_binds_frozen_public_trigger_and_skips_paid_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, communication: str
) -> None:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_v13_1_p5.py")))
    helpers["prepared"](tmp_path)
    capacity = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_v13_1_controls.py"))[
        "settings"
    ](tmp_path)
    settings = read_json(tmp_path / "config.json")
    settings.update(
        capacity=capacity["capacity"],
        memory_mutation_contract="event_bound_v1",
        memory_candidate_contract="read_handle_v1",
        memory_support_contract="direct_support_v1",
        memory_formation_policy="after_host_final_v1",
        writer_system_prompt="Choose actual direct supporting leaves.",
        memory_writer_repairs=0,
        **({"tool_schema_communication": communication} if communication != "legacy" else {}),
    )
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "direct-run"
    frozen = p5.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    assert frozen["memory_support_contract"] == "direct_support_v1"
    bindings = []
    original_bind = MemoryService.bind_public_turn

    def observe_binding(service: MemoryService, *args: Any, **kwargs: Any) -> Any:
        binding = original_bind(service, *args, **kwargs)
        bindings.append(binding)
        return binding

    monkeypatch.setattr(MemoryService, "bind_public_turn", observe_binding)
    responses = [
        {
            "calls": [
                {
                    "name": "manage_memory",
                    "arguments": {
                        "content": "Actual public request to reserve parcel",
                        "source_refs": [],
                        "field_support": {},
                    },
                }
            ]
        },
        {"answer": "Recorded the public request."},
    ]
    wires = []

    def make_model(
        config: dict[str, Any], budget: RunBudget, trace: Any, resource_root: Path
    ) -> Any:
        def response(request: httpx.Request) -> httpx.Response:
            wires.append(json.loads(request.content))
            with (resource_root / "synthetic-host-http-wire.jsonl").open("a") as stream:
                stream.write(json.dumps(wires[-1], ensure_ascii=False) + "\n")
            assert responses, "UNEXPECTED_EXTRA_GENERATION"
            payload = responses.pop(0)
            if "calls" in payload:
                public = bindings[0]["source_ref"]
                assert public in request.content.decode()
                payload["calls"][0]["arguments"].update(
                    source_refs=[public], field_support=selected([public])
                )
            return httpx.Response(
                200,
                json={
                    "id": "synthetic",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(payload),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                },
            )

        client = VLLMClient(
            VLLMConfig(**config["host"]),
            emit=trace,
            budget=budget,
            capacity=HostCapacity(config["capacity"]),
            transport=httpx.MockTransport(response),
        )
        return LangMemRecipeChatModel(
            client=client,
            capacity_path=resource_root / "host-capacity.json",
            tool_schema_communication=config.get("tool_schema_communication", "legacy"),
        )

    monkeypatch.setattr(p5, "make_model", make_model)
    result = p5.step(root, "mechanical", 0)
    assert result["status"] == "completed", result
    assert len(wires) == 2 and not responses
    assert len(result["bank"]) == 1
    public = bindings[0]["source_ref"]
    version = result["bank"][0]["value"]["_v13_1"]["current"]
    assert version["source_refs"] == [public]
    binding = version["trigger_binding"]
    assert binding["source_ref"] == public and binding["message_id"] == "m1"
    assert binding["session"] == "s1" and binding["config_sha256"] == frozen["config_sha256"]
    assert version["field_support"]["content"]["source_refs"] == [public]
    write_json(
        tmp_path / "direct-runner-evidence.json",
        {
            "frozen": frozen,
            "result": result,
            "wire": wires,
            "actual_bindings": bindings,
            "synthetic_mock_dispatches": 2,
            "socket_calls": 0,
        },
    )
    print(json.dumps({"actual_runner_evidence": str(tmp_path / "direct-runner-evidence.json")}))


@pytest.mark.parametrize("path", ["host_commit", "writer_commit", "checkpoint_resume"])
@pytest.mark.parametrize("communication", ["legacy", "shape_feedback_v1"])
def test_actual_d0_entry_profile_host_writer_and_checkpoint_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, communication: str
) -> None:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_v13_1_p5.py")))
    helpers["prepared"](tmp_path)
    capacity = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_v13_1_controls.py"))[
        "settings"
    ](tmp_path)
    settings = read_json(tmp_path / "config.json")
    settings.update(
        host=capacity["host"],
        capacity=capacity["capacity"],
        memory_mutation_contract="event_bound_v1",
        memory_candidate_contract="read_handle_v1",
        memory_support_contract="direct_support_v1",
        memory_formation_policy="after_host_final_v1",
        writer_system_prompt="Select actual supporting leaves for each whole field.",
        memory_writer_repairs=0,
        **({"tool_schema_communication": communication} if communication != "legacy" else {}),
    )
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "direct-d0-run"
    frozen = d0.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    assert frozen["memory_support_contract"] == "direct_support_v1"
    if communication != "legacy":
        from milai_lab.contracts.tool_schema_communication import check_frozen, present_catalog

        assert check_frozen(frozen) == communication
        assert frozen["tool_schema_communication_catalog"] == present_catalog(
            frozen["tool_catalog"], communication
        )
    assert d0._service_options(settings) == p5._service_options(settings)
    catalog = frozen["tool_catalog"]
    manage = next(t for t in catalog if t["function"]["name"] == "manage_memory")
    assert "field_support" in manage["function"]["parameters"]["properties"]
    bindings, phases, wires = [], [], []
    original_bind = MemoryService.bind_public_turn

    def observe_binding(service: MemoryService, *args: Any, **kwargs: Any) -> Any:
        binding = original_bind(service, *args, **kwargs)
        bindings.append(binding)
        phases.append(kwargs["phase"])
        return binding

    monkeypatch.setattr(MemoryService, "bind_public_turn", observe_binding)
    actions = ["commit", "answer"] if path == "host_commit" else ["answer", "commit"]
    original_client = d0.VLLMClient

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        wires.append(wire)
        if communication != "legacy":
            assert "UNUSABLE placeholders" in wire["messages"][0]["content"]
            assert "Human Source body remains selectable support" in wire["messages"][0]["content"]
        assert actions, "UNEXPECTED_EXTRA_GENERATION"
        action = actions.pop(0)
        if action == "commit":
            public = bindings[-1]["source_ref"]
            assert public in request.content.decode()
            payload = {
                "calls": [
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "content": "Actual expressed request for parcel",
                            "source_refs": [public],
                            "field_support": selected([public]),
                        },
                    }
                ]
            }
        else:
            payload = {"answer": "Actual public request acknowledged."}
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(payload)},
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    def client(*args: Any, **kwargs: Any) -> Any:
        return original_client(*args, transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(d0, "VLLMClient", client)
    if path == "checkpoint_resume":
        original_capture = d0._capture_final_assistant

        def cut(*args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt("SYNTHETIC_AFTER_HOST_CHECKPOINT_BEFORE_TERMINAL_RECEIPT")

        monkeypatch.setattr(d0, "_capture_final_assistant", cut)
        with pytest.raises(KeyboardInterrupt, match="SYNTHETIC_AFTER_HOST_CHECKPOINT"):
            d0.step(root, "mechanical", 0)
        assert len(wires) == 1 and phases == ["start"]
        monkeypatch.setattr(d0, "_capture_final_assistant", original_capture)
    result = d0.step(root, "mechanical", 0)
    assert result["status"] == "completed", result
    assert len(wires) == 2 and not actions
    assert phases == (["start", "resume"] if path == "checkpoint_resume" else ["start"])
    assert all(binding == bindings[0] for binding in bindings)
    assert len(result["records"]) == 1
    version = result["records"][0]["value"]
    public = bindings[0]["source_ref"]
    assert version["trigger_binding"] == bindings[0]
    assert version["source_refs"] == [public]
    assert version["field_support"]["content"]["source_refs"] == [public]
    assert bindings[0]["config_sha256"] == frozen["config_sha256"]
    user = next(s for s in result["sources"] if s["event_id"] == public)
    assert bindings[0]["content_sha256"] == user["content_sha256"]
    maintenance = result["semantic_maintenance"]
    assert maintenance["trigger_binding"] == bindings[0]
    if path == "host_commit":
        assert maintenance["status"] == "skipped_host_committed"
        assert maintenance["generation_calls"] == 0
    else:
        assert maintenance["status"] == "committed"
        assert maintenance["generation_calls"] == 1
        request = json.loads(wires[-1]["messages"][-1]["content"])
        assert request["trigger_binding"] == bindings[0]
        assert request["actual_events"][0]["event_id"] == public
    assert d0.step(root, "mechanical", 0) == result and len(wires) == 2
    evidence = tmp_path / "actual-d0-evidence.json"
    write_json(
        evidence,
        {
            "path": path,
            "frozen": frozen,
            "result": result,
            "wire": wires,
            "actual_bindings": bindings,
            "actual_checkpoint_phases": phases,
            "synthetic_mock_dispatches": 2,
            "socket_calls": 0,
            "content_verification": "unchecked",
        },
    )
    print(json.dumps({"actual_d0_evidence": str(evidence)}))


@pytest.mark.parametrize("runner", [d0, p5], ids=["d0", "p5"])
@pytest.mark.parametrize("drift", ["unknown", "missing", "catalog", "guidance"])
def test_communication_actual_entry_drift_rejects_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Any, drift: str
) -> None:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_v13_1_p5.py")))
    helpers["prepared"](tmp_path)
    capacity = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_v13_1_controls.py"))[
        "settings"
    ](tmp_path)
    settings = read_json(tmp_path / "config.json")
    settings.update(
        host=capacity["host"],
        capacity=capacity["capacity"],
        tool_schema_communication="shape_feedback_v1",
    )
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "communication-run"
    frozen = runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    if drift == "unknown":
        frozen["tool_schema_communication"] = "unknown"
    elif drift == "missing":
        frozen.pop("tool_schema_communication_metadata")
    elif drift == "catalog":
        frozen["tool_schema_communication_catalog"][0]["function"]["description"] += " changed"
    else:
        frozen["tool_schema_communication_guidance"] += " changed"
    write_json(root / "input-freeze.json", frozen)
    calls = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        calls.append(True)
        raise AssertionError("DISPATCH_AFTER_INVALID_FREEZE")

    monkeypatch.setattr(runner, "VLLMClient", forbidden)
    result = runner.step(root, "mechanical", 0)
    assert result["status"] == "interrupted", result
    assert result["error_type"] == "ValueError"
    assert result["error"].startswith("TOOL_SCHEMA_COMMUNICATION")
    assert not calls


@pytest.mark.parametrize("communication", ["legacy", "shape_feedback_v1"])
def test_actual_mock_invoke_cap12_and_resume_no_extra_dispatch(
    tmp_path: Path, communication: str
) -> None:
    actual, wires = model(tmp_path, [], communication=communication)
    bound = actual.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Synthetic echo actual x.",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "string"}},
                        "required": ["x"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
    )
    for _ in range(12):
        bound.invoke([HumanMessage(content="Synthetic ordinary public message")])
    assert len(wires) == 12 and read_json(tmp_path / "local-capacity.json")["u"] == 12
    before = read_json(tmp_path / "local-budget.json")
    with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
        bound.invoke([HumanMessage(content="Synthetic ordinary public message")])
    actual.begin_public_message("u", checkpoint_calls=12)
    with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
        bound.invoke([HumanMessage(content="Synthetic ordinary public message")])
    assert len(wires) == 12 and read_json(tmp_path / "local-budget.json") == before


def test_actual_p5_shape_feedback_checkpoint_resume_reuses_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_v13_1_p5.py")))
    helpers["prepared"](tmp_path)
    capacity = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_v13_1_controls.py"))[
        "settings"
    ](tmp_path)
    settings = read_json(tmp_path / "config.json")
    settings.update(
        host=capacity["host"],
        capacity=capacity["capacity"],
        tool_schema_communication="shape_feedback_v1",
        memory_mutation_contract="event_bound_v1",
        memory_candidate_contract="read_handle_v1",
        memory_support_contract="direct_support_v1",
        memory_formation_policy="after_host_final_v1",
        writer_system_prompt="Select real supporting leaves.",
        memory_writer_repairs=0,
    )
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "p5-shape-resume"
    frozen = p5.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    wires = []
    original_client = p5.VLLMClient

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        wires.append(wire)
        assert "[shape_feedback_v1]" in wire["messages"][0]["content"]
        assert len(wires) <= 2, "UNEXPECTED_EXTRA_GENERATION"
        return httpx.Response(
            200,
            json={
                "id": f"resume-{len(wires)}",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"answer": "No semantic change."}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    def client(*args: Any, **kwargs: Any) -> Any:
        return original_client(*args, transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(p5, "VLLMClient", client)
    original_capture = d0._capture_final_assistant

    def cut(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt("SYNTHETIC_P5_AFTER_HOST_CHECKPOINT")

    monkeypatch.setattr(d0, "_capture_final_assistant", cut)
    with pytest.raises(KeyboardInterrupt, match="SYNTHETIC_P5_AFTER_HOST_CHECKPOINT"):
        p5.step(root, "mechanical", 0)
    assert len(wires) == 1
    monkeypatch.setattr(d0, "_capture_final_assistant", original_capture)
    result = p5.step(root, "mechanical", 0, phase="resume", attempt_id="resume")
    assert result["status"] == "completed", result
    assert len(wires) == 2
    assert result["semantic_maintenance"]["generation_calls"] == 1
    assert (
        result["semantic_maintenance"]["trigger_binding"]["config_sha256"]
        == frozen["config_sha256"]
    )
    write_json(
        tmp_path / "shape-p5-resume-evidence.json",
        {
            "frozen": frozen,
            "wire": wires,
            "result": result,
            "mock_dispatches": 2,
            "socket_calls": 0,
        },
    )
