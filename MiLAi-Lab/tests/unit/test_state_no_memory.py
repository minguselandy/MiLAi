"""Explicit Host-only STATE execution; no empty retrieval receipt stands in for a baseline."""
import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.harness.http_ownership import PROFILE
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.state_bench_adapter import RETRIEVAL_INSTRUCTION, make_state_agent


def test_no_memory_agent_keeps_public_turn_gate_and_strips_hidden_context():
    sdk = pytest.importorskip("state_bench.agents.base")
    from langchain_core.messages import AIMessage

    turns, inputs = [], []

    class Model:
        def begin_public_message(self, key):
            turns.append(key)

        def bind_tools(self, tools):
            assert tools == []
            return self

        def invoke(self, messages):
            inputs.append(messages)
            return AIMessage(content="A public answer")

    runtime = sdk.AgentRuntimeContext(task_id="HIDDEN", user_id="u1", domain="travel", now="now",
        task_summary="HIDDEN", state_requirements=[{"HIDDEN": True}], config={"HIDDEN": True})
    agent = make_state_agent(Model(), None, runtime)
    assert agent.memory_tool_schemas() == [] and agent.memory_tool_handlers() == {}
    assert agent.runtime_context.task_id == "state-task"
    assert not agent.runtime_context.state_requirements
    assert agent.runtime_context.task_summary is None
    first = [{"role": "user", "content": "Public question"}]
    for conversation in [first, first, [*first, {"role": "user", "content": "Next question"}]]:
        agent.generate_next_turn(system_prompt="Public domain policy", conversation=conversation,
                                 tools=[])
    assert turns == ["turn-1", "turn-2"]
    assert all(rows[0].content == "Public domain policy" for rows in inputs)
    assert "HIDDEN" not in str(inputs) and RETRIEVAL_INSTRUCTION not in str(inputs)
    with pytest.raises(ValueError, match="requires a memory hook"):
        make_state_agent(Model(), None, runtime, initial_retrieval={"query": "memory"})


@pytest.mark.parametrize("host_instructions", [
    None, "Separate observed premises from conditional quotes."])
def test_cli_runs_native_domain_without_memory_storage_or_receipts(
    tmp_path, monkeypatch, host_instructions,
):
    state_bench = pytest.importorskip("state_bench")
    import run_state_bench_local_pilot as cli

    source = Path(state_bench.__file__).resolve().parent.parent
    preparation = tmp_path / "preparation"
    write_json(preparation / "selection.json", {"source": str(source), "domain": "travel",
        "split": "train", "task_id": "1-cancel_economy_domestic"})
    assert not (preparation / "sources.json").exists()
    budget_path = tmp_path / "original-budget.json"
    budget = RunBudget(RunLimits(), budget_path)
    budget.record_compute("existing", {"cpu_seconds": 1})
    host = asdict(VLLMConfig(base_url="http://example.test/v1", model="scripted",
                            tool_mode="json_action", enable_thinking=True))
    settings = {"host": host, "capacity": {}, "max_calls_per_message": 8,
        "memory_control": {"policy": "laya", "checkpoint": "must-not-load"},
        "stage_enable_thinking": {"state_simulator": False},
        "budget_path": str(budget_path), "http_ownership_profile": PROFILE,
        "http_ownership_domain": {"deployment_id": "unit-no-memory", "clients": [host]}}
    if host_instructions is not None:
        settings["state_host_instructions"] = host_instructions
    config = tmp_path / "config.json"
    write_json(config, {"entrypoints": {"functional": settings}})
    requests = []

    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert "retrieve_learnings" not in json.dumps(payload)
        prompt = payload["messages"][0]["content"]
        is_simulator = payload["messages"][-1]["content"].startswith("CONVERSATION SO FAR:")
        if host_instructions is not None:
            assert (host_instructions in prompt) is not is_simulator
        if len(requests) == 1:
            result = {"calls": [{"name": "cancel_booking",
                                 "arguments": {"booking_id": "BK-1000", "confirm": True}}]}
        elif len(requests) == 2:
            result = {"answer": "Cancelled."}
        else:
            result = {"answer": "[TASK_DONE]"}
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant",
            "content": json.dumps(result)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    def client(config, **kwargs):
        return VLLMClient(config, transport=httpx.MockTransport(transport), **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Host-only mode must not construct memory or consume training corpus")

    monkeypatch.setattr(cli, "VLLMClient", client)
    monkeypatch.setattr(cli, "HostCapacity", lambda _: None)
    monkeypatch.setattr(cli, "build_retrieval", forbidden)
    monkeypatch.setattr(cli, "policy_and_pool", forbidden)
    monkeypatch.setattr(cli, "seed_sources", forbidden)
    monkeypatch.setattr(cli.TransactionalSqliteStore, "from_conn_string", forbidden)
    monkeypatch.setattr("sys.argv", ["pilot", str(config), str(preparation), str(tmp_path / "run"),
        "--source-version", "test", "--memory-protocol", "none", "--policy", "laya",
        "--compute-phase", "host-only-unit"])
    cli.main()
    run = read_json(tmp_path / "run/run.json")
    assert run["status"] == "COMPLETED_RESEARCH_TRAJECTORY"
    assert run["memory_calls"] == 0 and run["memory_policy"] is None
    assert run["state_host_instructions"] == (host_instructions or "")
    assert run["memory_control_configuration"] is None and run["max_return_tokens"] is None
    assert "source_import_receipts" not in run
    assert not (tmp_path / "run/memory.sqlite").exists()
    assert not (tmp_path / "run/memory-sources.json").exists()
    trajectory = read_json(tmp_path / "run/trajectory.json")
    assert [call["name"] for row in trajectory["conversation"]
            for call in row.get("tool_calls") or []] == ["cancel_booking"]
    diff = read_json(tmp_path / "run/state-diff.json")
    assert diff["modified"]["bookings"]["BK-1000"]["status"]["new"] == "cancelled"
    ledger = read_json(budget_path)
    assert ledger["generation_requests"] == 3 and ledger["generation"]["known_tokens"] == 45
    assert ledger["compute"]["existing"]["cpu_seconds"] == 1
    assert ledger["compute"]["host-only-unit"]["runs"] == 1
