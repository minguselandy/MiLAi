"""Native MemSyco reader with boundary-Agent formation and a separate MCP query extension."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.benchmark_memories import (
    GenerationAdmission,
    backend_artifact,
    backend_identity,
    phase,
    raw_index,
    raw_retrieve,
    rolling_archive,
    summary_material,
    trace_raw,
    validate_u2,
)
from milai_lab.baselines.langmem_benchmark import (
    FORMATION_INSTRUCTION,
    ArchiveInput,
    agent_query,
    archive_input,
    form,
    formation_key,
    raw_dialogue,
    reader_functions,
    retrieved_material,
    scope_config,
)
from milai_lab.contracts.scope import FoundationScope
from milai_lab.datasets.contextual import HistoryMessage, TaskInput
from milai_lab.datasets.memsyco import MemSycoTask, load_memsyco_tasks
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    digest,
    read_json,
    write_json,
)
from milai_lab.integrations.memory.mem0 import mem0_dependency_identity
from milai_lab.memory.mcp import MemoryMCP
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.langmem_application_runtime import open_application_runtime
from milai_lab.runners.merit_native import (
    finish_job,
    prepare_manifest,
    sha,
    source_identity,
    start_job,
    trace_costs,
    validate_config,
)

ARMS = {"raw_dialogue", "milai", "milai_agent"}
U2_ARMS = {"raw_dialogue", "strong_raw_rag", "rolling_summary", "ordinary_milai", "mem0_native",
           "simplemem_text"}


@contextmanager
def _runtime(config: dict[str, Any], run_id: str, arm: str, root: Path) -> Iterator[Any]:
    if arm == "raw_dialogue" or arm in {
            "strong_raw_rag", "rolling_summary", "mem0_native", "simplemem_text"}:
        budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
            generation_tokens=None, embedding_tokens=None), Path(config["budget_path"]))
        with VLLMClient(VLLMConfig(**config["host"]), budget=budget,
            capacity=HostCapacity(config["capacity"]),
            emit=Trace(root / "trace.jsonl", "unified-memsyco-reader")) as client:
            if "benchmark_memory" in config:
                embed_config = {"base_url": config["embedding"]["base_url"],
                                "model": config["embedding"]["model"],
                                "timeout": config["embedding"].get("timeout", 180)}
                with VLLMClient(VLLMConfig(**embed_config), budget=budget,
                    emit=client.emit) as embedding_client:
                    yield SimpleNamespace(model=SimpleNamespace(client=client),
                                          embedding_client=embedding_client)
            else:
                yield SimpleNamespace(model=SimpleNamespace(client=client))
    else:
        with open_application_runtime(config, run_id, arm, root, "unified-memsyco",
                                      enable_projection=False) as runtime:
            yield runtime


def _config(config: dict[str, Any]) -> None:
    validate_config(config)
    if (config["formation_instruction"] != FORMATION_INSTRUCTION
            or config["reader"] != {"current_date": "2025-06-01", "extra_instruction": ""}
            or type(config["retrieval"]["limit"]) is not int or config["retrieval"]["limit"] <= 0
            or type(config["retrieval"]["material_max_chars"]) is not int
            or config["retrieval"]["material_max_chars"] <= 0
            or not isinstance(config["agent_query"]["system_prompt"], str)
            or not config["agent_query"]["system_prompt"]):
        raise ValueError("MEMSYCO_NATIVE_CONFIG_INVALID")


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, selection = read_json(args.config), read_json(args.selection)
    _config(config)
    u2 = "benchmark_memory" in config
    if u2:
        validate_u2(config)
    if args.arm not in (U2_ARMS if u2 else ARMS) or (
            args.arm == "milai_agent" and args.formation_root is None):
        raise ValueError("MEMSYCO_ARM_INVALID")
    tasks = load_memsyco_tasks(args.selection, group=args.group)
    root = Path(selection["external_root"])
    for source in selection["source_files"]:
        if sha(root / source["relative_path"]) != source["sha256"]:
            raise ValueError("MEMSYCO_SOURCE_CHANGED")
    jobs = [{"job_id": row.case_id, "track": row.track, "owner": row.task.user_id,
             "history_id": row.task.history_id, "history_sha256": digest([
                 asdict(item) for item in row.task.history])} for row in tasks]
    runtime_tasks = {"kind": "MILAI_MEMSYCO_RUNTIME_TASKS", "tasks": [asdict(row) for row in tasks]}
    task_bytes = (json.dumps(runtime_tasks, ensure_ascii=False, indent=2) + "\n").encode()
    peer = MemoryMCP(InMemoryStore(), args.run, args.arm, "schema-only",
                     read_only=args.arm == "milai_agent")
    # Tools bind an explicit Store; schema construction does not open the peer or do I/O.
    sources = {"baselines/common.py": sha(root / "baselines/common.py")}
    for track in {row.track for row in tasks}:
        reader_functions(root, track)
        relative = f"evaluation/task_{track}.py"
        sources[relative] = sha(root / relative)
    identity = {**source_identity(lab_root), "benchmark": "memsyco", "run_id": args.run,
        "arm_id": args.arm, "group": args.group, "recipe_id": config["recipe_id"],
        "config": config, "config_path": str(args.config.resolve()),
        "config_sha256": sha(args.config), "selection_path": str(args.selection.resolve()),
        "selection_sha256": sha(args.selection), "source_commit": selection["source_commit"],
        "source_files": selection["source_files"], "external_root": str(root.resolve()),
        "reader_source_sha256": sources,
        "runtime_tasks_sha256": hashlib.sha256(task_bytes).hexdigest(),
        "runtime_input": "prepare-sanitized TaskInput; execution never parses source gold fields",
        "runtime_root": str(args.runtime_root.resolve()), "budget_path": config["budget_path"],
        "memory_tool_catalog": peer.catalog if args.arm in {"milai", "milai_agent",
                                                            "ordinary_milai"} else [],
        "formation_instruction": config["formation_instruction"],
        "formation_cadence": "archive boundary Agent, not dialogue-as-live replay",
        "formation_cache_excludes": ["question", "answer", "gold"],
        "reader": {**config["reader"], "upstream_temperature": 0.2,
                   "local_temperature": config["host"]["temperature"],
                   "raw_label": "Earlier conversation",
                   "memory_label": "Retrieved memories from earlier conversation"},
        "formation_root": str(args.formation_root.resolve()) if args.formation_root else None,
        "rubric_read_by_runner": False,
        "agent_query_contract": "separate interface; read-only, zero tool calls permitted"}
    histories: dict[str, Any] | None = None
    if u2:
        if args.arm == "mem0_native":
            identity["mem0_dependency"] = mem0_dependency_identity()
        if args.arm == "simplemem_text":
            from milai_lab.integrations.memory.simplemem import (
                dependency_identity,
                validate_simplemem,
            )

            identity["simplemem_dependency"] = dependency_identity(validate_simplemem(config))
            identity["memory_tool_catalog"] = []
            identity["formation_contract"] = (
                "question-free archive; native core writer, not Host CRUD")
            identity["agent_query_contract"] = "NA: common native reader, no Agent query extension"
        histories = _history_inputs(tasks, identity, jobs)
        identity.update({"backend": backend_identity(args.arm),
            "runtime_histories_sha256": digest(histories),
            "exact_history_units": len(histories["histories"]),
            "exact_history_reuse_opportunities": len(jobs) - len(histories["histories"]),
            "formation_cadence": "question-free run-history, then fresh read-only native reader",
            "archive_batch_rule": "maximal whole completed-turn prefix fitting summary capacity; "
                                  "last two completed turns remain raw; no text truncation"})
        if args.arm == "simplemem_text":
            identity["archive_batch_rule"] = (
                "native 40 dialogues/overlap2; complete ordered archive; final process_remaining; "
                "short flush has no cross-flush overlap/previous_entries update")
    if args.arm == "milai_agent":
        formation = read_json(args.formation_root / "run_manifest.json")
        old = formation["identity"]
        if (old["benchmark"] != "memsyco" or old["arm_id"] != "milai"
                or old["selection_sha256"] != identity["selection_sha256"]
                or old["source_sha256"] != identity["source_sha256"]
                or old["config_sha256"] != identity["config_sha256"]):
            raise ValueError("MEMSYCO_FORMATION_IDENTITY_CHANGED")
        identity["formation_identity_sha256"] = digest(old)
    receipt = prepare_manifest(args, identity, jobs)
    task_path = args.runtime_root / "runtime-tasks.json"
    if task_path.exists() and task_path.read_bytes() != task_bytes:
        raise ValueError("MEMSYCO_RUNTIME_TASKS_CHANGED")
    if not task_path.exists():
        write_json(task_path, runtime_tasks)
    if histories is not None:
        path = args.runtime_root / "runtime-histories.json"
        if path.exists() and read_json(path) != histories:
            raise ValueError("MEMSYCO_RUNTIME_HISTORIES_CHANGED")
        if not path.exists():
            write_json(path, histories)
    return receipt


def _answer(client: Any, system: str, question: str) -> dict[str, Any]:
    receipt = client.chat([{"role": "system", "content": system},
                           {"role": "user", "content": question.strip()}])
    if len(receipt.get("choices", [])) != 1:
        raise ValueError("MEMSYCO_READER_RESPONSE_INVALID")
    choice = receipt["choices"][0]
    message = choice["message"]
    if (choice.get("finish_reason") != "stop" or message.get("tool_calls")
            or not isinstance(message.get("content"), str) or not message["content"].strip()):
        raise ValueError("MEMSYCO_READER_RESPONSE_INCOMPLETE")
    return {"answer": message["content"], "host_receipt": receipt}


def _method(identity: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    config = identity["config"]
    return {"recipe": config["recipe_id"], "host": config["host"],
            "embedding": config["embedding"], "formation": config["formation_instruction"],
            "tool_catalog": catalog, "source_sha256": identity["source_sha256"],
            "memory_contract": "strict", "transport": "mcp_http"}


def _history_inputs(tasks: list[MemSycoTask], identity: dict[str, Any],
                    jobs: list[dict[str, Any]]) -> dict[str, Any]:
    method = {**_method(identity, identity["memory_tool_catalog"]),
              "backend": backend_identity(identity["arm_id"]),
              "config_sha256": identity["config_sha256"],
              "backend_dependency": identity.get("mem0_dependency"),
              **({"simplemem_dependency": identity["simplemem_dependency"]}
                 if "simplemem_dependency" in identity else {})}
    units: dict[str, Any] = {}
    for task, job in zip(tasks, jobs, strict=True):
        archive = archive_input(task.task)
        key = formation_key(archive, method)
        job["build_history_id"] = key
        units.setdefault(key, {"history_id": key, "archive": asdict(archive),
                               "archive_sha256": digest(asdict(archive)),
                               "method_sha256": digest(method)})
    return {"kind": "MILAI_MEMSYCO_RUNTIME_HISTORIES", "histories": list(units.values())}


def _prepared_u2(args: Any, lab_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = read_json(args.runtime_root / "run_manifest.json")
    identity = manifest["identity"]
    if ("backend" not in identity or args.arm not in U2_ARMS
            or any(identity.get(key) != value for key, value in source_identity(lab_root).items())
            or identity["config_sha256"] != sha(args.config)
            or identity["selection_sha256"] != sha(args.selection)
            or read_json(args.prepared)["identity_sha256"] != digest(identity)
            or (identity["run_id"], identity["arm_id"], identity["group"],
                identity["runtime_root"]) != (
                    args.run, args.arm, args.group, str(args.runtime_root.resolve()))):
        raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    _config(identity["config"])
    validate_u2(identity["config"])
    if args.arm == "mem0_native" and identity["mem0_dependency"] != mem0_dependency_identity():
        raise ValueError("BENCHMARK_MEM0_SOURCE_CHANGED")
    if args.arm == "simplemem_text":
        from milai_lab.integrations.memory.simplemem import dependency_identity, validate_simplemem

        if identity["simplemem_dependency"] != dependency_identity(
                validate_simplemem(identity["config"])):
            raise ValueError("SIMPLEMEM_DEPENDENCY_CHANGED")
    hashes = {row["relative_path"]: row["sha256"] for row in identity["source_files"]}
    hashes.update(identity["reader_source_sha256"])
    if any(sha(Path(identity["external_root"]) / relative) != expected
           for relative, expected in hashes.items()):
        raise ValueError("MEMSYCO_SOURCE_CHANGED")
    histories = read_json(args.runtime_root / "runtime-histories.json")
    if (histories.get("kind") != "MILAI_MEMSYCO_RUNTIME_HISTORIES"
            or digest(histories) != identity["runtime_histories_sha256"]):
        raise ValueError("MEMSYCO_RUNTIME_HISTORIES_CHANGED")
    return manifest, histories


@contextmanager
def _mem0(runtime: Any, path: Path, run_id: str, arm: str,
          admission: Any = None) -> Iterator[Any]:
    from milai_lab.integrations.memory.mem0 import Mem0NativeRuntime

    native = Mem0NativeRuntime(path, run_id, arm, runtime.model.client,
                              runtime.embedding_client, admit_generation=admission)
    try:
        yield native
    finally:
        native.close()


def run_history(args: Any, *, lab_root: Path) -> dict[str, Any]:
    """Execute a frozen question-free archive unit once, independently from query jobs."""
    manifest, histories = _prepared_u2(args, lab_root)
    matches = [row for row in histories["histories"] if row["history_id"] == args.history]
    if len(matches) != 1:
        raise ValueError("MEMSYCO_HISTORY_UNKNOWN")
    unit = matches[0]
    attempts = manifest.setdefault("history_attempts", {})
    if args.history in attempts:
        raise ValueError("MEMSYCO_HISTORY_ALREADY_ATTEMPTED")
    terminal = {"COMPLETED", "FAILED", "DEGRADED_NATIVE", "INCOMPLETE"} if (
        args.arm == "simplemem_text") else {"COMPLETED", "FAILED"}
    if any(attempts.get(row["history_id"], {}).get("status") not in terminal
           for row in histories["histories"][:histories["histories"].index(unit)]):
        raise ValueError("MEMSYCO_HISTORY_ORDER")
    root = args.runtime_root / "histories" / args.history
    if root.exists():
        raise ValueError("MEMSYCO_HISTORY_RUNTIME_DIRTY")
    attempts[args.history] = {"status": "STARTED"}
    manifest["status"] = "RUNNING"
    write_json(args.runtime_root / "run_manifest.json", manifest)
    root.mkdir(parents=True)
    fields = unit["archive"]
    archive = ArchiveInput(fields["user_id"], fields["history_id"],
                           tuple(HistoryMessage(**row) for row in fields["history"]))
    records = [asdict(row) for row in archive.history]
    config = manifest["identity"]["config"]
    run_id = args.run + ":history:" + args.history
    try:
        with _runtime(config, run_id, args.arm, root) as runtime:
            client = runtime.model.client
            before = copy.deepcopy(client.budget.state)
            result: dict[str, Any] = {"status": "COMPLETED", "history_id": args.history,
                "archive_sha256": unit["archive_sha256"], "owner": archive.user_id,
                "scope": {"foundation_run_id": run_id, "arm_id": args.arm,
                          "user_id": archive.user_id}, "budget_before": before}
            if args.arm == "rolling_summary":
                result["built"] = rolling_archive(client, records)
            elif args.arm == "strong_raw_rag":
                with phase(client, "raw_index_build"):
                    result["built"] = raw_index(records, lambda texts:
                        runtime.embedding_client.embed(texts, config["embedding"]["model"]))
                trace_raw(client, result["built"], stage="index")
            elif args.arm == "ordinary_milai":
                with MemoryMCP(runtime.store, run_id, args.arm, archive.user_id,
                    emit=client.emit, timeout=max(config["host"]["timeout"],
                    config["embedding"].get("timeout", 180))) as peer:
                    with phase(client, "formation"):
                        result["built"] = form(runtime, peer, archive, run_id, args.arm,
                                               config["formation_instruction"])
            elif args.arm == "simplemem_text":
                from milai_lab.integrations.memory.simplemem import (
                    SimpleMemTextRuntime,
                    validate_simplemem,
                )

                native = SimpleMemTextRuntime(root / "simplemem", run_id, args.arm, archive.user_id,
                    client, runtime.embedding_client, validate_simplemem(config),
                    admit_generation=GenerationAdmission())
                if native.snapshot(archive.user_id):
                    raise ValueError("BENCHMARK_MEMORY_NAMESPACE_DIRTY")
                with phase(client, "simplemem_formation"):
                    result["built"] = native.add_archive(archive.user_id, records)
                if result["built"]["status"] != "COMPLETED":
                    result["status"] = result["built"]["status"]
                native.close()
            elif args.arm == "mem0_native":
                with _mem0(runtime, root / "mem0", run_id, args.arm,
                           GenerationAdmission()) as native:
                    if native.snapshot(archive.user_id, measure=True):
                        raise ValueError("BENCHMARK_MEMORY_NAMESPACE_DIRTY")
                    with phase(client, "formation"):
                        result["built"] = native.add_archive(archive.user_id, records)
                    if result["built"]["status"] != "COMPLETED":
                        result["status"] = "MAINTENANCE_INCOMPLETE"
            else:
                result["built"] = {"raw_archive_sha256": unit["archive_sha256"],
                                   "semantic_model_calls": 0}
            result["budget_after"] = copy.deepcopy(client.budget.state)
        result["costs"] = trace_costs(root)
        path = root / "formation.json"
        backend_artifact(path, client, result)
        attempts[args.history] = {"status": result["status"] if args.arm == "simplemem_text"
                                  else "COMPLETED" if result["status"] == "COMPLETED"
                                  else "FAILED", "output": str(path), "sha256": sha(path)}
        manifest["status"] = "HISTORIES_READY" if all(
            attempts.get(row["history_id"], {}).get("status") == "COMPLETED"
            for row in histories["histories"]) else "PARTIALLY_COMPLETED"
        write_json(args.runtime_root / "run_manifest.json", manifest)
        write_json(args.output, result)
        return result
    except BaseException as error:
        write_json(root / "failure.json", {"status": "FAILED", "error_type": type(error).__name__,
                                          "message": str(error), "costs": trace_costs(root)})
        attempts[args.history] = {"status": "FAILED", "error_type": type(error).__name__}
        manifest["status"] = "PARTIALLY_COMPLETED"
        write_json(args.runtime_root / "run_manifest.json", manifest)
        raise


def _run_u2_query(args: Any, row: MemSycoTask, identity: dict[str, Any],
                  manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    job = next(value for value in manifest["jobs"] if value["job_id"] == args.job)
    key = job["build_history_id"]
    attempt = manifest.get("history_attempts", {}).get(key, {})
    path = args.runtime_root / "histories" / key / "formation.json"
    ready = {"COMPLETED", "DEGRADED_NATIVE", "INCOMPLETE"} if (
        args.arm == "simplemem_text") else {"COMPLETED"}
    if attempt.get("status") not in ready or attempt.get("sha256") != sha(path):
        raise ValueError("MEMSYCO_HISTORY_NOT_COMPLETED")
    formed = read_json(path)
    if (formed["owner"] != row.task.user_id or formed["archive_sha256"] != digest(
            asdict(archive_input(row.task))) or formed["history_id"] != key
            or formed["scope"] != {"foundation_run_id": args.run + ":history:" + key,
                                   "arm_id": args.arm, "user_id": row.task.user_id}):
        raise ValueError("MEMSYCO_FORMATION_CACHE_CHANGED")
    config = identity["config"]
    scope = formed["scope"]
    run_id, arm = scope["foundation_run_id"], scope["arm_id"]
    with _runtime(config, run_id, arm, root) as runtime:
        client = runtime.model.client
        backend_artifact(path, client)
        before = copy.deepcopy(client.budget.state)
        prompt_fn, format_fn = reader_functions(Path(identity["external_root"]), row.track)
        result: dict[str, Any] = {"status": "COMPLETED", "case_id": row.case_id,
            "track": row.track, "arm": arm, "owner": row.task.user_id,
            "question": row.task.question, "build_history_id": key,
            "build_receipt_sha256": sha(path), "budget_before": before}
        if arm == "simplemem_text":
            result["formation_status"] = formed["status"]
        label = "Retrieved memories from earlier conversation"
        if arm == "raw_dialogue":
            material, label = raw_dialogue(row.task), "Earlier conversation"
        elif arm == "rolling_summary":
            material = summary_material(formed["built"],
                                       [asdict(message) for message in row.task.history])
        elif arm == "strong_raw_rag":
            with phase(client, "retrieval"):
                selected = raw_retrieve(formed["built"], row.task.question,
                    lambda texts: runtime.embedding_client.embed(
                        texts, config["embedding"]["model"]))
            result.update(selected)
            trace_raw(client, selected, stage="retrieval")
            material = selected["material"]
        elif arm == "ordinary_milai":
            with MemoryMCP(runtime.store, run_id, arm, row.task.user_id, read_only=True,
                emit=client.emit, timeout=max(config["host"]["timeout"],
                config["embedding"].get("timeout", 180))) as peer:
                current = scope_config(FoundationScope(run_id, arm, row.task.user_id, "reader"))
                prior = peer.records(current)
                if prior != formed["built"]["records_after"]:
                    raise ValueError("MEMSYCO_FORMATION_SNAPSHOT_CHANGED")
                with phase(client, "retrieval"):
                    retrieved_rows = peer.retrieve(row.task.question,
                                                   config["retrieval"]["limit"], current)
                material, ids, omitted = retrieved_material(retrieved_rows, format_fn,
                    config["retrieval"]["material_max_chars"])
                after = peer.records(current)
                result.update({"retrieved": retrieved_rows, "delivered_ids": ids,
                               "omitted_ids": omitted,
                               "records_before": prior, "records_after": after})
                if after != prior:
                    raise ValueError("BENCHMARK_READ_ONLY_SNAPSHOT_CHANGED")
        elif arm == "simplemem_text":
            from milai_lab.integrations.memory.simplemem import (
                SimpleMemTextRuntime,
                material_rows,
                validate_simplemem,
            )

            admission = GenerationAdmission()
            native = SimpleMemTextRuntime(path.parent / "simplemem", run_id, arm, row.task.user_id,
                client, runtime.embedding_client, validate_simplemem(config),
                admit_generation=admission)
            prior = native.snapshot(row.task.user_id)
            if prior != formed["built"]["records_after"]:
                raise ValueError("MEMSYCO_FORMATION_SNAPSHOT_CHANGED")
            with phase(client, "simplemem_retrieval"):
                selected = native.search_archive(row.task.user_id, row.task.question)
            material, ids, omitted = retrieved_material(material_rows(selected["results"]),
                format_fn, config["retrieval"]["material_max_chars"])
            after = native.snapshot(row.task.user_id)
            result.update({"retrieved": selected, "delivered_ids": ids, "omitted_ids": omitted,
                           "records_before": prior, "records_after": after})
            if after != prior:
                raise ValueError("BENCHMARK_READ_ONLY_SNAPSHOT_CHANGED")
            native.close()
        else:
            with _mem0(runtime, path.parent / "mem0", run_id, arm) as native:
                prior = native.snapshot(row.task.user_id, measure=True)
                if prior != formed["built"]["records_after"]:
                    raise ValueError("MEMSYCO_FORMATION_SNAPSHOT_CHANGED")
                with phase(client, "retrieval"):
                    selected = native.search_archive(row.task.user_id, row.task.question)
                rows = [{"id": value["id"], "value": {"content": value["memory"]}}
                        for value in selected["results"]]
                material, ids, omitted = retrieved_material(rows, format_fn, 16000)
                after = native.snapshot(row.task.user_id, measure=True)
                result.update({"retrieved": selected, "delivered_ids": ids, "omitted_ids": omitted,
                               "records_before": prior, "records_after": after})
                if after != prior:
                    raise ValueError("BENCHMARK_READ_ONLY_SNAPSHOT_CHANGED")
        if arm == "simplemem_text":
            admission()  # Planning/reflection and this actual final reader share query12.
        with phase(client, "reader"):
            result.update(_answer(client, prompt_fn(config["host"]["model"],
                config["reader"]["current_date"], material, label), row.task.question))
        result.update({"material": material, "budget_after": copy.deepcopy(client.budget.state)})
    result["costs"] = trace_costs(root)
    write_json(root / "result.json", result)
    write_json(args.output, result)
    finish_job(args, manifest, "COMPLETED", root / "result.json")
    return result


def run(args: Any, *, lab_root: Path) -> dict[str, Any]:
    current = read_json(args.runtime_root / "run_manifest.json")
    frozen_identity = current["identity"]
    if "backend" in frozen_identity:
        _prepared_u2(args, lab_root)
    _config(read_json(args.config))
    if (any(frozen_identity.get(key) != value for key, value in source_identity(lab_root).items())
            or frozen_identity["config_sha256"] != sha(args.config)
            or frozen_identity["selection_sha256"] != sha(args.selection)
            or (frozen_identity["run_id"], frozen_identity["arm_id"], frozen_identity["group"],
                frozen_identity["runtime_root"]) != (
                    args.run, args.arm, args.group, str(args.runtime_root.resolve()))):
        raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    source_root = Path(frozen_identity["external_root"])
    source_hashes = {row["relative_path"]: row["sha256"] for row in frozen_identity["source_files"]}
    source_hashes.update(frozen_identity["reader_source_sha256"])
    if any(sha(source_root / relative) != expected for relative, expected in source_hashes.items()):
        raise ValueError("MEMSYCO_SOURCE_CHANGED")
    task_path = args.runtime_root / "runtime-tasks.json"
    if sha(task_path) != frozen_identity["runtime_tasks_sha256"]:
        raise ValueError("MEMSYCO_RUNTIME_TASKS_CHANGED")
    runtime_tasks = read_json(task_path)
    if runtime_tasks["kind"] != "MILAI_MEMSYCO_RUNTIME_TASKS":
        raise ValueError("MEMSYCO_RUNTIME_TASKS_INVALID")
    (raw,) = [value for value in runtime_tasks["tasks"] if value["case_id"] == args.job]
    fields = dict(raw["task"], history=tuple(HistoryMessage(**message)
                                            for message in raw["task"]["history"]))
    row = MemSycoTask(raw["case_id"], raw["track"], TaskInput(**fields))
    manifest, _job, root = start_job(args, identity=current["identity"], jobs=current["jobs"])
    identity, config = current["identity"], current["identity"]["config"]
    task = row.task
    run_id, arm = args.run + ":" + args.job, args.arm
    try:
        if "backend" in identity:
            return _run_u2_query(args, row, identity, manifest, root)
        if args.arm == "milai_agent":
            if str(args.formation_root.resolve()) != identity["formation_root"]:
                raise ValueError("MEMSYCO_FORMATION_IDENTITY_CHANGED")
            formation_path = args.formation_root / "jobs" / args.job / "formation.json"
            frozen = read_json(formation_path)
            formation_identity = read_json(args.formation_root / "run_manifest.json")["identity"]
            expected_key = formation_key(archive_input(task), _method(formation_identity,
                                        formation_identity["memory_tool_catalog"]))
            if (digest(formation_identity) != identity["formation_identity_sha256"]
                    or frozen["cache_key"] != expected_key or frozen["status"] != "COMPLETED"):
                raise ValueError("MEMSYCO_FORMATION_CACHE_CHANGED")
            run_id, arm = frozen["scope"]["foundation_run_id"], frozen["scope"]["arm_id"]
        # The runtime owns the only RunBudget; formation, embeddings and reader share it.
        with _runtime(config, run_id, arm, root) as runtime:
            stage = "reader"
            original_emit = runtime.model.client.emit

            def emit(event: dict[str, Any]) -> None:
                if original_emit is not None:
                    original_emit({"benchmark_phase": stage, **event})

            runtime.model.client.emit = emit
            budget_before = copy.deepcopy(runtime.model.client.budget.state)
            prompt_fn, format_fn = reader_functions(source_root, row.track)
            if args.arm == "raw_dialogue":
                emit({"event": "benchmark_phase", "phase": stage})
                material, label = raw_dialogue(task), "Earlier conversation"
                result = _answer(runtime.model.client, prompt_fn(config["host"]["model"],
                    config["reader"]["current_date"], material, label), task.question)
            else:
                with MemoryMCP(runtime.store, run_id, arm, task.user_id, emit=emit,
                    read_only=args.arm == "milai_agent", timeout=max(config["host"]["timeout"],
                    config["embedding"].get("timeout", 180))) as peer:
                    if args.arm == "milai_agent":
                        if peer.records(scope_config(FoundationScope(run_id, arm, task.user_id,
                                                       "snapshot-guard"))) != frozen[
                                                           "records_after"]:
                            raise ValueError("MEMSYCO_FORMATION_SNAPSHOT_CHANGED")
                        stage = "agent_query"
                        emit({"event": "benchmark_phase", "phase": stage})
                        result = agent_query(runtime, peer, task, run_id, arm,
                                             config["agent_query"]["system_prompt"])
                    else:
                        stage = "formation"
                        emit({"event": "benchmark_phase", "phase": stage})
                        formation_before = copy.deepcopy(runtime.model.client.budget.state)
                        formed = form(runtime, peer, archive_input(task), run_id, arm,
                                      config["formation_instruction"])
                        formed.update({"cache_key": formation_key(archive_input(task),
                            _method(identity, peer.catalog)), "budget_before": formation_before,
                            "budget_after": copy.deepcopy(runtime.model.client.budget.state)})
                        write_json(root / "formation.json", formed)
                        stage = "retrieval"
                        emit({"event": "benchmark_phase", "phase": stage})
                        retrieve_before = copy.deepcopy(runtime.model.client.budget.state)
                        retrieved = peer.retrieve(task.question, config["retrieval"]["limit"],
                            scope_config(FoundationScope(run_id, arm, task.user_id, "reader")))
                        material, ids, omitted = retrieved_material(retrieved, format_fn,
                            config["retrieval"]["material_max_chars"])
                        emit({"event": "benchmark_retrieval", "query": task.question,
                              "retrieved": retrieved, "delivered_ids": ids, "omitted_ids": omitted,
                              "material": material, "budget_before": retrieve_before,
                              "budget_after": copy.deepcopy(runtime.model.client.budget.state)})
                        stage = "reader"
                        emit({"event": "benchmark_phase", "phase": stage})
                        result = _answer(runtime.model.client, prompt_fn(config["host"]["model"],
                            config["reader"]["current_date"], material,
                            "Retrieved memories from earlier conversation"), task.question)
                        result.update({"retrieved": retrieved, "delivered_ids": ids,
                                       "omitted_ids": omitted, "material": material})
                    result["ordinary_records_after"] = peer.records(scope_config(FoundationScope(
                        run_id, arm, task.user_id, "final-readback")))
            result.update({"status": "COMPLETED", "case_id": row.case_id, "track": row.track,
                "arm": args.arm, "question": task.question, "owner": task.user_id,
                "budget_before": budget_before,
                "budget_after": copy.deepcopy(runtime.model.client.budget.state)})
            write_json(root / "result.json", result)
        result["costs"] = trace_costs(root)
        write_json(root / "result.json", result)
        write_json(args.output, result)
        finish_job(args, manifest, "COMPLETED", root / "result.json")
        return result
    except BaseException as error:
        write_json(root / "failure.json", {"status": "FAILED", "error_type": type(error).__name__,
                                          "message": str(error), "costs": trace_costs(root)})
        finish_job(args, manifest, "FAILED", error=error)
        raise
