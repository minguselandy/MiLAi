"""Foundation-owned provider injection, explicit recipes and frozen transport parity."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage
from provider_contract_probe import SELECTED, edges_capture, manual_capture
from pydantic import ValidationError

from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers import chat_bridge, langmem_chat
from milai_lab.providers.chat_bridge import VLLMChatModel, _action_schema
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.request_pipeline import ChatRequest, PreparedRequest

LAB = Path(__file__).resolve().parents[2]
GOLDEN = LAB / "data/diagnostics/code-architecture-v12"


def test_old_facade_is_pure_and_exports_generic_same_objects() -> None:
    for name in langmem_chat.__all__:
        assert getattr(langmem_chat, name) is getattr(chat_bridge, name)
    for node in ast.parse((LAB / "src/milai_lab/providers/langmem_chat.py").read_text()).body:
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        elif isinstance(node, ast.ImportFrom):
            assert node.module == "milai_lab.providers.chat_bridge" and node.level == 0
        else:
            assert isinstance(node, ast.Assign)
            assert isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__all__"
            assert isinstance(node.value, ast.List)
            assert all(
                isinstance(item, ast.Constant) and isinstance(item.value, str)
                for item in node.value.elts
            )


@pytest.mark.parametrize(
    "name",
    [
        "observer",
        "m1",
        "odr",
        "projection",
        "request_view",
        "memory_protocol",
        "memory_turn",
        "research_profile",
    ],
)
def test_generic_constructor_rejects_method_fields_explicitly(name: str) -> None:
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock")) as client:
        with pytest.raises(ValidationError) as caught:
            VLLMChatModel(client=client, **{name: "C"})
        assert caught.value.errors()[0]["loc"] == (name,)
        assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_recipe_only_assembles_hooks_and_retains_live_setters() -> None:
    for name in (
        "_generate",
        "_reserve_request",
        "bind_tools",
        "begin_public_message",
        "_llm_type",
    ):
        assert getattr(LangMemRecipeChatModel, name) is getattr(VLLMChatModel, name)
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock")) as client:
        model = LangMemRecipeChatModel(client=client)
        for name in ("m1", "odr", "projection", "request_view", "observer"):
            live = object()
            setattr(model, name, live)
            assert getattr(model, name) is live
        for hook in (model.request_transform, model.delivery_observer, model.response_hook):
            assert hook.model is model
        model.memory_protocol, model.memory_turn, model.research_profile = "B", {}, "current"
        assert model.memory_protocol == "B" and model.memory_turn == {}
        assert model.research_profile == "current"


@pytest.mark.parametrize("fail_http", [False, True])
def test_generic_hooks_run_around_one_accounted_transport(fail_http: bool) -> None:
    events = []
    opaque = object()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "record",
                "description": "Record.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    class Transform:
        def validate(self, request: ChatRequest) -> None:
            events.append("validate")

        def project(self, request: ChatRequest) -> PreparedRequest:
            events.append("project")
            return PreparedRequest(request.messages, request.tools, _action_schema(tools), opaque)

    class Delivery:
        @contextmanager
        def request_scope(self, request: PreparedRequest, request_index: int) -> Any:
            assert request.attachment is opaque and request_index == 1
            events.append("scope_enter")
            try:
                yield
            finally:
                events.append("scope_exit")

        def record_delivery(self, request: PreparedRequest, receipt: Any, index: int) -> None:
            events.append("delivery")

        def after_delivery(self, request: PreparedRequest, index: int) -> None:
            events.append("after_delivery")

    class Response:
        def on_response(self, event: Any) -> None:
            assert event.request.attachment is opaque
            events.append(event.stage)
            if event.stage == "message_metadata":
                event.response_metadata["custom"] = "actual"

    def respond(request: httpx.Request) -> httpx.Response:
        events.append("http")
        return httpx.Response(
            503 if fail_http else 200,
            json={
                "id": "response",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"answer":"done"}'},
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    with VLLMClient(
        VLLMConfig(base_url="http://mock/v1/", model="mock"), transport=httpx.MockTransport(respond)
    ) as client:
        model = VLLMChatModel(
            client=client,
            request_transform=Transform(),
            delivery_observer=Delivery(),
            response_hook=Response(),
        )
        model.begin_public_message("thread:1")
        if fail_http:
            with pytest.raises(httpx.HTTPStatusError):
                model._generate([HumanMessage(content="actual")], tools=tools)
            assert events == ["validate", "project", "scope_enter", "http", "scope_exit"]
        else:
            message = (
                model._generate([HumanMessage(content="actual")], tools=tools)
                .generations[0]
                .message
            )
            assert events == [
                "validate",
                "project",
                "scope_enter",
                "http",
                "delivery",
                "scope_exit",
                "after_delivery",
                "schema_outcome",
                "validated_action",
                "final_action",
                "message_metadata",
                "decoded_message",
            ]
            assert message.response_metadata["custom"] == "actual"
            assert message.usage_metadata == {
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
            }
        assert model.calls_in_message == 1


def test_manual_order_and_edges_match_whole_frozen_contracts() -> None:
    expected = json.loads((GOLDEN / "provider-manual-golden.json").read_text())["contracts"]
    assert manual_capture(LangMemRecipeChatModel) == expected
    expected = json.loads((GOLDEN / "provider-edges-golden.json").read_text())["contracts"]
    assert edges_capture(LangMemRecipeChatModel, LAB) == expected


def test_existing_real_method_assertions_match_whole_frozen_contract() -> None:
    # A fresh process avoids nested fixture patches while replaying the existing graph tests.
    code = (
        "import json,sys,tempfile; from pathlib import Path; "
        f"sys.path.insert(0, {str(LAB / 'tests/architecture')!r}); "
        "from provider_contract_probe import Recorder,SELECTED; import pytest; "
        "from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel; "
        f"lab=Path({str(LAB)!r}); temporary=sys.argv[1]; "
        "recorder=Recorder(LangMemRecipeChatModel,lab/'src',temporary); "
        "args=['-q','--disable-warnings','--basetemp='+temporary+'/pytest']; "
        "args.extend(str(lab/'tests/unit'/file)+'::'+name "
        "for file,names in SELECTED.items() for name in names); "
        "status=pytest.main(args,plugins=[recorder]); "
        "Path(sys.argv[2]).write_text(json.dumps(recorder.cases,ensure_ascii=False)"
        ".replace(temporary,'<TMP>')); assert status==0"
    )
    with tempfile.TemporaryDirectory(prefix="milai-s5-real-test-") as temporary:
        output = Path(temporary) / "contracts.json"
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code, temporary, str(output)],
            cwd=LAB,
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        observed = json.loads(output.read_text())
    expected = json.loads((GOLDEN / "provider-real-golden.json").read_text())["contracts"]
    assert observed == expected
    assert len(observed) == 44
    assert sum(len(names) for names in SELECTED.values()) == 20


def test_normalized_legacy_export_is_canonical_math() -> None:
    from milai_lab.memory.embeddings import normalized
    from milai_lab.methods import reasoning_bank
    from milai_lab.providers import contextual_embeddings

    assert reasoning_bank.normalized is normalized
    assert contextual_embeddings.normalized is normalized
