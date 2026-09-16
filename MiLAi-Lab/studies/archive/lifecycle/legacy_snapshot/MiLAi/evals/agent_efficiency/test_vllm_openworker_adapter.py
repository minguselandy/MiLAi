from __future__ import annotations

import pytest

from evals.agent_efficiency import vllm_openworker_adapter as adapter


def test_upstream_is_exact_existing_vllm_bridge_origin() -> None:
    assert (
        adapter._strict_upstream("http://172.17.0.1:7860") == "http://172.17.0.1:7860"
    )
    for value in (
        "http://127.0.0.1:7860",
        "http://172.17.0.1:7861",
        "https://172.17.0.1:7860",
        "http://172.17.0.1:7860/v1",
        "http://example.invalid:7860",
    ):
        with pytest.raises(adapter.AdapterError):
            adapter._strict_upstream(value)


def test_only_reader_lite_recall_is_recognized() -> None:
    assert adapter._has_milai_recall(
        [
            {
                "type": "function",
                "function": {"name": "milai_recall", "parameters": {}},
            }
        ]
    )
    assert not adapter._has_milai_recall(
        [{"type": "function", "function": {"name": "bash"}}]
    )
    assert (
        adapter._milai_recall_name(
            [{"type": "function", "function": {"name": "milai_milai_recall"}}]
        )
        == "milai_milai_recall"
    )


def test_latest_user_text_is_bounded() -> None:
    assert (
        adapter._latest_user_text([{"role": "user", "content": "synthetic"}])
        == "synthetic"
    )
    assert (
        len(adapter._latest_user_text([{"role": "user", "content": "x" * 4000}]))
        == 2000
    )
    assert (
        adapter._recall_query(
            [
                {
                    "role": "user",
                    "content": "For synthetic subject milaie2e12345678, what is current?",
                }
            ],
            "a verbose query",
        )
        == "milaie2e12345678"
    )


def test_router_schema_exposes_query_only_host_fixed_recall() -> None:
    arguments = adapter._ROUTER_SCHEMA["properties"]["tool_arguments"]
    assert set(arguments["properties"]) == {"query"}
    assert arguments["required"] == ["query"]
    assert arguments["additionalProperties"] is False
