"""A Host tool over the existing evidence operations and durable read allowance."""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool

from milai_lab.memory.functional import normalize_read_goal
from milai_lab.memory.functional_state import (
    FunctionalIntegrityError,
    FunctionalRejection,
    canonical,
    namespace,
    note_exposure,
    reference_key,
)
from milai_lab.memory.retrieval_request import (
    RetrievalContext,
    RetrievalLimits,
    RetrievalRequest,
    StructuredReadGoal,
)
from milai_lab.memory.working_set import material_ref
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    project_packs,
)
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory
from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    MemoryAction,
    MemoryControlState,
    run_memory_control,
)

TOOL_DESCRIPTION = (
    "Retrieve evidence from existing memory for your current task. Supply the full query; "
    "optionally state the purpose, required evidence points, target scope, as_of time and "
    "references you actually received. Do not prescribe internal search/read/refresh steps. "
    "The result contains evidence, termination_reason and usage, not the final answer. "
    "Keep unverified premises as questions. Use the returned evidence to continue the original "
    "task; request additional material only when needed. A termination reason does not certify "
    "sufficiency. This tool does not save, correct, forget or execute business actions."
)


def material_binding(item: dict[str, Any]) -> dict[str, Any]:
    """Small evaluator trace of actual ranges/versions, outside the policy input."""
    result = {key: copy.deepcopy(item[key]) for key in (
        "kind", "id", "record_id", "revision", "version_view", "visibility", "body_delivered",
        "source_ranges", "context_source_ranges", "focus_source_ranges", "source_bindings",
        "source_observation_read")
        if key in item}
    if "support_turns" in item:
        result["support_turns"] = [{key: turn[key] for key in (
            "source_ref", "source_revision", "range", "role") if key in turn}
            for turn in item["support_turns"]]
    if "applicability" in item:
        result["unit_ids"] = [unit["unit_id"] for unit in item["applicability"]["units"]]
    return result


def retrieval_packet(
    key: str, items: list[dict[str, Any]], indices: list[int], positions: list[int],
    reason: str, usage: dict[str, Any], *, ok: bool = True,
) -> dict[str, Any]:
    """One full return representation for read admission and final delivery."""
    evidence = project_packs(items, indices, compact_view_bindings=True)
    references = dict(zip(indices, positions, strict=True))
    for row in evidence:
        row["ref"] = material_ref(key, references[int(row["label"][1:])])
    return {"ok": ok, "schema": "milai_retrieval_result_v1", "evidence": evidence,
            "termination_reason": reason, "usage": usage}


class IntentRetrievalMemory(FunctionalEditMemory):
    """Opt-in adapter: the Host calls retrieval instead of receiving automatic retrieval."""

    def __init__(self, *args: Any, retrieval_interface: Literal["rich", "query_only"] = "rich",
                 retrieval_observer: Callable[[dict[str, Any]], None] | None = None,
                 replay_initial_observation: dict[str, Any] | None = None,
                 replay_admission_policy: dict[str, Any] | None = None,
                 replay_control_checkpoint: dict[str, Any] | None = None,
                 capture_control_steps: bool = False,
                 control_intervention: FirstActionIntervention | None = None,
                 control_delivery_selection: bool = False,
                 return_envelope: Callable[[dict[str, Any]], Any] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retrieval_interface = retrieval_interface
        self.retrieval_observer = retrieval_observer
        self.replay_initial_observation = replay_initial_observation
        self.replay_admission_policy = replay_admission_policy
        self.replay_control_checkpoint = replay_control_checkpoint
        self.capture_control_steps = capture_control_steps
        self.control_intervention = control_intervention
        self.control_delivery_selection = control_delivery_selection
        self.return_envelope = return_envelope
        self.policy["retrieval_interface"] = retrieval_interface

    def return_tokens(self, packet: dict[str, Any]) -> int:
        """Budget the actual adapter envelope before selecting complete materials."""
        envelope = self.return_envelope(packet) if self.return_envelope else packet
        return self.token_count(canonical(envelope))

    def _read_admission_policy(self) -> dict[str, Any]:
        if self.replay_admission_policy is None:
            return super()._read_admission_policy()
        original = self.replay_admission_policy
        if {k: v for k, v in original.items() if k != "memory_control"} != {
                k: v for k, v in self.policy.items() if k != "memory_control"}:
            raise ValueError("FROZEN_RETRIEVAL_READ_POLICY_CHANGED")
        # Prior calls consumed this exact allowance under the original executor.
        # E2 changes only the next executor; it cannot reset or rewrite those calls.
        return original

    @property
    def read_tool_names(self) -> frozenset[str]:
        return super().read_tool_names | {"milai_retrieve"}

    def model_material(
        self, config: RunnableConfig, *, for_write: bool = False,
        fresh_observations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if for_write or self.forget_requested:
            return super().model_material(config, for_write=for_write,
                                          fresh_observations=fresh_observations)
        return {"ok": True, "schema": "milai_retrieval_context_v1",
                "instructions": "Call milai_retrieve when past evidence is needed. "
                    "Previously returned evidence remains in the actual tool messages.",
                "fresh_observations": fresh_observations or []}

    def tools(self) -> tuple[BaseTool, ...]:
        return self._retrieval_tools()

    def writer_tools(self, config: RunnableConfig) -> tuple[BaseTool, ...]:
        return self.tools()

    def instructions(self) -> str:
        return TOOL_DESCRIPTION

    def _retrieval_tools(self) -> tuple[BaseTool, ...]:
        def milai_retrieve(
            query: str, config: RunnableConfig, *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            read_goal: str | StructuredReadGoal | None = None,
            task_context: RetrievalContext | None = None,
            limits: RetrievalLimits | None = None,
        ) -> ToolMessage:
            request = RetrievalRequest.model_validate({"query": query, **{
                key: value for key, value in (("read_goal", read_goal),
                    ("task_context", task_context), ("limits", limits)) if value is not None}})
            result = self.retrieve(config, tool_call_id, request)
            return ToolMessage(name="milai_retrieve", tool_call_id=tool_call_id,
                               content=canonical(result),
                               status="success" if result["ok"] else "error")

        def query_only(
            query: str, config: RunnableConfig, *,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> ToolMessage:
            return milai_retrieve(query, config, tool_call_id=tool_call_id)

        retrieve = StructuredTool.from_function(
            query_only if self.retrieval_interface == "query_only" else milai_retrieve,
            name="milai_retrieve", description=(TOOL_DESCRIPTION
                if self.retrieval_interface == "rich" else
                "Retrieve evidence from existing memory. Supply a complete query describing "
                "the information needed for the user's task. The tool returns actual evidence, "
                "termination reason and usage; you use it to finish the task. "
                "This interface takes only query; retrieval does not save, correct or forget."))
        # This profile exposes retrieval only. The existing FunctionalEditMemory
        # profile continues to own explicit save/correct/forget tools.
        return (retrieve,)

    def _known_materials(self, request: RetrievalRequest) -> list[dict[str, Any]]:
        materials = []
        for ref in request.task_context.known_evidence_refs:
            stored = self.service.store.get(namespace(self.service), ref.snapshot_id)
            if (stored is None or stored.value.get("schema") != "milai_retrieval_snapshot_v1"
                    or ref.item_index not in stored.value.get("delivered_indices", [])):
                raise FunctionalRejection("RETRIEVAL_REFERENCE_NOT_DELIVERED")
            item = copy.deepcopy(stored.value["materials"][ref.item_index])
            if item["kind"] == "semantic_view":
                current = self.service.read(item["record_id"])
                if not current["ok"] or current["value"]["revision"] != item["revision"]:
                    item["version_view"] = "historical_exact_revision"
            materials.append(item)
        return open_evidence_packs(self.service, materials)

    def retrieve(self, config: RunnableConfig, call_id: str,
                 request: RetrievalRequest) -> dict[str, Any]:
        bound = self._binding(config)
        key = "retrieval:" + reference_key([bound["session"], bound["message_id"], call_id])
        def observe(event: dict[str, Any]) -> None:
            if self.retrieval_observer is not None:
                self.retrieval_observer({"call_id": call_id, **event})

        if self.retrieval_observer is not None:
            observe({"phase": "start", "request": request.project(), "binding": bound,
                     "read_allowance": self.read_allowance(config)})
        try:
            existing = self.service.store.get(namespace(self.service), key)
            if existing is not None:
                saved = existing.value
                if saved["request"] != request.project():
                    raise FunctionalRejection("RETRIEVAL_CALL_CHANGED")
                if self.replay_control_checkpoint is not None:
                    if saved["status"] != "started":
                        raise ValueError("CONTROL_CHECKPOINT_REQUIRES_IN_PROGRESS_CALL")
                    result = self._execute_retrieval(config, call_id, request, key, bound)
                elif saved["status"] != "completed":
                    raise FunctionalIntegrityError("RETRIEVAL_OUTCOME_UNKNOWN")
                else:
                    result = self._retrieval_result(key, saved)
            else:
                result = self._execute_retrieval(config, call_id, request, key, bound)
        except BaseException as error:
            observe({"phase": "failed", "error_type": type(error).__name__, "error": str(error)})
            raise
        observe({"phase": "completed", "result": result,
                 "served_from_cache": existing is not None
                                      and self.replay_control_checkpoint is None})
        return result

    def _execute_retrieval(
        self, config: RunnableConfig, call_id: str, request: RetrievalRequest,
        key: str, bound: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        return_limit = min(self.material_limit,
                           request.limits.max_return_tokens or self.material_limit)
        steps = min(self.control_steps, request.limits.max_control_steps
                    if request.limits.max_control_steps is not None else self.control_steps)
        saved: dict[str, Any] = {"schema": "milai_retrieval_snapshot_v1", "status": "started",
                                "request": request.project(), "return_limit": return_limit}
        self.service.store.put(namespace(self.service), key, saved, index=False)
        checkpoint = self.replay_control_checkpoint
        known = copy.deepcopy(checkpoint["operations"]["known_materials"]) if checkpoint else []
        if checkpoint is None and request.task_context.known_evidence_refs:
            receipt = self._read(config, call_id + ":known",
                {"tool": "memory_control", "known_evidence_refs": [
                    ref.model_dump() for ref in request.task_context.known_evidence_refs]},
                lambda _: {"ok": True, "materials": self._known_materials(request)},
                deliver_material=False)
            if not receipt["ok"]:
                saved.update(status="completed", ok=False, reason=receipt["status"], materials=[],
                    delivered_indices=[], usage={"control_steps": 0,
                        "known_reference_reads": 0, "operations": 0, "read_operations": 0},
                    wall_seconds=time.perf_counter() - started)
                self.service.store.put(namespace(self.service), key, saved, index=False)
                return self._retrieval_result(key, saved)
            known = receipt["materials"]
        state = (MemoryControlState(**copy.deepcopy(checkpoint["state"])) if checkpoint else
                 MemoryControlState(task={"request": request.query,
            "query_time": request.task_context.as_of or "", "mode": "retrieve",
            "read_goal": normalize_read_goal(request.read_goal),
            "retrieval_request": request.project(),
            "known_evidence": project_packs(known, list(range(len(known))))},
            budget={"max_return_tokens": return_limit}))

        def search_pool(query: str, limit: int) -> list[dict[str, Any]]:
            native = self.service.search_sources(query, limit=min(limit, self.source_top_k),
                excluded_source_refs=(bound["source_ref"],), tokenization=self.source_tokenization)
            records = self.service.search(query, limit=min(limit, self.semantic_top_k),
                                          include_raw=False)["records"]
            materials = build_evidence_packs(self.service, request.query,
                request.task_context.as_of or "", native["source_materials"], records,
                tokenization=self.source_tokenization)
            return (self.control_rank_pool(query, materials)
                    if self.control_rank_pool else materials)

        def refresh(messages: list[dict[str, str]], schema: dict[str, Any]) -> dict[str, Any]:
            assert self.dependency_read_call is not None
            return self.dependency_read_call("query_structure", messages, schema)

        def fits_delivery(items: dict[int, dict[str, Any]]) -> bool:
            # Counts are bounded by this call's declared decision budget. Timing
            # stays in the trace, so elapsed-time digits cannot displace evidence.
            usage = {"control_steps": steps, "known_reference_reads": len(known),
                     "operations": steps, "read_operations": steps,
                     "material_budget_rejections": steps}
            reasons: tuple[str, ...] = (
                "policy_handoff", "budget_exhausted", "no_available_operation",
                "operation_outcome_unknown")
            if self.control_intervention is not None:
                reasons += ("intervention_handoff",)
            return all(self.return_tokens(retrieval_packet(
                key, list(items.values()), list(items), list(range(len(items))), reason, usage,
                ok=False))
                <= return_limit for reason in reasons)

        operations = EvidenceOperations(self.service, state,
            load_pool=lambda: search_pool(request.query, self.source_top_k),
            search_pool=search_pool,
            search_batch_sizes=tuple(dict.fromkeys(min(n, self.source_top_k) for n in (8, 16))),
            refresh_call=refresh,
            fits=lambda items: self.token_count(canonical(items)) <= return_limit,
            fits_materials=fits_delivery,
            excluded_source_refs=(bound["source_ref"],),
            known_materials=known,
            view_capacity=self.control_view_capacity, view_policy=self.control_view_policy,
            source_observation=self.control_source_observation,
            delivery_selection=self.control_delivery_selection,
            checkpoint=checkpoint["operations"] if checkpoint else None)
        if self.control_delivery_selection:
            state.budget["acquisition_reads_remaining"] = self.read_allowance(config)[
                "reads_remaining"]
        if self.replay_initial_observation is not None and checkpoint is None:
            expected = copy.deepcopy(self.replay_initial_observation)
            for name in ("remaining_control_steps", "reader_capacity_reserved"):
                expected["budget"].pop(name)
            observed = state.project()
            original_timing = expected["budget"].pop("source_inventory_wall_seconds")
            actual_timing = observed["budget"].pop("source_inventory_wall_seconds")
            if observed != expected:
                raise ValueError("FROZEN_RETRIEVAL_INITIAL_OBSERVATION_CHANGED")
            # E2 supplies the very same original first model observation. Actual
            # replay computation time remains measured separately in the trace.
            state.budget["source_inventory_wall_seconds"] = original_timing
            self.control_record({"event": "frozen_retrieval_initial_observation",
                "original_inventory_wall_seconds": original_timing,
                "actual_inventory_wall_seconds": actual_timing})
        memory = self
        prefix_events = copy.deepcopy(checkpoint["prefix_trace"]) if checkpoint else []

        class AdmittedOperations:
            def actions(self, observed: MemoryControlState) -> list[MemoryAction]:
                actions = operations.actions(observed)
                if memory.control_delivery_selection:
                    remaining = memory.read_allowance(config)["reads_remaining"]
                    observed.budget["acquisition_reads_remaining"] = remaining
                    if not remaining:
                        actions = [a for a in actions if a.kind == "HANDOFF"]
                return actions

            def execute(self, action: MemoryAction, observed: MemoryControlState) -> dict[str, Any]:
                if action.kind == "HANDOFF":
                    return operations.execute(action, observed)
                return memory._read(config, call_id + ":" + str(
                    observed.budget["remaining_control_steps"]),
                    {"tool": "search_memory" if action.kind == "SEARCH" else "memory_control",
                     "request": request.project(), "operation": action.kind,
                     "target": action.target, "parameters": action.parameters},
                    lambda _: operations.execute(action, observed), deliver_material=False)

        def record(event: dict[str, Any]) -> None:
            if self.capture_control_steps and event["phase"] == "operation_result":
                prefix_events.append({k: copy.deepcopy(v)
                                      for k, v in event.items() if k != "phase"})
            if event.get("phase") == "decision_input":
                refs = {span["source_ref"] for item in known for span in [
                    *item.get("source_ranges", []), *item.get("support_turns", []),
                    *item.get("source_bindings", {}).values()]}
                refs.update(operations.observation_source_refs(state))
                with self.service._locked():
                    note_exposure(self.service, bound["source_ref"], sorted(refs))
                # Evaluator-only bindings preserve actual candidates and read outcomes.
                # They are outside before/state and never enter operation_payload.
                event["candidate_materials"] = [material_binding(m) for m in operations.materials]
                event["opened_materials"] = {i: material_binding(m)
                                             for i, m in operations.opened.items()}
                event["known_materials"] = [material_binding(m) for m in known]
                if memory.control_delivery_selection:
                    event["observed_materials"] = {i: material_binding(m)
                                                  for i, m in operations.observed.items()}
            self.control_record({**event, "retrieval_call_id": call_id})
            if self.retrieval_observer is not None and event["phase"] == "decision_input":
                observation = {"call_id": call_id, "phase": "decision_input",
                    "step": event["step"], "before": event["before"], "actions": event["actions"]}
                if self.capture_control_steps:
                    observation.update(read_allowance=self.read_allowance(config),
                        control_checkpoint={"step": event["step"], "state": event["before"],
                            "operations": operations.checkpoint(),
                            "prefix_trace": copy.deepcopy(prefix_events)})
                self.retrieval_observer(observation)

        assert self.control_policy is not None
        result = run_memory_control(state, self.control_policy, AdmittedOperations(),
            max_steps=steps, record=record, can_continue=lambda: self.control_available()
                and (bool(self.read_allowance(config)["reads_remaining"])
                     or (self.control_delivery_selection and bool(operations.observed))),
            intervention=self.control_intervention,
            start_step=checkpoint["step"] if checkpoint else 0,
            prefix_trace=checkpoint["prefix_trace"] if checkpoint else None)
        trace = result["trace"]
        saved.update(status="completed", reason=result["reason"],
            materials=list(operations.opened.values()), indices=list(operations.opened),
            wall_seconds=time.perf_counter() - started,
            usage={"control_steps": len(trace),
                   "known_reference_reads": len(known),
                   "operations": sum("result" in event for event in trace),
                   "material_budget_rejections": sum(event.get("result", {}).get("status")
                       == "material_budget_exhausted" for event in trace)})
        saved["usage"]["read_operations"] = sum(
            any(a["id"] == event["selected"] and a["kind"] == "READ" for a in event["actions"])
            for event in trace)
        packet = self._retrieval_result(key, saved)
        saved["reason"] = packet["termination_reason"]
        saved["delivered_indices"] = [row["ref"]["item_index"] for row in packet["evidence"]]
        self.service.store.put(namespace(self.service), key, saved, index=False)
        with self.service._locked():
            note_exposure(self.service, bound["source_ref"], list(operations.source_refs()))
        self.control_record({"event": "milai_retrieve_result", "call_id": call_id,
                             "request": request.project(), "result": packet,
                             "retrieval_wall_seconds": saved["wall_seconds"],
                             "control": result})
        return packet

    def _retrieval_result(self, key: str, saved: dict[str, Any]) -> dict[str, Any]:
        positions = saved.get("delivered_indices", list(range(len(saved["materials"]))))
        labels = saved.get("indices", list(range(len(saved["materials"]))))
        actual = open_evidence_packs(self.service, [saved["materials"][i] for i in positions])
        packet = retrieval_packet(key, actual, [labels[i] for i in positions], positions,
            saved["reason"], saved["usage"],
            ok=saved.get("ok", saved["reason"] != "operation_outcome_unknown"))
        if self.return_tokens(packet) > saved["return_limit"]:
            raise FunctionalRejection("RETRIEVAL_RETURN_ENVELOPE_EXCEEDS_LIMIT")
        return packet
