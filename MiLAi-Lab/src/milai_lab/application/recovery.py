"""Resume unknown application actions using a separately recorded real query."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from milai_lab.application.document_publication import DOCUMENT_MUTATIONS, document_recovery_effect
from milai_lab.application.journal import BusinessActionJournal, UnknownBusinessAction
from milai_lab.application.tools import _business_tools, document_business_tools
from milai_lab.application.world import ApplicationWorld

if TYPE_CHECKING:
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from milai_lab.contracts.scope import FoundationScope


class RecoveryObserver(Protocol):
    """Only the two observer operations consumed by the recovery query."""

    def begin_public_message(
        self, scope: FoundationScope, public_index: int, content: str,
    ) -> None: ...

    def run_tool(
        self, request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any],
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
