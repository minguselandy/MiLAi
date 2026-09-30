"""Opt-in P5 comparison using the original lifecycle engine and public bindings.

T3 native cadence and matched observation cadence are distinct experiments.
Only captured events enter backends. No fixture schedules, scorer, hidden world
or future question is accepted here. W3 requires a real durable UPDATE, never a
read, ADD, raw capture or unchanged replay. Native capability gaps stay visible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any, Literal, cast

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from milai_lab.application.tools import BUSINESS_SCHEMAS
from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.baselines.v13_1_controls import ControlsBackend, event_id, receipt_projection
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import digest, read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, Trace
from milai_lab.integrations.memory.mem0 import (
    MEM0_POLICY,
    Mem0NativeRuntime,
    mem0_dependency_identity,
)
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners import v13_1_controls as controls
from milai_lab.runners import v13_1_d0 as d0
from milai_lab.runners import v13_1_p5 as p5

ARMS = ("B2", "B6", "mem0_trace_equal", "field_grounded")
CADENCES = ("t3_native", "matched_observation_v1")
CLI = d0.LAB / "tools/run_v13_1_p5_compare.py"


def _sources() -> dict[str, str]:
    return {**p5._sources(), CLI.relative_to(d0.LAB).as_posix(): d0._sha(CLI)}


def _parameters(config: dict[str, Any], arm: str) -> dict[str, Any]:
    if arm not in ARMS or config.get("cadence") not in CADENCES:
        raise ValueError("P5_COMPARE_ARM_OR_CADENCE_INVALID")
    projection = config.get("operational_projection", "enabled")
    if type(projection) is not str or projection not in {"enabled", "disabled"}:
        raise ValueError("P5_COMPARE_PROJECTION_INVALID")
    if projection == "disabled" and arm != "field_grounded":
        raise ValueError("P5_COMPARE_EL_REQUIRES_FIELD_GROUNDED")
    native_interface = config.get("mem0_update_interface", "add_only")
    if type(native_interface) is not str or native_interface not in {
        "add_only",
        "manual_update_v1",
    }:
        raise ValueError("P5_COMPARE_MEM0_INTERFACE_INVALID")
    if config["cadence"] == "t3_native" and native_interface != "add_only":
        raise ValueError("P5_COMPARE_NATIVE_T3_IS_ADD_ONLY")
    parameters = controls._parameters(config)
    if arm == "mem0_trace_equal" and config["embedding_dimension"] != 1024:
        raise ValueError("P5_COMPARE_PINNED_MEM0_REQUIRES_DIMENSION_1024")
    return {
        **parameters,
        "arm": arm,
        "cadence": config["cadence"],
        "operational_projection": projection,
        "mem0_update_interface": native_interface,
        "mem0_policy": MEM0_POLICY if arm == "mem0_trace_equal" else None,
        "mem0_formation_route": "add_archive infer=True ADD-only; manual update is separate opt-in"
        if arm == "mem0_trace_equal"
        else None,
        "common_guard": p5.POLICY,
        "source_input": "original captured user/tool SourceEvents; no synthesized receipt",
        "el_contract": "same checked proposal and semantic revision; finite operational view off",
    }


def prepare(fixture: Path, config: Path, root: Path, arm: str) -> dict[str, Any]:
    settings = read_json(config)
    parameters = _parameters(settings, arm)
    # Reuse the exact old DTO/public authorization/catalog validation. The old
    # engine's preparation is temporary; it never overwrites a comparison freeze.
    with TemporaryDirectory() as temporary:
        frozen = p5.prepare(fixture, config, Path(temporary), "field_grounded")
    frozen.update(
        kind="MILAI_V13_1_P5_COMPARE_FREEZE",
        run_id=root.resolve().name,
        scope_arm=arm + ":" + settings["cadence"] + ":" + parameters["operational_projection"],
        source_sha256=_sources(),
        comparison_parameters=parameters,
        comparison_sdk=controls._sdk(),
        native_sdk=mem0_dependency_identity() if arm == "mem0_trace_equal" else None,
        prompt_sha256=hashlib.sha256(settings["reader_system_prompt"].encode()).hexdigest(),
    )
    if arm != "field_grounded":
        frozen["tool_catalog"] = [
            *map(convert_to_openai_tool, _backend_tools(None)),
            *BUSINESS_SCHEMAS,
        ]
        frozen["tool_catalog_sha256"] = digest(frozen["tool_catalog"])
    target = root / "input-freeze.json"
    if target.exists() and read_json(target) != frozen:
        raise ValueError("P5_COMPARE_INPUT_FREEZE_CHANGED")
    write_json(target, frozen)
    return frozen


def _frozen(root: Path) -> dict[str, Any]:
    frozen = cast(dict[str, Any], read_json(root / "input-freeze.json"))
    if frozen["source_sha256"] != _sources() or frozen["comparison_sdk"] != controls._sdk():
        raise ValueError("P5_COMPARE_SOURCE_OR_SDK_CHANGED")
    for kind in ("fixture", "config"):
        if d0._sha(Path(frozen[kind + "_path"])) != frozen[kind + "_sha256"]:
            raise ValueError("P5_COMPARE_INPUT_CHANGED")
    arm = frozen["comparison_parameters"]["arm"]
    if frozen["comparison_parameters"] != _parameters(frozen["config"], arm):
        raise ValueError("P5_COMPARE_PARAMETERS_CHANGED")
    if arm == "mem0_trace_equal" and frozen["native_sdk"] != mem0_dependency_identity():
        raise ValueError("P5_COMPARE_NATIVE_SDK_CHANGED")
    return frozen


class ObservedControls(ControlsBackend):
    """B2/B6 incremental material revision at an actual open observation boundary.

    This is deliberately not closed-turn ingest: no fabricated final assistant
    is added. One SDK item holds current index, revision history and receipts.
    Original source truth remains exclusively in the shared MemoryService.
    """

    def commit_observed(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        state = self._state()
        seen = {event_id(row): row for row in state["archive"]}
        added = []
        for row in records:
            if row["owner"] != self.owner or row["role"] not in {"user", "tool"}:
                raise ValueError("P5_COMPARE_SOURCE_SCOPE_INVALID")
            key = event_id(row)
            if key in seen and seen[key] != row:
                raise ValueError("P5_COMPARE_SOURCE_CHANGED")
            if key not in seen:
                seen[key] = row
                added.append(row)
        if not added:
            return {"status": "no_change", "operation": "NONE"}
        key = digest([event_id(row) for row in added])
        state["archive"].extend(added)
        state["boundaries"][key] = {"status": "RAW_CAPTURED", "source_sha256": digest(added)}
        self._put(state)
        try:
            chunks = self._chunks(state["archive"])
            old = state["index"]
            retained = dict(
                zip((c["id"] for c in old.get("chunks", [])), old.get("vectors", []), strict=True)
            )
            missing = [row for row in chunks if row["id"] not in retained]
            vectors = self.embeddings.embed_documents([row["content"] for row in missing])
            retained.update(zip((row["id"] for row in missing), vectors, strict=True))
            state["index"] = {"chunks": chunks, "vectors": [retained[row["id"]] for row in chunks]}
            if self.arm == "B6":
                state["projection"] = receipt_projection(state["archive"])
            revision = state.get("revision", 0) + 1
            receipt = {
                "status": "COMPLETED",
                "operation": "UPDATE" if revision > 1 else "CREATE",
                "revision": revision,
                "source_ids": [event_id(row) for row in added],
                "mechanism": "SDK durable original-material index revision",
            }
            state["revision"] = revision
            state.setdefault("material_history", []).append(receipt)
            state["boundaries"][key].update(status="COMPLETED", receipt=receipt)
            self._put(state)
            return receipt
        except Exception as error:
            state["boundaries"][key].update(status="MAINTENANCE_INCOMPLETE", error=str(error))
            self._put(state)
            raise


class _EmbeddingBridge:
    """Pinned SDK bridge still owns its lock; helper admits every actual input."""

    def __init__(self, embeddings: MeteredEmbeddings) -> None:
        self.embeddings = embeddings
        self.config = embeddings.client.config
        self.emit = embeddings.client.emit

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if model != self.embeddings.model:
            raise ValueError("P5_COMPARE_NATIVE_EMBED_MODEL_CHANGED")
        return self.embeddings.embed_documents(texts)


class ComparisonRuntime:
    frozen: dict[str, Any]
    service: MemoryService
    scope: FoundationScope
    store: Any
    saver: Any
    model: LangMemRecipeChatModel
    budget: RunBudget
    trace: Trace
    stack: ExitStack
    resource_root: Path
    wrapper: Any
    crash_at: Callable[[str, str, dict[str, Any]], None]

    def __init__(self, **context: Any) -> None:
        self.__dict__.update(context)
        self.settings = self.frozen["config"]
        self.parameters = self.frozen["comparison_parameters"]
        self.arm = self.parameters["arm"]
        self.pending: list[str] = []
        self.last_material: dict[str, Any] = {}
        self.backend: Any = None
        self.formation_namespace = (*self.service.namespace, "p5_compare_formation")
        if self.arm != "field_grounded":
            client = self.stack.enter_context(
                VLLMClient(
                    VLLMConfig(**self.settings["embedding"]), emit=self.trace, budget=self.budget
                )
            )
            embeddings = MeteredEmbeddings(
                client,
                self.settings["embedding"]["model"],
                self.settings["embedding_capacity"],
                dimension=self.settings["embedding_dimension"],
                batch_size=self.settings["embedding_batch"],
            )
            if self.arm in {"B2", "B6"}:
                self.backend = ObservedControls(
                    self.store,
                    self.saver,
                    self.scope.run_id,
                    self.arm,
                    self.scope.user_id,
                    self.settings,
                    self.model,
                    embeddings,
                )
            else:
                self.backend = Mem0NativeRuntime(
                    self.resource_root / "mem0",
                    self.scope.run_id,
                    self.scope.arm_id,
                    self.model.client,
                    cast(VLLMClient, _EmbeddingBridge(embeddings)),
                    admit_generation=self.model._reserve_request,
                )
                self.stack.callback(self.backend.close)

    def observed(self, source_ref: str) -> None:
        if source_ref not in self.pending:
            self.pending.append(source_ref)

    def _sources(self) -> list[dict[str, Any]]:
        # Re-read checked source hashes/owner through the existing public service.
        return [
            cast(dict[str, Any], self.service.source(row["event_id"]))
            for row in self.service.sources()
        ]

    def _formed_ids(self) -> set[str]:
        item = self.store.get(self.formation_namespace, "state")
        return set(item.value["source_ids"]) if item else set()

    def _formation(self) -> None:
        formed = self._formed_ids()
        rows = [row for row in self._sources() if row["event_id"] not in formed]
        if not rows:
            self.pending.clear()
            return
        key = digest([row["event_id"] for row in rows])
        attempt_key = "attempt:" + key
        old = self.store.get(self.formation_namespace, attempt_key)
        if (
            old
            and old.value["status"] not in {"COMPLETED", "PREPARED"}
            and self.arm != "field_grounded"
        ):
            raise ValueError("P5_COMPARE_FORMATION_OUTCOME_UNRESOLVED")
        if old and old.value["status"] == "COMPLETED":
            self.store.put(
                self.formation_namespace,
                "state",
                {"source_ids": sorted(formed | {row["event_id"] for row in rows})},
                index=False,
            )
            self.pending.clear()
            return
        requested = {"source_ids": [row["event_id"] for row in rows], "source_sha256": digest(rows)}
        self.store.put(
            self.formation_namespace,
            attempt_key,
            {"status": "PREPARED", "requested": requested},
            index=False,
        )
        if self.arm != "field_grounded" and self.parameters["cadence"] == "matched_observation_v1":
            self.crash_at(
                "W2",
                "memory_formation",
                {"requested": requested, "mechanism": "native/material formation boundary"},
            )
        self.store.put(
            self.formation_namespace,
            attempt_key,
            {"status": "PENDING", "requested": requested},
            index=False,
        )
        try:
            if self.arm in {"B2", "B6"}:
                receipt = self.backend.commit_observed(rows)
            elif self.arm == "mem0_trace_equal":
                receipt = self.backend.add_archive(self.scope.user_id, rows)
                if receipt["status"] != "COMPLETED":
                    raise ValueError("P5_COMPARE_NATIVE_MAINTENANCE_INCOMPLETE")
            else:
                config = self.scope.config()
                config["configurable"].update(
                    thread_id=str(config["configurable"]["thread_id"]) + ":formation:" + key,
                    v13_session=self.scope.episode_id,
                )
                writer = build_agent(
                    self.model,
                    self.store,
                    self.saver,
                    memory_tools=create_service_tools(self.service, replay_requested=True),
                    business_call_wrapper=self.wrapper,
                    system_prompt=self.settings["writer_system_prompt"],
                )
                self.writer_agent, self.writer_config = writer, config
                state = writer.get_state(config)
                writer.invoke(
                    None
                    if state.next
                    else {
                        "messages": [
                            HumanMessage(
                                id="formation:" + key,
                                content=self.settings["formation_instruction"]
                                + "\n"
                                + json.dumps(rows, ensure_ascii=False),
                            )
                        ]
                    },
                    config=config,
                    durability="sync",
                )
                receipt = {
                    "status": "COMPLETED",
                    "mechanism": "existing service writer",
                    "writer_messages": [
                        m.model_dump(mode="json")
                        for m in writer.get_state(config).values["messages"]
                    ],
                }
            self.store.put(
                self.formation_namespace,
                attempt_key,
                {"status": "COMPLETED", "requested": requested, "receipt": receipt},
                index=False,
            )
            self.store.put(
                self.formation_namespace,
                "state",
                {"source_ids": sorted(formed | {row["event_id"] for row in rows})},
                index=False,
            )
            self.trace({"event": "p5_compare_formation", "arm": self.arm, "receipt": receipt})
            self.pending.clear()
            if (
                receipt.get("operation") == "UPDATE"
                and self.parameters["cadence"] == "matched_observation_v1"
            ):
                self.crash_at(
                    "W3", "memory_formation", {"requested": requested, "receipt": receipt}
                )
        except Exception as error:
            # Keep the original request/error and whatever native durable state exists.
            self.store.put(
                self.formation_namespace,
                attempt_key,
                {"status": "INCOMPLETE", "requested": requested, "first_error": str(error)},
                index=False,
            )
            raise

    def _recall(self, query: str) -> dict[str, Any]:
        if self.arm in {"B2", "B6"}:
            return cast(dict[str, Any], self.backend.recall(self.scope.user_id, query))
        result = (
            self.backend.search_archive(self.scope.user_id, query)
            if self.arm == "mem0_trace_equal"
            else self.service.search(query, include_raw=False)
        )
        material = "[Archived memory material]\n" + json.dumps(result, ensure_ascii=False)
        capacity = self.model.client.capacity
        if capacity is None:
            raise ValueError("P5_COMPARE_HOST_CAPACITY_REQUIRED")
        tokens = capacity.text_tokens(material)
        if tokens > self.settings["controls"]["material_max_tokens"]:
            raise ValueError("CONTROL_MATERIAL_CAPACITY_EXCEEDED")
        return {"material": material, "material_tokens": tokens, "query": query, "result": result}

    def hook(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg = config["configurable"]
        if any(
            cfg[key] != value
            for key, value in {
                "foundation_run_id": self.scope.run_id,
                "arm_id": self.scope.arm_id,
                "user_id": self.scope.user_id,
            }.items()
        ):
            raise ValueError("P5_COMPARE_OWNER_SCOPE_CHANGED")
        unformed_tool = any(
            row["role"] == "tool" and row["event_id"] not in self._formed_ids()
            for row in self._sources()
        )
        if self.parameters["cadence"] == "matched_observation_v1" and unformed_tool:
            self._formation()
        messages = state["messages"]
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        self.last_material = self._recall(str(human.content))
        self.trace({"event": "p5_compare_material", "arm": self.arm, **self.last_material})
        return {
            "llm_input_messages": [
                SystemMessage(
                    content=self.settings["reader_system_prompt"]
                    + "\n"
                    + self.last_material["material"]
                ),
                *messages,
            ]
        }

    def tools(self) -> tuple[BaseTool, ...]:
        if self.arm == "field_grounded":
            return create_service_tools(self.service, replay_requested=True)

        return _backend_tools(self)

    def recovered(self, messages: list[Any]) -> None:
        start = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
            len(messages),
        )
        for message in messages[start + 1 :]:
            if not isinstance(message, ToolMessage) or not message.additional_kwargs.get(
                "application_recovery"
            ):
                continue
            body = json.loads(str(message.content))
            # Capture the actual recovery delivery as UNKNOWN, with no nested
            # query duplicated as a new source. The real query was captured separately.
            if body.get("status") == "ORIGINAL_CALL_OUTCOME_UNKNOWN":
                identity = "recovery-delivery:" + body["original_journal_key"]
                result = self.service.capture_tool(
                    self.scope.episode_id, identity, str(message.name), str(message.content), None
                )
                self.observed(result["source_ref"])

    def completed(self) -> None:
        if self.parameters["cadence"] == "t3_native" and self.arm != "field_grounded":
            self._formation()

    def snapshot(self) -> dict[str, Any]:
        events = (
            [json.loads(line) for line in self.trace.path.read_text().splitlines()]
            if self.trace.path.exists()
            else []
        )
        attempts = {"generation": 0, "embedding": 0}
        for event in events:
            if event["event"] in {"vllm_response", "vllm_error"}:
                attempts["embedding" if event["path"] == "embeddings" else "generation"] += 1
        result = {
            "parameters": self.parameters,
            "material": self.last_material,
            "request_attempts": attempts,
            "backend": (
                self.service.records()
                if self.arm == "field_grounded"
                else self.backend.snapshot(self.scope.user_id)
            ),
            "formation": self.service._rows(self.formation_namespace),
        }
        if hasattr(self, "writer_agent"):
            state = self.writer_agent.get_state(self.writer_config)
            result["writer_checkpoint"] = {
                "next": list(state.next),
                "config": state.config,
                "messages": [m.model_dump(mode="json") for m in state.values.get("messages", [])],
            }
        return result

    def native_update(self, call_id: str, requested: dict[str, Any]) -> dict[str, Any]:
        key = "native-proposal:" + digest([self.scope.episode_id, call_id])
        old = self.store.get(self.formation_namespace, key)
        if old:
            if old.value["requested"] != requested:
                return {"ok": False, "status": "rejected", "reason": "proposal_id_conflict"}
            if old.value["status"] == "COMPLETED":
                return {**old.value["receipt"], "status": "no_change", "replayed": True}
            return {"ok": False, "status": "rejected", "reason": "native_update_outcome_unknown"}
        attempt = {"status": "PREPARED", "requested": requested}
        self.store.put(self.formation_namespace, key, attempt, index=False)
        if (
            self.arm != "mem0_trace_equal"
            or requested["action"] != "update"
            or self.parameters["mem0_update_interface"] != "manual_update_v1"
        ):
            receipt = {
                "ok": False,
                "status": "rejected",
                "reason": "native_method_has_no_requested_operation",
            }
        else:
            result = self.backend.search_archive(self.scope.user_id, requested["target_query"])
            candidates = result.get("results", [])
            if len(candidates) != 1:
                receipt = {"ok": False, "status": "rejected", "reason": "target_not_unique"}
            else:
                target = candidates[0]["id"]
                # Search is scoped by the pinned native user filter. Bind again
                # to actual same-owner public readback before native update.
                attempt.update(status="PENDING", target=target)
                self.store.put(self.formation_namespace, key, attempt, index=False)
                try:
                    before = self._native_readback(target)
                    attempt["before"] = before
                    self.store.put(self.formation_namespace, key, attempt, index=False)
                    if not before["valid"]:
                        raise ValueError("P5_COMPARE_NATIVE_BEFORE_READBACK_INVALID")
                    result = self.backend.memory.update(memory_id=target, text=requested["content"])
                    attempt["native_result"] = result
                    self.store.put(self.formation_namespace, key, attempt, index=False)
                    after = self._native_readback(target)
                    attempt["after"] = after
                    previous_ids = {row["id"] for row in before["history"]}
                    changed = [row for row in after["history"] if row["id"] not in previous_ids]
                    proof = [
                        row
                        for row in changed
                        if row["memory_id"] == target
                        and row["event"] == "UPDATE"
                        and not row.get("is_deleted")
                        and row["old_memory"] == before["record"]["memory"]
                        and row["new_memory"] == requested["content"]
                    ]
                    changed_text = (
                        after["valid"] and after["record"]["memory"] != before["record"]["memory"]
                    )
                    verified = (
                        changed_text
                        and after["record"]["memory"] == requested["content"]
                        and bool(proof)
                    )
                    unchanged = (
                        after["valid"]
                        and after["record"]["memory"] == before["record"]["memory"]
                        and (before["record"]["memory"] == requested["content"] or not changed)
                    )
                    receipt = {
                        "ok": bool(verified or unchanged),
                        "status": "committed"
                        if verified
                        else "no_change"
                        if unchanged
                        else "unknown",
                        "operation": "UPDATE" if verified else "NONE" if unchanged else "UNKNOWN",
                        "id": target,
                        "native_result": result,
                        "semantic_text_changed": bool(changed_text),
                        "update_readback_verified": bool(verified),
                        "content_verification": "unchecked",
                        "fields_verification": "unchecked",
                        "mechanism": "public pinned Mem0 Memory.update; no infer/add substitution",
                        "readback": {"before": before, "after": after, "new_update_rows": proof},
                    }
                    if not receipt["ok"]:
                        attempt.update(
                            status="UNKNOWN", first_error="native_update_readback_not_verified"
                        )
                        receipt["reason"] = attempt["first_error"]
                        attempt["receipt"] = receipt
                        self.store.put(self.formation_namespace, key, attempt, index=False)
                        self.trace(
                            {
                                "event": "p5_compare_native_proposal",
                                "requested": requested,
                                "receipt": receipt,
                            }
                        )
                        return receipt
                except Exception as error:
                    attempt.update(status="UNKNOWN", first_error=str(error))
                    self.store.put(self.formation_namespace, key, attempt, index=False)
                    raise
        attempt.update(status="COMPLETED", receipt=receipt)
        self.store.put(self.formation_namespace, key, attempt, index=False)
        self.trace(
            {"event": "p5_compare_native_proposal", "requested": requested, "receipt": receipt}
        )
        return receipt

    def _native_readback(self, target: str) -> dict[str, Any]:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        calls = 0
        try:
            calls += 1
            scoped = self.backend.snapshot(self.scope.user_id)
            owned = [row for row in scoped if row["id"] == target]
            calls += 1
            record = self.backend.memory.get(target)
            calls += 1
            history = self.backend.memory.history(target)
            # Public get has no owner filter; verify its promoted identity against
            # the actual native owner filter and the independent scoped readback.
            valid = (
                len(owned) == 1
                and isinstance(record, dict)
                and record.get("id") == target
                and record.get("user_id") == self.backend._user_id(self.scope.user_id)
                and type(record.get("memory")) is str
                and record.get("memory") == owned[0].get("memory")
                and isinstance(history, list)
                and all(
                    isinstance(row, dict)
                    and type(row.get("id")) is str
                    and row.get("memory_id") == target
                    for row in history
                )
            )
            # Freeze actual returned values; SDK/fake mutable objects cannot later
            # rewrite the BEFORE evidence during update. No content is repaired.
            result = json.loads(
                json.dumps(
                    {"record": record, "owned_records": owned, "history": history, "valid": valid},
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            self.trace({"event": "p5_compare_native_readback", "target": target, "actual": result})
            return cast(dict[str, Any], result)
        finally:
            self.trace(
                {
                    "event": "p5_compare_native_readback_cost",
                    "calls": calls,
                    "wall_ns": time.perf_counter_ns() - wall,
                    "cpu_ns": time.process_time_ns() - cpu,
                    "generation_requests": 0,
                    "io_scope": "native snapshot/get/history only; partial",
                }
            )


def _backend_tools(runtime: ComparisonRuntime | None) -> tuple[BaseTool, ...]:
    def bound(config: RunnableConfig) -> ComparisonRuntime:
        if runtime is None:
            raise ValueError("P5_COMPARE_CATALOG_ONLY")
        cfg = config["configurable"]
        if any(
            cfg.get(key) != value
            for key, value in {
                "foundation_run_id": runtime.scope.run_id,
                "arm_id": runtime.scope.arm_id,
                "user_id": runtime.scope.user_id,
            }.items()
        ):
            raise ValueError("P5_COMPARE_OWNER_SCOPE_CHANGED")
        return runtime

    def search_memory(query: str, config: RunnableConfig) -> str:
        return json.dumps(bound(config)._recall(query), ensure_ascii=False)

    def read_memory(query: str, config: RunnableConfig) -> str:
        return json.dumps(bound(config)._recall(query), ensure_ascii=False)

    def manage_memory(
        content: str,
        target_query: str,
        config: RunnableConfig,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
        action: Literal["create", "update"] = "update",
    ) -> ToolMessage:
        active = bound(config)
        requested = {"content": content, "target_query": target_query, "action": action}
        receipt = active.native_update(tool_call_id, requested)
        return ToolMessage(
            name="manage_memory",
            tool_call_id=tool_call_id,
            content=json.dumps(receipt, ensure_ascii=False),
            status="success" if receipt["ok"] else "error",
        )

    return tuple(
        StructuredTool.from_function(function, name=name, description=description)
        for function, name, description in (
            (
                search_memory,
                "search_memory",
                "Search actual archived memory; observations grant no authority.",
            ),
            (
                read_memory,
                "read_memory",
                "Read queried native memory through actual same-owner lookup.",
            ),
            (
                manage_memory,
                "manage_memory",
                "Propose a native memory update by natural target query. "
                "Mem0 supports actual public update of a uniquely discovered record; B2/B6 form "
                "original material automatically and reject direct content writes. "
                "Claims are unchecked; manual Mem0 update requires explicit opt-in.",
            ),
        )
    )


class Composition:
    frozen = staticmethod(_frozen)

    @staticmethod
    def service_options(frozen: dict[str, Any]) -> dict[str, Any]:
        return {"operational_projection": frozen["comparison_parameters"]["operational_projection"]}

    @staticmethod
    def open(**context: Any) -> ComparisonRuntime:
        return ComparisonRuntime(**context)


def step(root: Path, case_id: str, message_index: int, **kwargs: Any) -> dict[str, Any]:
    return p5.step(root, case_id, message_index, composition=Composition(), **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "step"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--case-id")
    parser.add_argument("--message-index", type=int)
    parser.add_argument("--phase", choices=("start", "resume"), default="start")
    parser.add_argument("--attempt-id", default="start")
    parser.add_argument("--window", choices=("none", "W1", "W2", "W3"), default="none")
    parser.add_argument("--window-tool")
    parser.add_argument("--hit", type=int, default=1)
    parser.add_argument("--label-available", choices=("true", "false"))
    parser.add_argument("--world-event-id")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.fixture is None or args.config is None or args.arm is None:
            parser.error("prepare requires --fixture/--config/--arm")
        result = prepare(args.fixture, args.config, args.run_root, args.arm)
        print(json.dumps({"status": "prepared", "source_count": len(result["source_sha256"])}))
        return
    if args.case_id is None or args.message_index is None:
        parser.error("step requires --case-id/--message-index")
    result = step(
        args.run_root,
        args.case_id,
        args.message_index,
        phase=args.phase,
        attempt_id=args.attempt_id,
        window=args.window,
        window_tool=args.window_tool,
        hit=args.hit,
        world_event_id=args.world_event_id,
        label_available=None if args.label_available is None else args.label_available == "true",
    )
    print(json.dumps({key: result.get(key) for key in ("status", "error", "attempt_id")}))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
