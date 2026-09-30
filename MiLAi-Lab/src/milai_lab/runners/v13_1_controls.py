"""Opt-in finite controls API/CLI; prepare does local validation and zero HTTP.

Each operation may run in a fresh process using one SDK SQLite resource. The
caller declares the same admission_key for writer/reader phases belonging to
one public boundary. Native MERIT uses the existing agent_factory/callback API;
MemSyco can inject its existing public prompt/formatter into read_text/recall.
There is no dataset, scorer, rubric, hidden-world or future-question input here.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import inspect
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, cast

import httpx
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.baselines.v13_1_controls import ARMS, ControlsBackend, validate_config
from milai_lab.harness.artifact_io import digest, read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.methods.local_state_attention.summary import SUMMARY_PROMPT
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import EmbeddingCapacity, MeteredEmbeddings
from milai_lab.runners import v13_1_d0 as d0

LAB = d0.LAB
CLI = LAB / "tools/run_v13_1_controls.py"


def _sources() -> dict[str, str]:
    return {**d0._sources(), CLI.relative_to(LAB).as_posix(): d0._sha(CLI)}


def _sdk() -> dict[str, Any]:
    packages = (
        "langgraph",
        "langgraph-checkpoint",
        "langgraph-checkpoint-sqlite",
        "langchain-core",
        "langmem",
        "tokenizers",
        "transformers",
    )
    return {
        "versions": {name: importlib.metadata.version(name) for name in packages},
        "direct_urls": {
            name: importlib.metadata.distribution(name).read_text("direct_url.json")
            for name in packages
        },
        "sqlite_modules": {
            cls.__name__: d0._sha(Path(inspect.getfile(cls))) for cls in (SqliteStore, SqliteSaver)
        },
        "interpreter": str(Path(sys.executable).resolve()),
    }


def _parameters(config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    host, embed = VLLMConfig(**config["host"]), VLLMConfig(**config["embedding"])
    if not host.model or not embed.model or type(host.max_tokens) is not int or host.max_tokens < 1:
        raise ValueError("CONTROL_PROVIDER_DTO_INVALID")
    capacity = HostCapacity(config["capacity"])
    if capacity.identity["model"] != host.model:
        raise ValueError("CONTROL_HOST_MODEL_CAPACITY_MISMATCH")
    if host.enable_thinking is not None and host.enable_thinking != capacity.enable_thinking:
        raise ValueError("HOST_CAPACITY_THINKING_MODE_MISMATCH")
    embedding = EmbeddingCapacity(config["embedding_capacity"])
    for name in ("embedding_dimension", "embedding_batch"):
        if type(config[name]) is not int or config[name] < 1:
            raise ValueError("EMBEDDING_VECTOR_OR_BATCH_INVALID")
    budget_path = Path(config["budget_path"])
    if not budget_path.is_absolute() or not budget_path.is_file():
        raise ValueError("CONTROL_EXISTING_CONTINUOUS_BUDGET_REQUIRED")
    limits = read_json(budget_path)["limits"]
    RunLimits(**limits)
    return {
        "host_capacity": capacity.identity,
        "embedding_capacity": embedding.identity,
        "budget_limits": limits,
        **(
            {
                "generation_cap_profile": config["generation_cap_profile"],
                "effective_generation_cap": config["max_calls_per_message"],
            }
            if "generation_cap_profile" in config
            else {}
        ),
        "effective_controls": config["controls"],
        "summary_prompt_sha256": hashlib.sha256(SUMMARY_PROMPT.encode()).hexdigest(),
        "prompt_sha256": {
            key: hashlib.sha256(config[key].encode()).hexdigest()
            for key in (
                "writer_system_prompt",
                "formation_instruction",
                "reader_system_prompt",
                "prompt_only_instruction",
            )
        },
        "max_calls_per_message": config.get("max_calls_per_message", 12),
        "bm25": {"k1": 1.2, "b": 0.75},
        "fusion": "BM25+cosine reciprocal-rank fusion; stable original chunk IDs",
        "cost_scope": "metered provider reservations/usage; wall/CPU/resource/Store IO partial",
    }


def prepare(config_path: Path, root: Path, run_id: str, arm: str, owner: str) -> dict[str, Any]:
    if arm not in ARMS or not all(type(value) is str and value for value in (run_id, owner)):
        raise ValueError("CONTROL_SCOPE_INVALID")
    config = cast(dict[str, Any], read_json(config_path))
    frozen = {
        "kind": "MILAI_V13_1_FINITE_CONTROLS_FREEZE",
        "config": config,
        "config_path": str(config_path.resolve()),
        "config_sha256": d0._sha(config_path),
        "run_id": run_id,
        "arm": arm,
        "owner": owner,
        "source_sha256": _sources(),
        "sdk": _sdk(),
        **_parameters(config),
        "semantic_evidence": False,
    }
    target = root / "input-freeze.json"
    if target.exists() and read_json(target) != frozen:
        raise ValueError("CONTROL_INPUT_FREEZE_CHANGED")
    write_json(target, frozen)
    return frozen


def _frozen(root: Path) -> dict[str, Any]:
    frozen = cast(dict[str, Any], read_json(root / "input-freeze.json"))
    if frozen["source_sha256"] != _sources() or frozen["sdk"] != _sdk():
        raise ValueError("CONTROL_SOURCE_OR_SDK_CHANGED_AFTER_FREEZE")
    path = Path(frozen["config_path"])
    if frozen["config_sha256"] != d0._sha(path) or frozen["config"] != read_json(path):
        raise ValueError("CONTROL_CONFIG_CHANGED_AFTER_FREEZE")
    parameters = _parameters(frozen["config"])
    if any(frozen[key] != value for key, value in parameters.items()):
        raise ValueError("CONTROL_EFFECTIVE_PARAMETERS_CHANGED_AFTER_FREEZE")
    return frozen


@contextmanager
def open_controls(
    root: Path,
    admission_key: str,
    *,
    emit: Any = None,
    host_transport: httpx.BaseTransport | None = None,
    embedding_transport: httpx.BaseTransport | None = None,
) -> Iterator[ControlsBackend]:
    """Serial cooperating processes; never reset persisted admissions or ledger."""
    frozen = _frozen(root)
    if type(admission_key) is not str or not admission_key:
        raise ValueError("CONTROL_PUBLIC_ADMISSION_KEY_REQUIRED")
    config = frozen["config"]
    with ExitStack() as stack:
        lock = stack.enter_context((root / "execution.lock").open("a+"))
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**frozen["budget_limits"]), Path(config["budget_path"]))
        host = stack.enter_context(
            VLLMClient(
                VLLMConfig(**config["host"]),
                emit=emit,
                budget=budget,
                capacity=HostCapacity(config["capacity"]),
                transport=host_transport,
            )
        )
        embed_client = stack.enter_context(
            VLLMClient(
                VLLMConfig(**config["embedding"]),
                emit=emit,
                budget=budget,
                transport=embedding_transport,
            )
        )
        embeddings = MeteredEmbeddings(
            embed_client,
            config["embedding"]["model"],
            config["embedding_capacity"],
            dimension=config["embedding_dimension"],
            batch_size=config["embedding_batch"],
        )
        model = LangMemRecipeChatModel(
            client=host,
            capacity_path=root / "public-admissions.json",
            max_calls_per_message=config.get("max_calls_per_message", 12),
        )
        model.begin_public_message(frozen["owner"] + ":" + admission_key)
        store = stack.enter_context(
            SqliteStore.from_conn_string(
                str(root / "store.sqlite"),
                index={"dims": embeddings.dimension, "embed": embeddings, "fields": ["content"]},
            )
        )
        saver = stack.enter_context(SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")))
        yield ControlsBackend(
            store,
            saver,
            frozen["run_id"],
            frozen["arm"],
            frozen["owner"],
            config,
            model,
            embeddings,
        )


def operation(
    root: Path,
    operation_id: str,
    action: str,
    value: dict[str, Any],
    admission_key: str,
    *,
    host_transport: httpx.BaseTransport | None = None,
    embedding_transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """One immutable operation receipt, including initialization/pre-provider failures."""
    if not operation_id:
        raise ValueError("CONTROL_OPERATION_ID_REQUIRED")
    target = root / "operations" / (digest(operation_id) + ".json")
    identity = digest({"action": action, "value": value, "admission_key": admission_key})
    if target.exists():
        _frozen(root)
        old = cast(dict[str, Any], read_json(target))
        if old["input_sha256"] != identity:
            raise ValueError("CONTROL_OPERATION_CHANGED")
        return old
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    trace = Trace(target.with_suffix(".jsonl"), "v13_1_controls")
    output: dict[str, Any] = {
        "operation_id": operation_id,
        "action": action,
        "input_sha256": identity,
        "input": value,
        "admission_key": admission_key,
        "process_id": os.getpid(),
        "status": "INTERRUPTED",
        "first_error": None,
    }
    attempts = {"generation": 0, "embedding": 0}

    def emit(event: dict[str, Any]) -> None:
        if event["event"] in {"vllm_response", "vllm_error"}:
            attempts["embedding" if event["path"] == "embeddings" else "generation"] += 1
        if output["first_error"] is None and event["event"] in {
            "vllm_error",
            "vllm_budget_rejected",
            "vllm_capacity_rejected",
        }:
            output["first_error"] = event
        trace(event)

    def failure(error: Exception) -> None:
        evidence = {"error_type": type(error).__name__, "error": str(error)}
        if output["first_error"] is None:
            output["first_error"] = evidence
        rejected = isinstance(error, ValueError) and any(
            code in str(error)
            for code in (
                "OWNER_SCOPE",
                "BOUNDARY_CHANGED",
                "ORIGINAL_RECORD",
                "UNCLOSED",
                "ORIGINAL_EVENT",
                "CLOSED_BOUNDARY",
                "OPERATION_SCHEMA",
            )
        )
        context_refusal = any(
            code in str(error)
            for code in (
                "HOST_CONTEXT_CAPACITY_EXCEEDED",
                "EMBEDDING_CONTEXT_CAPACITY_EXCEEDED",
                "CONTROL_MATERIAL_CAPACITY_EXCEEDED",
            )
        )
        status = (
            "REJECTED"
            if rejected
            else "CAPACITY_REJECTED"
            if context_refusal
            else (
                "MAINTENANCE_INCOMPLETE"
                if "GENERATION_CAPACITY_EXCEEDED" in str(error)
                else "INTERRUPTED"
            )
        )
        if action == "ingest" and context_refusal:
            status = "MAINTENANCE_INCOMPLETE"
        output.update(status=status, **evidence)

    try:
        frozen = _frozen(root)
        output.update(arm=frozen["arm"], source_sha256=digest(frozen["source_sha256"]))
        output["budget_before"] = read_json(Path(frozen["config"]["budget_path"]))
        emit(
            {
                "event": "control_public_operation",
                "input": value,
                "action": action,
                "input_sha256": identity,
                "process_id": os.getpid(),
                "admission_key": admission_key,
            }
        )
        expected = {
            "ingest": {"owner", "boundary_id", "records"},
            "recall": {"owner", "query"},
            "read": {"owner", "question"},
            "snapshot": {"owner"},
        }
        if action not in expected or set(value) != expected[action]:
            raise ValueError("CONTROL_OPERATION_SCHEMA_INVALID")
        with open_controls(
            root,
            admission_key,
            emit=emit,
            host_transport=host_transport,
            embedding_transport=embedding_transport,
        ) as backend:
            budget = backend.model.client.budget
            assert budget is not None
            output["budget_before"] = json.loads(json.dumps(budget.state))
            try:
                if action == "ingest":
                    result = backend.ingest(value["owner"], value["boundary_id"], value["records"])
                elif action == "recall":
                    result = backend.recall(value["owner"], value["query"])
                elif action == "read":
                    result = backend.read_text(value["owner"], value["question"])
                else:
                    result = backend.snapshot(value["owner"])
                output.update(status=result.get("status", "COMPLETED"), result=result)
            except Exception as error:
                failure(error)
            finally:
                try:
                    output["snapshot_after"] = backend.snapshot(frozen["owner"])
                except Exception as error:
                    output["snapshot_error"] = str(error)
                    failure(error)
                output.update(
                    budget_after=budget.state,
                    generation_admissions_for_boundary=backend.model.calls_in_message,
                )
    except Exception as error:
        failure(error)
    if "budget_before" in output:
        try:
            output["budget_after"] = read_json(Path(frozen["config"]["budget_path"]))
        except Exception as error:
            failure(error)
    output.update(
        wall_ns=time.perf_counter_ns() - wall,
        cpu_ns=time.process_time_ns() - cpu,
        usage=trace.usage,
        resource_bytes={p.name: p.stat().st_size for p in root.glob("*.sqlite*") if p.is_file()},
        logical_snapshot_bytes=len(
            json.dumps(output.get("snapshot_after"), ensure_ascii=False).encode()
        ),
        request_attempts=attempts,
        cost_scope=(
            "full provider reservations/usage; wall/CPU/resources/logical snapshot IO partial"
        ),
        accounting_limit="excludes import/artifact writes; no complete Store IO trace",
        semantic_evidence=False,
    )
    emit({"event": "control_terminal", "status": output["status"]})
    write_json(target, output)
    if output["first_error"] is not None and not (root / "first-error.json").exists():
        write_json(
            root / "first-error.json",
            {"operation_id": operation_id, "first_error": output["first_error"]},
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "ingest", "recall", "read", "snapshot"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--arm", choices=sorted(ARMS))
    parser.add_argument("--owner")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--operation-id")
    parser.add_argument("--admission-key")
    args = parser.parse_args()
    if args.command == "prepare":
        if not all((args.config, args.run_id, args.arm, args.owner)):
            parser.error("prepare requires --config --run-id --arm --owner")
        frozen = prepare(args.config, args.run_root, args.run_id, args.arm, args.owner)
        print(
            json.dumps(
                {
                    "status": "PREPARED_ZERO_HTTP",
                    "arm": frozen["arm"],
                    "source_sha256": digest(frozen["source_sha256"]),
                }
            )
        )
    else:
        if not all((args.input, args.operation_id, args.admission_key)):
            parser.error("operation requires --input --operation-id --admission-key")
        result = operation(
            args.run_root,
            args.operation_id,
            args.command,
            read_json(args.input),
            args.admission_key,
        )
        print(json.dumps({key: result[key] for key in ("status", "process_id", "operation_id")}))
        if result["status"] in {"INTERRUPTED", "MAINTENANCE_INCOMPLETE"}:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
