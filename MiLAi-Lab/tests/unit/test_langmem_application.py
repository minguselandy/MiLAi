"""Small zero-model checks for the durable application workload."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

pytest.importorskip("langmem")

from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.base import Item, PutOp
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.methods.freshness_projection.identity import LAB
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel as VLLMChatModel
from milai_lab.methods.local_state_attention.controller import CONTROL_STAGE
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import langmem_application as app
from milai_lab.runners import langmem_application_runtime as app_runtime


class _R2DurableTestStore(InMemoryStore):
    """Test-only SQLite persistence for real Host memory writes across processes."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS records "
                          "(namespace TEXT, key TEXT, value TEXT, "
                          "created_at TEXT, updated_at TEXT, "
                          "PRIMARY KEY(namespace,key))")
        self.conn.execute("CREATE TABLE IF NOT EXISTS writes (id INTEGER PRIMARY KEY)")
        for namespace, key, value, created, updated in self.conn.execute("SELECT * FROM records"):
            ns = tuple(json.loads(namespace))
            self._data[ns][key] = Item(value=json.loads(value), key=key, namespace=ns,
                                       created_at=datetime.fromisoformat(created),
                                       updated_at=datetime.fromisoformat(updated))

    def batch(self, ops: Any) -> Any:
        operations = list(ops)
        result = super().batch(operations)
        with self.conn:
            for op in operations:
                if isinstance(op, PutOp):
                    namespace = json.dumps(op.namespace)
                    if op.value is None:
                        self.conn.execute("DELETE FROM records WHERE namespace=? AND key=?",
                                          (namespace, op.key))
                    else:
                        item = self._data[op.namespace][op.key]
                        self.conn.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)",
                                          (namespace, op.key, json.dumps(op.value),
                                           item.created_at.isoformat(),
                                           item.updated_at.isoformat()))
                    self.conn.execute("INSERT INTO writes DEFAULT VALUES")
        return result

    async def abatch(self, ops: Any) -> Any:
        return self.batch(ops)


def _r2_test_binding(scope: Any, message: dict[str, Any], task: str,
                     operations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"run_id": scope.run_id, "arm_id": scope.arm_id, "owner": scope.user_id,
            "thread_id": scope.config()["configurable"]["thread_id"],
            "public_index": message["public_index"], "message_id": message["message_id"],
            "task_id": task, "operations": operations,
            "recovery": {"absence_means_no_effect": True, "no_deletion": True,
                         "exclusive_writer": True}}


def _r2_subprocess_driver(root_text: str, case: str, stage_text: str) -> None:
    """Mechanical deterministic HTTP Host; this driver never contacts model services."""
    from milai_lab.baselines.langmem_agent import FoundationScope
    from milai_lab.harness.contextual_artifacts import read_json, write_json

    root, stage = Path(root_text), int(stage_text)
    target = {"item_key": "Mechanical parcel", "quantity": 2,
              "destination": "east desk", "packing": "paper sleeves"}
    reserve = {"operation_id": "reserve", "tool": "reserve_and_label", "args": target,
               "target": target, "retry": "never"}
    query = {"operation_id": "query", "tool": "get_reservation",
             "args": {"item_key": target["item_key"]}, "target": target, "retry": "never"}
    label = {"operation_id": "label", "tool": "complete_label", "args": {},
             "reservation_from": "query", "target": target, "retry": "no_effect",
             "depends_on": ["query"]}
    messages = [
        {"message_id": "reserve", "user_id": "alice", "session_id": "work",
         "public_index": 0, "text": "Reserve once and save the actual parcel progress."},
        {"message_id": "finish", "user_id": "alice",
         "session_id": "later" if case == "later" else "work",
         "public_index": 0 if case == "later" else 1,
         "text": ("A new independent request: reserve with the same parameters once. "
                  "Report the real outcome." if case == "later" else
                  "Read the existing reservation, finish only the label, "
                  "and update saved progress.")},
        {"message_id": "handoff", "user_id": "alice", "session_id": "handoff",
         "public_index": 0,
         "text": "Read saved parcel progress. Change no business or memory state."},
    ]
    phases = [{"id": index, "operator_memory": [],
               "world_events": ([{"event_id": "restore", "action": "set_label_available",
                                  "available": True}] if index == 1 and case != "later" else []),
               "messages": [message]} for index, message in enumerate(messages)]
    if case == "unknown":
        messages.pop(1)
        phases = [{**phases[0]}, {**phases[2], "id": 1}]
    script = {"initial_label_available": case == "later", "phases": phases}
    bindings = {}
    for phase in phases:
        message = phase["messages"][0]
        scope = FoundationScope("r2-mechanical", "protected", "alice",
                                "application:" + message["session_id"])
        task = "later-task" if message["message_id"] == "finish" and case == "later" else "task"
        ops = ([] if message["message_id"] == "handoff" else [reserve, query, label]
               if message["message_id"] == "reserve" else [reserve, query]
               if case == "later" else [query, label])
        bindings[message["message_id"]] = _r2_test_binding(scope, message, task, ops)
    if case == "unknown" and stage == 1:
        world = app.ApplicationWorld(root / "business-world.sqlite", False)
        world.set_label_available("restore-unknown", True)
        world.close()
    wires: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    current_status = ""
    operation_status = ""

    def parse_receipts(wire: dict[str, Any]) -> None:
        nonlocal current_status, operation_status
        for row in wire["messages"]:
            if row["role"] != "tool":
                continue
            try:
                value = json.loads(row["content"])
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and value.get("status") == "ORIGINAL_CALL_OUTCOME_UNKNOWN":
                value = json.loads(value["query_receipt"])
            if isinstance(value, dict) and "reservation_id" in value:
                ids["reservation"] = value["reservation_id"]
                current_status = value.get("label_status", current_status)
                operation_status = value.get("status", operation_status)
            if isinstance(value, list) and value and "key" in value[0]:
                ids["memory"] = value[0]["key"]
                saved = json.loads(value[0]["value"]["content"])
                ids["reservation"] = saved["reservation_id"]
                current_status = current_status or saved["label_status"]

    if stage == 0:
        plan = ["reserve"]
        if case == "no_effect":
            plan += ["query", "label"]
        plan += ["create", "answer"]
    elif stage == 1:
        plan = (["reserve", "answer"] if case == "later" else
                ["label", "create", "answer"] if case == "unknown" else
                ["query", "label", "search", "update", "answer"])
    else:
        plan = ["search", "answer"]

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        parse_receipts(wire)
        action_name = plan[len(wires) - 1]
        facts = {**target, "reservation_id": ids.get("reservation", ""),
                 "label_status": current_status}
        actions = {
            "reserve": ("reserve_and_label", target),
            "query": ("get_reservation", {"item_key": target["item_key"]}),
            "label": ("complete_label", {"reservation_id": ids.get("reservation", "")}),
            "search": ("search_memory", {"query": "parcel", "limit": 10}),
            "create": ("manage_memory", {"action": "create", "content": json.dumps(facts)}),
            "update": ("manage_memory", {"action": "update", "id": ids.get("memory", ""),
                                          "content": json.dumps(facts)}),
        }
        reported = ({**facts, "operation_status": operation_status}
                    if case == "later" and stage == 1 else facts)
        action = ({"answer": json.dumps(reported)} if action_name == "answer" else
                  {"calls": [{"name": actions[action_name][0],
                              "arguments": actions[action_name][1]}]})
        return httpx.Response(200, json={
            "id": f"r2-{case}-{stage}-{len(wires)}", "model": "mechanical-http",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    def lose_response(row: dict[str, Any], response: Any) -> None:
        marker = root / "injected-once.json"
        if case == "unknown" and row["name"] == "reserve_and_label" and not marker.exists():
            actual = json.loads(response.content)
            assert actual["status"] == "reserved_label_failed"
            write_json(marker, {"pid": os.getpid(), "point": row["response_hook_point"],
                                "native_status": actual["status"]})
            raise RuntimeError("PREDECLARED_POST_COMMIT_RESPONSE_LOST")

    base = _R2DurableTestStore(root / "memory.sqlite")
    before_writes = base.conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
    sidecar = RevisionSidecar(root / "instrumentation.sqlite")
    observer = ProvenanceObserver(sidecar, "r2-mechanical", "protected")
    store = ObservedStore(base, observer)
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mechanical-http",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        client.emit = observer.capture_provider_event
        with SqliteSaver.from_conn_string(str(root / "checkpoint.sqlite")) as saver:
            runtime = app_runtime.ApplicationRuntime(
                VLLMChatModel(client=client, capacity_path=root / "capacity.json",
                              observer=observer),
                store, saver, observer)
            phase_id = (0 if stage == 1 else 1) if case == "unknown" and stage else stage
            try:
                result = app.run_phase(script, root, "r2-mechanical", "protected", phase_id,
                                       runtime, memory_contract="strict",
                                       trusted_business_contracts=bindings,
                                       business_response_hook=(
                                           lose_response if case == "unknown" else None))
            except RuntimeError as error:
                if case != "unknown" or stage != 0 or str(error) != (
                    "PREDECLARED_POST_COMMIT_RESPONSE_LOST"
                ):
                    raise
                result = {"status": "EXPECTED_UNKNOWN", "error": str(error)}
    namespace = ("langmem", "r2-mechanical", "protected", "alice")
    records = [{"key": row.key, "value": row.value} for row in base.search(namespace)]
    write_json(root / f"stage-{stage}-evidence.json", {
        "pid": os.getpid(), "result": result, "wires": wires, "records": records,
        "writes_before": before_writes,
        "writes_after": base.conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0],
        "capacity": read_json(root / "capacity.json"),
    })
    sidecar.close()
    base.conn.close()


@pytest.mark.parametrize("case", ["partial", "unknown", "no_effect", "later"])
def test_r2_four_application_lifecycles_in_real_subprocesses(tmp_path: Path, case: str) -> None:
    from milai_lab.harness.contextual_artifacts import read_json

    evidence_root = os.environ.get("MILAI_R2_ENGINEERING_EVIDENCE")
    root = (Path(evidence_root) if evidence_root else tmp_path) / case
    root.mkdir(parents=True)
    for stage in range(3):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", "import runpy,sys; "
             "runpy.run_path(sys.argv[1])['_r2_subprocess_driver'](*sys.argv[2:])",
             str(Path(__file__).resolve()), str(root), case, str(stage)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    stages = [read_json(root / f"stage-{stage}-evidence.json") for stage in range(3)]
    assert len({row["pid"] for row in stages}) == 3
    world = app.ApplicationWorld(root / "business-world.sqlite", False)
    snapshot = world.snapshot()
    world.close()
    assert len(snapshot["reservations"]) == 1
    actual = snapshot["reservations"][0]
    assert actual["label_status"] == "created"
    assert sum(row["outcome"] == "reserved" for row in snapshot["attempts"]) == 1
    assert len(stages[2]["records"]) == 1
    facts = json.loads(stages[2]["records"][0]["value"]["content"])
    assert facts["reservation_id"] == actual["reservation_id"]
    assert facts["label_status"] == "created"
    assert all(facts[field] == actual[field] for field in (
        "item_key", "quantity", "destination", "packing"))
    assert stages[2]["writes_before"] == stages[2]["writes_after"]
    assert stages[2]["records"] == stages[1]["records"]
    answer = json.loads(stages[2]["result"]["messages"][0]["answer"])
    assert answer == facts
    assert all(value <= 12 for row in stages for value in row["capacity"].values())
    journal = read_json(root / "business-journal.json")
    calls = [row for row in journal.values() if "thread_id" in row]
    if case == "unknown":
        original = next(row for row in calls if row["name"] == "reserve_and_label")
        assert original["status"] == "pending" and "result" not in original
        assert original["error"]["message"] == "PREDECLARED_POST_COMMIT_RESPONSE_LOST"
        recovery = journal["_application"]["recoveries"][original["journal_key"]]
        assert recovery["effect"] == "partial" and recovery["origin"] == "application_recovery"
        wire = stages[1]["wires"][0]["messages"]
        error = next(row for row in wire if row["role"] == "tool")
        visible = json.loads(error["content"])
        assert visible["status"] == "ORIGINAL_CALL_OUTCOME_UNKNOWN"
        assert visible["origin"] == "application_recovery" and visible["original_receipt"] is None
        assert json.loads(visible["query_receipt"])["reservation_id"] == actual["reservation_id"]
        assert len([row for row in calls if row["name"] == "reserve_and_label"]) == 1
        assert sum(stages[1]["capacity"].values()) == sum(len(row["wires"]) for row in stages[:2])
    if case == "no_effect":
        labels = [row for row in calls if row["name"] == "complete_label"]
        assert [row["effect"] for row in labels] == ["none", "confirmed"]
        assert labels[0]["operation_key"] == labels[1]["operation_key"]
    if case == "later":
        reserves = [row for row in calls if row["name"] == "reserve_and_label"]
        assert len(reserves) == 2 and all(row["executed"] for row in reserves)
        assert reserves[0]["operation_key"] != reserves[1]["operation_key"]
        assert reserves[1]["effect"] == "none"
        assert stages[1]["writes_before"] == stages[1]["writes_after"]
        assert json.loads(stages[1]["result"]["messages"][0]["answer"])[
            "operation_status"] == "duplicate_reservation_attempt"


def test_r2_scoped_query_is_only_source_of_label_id_and_prestate(tmp_path: Path) -> None:
    from langchain_core.messages import HumanMessage
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from milai_lab.baselines.langmem_agent import FoundationScope
    from milai_lab.runners.langmem_foundation import BusinessActionJournal

    world = app.ApplicationWorld(tmp_path / "world.sqlite", False)
    target = {"item_key": "exact parcel", "quantity": 2, "destination": "east", "packing": "paper"}
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "r2", "protected")
    journal = BusinessActionJournal(tmp_path / "journal.json", app.BUSINESS_NAMES,
                                    application_protection=True)
    query_is_incomplete = False

    def setup(owner: str, task: str, expected: dict[str, Any]) -> tuple[Any, Any]:
        scope = FoundationScope("r2", "protected", owner, "application:" + task)
        operations = [
            {"operation_id": "reserve", "tool": "reserve_and_label", "args": expected,
             "target": expected},
            {"operation_id": "query", "tool": "get_reservation",
             "args": {"item_key": expected["item_key"]}, "target": expected},
            {"operation_id": "label", "tool": "complete_label", "args": {},
             "target": expected, "reservation_from": "query", "retry": "no_effect",
             "depends_on": ["query"], "precondition": {
                 "query_operation_id": "query", "status": "found", "label_status": "not_created"}},
        ]
        journal.bind_request(_r2_test_binding(scope, {"public_index": 0, "message_id": task},
                                              task, operations))
        observer.begin_public_message(scope, 0, "Trusted request")

        def wrapped(request: Any, execute: Any) -> Any:
            def received(item: Any) -> Any:
                response = execute(item)
                if query_is_incomplete and item.tool_call["name"] == "get_reservation":
                    raw = json.loads(response.content)
                    raw.pop("quantity", None)  # Declared malformed read-response control.
                    return response.model_copy(update={"content": json.dumps(raw)})
                return response
            return observer.run_tool(request, lambda item: journal(item, received), journal)

        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode(app._business_tools(world, owner), wrap_tool_call=wrapped))
        graph.set_entry_point("tools")
        graph.set_finish_point("tools")
        return graph.compile(), scope

    def call(agent: Any, scope: Any, name: str, args: dict[str, Any], call_id: str) -> Any:
        result = agent.invoke({"messages": [HumanMessage(content="Trusted request"), AIMessage(
            content="", id="generation-" + call_id,
            tool_calls=[{"name": name, "args": args, "id": call_id}])]}, config=scope.config())
        return result["messages"][-1]

    agent, scope = setup("alice", "seed", target)
    reserved = json.loads(call(agent, scope, "reserve_and_label", target, "seed").content)
    reservation_id = reserved["reservation_id"]
    agent, scope = setup("bob", "wrong-owner", target)
    assert json.loads(call(agent, scope, "get_reservation", {"item_key": target["item_key"]},
                           "bob-query").content)["status"] == "not_found"
    assert call(agent, scope, "complete_label", {"reservation_id": reservation_id},
                "bob-label").status == "error"
    agent, scope = setup("alice", "mismatch", {**target, "quantity": 9})
    call(agent, scope, "get_reservation", {"item_key": target["item_key"]}, "mismatch-query")
    assert call(agent, scope, "complete_label", {"reservation_id": reservation_id},
                "mismatch-label").status == "error"
    agent, scope = setup("alice", "finish", target)
    assert call(agent, scope, "complete_label", {"reservation_id": reservation_id},
                "label-before-query").status == "error"
    actual = json.loads(call(agent, scope, "get_reservation", {"item_key": target["item_key"]},
                            "actual-query").content)
    assert call(agent, scope, "complete_label", {"reservation_id": "guessed-id"},
                "guessed-label").status == "error"
    query_is_incomplete = True
    call(agent, scope, "get_reservation", {"item_key": target["item_key"]}, "incomplete-query")
    assert call(agent, scope, "complete_label", {"reservation_id": reservation_id},
                "stale-id-after-incomplete-query").status == "error"
    query_is_incomplete = False
    call(agent, scope, "get_reservation", {"item_key": target["item_key"]}, "fresh-query")
    unavailable = call(agent, scope, "complete_label", {"reservation_id": actual["reservation_id"]},
                       "label-unavailable")
    assert json.loads(unavailable.content)["status"] == "label_service_unavailable"
    world.set_label_available("restore", True)
    completed = call(agent, scope, "complete_label", {
        "reservation_id": actual["reservation_id"]}, "label-retry")
    assert json.loads(completed.content)["status"] == "label_created"
    assert call(agent, scope, "complete_label", {"reservation_id": actual["reservation_id"]},
                "label-duplicate").status == "error"
    observer.assert_healthy()
    assert len(world.snapshot()["attempts"]) == 2
    world.close()
    sidecar.close()


def test_r2_pending_multicall_cannot_skip_an_unexecuted_call(tmp_path: Path) -> None:
    from langchain_core.messages import HumanMessage
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from milai_lab.baselines.langmem_agent import FoundationScope, build_agent
    from milai_lab.runners.langmem_foundation import BusinessActionJournal, UnknownBusinessAction

    scope = FoundationScope("r2", "protected", "alice", "application:unknown")
    target = {"item_key": "parcel", "quantity": 2, "destination": "east", "packing": "paper"}
    world = app.ApplicationWorld(tmp_path / "world.sqlite", False)
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "r2", "protected")
    observer.begin_public_message(scope, 0, "Reserve once")

    def lose_response(_row: dict[str, Any], _response: Any) -> None:
        raise RuntimeError("declared lost outcome")

    journal = BusinessActionJournal(tmp_path / "journal.json", app.BUSINESS_NAMES,
                                    application_protection=True, response_hook=lose_response)
    journal.bind_request(_r2_test_binding(scope, {"public_index": 0, "message_id": "m"}, "task", [
        {"operation_id": "reserve", "tool": "reserve_and_label", "args": target, "target": target},
        {"operation_id": "query", "tool": "get_reservation",
         "args": {"item_key": "parcel"}, "target": target},
    ]))
    first_call = {"name": "reserve_and_label", "args": target, "id": "unknown"}
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode(app._business_tools(world, "alice"), wrap_tool_call=journal))
    graph.set_entry_point("tools")
    graph.set_finish_point("tools")
    with pytest.raises(RuntimeError, match="declared lost outcome"):
        graph.compile().invoke({"messages": [HumanMessage(content="Reserve once"), AIMessage(
            content="original body", id="original-generation", tool_calls=[first_call])]},
            config=scope.config())
    client = VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="unused"),
                        transport=httpx.MockTransport(lambda _request: pytest.fail("No Host call")))
    with client, SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
        model = VLLMChatModel(client=client, observer=observer)
        agent = build_agent(model, InMemoryStore(), saver, app._business_tools(world, "alice"),
                            business_call_wrapper=journal, observer=observer)
        original = AIMessage(content="original body", id="original-generation", tool_calls=[
            first_call, {"name": "get_reservation", "args": {"item_key": "parcel"},
                         "id": "not-run"}])
        agent.update_state(scope.config(), {"messages": [HumanMessage(content="Reserve once"),
                                                       original]}, as_node="agent")
        runtime = app_runtime.ApplicationRuntime(model, InMemoryStore(), saver, observer)
        with pytest.raises(UnknownBusinessAction, match="OTHER_CALL_UNRESOLVED"):
            app.recover_pending_application_call(agent, scope, journal, world, runtime)
        snapshot = agent.get_state(scope.config())
        assert snapshot.next == ("tools",) and snapshot.values["messages"][-1] == original
    assert len(world.snapshot()["attempts"]) == 1
    assert len(journal.calls_for_thread(scope.config()["configurable"]["thread_id"])) == 1
    observer.assert_healthy()
    world.close()
    sidecar.close()


def test_durable_partial_business_result_and_user_scope(tmp_path: Path) -> None:
    path = tmp_path / "world.sqlite"
    world = app.ApplicationWorld(path, initial_label_available=False)
    partial = json.loads(world.reserve_and_label(
        "alice", "same-item", 6, "east bay", "foam"))
    assert partial["ok"] is False and partial["status"] == "reserved_label_failed"
    assert partial["label_status"] == "not_created"
    reservation_id = partial["reservation_id"]
    assert json.loads(world.get_reservation("bob", "same-item"))["status"] == "not_found"
    world.close()

    reopened = app.ApplicationWorld(path, initial_label_available=True)
    assert reopened.snapshot()["label_available"] is False
    assert json.loads(reopened.get_reservation("alice", "same-item"))[
        "reservation_id"] == reservation_id
    reopened.set_label_available("restore", True)
    assert json.loads(reopened.complete_label("bob", reservation_id))["status"] == "not_found"
    completed = json.loads(reopened.complete_label("alice", reservation_id))
    assert completed["ok"] is True and completed["status"] == "label_created"
    duplicate = json.loads(reopened.reserve_and_label(
        "alice", "same-item", 6, "east bay", "foam"))
    assert duplicate["status"] == "duplicate_reservation_attempt"
    bob = json.loads(reopened.reserve_and_label(
        "bob", "same-item", 3, "south bay", "cloth"))
    assert bob["ok"] is True and bob["reservation_id"] != reservation_id
    assert len(reopened.snapshot()["reservations"]) == 2
    assert len(reopened.snapshot()["attempts"]) == 4
    reopened.close()


def test_operator_aliases_bind_public_tool_ids_per_user(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1_control")
    store = ObservedStore(InMemoryStore(), observer)
    runtime = SimpleNamespace(store=store, observer=observer)
    root = tmp_path / "runtime"
    root.mkdir()
    try:
        for user_id, content in (("alice", "Alice first"), ("bob", "Bob first")):
            app._operator_memory_event({
                "event_id": user_id + "-create", "user_id": user_id,
                "action": "create", "alias": "plan", "content": content},
                "run", "b1_control", root, runtime)
        update = {"event_id": "alice-update", "user_id": "alice",
                  "action": "update", "alias": "plan", "content": "Alice second"}
        app._operator_memory_event(update, "run", "b1_control", root, runtime)
        app._operator_memory_event(update, "run", "b1_control", root, runtime)
        app._operator_memory_event({
            "event_id": "alice-old-create", "user_id": "alice", "action": "create",
            "alias": "old", "content": "Obsolete"}, "run", "b1_control", root, runtime)
        app._operator_memory_event({
            "event_id": "alice-old-delete", "user_id": "alice", "action": "delete",
            "alias": "old"}, "run", "b1_control", root, runtime)
        ledger = json.loads((root / "operator-memory.json").read_text())
        alice_id = ledger["aliases"]["alice"]["plan"]["id"]
        bob_id = ledger["aliases"]["bob"]["plan"]["id"]
        assert alice_id != bob_id
        assert store.get(("langmem", "run", "b1_control", "alice"), alice_id).value[
            "content"] == "Alice second"
        assert store.get(("langmem", "run", "b1_control", "bob"), bob_id).value[
            "content"] == "Bob first"
        old_id = ledger["aliases"]["alice"]["old"]["id"]
        assert store.get(("langmem", "run", "b1_control", "alice"), old_id) is None
        assert len(ledger["events"]) == 5
        assert {row["tool_name"] for row in sidecar.rows("tool_calls")} == {
            "operator:manage_memory"}
        ledger["events"]["interrupted"] = {
            "input": {"event_id": "interrupted", "user_id": "alice",
                      "action": "update", "alias": "plan", "content": "Never replay"},
            "status": "pending"}
        (root / "operator-memory.json").write_text(json.dumps(ledger))
        with pytest.raises(ValueError, match="APPLICATION_OPERATOR_OUTCOME_UNKNOWN"):
            app._operator_memory_event(ledger["events"]["interrupted"]["input"],
                                       "run", "b1_control", root, runtime)
    finally:
        sidecar.close()


def test_phase_resume_and_local_capacity_only_skip_same_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = {"initial_label_available": False, "phases": [
        {"id": 0, "operator_memory": [], "world_events": [], "messages": [
            {"message_id": "a0", "user_id": "alice", "session_id": "main",
             "public_index": 0, "text": "a0"},
            {"message_id": "b0", "user_id": "bob", "session_id": "main",
             "public_index": 0, "text": "b0"}]},
        {"id": 1, "operator_memory": [], "world_events": [], "messages": [
            {"message_id": "a1", "user_id": "alice", "session_id": "main",
             "public_index": 1, "text": "capacity"},
            {"message_id": "a2", "user_id": "alice", "session_id": "main",
             "public_index": 2, "text": "skip"},
            {"message_id": "b1", "user_id": "bob", "session_id": "main",
             "public_index": 1, "text": "b1"}]},
    ]}
    calls: list[tuple[str, str, int]] = []

    def invoke(_agent: Any, _model: Any, scope: Any, text: str,
               index: int, _pending: bool) -> list[AIMessage]:
        calls.append((scope.user_id, text, index))
        if text == "capacity":
            raise ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")
        return [AIMessage(content="done", id=text)]

    monkeypatch.setattr(app, "build_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(app, "invoke_or_resume_public_message", invoke)
    runtime = SimpleNamespace(model=object(), store=object(), checkpointer=object(),
                              observer=SimpleNamespace(assert_healthy=lambda: None))
    first = app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime)
    assert first["status"] == "TERMINAL"
    assert app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime) == first
    second = app.run_phase(script, tmp_path, "run", "b1_control", 1, runtime)
    assert second["status"] == "TERMINAL_WITH_LOCAL_CAPACITY_FAILURE"
    assert [row["status"] for row in second["messages"]] == [
        "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED",
        "SKIPPED_AFTER_LOCAL_CAPACITY", "COMPLETED"]
    assert calls == [("alice", "a0", 0), ("bob", "b0", 0),
                     ("alice", "capacity", 1), ("bob", "b1", 1)]

    def service_failure(*_args: Any) -> list[AIMessage]:
        raise RuntimeError("SERVICE_UNAVAILABLE")

    monkeypatch.setattr(app, "invoke_or_resume_public_message", service_failure)
    fault_root = tmp_path / "fault"
    fault_root.mkdir()
    with pytest.raises(RuntimeError, match="SERVICE_UNAVAILABLE"):
        app.run_phase({"initial_label_available": False, "phases": [{
            "id": 0, "operator_memory": [], "world_events": [], "messages": [
                {"message_id": "fault", "user_id": "alice", "session_id": "main",
                 "public_index": 0, "text": "fault"},
                {"message_id": "untouched", "user_id": "bob", "session_id": "main",
                 "public_index": 0, "text": "untouched"}]}]},
            fault_root, "run", "b1_control", 0, runtime)
    assert json.loads((fault_root / "phase-progress.json").read_text())[
        "pending_message"] == "fault"


def test_phase_passes_strict_host_contract_without_changing_operator_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = {"initial_label_available": True, "phases": [{
        "id": 0, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": "m0", "user_id": "alice", "session_id": "main",
            "public_index": 0, "text": "hello"}]}]}
    selected: list[str] = []

    def build(*_args: Any, **kwargs: Any) -> object:
        selected.append(kwargs["memory_contract"])
        return object()

    monkeypatch.setattr(app, "build_agent", build)
    monkeypatch.setattr(app, "invoke_or_resume_public_message",
                        lambda *_args: [AIMessage(content="done")])
    runtime = SimpleNamespace(model=object(), store=object(), checkpointer=object(),
                              observer=SimpleNamespace(assert_healthy=lambda: None))
    result = app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime,
                           memory_contract="strict")
    assert result["messages"][0]["status"] == "COMPLETED"
    assert selected == ["strict"]


def test_phase_reopens_checkpoint_and_new_session_starts_fresh(tmp_path: Path) -> None:
    script = {"initial_label_available": False, "phases": [
        {"id": index, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": f"m{index}", "user_id": "alice",
            "session_id": "handoff" if index < 2 else "followup",
            "public_index": index if index < 2 else 0,
            "text": f"message {index}"}]}
        for index in range(3)]}
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "id": f"generation-{len(wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"answer": "done"})}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    for phase_id in range(3):
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(respond)) as client:
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                runtime = SimpleNamespace(
                    model=VLLMChatModel(client=client), store=InMemoryStore(),
                    checkpointer=saver,
                    observer=SimpleNamespace(
                        assert_healthy=lambda: None,
                        run_tool=lambda request, execute, _wrapper: execute(request)))
                app.run_phase(script, tmp_path, "run", "b1_control", phase_id, runtime)
    assert [sum(message["role"] == "user" for message in wire["messages"])
            for wire in wires] == [1, 2, 1]


def test_full_history_replays_interleaved_turns_after_process_reopen(
    tmp_path: Path,
) -> None:
    from milai_lab.harness.contextual_artifacts import write_json

    write_json(tmp_path / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "full_history"}})
    script = {"initial_label_available": False, "phases": [
        {"id": index, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": f"m{index}", "user_id": "alice",
            "session_id": "a" if index != 1 else "b",
            "public_index": 1 if index == 2 else 0,
            "text": f"message {index}"}]}
        for index in range(3)]}
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        action = ({"calls": [{"name": "read_history", "arguments": {
            "cursor": 0, "max_bytes": 16384}}]}
                  if len(wires) == 3 else
                  {"answer": f"done {len(wires) - (len(wires) == 4)}"})
        return httpx.Response(200, json={
            "id": f"generation-{len(wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    store = InMemoryStore()
    for phase_id in range(3):
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(respond)) as client:
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                runtime = SimpleNamespace(
                    model=VLLMChatModel(client=client), store=store, checkpointer=saver,
                    observer=SimpleNamespace(
                        assert_healthy=lambda: None,
                        run_tool=lambda request, execute, _wrapper: execute(request)))
                app.run_phase(script, tmp_path, "run", "full_history", phase_id, runtime,
                              history_mode="full", history_page_max_bytes=16384)
    last = wires[3]["messages"]
    assert [message["content"] for message in last if message["role"] == "user"] == [
        "message 0", "message 1", "message 2"]
    assert [message["content"] for message in last if message["role"] == "assistant"][:2] == [
        "done 1", "done 2"]
    result = next(message for message in last if message["role"] == "tool")
    assert [row["message_id"] for row in json.loads(result["content"])["records"]] == [
        "m0", "m1"]
    assert all("read_history" in wire["messages"][0]["content"] for wire in wires)
    progress = json.loads((tmp_path / "phase-progress.json").read_text())
    assert [row["visited_ordinal"] for row in progress["messages"].values()] == [0, 1, 2]


def test_window_summary_uses_one_accounted_control_call_and_same_history_tool(
    tmp_path: Path,
) -> None:
    from milai_lab.harness.contextual_artifacts import write_json

    write_json(tmp_path / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "window_summary"}})
    script = {"initial_label_available": False, "phases": [
        {"id": index, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": f"m{index}", "user_id": "alice",
            "session_id": "a" if index % 2 == 0 else "b",
            "public_index": index // 2,
            "text": f"message {index}"}]}
        for index in range(4)]}
    host_wires: list[dict[str, Any]] = []
    control_wires: list[dict[str, Any]] = []
    control_events: list[dict[str, Any]] = []

    def host_response(request: httpx.Request) -> httpx.Response:
        host_wires.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "id": f"host-{len(host_wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"answer": "done"})}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    def control_response(request: httpx.Request) -> httpx.Response:
        control_wires.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "id": "control-1", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"summary": "Message 0."})}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    store = InMemoryStore()
    for phase_id in range(4):
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(host_response)) as host:
            with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                       max_tokens=2048),
                            emit=lambda event: control_events.append({
                                **event, "role": "state_control",
                                "control_stage": CONTROL_STAGE.get()}),
                            transport=httpx.MockTransport(control_response)) as control:
                with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                    runtime = SimpleNamespace(
                        model=VLLMChatModel(client=host), store=store, checkpointer=saver,
                        observer=SimpleNamespace(
                            assert_healthy=lambda: None,
                            run_tool=lambda request, execute, _wrapper: execute(request)))
                    summary = HistorySummaryController(
                        control, window_completed_turns=2,
                        summary_content_max_chars=16000,
                        capacity_path=tmp_path / "control-capacity.json",
                        max_calls_per_message=13)
                    app.run_phase(script, tmp_path, "run", "window_summary", phase_id,
                                  runtime, history_mode="window",
                                  history_page_max_bytes=16384,
                                  history_summary_controller=summary)
    assert len(host_wires) == 4 and len(control_wires) == 1
    assert [item["content"] for item in host_wires[-1]["messages"]
            if item["role"] == "user"] == ["message 1", "message 2", "message 3"]
    assert "Message 0." in host_wires[-1]["messages"][0]["content"]
    assert "message 3" not in json.dumps(control_wires[0], ensure_ascii=False)
    assert control_wires[0]["max_tokens"] == 2048
    assert any(item["event"] == "vllm_response" and item["role"] == "state_control"
               and item["control_stage"] == "history_summary"
               for item in control_events)
    counts = json.loads((tmp_path / "control-capacity.json").read_text())
    assert sum(value for key, value in counts.items()
               if key.startswith("history_summary:")) == 1
    schemas = [wire["response_format"] for wire in host_wires]
    assert all(item == schemas[0] for item in schemas)
    assert "read_history" in json.dumps(schemas[0])
    full_root = tmp_path / "full"
    full_root.mkdir()
    write_json(full_root / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "full_history"}})
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(host_response)) as host:
        with SqliteSaver.from_conn_string(str(full_root / "checkpoint.sqlite")) as saver:
            runtime = SimpleNamespace(
                model=VLLMChatModel(client=host), store=store, checkpointer=saver,
                observer=SimpleNamespace(
                    assert_healthy=lambda: None,
                    run_tool=lambda request, execute, _wrapper: execute(request)))
            app.run_phase({**script, "phases": script["phases"][:1]}, full_root,
                          "run", "full_history", 0, runtime,
                          history_mode="full", history_page_max_bytes=16384)
    assert host_wires[-1]["response_format"] == schemas[0]


def test_mock_provider_business_call_commits_real_partial_result(tmp_path: Path) -> None:
    script = {"initial_label_available": False, "phases": [{
        "id": 0, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": "reserve", "user_id": "alice", "session_id": "handoff",
            "public_index": 0, "text": "Reserve the complete item reference once."}]}]}
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        action = ({"calls": [{"name": "reserve_and_label", "arguments": {
            "item_key": "Cobalt display panels", "quantity": 6,
            "destination": "east bay", "packing": "foam"}}]}
            if len(wires) == 1 else {"answer": "Reservation persisted; label failed."})
        return httpx.Response(200, json={
            "id": f"generation-{len(wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            runtime = SimpleNamespace(
                model=VLLMChatModel(client=client), store=InMemoryStore(),
                checkpointer=saver,
                observer=SimpleNamespace(
                    assert_healthy=lambda: None,
                    run_tool=lambda request, execute, _wrapper: execute(request)))
            result = app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime)
            assert app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime) == result
    assert len(wires) == 2
    assert "complete item reference" in wires[0]["messages"][0]["content"]
    assert len(result["world"]["reservations"]) == 1
    assert result["world"]["reservations"][0]["label_status"] == "not_created"
    assert len(result["world"]["attempts"]) == 1
    assert result["messages"][0]["business_calls"][0]["status"] == "complete"


def test_four_arm_policy_and_generic_frozen_script_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(app_runtime, "ProjectionController", lambda *_args, **kwargs: (
        captured.append(kwargs) or kwargs))
    config = {"refresh_policy": {
        "refresh_until_current_candidate": True,
        "max_exact_refresh_per_search": 1}}
    for arm in ("b1_control", "a3_exact_refresh", "a4_selective_rebase",
                "a5_rank_bounded_rebase"):
        app_runtime.projection_for_arm(None, None, None, arm, config)
    assert [item["arm"] for item in captured] == [
        "a3_exact_refresh", "a4_selective_rebase", "a5_rank_bounded_rebase"]
    assert all(item["stage"] == "v21" for item in captured)
    assert [item["max_exact_refresh_per_search"] for item in captured] == [None, None, 1]
    reserve_key = app.BUSINESS_SCHEMAS[0]["function"]["parameters"]["properties"]["item_key"]
    read_key = app.BUSINESS_SCHEMAS[1]["function"]["parameters"]["properties"]["item_key"]
    assert "complete item reference" in reserve_key["description"]
    assert "complete item reference" in read_key["description"]

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_milai_application_v25 as entry

    monkeypatch.setattr(entry, "verify_application_v25_lock", lambda *_args, **_kwargs: {})
    lock, app_config = tmp_path / "lock.json", tmp_path / "config.json"
    lock.write_text("{}")
    app_config.write_text("{}")
    for variant in ("short", "medium", "long"):
        suffix = "" if variant == "short" else "-" + variant
        script = LAB / f"data/diagnostics/milai-application-v25{suffix}-script.json"
        freeze = LAB / f"data/manifests/milai-application-v25{suffix}-input-freeze.json"
        receipt = entry.prepare(SimpleNamespace(
            lock=lock, config=app_config, script=script, input_freeze=freeze,
            run="run", arm="b1_control", runtime_root=tmp_path / variant,
            output=tmp_path / f"{variant}.json"))
        assert receipt["public_messages"] == 9
        assert receipt["rubric_read_by_runner"] is False
