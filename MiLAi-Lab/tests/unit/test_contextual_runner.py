from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import ValidationError, validate
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from milai_lab.datasets.contextual import EvaluationCase, HistoryMessage, TaskInput

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
runner = importlib.import_module("milai_lab.runners.contextual")
cli = importlib.import_module("run_contextual_user_memory")
adapter = importlib.import_module("contextual_host_adapter")


def test_cli_keeps_entrypoint_and_legacy_runner_exports(tmp_path: Path) -> None:
    args = cli.parser().parse_args(
        [
            "--config",
            str(tmp_path / "config.json"),
            "--output",
            str(tmp_path),
            "--phase",
            "score",
        ]
    )
    assert args.phase == "score"
    assert (
        cli.parser()
        .parse_args(
            [
                "--config",
                str(tmp_path / "config.json"),
                "--output",
                str(tmp_path),
                "--phase",
                "ingest",
            ]
        )
        .phase
        == "ingest"
    )
    assert cli.build_history is runner.build_history
    assert cli.run_answers is runner.run_answers


def test_ordinary_tool_schema_requires_explicit_write_operation() -> None:
    save = next(
        tool
        for tool in runner.memory_tools("ordinary")
        if tool["function"]["name"] == "memory_save"
    )
    schema = save["function"]["parameters"]
    validate(
        {
            "op": "CREATE",
            "certainty": "explicit",
            "content": "A new understanding",
            "about_ref": "unknown",
            "source_refs": [],
        },
        schema,
    )
    validate(
        {
            "op": "REVISE",
            "certainty": "explicit",
            "target_ref": "m0",
            "content": "Current meaning",
            "about_ref": "unknown",
            "source_refs": [],
            "dependencies": [],
        },
        schema,
    )
    validate({"op": "RETAIN_SOURCE", "source_ref": "m0"}, schema)
    validate({"op": "NO_CHANGE"}, schema)
    with pytest.raises(ValidationError):
        validate({"content": "Unmarked"}, schema)
    with pytest.raises(ValidationError):
        validate(
            {"op": "CREATE", "certainty": "explicit", "content": "Wrong", "forget_refs": []}, schema
        )


def config(tmp_path: Path) -> dict:
    tokenizer_path = tmp_path / "tokenizer.json"
    Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]")).save(str(tokenizer_path))
    host_path = tmp_path / "host-tokenizer"
    base = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    base.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=base, unk_token="[UNK]")
    tokenizer.chat_template = (
        "{% for m in messages %}{{ m['role'] }} {{ m['content'] }} {% endfor %}assistant"
    )
    tokenizer.save_pretrained(str(host_path))
    return {
        "host": {"model": "fixture-host"},
        "embedding": {"model": "fixture-embedding"},
        "embedding_dimension": 2,
        "embedding_batch": 2,
        "embedding_window": {"tokenizer_path": str(tokenizer_path), "max_tokens": 5},
        "history_capacity": {
            "model": "fixture-host",
            "tokenizer_path": str(host_path),
            "tokenizer_files_sha256": {
                name: hashlib.sha256((host_path / name).read_bytes()).hexdigest()
                for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
            },
            "context_tokens": 20000,
            "output_tokens": 1000,
            "batch_source_tokens": 1,
        },
        "history_max_operations": 4,
        "history_context_bytes": 12000,
        "model_identity": {"embedding": {"weights_sha256": "fixture-weights"}},
        "profiles": {"CANDIDATE": "state", "QUERY_ONLY": "query_only", "RAW_RETRIEVAL": "raw"},
        "answer_calls": 2,
    }


def case(case_id: str = "first") -> EvaluationCase:
    return EvaluationCase(
        case_id,
        "personamem-v2",
        "fixture",
        TaskInput(
            "user",
            "history",
            (HistoryMessage("one", "user", "past"), HistoryMessage("two", "user", "later")),
            "question " + case_id,
            options=("option A", "option B"),
        ),
        "A",
        {"type": "fixture"},
        {},
    )


def test_history_resume_exposes_only_the_legal_prefix(tmp_path: Path, monkeypatch) -> None:
    observations = []
    fail_once = True

    class Host:
        def chat(self, messages, response_format):
            nonlocal fail_once
            message = json.loads(messages[1]["content"])
            chunk = message["observations"]
            received = [item["content"] for item in chunk]
            observations.append(received)
            assert case().task.question not in messages[1]["content"]
            if received == ["later"] and fail_once:
                fail_once = False
                raise RuntimeError("provider incomplete")
            if received == ["later"]:
                assert message["related_records"][0]["text"] == "past"
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "operations": [
                                        {
                                            "op": "CREATE",
                                            "certainty": "explicit",
                                            "source_refs": [item["source_ref"]],
                                            "about_ref": "u0",
                                            "content": item["content"],
                                        }
                                        for item in chunk
                                    ]
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    ingest = runner.ingest_chunk

    def check_prefix(memory, chunk, **kwargs):
        received = [item["content"] for item in chunk]
        known = {source.content for source in memory.sources.values()}
        assert known == ({"past"} if received == ["past"] else {"past", "later"})
        return ingest(memory, chunk, **kwargs)

    monkeypatch.setattr(runner, "ingest_chunk", check_prefix)
    arguments = {
        "arm": "CANDIDATE",
        "config": config(tmp_path),
        "data_identity": "fixture-data",
        "output": tmp_path,
        "host": Host(),
        "embedding": SimpleNamespace(embed=lambda texts, model: [[1.0, 0.0] for _ in texts]),
    }
    with pytest.raises(RuntimeError, match="incomplete"):
        runner.build_history(case().task, **arguments)
    with pytest.raises(ValueError, match="EXPLICIT_REPAIR"):
        runner.build_history(case().task, **arguments)
    assert observations == [["past"], ["later"]]
    progress = runner.read_json(next(tmp_path.glob("history/CANDIDATE/*/progress.json")))
    assert len(progress["settled_batches"]) == 1
    assert progress["active_batch"] == 1
    assert progress["active_source_acceptance"]["retained_sources"] == 1
    assert {source["content"] for source in progress["checkpoint"]["sources"].values()} == {
        "past",
        "later",
    }
    assert progress["active_proposal"]["state"] == "request_started"
    assert not progress["active_proposal"]["proposal_valid"]
    old_progress_path = next(tmp_path.glob("history/CANDIDATE/*/progress.json"))
    old_batches_path = old_progress_path.with_name("batches.json")
    old_progress_bytes = old_progress_path.read_bytes()
    repair = {
        "previous_progress_path": str(old_progress_path),
        "previous_progress_sha256": hashlib.sha256(old_progress_bytes).hexdigest(),
        "previous_batches_path": str(old_batches_path),
        "previous_batches_sha256": hashlib.sha256(old_batches_path.read_bytes()).hexdigest(),
        "reason": "Zero-commit failed proposal under the earlier handle grammar",
    }
    repaired_config = {**arguments["config"], "history_repair": repair}
    repaired_checkpoint, record = runner.build_history(
        case().task,
        **{**arguments, "config": repaired_config},
    )
    assert observations == [["past"], ["later"], ["later"]]
    assert len(record["settled_batches"]) == 2
    assert record["history_repair"]["failed_batch"] == 1
    repaired = runner.read_json(
        tmp_path / "history" / "CANDIDATE" / record["cache_id"] / "progress.json"
    )
    assert repaired["active_batch"] is None
    assert repaired["history_repair"] == record["history_repair"]
    later_ref = next(
        ref
        for ref, source in repaired_checkpoint["sources"].items()
        if source["content"] == "later"
    )
    assert repaired_checkpoint["source_sequence"][later_ref] == 2
    assert old_progress_path.read_bytes() == old_progress_bytes


def test_history_retained_source_resumes_before_host_proposal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task = TaskInput(
        "user",
        "one-message-history",
        (HistoryMessage("one", "user", "fact", "session-1"),),
        "question",
    )
    cfg = config(tmp_path)
    cfg["profiles"]["CANDIDATE"] = "ordinary"
    requests = 0

    class Host:
        def chat(self, messages, response_format):
            nonlocal requests
            requests += 1
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "operations": [
                                        {"op": "NO_CHANGE", "reason": "NO_NEW_MAINTAINABLE_FACT"},
                                    ]
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    arguments = {
        "arm": "CANDIDATE",
        "config": cfg,
        "data_identity": "fixture-data",
        "output": tmp_path,
        "host": Host(),
        "embedding": SimpleNamespace(embed=lambda texts, model: [[1.0, 0.0] for _ in texts]),
    }
    prepare = runner.prepare_ingestion

    def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted after source acceptance")

    monkeypatch.setattr(runner, "prepare_ingestion", interrupted)
    with pytest.raises(RuntimeError, match="after source acceptance"):
        runner.build_history(task, **arguments)
    progress_path = next(tmp_path.glob("history/CANDIDATE/*/progress.json"))
    progress = runner.read_json(progress_path)
    assert progress["active_proposal"] is None
    assert progress["active_source_acceptance"]["newly_retained_sources"] == 1
    assert [source["content"] for source in progress["checkpoint"]["sources"].values()] == [
        "fact",
    ]

    monkeypatch.setattr(runner, "prepare_ingestion", prepare)
    checkpoint, record = runner.build_history(task, **arguments)
    assert requests == 1
    assert len(checkpoint["sources"]) == 1
    settled = record["settled_batches"][0]
    assert settled["source_acceptance"]["newly_retained_sources"] == 1
    assert settled["interpretation_changes"] == {"created": 0, "revised": 0}
    assert settled["no_change_reasons"] == ["NO_NEW_MAINTAINABLE_FACT"]
    events = [
        json.loads(line)["event"]
        for line in progress_path.with_name("trace.jsonl").read_text().splitlines()
    ]
    assert events.count("history_source_acceptance") == 1


def test_history_resume_counts_units_committed_before_interruption(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task = TaskInput(
        "user",
        "one-message-history",
        (HistoryMessage("one", "user", "fact", "session-1"),),
        "question",
    )
    cfg = config(tmp_path)
    cfg["profiles"]["CANDIDATE"] = "ordinary"
    requests = 0

    class Host:
        def chat(self, messages, response_format):
            nonlocal requests
            requests += 1
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "operations": [
                                        {
                                            "op": "CREATE",
                                            "certainty": "explicit",
                                            "content": "First",
                                            "about_ref": "u0",
                                            "source_refs": ["s0"],
                                        },
                                        {
                                            "op": "CREATE",
                                            "certainty": "explicit",
                                            "content": "Second",
                                            "about_ref": "u0",
                                            "source_refs": ["s0"],
                                        },
                                    ]
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    arguments = {
        "arm": "CANDIDATE",
        "config": cfg,
        "data_identity": "fixture-data",
        "output": tmp_path,
        "host": Host(),
        "embedding": SimpleNamespace(embed=lambda texts, model: [[1.0, 0.0] for _ in texts]),
    }
    ingest = runner.ingest_chunk
    fail_once = True

    def interrupt_second_unit(memory, observations, **kwargs):
        nonlocal fail_once
        dispatch = memory.dispatch
        attempted = 0

        def once(name, parameters, *, operation_id=None):
            nonlocal attempted, fail_once
            attempted += 1
            if attempted == 2 and fail_once:
                fail_once = False
                raise RuntimeError("interrupted before second unit")
            return dispatch(name, parameters, operation_id=operation_id)

        memory.dispatch = once
        try:
            return ingest(memory, observations, **kwargs)
        finally:
            memory.dispatch = dispatch

    monkeypatch.setattr(runner, "ingest_chunk", interrupt_second_unit)
    with pytest.raises(RuntimeError, match="before second unit"):
        runner.build_history(task, **arguments)
    progress = runner.read_json(next(tmp_path.glob("history/CANDIDATE/*/progress.json")))
    assert len(progress["active_proposal"]["unit_receipts"]) == 1
    assert progress["active_card_versions"] == {}
    assert len(progress["checkpoint"]["cards"]) == 1

    checkpoint, record = runner.build_history(task, **arguments)
    assert requests == 1
    assert len(checkpoint["cards"]) == 2
    assert record["settled_batches"][0]["interpretation_changes"] == {
        "created": 2,
        "revised": 0,
    }


def test_online_arrival_never_publishes_future_after_unsettled_unit(tmp_path: Path) -> None:
    task = TaskInput(
        "user",
        "online-history",
        (
            HistoryMessage("lead", "assistant", "leading marker"),
            HistoryMessage("first", "user", "current marker"),
            HistoryMessage("reply", "assistant", "reply marker"),
            HistoryMessage("next", "user", "future marker"),
        ),
        "future question",
    )
    cfg = config(tmp_path)
    cfg["history_arrival_policy"] = "online_turn_replay"
    cfg["history_capacity"]["batch_source_tokens"] = 100
    received: list[list[str]] = []

    class Host:
        def chat(self, messages, response_format):
            observations = json.loads(messages[1]["content"])["observations"]
            received.append([item["content"] for item in observations])
            assert "future marker" not in json.dumps(messages)
            raise RuntimeError("first arrival unsettled")

    with pytest.raises(RuntimeError, match="first arrival unsettled"):
        runner.build_history(
            task,
            arm="CANDIDATE",
            config=cfg,
            data_identity="fixture-data",
            output=tmp_path,
            host=Host(),
            embedding=SimpleNamespace(embed=lambda texts, model: [[1.0, 0.0] for _ in texts]),
        )
    assert received == [["leading marker", "current marker", "reply marker"]]
    cache = next((tmp_path / "history" / "CANDIDATE").iterdir())
    plan = runner.read_json(cache / "batches.json")
    assert plan["arrival_policy"] == "online_turn_replay"
    assert plan["arrival_boundaries"] == [{"start": 0, "end": 3}, {"start": 3, "end": 4}]
    assert runner.history_coverage(task.history, plan["batches"])["messages"] == 4
    progress = runner.read_json(cache / "progress.json")
    assert progress["active_batch"] == 0
    assert progress["settled_batches"] == []
    assert "future marker" not in json.dumps(progress["checkpoint"])


def test_history_model_cannot_delete_managed_sources(tmp_path: Path, monkeypatch) -> None:
    private = "private source text"
    old_checkpoint = None
    forgotten_ref = None

    def ingest(memory, observations, *, emit, **kwargs):
        nonlocal old_checkpoint, forgotten_ref
        emit(
            {
                "event": "vllm_response",
                "path": "chat/completions",
                "usage": {"total_tokens": 7},
                "wall_seconds": 1,
                "response_text": private,
            }
        )
        if forgotten_ref is None:
            forgotten_ref = observations[0]["source_ref"]
            receipt = memory.dispatch(
                "memory_save",
                {
                    "op": "RETAIN_SOURCE",
                    "source_ref": forgotten_ref,
                },
            )
        else:
            progress = next((tmp_path / "history" / "CANDIDATE").glob("*/progress.json"))
            old_checkpoint = runner.read_json(progress)["checkpoint"]
            receipt = memory.dispatch("memory_save", {"forget_refs": [forgotten_ref]})
        call = {"name": "memory_save", "ok": True, "result": receipt}
        emit({"event": "host_tool_call", "call": {**call, "arguments": {"content": private}}})
        return {
            "status": "complete",
            "proposal": {"text": private},
            "calls": [call],
            "maintenance_settled": True,
            "usage": {"total_tokens": 7},
            "elapsed_seconds": 1,
        }

    monkeypatch.setattr(runner, "ingest_chunk", ingest)
    cfg = config(tmp_path)
    cfg["history_capacity"]["batch_source_tokens"] = 100
    task = TaskInput(
        "user",
        "history",
        (
            HistoryMessage("one", "user", private, "session-1"),
            HistoryMessage("two", "user", "public later", "session-2"),
        ),
        "question",
    )
    checkpoint, record = runner.build_history(
        task,
        arm="CANDIDATE",
        config=cfg,
        data_identity="fixture-data",
        output=tmp_path,
        host=SimpleNamespace(),
        embedding=SimpleNamespace(),
    )
    cache = tmp_path / "history" / "CANDIDATE" / record["cache_id"]
    ledger = runner.deletion_ledger(tmp_path, "history", "CANDIDATE", record["cache_id"], "user")
    assert ledger.read().refs == frozenset()
    assert private in (cache / "trace.jsonl").read_text()
    assert forgotten_ref in checkpoint["sources"]
    assert all(json.loads(line) for line in (cache / "trace.jsonl").read_text().splitlines())
    assert old_checkpoint is not None
    restored = runner.ContextualMemory.restore(
        old_checkpoint,
        user_id="user",
        embed=lambda texts: [],
        deletion_ledger=ledger,
    )
    assert forgotten_ref in restored.sources


def test_lifecycle_cleanup_resumes_committed_operation(tmp_path: Path) -> None:
    from milai_lab.methods.contextual_memory.operations import TaskEnvelope

    ledger = runner.deletion_ledger(tmp_path, "answers", "ordinary", "one", "user")
    memory = runner.ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [],
        deletion_ledger=ledger,
    )
    ref = memory.publish(
        runner.Observation("one", "private body", "user", "source", actor_ref="current_user")
    )
    memory.save(source_ref=ref)
    old = memory.checkpoint()
    memory.start_task("lifecycle", "")
    envelope = TaskEnvelope(
        "user",
        "lifecycle",
        "lifecycle",
        frozenset({"delete"}),
        (ref,),
        "operation-1",
        "delete_then_answer",
        "Public continuation",
        str(ledger.path.parent.resolve()),
    )
    cache = tmp_path / "managed"
    cache.mkdir()
    trace = runner.Trace(cache / "trace.jsonl", "history")
    trace({"event": "vllm_response", "response_text": "private body"})
    (cache / "progress.json").write_text("private body")
    (cache / "checkpoint.json").write_text("private body")
    (cache / "chunk-old.json").write_text("private body")
    embed = runner.CachedEmbedding(
        SimpleNamespace(emit=None),
        config(tmp_path),
        tmp_path / "embeddings.sqlite",
        used_keys_path=cache / "cache-keys.json",
    )
    embed.used_keys.add("private-key")
    runner.write_json(embed.used_keys_path, ["private-key"])
    embed.connection.execute(
        "INSERT INTO vectors VALUES (?, ?)",
        ("private-key", "[1.0, 0.0]"),
    )
    embed.connection.commit()

    def interrupted() -> None:
        raise RuntimeError("interrupted cleanup")

    with pytest.raises(RuntimeError, match="interrupted cleanup"):
        runner.perform_lifecycle_delete(
            memory,
            envelope,
            [ref],
            {"history_artifacts": interrupted},
        )
    assert ledger.read().generation == 1
    assert ledger.read().operations["operation-1"].pending_effects == ("history_artifacts",)
    assert "private body" in (cache / "trace.jsonl").read_text()
    restored = runner.ContextualMemory.restore(
        old,
        user_id="user",
        embed=memory.embed,
        deletion_ledger=ledger,
    )
    restored.start_task("lifecycle", "")
    receipt = runner.perform_lifecycle_delete(
        restored,
        envelope,
        [ref],
        {
            "history_artifacts": lambda: runner.scrub_history_artifacts(
                cache,
                trace,
                embed,
            )
        },
    )
    assert receipt["completion"] == "complete"
    assert ledger.read().generation == 1
    assert ref not in restored.sources
    assert "private body" not in (cache / "trace.jsonl").read_text()
    assert not (cache / "progress.json").exists()
    assert not (cache / "checkpoint.json").exists()
    assert not (cache / "chunk-old.json").exists()
    assert not (cache / "cache-keys.json").exists()
    assert embed.connection.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0

    requests = []

    class HostClient:
        config = SimpleNamespace(tool_mode="native", max_calls=1)

        def chat(self, messages, tools, **kwargs):
            requests.append(messages)
            return {"choices": [{"message": {"role": "assistant", "content": "Safe answer"}}]}

    host = runner.ContextualHost(
        HostClient(), restored.dispatch, runner.TOOLS, "Answer.", memory=restored
    )
    result = host.run([{"role": "user", "content": "private body"}], envelope=envelope)
    assert result.answer == "Safe answer"
    assert "private body" not in json.dumps(requests)
    assert "Public continuation" in json.dumps(requests)
    embed.close()


def test_question_overlays_are_isolated_and_query_only_has_no_history(
    tmp_path: Path, monkeypatch
) -> None:
    memory = runner.ContextualMemory("user", host_id="fixture-host", embed=lambda texts: [])
    checkpoint = memory.checkpoint(include_task=False)
    frozen = json.dumps(checkpoint, sort_keys=True)
    monkeypatch.setattr(
        runner,
        "build_history",
        lambda *a, **kw: (checkpoint, {"cache_id": "id", "status": "BUILT"}),
    )
    scopes = []

    class Host:
        def __init__(
            self, client, dispatch, tools, prompt, emit, delivery_mode="full", memory=None
        ):
            self.memory, self.tools = memory, tools

        def run(self, messages, max_calls):
            scopes.append(set(source.content for source in self.memory.sources.values()))
            assert not self.memory.workspace.cards
            if self.tools:
                source = next(iter(self.memory.sources))
                self.memory.save(source_ref=source, content="question-specific interpretation")
            return adapter.HostResult("Final Answer: A", "complete", [], {}, 0, [])

    monkeypatch.setattr(runner, "ContextualHost", Host)
    for item, arm in [(case(), "CANDIDATE"), (case("next"), "CANDIDATE"), (case(), "QUERY_ONLY")]:
        runner.answer_case(
            item,
            arm=arm,
            config=config(tmp_path),
            data_identity="fixture-data",
            output=tmp_path,
            host=SimpleNamespace(),
            embedding=SimpleNamespace(),
        )
    assert scopes == [{"past", "later"}, {"past", "later"}, set()]
    assert json.dumps(checkpoint, sort_keys=True) == frozen


def test_answer_model_cannot_delete_or_clear_derived_cache(tmp_path: Path, monkeypatch) -> None:
    history = runner.ContextualMemory("user", host_id="fixture-host", embed=lambda texts: [])
    source = history.publish(
        runner.Observation("one", "past", "user", "fixture-data", actor_ref="current_user")
    )
    history.save(source_ref=source)
    checkpoint = history.checkpoint(include_task=False)
    monkeypatch.setattr(
        runner,
        "build_history",
        lambda *a, **kw: (checkpoint, {"cache_id": "owner", "status": "BUILT"}),
    )

    class Host:
        def __init__(
            self, client, dispatch, tools, prompt, emit, delivery_mode="full", memory=None
        ):
            self.memory, self.dispatch, self.emit = memory, dispatch, emit

        def run(self, messages, max_calls):
            if "question first" in messages[0]["content"]:
                self.memory.embed(["past"])
                self.emit(
                    {
                        "event": "vllm_response",
                        "path": "chat/completions",
                        "usage": {"total_tokens": 5},
                        "wall_seconds": 1,
                        "response_text": "past",
                    }
                )
                receipt = self.dispatch("memory_save", {"forget_refs": [source]})
                self.emit(
                    {
                        "event": "host_tool_call",
                        "call": {
                            "name": "memory_save",
                            "ok": True,
                            "result": receipt,
                            "arguments": {"private": "past"},
                        },
                    }
                )
            else:
                assert source in self.memory.sources
            return adapter.HostResult(
                "Final Answer: A",
                "complete",
                [],
                {},
                0,
                [{"role": "tool", "content": "past"}],
            )

    monkeypatch.setattr(runner, "ContextualHost", Host)
    arguments = {
        "arm": "CANDIDATE",
        "config": config(tmp_path),
        "data_identity": "fixture-data",
        "output": tmp_path,
        "host": SimpleNamespace(),
        "embedding": SimpleNamespace(embed=lambda texts, model: [[1.0, 0.0] for _ in texts]),
    }
    first = runner.answer_case(case(), **arguments)
    first_dir = tmp_path / "answers" / "CANDIDATE" / runner.digest("first")
    assert first["host"]["transcript"] == [{"role": "tool", "content": "past"}]
    assert "past" in (first_dir / "trace.jsonl").read_text()
    assert (first_dir / "cache-keys.json").exists()
    with runner.sqlite3.connect(tmp_path / "embeddings.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 1
    second = runner.answer_case(case("next"), **arguments)
    assert second["host"]["transcript"] == [{"role": "tool", "content": "past"}]
    first_ledger = runner.deletion_ledger(
        tmp_path, "answers", "CANDIDATE", runner.digest("first"), "user"
    )
    second_ledger = runner.deletion_ledger(
        tmp_path, "answers", "CANDIDATE", runner.digest("next"), "user"
    )
    assert source not in first_ledger.read().refs
    assert source not in second_ledger.read().refs
    assert (
        source
        not in runner.deletion_ledger(tmp_path, "history", "CANDIDATE", "owner", "user").read().refs
    )


def test_pending_answer_maintenance_runs_once_and_resumes(tmp_path: Path, monkeypatch) -> None:
    cfg = config(tmp_path)
    cfg["profiles"]["CANDIDATE"] = "support"
    history = runner.ContextualMemory(
        "user", host_id="fixture-host", embed=lambda texts: [], profile="support"
    )
    source = history.publish(
        runner.Observation("one", "past", "user", "fixture-data", actor_ref="current_user")
    )
    history.save(source_ref=source)
    history.revisions.pending[source] = {
        "reason": "fixture",
        "reason_refs": [],
        "known_at": "2026-01-01",
    }
    checkpoint = history.checkpoint(include_task=False)
    monkeypatch.setattr(
        runner,
        "build_history",
        lambda *a, **kw: (checkpoint, {"cache_id": "owner", "status": "BUILT_WITH_PENDING"}),
    )
    proposals = []

    def maintenance(memory, observations, *, emit, maintenance_query, **kwargs):
        proposals.append((observations, maintenance_query))
        emit(
            {
                "event": "vllm_response",
                "path": "chat/completions",
                "usage": {"total_tokens": 3},
                "wall_seconds": 1,
            }
        )
        memory.revisions.pending.clear()
        return {
            "status": "complete",
            "calls": [],
            "related_record_refs": [source],
            "usage": {"total_tokens": 3},
        }

    monkeypatch.setattr(runner, "ingest_chunk", maintenance)
    fails = [True, False]

    class Host:
        def __init__(
            self, client, dispatch, tools, prompt, emit, delivery_mode="full", memory=None
        ):
            pass

        def run(self, messages, max_calls):
            if fails.pop(0):
                raise RuntimeError("answer interrupted")
            return adapter.HostResult("Final Answer: A", "complete", [], {}, 0, [])

    monkeypatch.setattr(runner, "ContextualHost", Host)
    arguments = {
        "arm": "CANDIDATE",
        "config": cfg,
        "data_identity": "fixture-data",
        "output": tmp_path,
        "host": SimpleNamespace(),
        "embedding": SimpleNamespace(),
    }
    with pytest.raises(RuntimeError, match="answer interrupted"):
        runner.answer_case(case(), **arguments)
    result = runner.answer_case(case(), **arguments)
    assert proposals == [([], "question first")]
    assert result["maintenance"]["selected_records"] == 1
    trace_path = tmp_path / "answers" / "CANDIDATE" / runner.digest("first") / "trace.jsonl"
    assert json.loads(trace_path.read_text().splitlines()[0])["stage"] == "maintenance"


def test_report_keeps_missing_group_members_and_counts_shared_trace_once(tmp_path: Path) -> None:
    cases = [case(), replace(case("next"), groups={"type": "missing"})]
    runner.write_json(
        tmp_path / "scores" / "BASELINE" / runner.digest("first") / "score.json",
        {"status": "SCORED", "success": True},
    )
    trace = runner.Trace(tmp_path / "history" / "BASELINE" / "shared" / "trace.jsonl", "history")
    trace(
        {
            "event": "vllm_response",
            "path": "chat/completions",
            "usage": {"total_tokens": 10},
            "wall_seconds": 1,
        }
    )
    trace({"event": "vllm_error", "path": "embeddings", "wall_seconds": 2})
    trace(
        {
            "event": "host_tool_call",
            "call": {
                "name": "memory_read",
                "ok": True,
                "result": {"dependencies": [{"status": "NEEDS_REVISION"}]},
            },
        }
    )
    trace(
        {
            "event": "host_tool_call",
            "call": {
                "name": "memory_save",
                "ok": False,
                "result": {"status": "PENDING"},
                "operation_receipt": {"completion": "pending"},
            },
        }
    )
    report = runner.summarize(
        cases, ["BASELINE", "EXPERIMENT_V3"], tmp_path, reference_arm="BASELINE"
    )
    baseline = report["arms"]["BASELINE"]
    assert baseline["total"] == 2
    assert baseline["scoring_coverage"] == 0.5
    assert baseline["accuracy_scope"] == "PARTIAL"
    assert baseline["groups"]["type=missing"]["host_uncompleted"] == 1
    assert report["costs"]["BASELINE"]["history_llm"]["known_tokens"] == 10
    assert report["costs"]["BASELINE"]["history_embedding"]["missing_usage"] == 1
    assert report["tools"]["BASELINE"]["memory_read"]["revision_signals"] == 1
    assert report["tools"]["BASELINE"]["memory_save"] == {
        "attempts": 1,
        "errors": 0,
        "pending": 1,
        "revision_signals": 0,
        "reused": 0,
    }
    assert report["paired"]["EXPERIMENT_V3"]["unpaired"] == 2


def test_frozen_partial_batch_rejects_later_answer(tmp_path: Path) -> None:
    frozen = runner.freeze_answers([case()], ["EXPERIMENT_V3"], tmp_path)
    assert frozen["scope"] == "PARTIAL"
    assert frozen["entries"][0]["status"] == "MISSING"
    runner.write_json(
        tmp_path / "answers" / "EXPERIMENT_V3" / runner.digest("first") / "answer.json",
        {"status": "complete", "hypothesis": "A"},
    )
    with pytest.raises(ValueError, match="Frozen answer batch changed"):
        runner.freeze_answers([case()], ["EXPERIMENT_V3"], tmp_path)


def test_batch_keeps_success_when_later_update_conflicts() -> None:
    memory = runner.ContextualMemory(
        "user",
        host_id="fixture",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    source = memory.publish(
        runner.Observation("event", "original", "user", "fixture", actor_ref="current_user")
    )
    ref = memory.save(content="old understanding", source_ref=source)["record"]["ref"]
    incoming = memory.publish(
        runner.Observation("next", "new information", "user", "fixture", actor_ref="current_user")
    )

    class Host:
        def chat(self, messages, response_format):
            provided = json.loads(messages[1]["content"])["related_records"]
            assert provided[0]["ref"] == "r0"
            operations = [
                {
                    "op": "REVISE",
                    "certainty": "explicit",
                    "target_ref": "r0",
                    "content": "revised",
                    "about_ref": "u0",
                    "source_refs": ["s0"],
                    "dependencies": [],
                },
                {
                    "op": "REVISE",
                    "certainty": "explicit",
                    "target_ref": "r0",
                    "content": "stale update",
                    "about_ref": "u0",
                    "source_refs": ["s0"],
                    "dependencies": [],
                },
            ]
            return {
                "choices": [
                    {
                        "message": {"content": json.dumps({"operations": operations})},
                        "finish_reason": "stop",
                    }
                ]
            }

    result = runner.ingest_chunk(
        memory,
        [{"source_ref": incoming, "content": "new information"}],
        host=Host(),
        prompt="fixture",
        max_operations=4,
        context_bytes=12000,
        emit=lambda event: None,
    )
    assert result["status"] == "partial_failure"
    assert result["related_record_refs"] == [ref]
    assert result["maintenance_settled"] is False
    assert result["calls"][0]["ok"]
    assert not result["calls"][1]["ok"]
    assert result["calls"][1]["operation_receipt"]["completion"] == "failed"
    assert next(iter(memory.workspace.cards.values())).text == "revised"


def _stale_cases(scenario_id: str, scenario_type: str) -> list[EvaluationCase]:
    history = (
        HistoryMessage("old", "user", "earlier", "session-1", "2025-01-01"),
        HistoryMessage("new", "user", "later", "session-2", "2025-02-01"),
    )
    result = []
    for index in range(1, 4):
        key = f"dim{index}_query"
        result.append(
            EvaluationCase(
                f"{scenario_id}:{key}",
                "stale",
                "fixed-small",
                TaskInput(scenario_id, scenario_id, history, f"Question {index}"),
                None,
                {"type": scenario_type, "dimension": f"dim{index}"},
                {
                    "scenario_id": scenario_id,
                    "type": scenario_type,
                    "probe_key": key,
                    "M_old": "OLD_GOLD",
                    "M_new": "NEW_GOLD",
                    "explanation": "the state changed",
                },
            )
        )
    return result


def test_stale_scores_three_frozen_probes_with_one_budgeted_judge_call(
    tmp_path: Path,
) -> None:
    cases = _stale_cases("scenario-t1", "T1") + _stale_cases("scenario-t2", "T2")
    answers = {}
    for item in cases[:-1]:
        record = {
            "question_id": item.case_id,
            "arm": "RAW",
            "status": "complete",
            "hypothesis": "frozen answer",
        }
        answers[item.case_id] = record
        runner.write_json(
            tmp_path / "answers" / "RAW" / runner.digest(item.case_id) / "answer.json",
            record,
        )
    runner.freeze_answers(cases, ["RAW"], tmp_path)
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["max_tokens"] >= 1536
        assert len(payload["messages"]) == 2
        content = json.dumps(
            {
                "dim1_eval": {"reasoning": "current state", "pass": True},
                "dim2_eval": {"reasoning": "false premise", "pass": False},
                "dim3_eval": {"reasoning": "safe action", "pass": True},
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 120},
            },
        )

    budget = runner.RunBudget(runner.RunLimits(), tmp_path / "budget.json")
    with runner.VLLMClient(
        runner.VLLMConfig(base_url="http://fixture/v1", model="judge", max_tokens=1536),
        transport=httpx.MockTransport(respond),
        budget=budget,
    ) as judge:
        t1 = runner.score_stale_group(
            cases[:3], answers, arm="RAW", output=tmp_path, judge=judge, judge_attempts=2
        )
        t2 = runner.score_stale_group(
            cases[3:], answers, arm="RAW", output=tmp_path, judge=judge, judge_attempts=2
        )
        runner.score_stale_group(
            cases[:3], answers, arm="RAW", output=tmp_path, judge=judge, judge_attempts=2
        )
    assert len(requests) == 1
    assert budget.state["generation_requests"] == 1
    assert [t1[item.case_id]["success"] for item in cases[:3]] == [True, False, True]
    assert [t2[item.case_id]["status"] for item in cases[3:]] == [
        "JUDGE_UNRESOLVED",
        "JUDGE_UNRESOLVED",
        "HOST_INCOMPLETE",
    ]
    report = runner.summarize(cases, ["RAW"], tmp_path, reference_arm="RAW")
    assert report["arms"]["RAW"]["total"] == 6
    assert report["arms"]["RAW"]["native_types"]["T1"]["overall"]["correct"] == 2
    assert report["arms"]["RAW"]["native_types"]["T2"]["overall"]["unjudged"] == 3
    assert report["costs"]["RAW"]["judge_llm"]["requests"] == 1


def test_score_case_legacy_export_keeps_memsyco_native_judge(tmp_path: Path) -> None:
    item = EvaluationCase(
        "memsyco-case",
        "memsyco",
        "screen",
        TaskInput("user", "history", (), "What now?"),
        "new choice",
        {"track": "valid_memory_selection"},
        {
            "task": "valid_memory_selection",
            "memory": {
                "items": [
                    {"status": "outdated", "content": "old choice", "type": "preference"},
                    {"status": "current", "content": "new choice", "type": "preference"},
                ]
            },
            "evaluation": {
                "reference_answer": "new choice",
                "rubric": {"expected_behavior": "use new", "failure_behavior": "use old"},
            },
        },
    )
    answer = {
        "question_id": item.case_id,
        "arm": "RAW",
        "status": "complete",
        "hypothesis": "new choice",
    }
    runner.write_json(
        tmp_path / "answers" / "RAW" / runner.digest(item.case_id) / "answer.json", answer
    )
    runner.freeze_answers([item], ["RAW"], tmp_path)

    class Judge:
        emit = None

        def chat(self, messages, response_format):
            assert response_format["type"] == "json_schema"
            assert "older_preference_memory" in messages[1]["content"]
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "uses_latest_preference": 1,
                                    "outdated_preference_contamination": 0,
                                    "valid_selection_pass": True,
                                    "brief_rationale": "new preference followed",
                                }
                            )
                        },
                    }
                ]
            }

    score = runner.score_case(item, answer, output=tmp_path, judge=Judge(), judge_attempts=1)
    assert score["status"] == "SCORED"
    assert score["success"] is True
    assert score["format_error"] is False


def test_finite_profiles_and_direct_history_owner_build_before_workers(
    tmp_path: Path, monkeypatch
) -> None:
    support = runner.resolve_profile("support")
    linked = runner.resolve_profile("support_linked")
    delta = runner.resolve_profile("support_delta")
    assert support.write_profile == linked.write_profile == "support"
    assert linked.material_mode == "linked"
    assert delta.delivery_mode == "delta"
    assert runner.resolve_profile("support_raw_evidence").old_source_bytes == 4096
    assert any(
        tool["function"]["name"] == "memory_save"
        and "changeset" in tool["function"]["parameters"]["properties"]
        for tool in runner.memory_tools("support_linked")
    )
    assigned = {"OWNER": "support", "LINKED": "support_linked"}
    assert runner.validate_history_owners(list(assigned), assigned, {"LINKED": "OWNER"}) == {
        "LINKED": "OWNER"
    }
    with pytest.raises(ValueError, match="same write and maintenance"):
        runner.validate_history_owners(
            ["OWNER", "LINKED"],
            {"OWNER": "support", "LINKED": "support_pending"},
            {"LINKED": "OWNER"},
        )
    with pytest.raises(ValueError, match="direct and acyclic"):
        runner.validate_history_owners(
            ["OWNER", "LINKED"], assigned, {"LINKED": "OWNER", "OWNER": "LINKED"}
        )
    run_config = config(tmp_path)
    run_config.update(
        profiles=assigned,
        history_owner={"LINKED": "OWNER"},
        concurrency=2,
    )
    run_config["host"]["base_url"] = "http://fixture/v1"
    run_config["embedding"]["base_url"] = "http://fixture/v1"
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def build(task, **kwargs):
        calls.append(("build", kwargs["arm"], task.history_id))
        return {}, {"cache_id": "shared", "status": "BUILT"}

    def answer(group, **kwargs):
        assert calls[0] == ("build", "OWNER", "history")
        assert sum(item[0] == "build" for item in calls) == 1
        calls.append(("answer", group[0], group[1][0].task.history_id))

    monkeypatch.setattr(runner, "VLLMClient", Client)
    monkeypatch.setattr(runner, "build_history", build)
    monkeypatch.setattr(runner, "answer_group", answer)
    runner.run_answers(
        [case(), case("next")],
        ["LINKED", "OWNER"],
        config=run_config,
        data_identity="fixed",
        output=tmp_path,
        budget=runner.RunBudget(runner.RunLimits(), tmp_path / "budget.json"),
    )
    assert len([item for item in calls if item[0] == "answer"]) == 2

    calls.clear()
    ingest_output = tmp_path / "ingest-only"
    runner.execute_batches(
        [
            (
                {"data_manifest_sha256": "fixed"},
                [case(), case("next")],
                ["LINKED", "OWNER"],
                ingest_output,
            )
        ],
        config=run_config,
        output=tmp_path,
        budget=runner.RunBudget(runner.RunLimits(), tmp_path / "ingest-budget.json"),
        phase="ingest",
    )
    assert calls == [("build", "OWNER", "history")]
    assert not (ingest_output / "answer-batch.json").exists()
    assert not (tmp_path / "answer-batch.json").exists()
    assert not (ingest_output / "answers").exists()

    calls.clear()
    other = case("other")
    other = replace(other, task=replace(other.task, history_id="other-history"))

    def fail_one(task, **kwargs):
        if task.history_id == "history":
            raise RuntimeError("shared build unavailable")
        calls.append(("build", kwargs["arm"], task.history_id))
        return {}, {"cache_id": "other", "status": "BUILT"}

    def answer_other(group, **kwargs):
        assert group[1][0].task.history_id == "other-history"
        calls.append(("answer", group[0], "other-history"))

    monkeypatch.setattr(runner, "build_history", fail_one)
    monkeypatch.setattr(runner, "answer_group", answer_other)
    failure_output = tmp_path / "failed-build"
    runner.run_answers(
        [case(), other],
        ["LINKED", "OWNER"],
        config=run_config,
        data_identity="fixed",
        output=failure_output,
        budget=runner.RunBudget(runner.RunLimits(), tmp_path / "failure-budget.json"),
    )
    assert calls.count(("build", "OWNER", "other-history")) == 1
    assert len([item for item in calls if item[0] == "answer"]) == 2
    for arm in ("LINKED", "OWNER"):
        assert (failure_output / "failures" / arm / (runner.digest("first") + ".jsonl")).exists()


def test_failed_history_is_attempted_once_for_all_probes_in_one_arm(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = config(tmp_path)
    cfg["profiles"] = {"BROKEN": "support", "OTHER": "support"}
    cfg["concurrency"] = 2
    cfg["host"]["base_url"] = "http://fixture/v1"
    cfg["embedding"]["base_url"] = "http://fixture/v1"
    members = [case("first"), case("second"), case("third")]
    builds: list[str] = []
    answered: list[tuple[str, str]] = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def build(task, **kwargs):
        builds.append(kwargs["arm"])
        if kwargs["arm"] == "BROKEN":
            raise ValueError("historical proposal rejected")
        return {}, {"cache_id": "ready", "status": "BUILT"}

    def answer(item, *, arm, **kwargs):
        answered.append((arm, item.case_id))
        return {"status": "complete"}

    monkeypatch.setattr(runner, "VLLMClient", Client)
    monkeypatch.setattr(runner, "build_history", build)
    monkeypatch.setattr(runner, "answer_case", answer)
    runner.run_answers(
        members,
        ["BROKEN", "OTHER"],
        config=cfg,
        data_identity="fixed",
        output=tmp_path,
        budget=runner.RunBudget(runner.RunLimits(), tmp_path / "budget.json"),
    )
    assert sorted(builds) == ["BROKEN", "OTHER"]
    assert answered == [("OTHER", item.case_id) for item in members]
    for item in members:
        path = tmp_path / "failures" / "BROKEN" / (runner.digest(item.case_id) + ".jsonl")
        failure = json.loads(path.read_text().splitlines()[0])
        assert (failure["type"], failure["stage"], failure["history_id"]) == (
            "ValueError",
            "history",
            "history",
        )


def test_shared_checkpoint_restores_arm_specific_material_and_delivery(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = config(tmp_path)
    cfg["profiles"] = {
        "OWNER": "support",
        "LINKED": "support_linked",
        "DELTA": "support_delta",
    }
    cfg["history_owner"] = {"LINKED": "OWNER", "DELTA": "OWNER"}
    memory = runner.ContextualMemory(
        "user", host_id="fixture-host", embed=lambda texts: [], profile="support"
    )
    checkpoint = memory.checkpoint(include_task=False)
    owners = []
    seen = []

    def built(task, **kwargs):
        owners.append(kwargs["arm"])
        return checkpoint, {"cache_id": "owner-cache", "status": "BUILT"}

    class Host:
        def __init__(
            self, client, dispatch, tools, prompt, emit, delivery_mode="full", memory=None
        ):
            seen.append((memory.material_mode, delivery_mode))

        def run(self, messages, max_calls):
            return adapter.HostResult("answer", "complete", [], {}, 0, [])

    monkeypatch.setattr(runner, "build_history", built)
    monkeypatch.setattr(runner, "ContextualHost", Host)
    for arm in ("LINKED", "DELTA"):
        answer = runner.answer_case(
            case(),
            arm=arm,
            config=cfg,
            data_identity="fixed",
            output=tmp_path,
            host=SimpleNamespace(),
            embedding=SimpleNamespace(),
        )
        assert answer["history_cache_id"] == "owner-cache"
    assert owners == ["OWNER", "OWNER"]
    assert seen == [("linked", "full"), ("plain", "delta")]
