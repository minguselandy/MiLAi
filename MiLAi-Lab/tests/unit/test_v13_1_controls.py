"""Finite controls: MockTransport plus the actual persistent SDK, no semantic scores."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore
from tokenizers import Tokenizer, models, pre_tokenizers, processors
from transformers import PreTrainedTokenizerFast

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


def settings(tmp_path: Path) -> dict[str, Any]:
    tokenizer = Tokenizer(
        models.WordLevel({"[UNK]": 0, "x": 1, "<s>": 2, "</s>": 3}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", special_tokens=[("<s>", 2), ("</s>", 3)]
    )
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    host_path = tmp_path / "host-tokenizer"
    host = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]")
    host.chat_template = (
        "{% for m in messages %}{{ m.role }} {{ m.content }} {% endfor %}"
        "{% if tools %}{{ tools | tojson }}{% endif %} assistant "
    )
    host.save_pretrained(str(host_path))
    (host_path / "chat_template.jinja").write_text(host.chat_template)
    return {
        "host": {"base_url": "http://mock/v1", "model": "same-model", "max_tokens": 64},
        "embedding": {"base_url": "http://mock/v1", "model": "bge-m3"},
        "capacity": {
            "model": "same-model",
            "tokenizer_path": str(host_path),
            "tokenizer_files_sha256": {
                name: hashlib.sha256((host_path / name).read_bytes()).hexdigest()
                for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
            },
            "context_tokens": 32768,
            "output_tokens": 64,
            "batch_source_tokens": 10000,
        },
        "budget_path": str(tmp_path / "budget.json"),
        "embedding_dimension": 2,
        "embedding_batch": 2,
        "embedding_capacity": {
            "tokenizer_path": str(path),
            "tokenizer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "context_tokens": 8192,
        },
        "max_calls_per_message": 12,
        "controls": {
            "material_max_tokens": 6000,
            "raw_rag": {
                "chunk_chars": 2048,
                "chunk_step": 1792,
                "bm25_k1": 1.2,
                "bm25_b": 0.75,
                "rrf_k": 60,
                "top_k": 10,
                "material_max_chars": 16000,
            },
            "summary": {"window_completed_turns": 0, "content_max_chars": 2048, "max_tokens": 64},
        },
        "writer_system_prompt": "Same generic writer.",
        "formation_instruction": "Store useful original past data with the ordinary memory tools.",
        "reader_system_prompt": "Same generic reader, report actual tools.",
        "prompt_only_instruction": "Keep sources and limits; never invent completed results.",
    }


def archive(prefix: str = "a", text: str = "Cobalt Cobalt") -> list[dict[str, Any]]:
    return [
        {
            "event_id": prefix + "u",
            "role": "user",
            "content": text,
            "session_id": "original",
            "timestamp": None,
        },
        {
            "id": prefix + "f",
            "role": "assistant",
            "content": "Observed reply.",
            "session_id": "original",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    ]


class Capacity:
    enable_thinking = False

    def __init__(self, maximum: int = 100000) -> None:
        self.maximum = maximum

    def check(
        self, messages: Any, output_tokens: int | None = None, tools: Any = None
    ) -> dict[str, Any]:
        from milai_lab.providers.contextual_capacity import CapacityExceeded

        count = len(json.dumps(messages)) + len(json.dumps(tools or []))
        if count > self.maximum:
            raise CapacityExceeded({"prompt_tokens": count, "context_tokens": self.maximum})
        return {
            "prompt_tokens": count,
            "output_reserve_tokens": output_tokens or 64,
            "safety_tokens": 0,
        }

    def text_tokens(self, text: str) -> int:
        tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        return len(tokenizer.encode(text, add_special_tokens=False).ids)


def runtime(
    tmp_path: Path, config: dict[str, Any], replies: list[dict[str, Any]]
) -> tuple[Any, Any, list[Any]]:
    from milai_lab.providers.embedding_capacity import MeteredEmbeddings

    wires: list[Any] = []
    budget = RunBudget(RunLimits(1, 1, 100, 10000000, 10000000), Path(config["budget_path"]))

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append((request.url.path, wire))
        if request.url.path.endswith("embeddings"):
            rows = [
                {"index": i, "embedding": [1.0, 0.0] if "Cobalt" in text else [0.0, 1.0]}
                for i, text in enumerate(wire["input"])
            ]
            return httpx.Response(200, json={"data": rows, "usage": {"total_tokens": 4}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(replies.pop(0))},
                    }
                ],
                "usage": {"total_tokens": 6},
            },
        )

    host = VLLMClient(
        VLLMConfig(**config["host"]),
        budget=budget,
        capacity=HostCapacity(config["capacity"]),
        transport=httpx.MockTransport(respond),
    )
    embedding = VLLMClient(
        VLLMConfig(**config["embedding"]), budget=budget, transport=httpx.MockTransport(respond)
    )
    model = LangMemRecipeChatModel(
        client=host,
        capacity_path=tmp_path / "admissions.json",
        max_calls_per_message=config["max_calls_per_message"],
    )
    model.begin_public_message("shared")
    embed = MeteredEmbeddings(
        embedding,
        config["embedding"]["model"],
        config["embedding_capacity"],
        dimension=2,
        batch_size=2,
    )
    return model, embed, wires


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "B3", "B4", "B5", "B6"])
def test_actual_sdk_reopen_scope_capture_and_question_free_formation(
    tmp_path: Path, arm: str
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    replies = (
        [{"summary": "Past summary only."}] if arm == "B3" else [{"answer": "No write needed."}]
    )
    model, embed, wires = runtime(tmp_path, config, replies)
    source = archive()
    path = tmp_path / "store.sqlite"
    with SqliteStore.from_conn_string(
        str(path), index={"dims": 2, "embed": embed, "fields": ["content"]}
    ) as store:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
            backend = ControlsBackend(store, saver, "r", arm, "alice", config, model, embed)
            result = backend.ingest("alice", "closed-1", source)
            assert result["status"] == "COMPLETED"
            before = len(wires)
            assert backend.ingest("alice", "closed-1", source)["status"] == (
                "COMPLETED" if arm == "B0" else "no_change"
            )
            assert len(wires) == before
            with pytest.raises(ValueError, match="OWNER"):
                backend.recall("bob", "Cobalt")
    with SqliteStore.from_conn_string(
        str(path), index={"dims": 2, "embed": embed, "fields": ["content"]}
    ) as store:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
            backend = ControlsBackend(store, saver, "r", arm, "alice", config, model, embed)
            snapshot = backend.snapshot("alice")
            assert snapshot["archive"] == ([] if arm == "B0" else source)
            selected = backend.recall("alice", "Cobalt")
            if arm == "B1":
                assert (
                    json.loads(selected["material"].split("\n", 1)[1])["original_records"] == source
                )
    for _, wire in wires:
        assert "FUTURE_READER_QUESTION" not in json.dumps(wire)
    assert model.client.budget.state["generation_requests"] == (
        1 if arm in {"B3", "B4", "B5"} else 0
    )


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "B3", "B4", "B5", "B6"])
def test_static_archive_edges_preserved_with_real_sdk_reopen_and_original_wires(
    tmp_path: Path, arm: str
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    config["controls"]["summary"]["window_completed_turns"] = 1
    replies = (
        [{"summary": "First closed past only."}]
        if arm == "B3"
        else [{"answer": "No write needed."}] * 4
    )
    model, embed, wires = runtime(tmp_path, config, replies)
    leading = {
        "id": "original-leading",
        "role": "assistant",
        "content": "Cobalt original leading reply.",
        "timestamp": None,
        "session_id": "original",
    }
    trailing = {
        "event_id": "original-trailing",
        "role": "user",
        "content": "Original trailing user fragment.",
        "timestamp": "2026-01-01T00:03:00Z",
        "session_id": "original",
    }
    first, recent = archive("first", "First closed past."), archive("recent", "Recent past.")
    source = [leading, *first, *recent, trailing]
    original_bytes = json.dumps(source, ensure_ascii=False)
    store_path, saver_path = tmp_path / "store.sqlite", tmp_path / "checkpoint.sqlite"
    with (
        SqliteStore.from_conn_string(str(store_path)) as store,
        SqliteSaver.from_conn_string(str(saver_path)) as saver,
    ):
        backend = ControlsBackend(store, saver, "r", arm, "alice", config, model, embed)
        for index, row in enumerate((leading, trailing)):
            with pytest.raises(ValueError, match="UNCLOSED_EVENT_BOUNDARY"):
                backend.ingest("alice", f"default-edge-{index}", [row])
        assert not wires and backend.snapshot("alice")["archive"] == []
        with pytest.raises(ValueError, match="OWNER_SCOPE_MISMATCH"):
            backend.ingest_archive("bob", "leading", [leading])
        backend.ingest_archive("alice", "leading", [leading])
        backend.ingest("alice", "first", first)
        backend.ingest("alice", "recent", recent)
        backend.ingest_archive("alice", "trailing", [trailing])
        count = len(wires)
        replay = backend.ingest_archive("alice", "leading", [leading])
        assert replay["status"] == ("COMPLETED" if arm == "B0" else "no_change")
        assert len(wires) == count
        if arm != "B0":
            with pytest.raises(ValueError, match="ORIGINAL_EVENT_CHANGED"):
                backend.ingest_archive("alice", "changed", [{**trailing, "content": "Changed."}])
        assert json.dumps(source, ensure_ascii=False) == original_bytes
    with (
        SqliteStore.from_conn_string(str(store_path)) as store,
        SqliteSaver.from_conn_string(str(saver_path)) as saver,
    ):
        backend = ControlsBackend(store, saver, "r", arm, "alice", config, model, embed)
        assert backend.snapshot("alice")["archive"] == ([] if arm == "B0" else source)
        result = backend.recall("alice", "CURRENT_READER_QUESTION")
        if arm == "B0":
            assert result["material"] == "" and not store.search(("v13_1_controls",))
        if arm == "B1":
            assert json.loads(result["material"].split("\n", 1)[1])["original_records"] == source
        if arm == "B2":
            chunks = json.loads(result["material"].split("\n", 1)[1])
            assert {chunk["source_id"] for chunk in chunks} == {
                row.get("event_id", row.get("id")) for row in source
            }
            assert sorted(
                (json.loads(chunk["content"]) for chunk in chunks), key=lambda r: r["content"]
            ) == sorted(source, key=lambda r: r["content"])
        if arm == "B3":
            material = json.loads(result["material"].split("\n", 1)[1])
            assert material["model_generated_summary"] == "First closed past only."
            assert material["recent_original_records"] == [leading, *recent, trailing]
            assert result["delivered_ids"] == [
                "original-leading",
                "recentu",
                "recentf",
                "original-trailing",
            ]
    generation = [wire for path, wire in wires if path.endswith("chat/completions")]
    if arm == "B3":
        assert len(generation) == 1
        payload = json.loads(generation[0]["messages"][1]["content"])
        assert payload["new_completed_turns"][0]["messages"] == first
        assert payload["new_completed_turns"][0]["source_ids"] == ["firstu", "firstf"]
        assert all(row["content"] not in json.dumps(generation) for row in (leading, trailing))
    if arm in {"B4", "B5"}:
        delivered = [
            json.loads(wire["messages"][1]["content"].split("[Archived conversation data]\n", 1)[1])
            for wire in generation
        ]
        assert delivered == [[leading], first, recent, [trailing]]
    assert all("CURRENT_READER_QUESTION" not in json.dumps(wire) for wire in generation)
    assert model.client.budget.state["generation_requests"] == (
        1 if arm == "B3" else 4 if arm in {"B4", "B5"} else 0
    )


def test_archive_pending_tool_calls_are_not_summary_closed_turns(tmp_path: Path) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    model, embed, wires = runtime(tmp_path, config, [{"summary": "Completed past only."}])
    first = archive("first", "Completed original past.")
    pending = [
        {"id": "pending-user", "role": "user", "content": "Past pending request."},
        {
            "id": "pending-assistant",
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "original-call", "name": "lookup", "args": {}}],
        },
        {
            "id": "pending-tool",
            "role": "tool",
            "tool_call_id": "original-call",
            "content": "Actual public observation.",
        },
        {
            "id": "pending-next-call",
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "original-next", "name": "lookup", "args": {}}],
        },
    ]
    path = tmp_path / "store.sqlite"
    with (
        SqliteStore.from_conn_string(str(path)) as store,
        SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B3", "alice", config, model, embed)
        backend.ingest("alice", "first", first)
        with pytest.raises(ValueError, match="UNCLOSED_EVENT_BOUNDARY"):
            backend.ingest("alice", "pending-default", pending)
        backend.ingest_archive("alice", "pending-archive", pending)
    with (
        SqliteStore.from_conn_string(str(path)) as store,
        SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B3", "alice", config, model, embed)
        state = backend.snapshot("alice")
        assert state["archive"] == [*first, *pending] and state["covered_ordinal"] == 0
        material = json.loads(
            backend.recall("alice", "CURRENT_QUESTION")["material"].split("\n", 1)[1]
        )
        assert material["recent_original_records"] == pending
    assert len(wires) == 1
    assert (
        json.loads(wires[0][1]["messages"][1]["content"])["new_completed_turns"][0]["messages"]
        == first
    )
    assert model.client.budget.state["generation_requests"] == 1


def test_finite_lifecycle_quality_profile_shared_writer_reader_admission_reopens(
    tmp_path: Path,
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend, validate_config

    config = settings(tmp_path)
    for invalid in (
        {"max_calls_per_message": 24},
        {"generation_cap_profile": "lifecycle_quality_24_v1", "max_calls_per_message": 25},
        {"generation_cap_profile": "unlimited", "max_calls_per_message": 24},
    ):
        with pytest.raises(ValueError, match="GENERATION_CAP"):
            validate_config({**config, **invalid})
    config.update(generation_cap_profile="lifecycle_quality_24_v1", max_calls_per_message=24)
    model, embed, wires = runtime(tmp_path, config, [{"answer": "Original writer result."}] * 13)
    store_path, saver_path = tmp_path / "store.sqlite", tmp_path / "checkpoint.sqlite"
    with (
        SqliteStore.from_conn_string(str(store_path)) as store,
        SqliteSaver.from_conn_string(str(saver_path)) as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B4", "alice", config, model, embed)
        backend.ingest("alice", "past", archive())
        for _ in range(12):
            backend.read_text("alice", "Current question")
        assert (
            model.calls_in_message == 13 and model.client.budget.state["generation_requests"] == 13
        )
    model.client.close()
    reopened, embed2, wires2 = runtime(
        tmp_path, config, [{"answer": "Original reader result."}] * 11
    )
    with (
        SqliteStore.from_conn_string(str(store_path)) as store,
        SqliteSaver.from_conn_string(str(saver_path)) as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B4", "alice", config, reopened, embed2)
        assert reopened.calls_in_message == 13
        for _ in range(11):
            backend.read_text("alice", "Current question")
        assert reopened.calls_in_message == 24
        with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
            backend.read_text("alice", "Current question")
        with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
            backend.ingest("alice", "next-past", archive("next"))
        assert (
            backend.snapshot("alice")["boundaries"]["next-past"]["status"]
            == "MAINTENANCE_INCOMPLETE"
        )
        assert reopened.client.budget.state["generation_requests"] == 24
    assert len(wires) + len(wires2) == 24


def test_embedding_overcapacity_rejects_before_any_mock_http_even_with_tokenizer_truncation(
    tmp_path: Path,
) -> None:
    config = settings(tmp_path)
    model, embed, wires = runtime(tmp_path, config, [])
    embed.capacity.tokenizer.enable_truncation(2)
    with pytest.raises(ValueError, match="EMBEDDING_CONTEXT_CAPACITY_EXCEEDED"):
        embed.embed_documents(["x " * 8193])
    assert wires == [] and model.client.budget.state["embedding"]["charged_tokens"] == 0


def test_full_history_explicit_capacity_does_not_truncate_or_dispatch(tmp_path: Path) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend
    from milai_lab.providers.contextual_capacity import CapacityExceeded

    config = settings(tmp_path)
    model, embed, wires = runtime(tmp_path, config, [])
    with (
        SqliteStore.from_conn_string(":memory:") as store,
        SqliteSaver.from_conn_string(":memory:") as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B1", "alice", config, model, embed)
        backend.ingest("alice", "closed", archive(text="x" * 2000))
        model.client.capacity = Capacity(200)
        with pytest.raises(CapacityExceeded):
            backend.read_text("alice", "FUTURE_READER_QUESTION")
        assert wires == [] and len(backend.snapshot("alice")["archive"][0]["content"]) == 2000


def test_b6_keeps_original_unknown_separate_from_real_query_and_observation_history(
    tmp_path: Path,
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    model, embed, _ = runtime(tmp_path, config, [])
    original = archive()
    original.insert(
        1,
        {
            "event_id": "receipt-1",
            "role": "tool",
            "name": "reserve_and_label",
            "tool_call_id": "real-call",
            "content": json.dumps(
                {
                    "status": "reserved_label_failed",
                    "label_status": "not_created",
                    "reservation_id": "actual-r",
                    "item_key": "Cobalt",
                }
            ),
        },
    )
    original.insert(
        2,
        {
            "event_id": "unknown",
            "role": "tool",
            "name": "complete_label",
            "tool_call_id": "lost",
            "content": json.dumps(
                {
                    "status": "ORIGINAL_CALL_OUTCOME_UNKNOWN",
                    "original_receipt": None,
                    "original_journal_key": "original-key",
                    "query_receipt": json.dumps({"status": "found", "label_status": "created"}),
                }
            ),
        },
    )
    original.insert(
        3,
        {
            "event_id": "real-query",
            "role": "tool",
            "name": "get_reservation",
            "tool_call_id": "actual-query",
            "content": json.dumps(
                {
                    "status": "found",
                    "label_status": "created",
                    "reservation_id": "actual-r",
                    "item_key": "Cobalt",
                }
            ),
        },
    )
    with (
        SqliteStore.from_conn_string(":memory:") as store,
        SqliteSaver.from_conn_string(":memory:") as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B6", "alice", config, model, embed)
        backend.ingest("alice", "closed", original)
        projection = backend.snapshot("alice")["projection"]
        assert projection["unknown"][0]["original_record"] == original[2]
        history = projection["objects"]["actual-r"]["history"]
        assert [row["source_id"] for row in history] == ["receipt-1", "real-query"]
        assert history[0]["fields"]["label_status"] == "not_created"
        assert history[1]["fields"]["label_status"] == "created"
        assert projection["objects"]["actual-r"]["latest_observation"] == history[-1]
        assert backend.snapshot("alice")["archive"] == original


def test_reader_current_question_is_absent_from_writer_and_b5_only_adds_prompt(
    tmp_path: Path,
) -> None:
    from langchain_core.tools import tool

    from milai_lab.baselines.v13_1_controls import ControlsBackend
    from milai_lab.contracts.scope import FoundationScope

    prompts, text_readers, agent_readers = [], [], []

    @tool
    def lookup(key: str) -> str:
        """Public read-only lookup."""
        return key

    for arm in ("B4", "B5"):
        path = tmp_path / arm
        path.mkdir()
        config = settings(path)
        model, embed, wires = runtime(
            path,
            config,
            [{"answer": "No write."}, {"answer": "Reader."}, {"answer": "Agent reader."}],
        )
        with (
            SqliteStore.from_conn_string(":memory:") as store,
            SqliteSaver.from_conn_string(":memory:") as saver,
        ):
            backend = ControlsBackend(store, saver, "r", arm, "alice", config, model, embed)
            backend.ingest("alice", "closed", archive())
            writer_wire = json.dumps(wires[0][1])
            assert "FUTURE_READER_QUESTION" not in writer_wire
            prompts.append(wires[0][1]["messages"][0]["content"])
            backend.read_text("alice", "FUTURE_READER_QUESTION")
            assert "FUTURE_READER_QUESTION" in json.dumps(wires[-1][1])
            text_readers.append(wires[-1][1]["messages"])
            agent = backend.reader_agent(
                business_tools=[lookup], environment_rules="Same environment."
            )
            agent.invoke(
                {"messages": [HumanMessage(content="FUTURE_READER_QUESTION", id="now")]},
                config=FoundationScope("r", arm, "alice", "reader").config(),
                durability="sync",
            )
            agent_readers.append(wires[-1][1]["messages"])
            assert model.calls_in_message == 3
    assert prompts[1] == prompts[0] + "\n" + config["prompt_only_instruction"]
    assert text_readers[0] == text_readers[1] and agent_readers[0] == agent_readers[1]
    assert config["prompt_only_instruction"] not in json.dumps(text_readers + agent_readers)


def test_prepare_is_zero_http_and_freezes_actual_policies_prompts_and_sources(
    tmp_path: Path,
) -> None:
    from milai_lab.runners import v13_1_controls as runner

    config = settings(tmp_path)
    budget = RunBudget(RunLimits(1, 1, 100, 10000000, 10000000), Path(config["budget_path"]))
    budget.reserve("chat/completions", {"messages": [], "max_tokens": 1})
    write_json(tmp_path / "config.json", config)
    frozen = runner.prepare(tmp_path / "config.json", tmp_path / "run", "r", "B2", "alice")
    assert frozen["config"] == config
    assert "tools/run_v13_1_controls.py" in frozen["source_sha256"]
    assert frozen["embedding_capacity"]["context_tokens"] == 8192
    assert read_json(Path(config["budget_path"])) == budget.state


def test_embedding_special_tokens_all_inputs_and_dimension_failure_are_accounted(
    tmp_path: Path,
) -> None:
    from milai_lab.providers.embedding_capacity import EmbeddingCapacity, MeteredEmbeddings

    config = settings(tmp_path)
    model, embed, wires = runtime(tmp_path, config, [])
    assert embed.capacity.check(["x " * 8190]) == [8192]
    # Generic capacity follows the supplied model limit, while this BGE config
    # remains 8192. No chat template or truncation participates in admission.
    larger = EmbeddingCapacity({**config["embedding_capacity"], "context_tokens": 10000})
    assert larger.check(["x " * 8193]) == [8195]
    with pytest.raises(ValueError, match="EMBEDDING_CONTEXT_LIMIT_INVALID"):
        EmbeddingCapacity({**config["embedding_capacity"], "context_tokens": 0})
    with pytest.raises(ValueError, match="EMBEDDING_CONTEXT_CAPACITY_EXCEEDED"):
        embed.embed_documents(["x", "x " * 8191])
    assert not wires
    assert embed.embed_query("x") == [0.0, 1.0]
    assert model.client.budget.state["embedding"]["charged_tokens"] == 4
    bad = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1, 0, 0]}], "usage": {"total_tokens": 9}}
        )
    )
    with VLLMClient(
        VLLMConfig(**config["embedding"]), budget=model.client.budget, transport=bad
    ) as client:
        embed.client = client
        with pytest.raises(ValueError, match="EMBEDDING_CONTRACT_MISMATCH"):
            embed.embed_query("x")
    assert model.client.budget.state["embedding"]["charged_tokens"] == 13
    assert model.client.budget.state["embedding"]["unknown_usage"] == 0
    correct = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [1.0, *([0.0] * 1023)]}],
                "usage": {"total_tokens": 3},
            },
        )
    )
    with VLLMClient(
        VLLMConfig(**config["embedding"]), budget=model.client.budget, transport=correct
    ) as client:
        bge_shape = MeteredEmbeddings(
            client, "bge-m3", config["embedding_capacity"], dimension=1024, batch_size=16
        )
        assert len(bge_shape.embed_query("x")) == 1024
    assert model.client.budget.state["embedding"]["charged_tokens"] == 16


def test_full_history_actual_material_tokens_closed_boundary_and_immutable_id(
    tmp_path: Path,
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    config["controls"]["material_max_tokens"] = 100
    model, embed, wires = runtime(tmp_path, config, [])
    source = archive(text="x " * 120)
    with (
        SqliteStore.from_conn_string(":memory:") as store,
        SqliteSaver.from_conn_string(":memory:") as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B1", "alice", config, model, embed)
        with pytest.raises(ValueError, match="UNCLOSED_EVENT_BOUNDARY"):
            backend.ingest("alice", "unclosed", source[:1])
        pending = [source[0], {**source[1], "tool_calls": [{"name": "unfinished"}]}]
        with pytest.raises(ValueError, match="UNCLOSED_EVENT_BOUNDARY"):
            backend.ingest("alice", "pending", pending)
        backend.ingest("alice", "closed", source)
        assert len(json.dumps(source)) < config["controls"]["raw_rag"]["material_max_chars"]
        with pytest.raises(ValueError, match="MATERIAL_CAPACITY_EXCEEDED"):
            backend.recall("alice", "x")
        with pytest.raises(ValueError, match="ORIGINAL_EVENT_CHANGED"):
            backend.ingest("alice", "new-boundary", archive(text="Changed same original ID."))
        assert backend.snapshot("alice")["archive"] == source and not wires


def test_b2_bm25_and_real_mock_dense_both_contribute_not_dense_renamed(tmp_path: Path) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    model, embed, wires = runtime(tmp_path, config, [])
    dense_inputs = []

    def dense_response(request: httpx.Request) -> httpx.Response:
        value = json.loads(request.read())
        dense_inputs.extend(value["input"])
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "index": i,
                        "embedding": [1, 0]
                        if text in {"needle", "semantic-only"} or "Cobalt" in text
                        else [0, 1],
                    }
                    for i, text in enumerate(value["input"])
                ],
                "usage": {"total_tokens": 4},
            },
        )

    with VLLMClient(
        VLLMConfig(**config["embedding"]),
        budget=model.client.budget,
        transport=httpx.MockTransport(dense_response),
    ) as client:
        embed.client = client
        with (
            SqliteStore.from_conn_string(":memory:") as store,
            SqliteSaver.from_conn_string(":memory:") as saver,
        ):
            backend = ControlsBackend(store, saver, "r", "B2", "alice", config, model, embed)
            backend.ingest("alice", "a", archive("a", "needle needle needle"))
            backend.ingest("alice", "b", archive("b", "Cobalt only"))
            lexical = json.loads(backend.recall("alice", "needle")["material"].split("\n", 1)[1])
            semantic = json.loads(
                backend.recall("alice", "semantic-only")["material"].split("\n", 1)[1]
            )
            assert lexical[0]["source_id"] == "au"  # Lexical evidence beats dense-only first place.
            assert semantic[0]["source_id"] == "bu"  # Dense evidence works with no lexical hit.
            assert backend.snapshot("alice")["archive"] == archive(
                "a", "needle needle needle"
            ) + archive("b", "Cobalt only")
    assert dense_inputs[-2:] == ["needle", "semantic-only"]
    assert not wires and model.client.budget.state["embedding"]["charged_tokens"] == 16


@pytest.mark.parametrize("size,step", [(1024, 896), (2048, 1792)])
def test_b2_configured_original_chunk_spans_preserve_lossless_rows(
    tmp_path: Path, size: int, step: int
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    config["controls"]["raw_rag"].update(chunk_chars=size, chunk_step=step)
    model, embed, wires = runtime(tmp_path, config, [])
    source = archive(text="Cobalt " * 500)
    with (
        SqliteStore.from_conn_string(":memory:") as store,
        SqliteSaver.from_conn_string(":memory:") as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B2", "alice", config, model, embed)
        backend.ingest("alice", "closed", source)
        chunks = backend.snapshot("alice")["index"]["chunks"]
        for row in source:
            identity = row.get("event_id", row.get("id"))
            spans = [c for c in chunks if c["source_id"] == identity]
            original = json.dumps(row, ensure_ascii=False)
            reconstructed, covered = "", 0
            for chunk in spans:
                assert (
                    chunk["start"] <= covered
                    and chunk["content"] == original[chunk["start"] : chunk["end"]]
                )
                reconstructed += chunk["content"][covered - chunk["start"] :]
                covered = chunk["end"]
            assert reconstructed == original
        assert max(len(c["content"]) for c in chunks) == size
        assert [c["start"] for c in chunks if c["source_id"] == "au"][1] == step
    assert [
        text for path, wire in wires if path.endswith("embeddings") for text in wire["input"]
    ] == [c["content"] for c in chunks]


@pytest.mark.parametrize("maximum,chars", [(1536, 6000), (3072, 12000)])
def test_b3_configured_window_summary_output_and_prior_only_wire(
    tmp_path: Path, maximum: int, chars: int
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    config["controls"]["summary"].update(
        window_completed_turns=2, content_max_chars=chars, max_tokens=maximum
    )
    model, embed, wires = runtime(
        tmp_path, config, [{"summary": "First past."}, {"summary": "Two past."}]
    )
    with (
        SqliteStore.from_conn_string(":memory:") as store,
        SqliteSaver.from_conn_string(":memory:") as saver,
    ):
        backend = ControlsBackend(store, saver, "r", "B3", "alice", config, model, embed)
        backend.ingest("alice", "a", archive("a", "A original"))
        backend.ingest("alice", "b", archive("b", "B original"))
        assert not wires
        backend.ingest("alice", "c", archive("c", "C original"))
        backend.ingest("alice", "d", archive("d", "D original"))
        first, second = [json.loads(wire["messages"][1]["content"]) for _, wire in wires]
        assert first["prior_summary"] == "" and first["new_completed_turns"][0][
            "messages"
        ] == archive("a", "A original")
        assert second["prior_summary"] == "First past." and second["new_completed_turns"][0][
            "messages"
        ] == archive("b", "B original")
        for _, wire in wires:
            assert wire["max_tokens"] == maximum
            assert (
                wire["response_format"]["json_schema"]["schema"]["properties"]["summary"][
                    "maxLength"
                ]
                == chars
            )
            assert "C original" not in json.dumps(wire) and "D original" not in json.dumps(wire)
        material = json.loads(
            backend.recall("alice", "CURRENT_QUESTION")["material"].split("\n", 1)[1]
        )
        assert material["recent_original_records"] == archive("c", "C original") + archive(
            "d", "D original"
        )
        assert material["model_generated_summary"] == "Two past."
        assert model.client.config.max_tokens == config["host"]["max_tokens"]
    assert model.calls_in_message == 2 and model.client.budget.state["generation_requests"] == 2


def test_ordinary_failure_after_actual_commit_keeps_original_raw_proposal_history(
    tmp_path: Path,
) -> None:
    from milai_lab.baselines.v13_1_controls import ControlsBackend

    config = settings(tmp_path)
    config["max_calls_per_message"] = 1
    proposal = {
        "calls": [
            {
                "name": "manage_memory",
                "arguments": {"action": "create", "content": "Cobalt unchecked prose."},
            }
        ]
    }
    model, embed, wires = runtime(tmp_path, config, [proposal])
    with SqliteStore.from_conn_string(
        str(tmp_path / "store.sqlite"), index={"dims": 2, "embed": embed, "fields": ["content"]}
    ) as store:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            backend = ControlsBackend(store, saver, "r", "B4", "alice", config, model, embed)
            with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
                backend.ingest("alice", "closed", archive())
            snapshot = backend.snapshot("alice")
            boundary = snapshot["boundaries"]["closed"]
            assert (
                snapshot["archive"] == archive() and boundary["status"] == "MAINTENANCE_INCOMPLETE"
            )
            assert snapshot["records"][0]["value"] == {"content": "Cobalt unchecked prose."}
            assert any(row.get("tool_calls") for row in boundary["writer_messages"])
            assert any(
                row["type"] == "tool" and json.loads(row["content"])["status"] == "created"
                for row in boundary["writer_messages"]
            )
            before = len(wires)
            assert (
                backend.ingest("alice", "closed", archive())["status"] == "MAINTENANCE_INCOMPLETE"
            )
            assert len(wires) == before
            with pytest.raises(ValueError, match="MAINTENANCE_INCOMPLETE"):
                backend.recall("alice", "Cobalt")
    assert model.client.budget.state["generation_requests"] == 1


@pytest.mark.parametrize("arm", ["B0", "B2"])
def test_native_merit_factory_callback_current_human_and_same_public_tool_wrapper(
    tmp_path: Path, arm: str
) -> None:
    from langchain_core.tools import tool

    from milai_lab.baselines.v13_1_controls import ControlsBackend, merit_adapters
    from milai_lab.contracts.scope import FoundationScope

    config = settings(tmp_path)
    model, embed, wires = runtime(
        tmp_path,
        config,
        [
            {"calls": [{"name": "lookup", "arguments": {"key": "Past"}}]},
            {"answer": "Original past answer."},
            {"calls": [{"name": "lookup", "arguments": {"key": "Cobalt"}}]},
            {"answer": "Actual reply."},
            {"answer": "New episode reply."},
        ],
    )
    seen = []

    @tool
    def lookup(key: str) -> str:
        """Public read-only lookup."""
        seen.append(key)
        return json.dumps({"status": "found", "original_key": key})

    guarded = []

    def wrapper(request: Any, execute: Any) -> Any:
        guarded.append(request.tool_call)
        return execute(request)

    with SqliteStore.from_conn_string(
        ":memory:", index={"dims": 2, "embed": embed, "fields": ["content"]}
    ) as store:
        with SqliteSaver.from_conn_string(":memory:") as saver:
            backend = ControlsBackend(store, saver, "r", arm, "alice", config, model, embed)
            backend.ingest("alice", "past", archive())
            factory, completed = merit_adapters(None, "r", arm, config, embed)
            agent = factory(
                model,
                store,
                saver,
                [lookup],
                user_id="alice",
                environment_rules="Original environment rules.",
                business_call_wrapper=wrapper,
            )
            scope = FoundationScope("r", arm, "alice", "native")
            model.begin_public_message("native:0")
            agent.invoke(
                {"messages": [HumanMessage(content="OLD_QUESTION", id="old")]},
                config=scope.config(),
                durability="sync",
            )
            completed(agent, scope, 0, "COMPLETED", [])
            model.begin_public_message("native:1")
            start = len(wires)
            result = agent.invoke(
                {"messages": [HumanMessage(content="CURRENT_QUESTION", id="now")]},
                config=scope.config(),
                durability="sync",
            )
            assert result["messages"][-1].content == "Actual reply."
            assert seen == ["Past", "Cobalt"] and guarded[-1]["args"] == {"key": "Cobalt"}
            current = wires[start:]
            generation = [wire for path, wire in current if path.endswith("chat/completions")]
            assert all("OLD_QUESTION" in json.dumps(wire) for wire in generation)
            assert all("Original past answer." in json.dumps(wire) for wire in generation)
            assert all(
                json.dumps({"status": "found", "original_key": "Past"})
                in [message["content"] for message in wire["messages"]]
                for wire in generation
            )
            assert "lookup" in generation[0]["messages"][0]["content"]
            assert "manage_memory" not in generation[0]["messages"][0]["content"]
            assert "Original environment rules." in generation[0]["messages"][0]["content"]
            if arm == "B2":
                assert next(
                    wire["input"] for path, wire in current if path.endswith("embeddings")
                ) == ["CURRENT_QUESTION"]
            completed(agent, scope, 1, "COMPLETED", [])
            snapshot = backend.snapshot("alice")
            if arm == "B0":
                assert snapshot["archive"] == [] and not store.search(("v13_1_controls",))
            else:
                original_tool = next(
                    row
                    for row in snapshot["archive"]
                    if row["role"] == "tool" and "Cobalt" in row["content"]
                )
                assert original_tool["content"] == json.dumps(
                    {"status": "found", "original_key": "Cobalt"}
                )
                assert original_tool["tool_call_id"] == guarded[-1]["id"]
            fresh = FoundationScope("r", arm, "alice", "new-episode")
            assert not agent.get_state(fresh.config()).values
            model.begin_public_message("new-episode:0")
            agent.invoke(
                {"messages": [HumanMessage(content="NEW_EPISODE_QUESTION", id="fresh")]},
                config=fresh.config(),
                durability="sync",
            )
            if arm == "B0":
                assert "OLD_QUESTION" not in json.dumps(wires[-1][1])
                assert "CURRENT_QUESTION" not in json.dumps(wires[-1][1])
                assert "Past" not in json.dumps(wires[-1][1])
    assert model.calls_in_message == 1


CHILD = r"""
import json,sys
from pathlib import Path
import httpx
from milai_lab.runners.v13_1_controls import operation
from milai_lab.harness.artifact_io import read_json
root=Path(sys.argv[1]); mode=sys.argv[2]
responses=[{"calls":[{"name":"manage_memory","arguments":{
    "action":"create","content":"Cobalt original NL card."}}]},
    {"answer":"Stored."}] if mode=="writer" else []
def respond(request):
    wire=json.loads(request.read())
    if request.url.path.endswith("embeddings"):
        return httpx.Response(200,json={"data":[{"index":i,"embedding":[1,0]}
            for i in range(len(wire["input"]))],"usage":{"total_tokens":2}})
    content=json.dumps(responses.pop(0)) if responses else "Common reader reply."
    return httpx.Response(200,json={"choices":[{"finish_reason":"stop",
        "message":{"role":"assistant","content":content}}],"usage":{"total_tokens":3}})
transport=httpx.MockTransport(respond)
if mode=="writer":
    rows=[operation(root,"writer","ingest",read_json(Path(sys.argv[3])),"boundary",host_transport=transport,embedding_transport=transport)]
else:
    key="next-boundary" if mode=="new" else "boundary"
    count=1 if mode=="new" else 11
    rows=[operation(root,mode+str(i),"read",{"owner":"alice","question":"CURRENT_QUESTION"},
        key,host_transport=transport,embedding_transport=transport) for i in range(count)]
print(json.dumps(rows))
"""


def test_real_process_reopen_shared_writer_reader_twelve_and_new_boundary(tmp_path: Path) -> None:
    from milai_lab.runners.v13_1_controls import LAB, prepare

    config = settings(tmp_path)
    budget = RunBudget(RunLimits(1, 1, 100, 10000000, 10000000), Path(config["budget_path"]))
    # The runner requires an existing ledger. Seeding writes only the test ledger.
    write_json(Path(config["budget_path"]), budget.state)
    write_json(tmp_path / "config.json", config)
    run = tmp_path / "run"
    prepare(tmp_path / "config.json", run, "r", "B4", "alice")
    write_json(
        tmp_path / "archive.json", {"owner": "alice", "boundary_id": "closed", "records": archive()}
    )

    def child(mode: str) -> list[Any]:
        result = subprocess.run(  # noqa: S603 - fixed code, own interpreter, temporary resources
            [sys.executable, "-c", CHILD, str(run), mode, str(tmp_path / "archive.json")],
            env={**os.environ, "PYTHONPATH": str(LAB / "src")},
            capture_output=True,
            text=True,
            cwd=LAB,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    writer, readers, fresh = child("writer"), child("reader"), child("new")
    assert writer[0]["status"] == "COMPLETED"
    assert [row["status"] for row in readers] == ["COMPLETED"] * 10 + ["MAINTENANCE_INCOMPLETE"]
    assert readers[-1]["generation_admissions_for_boundary"] == 12
    assert readers[-1]["budget_after"]["generation_requests"] == 12
    assert fresh[0]["status"] == "COMPLETED" and fresh[0]["generation_admissions_for_boundary"] == 1
    assert fresh[0]["budget_after"]["generation_requests"] == 13
    assert fresh[0]["snapshot_after"]["archive"] == archive()
    assert fresh[0]["snapshot_after"]["records"][0]["value"] == {
        "content": "Cobalt original NL card."
    }
    assert len({writer[0]["process_id"], readers[0]["process_id"], fresh[0]["process_id"]}) == 3
    assert read_json(run / "first-error.json")["operation_id"] == "reader10"


def test_setup_failure_terminal_first_error_and_freeze_drift_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from milai_lab.runners import v13_1_controls as runner

    config = settings(tmp_path)
    budget = RunBudget(RunLimits(1, 1, 100, 10000000, 10000000), Path(config["budget_path"]))
    write_json(Path(config["budget_path"]), budget.state)
    write_json(tmp_path / "config.json", config)
    root = tmp_path / "run"
    frozen = runner.prepare(tmp_path / "config.json", root, "r", "B0", "alice")
    untouched = Path(config["budget_path"]).read_bytes()
    forbidden = httpx.MockTransport(lambda request: pytest.fail("Unexpected dispatch"))
    with monkeypatch.context() as patch:

        def failed_open(*args: Any, **kwargs: Any) -> Any:
            raise OSError("Real setup failure marker.")

        patch.setattr(SqliteStore, "from_conn_string", failed_open)
        failed = runner.operation(
            root,
            "failed",
            "snapshot",
            {"owner": "alice"},
            "boundary",
            host_transport=forbidden,
            embedding_transport=forbidden,
        )
    assert failed["status"] == "INTERRUPTED" and failed["first_error"]["error_type"] == "OSError"
    first = read_json(root / "first-error.json")
    rejected = runner.operation(
        root,
        "foreign",
        "snapshot",
        {"owner": "bob"},
        "boundary",
        host_transport=forbidden,
        embedding_transport=forbidden,
    )
    assert rejected["status"] == "REJECTED" and read_json(root / "first-error.json") == first
    refusal = runner.operation(
        root,
        "large",
        "read",
        {"owner": "alice", "question": "x " * 40000},
        "new-boundary",
        host_transport=forbidden,
        embedding_transport=forbidden,
    )
    assert refusal["status"] == "CAPACITY_REJECTED"
    assert refusal["request_attempts"] == {"generation": 0, "embedding": 0}
    assert refusal["budget_before"] == refusal["budget_after"]
    assert refusal["snapshot_after"]["archive"] == []
    with monkeypatch.context() as patch:
        patch.setattr(
            runner, "_sources", lambda: {**frozen["source_sha256"], "new_runtime.py": "changed"}
        )
        with pytest.raises(ValueError, match="SOURCE_OR_SDK_CHANGED"):
            runner._frozen(root)
    config["reader_system_prompt"] += " Config change."
    write_json(tmp_path / "config.json", config)
    with pytest.raises(ValueError, match="CONFIG_CHANGED"):
        runner._frozen(root)
    assert Path(config["budget_path"]).read_bytes() == untouched
