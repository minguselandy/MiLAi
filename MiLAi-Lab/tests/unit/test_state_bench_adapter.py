"""Actual Store/optional STATE sandbox mechanics; scripted Host is not model evidence."""
import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import ToolMessage
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import context, memory_at

from milai_lab.memory.functional_state import canonical
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.state_bench_adapter import (
    StateMemoryHook,
    conversation_messages,
    learning_envelope,
    make_state_agent,
    run_with_domain_snapshots,
)


@pytest.mark.parametrize("override", [None, False, True])
def test_local_simulator_thinking_override_is_per_request_and_keeps_host_and_prompt(override):
    from run_state_bench_local_pilot import LocalSimulator

    wires = []

    def respond(request):
        wires.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant",
            "content": '{"answer":"Actual reply"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    with VLLMClient(VLLMConfig(base_url="http://example.test/v1", model="scripted",
        tool_mode="json_action", enable_thinking=True),
        transport=httpx.MockTransport(respond)) as client:
        host = VLLMChatModel(client=client)
        simulator_model = VLLMChatModel(client=client, max_calls_per_message=1)
        simulator = LocalSimulator(simulator_model, enable_thinking=override)
        original = [{"role": "system", "content": "Literal upstream simulator instructions"},
                    {"role": "user", "content": "Literal upstream conversation"}]
        assert simulator.complete_chat(messages=original) == "Actual reply"
        assert simulator.complete_chat(messages=original) == "Actual reply"
        assert simulator.calls == 2 and simulator_model.active_message_key == "simulator-2"
        assert simulator_model.calls_in_message == 1
        assert host.calls_in_message == 0
        host.begin_public_message("host-turn")
        host.invoke([{"role": "user", "content": "Host continues"}])
        assert [wire["chat_template_kwargs"]["enable_thinking"] for wire in wires] == [
            True if override is None else override,
            True if override is None else override, True]
        assert all(wire["messages"][-1]["content"] == original[-1]["content"] for wire in wires[:2])
        assert all(original[0]["content"] in wire["messages"][0]["content"] for wire in wires[:2])
        assert client.config.enable_thinking is True and host.calls_in_message == 1


def test_canonical_transcript_keeps_executed_tool_results_once_in_order():
    calls = [{"name": "lookup", "arguments": {"id": "B1"}, "result": {"seat": "aisle"}},
             {"name": "update", "arguments": {"seat": "window"}, "result": {"ok": True}}]
    messages = conversation_messages([
        {"role": "user", "content": "Change the seat."},
        {"role": "assistant", "content": "", "tool_calls": calls},
        {"role": "tool", "content": calls},
        {"role": "assistant", "content": "Done.", "tool_calls": None}])
    assert [m.type for m in messages] == ["human", "ai", "tool", "tool", "ai"]
    assert [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)] == [
        call["result"] for call in calls]
    assert [c["id"] for c in messages[1].tool_calls] == [
        m.tool_call_id for m in messages if isinstance(m, ToolMessage)]


def test_external_string_envelope_is_budgeted_before_material_admission(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-wire", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        body = 'Envelope report with quote " and slash \\; ' * 25
        source = service.capture_user("history", "report", body)
        request = RetrievalRequest(query="Envelope report with quote and slash")
        plain = memory_at(service)
        packet = plain.retrieve(context(service, "first"), "first", request)
        assert packet["evidence"]
        budget = len(canonical(packet)) + 10
        assert len(canonical(learning_envelope(packet))) > budget
        wrapped = memory_at(service, return_envelope=learning_envelope)
        wrapped.material_limit = budget
        result = wrapped.retrieve(context(service, "other"), "other", request)
        assert wrapped.return_tokens(result) <= budget
        assert result["usage"]["material_budget_rejections"] > 0
        assert all("Envelope report" not in source["content"]
                   for item in result["evidence"] for source in item["evidence"])
        assert service.source(source["source_ref"])["content"] == body


def test_memory_hook_keeps_one_public_allowance_and_only_actual_prior_refs(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-hook", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "report", "Use the hotel inventory identifier to book.")
        memory = memory_at(service)
        records = []
        hook = StateMemoryHook(memory, session="task", now="2026-06-15T10:00:00",
            domain="travel", user_id="user_001", config_version="state-test", record=records.append)
        conversation = [{"role": "user", "content": "Book my hotel."}]
        assert hook.bind_conversation(conversation)
        envelope = hook.retrieve({"query": "hotel inventory identifier", "top_k": 3})
        assert len(envelope["learnings"]) == 1
        packet = json.loads(envelope["learnings"][0])
        assert packet["evidence"]
        remaining = memory.read_allowance(hook.config)["reads_remaining"]
        assert not hook.bind_conversation(conversation)
        assert memory.read_allowance(hook.config)["reads_remaining"] == remaining
        assert records[0]["request"]["task_context"]["known_evidence_refs"] == []
        hook.retrieve({"query": "hotel inventory identifier"})
        assert records[1]["request"]["task_context"]["known_evidence_refs"] == [
            item["ref"] for item in packet["evidence"]]
        assert records[0]["request"]["task_context"]["known_evidence_refs"] == []


@pytest.mark.parametrize("now", ["2026-06-15T10:00:00", ""])
def test_dynamic_hook_keeps_real_tool_occurrences_across_upstream_transcript_regrouping(
    tmp_path, now,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        captured = datetime(2039, 10, 24, tzinfo=UTC)
        service = MemoryService(store, ("state-observations", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1", clock=lambda: captured)
        memory = memory_at(service)
        hook = StateMemoryHook(memory, session="task", now=now,
            domain="travel", user_id="u1", config_version="test", record=lambda _: None)
        opening = {"role": "user", "content": "Check my reservation before changing it."}
        assert hook.bind_conversation([opening])
        first = {"name": "lookup", "arguments": {"id": "B1"},
                 "result": {"status": "confirmed"}}
        recall = {"name": "retrieve_learnings", "arguments": {"query": "reservation"},
                  "result": {"learnings": ["Already stored evidence; not a new observation"]}}
        current = [opening, {"role": "assistant", "content": "Checking.",
                            "tool_calls": [recall, first]},
                   {"role": "tool", "content": [recall, first]}]
        assert not hook.bind_conversation(current)
        remaining = memory.read_allowance(hook.config)["reads_remaining"]
        # A repeated actual call with identical content is a distinct occurrence.
        current += [{"role": "assistant", "content": "Checking again.", "tool_calls": [first]},
                    {"role": "tool", "content": [first]}]
        assert not hook.bind_conversation(current)
        sources = service.sources()
        observed = [s for s in sources if s["role"] == "tool"]
        assert len(observed) == 2
        assert observed[0]["content"] == observed[1]["content"]
        assert json.loads(observed[0]["content"]) == first
        assert observed[0]["event_id"] != observed[1]["event_id"]
        assert all(s["origin"] == "lookup" and s["object_ref"] is None for s in observed)
        assert not hook.bind_conversation(current)
        assert memory.read_allowance(hook.config)["reads_remaining"] == remaining
        # STATE folds all calls into one assistant row after finishing a user turn.
        collapsed = [opening, {"role": "assistant", "content": "It is still confirmed.",
                               "tool_calls": [recall, first, first]},
                     {"role": "user", "content": "Keep it as is."}]
        assert hook.bind_conversation(collapsed)
        after = service.sources()
        assert len([s for s in after if s["role"] == "tool"]) == 2
        assert [s["content"] for s in after if s["role"] == "assistant"] == [
            "It is still confirmed."]
        assert len([s for s in after if s["role"] == "user"]) == 2
        assert "Already stored evidence" not in canonical(after)
        assert all(s.get("calendar_context") == (now or None) for s in after)
        assert all(s.get("occurred_at") is None for s in after)
        assert all(s["observed_at"] == captured.isoformat() for s in after)
        # Reopening a hook replays the same occurrences without changing their clocks.
        reopened = StateMemoryHook(memory, session="task", now=now,
            domain="travel", user_id="u1", config_version="test", record=lambda _: None)
        assert reopened.bind_conversation(collapsed)
        assert service.sources() == after


@pytest.mark.parametrize("prior_calendar", [None, "2026-06-14T10:00:00"])
def test_dynamic_hook_does_not_backfill_or_replace_existing_source_calendar(
    tmp_path, prior_calendar,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-existing", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        text = "Check my reservation before changing it."
        ref = service.capture_user("task", "turn-1", text,
                                   calendar_context=prior_calendar)["source_ref"]
        original = service.source(ref)
        now = "2026-06-15T10:00:00"
        hook = StateMemoryHook(memory_at(service), session="task", now=now,
            domain="travel", user_id="u1", config_version="test", record=lambda _: None)
        conversation = [{"role": "user", "content": text}]
        if prior_calendar is not None:
            with pytest.raises(ValueError, match="V13_SOURCE_CALENDAR_CONTEXT_CHANGED"):
                hook.bind_conversation(conversation)
        else:
            assert hook.bind_conversation(conversation)
            conversation.append({"role": "user", "content": "Keep it as is."})
            assert hook.bind_conversation(conversation)
            new_ref = service.event_id("task", "turn-2", "user")
            assert service.source(new_ref)["calendar_context"] == now
        assert service.source(ref) == original


def test_state_hook_preserves_host_evidence_requirements(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-rich", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "report", "The cancellation was only a preview.")
        records = []
        hook = StateMemoryHook(memory_at(service), session="task", now="2026-06-15T10:00:00",
            domain="travel", user_id="u1", config_version="test", record=records.append)
        hook.bind_conversation([{"role": "user", "content": "Has it actually executed?"}])
        goal = {"purpose": "Check execution against the original receipt",
                "evidence": ["original_source"], "required_points": ["preview or completed"]}
        hook.retrieve({"query": "cancellation", "top_k": 3, "read_goal": goal})
        assert records[-1]["request"]["read_goal"] == goal
        assert records[-1]["request"]["task_context"]["target_scope"] == {
            "domain": "travel", "user_id": "u1"}


@pytest.mark.parametrize("policy", ["rules", "laya"])
def test_state_builder_reuses_existing_policy_and_view_metering(tmp_path, monkeypatch, policy):
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from run_state_bench_local_pilot import build_retrieval

    loads, admissions, generations, records = [], [], [], []

    class Decision:
        def __init__(self, *args, **kwargs):
            loads.append(args)
            self.counters = {"forwards": 0, "input_tokens": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            self.counters["input_tokens"] += 1  # Synthetic unit-test accounting.
            return {"choice": "handoff" if payload["state"]["visible_evidence"]
                    else "refresh_view"}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Decision)

    def generate(stage, messages, schema):
        payload = json.loads(messages[-1]["content"])
        generations.append(stage)
        return {"scope": "Original booking advice", "nodes": [
            {"id": "n" + row["id"][1:], "text": row["text"], "kind": "reported",
             "evidence": [row["id"]]} for row in payload["sources"]],
            "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

    settings = {"ordinary_material_tokens": 8000, "additional_reads": 8,
        "source_top_k": 16, "semantic_top_k": 16, "memory_control": {
            "reads": 1, "max_control_steps": 8, "checkpoint": "scripted",
            "device": "cpu", "state_projection": "full"}}
    budget = RunBudget(RunLimits(), tmp_path / "unit-budget.json")
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-builder", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "report", "Use the hotel inventory identifier to book.")
        memory = build_retrieval(service, len, settings, policy, budget, records.append,
            call=generate, admit=lambda: admissions.append("local_prediction"))
        packet = memory.retrieve(context(service), "query", RetrievalRequest(query="hotel"))
        assert generations == ["query_structure"]
        assert any(e["kind"] == "query_structure" for e in packet["evidence"])
        if policy == "laya":
            assert len(loads) == 1 and len(admissions) == 2
            assert budget.state["compute"]["dynamic_memory_laya_load"]["loads"] == 1
            assert budget.state["compute"]["dynamic_memory_laya"]["forwards"] == 2
        else:
            assert not loads and not admissions and "compute" not in budget.state


def test_state_selected_pool_uses_actual_hook_and_records_nested_compute(tmp_path):
    pytest.importorskip("mempursuit")
    from langchain_core.embeddings import Embeddings

    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from run_state_bench_local_pilot import build_retrieval

    class Vectors(Embeddings):
        def embed_documents(self, texts):
            return [[1., 0.] if "hotel" in text else [0., 1.] for text in texts]

        def embed_query(self, text):
            return self.embed_documents([text])[0]

    settings = {"ordinary_material_tokens": 8000, "additional_reads": 8,
                "source_top_k": 16, "semantic_top_k": 16,
                "memory_control": {"reads": 4, "max_control_steps": 8,
                                   "pursuit_adaptive": True}}
    budget = RunBudget(RunLimits(), tmp_path / "unit-budget.json")
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-pursuit", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "hotel", "Use the hotel inventory identifier to book.")
        service.capture_user("history", "train", "A train reservation uses its service identifier.")
        records = []
        memory = build_retrieval(service, len, settings, "mempursuit", budget,
                                 records.append, embeddings=Vectors())
        hook = StateMemoryHook(memory, session="task", now="2026-06-15T10:00:00",
            domain="travel", user_id="u1", config_version="state-test", record=records.append)
        hook.bind_conversation([{"role": "user", "content": "Book my hotel."}])
        envelope = hook.retrieve({"query": "hotel inventory identifier", "top_k": 3})
        packet = json.loads(envelope["learnings"][0])
        assert "Use the hotel inventory identifier to book." in canonical(packet)
        assert len(canonical(envelope)) <= settings["ordinary_material_tokens"]
        assert all(item["kind"] == "original_source" for item in packet["evidence"])
        pools = [event for event in records if event["event"] == "memory_control_mempursuit_pool"]
        assert pools and pools[0]["query"] == "hotel inventory identifier"
        assert budget.state["compute"]["memory_control_mempursuit_pool"]["pools"] == len(pools)
        assert budget.state["generation_requests"] == 0


@pytest.mark.parametrize("frozen_request", [False, True])
@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("host_instructions", [
    "", "Separate observed premises from conditional quotes."])
def test_public_sdk_executes_real_sandbox_write_without_hidden_context(
    tmp_path, frozen_request, readonly, host_instructions,
):
    sdk = pytest.importorskip("state_bench.agents.base")
    from state_bench.domain import get_domain_config
    from state_bench.domains.travel.schemas import EnvironmentData, HotelInventoryItem, User
    from state_bench.orchestrator import _run_harness_executed_agent_turn

    domain = get_domain_config("travel")
    now = "2026-06-15T10:00:00"
    data = EnvironmentData(flights=[], bookings=[], users=[User("u1", "Alice", "a@example.test")],
        hotel_inventory=[HotelInventoryItem("H1", "Example Hotel", "DEN", "2026-07-01",
                                           "2026-07-02", "standard", 100, 100)])
    env = domain.environment_class(data, now)
    hidden = "HIDDEN_EVALUATOR_ONLY_SENTINEL"
    runtime = sdk.AgentRuntimeContext(task_id=hidden, user_id="u1", domain="travel", now=now,
        task_summary=hidden, state_requirements=[{"secret": hidden}],
        task_requirements=[{"secret": hidden}], config={"secret": hidden})

    requests = []

    def scripted_transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        text = "\n".join(m["content"] for m in payload["messages"])
        assert hidden not in text
        assert "retrieve_learnings" in text and "book_hotel" in text
        if host_instructions:
            assert payload["messages"][0]["content"].count(host_instructions) == 1
        step = len(requests) + int(frozen_request)
        if step == 1:
            action = {"calls": [{"name": "retrieve_learnings",
                "arguments": {"query": "hotel inventory identifier", "top_k": 3}}]}
        elif step == 2:
            assert "Use the hotel inventory identifier" in text
            action = {"calls": [{"name": "book_hotel",
                                "arguments": {"user_id": "u1", "hotel_id": "H1"}}]}
        else:
            assert '"status":"confirmed"' in text
            action = {"answer": "Booked."}
        return httpx.Response(200, json={"id": f"scripted-{len(requests)}", "model": "scripted",
            "choices": [{"message": {"role": "assistant", "content": canonical(action)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-sdk", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "report", "Use the hotel inventory identifier to book.")
        records = []
        if readonly:
            from milai_lab.methods.memory_control import FixedContextMemoryPolicy
            from milai_lab.methods.readonly_retrieval import (
                ReadOnlyMemoryService,
                ReadOnlyRetrieval,
            )
            from milai_lab.runners.state_bench_adapter import StateReadOnlyMemoryHook

            reader = ReadOnlyMemoryService(store, service.namespace, service.owner,
                tmp_path / "readonly.lock", functional_contract="functional_v1")
            memory = ReadOnlyRetrieval(reader, len, FixedContextMemoryPolicy(), material_limit=8000)
            hook = StateReadOnlyMemoryHook(memory, session="mechanical", now=now, domain="travel",
                user_id="u1", record=records.append)
            before = list(store.conn.iterdump())
            store.conn.execute("PRAGMA query_only=ON")
        else:
            hook = StateMemoryHook(memory_at(service), session="mechanical", now=now,
                domain="travel",
                user_id="u1", config_version="state-test", record=records.append)
        client = VLLMClient(VLLMConfig(base_url="http://example.test/v1/", model="scripted",
            tool_mode="json_action"), transport=httpx.MockTransport(scripted_transport))
        model = VLLMChatModel(client=client)
        frames = []
        agent = make_state_agent(model, hook, runtime, observe_host=frames.append,
            host_instructions=host_instructions,
            initial_retrieval={"query": "hotel inventory identifier", "top_k": 3}
            if frozen_request else None)
        assert agent.runtime_context.task_id == "mechanical"
        assert agent.runtime_context.task_summary is None
        assert agent.runtime_context.state_requirements == []
        assert agent.runtime_context.task_requirements == []
        assert agent.runtime_context.config == {}
        text, calls = _run_harness_executed_agent_turn(agent=agent,
            system_prompt=domain.agent_system_prompt.format(now=now, user_id="u1"),
            conversation_full=[{"role": "user", "content": "Book the H1 hotel for me."}],
            domain_tools=domain.tool_schemas, domain_tool_handlers=env.tool_handlers)
        assert text == "Booked."
        assert [c["name"] for c in calls] == ["retrieve_learnings", "book_hotel"]
        assert len(env.hotels) == 1
        assert next(iter(env.hotels.values())).hotel_id == "H1"
        assert model.active_message_key == "turn-1"
        assert model.calls_in_message == 3 - int(frozen_request)
        assert agent.token_usage.total_tokens == 15 * (3 - int(frozen_request))
        assert hidden not in canonical(records)
        assert hidden not in canonical(frames)
        assert frames[0]["host_request_generated"] is not frozen_request
        assert frames[0]["response"]["tool_calls"][0]["name"] == "retrieve_learnings"
        assert frames[1]["conversation"][1]["tool_calls"][0]["result"] == calls[0]["result"]
        assert frames[-1]["response"]["text"] == "Booked."
        if host_instructions:
            assert all(frame["system_prompt"].count(host_instructions) == 1 for frame in frames)
        if readonly:
            assert isinstance(calls[0]["result"], list) and len(calls[0]["result"]) <= 3
            assert list(store.conn.iterdump()) == before
        client.close()


def test_frozen_probe_accepts_only_public_memory_tool_arguments():
    pytest.importorskip("state_bench.agents.base")
    from jsonschema.exceptions import ValidationError

    with pytest.raises(ValidationError):
        make_state_agent(None, None, None, initial_retrieval={
            "query": "hotel", "state_requirements": ["hidden evaluator payload"]})


def test_actual_sandbox_write_survives_later_readout_failure(tmp_path):
    pytest.importorskip("state_bench.schemas")
    from state_bench.domain import get_domain_config
    from state_bench.domains.travel.schemas import EnvironmentData, HotelInventoryItem, User

    data = EnvironmentData(flights=[], bookings=[], users=[User("u1", "Alice", "a@example.test")],
        hotel_inventory=[HotelInventoryItem("H1", "Example Hotel", "DEN", "2026-07-01",
                                           "2026-07-02", "standard", 100, 100)])
    env = get_domain_config("travel").environment_class(data, "2026-06-15T10:00:00")

    def execute_then_fail():
        env.tool_handlers["book_hotel"]({"user_id": "u1", "hotel_id": "H1"})
        raise RuntimeError("Later readout failed")

    with pytest.raises(RuntimeError, match="Later readout failed"):
        run_with_domain_snapshots(env, tmp_path, execute_then_fail)
    before = json.loads((tmp_path / "state-before.json").read_text())
    after = json.loads((tmp_path / "state-after.json").read_text())
    assert before["hotels"] == {}
    assert next(iter(after["hotels"].values()))["hotel_id"] == "H1"
    diff = json.loads((tmp_path / "state-diff.json").read_text())
    assert diff["created"]["hotels"] == after["hotels"]
