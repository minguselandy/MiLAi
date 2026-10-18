"""One Host can use explicit JSON schemas and its existing JSON tool protocol."""
import json

import httpx
import pytest

from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


@pytest.mark.parametrize("model_class", [VLLMChatModel, LangMemRecipeChatModel])
def test_schema_call_then_tool_call_then_final_answer(model_class):
    wires = []
    replies = [{"choice": "read_0"},
               {"calls": [{"name": "read_source", "arguments": {"source": "s1"}}]},
               {"answer": "The threshold is 1000."}]

    def respond(request):
        wires.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"reply-{len(wires)}", "choices": [{
            "finish_reason": "stop", "message": {"role": "assistant",
            "content": json.dumps(replies.pop(0))}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    schema = {"type": "json_schema", "json_schema": {"name": "memory_control",
        "schema": {"type": "object", "properties": {"choice": {"enum": ["read_0"]}},
                   "required": ["choice"], "additionalProperties": False}}}
    tool = {"type": "function", "function": {"name": "read_source", "description": "Read source",
        "parameters": {"type": "object", "properties": {"source": {"type": "string"}},
                       "required": ["source"]}}}
    with VLLMClient(VLLMConfig("http://mock/v1", "mock", tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = model_class(client=client)
        selected = model.invoke("Choose an operation", tools=[], response_format=schema)
        called = model.invoke("Read the source", tools=[tool])
        final = model.invoke("Answer from the delivered source", tools=[])
    assert json.loads(selected.content) == {"choice": "read_0"}
    assert called.tool_calls[0]["name"] == "read_source"
    assert called.tool_calls[0]["args"] == {"source": "s1"}
    assert final.content == "The threshold is 1000."
    assert wires[0]["response_format"] == schema
    assert "For a final reply" not in str(wires[0]["messages"])
    assert not any("tools" in wire or "tool_choice" in wire for wire in wires)
    assert wires[2]["response_format"]["json_schema"]["schema"]["required"] == ["answer"]
