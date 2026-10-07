"""One source batch through extraction, locating, editing and existing commits.

The caller supplies transport and its existing commit boundary. Checkpoints live
in the same Store as memory; they are execution state, never retrieval facts.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any, Literal

from jsonschema import ValidationError as SchemaError  # type: ignore[import-untyped]
from pydantic import ValidationError

from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.methods.edit_memory import EditMemory

MaintenanceRecipe = Literal["single_pass", "extract_then_edit"]
ModelCall = Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
Commit = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]


def parse_object(text: str, *, reject_duplicate_keys: bool = False) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON object key: {key}")
            result[key] = item
        return result

    parsed = (
        json.loads(value, object_pairs_hook=unique_object)
        if reject_duplicate_keys else json.loads(value)
    )
    if not isinstance(parsed, dict):
        raise ValueError("Model response is not a JSON object")
    return parsed


def maintain_event(
    method: EditMemory,
    delivery: dict[str, Any],
    *,
    session: str,
    request_id: str,
    date: str,
    recipe: MaintenanceRecipe,
    model_call: ModelCall,
    commit: Commit | None = None,
    retrieval_limit: int = 10,
    fit: Callable[[list[dict[str, str]]], bool] | None = None,
    prepare_delivery: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """At most one extraction and one editor call for this actual source batch.

    A saved envelope resumes with the same operation IDs. An interrupted model
    request remains incomplete; recovery never silently repeats unknown HTTP.
    The Host must establish current write permission before invoking this path.
    """
    if recipe not in {"single_pass", "extract_then_edit"}:
        raise ValueError("EDIT_MAINTENANCE_RECIPE_INVALID")
    service = method.service
    sources = delivery["sources"]
    # Recheck visibility before replaying any cached envelope or receipt.
    for source in [*sources, *delivery.get("redelivered_sources", [])]:
        if service.source(source["source_ref"]) is None:
            raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
    ns = (*service.namespace, "edit_maintenance")
    key = json.dumps([session, request_id], ensure_ascii=False)
    binding = {
        "recipe": recipe, "arm": method.method_name, "interface": method.interface_version,
        "features": method.features.settings(),
        "sources": [{k: s[k] for k in ("source_ref", "source_revision", "start", "end")}
                    for s in sources],
    }
    prior = service.store.get(ns, key)
    state: dict[str, Any] = copy.deepcopy(prior.value) if prior else {
        "binding": binding, "phase": "start", "receipts": [], "unprocessed": [],
        "prior_context": copy.deepcopy(delivery.get("prior_context", [])),
    }
    if state["binding"] != binding:
        raise FunctionalRejection("EDIT_MAINTENANCE_REQUEST_CHANGED")
    for source in state.get("prior_context", []):
        if service.source(source["source_ref"]) is None:
            raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")

    def save() -> None:
        service.store.put(ns, key, copy.deepcopy(state), index=False)

    def result() -> dict[str, Any]:
        return {
            "status": "completed" if state["phase"] == "complete" else "incomplete",
            "phase": state["phase"], "recipe": recipe,
            "request_id": request_id,
            "source_refs": list(dict.fromkeys(s["source_ref"] for s in sources)),
            "receipts": copy.deepcopy(state["receipts"]),
            "unprocessed": copy.deepcopy(state["unprocessed"]) + (
                [{"phase": state["phase"], "reason": "model_outcome_unconfirmed"}]
                if state["phase"].endswith("_pending") else []
            ),
            "semantic_write_performed": any(
                r.get("ok") and r.get("effect") == "memory_only"
                and (r.get("status") == "committed" or r.get("original_status") == "committed")
                for r in state["receipts"]
            ),
        }

    if not execute or state["phase"] in {
        "complete", "incomplete", "extract_pending", "edit_pending"
    }:
        return result()

    def call(stage: str, messages: list[dict[str, str]], schema: dict[str, Any]) -> Any:
        if fit is not None and not fit(messages):
            raise FunctionalRejection("EDIT_MAINTENANCE_REQUEST_EXCEEDS_CAPACITY")
        state["phase"] = stage + "_pending"
        save()
        # Transport exceptions deliberately leave the durable pending marker.
        return model_call(stage, messages, schema)

    try:
        if state["phase"] == "start":
            if recipe == "extract_then_edit":
                request = method.change_request(
                    {**delivery, "prior_context": state.get("prior_context", [])}, date
                )
                envelope = call("extract", request["messages"], request["schema"])
                state["changes"] = method.decode_changes(envelope, request)
            else:
                state["changes"] = None
            state["phase"] = "locate"
            save()
        if state["phase"] == "locate":
            query = "\n".join(s["text"] for s in sources)
            if state["changes"] is not None:
                query = method.changes_query(state["changes"], query)
            located = method.prepare(
                list(dict.fromkeys(s["source_ref"] for s in sources)), query,
                limit=retrieval_limit,
                source_ranges=[{k: s[k] for k in ("source_ref", "start", "end")} for s in sources],
                redelivered_ranges=[],
            )
            # Keep original source bodies and their metadata in both recipes.
            located["sources"] = copy.deepcopy(sources)
            located["prior_context"] = state.get("prior_context", [])
            located["candidate_changes"] = state["changes"]
            if prepare_delivery is not None:
                located = prepare_delivery(located)
            view = method.writer_request(located, request_id=request_id)
            state.update(view=view, phase="edit")
            save()
        if state["phase"] == "edit":
            view = state["view"]
            messages = method.edit_messages(
                view["packet"], date, allow_create=True, schema=view["schema"],
                change_candidates=(method.writer_changes(state["changes"], view["mapping"])
                                   if state["changes"] is not None else None),
                prior_context=state.get("prior_context", []),
            )
            envelope = call("edit", messages, view["schema"])
            state.update(
                proposals=method.envelope_proposals(envelope, view["mapping"]),
                phase="commit",
            )
            save()
        for index in range(len(state["receipts"]), len(state["proposals"])):
            proposal = state["proposals"][index]
            operation_id = f"{request_id}:proposal:{index}"
            try:
                mapping = state["view"]["mapping"]
                receipt = (
                    commit(operation_id, proposal, mapping) if commit else method.apply(
                        session, operation_id, method.decode_proposal(proposal, mapping)
                    )
                )
            except (FunctionalRejection, ValidationError, SchemaError) as error:
                receipt = {"ok": False, "status": "rejected", "effect": "none",
                           "reason": str(error)}
            state["receipts"].append(receipt)
            if not receipt.get("ok"):
                state["unprocessed"].append({"operation_id": operation_id, "receipt": receipt})
            save()
        state["phase"] = "incomplete" if state["unprocessed"] else "complete"
    except (FunctionalRejection, ValidationError, SchemaError, ValueError) as error:
        state["unprocessed"].append({"phase": state["phase"], "reason": str(error)})
        state["phase"] = "incomplete"
    save()
    return result()
