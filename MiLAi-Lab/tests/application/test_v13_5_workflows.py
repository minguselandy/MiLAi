"""Local workflow and true process interruption checks, with no model HTTP."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.functional import FunctionalApplication
from milai_lab.application.journal import UnknownBusinessAction
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.service import MemoryService


def opened(stack: ExitStack, root: Path, workflow: str, **kwargs: Any) -> tuple[Any, Any, Any]:
    app = stack.enter_context(FunctionalApplication.open(root, workflow, "alice", **kwargs))
    store = stack.enter_context(SqliteStore.from_conn_string(str(root / "memory.sqlite")))
    service = MemoryService(store, ("functional-test", "alice"), "alice", root / "memory.lock",
                            functional_contract="functional_v1", receipt_profile=app.workflow)
    service.capture_user("session", "message", "Operate the local test object.")
    wrapper = app.call_wrapper(service, "session", "message")
    return app, service, wrapper


def config() -> dict[str, Any]:
    return FoundationScope("run", "arm", "alice", "session").config()


def call(wrapper: Any, name: str, args: dict[str, Any], call_id: str) -> Any:
    tool_call = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
    request = SimpleNamespace(tool_call=tool_call, runtime=SimpleNamespace(config=config()),
                              state={"messages": [HumanMessage(content="Operate"),
                                     AIMessage(content="", id="g-" + call_id,
                                               tool_calls=[tool_call])]})
    tool = next(tool for tool in wrapper.app.tools if tool.name == name)
    return wrapper(request, lambda item: tool.invoke(item.tool_call))


def reserve_args() -> dict[str, Any]:
    return {"item_key": "mechanical item", "quantity": 1, "destination": "local", "packing": "box"}


def draft_args() -> dict[str, Any]:
    return {"title": "mechanical draft", "content": "Original content",
            "document_version": 0, "content_digest": ""}


def receipt(message: Any) -> dict[str, Any]:
    return json.loads(message.content)["receipt"]


def test_native_reservation_partial_no_effect_remaining_step_and_stale_source(
    tmp_path: Path,
) -> None:
    with ExitStack() as stack:
        app, service, wrapper = opened(
            stack, tmp_path, "reservation", initial_label_available=False
        )
        first = call(wrapper, "reserve_and_label", reserve_args(), "reserve")
        original = receipt(first)
        assert original["status"] == "reserved_label_failed"
        assert json.loads(first.content)["business_outcome"] == "partial"
        assert json.loads(first.content)["semantic_maintenance"] == {"status": "not_requested"}
        no_effect = receipt(call(wrapper, "complete_label",
                                 {"reservation_id": original["reservation_id"]}, "unavailable"))
        assert no_effect["status"] == "label_service_unavailable"
        app.world.set_label_available("actual-backend-up", True)
        assert receipt(call(wrapper, "complete_label",
                            {"reservation_id": original["reservation_id"]}, "label"))["ok"]
        # Replay never turns old partial into a current successful observation.
        assert call(wrapper, "reserve_and_label", reserve_args(), "reserve") == first
        old_source = service.source(json.loads(first.content)["source_ref"])
        assert json.loads(old_source["content"])["label_status"] == "not_created"
        assert old_source["object_ref"]["fields"]["label_status"] == "not_created"
        assert [r["operation"] for r in app.world.snapshot()["attempts"]] == [
            "reserve_and_label", "complete_label"]
        denied = json.loads(call(wrapper, "reserve_and_label", reserve_args(), "new-call").content)
        assert denied == {"status": "operation_already_completed", "executed": False}


@pytest.mark.parametrize("workflow", ["reservation", "document"])
def test_single_phase_policy_retains_failed_attempt_and_requires_new_public_turn(
    tmp_path: Path, workflow: str,
) -> None:
    options = {"attempt_policy": "single_phase_per_public_turn_v1",
               "initial_label_available" if workflow == "reservation"
               else "initial_publication_available": False}
    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, workflow, **options)
        if workflow == "reservation":
            first = call(wrapper, "reserve_and_label", reserve_args(), "reserve")
            original = receipt(first)
            name, args = "complete_label", {"reservation_id": original["reservation_id"]}
            # Another exact object has its own phase allowance.
            other = call(wrapper, "reserve_and_label",
                         {**reserve_args(), "item_key": "another item"}, "another")
            assert receipt(other)["status"] == "reserved_label_failed"
        else:
            draft = receipt(call(wrapper, "create_or_update_draft", draft_args(), "draft"))
            bound = {k: draft[k] for k in ("title", "document_version", "content_digest")}
            assert receipt(call(wrapper, "approve_document_version", bound, "approve"))["ok"]
            name, args = "publish_approved_document", {**bound, "audience": "local audience"}
            first = call(wrapper, name, args, "publish")
        denied = call(wrapper, name, args, "repeat")
        assert json.loads(denied.content) == {
            "status": "business_phase_already_attempted_this_turn", "executed": False}
        source = service.source(json.loads(first.content)["source_ref"])
        policy = receipt(first)["request_attempt_policy"]
        assert policy["scope"] == "current_public_message_only"
        assert policy["closed_phases"] == (["label", "reservation"]
            if workflow == "reservation" else ["publish_approved_document"])
        assert policy["further_attempts_in_this_message"] is False
        assert json.loads(source["content"])["request_attempt_policy"] == policy
        entries = app.snapshot()["journal"].values()
        saved = next(r for r in entries if r.get("call_id") == first.tool_call_id)
        assert "request_attempt_policy" not in json.loads(saved["native_result"]["content"])

    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, workflow, **options)
        # Reopen cannot refund the known failed phase.
        assert json.loads(call(wrapper, name, args, "after-reopen").content)["executed"] is False
        service.capture_user("session", "continue", "Query then try the remaining step once.")
        wrapper = app.call_wrapper(service, "session", "continue")
        query_name = "get_reservation" if workflow == "reservation" else "get_document_status"
        query_args = {"item_key": "mechanical item"} if workflow == "reservation" else {
            "title": "mechanical draft"}
        assert receipt(call(wrapper, query_name, query_args, "live-query"))["ok"]
        failed = call(wrapper, name, args, "new-turn-attempt")
        assert receipt(failed)["ok"] is False
        if workflow == "reservation":
            app.world.set_label_available("backend-up", True)
        else:
            app.world.set_publication_available("backend-up", True)
        assert json.loads(call(wrapper, name, args, "same-turn-again").content)["executed"] is False
        service.capture_user("session", "continue-again", "Try the remaining step now.")
        wrapper = app.call_wrapper(service, "session", "continue-again")
        assert receipt(call(wrapper, name, args, "final-attempt"))["ok"]
        assert service.source(json.loads(first.content)["source_ref"]) == source


def test_native_document_version_approval_publish_and_stale_observation(tmp_path: Path) -> None:
    with ExitStack() as stack:
        app, service, wrapper = opened(
            stack, tmp_path, "document", initial_publication_available=False
        )
        draft = receipt(call(wrapper, "create_or_update_draft", draft_args(), "create"))
        bound = {k: draft[k] for k in ("title", "document_version", "content_digest")}
        approval = call(wrapper, "approve_document_version", bound, "approve")
        assert receipt(approval)["approval_status"] == "approved"
        pubargs = {**bound, "audience": "local audience"}
        assert receipt(call(wrapper, "publish_approved_document", pubargs, "unavailable"))[
            "status"] == "publish_service_unavailable"
        app.world.set_publication_available("actual-backend-up", True)
        assert receipt(call(wrapper, "publish_approved_document", pubargs, "publish"))[
            "publication_status"] == "published"
        edit = receipt(call(wrapper, "create_or_update_draft",
                            {**bound, "content": "Revised content"}, "edit"))
        assert edit["document_version"] == 2 and edit["approval_status"] == "invalidated"
        # Same-message completed operation is safely blocked before another execution.
        stale = json.loads(call(wrapper, "publish_approved_document", pubargs, "stale").content)
        assert stale["executed"] is False
        assert json.loads(app.world.publish_approved_document("alice", **pubargs))[
            "status"] == "stale_document_version"
        old_source = service.source(json.loads(approval.content)["source_ref"])
        assert json.loads(old_source["content"])["approval_status"] == "approved"
        assert len(app.world.snapshot()["documents"][0]["publications"]) == 1


@pytest.mark.parametrize("happened", [False, True])
@pytest.mark.parametrize("workflow", ["reservation", "document"])
def test_unknown_blocks_changed_call_id_until_public_discovery(
    tmp_path: Path, happened: bool, workflow: str,
) -> None:
    def lost(row: Any, response: Any) -> None:
        raise RuntimeError("lost native response")

    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, workflow,
                                       response_hook=lost if happened else None)
        name = "reserve_and_label" if workflow == "reservation" else "create_or_update_draft"
        args = reserve_args() if workflow == "reservation" else draft_args()
        if happened:
            with pytest.raises(RuntimeError, match="lost native response"):
                call(wrapper, name, args, "original")
        else:
            tool_call = {"name": name, "args": args, "id": "original", "type": "tool_call"}
            request = SimpleNamespace(tool_call=tool_call, runtime=SimpleNamespace(config=config()),
                                      state={"messages": [AIMessage(content="", id="g-original",
                                                                    tool_calls=[tool_call])]})
            with pytest.raises(RuntimeError, match="lost native response"):
                wrapper(request, lambda request: lost(None, None))
        app.journal.response_hook = None
        with pytest.raises(UnknownBusinessAction):
            call(wrapper, name, args, "original")
        assert json.loads(call(wrapper, name, args, "changed-id").content) == {
            "status": "outcome_unknown_query_required", "executed": False}
        assert len(service.sources()) == 1  # no invented original execution receipt
        query = "get_reservation" if workflow == "reservation" else "get_document_status"
        field = "item_key" if workflow == "reservation" else "title"
        call(wrapper, query, {field: args[field]}, "discover")
        original = app.journal.entry_for_call(config()["configurable"]["thread_id"],
                                              "g-original", "original")
        assert original["status"] == "pending" and "result" not in original
        recovery = app.journal.recovery_for_call(original["journal_key"])
        assert recovery["effect"] == ("confirmed" if happened else "none")
        # Kill-equivalent marker loss after the query receipt persisted. Replaying
        # that same query call reconstructs recovery from its original receipt.
        rows = app.journal._entries()
        rows.pop("_native_recoveries")
        write_json(app.journal.path, rows)
        call(wrapper, query, {field: args[field]}, "discover")
        assert app.journal.recovery_for_call(original["journal_key"]) == recovery
        assert len(service.sources()) == 2
        if happened:
            assert json.loads(call(wrapper, name, args, "retry").content)["status"] == (
                "operation_effect_already_observed")
        else:
            assert receipt(call(wrapper, name, args, "retry"))["ok"]


def worker(root: Path, workflow: str, window: str, phase: str) -> None:
    """Real SIGKILL leaves actual SDK/checkpoint/world files for another process."""
    with ExitStack() as stack:
        def crash(boundary: str, actual: dict[str, Any]) -> None:
            if phase == "start" and boundary == window.split("-")[0]:
                write_json(root / "witness.json", {"window": window, "pid": os.getpid(),
                                                   "actual": actual})
                os.kill(os.getpid(), signal.SIGKILL)

        app, service, wrapper = opened(stack, root, workflow,
            response_hook=lambda row, response: crash("W1", {"journal_key": row["journal_key"]}))
        wrapper.boundary_hook = crash
        saver = stack.enter_context(SqliteSaver.from_conn_string(str(root / "checkpoint.sqlite")))
        cfg = config()
        cfg["configurable"].update(v13_session="session", v13_turn_id="message",
                                    v13_support_config_sha256="a" * 64)
        memory = FunctionalMemory(service, len)
        memory.context("session", "message", "a" * 64)

        def execute_boundary(request: Any, execute: Any) -> Any:
            def native(item: Any) -> Any:
                if phase == "start" and window == "W1-empty":
                    crash("W1", {"stage": "after_intent_before_native"})
                return execute(item)
            return wrapper(request, native)

        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode([*app.tools, *memory.tools()],
                                         wrap_tool_call=execute_boundary))
        graph.set_entry_point("tools")
        graph.set_finish_point("tools")
        agent = graph.compile(checkpointer=saver)
        if phase == "start":
            name = "reserve_and_label" if workflow == "reservation" else "create_or_update_draft"
            args = reserve_args() if workflow == "reservation" else draft_args()
            if window.endswith("-memory"):
                name = "save_memory"
                fragments = service.source_fragments(service.event_id("session", "message", "user"))
                args = {"content": "Operate the local test object.", "fragment_handles": [
                    row["fragment_handle"] for row in fragments]}
            tool_call = {"name": name, "args": args, "id": "original", "type": "tool_call"}
            agent.invoke({"messages": [HumanMessage(content="Operate", id="message"),
                                        AIMessage(content="", id="generation",
                                                  tool_calls=[tool_call])]},
                         cfg, durability="sync")
        else:
            scope = FoundationScope("run", "arm", "alice", "session")
            app.recover_pending(agent, scope, wrapper)
            if agent.get_state(config()).next:
                agent.invoke(None, cfg, durability="sync")
        write_json(root / "result.json", {"pid": os.getpid(), "application": app.snapshot(),
                                          "sources": service.sources(),
                                          "observations": service.observations(),
                                          "records": service.records(),
                                          "history": [service.history_index(row["id"])
                                                      for row in service.records()],
                                          "checkpoint_next": list(agent.get_state(config()).next)})


@pytest.mark.parametrize("workflow", ["reservation", "document"])
@pytest.mark.parametrize("window", ["W1", "W1-empty", "W2", "W3"])
def test_actual_sigkill_new_process_recovery(tmp_path: Path, workflow: str, window: str) -> None:
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               str(tmp_path), workflow, window]
    start = subprocess.run([*command, "start"], capture_output=True, text=True, timeout=30)  # noqa: S603
    assert start.returncode == -signal.SIGKILL, start.stdout + start.stderr
    resume = subprocess.run([*command, "resume"], capture_output=True, text=True, timeout=30)  # noqa: S603
    assert resume.returncode == 0, resume.stdout + resume.stderr
    actual, witness = read_json(tmp_path / "result.json"), read_json(tmp_path / "witness.json")
    assert actual["pid"] != witness["pid"] and actual["checkpoint_next"] == []
    world = actual["application"]["world"]
    if workflow == "reservation":
        assert len(world["reservations"]) == len(world["attempts"]) == int(window != "W1-empty")
    else:
        assert len(world["documents"]) == int(window != "W1-empty")
        if world["documents"]:
            assert len(world["documents"][0]["versions"]) == 1
    assert len(actual["sources"]) == 2
    assert not actual["observations"]["pending"]
    if window.startswith("W1"):
        rows = actual["application"]["journal"]
        original = next(r for r in rows.values() if r.get("call_id") == "original")
        assert original["status"] == "pending" and "result" not in original


def test_semantic_commit_w3_reopens_without_duplicate_revision(tmp_path: Path) -> None:
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               str(tmp_path), "reservation", "W3-memory"]
    start = subprocess.run([*command, "start"], capture_output=True, text=True, timeout=30)  # noqa: S603
    assert start.returncode == -signal.SIGKILL, start.stdout + start.stderr
    resume = subprocess.run([*command, "resume"], capture_output=True, text=True, timeout=30)  # noqa: S603
    assert resume.returncode == 0, resume.stdout + resume.stderr
    actual = read_json(tmp_path / "result.json")
    assert len(actual["records"]) == 1
    assert actual["records"][0]["value"]["revision"] == 1
    assert actual["history"][0]["revision_count"] == 1
    assert actual["application"]["world"]["attempts"] == []


def test_owner_identity_and_cooperative_lock_are_enforced(tmp_path: Path) -> None:
    with FunctionalApplication.open(tmp_path, "reservation", "alice"):
        with pytest.raises(BlockingIOError):
            FunctionalApplication.open(tmp_path, "reservation", "alice")
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        FunctionalApplication.open(tmp_path, "reservation", "bob")


def test_lost_public_query_response_never_blocks_a_later_native_mutation(tmp_path: Path) -> None:
    def lost(row: Any, response: Any) -> None:
        raise RuntimeError("query response lost")

    with ExitStack() as stack:
        app, _, wrapper = opened(stack, tmp_path, "reservation", response_hook=lost)
        with pytest.raises(RuntimeError, match="query response lost"):
            call(wrapper, "get_reservation", {"item_key": "mechanical item"}, "lost-read")
        app.journal.response_hook = None
        with pytest.raises(UnknownBusinessAction):
            call(wrapper, "get_reservation", {"item_key": "mechanical item"}, "lost-read")
        assert receipt(call(wrapper, "reserve_and_label", reserve_args(), "reserve"))["ok"]
        refreshed = receipt(call(
            wrapper, "get_reservation", {"item_key": "mechanical item"}, "read"
        ))
        assert refreshed["status"] == "found"
        original = app.journal.entry_for_call(config()["configurable"]["thread_id"],
                                              "g-lost-read", "lost-read")
        assert original["status"] == "pending" and "result" not in original
        assert original["effect"] == "none"
        recovery = app.journal.recovery_for_call(original["journal_key"])
        assert recovery["effect"] == "none"
        assert recovery["effect_source"] == "native_public_read_contract_no_business_mutation"
        assert len(app.world.snapshot()["attempts"]) == 1


def test_revoked_current_input_binding_requires_exact_runtime_identity(tmp_path: Path) -> None:
    with ExitStack() as stack:
        app, service, _ = opened(stack, tmp_path, "reservation")
        memory = FunctionalMemory(service, len)
        memory.context("session", "message", "a" * 64)
        ref = service.event_id("session", "message", "user")
        handles = [row["fragment_handle"] for row in service.source_fragments(ref)]
        assert service.forget("session", "forget-source", fragment_handles=handles)["ok"]
        assert service.source(ref) is None
        cfg = config()
        cfg["configurable"].update(v13_session="session", v13_turn_id="message",
                                    v13_support_config_sha256="a" * 64)
        with pytest.raises(ValueError, match="ACTUAL_PUBLIC_SOURCE_REQUIRED"):
            app.call_wrapper(service, "session", "message")
        for changed in ({"v13_session": "other"}, {"v13_turn_id": "other"},
                        {"v13_support_config_sha256": ""}):
            invalid = {**cfg, "configurable": {**cfg["configurable"], **changed}}
            with pytest.raises(ValueError, match="PUBLIC_TURN_CONFIGURATION_INVALID"):
                app.call_wrapper(service, "session", "message", runtime_config=invalid)
        invalid = {**cfg, "configurable": {**cfg["configurable"],
                                           "v13_support_config_sha256": "b" * 64}}
        with pytest.raises(ValueError, match="ACTUAL_PUBLIC_SOURCE_REQUIRED"):
            app.call_wrapper(service, "session", "message", runtime_config=invalid)
        assert app.call_wrapper(service, "session", "message", runtime_config=cfg)
        assert service.source(ref) is None
        with pytest.raises(ValueError, match="SOURCE_UNAVAILABLE"):
            service.source_fragments(ref)


def test_lost_recovery_query_reopens_with_fresh_public_identity(tmp_path: Path) -> None:
    def graph_for(app: Any, wrapper: Any, saver: Any) -> Any:
        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode(app.tools, wrap_tool_call=wrapper))
        graph.set_entry_point("tools")
        graph.set_finish_point("tools")
        return graph.compile(checkpointer=saver)

    def lost(row: Any, response: Any) -> None:
        raise RuntimeError("mechanical native response lost")

    scope = FoundationScope("run", "arm", "alice", "session")
    with ExitStack() as stack:
        app, _, wrapper = opened(stack, tmp_path, "reservation", response_hook=lost)
        saver = stack.enter_context(SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.db")))
        agent = graph_for(app, wrapper, saver)
        native = {"name": "reserve_and_label", "args": reserve_args(),
                  "id": "original", "type": "tool_call"}
        with pytest.raises(RuntimeError, match="native response lost"):
            agent.invoke({"messages": [HumanMessage(content="Operate", id="message"),
                         AIMessage(content="", id="generation", tool_calls=[native])]},
                         config(), durability="sync")
        with pytest.raises(RuntimeError, match="native response lost"):
            app.recover_pending(agent, scope, wrapper)
        pending = app.journal._entries()
        assert {row["name"] for row in pending.values()} == {
            "reserve_and_label", "get_reservation"}
        assert all(row["status"] == "pending" and "result" not in row
                   for row in pending.values())

    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, "reservation")
        saver = stack.enter_context(SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.db")))
        agent = graph_for(app, wrapper, saver)
        FunctionalMemory(service, len).context("session", "message", "a" * 64)
        app.recover_pending(agent, scope, wrapper)
        state = agent.get_state(config())
        assert not state.next
        delivered = json.loads(state.values["messages"][-1].content)
        assert delivered["status"] == "ORIGINAL_CALL_OUTCOME_UNKNOWN"
        assert delivered["original_receipt"] is None
        assert delivered["query_receipt"]["status"] == "found"
        assert delivered["observed_effect"] == "confirmed"
        assert delivered["query_source"]["source_fragment_index"]
        rows = app.journal._entries()
        assert all(rows[key] == original for key, original in pending.items())
        queries = [row for row in rows.values() if row.get("name") == "get_reservation"]
        assert sorted(row["status"] for row in queries) == ["complete", "pending"]
        assert len(service.sources()) == 2
        assert len(app.world.snapshot()["reservations"]) == 1
        assert len(app.world.snapshot()["attempts"]) == 1
        copied = service.capture_assistant("session", "message:final",
                                           json.dumps(delivered["query_receipt"]))["source_ref"]
        service.capture_user("session", "forget", "Forget the discovered receipt.")
        FunctionalMemory(service, len).context("session", "forget", "a" * 64)
        forgotten = service.forget("session", "forget-query", fragment_handles=[
            row["fragment_handle"] for row in delivered["query_source"]["source_fragment_index"]])
        assert copied in forgotten["revoked_source_refs"]
        assert service.source(service.event_id("session", "message", "user")) is not None


@pytest.mark.parametrize("delivered", [False, True])
def test_only_delivered_tool_source_becomes_an_assistant_dependency(
    tmp_path: Path, delivered: bool,
) -> None:
    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, "reservation")
        FunctionalMemory(service, len).context("session", "message", "a" * 64)
        if not delivered:
            def interrupt(window: str, event: Any) -> None:
                if window == "W2":
                    raise RuntimeError("captured but not delivered")
            wrapper.boundary_hook = interrupt
            with pytest.raises(RuntimeError, match="not delivered"):
                call(wrapper, "reserve_and_label", reserve_args(), "reserve")
        else:
            assert receipt(call(wrapper, "reserve_and_label", reserve_args(), "reserve"))["ok"]
        actual_tool = next(row for row in service.sources() if row["role"] == "tool")
        copied = service.capture_assistant("session", "message:final",
            actual_tool["content"] if delivered else "No tool result was received.")["source_ref"]
        handles = [row["fragment_handle"]
                   for row in service.source_fragments(actual_tool["event_id"])]
        service.capture_user("session", "forget", "Forget the captured receipt.")
        FunctionalMemory(service, len).context("session", "forget", "a" * 64)
        forgotten = service.forget("session", "forget-tool", fragment_handles=handles)
        assert (copied in forgotten["revoked_source_refs"]) is delivered
        assert (service.source(copied) is None) is delivered
        assert service.source(service.event_id("session", "message", "user")) is not None
        assert len(app.world.snapshot()["reservations"]) == 1


if __name__ == "__main__" and sys.argv[1] == "--worker":
    worker(Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])


@pytest.mark.parametrize('workflow', ['reservation', 'document'])
def test_live_query_includes_bounded_owner_object_original_attempt_receipts(
    tmp_path: Path, workflow: str,
) -> None:
    options = {'attempt_policy': 'single_phase_with_history_v2',
               'initial_label_available' if workflow == 'reservation'
               else 'initial_publication_available': False}
    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, workflow, **options)
        if workflow == 'reservation':
            first = receipt(call(wrapper, 'reserve_and_label', reserve_args(), 'reserve'))
            name, args = 'complete_label', {'reservation_id': first['reservation_id']}
            query, query_args = 'get_reservation', {'item_key': reserve_args()['item_key']}
            expected = 'label_service_unavailable'
            call(wrapper, 'reserve_and_label', {**reserve_args(), 'item_key': 'unrelated'}, 'other')
        else:
            first = receipt(call(wrapper, 'create_or_update_draft', draft_args(), 'draft'))
            bound = {k: first[k] for k in ['title', 'document_version', 'content_digest']}
            call(wrapper, 'approve_document_version', bound, 'approve')
            name, args = 'publish_approved_document', {**bound, 'audience': 'local'}
            query, query_args = 'get_document_status', {'title': first['title']}
            expected = 'publish_service_unavailable'
        for index in range(18):
            turn = 'attempt-turn-' + str(index)
            service.capture_user('session', turn, 'Query then try the remaining action once.')
            wrapper = app.call_wrapper(service, 'session', turn)
            assert receipt(call(wrapper, name, args, 'attempt-' + str(index)))['status'] == expected
        service.capture_user('session', 'history', 'Show current and prior attempt state.')
        wrapper = app.call_wrapper(service, 'session', 'history')
        queried = call(wrapper, query, query_args, 'history-query')
        history = receipt(queried)['operation_history']
        assert len(history['items']) == 16
        assert history['omitted_earlier_count'] == (3 if workflow == 'reservation' else 4)
        assert all(r['operation'] == name and r['effect'] == 'none'
                   and r['result_status'] == expected and not r['same_public_message']
                   for r in history['items'])
        assert 'unrelated' not in json.dumps(history)
        assert not any('args' in r or 'content' in r for r in history['items'])
        source = service.source(json.loads(queried.content)['source_ref'])
        assert json.loads(source['content'])['operation_history'] == history
    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, workflow, **options)
        service.capture_user('session', 'after-open', 'Show current state.')
        wrapper = app.call_wrapper(service, 'session', 'after-open')
        again = receipt(call(wrapper, query, query_args, 'query-after-open'))
        assert again['operation_history'] == history


def test_query_attempt_history_preserves_unknown_and_filters_foreign_owner(tmp_path: Path) -> None:
    def lost(row: dict[str, Any], response: Any) -> None:
        if row['name'] == 'reserve_and_label':
            raise OSError('response lost after native effect')

    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, 'reservation',
            attempt_policy='single_phase_with_history_v2', response_hook=lost)
        with pytest.raises(OSError):
            call(wrapper, 'reserve_and_label', reserve_args(), 'unknown')
        rows = read_json(app.journal.path)
        original = next(r for r in rows.values() if r.get('call_id') == 'unknown')
        rows['foreign'] = {**original, 'owner': 'bob', 'status': 'complete',
                           'result': {'content': json.dumps({'status': 'FOREIGN_PRIVATE_RESULT'})}}
        write_json(app.journal.path, rows)
        service.capture_user('session', 'discover', 'Query actual state first.')
        wrapper = app.call_wrapper(service, 'session', 'discover')
        current = receipt(call(wrapper, 'get_reservation',
            {'item_key': reserve_args()['item_key']}, 'discovery'))
        assert current['label_status'] == 'created'
        history = current['operation_history']
        assert len(history['items']) == 1
        assert history['items'][0]['effect'] == 'unknown'
        assert history['items'][0]['receipt_status'] == 'pending'
        assert 'result_status' not in history['items'][0]
        assert 'FOREIGN_PRIVATE_RESULT' not in json.dumps(current)
        original_after = read_json(app.journal.path)[original['journal_key']]
        assert original_after['status'] == 'pending' and original_after['effect'] == 'unknown'


@pytest.mark.parametrize('available', [False, True])
def test_publication_receipt_binds_attempted_audience_without_claiming_delivery(
    tmp_path: Path, available: bool,
) -> None:
    with ExitStack() as stack:
        app, service, wrapper = opened(stack, tmp_path, 'document',
            attempt_policy='single_phase_with_history_v2', initial_publication_available=available)
        draft = receipt(call(wrapper, 'create_or_update_draft', draft_args(), 'draft'))
        bound = {k: draft[k] for k in ['title', 'document_version', 'content_digest']}
        call(wrapper, 'approve_document_version', bound, 'approve')
        published = call(wrapper, 'publish_approved_document',
                         {**bound, 'audience': 'local team'}, 'pub')
        body = receipt(published)
        assert body['attempted_audience'] == 'local team'
        assert body['audience'] == ('local team' if available else '')
        assert body['publication_status'] == ('published' if available else 'not_published')
        source = service.source(json.loads(published.content)['source_ref'])
        assert json.loads(source['content']) == body
        entry = next(r for r in app.snapshot()['journal'].values() if r.get('call_id') == 'pub')
        original = json.loads(entry['native_result']['content'])
        assert 'attempted_audience' not in original and 'request_attempt_policy' not in original
