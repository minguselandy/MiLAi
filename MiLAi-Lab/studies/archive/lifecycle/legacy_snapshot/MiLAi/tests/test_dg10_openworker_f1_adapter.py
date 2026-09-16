from __future__ import annotations

import json

from evals.agent_integration import f1_openworker, openworker_adapter


def test_extracts_nested_mcp_structured_result() -> None:
    recall = {
        "status": "OK",
        "items": [{"payload": {"python": "3.11"}}],
        "open_issue_ids": [],
    }
    messages = [
        {"role": "user", "content": "question"},
        {
            "role": "tool",
            "content": json.dumps({"structuredContent": recall}),
        },
    ]
    assert openworker_adapter._recall_from_messages(messages) == recall


def test_reader_lite_namespaced_tool_is_selected() -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": "milai_milai_recall", "parameters": {}},
        }
    ]
    assert openworker_adapter._tool_name(tools) == "milai_milai_recall"


def test_unrelated_json_is_not_treated_as_memory() -> None:
    messages = [{"role": "tool", "content": '{"status":"failed"}'}]
    assert openworker_adapter._recall_from_messages(messages) is None


def test_recall_query_preserves_original_question() -> None:
    question = (
        "Use the tool once. What Python version belongs to synthetic project "
        "milaie2eABCDEF123456? Preserve uncertainty."
    )
    assert openworker_adapter._recall_query(question) == question


def test_serving_memory_mode_can_freeze_route_without_changing_prompt() -> None:
    question = "What is the remembered project version?"

    assert not openworker_adapter._should_recall("none")
    assert openworker_adapter._should_recall("prefetch")
    assert openworker_adapter._should_recall("auto")
    assert openworker_adapter._task_seed(question) == openworker_adapter._task_seed(question)


def test_openworker_run_reuses_the_pre_warmed_container_server() -> None:
    command = f1_openworker._opencode_api_command("worker")

    assert command[:3] == ["docker", "exec", "--interactive"]
    assert command[-2] == "-e"
    assert "POST" in command[-1]
    assert "/session/" in command[-1]


def test_prefetch_mode_requires_host_mcp_socket(tmp_path) -> None:
    try:
        openworker_adapter.OpenWorkerProviderAdapter(
            tmp_path / "manifest.json",
            tmp_path / "ledger.jsonl",
            tmp_path / "trace.jsonl",
            memory_mode="prefetch",
        )
    except ValueError as exc:
        assert str(exc) == "prefetch mode requires a host MCP socket"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("prefetch mode accepted no host MCP socket")
