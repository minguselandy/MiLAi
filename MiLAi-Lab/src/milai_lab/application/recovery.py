"""Resume unknown application actions using a separately recorded real query."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from milai_lab.application.document_publication import DOCUMENT_MUTATIONS, document_recovery_effect
from milai_lab.application.journal import BusinessActionJournal, UnknownBusinessAction
from milai_lab.application.tools import _business_tools, document_business_tools
from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import VerifiedObjectRef

if TYPE_CHECKING:
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from milai_lab.application.adapters import ApplicationAdapter
    from milai_lab.application.functional import FunctionalApplication
    from milai_lab.contracts.scope import FoundationScope


class UnknownModelRequest(RuntimeError):
    """A model request lost its response; this does not imply a semantic commit."""


class UnknownSemanticCommit(RuntimeError):
    """An issued semantic operation needs reconciliation by its original ID."""


def resume_request(
    app: FunctionalApplication,
    adapter: ApplicationAdapter,
    request_id: str,
    *,
    requirements: dict[str, Any] | None = None,
    current: Mapping[str, Any] | None = None,
    save_result: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    reconcile_memory: Callable[[str], dict[str, Any] | None] | None = None,
    feedback: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Continue full request requirements using the existing receipt progress.

    Requirements contain target, steps, save_result and feedback. Each step has
    id, operation, arguments, completed (literal observed fields), and optionally
    arguments_from_state (argument -> actual observed field). The caller supplies
    this trusted plan; it is neither model inference nor application permission.

    Current controls readonly, allow_memory, allow_feedback and
    new_semantic_attempt. Business permission is always the adapter's CURRENT
    allowlist. Callbacks perform maintenance/delivery; this module owns no model,
    semantic core or secondary database. Failures and unknown attempts stay intact.
    """
    controls = dict(current or {})
    if not request_id or adapter.owner != app.owner:
        raise ValueError("APPLICATION_RESUME_SCOPE_INVALID")
    if requirements is not None:
        steps = requirements["steps"]
        if len({step["id"] for step in steps}) != len(steps) or any(
            not step["completed"] for step in steps
        ):
            raise ValueError("APPLICATION_RESUME_STEPS_INVALID")
    key, row = app.progress.request_state(app.owner, request_id, requirements)
    requirements = row["requirements"]
    state = row.get("request_progress") or {
        "business": {
            "status": "pending",
            "steps": [
                {"id": step["id"], "status": "pending", "attempts": []}
                for step in requirements["steps"]
            ],
        },
        "memory": {
            "status": "pending" if requirements.get("save_result") else "not_requested",
            "attempts": [],
        },
        "feedback": {
            "status": "pending" if requirements.get("feedback", True) else "not_requested",
            "attempts": [],
        },
        "discoveries": [],
    }

    def persist() -> None:
        app.progress.save_request_state(key, state)

    def snapshot_result() -> dict[str, Any]:
        return _resume_result(request_id, state, adapter.source_visible)

    if not adapter.can_read:
        # The original journal remains evidence, but access revocation prevents
        # redisclosing prior receipts, saving them or invoking a feedback callback.
        return {
            "request_id": request_id,
            "status": "access_revoked",
            "complete": False,
            "business": {"status": "access_revoked"},
            "memory": {"status": "not_authorized_current_request"},
            "feedback": {"status": "not_authorized_current_request"},
            "source_refs": [],
        }

    discovery_id = request_id + ":discover:" + str(len(state["discoveries"]) + 1)
    state["discoveries"].append({"attempt_id": discovery_id, "status": "pending"})
    persist()
    try:
        observed = adapter.discover(requirements["target"], attempt_id=discovery_id)
    except Exception as error:
        state["discoveries"][-1].update(status="unknown", error=str(error))
        state["business"]["status"] = "observation_unknown"
        persist()
        return snapshot_result()
    state["discoveries"][-1].update(status="complete", result=observed)
    business = state["business"]
    actual = observed.get("current_state") or {}
    business["observation"] = observed
    business["status"] = "pending"
    if observed.get("unknown_effects"):
        business["status"] = "business_unknown"
        persist()
        return snapshot_result()
    for step, progress in zip(requirements["steps"], business["steps"], strict=True):
        satisfied = all(actual.get(field) == value for field, value in step["completed"].items())
        if satisfied:
            progress.update(status="completed", completion_source=observed.get("source_ref"))
            continue
        # Confirmed effects cannot be repeated merely because later state changed.
        if progress["status"] == "completed" or any(
            attempt.get("result", {}).get("business_effect") in {"confirmed", "partial"}
            for attempt in progress["attempts"]
        ):
            progress["status"] = "superseded"
        if progress["status"] == "superseded":
            business["status"] = "current_state_changed"
            break
        if controls.get("readonly", False):
            business["status"] = "observed_only"
            break
        if step["operation"] not in adapter.allowed_operations:
            business["status"] = "not_authorized_current_request"
            break
        arguments = {
            **step.get("arguments", {}),
            **{
                argument: actual[field]
                for argument, field in step.get("arguments_from_state", {}).items()
            },
        }
        attempt_id = request_id + ":" + step["id"] + ":" + str(len(progress["attempts"]) + 1)
        attempt: dict[str, Any] = {"attempt_id": attempt_id, "status": "unknown"}
        progress["attempts"].append(attempt)
        persist()
        try:
            ref = (
                VerifiedObjectRef(**observed["object_ref"]) if observed.get("object_ref") else None
            )
            result = adapter.execute(step["operation"], arguments, attempt_id=attempt_id, ref=ref)
        except Exception as error:
            attempt["error"] = str(error)
            progress["status"], business["status"] = "unknown", "business_unknown"
            break
        attempt.update(status="complete", result=result)
        observed = result
        actual = result.get("current_state") or actual
        satisfied = all(actual.get(field) == value for field, value in step["completed"].items())
        progress["status"] = "completed" if satisfied else "incomplete"
        if satisfied:
            progress["completion_source"] = result.get("source_ref")
        if not result.get("executed") or not result.get("receipt", {}).get("ok"):
            business["status"] = (
                "partial"
                if any(item["status"] == "completed" for item in business["steps"])
                else "incomplete"
            )
            break
    else:
        business["status"] = "completed"
    persist()

    memory = state["memory"]
    readonly = controls.get("readonly", False)
    can_save = not readonly and controls.get("allow_memory", False)
    if requirements.get("save_result") and memory["status"] != "committed":
        if business["status"] == "completed":
            memory.pop("current_permission", None)
            _resume_memory(
                request_id,
                state,
                controls,
                save_result if can_save else None,
                reconcile_memory,
                persist,
                snapshot_result,
            )
        if not can_save and memory["status"] != "committed":
            memory["current_permission"] = "not_authorized_current_request"
    if requirements.get("feedback", True) and controls.get("allow_feedback", True) and feedback:
        final_input = snapshot_result()
        old = state["feedback"]
        basis = {name: final_input[name]["status"] for name in ("business", "memory")}
        if old["status"] != "delivered" or old.get("basis") != basis:
            attempt_id = request_id + ":feedback:" + str(len(old["attempts"]) + 1)
            attempt = {"attempt_id": attempt_id, "status": "unknown"}
            old["attempts"].append(attempt)
            persist()
            try:
                receipt = feedback(attempt_id, final_input)
            except Exception as error:
                attempt.update(status="failed", error=str(error))
                old["status"] = "failed"
            else:
                attempt.update(status="complete", receipt=receipt)
                old.update(status="delivered" if receipt.get("ok") else "failed", basis=basis)
    persist()
    return snapshot_result()


def _resume_memory(
    request_id: str,
    state: dict[str, Any],
    current: dict[str, Any],
    save_result: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
    reconcile: Callable[[str], dict[str, Any] | None] | None,
    persist: Callable[[], None],
    result: Callable[[], dict[str, Any]],
) -> None:
    memory = state["memory"]
    if memory["status"] == "semantic_unknown":
        receipt = reconcile(memory["attempts"][-1]["operation_id"]) if reconcile else None
        if receipt is None:
            return
        memory["reconciliation"] = receipt
        memory["status"] = (
            "committed"
            if _semantic_committed(receipt)
            else (
                "failed"
                if receipt.get("status") in {"not_committed", "rejected", "failed"}
                else "semantic_unknown"
            )
        )
        persist()
    if memory["status"] in {"failed", "model_unknown"} and not current.get("new_semantic_attempt"):
        return
    if memory["status"] in {"committed", "semantic_unknown"} or save_result is None:
        return
    operation_id = request_id + ":memory:" + str(len(memory["attempts"]) + 1)
    attempt: dict[str, Any] = {"operation_id": operation_id, "status": "semantic_unknown"}
    memory["attempts"].append(attempt)
    memory["status"] = "semantic_unknown"
    persist()
    try:
        receipt = save_result(operation_id, result())
    except UnknownModelRequest as error:
        attempt.update(status="model_unknown", error=str(error))
    except Exception as error:
        # UnknownSemanticCommit and an unclassified callback interruption both
        # need operation-ID reconciliation; neither is a known failed write.
        attempt.update(status="semantic_unknown", error=str(error))
    else:
        attempt.update(
            status="committed" if _semantic_committed(receipt) else "failed", receipt=receipt
        )
    memory["status"] = attempt["status"]
    persist()


def _semantic_committed(receipt: dict[str, Any]) -> bool:
    return bool(
        receipt.get("ok")
        and (
            receipt.get("status") == "committed"
            or (
                receipt.get("status") == "no_change"
                and receipt.get("replayed")
                and receipt.get("original_status") == "committed"
            )
        )
    )


def _resume_result(
    request_id: str,
    state: dict[str, Any],
    source_visible: Callable[[str], bool],
) -> dict[str, Any]:
    refs = list(
        dict.fromkeys(
            result["source_ref"]
            for result in [
                *(row["result"] for row in state["discoveries"] if "result" in row),
                *(
                    attempt["result"]
                    for step in state["business"]["steps"]
                    for attempt in step["attempts"]
                    if "result" in attempt
                ),
            ]
            if result.get("source_ref") and source_visible(result["source_ref"])
        )
    )
    complete = (
        state["business"]["status"] == "completed"
        and state["memory"]["status"]
        in {
            "committed",
            "not_requested",
        }
        and state["feedback"]["status"] in {"delivered", "not_requested"}
    )

    def visible(value: Any) -> Any:
        if isinstance(value, dict):
            if value.get("source_ref") and not source_visible(value["source_ref"]):
                return {"source_ref": value["source_ref"], "status": "visibility_revoked"}
            return {key: visible(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visible(item) for item in value]
        return value

    # Return a visible snapshot: callbacks cannot change durable progress or use
    # forgotten cached receipts as fresh semantic evidence.
    return cast(
        dict[str, Any],
        visible(
            json.loads(
                json.dumps(
                    {
                        "request_id": request_id,
                        "status": "completed" if complete else "incomplete",
                        "complete": complete,
                        "business": state["business"],
                        "memory": state["memory"],
                        "feedback": state["feedback"],
                        "source_refs": refs,
                    }
                )
            )
        ),
    )


class RecoveryObserver(Protocol):
    """Only the two observer operations consumed by the recovery query."""

    def begin_public_message(
        self,
        scope: FoundationScope,
        public_index: int,
        content: str,
    ) -> None: ...

    def run_tool(
        self,
        request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], Any],
        business_journal: Any = None,
    ) -> Any: ...


class ApplicationRuntime(Protocol):
    """Only the observer view needed by recovery; the runtime factory stays in runners."""

    @property
    def observer(self) -> RecoveryObserver: ...


def recover_pending_application_call(
    agent: Any,
    scope: FoundationScope,
    journal: BusinessActionJournal,
    world: ApplicationWorld,
    runtime: ApplicationRuntime,
    *,
    application_workflow: str = "reservation_v1",
) -> None:
    """Observe an unknown effect before resuming tools; never replay its mutation."""
    snapshot = agent.get_state(scope.config())
    if not snapshot.values or "tools" not in snapshot.next:
        return
    messages = snapshot.values["messages"]
    generated = messages[-1]
    if not isinstance(generated, AIMessage) or not generated.id:
        raise UnknownBusinessAction("APPLICATION_RECOVERY_GENERATION_MISSING")
    thread_id = str(scope.config()["configurable"]["thread_id"])
    if any(type(call.get("id")) is not str for call in generated.tool_calls):
        raise UnknownBusinessAction("APPLICATION_RECOVERY_CALL_ID_MISSING")
    entries = [
        journal.entry_for_call(thread_id, generated.id, cast(str, call["id"]))
        for call in generated.tool_calls
    ]
    pending = [row for row in entries if row is not None and row["status"] == "pending"]
    if not pending:
        return
    # ToolNode may have failed after executing only a prefix of a multi-call message.
    if any(row is None for row in entries) or any(
        row is not None
        and row["status"] == "pending"
        and row["name"]
        not in (
            DOCUMENT_MUTATIONS
            if application_workflow == "document_publication_v1"
            else {"reserve_and_label", "complete_label"}
        )
        for row in entries
    ):
        raise UnknownBusinessAction("APPLICATION_RECOVERY_OTHER_CALL_UNRESOLVED")
    binding = journal.binding
    if binding is None:
        raise UnknownBusinessAction("AUTHORIZATION_UNDETERMINED")
    current_user = next(row for row in reversed(messages) if isinstance(row, HumanMessage))
    runtime.observer.begin_public_message(scope, binding["public_index"], str(current_user.content))
    deliveries: list[ToolMessage] = []
    for original in entries:
        assert original is not None
        if original["status"] == "complete":
            deliveries.append(ToolMessage.model_validate(original["result"]))
            continue
        original_key = original["journal_key"]
        recovery = journal.recovery_for_call(original_key)
        if recovery is None:
            query_name = (
                "get_document_status"
                if application_workflow == "document_publication_v1"
                else "get_reservation"
            )
            original_op = next(
                op for op in binding["operations"] if op["operation_id"] == original["operation_id"]
            )
            query_id = original_op.get("recovery_query_operation_id")
            queries = [
                op
                for op in binding["operations"]
                if op["tool"] == query_name
                and (query_id is None or op["operation_id"] == query_id)
                and op["target"] == original["target"]
            ]
            if len(queries) != 1:
                raise UnknownBusinessAction("APPLICATION_RECOVERY_QUERY_NOT_AUTHORIZED")
            query = queries[0]
            query_call = {
                "name": query_name,
                "args": query["args"],
                "id": "application-query-" + original_key,
            }
            query_ai = AIMessage(
                content="",
                id="application-recovery-" + original_key,
                tool_calls=[query_call],
                response_metadata={
                    "application_recovery": True,
                    "original_journal_key": original_key,
                },
            )

            def observe_query(request: Any, execute: Any) -> Any:
                return runtime.observer.run_tool(
                    request, lambda item: journal(item, execute), journal
                )

            # This is an application-origin ToolNode query, not a Host generation.
            query_node = ToolNode(
                (
                    document_business_tools(world, scope.user_id)
                    if application_workflow == "document_publication_v1"
                    else _business_tools(world, scope.user_id)
                ),
                wrap_tool_call=observe_query,
            )
            query_graph = StateGraph(MessagesState)
            query_graph.add_node("tools", query_node)
            query_graph.set_entry_point("tools")
            query_graph.set_finish_point("tools")
            result = query_graph.compile().invoke(
                {"messages": [*messages, query_ai]}, config=cast(RunnableConfig, scope.config())
            )
            raw = result["messages"][-1]
            query_entry = journal.entry_for_call(thread_id, str(query_ai.id), query_call["id"])
            if (
                not isinstance(raw, ToolMessage)
                or query_entry is None
                or not query_entry["executed"]
            ):
                raise UnknownBusinessAction("APPLICATION_RECOVERY_QUERY_NOT_EXECUTED")
            try:
                observation = json.loads(str(raw.content))
            except ValueError as error:
                raise UnknownBusinessAction("APPLICATION_RECOVERY_QUERY_INVALID") from error
            effect = "unknown"
            if application_workflow == "document_publication_v1" and isinstance(observation, dict):
                effect = document_recovery_effect(
                    original, observation, query_entry.get("target_matched") is True, binding
                )
            elif (
                isinstance(observation, dict)
                and observation.get("status") == "found"
                and query_entry.get("target_matched") is True
            ):
                effect = (
                    "confirmed"
                    if observation.get("label_status") == "created"
                    else "partial"
                    if original["name"] == "reserve_and_label"
                    else "none"
                )
            elif (
                isinstance(observation, dict)
                and observation.get("status") == "not_found"
                and all(
                    binding.get("recovery", {}).get(field) is True
                    for field in ("absence_means_no_effect", "no_deletion", "exclusive_writer")
                )
            ):
                effect = "none"
            recovery = {
                "origin": "application_recovery",
                "original_journal_key": original_key,
                "original_call_status": "UNKNOWN",
                "thread_id": thread_id,
                "generation_id": original["generation_id"],
                "call_id": original["call_id"],
                "query": query_call,
                "query_journal_key": query_entry["journal_key"],
                "query_result": raw.model_dump(mode="json"),
                "effect": effect,
                "effect_source": "query_observation_not_original_execution_receipt",
            }
            journal.record_recovery(original_key, recovery)
        if recovery["effect"] == "unknown":
            raise UnknownBusinessAction("APPLICATION_RECOVERY_OBSERVATION_UNRESOLVED")
        delivery = ToolMessage(
            content=json.dumps(
                {
                    "status": "ORIGINAL_CALL_OUTCOME_UNKNOWN",
                    "original_receipt": None,
                    "origin": "application_recovery",
                    "original_journal_key": original_key,
                    "query": recovery["query"],
                    "query_receipt": recovery["query_result"]["content"],
                    "observed_effect": recovery["effect"],
                    "effect_source": recovery["effect_source"],
                    "instruction": "Use the actual query observation to choose remaining work; "
                    "the original call outcome remains unknown.",
                },
                ensure_ascii=False,
            ),
            name=original["name"],
            tool_call_id=original["call_id"],
            status="error",
            additional_kwargs={"application_recovery": recovery},
        )
        deliveries.append(delivery)
    # Append a new checkpoint version. Keep original AI text and pending journal entries intact.
    agent.update_state(scope.config(), {"messages": deliveries}, as_node="tools")
