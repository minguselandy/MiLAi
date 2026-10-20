"""Actual Store/optional STATE sandbox mechanics; scripted Host is not model evidence."""
import json

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


def test_public_sdk_executes_real_sandbox_write_without_hidden_context(tmp_path):
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
        if len(requests) == 1:
            action = {"calls": [{"name": "retrieve_learnings",
                "arguments": {"query": "hotel inventory identifier", "top_k": 3}}]}
        elif len(requests) == 2:
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
        hook = StateMemoryHook(memory_at(service), session="mechanical", now=now, domain="travel",
            user_id="u1", config_version="state-test", record=records.append)
        client = VLLMClient(VLLMConfig(base_url="http://example.test/v1/", model="scripted",
            tool_mode="json_action"), transport=httpx.MockTransport(scripted_transport))
        model = VLLMChatModel(client=client)
        agent = make_state_agent(model, hook, runtime)
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
        assert model.active_message_key == "turn-1" and model.calls_in_message == 3
        assert agent.token_usage.total_tokens == 45  # Scripted transport telemetry only.
        assert hidden not in canonical(records)
        client.close()


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
