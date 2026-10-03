"""Opt-in journals for naturally selected, owner-bound public tool calls.

Tool arguments identify an operation; they do not prove user intent. The native
tool's owner scope, schema and version checks remain the authority boundary.
The quality/appropriateness of a model's choice remains separately evaluable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]
from langchain_core.messages import AIMessage, ToolMessage

from milai_lab.application.document_publication import document_recovery_effect, document_schemas
from milai_lab.application.journal import BusinessActionJournal, UnknownBusinessAction
from milai_lab.application.tools import BUSINESS_SCHEMAS
from milai_lab.harness.artifact_io import write_json


class NativePublicActionJournal(BusinessActionJournal):
    def __init__(self, *args: Any, owner: str, world: Any,
                 single_phase_per_turn: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, application_protection=True, **kwargs)
        self.owner, self.world = owner, world
        self.single_phase_per_turn = single_phase_per_turn
        self.public_turn: dict[str, Any] | None = None
        schemas = document_schemas() if self.document_workflow else BUSINESS_SCHEMAS
        self.parameter_schemas = {item["function"]["name"]: item["function"]["parameters"]
                                  for item in schemas}

    def bind_public_turn(self, session: str, turn_id: str, source: dict[str, Any]) -> None:
        if (source.get("owner") != self.owner or source.get("session") != session
                or source.get("role") != "user"):
            raise ValueError("NATIVE_PUBLIC_TURN_SOURCE_INVALID")
        self.public_turn = {"session": session, "turn_id": turn_id,
                            "source_ref": source["event_id"],
                            "source_sha256": source["content_sha256"]}

    def _target(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.document_workflow:
            return {"title": args.get("title")}
        if name == "complete_label":
            row = self.world.conn.execute(
                "SELECT item_key FROM reservations WHERE user_id=? AND reservation_id=?",
                (self.owner, args.get("reservation_id")),
            ).fetchone()
            return ({"item_key": row["item_key"]} if row is not None else
                    {"reservation_id": args.get("reservation_id")})
        return {"item_key": args.get("item_key")}

    def _is_query(self, name: str) -> bool:
        return name == ("get_document_status" if self.document_workflow else "get_reservation")

    @staticmethod
    def _attempt_phases(name: str) -> set[str]:
        if name == "reserve_and_label":
            return {"reservation", "label"}
        if name == "complete_label":
            return {"label"}
        return {name}

    def _protected_call(self, request: Any, execute: Callable[[Any], Any]) -> ToolMessage:
        call, generated = request.tool_call, request.state["messages"][-1]
        config = request.runtime.config["configurable"]
        if (config.get("user_id") != self.owner or self.public_turn is None
                or request.runtime.config.get("max_concurrency") != 1):
            raise ValueError("NATIVE_PUBLIC_CALL_SCOPE_INVALID")
        if not isinstance(generated, AIMessage) or not generated.id or not call.get("id"):
            raise ValueError("NATIVE_PUBLIC_CALL_IDENTITY_REQUIRED")
        validate(call["args"], self.parameter_schemas[call["name"]])
        key = self._hash_call(config["thread_id"], generated.id, call["id"])
        identity = {"thread_id": config["thread_id"], "generation_id": generated.id,
                    "call_id": call["id"], "name": call["name"], "args": call["args"],
                    "owner": self.owner, "public_turn": self.public_turn}
        entries = self._entries()
        prior = entries.get(key)
        if prior is not None:
            if any(prior.get(k) != v for k, v in identity.items()):
                raise ValueError("NATIVE_PUBLIC_CALL_IDENTITY_CHANGED")
            if prior["status"] != "complete":
                raise UnknownBusinessAction("BUSINESS_CALL_OUTCOME_UNKNOWN:" + key)
            if prior.get("executed") and self._is_query(prior["name"]):
                # A kill can fall between the query receipt and the separate
                # reconciliation marker. Reuse its actual receipt, never query
                # or mutate again merely to repair this local marker.
                self._reconcile(prior)
            return ToolMessage.model_validate(prior["result"])
        target = self._target(call["name"], call["args"])
        operation = self._hash([self.owner, call["name"], call["args"]])
        reason = None
        if not self._is_query(call["name"]):
            for old in entries.values():
                if (not isinstance(old, dict) or old.get("target") != target
                        or not old.get("executed") or self._is_query(old.get("name", ""))):
                    continue
                if old.get("status") == "pending":
                    recovery = self.recovery_for_call(old["journal_key"])
                    if recovery is None or recovery["effect"] == "unknown":
                        reason = "outcome_unknown_query_required"
                        break
                    if (old.get("operation_key") == operation
                            and recovery["effect"] in {"confirmed", "partial"}):
                        reason = "operation_effect_already_observed"
                        break
                if (old.get("operation_key") == operation
                        and old.get("public_turn") == self.public_turn
                        and old.get("effect") in {"confirmed", "partial"}):
                    reason = "operation_already_completed"
                    break
                if (self.single_phase_per_turn and old.get("status") == "complete"
                        and old.get("public_turn") == self.public_turn
                        and self._attempt_phases(old["name"]).intersection(
                            self._attempt_phases(call["name"]))):
                    # A known failed attempt is not authorization to keep trying.
                    # The old receipt stays unchanged; a new public request may
                    # continue after a live query. Unknown recovery still uses
                    # the distinct original-call discovery contract above.
                    reason = "business_phase_already_attempted_this_turn"
                    break
        row = {**identity, "journal_key": key, "target": target,
               "operation_key": operation, "status": "pending", "executed": False,
               "effect": "none", "decision": "blocked" if reason else "native_public",
               "origin": "application_recovery" if generated.response_metadata.get(
                   "application_recovery") else "host"}
        entries[key] = row
        if reason:
            response = ToolMessage(name=call["name"], tool_call_id=call["id"], status="error",
                                   content=json.dumps({"status": reason, "executed": False}))
        else:
            # The fixed public read contract has no business mutation, even if
            # its response is lost. Response uncertainty remains status=pending.
            row.update(executed=True,
                       effect="none" if self._is_query(call["name"]) else "unknown")
            write_json(self.path, entries)
            try:
                response = execute(request)
                if not isinstance(response, ToolMessage):
                    raise TypeError("NATIVE_PUBLIC_TOOL_MESSAGE_REQUIRED")
                if self.response_hook is not None:
                    self.response_hook(dict(row), response)
            except BaseException as error:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
                write_json(self.path, entries)
                raise
            row["effect"] = self._receipt_effect({"tool": call["name"]}, response)
        row.update(status="complete", result=response.model_dump(mode="json"))
        write_json(self.path, entries)
        if row["executed"] and self._is_query(call["name"]):
            self._reconcile(row)
        return response

    @staticmethod
    def _hash_call(thread: str, generation: str, call: str) -> str:
        # Compatible with the historical journal's public entry_for_call API.
        import hashlib

        identity = json.dumps([thread, generation, call], ensure_ascii=False).encode()
        return hashlib.sha256(identity).hexdigest()

    def _reconcile(self, query: dict[str, Any]) -> None:
        observation = json.loads(query["result"]["content"])
        entries = self._entries()
        for original in list(entries.values()):
            if (not isinstance(original, dict) or original.get("status") != "pending"
                    or original.get("target") != query["target"] or not original.get("executed")):
                continue
            effect = "unknown"
            effect_source = "query_observation_not_original_execution_receipt"
            if self._is_query(original["name"]):
                effect = "none"
                effect_source = "native_public_read_contract_no_business_mutation"
            elif self.document_workflow:
                effect = document_recovery_effect(
                    original, observation,
                    observation.get("title") == original["target"].get("title"),
                    {"recovery": {"absence_means_no_effect": True, "no_deletion": True,
                                  "exclusive_writer": True}},
                )
            elif observation.get("status") == "not_found":
                effect = "none"
            elif observation.get("status") == "found":
                matches = (all(observation.get(k) == original["args"].get(k)
                               for k in ("item_key", "quantity", "destination", "packing"))
                           if original["name"] == "reserve_and_label" else
                           observation.get("reservation_id")
                           == original["args"].get("reservation_id"))
                if matches:
                    effect = ("confirmed" if observation.get("label_status") == "created" else
                              "partial" if original["name"] == "reserve_and_label" else "none")
            recovery = {"original_journal_key": original["journal_key"],
                        "original_call_status": "UNKNOWN", "effect": effect,
                        "query_journal_key": query["journal_key"], "query_result": query["result"],
                        "effect_source": effect_source}
            recoveries = entries.setdefault("_native_recoveries", {})
            recoveries.setdefault(original["journal_key"], {})[query["journal_key"]] = recovery
        write_json(self.path, entries)

    def recovery_for_call(self, original_key: str) -> dict[str, Any] | None:
        rows = self._entries().get("_native_recoveries", {}).get(original_key, {})
        return next(reversed(rows.values())) if rows else None


def recover_native_pending(app: Any, agent: Any, scope: Any, runtime: Any) -> None:
    """Discover actual local state, retaining every original unknown journal row."""
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    snapshot = agent.get_state(scope.config())
    if not snapshot.values or "tools" not in snapshot.next:
        return
    generated = snapshot.values["messages"][-1]
    if not isinstance(generated, AIMessage) or not generated.id:
        raise UnknownBusinessAction("NATIVE_RECOVERY_GENERATION_MISSING")
    thread = scope.config()["configurable"]["thread_id"]
    entries = [app.journal.entry_for_call(thread, generated.id, call["id"])
               for call in generated.tool_calls]
    if not any(row and row["status"] == "pending" for row in entries):
        return
    if any(row is None for row in entries):
        raise UnknownBusinessAction("NATIVE_RECOVERY_MIXED_BATCH_UNRESOLVED")
    deliveries = []
    delivered_sources = []
    for original in entries:
        if original["status"] == "complete":
            deliveries.append(ToolMessage.model_validate(original["result"]))
            continue
        query_name = "get_document_status" if app.journal.document_workflow else "get_reservation"
        field = "title" if app.journal.document_workflow else "item_key"
        if field not in original["target"]:
            raise UnknownBusinessAction("NATIVE_RECOVERY_DISCOVERY_TARGET_UNAVAILABLE")
        query_id = "discovery-" + original["journal_key"]
        attempt = 0
        while (prior_query := app.journal.entry_for_call(thread, query_id, query_id)) is not None:
            if prior_query["status"] == "complete":
                break
            # A discovery read can itself lose its response. Never relabel or
            # replay that call: a distinct public read obtains a fresh receipt.
            # Completed reads retain their ID so capture/projection can resume.
            attempt += 1
            query_id = "discovery-" + original["journal_key"] + ":retry-" + str(attempt)
        query = {"name": query_name, "args": {field: original["target"][field]}, "id": query_id}
        query_ai = AIMessage(content="", id=query_id,
                             tool_calls=[query], response_metadata={"application_recovery": True})

        def wrap(request: Any, execute: Any) -> Any:
            return runtime.observer.run_tool(request, lambda item: app.journal(item, execute))

        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode(app.tools, wrap_tool_call=wrap))
        graph.set_entry_point("tools")
        graph.set_finish_point("tools")
        graph.compile().invoke(
            {"messages": [*snapshot.values["messages"], query_ai]}, scope.config()
        )
        recovery = app.journal.recovery_for_call(original["journal_key"])
        if recovery is None or recovery["effect"] == "unknown":
            raise UnknownBusinessAction("NATIVE_RECOVERY_OBSERVATION_UNRESOLVED")
        query_source = runtime.observer.query_source_delivery(recovery["query_journal_key"])
        delivered_sources.append(query_source["source_ref"])
        deliveries.append(ToolMessage(
            name=original["name"], tool_call_id=original["call_id"], status="error",
            content=json.dumps({"status": "ORIGINAL_CALL_OUTCOME_UNKNOWN", "original_receipt": None,
                                "query_receipt": json.loads(recovery["query_result"]["content"]),
                                "query_source": query_source,
                                "observed_effect": recovery["effect"],
                                "effect_source": recovery["effect_source"]}),
            additional_kwargs={"application_recovery": recovery},
        ))
    # All discovery bodies are now selected for this delivery. Persist exposure
    # before the checkpoint so a kill cannot leave a delivered body untracked;
    # only a later assistant output can inherit this noncausal input edge.
    runtime.observer.note_delivered_sources(delivered_sources)
    agent.update_state(scope.config(), {"messages": deliveries}, as_node="tools")
