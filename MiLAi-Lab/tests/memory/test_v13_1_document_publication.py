"""Document lifecycle mechanics over actual SQLite and persistent public SDKs."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.document_publication import DOCUMENT_FIELDS, DocumentPublicationWorld
from milai_lab.application.refs import verified_document_ref
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_p5 as p5
from milai_lab.runners import v13_1_p5_compare as compare


def helpers() -> Any:
    path = Path(__file__).parents[1] / "unit/test_v13_1_controls.py"
    spec = importlib.util.spec_from_file_location("document_controls_helpers", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shared = helpers()
TITLE, BODY, AUDIENCE = "Release note", "Original body", "Project members"


def authority() -> list[dict[str, Any]]:
    target = {"title": TITLE}
    return [
        {
            "operation_id": "create",
            "tool": "create_or_update_draft",
            "args": {"title": TITLE, "content": BODY, "document_version": 0},
            "target": target,
        },
        {
            "operation_id": "inspect",
            "tool": "get_document_status",
            "args": {"title": TITLE},
            "target": target,
        },
        {
            "operation_id": "restore",
            "tool": "create_or_update_draft",
            "args": {"title": TITLE, "content": BODY},
            "target": target,
            "document_from": "inspect",
        },
        {
            "operation_id": "approve",
            "tool": "approve_document_version",
            "args": {"title": TITLE},
            "target": target,
            "document_from": ["create", "inspect", "restore"],
        },
        {
            "operation_id": "publish",
            "tool": "publish_approved_document",
            "args": {"title": TITLE, "audience": AUDIENCE},
            "target": target,
            "document_from": ["create", "approve", "inspect", "restore"],
            "retry": "no_effect",
            "recovery_retry": "confirmed_no_effect_v1",
            "recovery_query_operation_id": "inspect",
            "recovery_precondition": {"status": "found", "approval_status": "approved"},
        },
    ]


def prepared(tmp_path: Path, arm: str = "field_grounded", available: bool = True) -> Path:
    config = shared.settings(tmp_path)
    model, _, _ = shared.runtime(tmp_path, config, [])
    write_json(Path(config["budget_path"]), model.client.budget.state)
    config.update(
        application_workflow="document_publication_v1",
        memory_receipt_contract="explicit_receipt_v1",
        cadence="t3_native" if arm == "field_grounded" else "matched_observation_v1",
    )
    fixture = {
        "kind": "MILAI_V13_1_D0_NORMAL_USE",
        "cases": [
            {
                "case_id": "mechanical",
                "owner": "alice",
                "initial_world": {"publication_available": available},
                "messages": [
                    {
                        "message_id": "m0",
                        "session_id": "s0",
                        "content": (
                            "Save and approve the Release note with Original body, publish to "
                            "Project members, then remember the actual result."
                        ),
                        "application_binding": {
                            "task_id": "public-document",
                            "operations": authority(),
                            "recovery": {
                                "absence_means_no_effect": True,
                                "no_deletion": True,
                                "exclusive_writer": True,
                            },
                        },
                    },
                    {
                        "message_id": "m1",
                        "session_id": "s1",
                        "content": (
                            "Look up the Release note actual state; if the body changed, restore "
                            "Original body then approve and publish to Project members; revise "
                            "the recorded observation."
                        ),
                        "application_binding": {
                            "task_id": "public-document",
                            "operations": authority(),
                            "recovery": {
                                "absence_means_no_effect": True,
                                "no_deletion": True,
                                "exclusive_writer": True,
                            },
                        },
                    },
                ],
            }
        ],
    }
    write_json(tmp_path / "config.json", config)
    write_json(tmp_path / "public.json", fixture)
    root = tmp_path / "comparison"
    compare.prepare(tmp_path / "public.json", tmp_path / "config.json", root, arm)
    return root


@pytest.mark.parametrize("mode", ["ref_only", "field_grounded"])
def test_actual_document_refs_finite_typed_claims_body_raw_history_and_reopen(
    tmp_path: Path, mode: Any
) -> None:
    world = DocumentPublicationWorld(tmp_path / "world.sqlite", True)
    path = tmp_path / "memory.sqlite"
    try:
        native = world.create_or_update_draft("alice", TITLE, BODY)
        with SqliteStore.from_conn_string(str(path)) as store:
            service = MemoryService(
                store,
                ("doc", "alice"),
                "alice",
                tmp_path / "lock",
                mode=mode,
                receipt_profile="document_publication_v1",
                receipt_contract="explicit_receipt_v1",
            )
            source = service.event_id("s0", "actual-draft", "tool")
            trace = []
            ref = verified_document_ref(
                world, "alice", source, "create_or_update_draft", native, observer=trace.append
            )
            assert ref and type(ref.fields["document_version"]) is int
            assert (
                trace[0]["lookup_calls"] == 1
                and trace[0]["original_lookup_result"]["content"] == BODY
            )
            assert (
                verified_document_ref(world, "bob", source, "create_or_update_draft", native)
                is None
            )
            assert (
                verified_document_ref(
                    world,
                    "alice",
                    source,
                    "create_or_update_draft",
                    json.dumps({**json.loads(native), "document_id": "fake"}),
                )
                is None
            )
            service.capture_tool("s0", "actual-draft", "create_or_update_draft", native, ref)
            fields = dict(ref.fields)
            raw = {
                "action": "create",
                "id": None,
                "expected_revision": 0,
                "content": json.dumps(fields),
                "content_format": "receipt_json_v1",
                "fields": fields,
                "kind": "episodic",
                "scope": {},
                "basis": "tool_observation",
                "source_ref": source,
                "object_ref": ref.id,
            }
            missing = {**raw, "fields": {}}
            assert service.commit("s0", "missing", missing)["reason"] == "receipt_fields_required"
            wrong = {
                **raw,
                "fields": {**fields, "document_version": 99},
                "content": json.dumps({**fields, "document_version": 99}),
            }
            result = service.commit("s0", "wrong", wrong)
            assert result["ok"] == (mode == "ref_only")

            def actual_query(key: str) -> dict[str, Any]:
                native_query = world.get_document_status("alice", TITLE)
                query_source = service.event_id("s0", key, "tool")
                query_ref = verified_document_ref(
                    world, "alice", query_source, "get_document_status", native_query
                )
                assert query_ref
                service.capture_tool("s0", key, "get_document_status", native_query, query_ref)
                return {
                    **raw,
                    "source_ref": query_source,
                    "object_ref": query_ref.id,
                    "fields": query_ref.fields,
                    "content": json.dumps(query_ref.fields),
                }

            body_raw = actual_query("actual-query-for-body")
            body_conflict = service.commit(
                "s0",
                "body-conflict",
                {**body_raw, "content": json.dumps({**body_raw["fields"], "audience": "invented"})},
            )
            assert body_conflict["ok"] == (mode == "ref_only")
            raw = actual_query("actual-query-for-good")
            fields = raw["fields"]
            assert (
                service.commit(
                    "s0", "bad-type", {**raw, "fields": {**fields, "document_version": True}}
                )["reason"]
                == "invalid_receipt_fields"
            )
            created = service.commit("s0", "good", raw)
            assert created["ok"] and service.commit("s0", "good", raw)["status"] == "no_change"
            assert any(
                item.value["raw"] == missing for item in store.search(service.attempts_namespace)
            )
            # Same receipt/body/public typed integer passes the actual public tool schema.
            manage = create_service_tools(service)[0]
            tool_result = manage.invoke(
                {
                    "type": "tool_call",
                    "id": "public-call",
                    "name": "manage_memory",
                    "args": {
                        "content": raw["content"],
                        "basis": "tool_observation",
                        "kind": "episodic",
                        "fields": fields,
                        "content_format": "receipt_json_v1",
                    },
                },
                config={"configurable": {"user_id": "alice", "v13_session": "s0"}},
            )
            assert json.loads(tool_result.content)["ok"]
            world.approve_document_version("alice", TITLE, 1)
            world.create_or_update_draft(
                "alice", TITLE, "Changed body", 1
            )
            # Historical draft receipt retains its original observed fields after live edit.
            historical = verified_document_ref(
                world, "alice", source, "create_or_update_draft", native
            )
            assert historical and historical.fields == ref.fields
        with SqliteStore.from_conn_string(str(path)) as store:
            service = MemoryService(
                store,
                ("doc", "alice"),
                "alice",
                tmp_path / "lock",
                mode=mode,
                receipt_profile="document_publication_v1",
                receipt_contract="explicit_receipt_v1",
            )
            assert service.read(created["id"])["value"]["fields"] == fields
            assert service.search(TITLE, include_raw=False)["records"]
    finally:
        world.close()


def test_actual_draft_approval_publication_versions_noops_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "world.sqlite"
    world = DocumentPublicationWorld(path, True)
    try:
        draft = json.loads(world.create_or_update_draft("alice", "Release note", "Original body"))
        assert draft["document_version"] == 1
        assert "content_digest" not in draft
        assert draft["approval_status"] == "not_approved"
        approved = json.loads(
            world.approve_document_version(
                "alice", "Release note", draft["document_version"]
            )
        )
        assert approved["status"] == "document_approved"
        published = json.loads(
            world.publish_approved_document(
                "alice", "Release note", 1, audience="Project members"
            )
        )
        assert published["status"] == "document_published"
        assert published["published_version"] == draft["document_version"]
        duplicate = json.loads(
            world.publish_approved_document(
                "alice", "Release note", 1, audience="Project members"
            )
        )
        assert duplicate["status"] == "already_published" and not duplicate["ok"]
        same = json.loads(
            world.create_or_update_draft(
                "alice", "Release note", "Original body", 1
            )
        )
        assert same["status"] == "draft_unchanged" and same["document_version"] == 1
        changed = json.loads(
            world.create_or_update_draft(
                "alice", "Release note", "Changed body", 1
            )
        )
        assert changed["document_version"] == 2 and changed["approval_status"] == "invalidated"
        stale = json.loads(
            world.publish_approved_document(
                "alice", "Release note", 2, audience="Project members"
            )
        )
        assert stale["status"] == "stale_approval" and not stale["ok"]
        assert json.loads(world.get_document_status("bob", "Release note"))["status"] == "not_found"
    finally:
        world.close()
    world = DocumentPublicationWorld(path, True)
    try:
        current = json.loads(world.get_document_status("alice", "Release note"))
        assert current["content"] == "Changed body"
        assert current["document_version"] == 2 and current["publication_status"] == "not_published"
        assert [row["document_version"] for row in current["versions"]] == [1, 2]
        assert current["approvals"][0]["document_version"] == draft["document_version"]
        assert len(current["publications"]) == 1
        assert current["publications"][0]["audience"] == "Project members"
    finally:
        world.close()


def test_publication_no_effect_retains_approval_and_rejects_stale_native_args(
    tmp_path: Path,
) -> None:
    world = DocumentPublicationWorld(tmp_path / "world.sqlite", False)
    try:
        created = json.loads(world.create_or_update_draft("alice", "Notice", "Body"))
        version = created["document_version"]
        assert (
            json.loads(world.approve_document_version("alice", "Notice", 2))["status"]
            == "stale_document_version"
        )
        assert (
            json.loads(world.approve_document_version("alice", "Notice", True))["status"]
            == "stale_document_version"
        )
        assert (
            json.loads(world.publish_approved_document(
                "alice", "Notice", version, audience="Team"))[
                "status"
            ]
            == "approval_required"
        )
        world.approve_document_version("alice", "Notice", version)
        failed = json.loads(world.publish_approved_document(
            "alice", "Notice", version, audience="Team"))
        assert failed["status"] == "publish_service_unavailable"
        assert failed["approval_status"] == "approved" and failed["publications"] == []
        world.set_publication_available("actual-backend-change", True)
        world.set_publication_available("actual-backend-change", True)
        with pytest.raises(ValueError, match="WORLD_EVENT_CHANGED"):
            world.set_publication_available("actual-backend-change", False)
        assert (
            json.loads(world.publish_approved_document(
                "alice", "Notice", version, audience="Team"))[
                "status"
            ]
            == "document_published"
        )
        assert (
            json.loads(world.create_or_update_draft("alice", "Notice", "New body"))["status"]
            == "stale_document_version"
        )
    finally:
        world.close()


class ScriptModel(LangMemRecipeChatModel):
    arm: str
    wire_path: Path
    mixed: bool = False

    def _generate(
        self, messages: list[Any], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self._reserve_request()
        with self.wire_path.open("a") as stream:
            stream.write(json.dumps([m.model_dump(mode="json") for m in messages]) + "\n")
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        current = messages[messages.index(human) + 1 :]
        tools = [m for m in current if isinstance(m, ToolMessage)]
        last = tools[-1] if tools else None
        name, args = "", {}
        if last is None:
            if human.id == "m0":
                name, args = "create_or_update_draft", {"title": TITLE, "content": BODY}
            else:
                name, args = "get_document_status", {"title": TITLE}
        else:
            delivered = json.loads(str(last.content))
            native = delivered.get("receipt", delivered)
            version_args = {
                "title": TITLE,
                "document_version": native.get("document_version"),
            }
            if native.get("status") == "ORIGINAL_CALL_OUTCOME_UNKNOWN":
                name, args = "get_document_status", {"title": TITLE}
            elif last.name == "create_or_update_draft":
                name, args = "approve_document_version", version_args
            elif last.name == "approve_document_version":
                name, args = "publish_approved_document", {**version_args, "audience": AUDIENCE}
            elif last.name == "get_document_status" and native["content"] != BODY:
                name, args = "create_or_update_draft", {**version_args, "content": BODY}
            elif (
                last.name == "get_document_status"
                and native["publication_status"] == "not_published"
                and native["approval_status"] == "approved"
            ):
                name, args = "publish_approved_document", {**version_args, "audience": AUDIENCE}
            elif (
                last.name in {"get_document_status", "publish_approved_document"}
                and self.arm == "field_grounded"
            ):
                fields = {key: native[key] for key in DOCUMENT_FIELDS}
                name, args = (
                    "manage_memory",
                    {
                        "basis": "tool_observation",
                        "kind": "episodic",
                        "content": json.dumps(fields),
                        "content_format": "receipt_json_v1",
                        "fields": fields,
                    },
                )
                if human.id == "m1":
                    args.update(action="update", target_query=TITLE)
        calls = (
            [{"name": name, "args": args, "id": f"{human.id}-{name}-{len(tools)}"}] if name else []
        )
        if name == "publish_approved_document" and self.mixed:
            calls.append(
                {"name": "search_memory", "args": {"query": TITLE}, "id": "unresolved-batch-read"}
            )
        response = AIMessage(
            content="" if calls else "Actual observation delivered.",
            id=f"{human.id}-a{sum(isinstance(m, AIMessage) for m in current)}",
            tool_calls=calls,
        )
        return ChatResult(generations=[ChatGeneration(message=response)])


def scripted_model(
    settings: dict[str, Any], budget: Any, trace: Any, resource: Path
) -> ScriptModel:
    transport = httpx.MockTransport(lambda request: pytest.fail("Unexpected generation HTTP"))
    client = VLLMClient(
        VLLMConfig(**settings["host"]),
        budget=budget,
        emit=trace,
        capacity=HostCapacity(settings["capacity"]),
        transport=transport,
    )
    return ScriptModel(
        client=client,
        capacity_path=resource / "host-capacity.json",
        max_calls_per_message=settings["max_calls_per_message"],
        arm=os.environ["DOCUMENT_TEST_ARM"],
        wire_path=resource / "mechanical-wire.jsonl",
        mixed=os.environ.get("DOCUMENT_TEST_MIXED") == "true",
    )


def child(
    root: Path,
    arm: str,
    index: int,
    phase: str,
    window: str = "none",
    tool: str | None = None,
    available: bool | None = None,
    mixed: bool = False,
    edit: dict[str, str] | None = None,
) -> tuple[Any, dict[str, Any]]:
    attempt = f"m{index}-{phase}-{window}"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(Path(__file__)),
            str(root),
            str(index),
            phase,
            window,
            str(tool),
            attempt,
            str(available),
        ],
        env={
            **os.environ,
            "DOCUMENT_TEST_ARM": arm,
            "DOCUMENT_TEST_MIXED": str(mixed).lower(),
            "DOCUMENT_TEST_EDIT": json.dumps(edit),
        },
        text=True,
        capture_output=True,
        timeout=45,
    )
    path = p5.case_path(root, "mechanical") / f"attempt-{attempt}.json"
    assert path.exists(), result.stderr
    return result, read_json(path)


@pytest.mark.parametrize("available", [True, False])
def test_real_publish_unknown_happened_and_no_effect_independent_discovery(
    tmp_path: Path, available: bool
) -> None:
    root = prepared(tmp_path, available=available)
    ledger = (tmp_path / "budget.json").read_bytes()
    killed, pending = child(root, "field_grounded", 0, "start", "W1", "publish_approved_document")
    assert killed.returncode == -signal.SIGKILL, pending
    assert pending["world"]["documents"][0]["publication_status"] == (
        "published" if available else "not_published"
    )
    assert not any(row["origin"] == "publish_approved_document" for row in pending["sources"])
    assert (tmp_path / "budget.json").read_bytes() == ledger
    resumed, receipt = child(root, "field_grounded", 0, "resume", available=True)
    assert resumed.returncode == 0, receipt
    rows = receipt["action_journal"].values()
    original = next(row for row in rows if row.get("status") == "pending")
    assert original["effect"] == "unknown" and "result" not in original
    assert len(receipt["world"]["documents"][0]["publications"]) == 1
    journal = read_json(p5.case_path(root, "mechanical") / "business-journal.json")
    recovery = journal["_application"]["recoveries"][original["journal_key"]]
    assert recovery["original_call_status"] == "UNKNOWN"
    assert recovery["effect"] == ("confirmed" if available else "none")
    queries = [row for row in receipt["sources"] if row["origin"] == "get_document_status"]
    assert any(row["object_ref"] for row in queries)
    assert all(
        row["object_ref"] is None
        for row in receipt["sources"]
        if '"original_receipt": null' in str(row["content"])
    )
    assert receipt["bank"] and (tmp_path / "budget.json").read_bytes() == ledger
    assert receipt["process_id"] != pending["process_id"]


def test_actual_document_receipt_w2_and_durable_update_w3_replay(tmp_path: Path) -> None:
    root = prepared(tmp_path)
    killed, captured = child(root, "field_grounded", 0, "start", "W2", "manage_memory")
    assert killed.returncode == -signal.SIGKILL and not captured["bank"], captured
    assert any(
        row["origin"] == "publish_approved_document" and row["object_ref"]
        for row in captured["sources"]
    )
    resumed, formed = child(root, "field_grounded", 0, "resume")
    assert resumed.returncode == 0 and formed["bank"], formed
    killed, committed = child(root, "field_grounded", 1, "start", "W3", "manage_memory")
    assert killed.returncode == -signal.SIGKILL, committed
    memory = committed["bank"][0]
    assert memory["value"]["_v13_1"]["revision"] == 2
    assert committed["boundary_witness"]["requested_call"]["args"]["action"] == "update"
    resumed, final = child(root, "field_grounded", 1, "resume")
    assert resumed.returncode == 0, final
    assert final["bank"][0]["value"]["_v13_1"]["revision"] == 2
    assert len(final["world"]["documents"][0]["publications"]) == 1


def test_actual_collaborator_edit_is_discovered_then_authorized_body_restored(
    tmp_path: Path,
) -> None:
    root = prepared(tmp_path)
    first, clean = child(root, "field_grounded", 0, "start")
    assert first.returncode == 0, clean
    second, restored = child(
        root,
        "field_grounded",
        1,
        "start",
        edit={"title": TITLE, "content": "Collaborator changed body"},
    )
    assert second.returncode == 0, restored
    state = restored["world"]["documents"][0]
    assert state["content"] == BODY and state["document_version"] == 3
    assert state["approval_status"] == "approved" and state["published_version"] == 3
    assert [row["document_version"] for row in state["publications"]] == [1, 3]
    sources = restored["sources"]
    actual = next(
        row
        for row in sources
        if row["origin"] == "get_document_status"
        and json.loads(row["content"])["document_version"] == 2
    )
    assert json.loads(actual["content"])["approval_status"] == "invalidated"
    assert json.loads(actual["content"])["content"] == "Collaborator changed body"
    assert all(row["origin"] != "collaborator" for row in sources)
    calls = restored["business_calls"]
    assert [row["name"] for row in calls if row.get("executed")] == [
        "get_document_status",
        "create_or_update_draft",
        "approve_document_version",
        "publish_approved_document",
    ]
    initial_create = next(
        row for row in clean["business_calls"] if row["name"] == "create_or_update_draft"
    )
    assert initial_create["args"] == {"title": TITLE, "content": BODY}


def test_actual_two_connection_stale_edit_cannot_overwrite_current_version(tmp_path: Path) -> None:
    path = tmp_path / "world.sqlite"
    first, second = DocumentPublicationWorld(path), DocumentPublicationWorld(path)
    try:
        created = json.loads(first.create_or_update_draft("alice", TITLE, BODY))
        second.approve_document_version("alice", TITLE, created["document_version"])
        changed = json.loads(
            first.create_or_update_draft("alice", TITLE, "New draft", 1)
        )
        refused = json.loads(
            second.create_or_update_draft(
                "alice", TITLE, "Stale overwrite", 1
            )
        )
        assert not refused["ok"] and refused["status"] == "stale_document_version"
        actual = json.loads(second.get_document_status("alice", TITLE))
        assert (
            actual["content"] == "New draft"
            and actual["document_version"] == changed["document_version"]
        )
        assert actual["approval_status"] == "invalidated"
        assert [row["document_version"] for row in actual["versions"]] == [1, 2]
    finally:
        second.close()
        first.close()


def test_document_prepare_freezes_equal_finite_quality_cap_and_public_schema_zero_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = prepared(tmp_path)
    config = read_json(tmp_path / "config.json")
    config.update(
        generation_cap_profile="lifecycle_quality_24_v1",
        max_calls_per_message=24,
        embedding_dimension=1024,
    )
    write_json(tmp_path / "quality.json", config)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("PREPARE_MUST_NOT_CONSTRUCT_PROVIDER_OR_NATIVE_RUNTIME")

    monkeypatch.setattr(compare, "VLLMClient", forbidden)
    monkeypatch.setattr(compare, "Mem0NativeRuntime", forbidden)
    # DTO/freezing only; actual installed native methods have their own SDK test.
    monkeypatch.setattr(compare, "mem0_dependency_identity", lambda: {"test_metadata": True})
    from milai_lab.application.document_publication import DOCUMENT_NAMES

    for arm in compare.ARMS:
        frozen = compare.prepare(
            tmp_path / "public.json", tmp_path / "quality.json", tmp_path / ("quality-" + arm), arm
        )
        assert frozen["effective_generation_cap"] == 24
        assert frozen["comparison_parameters"]["effective_generation_cap"] == 24
        assert frozen["generation_cap_profile"] == "lifecycle_quality_24_v1"
        assert frozen["receipt_profile"] == "document_publication_v1"
        business = [
            row for row in frozen["tool_catalog"] if row["function"]["name"] in DOCUMENT_NAMES
        ]
        assert [row["function"]["name"] for row in business] == list(DOCUMENT_NAMES)
        for row in business:
            assert "user_id" not in row["function"]["parameters"]["properties"]
    original = compare._frozen(root)
    assert "generation_cap_profile" not in original
    assert "effective_generation_cap" not in original
    for invalid in (None, True, "unknown"):
        with pytest.raises(ValueError, match="WORKFLOW_INVALID"):
            p5.application_workflow({"application_workflow": invalid})


@pytest.mark.parametrize("arm", ["B2", "B6"])
def test_document_matched_original_index_w2_actual_update_w3_and_projection(
    tmp_path: Path, arm: str
) -> None:
    root = prepared(tmp_path, arm)
    killed, captured = child(root, arm, 0, "start", "W2", "memory_formation")
    assert killed.returncode == -signal.SIGKILL, captured
    assert not captured["comparison"]["backend"]["archive"]
    resumed, formed = child(root, arm, 0, "resume")
    assert resumed.returncode == 0, formed
    killed, committed = child(root, arm, 1, "start", "W3", "memory_formation")
    assert killed.returncode == -signal.SIGKILL, committed
    assert committed["boundary_witness"]["receipt"]["operation"] == "UPDATE"
    resumed, final = child(root, arm, 1, "resume")
    assert resumed.returncode == 0, final
    archive = final["comparison"]["backend"]["archive"]
    assert all(row["role"] in {"user", "tool"} for row in archive)
    if arm == "B6":
        projected = final["comparison"]["backend"]["projection"]["documents"]
        document = next(iter(projected.values()))
        assert document["latest_observation"]["fields"]["document_version"] == 1
        assert document["latest_observation"]["fields"]["publication_status"] == "published"


def test_document_mixed_pending_batch_is_unresolved_not_blind_retried(tmp_path: Path) -> None:
    root = prepared(tmp_path)
    killed, pending = child(
        root, "field_grounded", 0, "start", "W1", "publish_approved_document", mixed=True
    )
    assert killed.returncode == -signal.SIGKILL, pending
    resumed, final = child(root, "field_grounded", 0, "resume", mixed=True)
    assert resumed.returncode != 0 and final["status"] == "interrupted"
    assert "OTHER_CALL_UNRESOLVED" in final["error"]
    assert len(final["world"]["documents"][0]["publications"]) == 1


if __name__ == "__main__":
    root, index, phase, window, tool, attempt, available = sys.argv[1:]
    p5.make_model = scripted_model
    original_client = compare.VLLMClient

    def mock_embedding(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": [1.0, 0.0]} for i in range(len(wire["input"]))],
                "usage": {"total_tokens": 4},
            },
        )

    def embedding_client(*args: Any, **kwargs: Any) -> VLLMClient:
        return original_client(*args, **kwargs, transport=httpx.MockTransport(mock_embedding))

    compare.VLLMClient = embedding_client
    edit = json.loads(os.environ.get("DOCUMENT_TEST_EDIT", "null"))
    result = compare.step(
        Path(root),
        "mechanical",
        int(index),
        phase=phase,
        window=window,
        window_tool=None if tool == "None" else tool,
        attempt_id=attempt,
        publication_available=None if available == "None" else available == "True",
        document_edit=edit,
        world_event_id="actual-collaborator-edit"
        if edit is not None
        else None
        if available == "None"
        else "actual-publication-availability",
    )
    print(json.dumps({"status": result["status"], "error": result.get("error")}))
    sys.exit(0 if result["status"] == "completed" else 1)
