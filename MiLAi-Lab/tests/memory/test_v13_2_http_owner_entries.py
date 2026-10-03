from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
import sys
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Annotated, Any

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.store.sqlite import SqliteStore

from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.harness.http_ownership import PROFILE, HttpOwnership, HttpOwnershipError
from milai_lab.integrations.memory.mem0 import _ChatCompletions, _Embeddings
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_baseline_micro as micro
from milai_lab.runners import v13_1_d0 as d0
from milai_lab.runners import v13_1_p5 as p5

LAB = Path(__file__).resolve().parents[2]
ROOT = LAB / "artifacts/v13-2-http-owner-implementation"
ENGINEERING = runpy.run_path(str(LAB / "tests/memory/test_v13_2_read_protocol.py"))


@pytest.fixture(autouse=True)
def portable_frozen_sources(monkeypatch, frozen_pre_http_sources):
    monkeypatch.setitem(globals(), "ROOT", frozen_pre_http_sources)


def proof(path: Path, name: str, value: Any) -> None:
    p = path / name
    assert not p.exists(), p
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def owned_settings(path: Path) -> tuple[Path, Path, dict[str, Any]]:
    fp, cp, settings = ENGINEERING["synthetic_settings"](path)
    settings.update(
        http_ownership_profile=PROFILE,
        http_ownership_domain={
            "deployment_id": "synthetic-complete-domain",
            "clients": [asdict(VLLMConfig(**settings[name])) for name in ("host", "embedding")],
        },
    )
    ledger = read_json(Path(settings["budget_path"]))
    ledger["prior_history"] = [{"actual_synthetic_prior": "retained"}]
    write_json(Path(settings["budget_path"]), ledger)
    write_json(cp, settings)
    return fp, cp, settings


def response(
    body: dict[str, Any],
    number: int,
    *,
    native: bool = False,
    calls: bool = False,
    dimension: int = 2,
) -> dict[str, Any]:
    if "input" in body:
        return {
            "data": [
                {"index": i, "embedding": [1.0] + [0.0] * (dimension - 1)}
                for i, _ in enumerate(body["input"])
            ],
            "usage": {"total_tokens": 3},
        }
    message: dict[str, Any] = {"role": "assistant", "content": "Final remains unchanged"}
    if calls:
        if native:
            message.update(
                content=None,
                tool_calls=[
                    {
                        "id": "synthetic-call",
                        "type": "function",
                        "function": {"name": "echo", "arguments": json.dumps({"value": "x"})},
                    }
                ],
            )
        else:
            message["content"] = json.dumps(
                {"calls": [{"name": "echo", "arguments": {"value": "x"}}]}
            )
    elif not native:
        message["content"] = json.dumps({"answer": "Final remains unchanged"})
    return {
        "id": "synthetic-response-" + str(number),
        "object": "chat.completion",
        "created": 0,
        "model": body["model"],
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if calls and native else "stop",
                "message": message,
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
    }


@pytest.mark.parametrize("runner", [d0, p5])
def test_actual_entry_lease_host_writer_terminal_and_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Any
) -> None:
    fp, cp, settings = owned_settings(tmp_path)
    root = tmp_path / "run"
    wires, lifecycle, budgets = [], [], []
    real_close = HttpOwnership.close

    def closing(owner: HttpOwnership) -> None:
        terminal = (
            list(root.rglob("message-0.json"))
            if runner is d0
            else list(root.rglob("attempt-start.json"))
        )
        lifecycle.append(
            {
                "owner_close": True,
                "terminal_present": bool(terminal),
                "clients": len(owner._clients),
                "ledger": read_json(owner.path),
            }
        )
        real_close(owner)

    monkeypatch.setattr(HttpOwnership, "close", closing)

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        budget = kwargs["budget"]
        budgets.append(budget)

        def transport(request: httpx.Request) -> httpx.Response:
            owner = budget.http_owner
            assert owner is not None and owner.mutex.locked() and not owner.closed
            assert read_json(owner.path) == budget.state
            body = json.loads(request.content)
            wires.append(
                {"url": str(request.url), "body": body, "state_at_dispatch": read_json(owner.path)}
            )
            return httpx.Response(200, json=response(body, len(wires)))

        value = VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))
        old_close = value._client.close

        def http_close() -> None:
            assert budget.http_owner is not None and not budget.http_owner.closed
            lifecycle.append({"http_close": str(value._client.base_url)})
            old_close()

        monkeypatch.setattr(value._client, "close", http_close)
        return value

    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(p5, "VLLMClient", client)
    frozen = runner.prepare(fp, cp, root)
    assert frozen["http_ownership_profile"] == PROFILE
    assert frozen["http_ownership_binding"]["canonical_ledger"] == str(
        Path(settings["budget_path"]).resolve()
    )
    outcome = runner.step(root, "synthetic-entry", 0)
    assert outcome["status"] == "completed", outcome
    assert outcome["final_answer"] == "Final remains unchanged"
    assert outcome["semantic_maintenance"]["generation_calls"] == 1
    assert len({id(b) for b in budgets}) == 1
    assert sum("messages" in w["body"] for w in wires) == 2
    assert lifecycle[-1]["terminal_present"] and lifecycle[-1]["clients"] == 0
    assert read_json(Path(settings["budget_path"]))["prior_history"] == [
        {"actual_synthetic_prior": "retained"}
    ]
    assert outcome["budget"] == read_json(Path(settings["budget_path"]))
    altered = read_json(root / "input-freeze.json")
    altered["http_ownership_domain"]["deployment_id"] = "changed"
    write_json(root / "input-freeze.json", altered)
    with pytest.raises(HttpOwnershipError, match="FROZEN_CHANGED"):
        runner._frozen(root)
    proof(
        tmp_path,
        "actual-entry.json",
        {"frozen": frozen, "wire": wires, "lifecycle": lifecycle, "result": outcome},
    )


def test_p5_actual_unknown_resume_one_new_owner_preserves_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fp, cp, settings = owned_settings(tmp_path)
    root = tmp_path / "resume"
    owners, wires = [], []

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        budget = kwargs["budget"]
        owners.append(budget.http_owner)

        def transport(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            wires.append(body)
            if "messages" in body and sum("messages" in b for b in wires) == 1:
                raise RuntimeError("synthetic transport unknown")
            return httpx.Response(200, json=response(body, len(wires)))

        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(p5, "VLLMClient", client)
    frozen = p5.prepare(fp, cp, root)
    first = p5.step(root, "synthetic-entry", 0, attempt_id="first")
    assert first["status"] == "interrupted" and "synthetic transport unknown" in first["error"]
    first_state = read_json(Path(settings["budget_path"]))
    resumed = p5.step(root, "synthetic-entry", 0, phase="resume", attempt_id="resume")
    assert resumed["status"] == "completed", resumed
    state = read_json(Path(settings["budget_path"]))
    assert first_state["generation"]["unknown_usage"] == state["generation"]["unknown_usage"] == 1
    assert len({id(o) for o in owners}) == 2 and all(o.closed for o in owners)
    proof(
        tmp_path,
        "actual-p5-resume.json",
        {
            "frozen": frozen,
            "first": first,
            "resumed": resumed,
            "wire": wires,
            "first_ledger": first_state,
            "final_ledger": state,
        },
    )


def test_micro_actual_entry_native_callbacks_snapshot_close_and_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fp, cp, settings = owned_settings(tmp_path)
    settings["embedding"]["model"] = "bge-m3"
    settings["embedding_dimension"] = 1024
    settings["reader_system_prompt"] = "Use only the synthetic saved records."
    settings["http_ownership_domain"]["clients"] = [
        asdict(VLLMConfig(**settings[n])) for n in ("host", "embedding")
    ]
    write_json(cp, settings)
    write_json(
        fp,
        {
            "cases": [
                {
                    "case_id": "native",
                    "owner": "owner",
                    "steps": [
                        {
                            "step_id": "archive",
                            "operation": "archive",
                            "records": [{"content": "synthetic leaf"}],
                        },
                        {
                            "step_id": "query",
                            "operation": "search",
                            "query": "synthetic",
                            "reader_question": "read saved",
                        },
                    ],
                }
            ]
        },
    )
    root, wires, lifecycle, owners = tmp_path / "micro", [], [], []

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        owner = kwargs["budget"].http_owner
        owners.append(owner)

        def transport(request: httpx.Request) -> httpx.Response:
            assert owner.mutex.locked()
            body = json.loads(request.content)
            wires.append(body)
            return httpx.Response(200, json=response(body, len(wires), native=True, dimension=1024))

        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    def native_factory(
        backend: str,
        config: Any,
        resource: Any,
        run: Any,
        primary: Any,
        host: VLLMClient,
        embed: VLLMClient,
        admit: Any,
    ) -> Any:
        outer_lock = Lock()
        assert outer_lock is not host.budget.http_owner.mutex
        chat = _ChatCompletions(host, outer_lock, admit)
        embeddings = _Embeddings(embed, outer_lock)

        class Native:
            def add_archive(self, owner: str, records: Any) -> dict[str, Any]:
                chat.create(
                    model=host.config.model,
                    messages=[{"role": "user", "content": "native archive"}],
                    temperature=host.config.temperature,
                    max_tokens=host.config.max_tokens,
                    top_p=1.0,
                )
                embeddings.create(
                    model=embed.config.model, input=["synthetic leaf"], encoding_format="float"
                )
                return {"status": "COMPLETED"}

            def search_archive(self, owner: str, query: str) -> dict[str, Any]:
                embeddings.create(model=embed.config.model, input=[query], encoding_format="float")
                return {"results": self.snapshot(owner)}

            def snapshot(self, owner: str) -> list[dict[str, Any]]:
                assert not host.budget.http_owner.closed
                lifecycle.append("snapshot-before-close")
                return [{"owner": owner, "memory": "synthetic saved leaf"}]

            def close(self) -> None:
                assert not host.budget.http_owner.closed
                lifecycle.append("native-close")

        return Native()

    monkeypatch.setattr(micro, "VLLMClient", client)
    monkeypatch.setattr(micro, "_native_runtime", native_factory)
    # This interpreter has no mem0ai distribution. Freeze an explicitly synthetic
    # dependency for the mock Native only; the existing callbacks remain real.
    monkeypatch.setattr(micro, "_dependency_identity", lambda *args: {"synthetic_native": True})
    frozen = micro.prepare(fp, cp, root, "mem0_oss")
    archive = micro.step(root, "native", "archive")
    query = micro.step(root, "native", "query")
    assert archive["status"] == query["status"] == "COMPLETED", (archive, query)
    assert query["reader_status"] == "COMPLETED"
    assert sum("messages" in w for w in wires) == 2
    assert len({id(o) for o in owners}) == 2 and all(o.closed for o in owners)
    assert lifecycle == [
        "snapshot-before-close",
        "native-close",
        "snapshot-before-close",
        "snapshot-before-close",
        "native-close",
    ]
    assert read_json(Path(settings["budget_path"])) == query["budget_after"]
    proof(
        tmp_path,
        "actual-micro-callbacks.json",
        {
            "scope": "actual entry and existing callbacks; synthetic Native, no SDK quality claim",
            "frozen": frozen,
            "archive": archive,
            "query": query,
            "wire": wires,
            "lifecycle": lifecycle,
        },
    )


def load_base(relative: str, name: str) -> Any:
    path = ROOT / "base-source" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ["native", "json_action"])
@pytest.mark.parametrize("model_class", [VLLMChatModel, LangMemRecipeChatModel])
@pytest.mark.parametrize("explicit_legacy", [False, True])
def test_eight_actual_default_graph_wire_and_receipt_byte_pairs(
    tmp_path: Path, mode: str, model_class: Any, explicit_legacy: bool
) -> None:
    original_budget = load_base(
        "src/milai_lab/harness/contextual_artifacts.py", "synthetic_base_budget"
    )
    original_provider = load_base(
        "src/milai_lab/providers/contextual_vllm.py", "synthetic_base_provider"
    )

    class OriginalClient(original_provider.VLLMClient, VLLMClient):
        pass

    original_provider.VLLMClient = OriginalClient

    @tool
    def echo(value: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
        """Return the exact synthetic value."""
        return ToolMessage(
            content=value, tool_call_id=tool_call_id, id="synthetic-tool-result", name="echo"
        )

    runs = []
    for identity, budget_class, provider in [
        ("base", original_budget.RunBudget, original_provider),
        ("current", RunBudget, sys.modules[VLLMClient.__module__]),
    ]:
        path = tmp_path / identity
        path.mkdir()
        wires, provider_events = [], []
        ledger = path / "ledger.json"
        budget = budget_class(RunLimits(generation_requests=12), ledger)
        write_json(ledger, budget.state)

        def transport(request: httpx.Request, wires: list[Any] = wires) -> httpx.Response:
            body = json.loads(request.content)
            answer = httpx.Response(
                200, json=response(body, len(wires) + 1, native=mode == "native", calls=not wires)
            )
            wires.append(
                {
                    "url": str(request.url),
                    "method": request.method,
                    "body": body,
                    "raw_headers_hex": [
                        [key.hex(), value.hex()] for key, value in request.headers.raw
                    ],
                    "raw_body_utf8": request.content.decode(),
                    "raw_body_hex": request.content.hex(),
                    "raw_body_sha256": hashlib.sha256(request.content).hexdigest(),
                    "raw_response_utf8": answer.content.decode(),
                    "raw_response_hex": answer.content.hex(),
                    "raw_response_sha256": hashlib.sha256(answer.content).hexdigest(),
                }
            )
            return answer

        from milai_lab.harness.contextual_artifacts import http_budget_scope

        legacy_scope = (
            http_budget_scope({"http_ownership_profile": "legacy"})
            if explicit_legacy
            else nullcontext()
        )
        with legacy_scope:
            with (
                provider.VLLMClient(
                    provider.VLLMConfig("http://synthetic/v1", "synthetic", tool_mode=mode),
                    budget=budget,
                    emit=provider_events.append,
                    transport=httpx.MockTransport(transport),
                ) as client,
                SqliteStore.from_conn_string(":memory:") as store,
            ):
                model = model_class(client=client)
                model.begin_public_message("u")
                agent = (
                    create_react_agent(
                        model,
                        [echo],
                        store=store,
                        checkpointer=InMemorySaver(),
                        prompt="Synthetic generic Host.",
                    )
                    if model_class is VLLMChatModel
                    else build_agent(
                        model,
                        business_tools=(echo,),
                        memory_tools=(),
                        store=store,
                        checkpointer=InMemorySaver(),
                        system_prompt="Synthetic generic Host.",
                    )
                )
                result = agent.invoke(
                    {"messages": [HumanMessage("Echo the actual synthetic value", id="u")]},
                    config=FoundationScope("run", "arm", "owner", "s").config(),
                )
        assert len(wires) == 2 and result["messages"][-1].content == "Final remains unchanged"
        messages = [r.model_dump(mode="json") for r in result["messages"]]
        # Scripted provider IDs and the explicit ToolMessage ID keep all original
        # receipt fields byte comparable. Only wall_seconds is excluded from events.
        stable_messages = messages
        capacity = HostCapacity(ENGINEERING["capacity_config"](path))
        costs = [
            {
                "actual_template_prompt_tokens": capacity.count_messages(
                    w["body"]["messages"], w["body"].get("tools")
                ),
                "serialized_complete_http_json_tokens": capacity.text_tokens(
                    json.dumps(w["body"], ensure_ascii=False, separators=(",", ":"))
                ),
            }
            for w in wires
        ]
        events = [
            {k: v for k, v in event.items() if k != "wall_seconds"} for event in provider_events
        ]
        runs.append(
            {
                "wire": wires,
                "events": events,
                "messages": messages,
                "stable_messages": stable_messages,
                "ledger_bytes": ledger.read_text(),
                "costs": costs,
                "source_sha256": {
                    relative: hashlib.sha256(
                        (
                            ROOT / "base-source" / relative
                            if identity == "base"
                            else LAB / relative
                        ).read_bytes()
                    ).hexdigest()
                    for relative in (
                        "src/milai_lab/harness/contextual_artifacts.py",
                        "src/milai_lab/providers/contextual_vllm.py",
                    )
                },
            }
        )
    assert runs[0]["wire"] == runs[1]["wire"]
    assert runs[0]["events"] == runs[1]["events"]
    assert runs[0]["stable_messages"] == runs[1]["stable_messages"]
    assert runs[0]["ledger_bytes"] == runs[1]["ledger_bytes"]
    assert runs[0]["costs"] == runs[1]["costs"]
    proof(
        tmp_path,
        "default-wire-pair.json",
        {
            "mode": mode,
            "model": model_class.__name__,
            "explicit_legacy": explicit_legacy,
            "runs": runs,
        },
    )


@pytest.mark.parametrize("material_profile", ["full_v1", "compact_v1"])
@pytest.mark.local_artifacts
def test_actual_qwen_material_source_prefix_and_owned_wire_cost(
    tmp_path: Path, material_profile: str
) -> None:
    capacity = HostCapacity(ENGINEERING["capacity_config"]())
    with ENGINEERING["opened"](tmp_path) as service:
        ENGINEERING["seeded"](service)
        ENGINEERING["turn"](service)
        recipe = GroundedMemoryRecipe(
            service, capacity.text_tokens, material_profile=material_profile
        )
        state = ENGINEERING["packet"](recipe, budget=2048)
        original_material = state["material"]
        assert state["material_tokens"] == capacity.text_tokens(original_material) <= 2048
        assert len(state["selected"]) <= 6
        units = state["packet"]["items"]
        inventory = state.get("selected_inventory", [])
        coverage = state["packet"]["coverage"]
        source_lengths = [
            {
                "unit_id": u.get("unit_id"),
                "source_ref": u.get("source", {}).get("event_id"),
                "body_codepoints": len(u.get("source", {}).get("content", "")),
                "body_delivery": u.get("body_delivery"),
                "omitted": u.get("omitted"),
            }
            for u in units
        ]
        host = VLLMConfig("http://synthetic/v1", "synthetic", max_tokens=8)
        ledger = tmp_path / "local-pressure-ledger.json"
        old = RunBudget(RunLimits(generation_requests=12), ledger)
        write_json(ledger, old.state)
        settings = {
            "budget_path": str(ledger),
            "http_ownership_profile": PROFILE,
            "http_ownership_domain": {"deployment_id": "synthetic", "clients": [asdict(host)]},
        }
        wires = []
        for selected in ["legacy", PROFILE]:
            from milai_lab.harness.contextual_artifacts import entry_budget, http_budget_scope

            config = {**settings, "http_ownership_profile": selected}
            with http_budget_scope(config):
                budget = entry_budget(old.limits, ledger)

                def transport(request: httpx.Request) -> httpx.Response:
                    body = json.loads(request.content)
                    wires.append(body)
                    return httpx.Response(200, json=response(body, len(wires)))

                with VLLMClient(
                    host, budget=budget, transport=httpx.MockTransport(transport)
                ) as client:
                    client.chat(
                        [
                            {"role": "system", "content": "Synthetic evidence."},
                            {"role": "user", "content": original_material},
                        ]
                    )
        assert wires[0] == wires[1]
        proof(
            tmp_path,
            "qwen-pressure-owned-pair.json",
            {
                "material_profile": material_profile,
                "packet": state["packet"],
                "material": original_material,
                "material_tokens": state["material_tokens"],
                "selected": state["selected"],
                "selected_inventory": inventory,
                "coverage": coverage,
                "source_lengths": source_lengths,
                "wire": wires,
                "counts": {
                    "selected_records": len(state["selected"]),
                    "delivered_units": len(units),
                },
                "prompt_tokens": capacity.count_messages(wires[0]["messages"]),
                "whole_http_json_tokens": capacity.text_tokens(
                    json.dumps(wires[0], ensure_ascii=False)
                ),
                "limit": (
                    "raw Source stress; no new owner metadata in ordinary material, "
                    "no semantic benefit"
                ),
            },
        )


@pytest.mark.parametrize("runner", [d0, p5, micro])
@pytest.mark.parametrize("fault", ["unknown_profile", "actual_dto_outside_domain"])
def test_entry_configuration_rejected_before_ledger_or_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Any, fault: str
) -> None:
    fp, cp, settings = owned_settings(tmp_path)
    if fault == "unknown_profile":
        settings["http_ownership_profile"] = "unsupported"
    else:
        settings["host"]["model"] = "actual-not-declared"
    write_json(cp, settings)
    called = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        called.append(True)
        raise AssertionError("ledger/SDK must not be reached")

    monkeypatch.setattr(HttpOwnership, "_read_disk", forbidden)
    monkeypatch.setattr(runner, "VLLMClient", forbidden)
    with pytest.raises(HttpOwnershipError):
        if runner is micro:
            runner.prepare(fp, cp, tmp_path / "run", "mem0_oss")
        else:
            runner.prepare(fp, cp, tmp_path / "run")
    assert not called
