"""One source batch through extraction, locating, editing and existing commits.

The caller supplies transport and its existing commit boundary. Checkpoints live
in the same Store as memory; they are execution state, never retrieval facts.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from milai_lab.contracts.memory import EpisodeDescription
from milai_lab.memory.edit_units import issue_evidence
from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.retrieval import merge_candidates
from milai_lab.memory.working_set import record_candidate
from milai_lab.methods.edit_memory import EditMemory

MaintenanceRecipe = Literal["single_pass", "extract_then_edit"]
ModelCall = Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
Commit = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
CandidateMode = Literal["combined_dense", "per_candidate_dense"]
MemoryViewMode = Literal["legacy", "staged", "state_driven"]


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


def locate_candidates(
    method: EditMemory,
    changes: list[dict[str, Any]] | None,
    original_query: str,
    *,
    limit: int = 10,
    mode: CandidateMode = "combined_dense",
) -> list[dict[str, Any]]:
    """Locate a batch with common dense retrieval; each actual target occurs once.

    The default is the existing one combined query, including the original body
    when extraction is empty. Per-candidate locating is an explicit alternative
    and uses the same search and total candidate limit for every memory method.
    """
    if mode not in {"combined_dense", "per_candidate_dense"}:
        raise ValueError("EDIT_CANDIDATE_MODE_INVALID")
    queries = (
        [method.changes_query([change], original_query) for change in changes]
        if mode == "per_candidate_dense" and changes
        else [method.changes_query(changes or [], original_query)]
    )
    return merge_candidates(
        [method.service.search(query, limit=limit, include_raw=False)["records"]
         for query in queries],
        limit=limit,
    )


def _located_delivery(
    method: EditMemory,
    delivery: dict[str, Any],
    changes: list[dict[str, Any]] | None,
    *,
    retrieval_limit: int,
    selected_record_ids: list[str] | None,
    candidate_mode: CandidateMode,
    prepare_delivery: Callable[[dict[str, Any]], dict[str, Any]] | None,
    selected_records: list[dict[str, Any]] | None = None,
    materialize_support: bool = False,
) -> dict[str, Any]:
    sources = delivery["sources"]
    if selected_records is None:
        selected_records = (
            [method.service.read(record_id) for record_id in dict.fromkeys(selected_record_ids)]
            if selected_record_ids is not None else locate_candidates(
                method, changes, "\n".join(s["text"] for s in sources),
                limit=retrieval_limit, mode=candidate_mode,
            )
        )
    located = method.prepare(
        list(dict.fromkeys(s["source_ref"] for s in sources)), "",
        selected_records=selected_records,
        source_ranges=[{k: s[k] for k in ("source_ref", "start", "end")} for s in sources],
        redelivered_ranges=(method.target_support_ranges(selected_records)
                            if materialize_support else []),
    )
    located.update(
        sources=copy.deepcopy(sources),
        prior_context=copy.deepcopy(delivery.get("prior_context", [])),
        candidate_changes=changes,
    )
    for key in ("episode_context", "replay", "new_independent_support"):
        if key in delivery:
            located[key] = copy.deepcopy(delivery[key])
    return prepare_delivery(located) if prepare_delivery is not None else located


def _replay_context(
    messages: list[dict[str, str]], delivery: dict[str, Any]
) -> list[dict[str, str]]:
    if not delivery.get("episode_context") and not delivery.get("replay"):
        return messages
    result = copy.deepcopy(messages)
    packet = json.loads(result[1]["content"])
    packet.update({key: delivery[key] for key in (
        "episode_context", "replay", "new_independent_support"
    ) if key in delivery})
    result[1]["content"] = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    result[0]["content"] += (
        " Episode descriptions are source-linked interpretations, not extra evidence. "
        "Replay retains original source identity and adds no independent support."
    )
    return result


def _index_episode_descriptions(
    method: EditMemory, sources: list[dict[str, Any]], receipts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Index only interpretations actually committed with this source's assertion."""
    index = EpisodeIndex(method.service)
    descriptions: dict[str, list[EpisodeDescription]] = {}
    for receipt in receipts:
        if not receipt.get("ok") or not (
            receipt.get("status") == "committed" or receipt.get("original_status") == "committed"
        ):
            continue
        row = method.service.read(receipt["id"], receipt["revision"])
        if not row.get("ok"):
            continue
        for unit in row["value"].get("edit_state", {}).get("units", []):
            assertion = unit.get("assertion") or {}
            if not assertion.get("source_ref"):
                continue
            description: EpisodeDescription = {
                "kind": "context", "basis": assertion["kind"], "text": unit["text"],
                "source_refs": [assertion["source_ref"]],
            }
            limits = assertion.get("applicability", {})
            for source_key, destination in (
                ("event_at", "occurred_at"), ("effective_from", "effective_from"),
                ("effective_until", "effective_until"),
            ):
                if source_key in limits:
                    description[destination] = limits[source_key]  # type: ignore[literal-required]
            descriptions.setdefault(assertion["source_ref"], []).append(description)
    indexed, failed = [], []
    for ref in dict.fromkeys(source["source_ref"] for source in sources):
        actual = method.service.source(ref)
        if actual is None or "episode_id" not in actual or ref not in descriptions:
            continue
        episode_id = actual["episode_id"]
        stored = method.service.store.get(index.namespace, episode_id)
        previous = copy.deepcopy(stored.value["descriptions"]) if stored else []
        for description in descriptions[ref]:
            if description not in previous:
                previous.append(description)
        try:
            index.register(episode_id, [ref], descriptions=previous)
            indexed.append(episode_id)
        except FunctionalRejection as error:
            failed.append({"episode_id": episode_id, "reason": str(error)})
    return {"status": "incomplete" if failed else "indexed",
            "episode_ids": indexed, "unprocessed": failed, "new_independent_support": False}


def plan_source_batches(
    method: EditMemory,
    delivery: dict[str, Any],
    *,
    date: str,
    recipe: MaintenanceRecipe,
    fit: Callable[[list[dict[str, str]]], bool],
    retrieval_limit: int = 10,
    selected_record_ids: list[str] | None = None,
    candidate_mode: CandidateMode = "combined_dense",
    prepare_delivery: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Losslessly partition current source, preferring whole events/paragraphs.

    Preview the actual source, existing locating pool, prior context and schema.
    Extracted candidates and their locating pool are not yet known; their final
    request is checked again before HTTP. The current K and old context are not
    reduced to make a preview fit. No model or semantic commit runs here.
    """
    located = _located_delivery(
        method, delivery, None, retrieval_limit=retrieval_limit,
        selected_record_ids=selected_record_ids, candidate_mode=candidate_mode,
        prepare_delivery=prepare_delivery,
    )
    selected = [method.service.read(row["record_id"]) for row in located["records"]]

    def fits(sources: list[dict[str, Any]]) -> bool:
        trial = {**delivery, "sources": sources}
        if recipe == "extract_then_edit":
            request = method.change_request(trial, date)
            if not fit(_replay_context(request["messages"], trial)):
                return False
        preview_delivery = _located_delivery(
            method, trial, None, retrieval_limit=retrieval_limit,
            selected_record_ids=selected_record_ids, candidate_mode=candidate_mode,
            prepare_delivery=prepare_delivery, selected_records=selected,
        )
        request = method.preview_writer_request(preview_delivery)
        return fit(_replay_context(method.edit_messages(
            request["packet"], date, allow_create=True, schema=request["schema"],
            prior_context=delivery.get("prior_context", []),
        ), trial))

    if fits(delivery["sources"]):
        return [delivery]
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def sliced(source: dict[str, Any], start: int, end: int) -> dict[str, Any]:
        return {
            **source, **issue_evidence(method.service, source["source_ref"], start, end),
            "text": source["text"][start - source["start"]:end - source["start"]],
        }

    def flush() -> None:
        if current:
            batches.append({**copy.deepcopy(delivery), "sources": copy.deepcopy(current)})
            current.clear()

    for source in delivery["sources"]:
        if fits([*current, source]):
            current.append(source)
            continue
        if current:
            flush()
        if fits([source]):
            current.append(source)
            continue
        offset = source["start"]
        for paragraph in source["text"].splitlines(keepends=True) or [source["text"]]:
            end = offset + len(paragraph)
            if fits([*current, sliced(source, offset, end)]):
                current.append(sliced(source, offset, end))
                offset = end
                continue
            flush()
            while offset < end:
                low, high, chosen = offset + 1, end, offset
                while low <= high:
                    midpoint = (low + high) // 2
                    if fits([sliced(source, offset, midpoint)]):
                        chosen, low = midpoint, midpoint + 1
                    else:
                        high = midpoint - 1
                if chosen == offset:
                    raise FunctionalRejection("EDIT_MAINTENANCE_INDIVISIBLE_CAPACITY")
                current.append(sliced(source, offset, chosen))
                offset = chosen
                if offset < end:
                    flush()
    flush()
    if not batches:
        raise FunctionalRejection("EDIT_MAINTENANCE_INDIVISIBLE_CAPACITY")
    return batches


def _directory_ref(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("ok") or not isinstance(row.get("value"), dict):
        raise FunctionalRejection("EDIT_RECORD_UNAVAILABLE")
    value = row["value"]
    return {
        "record_id": row["id"], "revision": value["revision"],
        "matter": (value.get("edit_state") or {}).get("matter_description", ""),
    }


def _append_work(
    state: dict[str, Any], request_id: str, records: list[dict[str, Any]],
    *, create: bool, done: bool,
) -> None:
    state["work_items"].append({
        "request_id": f"{request_id}:work:{len(state['work_items'])}",
        "records": copy.deepcopy(records), "create": create, "done": done,
        "status": "pending",
    })


def _has_semantic_receipt(receipts: list[dict[str, Any]]) -> bool:
    return any(
        receipt.get("ok") and receipt.get("id") is not None
        and receipt.get("revision") is not None and (
            receipt.get("status") in {"committed", "no_change"}
            or receipt.get("original_status") in {"committed", "no_change"}
        ) for receipt in receipts
    )


def has_pending_save(state: dict[str, Any]) -> bool:
    """An explicit save is pending when any actual work scope lacks confirmation."""
    if not state.get("memory_save_requested"):
        return False
    if state["phase"] != "complete" or state.get("unprocessed"):
        return True
    scopes = [item.get("result", {}) for item in state.get("work_items", [])] or list(
        state.get("batch_results", {}).values()
    )
    return any(not _has_semantic_receipt(scope.get("receipts", [])) for scope in scopes) \
        if scopes else not _has_semantic_receipt(state.get("receipts", []))


def _maintain_views(
    method: EditMemory, delivery: dict[str, Any], state: dict[str, Any], *,
    session: str, request_id: str, date: str, recipe: MaintenanceRecipe,
    memory_view_mode: MemoryViewMode, model_call: ModelCall, commit: Commit | None,
    retrieval_limit: int, fit: Callable[[list[dict[str, str]]], bool] | None,
    prepare_delivery: Callable[[dict[str, Any]], dict[str, Any]] | None,
    candidate_mode: CandidateMode, save: Callable[[], None],
    call: Callable[[str, list[dict[str, str]], dict[str, Any]], Any],
) -> None:
    """Replace the writer scope per work item; all calls use the original callback.

    Each initial pool record is selected at most once, and creation is one work
    scope. This bounds navigation without a second model budget or retry loop.
    Work IDs and child checkpoints are durable before an editor can be issued.
    """
    service = method.service
    ns = (*service.namespace, "edit_maintenance")
    while state["phase"] == "views":
        pending = next((item for item in state["work_items"]
                        if item["status"] != "completed"), None)
        if pending is None:
            handled = {ref["record_id"] for item in state["work_items"] for ref in item["records"]}
            remaining = [ref for ref in state["directory"] if ref["record_id"] not in handled]
            create_available = not any(item["create"] for item in state["work_items"])
            if (state["work_items"] and (memory_view_mode == "staged"
                    or state["work_items"][-1]["done"])) or not (remaining or create_available):
                state["phase"] = "complete"
                return
            directory_refs = [_directory_ref(service.read(ref["record_id"])) for ref in remaining]
            directory = [record_candidate(ref["record_id"], ref["revision"], ref["matter"])
                         for ref in directory_refs]
            schema: dict[str, Any] = {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "record_ids": {"type": "array", "uniqueItems": True, "items": {
                        "type": "string", "enum": [ref["record_id"] for ref in directory]
                    }} if directory else {"type": "array", "maxItems": 0},
                    "done": {"type": "boolean"},
                }, "required": ["record_ids", "done"],
            }
            messages = [{"role": "system", "content": (
                "Select actual whole matters to open for this source's maintenance. "
                "The directory is a locating hint, not evidence. Related targets can be "
                "selected together. The first work also lets the existing editor consider "
                "new matters from the current source; later work does not create them again. "
                "Empty selection is allowed. Set done when no further old matters need opening. "
                "No record must be selected. Return the supplied schema."
            )}, {"role": "user", "content": json.dumps({
                "observed_date": date, "sources": delivery["sources"],
                "prior_context": method.context_projection(state.get("prior_context", [])),
                "change_candidates": state["changes"], "directory": directory,
                "create_available": create_available,
                "processed": [{"request_id": item["request_id"], "records": item["records"],
                               "receipts": item["result"]["receipts"]}
                              for item in state["work_items"]],
                "response_schema": schema,
            }, ensure_ascii=False, separators=(",", ":"))}]
            saved_selection = "selection" in state
            if not saved_selection:
                state["selection"] = call(f"select:{len(state['work_items'])}", messages, schema)
                state["phase"] = "views"
                save()
            selection = state["selection"]
            legacy_selection = saved_selection and "create" in selection
            validation_schema = schema
            if legacy_selection:
                # A response already saved under the old selection contract keeps
                # its original creation decision; issued work/mappings are unchanged.
                validation_schema = {**schema, "properties": {
                    **schema["properties"], "create": {"type": "boolean"}},
                    "required": [*schema["required"], "create"]}
            Draft202012Validator(validation_schema).validate(selection)
            identifiers = list(dict.fromkeys(selection["record_ids"]))
            available = {ref["record_id"]: ref for ref in directory_refs}
            if any(identifier not in available for identifier in identifiers):
                raise FunctionalRejection("EDIT_VIEW_SELECTION_UNAVAILABLE")
            create = bool(selection["create"]) if legacy_selection else create_available
            if create and not create_available:
                raise FunctionalRejection("EDIT_VIEW_CREATE_SCOPE_ALREADY_PROCESSED")
            if not identifiers and not create:
                if selection["done"]:
                    state["phase"] = "complete"
                    state.pop("selection")
                    save()
                    return
                raise FunctionalRejection("EDIT_VIEW_NO_PROGRESS")
            _append_work(state, request_id, [available[key] for key in identifiers],
                         create=create, done=bool(selection["done"]))
            state.pop("selection")
            save()
            pending = state["work_items"][-1]

        child_id = pending["request_id"]
        child_key = json.dumps([session, child_id], ensure_ascii=False)
        if service.store.get(ns, child_key) is None:
            selected_ids = [ref["record_id"] for ref in pending["records"]]
            # Earlier work can change actual state. Open the current version now,
            # before issuing this work's immutable editor mapping.
            pending["records"] = [_directory_ref(service.read(key)) for key in selected_ids]
            child_binding = {key: copy.deepcopy(value) for key, value in state["binding"].items()
                             if key not in {"memory_view_mode", "candidate_record_ids"}}
            child_binding["selected_record_ids"] = selected_ids
            service.store.put(ns, child_key, {
                "binding": child_binding, "phase": "locate", "receipts": [], "unprocessed": [],
                "changes": copy.deepcopy(state["changes"]),
                "prior_context": copy.deepcopy(state.get("prior_context", [])), "date": date,
                "allow_create": pending["create"],
                **({"memory_save_requested": True} if state.get("memory_save_requested") else {}),
            }, index=False)
            save()

        def work_call(
            stage: str, messages: list[dict[str, str]], schema: dict[str, Any],
            work_ref: str = child_id,
        ) -> Any:
            return model_call(f"{stage}:{work_ref}", messages, schema)

        child = maintain_event(
            method, {**delivery, "materialize_selected_support": True},
            session=session, request_id=child_id, date=date, recipe=recipe,
            model_call=work_call, commit=commit, retrieval_limit=retrieval_limit, fit=fit,
            prepare_delivery=prepare_delivery, candidate_mode=candidate_mode,
            selected_record_ids=[ref["record_id"] for ref in pending["records"]],
            batch_sources=False,
        )
        pending.update(result=child, status=child["status"])
        state["receipts"] = [receipt for item in state["work_items"]
                             for receipt in item.get("result", {}).get("receipts", [])]
        save()
        if child["status"] != "completed":
            return


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
    selected_record_ids: list[str] | None = None,
    candidate_mode: CandidateMode = "combined_dense",
    batch_sources: bool | None = None,
    memory_view_mode: MemoryViewMode = "legacy",
    memory_save_requested: bool = False,
    candidate_record_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Maintain an actual event with legacy or selected whole-matter delivery.

    Legacy retains at most one extraction and one edit per source batch. View
    modes extract once, then use bounded selections within the caller's budget.
    A saved envelope resumes with the same operation IDs. An interrupted model
    request remains incomplete; recovery never silently repeats unknown HTTP.
    The Host must establish current write permission before invoking this path.
    A finite delivery comparison can fix an actual candidate pool without marking
    those candidates as selected/opened work. Ordinary callers still locate it.
    """
    if recipe not in {"single_pass", "extract_then_edit"}:
        raise ValueError("EDIT_MAINTENANCE_RECIPE_INVALID")
    if memory_view_mode not in {"legacy", "staged", "state_driven"}:
        raise ValueError("EDIT_MEMORY_VIEW_MODE_INVALID")
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
    if selected_record_ids is not None:
        binding["selected_record_ids"] = list(dict.fromkeys(selected_record_ids))
    if candidate_mode != "combined_dense":
        binding["candidate_mode"] = candidate_mode
    if memory_view_mode != "legacy":
        binding["memory_view_mode"] = memory_view_mode
    if candidate_record_ids is not None:
        binding["candidate_record_ids"] = list(dict.fromkeys(candidate_record_ids))
    locating_ids = selected_record_ids if selected_record_ids is not None else candidate_record_ids
    prior = service.store.get(ns, key)
    state: dict[str, Any] = copy.deepcopy(prior.value) if prior else {
        "binding": binding, "phase": "start", "receipts": [], "unprocessed": [],
        "prior_context": copy.deepcopy(delivery.get("prior_context", [])),
        "date": date,
        **({"memory_save_requested": True} if memory_save_requested else {}),
    }
    date = state.get("date", date)
    if state["binding"] != binding:
        raise FunctionalRejection("EDIT_MAINTENANCE_REQUEST_CHANGED")
    for source in state.get("prior_context", []):
        if service.source(source["source_ref"]) is None:
            raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")

    def save() -> None:
        service.store.put(ns, key, copy.deepcopy(state), index=False)

    def result() -> dict[str, Any]:
        batches = list(state.get("batch_results", {}).values())
        if "work_items" in state:
            batches = [item["result"] for item in state["work_items"] if "result" in item]
        return {
            "status": "completed" if state["phase"] == "complete" else "incomplete",
            "phase": state["phase"], "recipe": recipe,
            "request_id": request_id,
            "date": date,
            "source_refs": list(dict.fromkeys(s["source_ref"] for s in sources)),
            "receipts": copy.deepcopy(state["receipts"]),
            "unprocessed": copy.deepcopy(state["unprocessed"]) + (
                [{"phase": state["phase"], "reason": "model_outcome_unconfirmed"}]
                if state["phase"].endswith("_pending") else []
            ) + [{"batch": index, **item}
                 for index, batch in enumerate(batches) for item in batch["unprocessed"]],
            "semantic_write_performed": any(
                r.get("ok") and r.get("effect") == "memory_only"
                and (r.get("status") == "committed" or r.get("original_status") == "committed")
                for r in state["receipts"]
            ),
            **({"batches": copy.deepcopy(batches),
                "source_batch_count": len(state["batches"])} if "batches" in state else {}),
            **({"prior_request_id": state["prior_request_id"]}
               if "prior_request_id" in state else {}),
            **({"prior_session": state["prior_session"]} if "prior_session" in state else {}),
            **({"episode_index": copy.deepcopy(state["episode_index"])}
               if "episode_index" in state else {}),
            **({"memory_save_requested": True} if state.get("memory_save_requested") else {}),
            **({"batches": copy.deepcopy(batches), "source_batch_count": 1,
                "memory_view": {
                    "mode": memory_view_mode,
                    "directory": copy.deepcopy(state.get("directory", [])),
                    "work_items": [{key: copy.deepcopy(item[key]) for key in (
                        "request_id", "records", "create", "status"
                    ) if key in item} for item in state["work_items"]],
                    "pending_refs": [item["request_id"] for item in state["work_items"]
                                     if item.get("status") != "completed"] + (
                        [state["active_call_ref"]] if state["phase"].endswith("_pending")
                        and "active_call_ref" in state else []
                    ),
                }} if "work_items" in state else {}),
        }

    if execute and state["phase"] == "complete" and service.memory_profile == "unified_v1" \
            and "episode_index" not in state:
        state["episode_index"] = _index_episode_descriptions(method, sources, state["receipts"])
        save()
    if not execute or state["phase"] in {"complete", "incomplete"} \
            or state["phase"].endswith("_pending"):
        return result()

    def call(stage: str, messages: list[dict[str, str]], schema: dict[str, Any]) -> Any:
        if fit is not None and not fit(messages):
            raise FunctionalRejection("EDIT_MAINTENANCE_REQUEST_EXCEEDS_CAPACITY")
        state["phase"] = stage.split(":", 1)[0] + "_pending"
        if memory_view_mode != "legacy":
            state["active_call_ref"] = f"{request_id}:{stage}"
        save()
        # Transport exceptions deliberately leave the durable pending marker.
        return model_call(stage, messages, schema)

    try:
        if memory_view_mode == "legacy" and state["phase"] == "start" and fit is not None and (
            batch_sources if batch_sources is not None else service.memory_profile == "unified_v1"
        ):
            batches = plan_source_batches(
                method, delivery, date=date, recipe=recipe, fit=fit,
                retrieval_limit=retrieval_limit, selected_record_ids=locating_ids,
                candidate_mode=candidate_mode, prepare_delivery=prepare_delivery,
            )
            if len(batches) > 1:
                state.update(batches=batches, batch_results={}, next_batch=0, phase="batches")
                save()
        if state["phase"] == "batches":
            while state["next_batch"] < len(state["batches"]):
                index = state["next_batch"]
                if state["batch_results"].get(str(index), {}).get("status") == "completed":
                    state["next_batch"] += 1
                    save()
                    continue
                batch = maintain_event(
                    method, state["batches"][index], session=session,
                    request_id=f"{request_id}:batch:{index}", date=date, recipe=recipe,
                    model_call=model_call, commit=commit, retrieval_limit=retrieval_limit,
                    fit=fit, prepare_delivery=prepare_delivery, execute=execute,
                    selected_record_ids=locating_ids, candidate_mode=candidate_mode,
                    batch_sources=False,
                    memory_save_requested=state.get("memory_save_requested", False),
                )
                state["batch_results"][str(index)] = batch
                state["receipts"] = [
                    receipt for item in state["batch_results"].values()
                    for receipt in item["receipts"]
                ]
                if batch["status"] != "completed":
                    save()
                    return result()
                state["next_batch"] += 1
                save()
            state["phase"] = "complete"
            save()
            return result()
        if state["phase"] == "start":
            if recipe == "extract_then_edit":
                request = method.change_request(
                    {**delivery, "prior_context": state.get("prior_context", [])}, date
                )
                envelope = call(
                    "extract", _replay_context(request["messages"], delivery), request["schema"]
                )
                state["changes"] = method.decode_changes(envelope, request)
            else:
                state["changes"] = None
            state["phase"] = "locate"
            save()
        if state["phase"] == "locate":
            if memory_view_mode != "legacy":
                selected = (
                    [service.read(record_id) for record_id in dict.fromkeys(locating_ids)]
                    if locating_ids is not None else locate_candidates(
                        method, state["changes"], "\n".join(s["text"] for s in sources),
                        limit=retrieval_limit, mode=candidate_mode,
                    )
                )
                state.update(
                    directory=[_directory_ref(row) for row in selected],
                    work_items=[], phase="views",
                )
                if selected_record_ids is not None or not selected:
                    _append_work(state, request_id, state["directory"], create=True, done=True)
                save()
            else:
                located = _located_delivery(
                    method, {**delivery, "prior_context": state.get("prior_context", [])},
                    state["changes"], retrieval_limit=retrieval_limit,
                    selected_record_ids=locating_ids, candidate_mode=candidate_mode,
                    prepare_delivery=prepare_delivery,
                    materialize_support=bool(delivery.get("materialize_selected_support")),
                )
                view = method.writer_request(
                    located, request_id=request_id, allow_create=state.get("allow_create", True)
                )
                state.update(view=view, phase="edit")
                save()
        if state["phase"] == "views":
            _maintain_views(
                method, delivery, state, session=session, request_id=request_id,
                date=date, recipe=recipe, memory_view_mode=memory_view_mode,
                model_call=model_call, commit=commit, retrieval_limit=retrieval_limit,
                fit=fit, prepare_delivery=prepare_delivery, candidate_mode=candidate_mode,
                save=save, call=call,
            )
            if state["phase"] == "complete" and service.memory_profile == "unified_v1":
                state["episode_index"] = _index_episode_descriptions(
                    method, sources, state["receipts"]
                )
            save()
            return result()
        if state["phase"] == "edit":
            view = state["view"]
            messages = method.edit_messages(
                view["packet"], date, allow_create=state.get("allow_create", True),
                schema=view["schema"],
                change_candidates=(method.writer_changes(state["changes"], view["mapping"])
                                   if state["changes"] is not None else None),
                prior_context=state.get("prior_context", []),
            )
            envelope = call("edit", _replay_context(messages, delivery), view["schema"])
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
        if service.memory_profile == "unified_v1":
            state["episode_index"] = _index_episode_descriptions(method, sources, state["receipts"])
    except (FunctionalRejection, ValidationError, SchemaError, ValueError) as error:
        state["unprocessed"].append({"phase": state["phase"], "reason": str(error)})
        state["phase"] = "incomplete"
    save()
    return result()


def resume_maintenance(
    method: EditMemory,
    delivery: dict[str, Any],
    *,
    session: str,
    prior_request_id: str,
    date: str,
    recipe: MaintenanceRecipe,
    model_call: ModelCall,
    new_attempt_id: str | None = None,
    commit: Commit | None = None,
    retrieval_limit: int = 10,
    fit: Callable[[list[dict[str, str]]], bool] | None = None,
    prepare_delivery: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    selected_record_ids: list[str] | None = None,
    candidate_mode: CandidateMode = "combined_dense",
    memory_view_mode: MemoryViewMode = "legacy",
    memory_save_requested: bool = False,
    execute: bool = True,
    new_attempt_session: str | None = None,
) -> dict[str, Any]:
    """Reconcile old proposal outcomes, then use an explicit new semantic identity.

    No business operation is invoked here. An issued proposal with an unknown
    commit remains unknown unless its existing operation receipt is observable.
    An unknown model response can be left intact while a caller requests a new
    semantic attempt. Confirmed source batches are reused rather than edited again.
    A completed empty explicit save can likewise get an explicit new attempt;
    completion of the old call is not proof of saved semantic memory. The Host's
    current permission boundary remains authoritative. ``execute=False`` only
    inspects and reconciles receipts. A cross-session attempt uses its current
    session for new operations while retaining the old source and journal refs.
    """
    service = method.service
    ns = (*service.namespace, "edit_maintenance")
    key = json.dumps([session, prior_request_id], ensure_ascii=False)
    prior = service.store.get(ns, key)
    if prior is None:
        raise FunctionalRejection("EDIT_MAINTENANCE_PRIOR_REQUEST_UNAVAILABLE")
    options: dict[str, Any] = {
        "session": session, "date": prior.value.get("date", date),
        "recipe": recipe, "model_call": model_call,
        "commit": commit, "retrieval_limit": retrieval_limit, "fit": fit,
        "prepare_delivery": prepare_delivery, "selected_record_ids": selected_record_ids,
        "candidate_mode": candidate_mode,
        "memory_view_mode": memory_view_mode,
        "memory_save_requested": memory_save_requested,
    }
    original = maintain_event(
        method, delivery, request_id=prior_request_id, execute=False, **options
    )
    state = copy.deepcopy(prior.value)
    if not execute and new_attempt_id is not None:
        attempt_session = session if new_attempt_session is None else new_attempt_session
        attempted = service.store.get(ns, json.dumps(
            [attempt_session, new_attempt_id], ensure_ascii=False
        ))
        if attempted is not None:
            if (attempted.value.get("prior_request_id") != prior_request_id
                    or attempted.value.get("prior_session", attempt_session) != session):
                raise FunctionalRejection("EDIT_MAINTENANCE_NEW_ATTEMPT_ALREADY_BOUND")
            return maintain_event(
                method, delivery, request_id=new_attempt_id, execute=False,
                **{**options, "session": attempt_session},
            )

    def retry_completed() -> bool:
        return (state["phase"] == "complete" and has_pending_save(state)
                and new_attempt_id is not None)

    if state["phase"] == "complete" and (not retry_completed() or not execute):
        return {**original, "replayed": True}

    reconciliation: list[dict[str, Any]] = []
    if "work_items" in state:
        for work in state["work_items"]:
            if work.get("status") == "completed":
                continue
            child_id = work["request_id"]
            child = service.store.get(ns, json.dumps([session, child_id], ensure_ascii=False))
            if child is None:
                # This work has not issued a model request; the same identity is safe.
                continue
            child_options = {**options, "memory_view_mode": "legacy",
                             "selected_record_ids": [ref["record_id"] for ref in work["records"]]}
            if child.value["phase"] in {"locate", "edit"}:
                def work_call(
                    stage: str, messages: list[dict[str, str]], schema: dict[str, Any],
                    work_ref: str = child_id,
                ) -> Any:
                    return model_call(f"{stage}:{work_ref}", messages, schema)

                child_options["model_call"] = work_call
                inspected = maintain_event(
                    method, {**delivery, "materialize_selected_support": True},
                    request_id=child_id, execute=execute and new_attempt_id is None,
                    **child_options,
                )
            else:
                inspected = resume_maintenance(
                    method, {**delivery, "materialize_selected_support": True},
                    prior_request_id=child_id, execute=execute, **child_options,
                )
            reconciliation.append({"request_id": child_id, "result": inspected})
            if inspected.get("outcome") == "semantic_outcome_unconfirmed":
                return {**original, "outcome": "semantic_outcome_unconfirmed",
                        "reconciliation": reconciliation}
            work.update(result=inspected, status=inspected["status"])
        state["receipts"] = [receipt for work in state["work_items"]
                             for receipt in work.get("result", {}).get("receipts", [])]
        pending = [work for work in state["work_items"] if work.get("status") != "completed"]
        if not pending and state["work_items"] and (
                memory_view_mode == "staged" or state["work_items"][-1]["done"]):
            state["phase"] = "complete"
        service.store.put(ns, key, state, index=False)
        original = maintain_event(method, delivery, request_id=prior_request_id,
                                  execute=False, **options)
        if state["phase"] == "complete" and not retry_completed():
            return {**original, "replayed": True, "reconciliation": reconciliation}
        if execute and new_attempt_id is None and state["phase"] == "views" and (
            not pending or all(service.store.get(
                ns, json.dumps([session, work["request_id"]], ensure_ascii=False)
            ) is None for work in pending)
        ):
            return {**maintain_event(method, delivery, request_id=prior_request_id, **options),
                    "reconciliation": reconciliation}
    elif state.get("batches") and not retry_completed():
        index = state["next_batch"]
        child_id = f"{prior_request_id}:batch:{index}"
        child = service.store.get(ns, json.dumps([session, child_id], ensure_ascii=False))
        if child is not None:
            inspected = resume_maintenance(
                method, state["batches"][index], prior_request_id=child_id,
                execute=execute, **options,
            )
            reconciliation.append({"request_id": child_id, "result": inspected})
            if inspected.get("outcome") == "semantic_outcome_unconfirmed":
                return {**original, "outcome": "semantic_outcome_unconfirmed",
                        "reconciliation": reconciliation}
            if inspected["status"] == "completed":
                state["batch_results"][str(index)] = inspected
                state["next_batch"] += 1
                state["receipts"] = [
                    receipt for batch in state["batch_results"].values()
                    for receipt in batch["receipts"]
                ]
                if state["next_batch"] == len(state["batches"]):
                    state["phase"] = "complete"
                service.store.put(ns, key, state, index=False)
                original = maintain_event(
                    method, delivery, request_id=prior_request_id, execute=False, **options
                )
                if state["phase"] == "complete" and not retry_completed():
                    return {**original, "replayed": True, "reconciliation": reconciliation}
    else:
        for index in range(len(state.get("proposals", []))):
            previous_receipt = (
                state["receipts"][index] if index < len(state["receipts"]) else None
            )
            if previous_receipt is not None and not (
                previous_receipt.get("status") == "outcome_unknown"
                or previous_receipt.get("effect") == "unconfirmed"
            ):
                continue
            operation_id = f"{prior_request_id}:proposal:{index}"
            receipt = service.operation_receipt(session, operation_id)
            reconciliation.append({"operation_id": operation_id, "receipt": receipt})
            if receipt is None:
                return {**original, "outcome": "semantic_outcome_unconfirmed",
                        "reconciliation": reconciliation}
            state.setdefault("first_outcomes", []).append({
                "phase": state["phase"], "operation_id": operation_id,
                "receipt": previous_receipt,
            })
            if index < len(state["receipts"]):
                state["receipts"][index] = receipt
            else:
                state["receipts"].append(receipt)
            if receipt.get("ok"):
                state["unprocessed"] = [item for item in state["unprocessed"]
                                        if item.get("operation_id") != operation_id]
        if "proposals" in state and len(state["receipts"]) == len(state["proposals"]):
            state["phase"] = "incomplete" if state["unprocessed"] or any(
                not receipt.get("ok") for receipt in state["receipts"]
            ) else "complete"
            service.store.put(ns, key, state, index=False)
            original = maintain_event(
                method, delivery, request_id=prior_request_id, execute=False, **options
            )
            if state["phase"] == "complete" and not retry_completed():
                return {**original, "replayed": True, "reconciliation": reconciliation}

    if not execute or new_attempt_id is None:
        return {**original, "reconciliation": reconciliation,
                "continuation": "explicit_new_semantic_attempt_required"}
    if not new_attempt_id or new_attempt_id == prior_request_id:
        raise FunctionalRejection("EDIT_MAINTENANCE_NEW_ATTEMPT_ID_REQUIRED")
    attempt_session = session if new_attempt_session is None else new_attempt_session
    new_key = json.dumps([attempt_session, new_attempt_id], ensure_ascii=False)
    previous_attempt = service.store.get(ns, new_key)
    if previous_attempt is not None:
        if previous_attempt.value.get("prior_request_id") != prior_request_id:
            raise FunctionalRejection("EDIT_MAINTENANCE_NEW_ATTEMPT_ALREADY_BOUND")
        if previous_attempt.value.get("prior_session", attempt_session) != session:
            raise FunctionalRejection("EDIT_MAINTENANCE_NEW_ATTEMPT_ALREADY_BOUND")
    else:
        replacement = {
            "binding": state["binding"], "phase": "start", "receipts": [], "unprocessed": [],
            "prior_context": copy.deepcopy(state.get("prior_context", [])),
            "prior_request_id": prior_request_id,
            "date": state.get("date", date),
            **({"memory_save_requested": True} if state.get("memory_save_requested") else {}),
            **({"prior_session": session} if attempt_session != session else {}),
        }
        if "changes" in state:
            replacement.update(changes=copy.deepcopy(state["changes"]), phase="locate")
        if "work_items" in state:
            confirmed_work = [copy.deepcopy(work) for work in state["work_items"]
                              if work.get("status") == "completed" and (
                                  not retry_completed()
                                  or _has_semantic_receipt(work["result"]["receipts"])
                              )]
            if not retry_completed() or confirmed_work:
                replacement.update(
                    phase="views", directory=copy.deepcopy(state["directory"]),
                    work_items=confirmed_work,
                    receipts=[receipt for work in confirmed_work
                              for receipt in work["result"]["receipts"]],
                )
                for work in state["work_items"]:
                    if work.get("status") != "completed" or (
                        retry_completed() and not _has_semantic_receipt(work["result"]["receipts"])
                    ):
                        _append_work(replacement, new_attempt_id, work["records"],
                                     create=work["create"], done=work["done"])
        if state.get("batches"):
            confirmed = {
                str(index): state["batch_results"][str(index)]
                for index in range(state["next_batch"]) if not retry_completed()
                or _has_semantic_receipt(state["batch_results"][str(index)]["receipts"])
            }
            replacement.update(
                phase="batches", batches=copy.deepcopy(state["batches"]),
                batch_results=confirmed, next_batch=0 if retry_completed() else state["next_batch"],
                receipts=[receipt for batch in confirmed.values() for receipt in batch["receipts"]],
            )
            for index in range(state["next_batch"]):
                if str(index) in confirmed:
                    continue
                child = service.store.get(ns, json.dumps(
                    [session, f"{prior_request_id}:batch:{index}"], ensure_ascii=False
                ))
                if child is not None and "changes" in child.value:
                    service.store.put(ns, json.dumps(
                        [attempt_session, f"{new_attempt_id}:batch:{index}"], ensure_ascii=False
                    ), {
                        "binding": copy.deepcopy(child.value["binding"]), "phase": "locate",
                        "changes": copy.deepcopy(child.value["changes"]),
                        "prior_context": copy.deepcopy(child.value.get("prior_context", [])),
                        "date": child.value.get("date", date), "receipts": [], "unprocessed": [],
                        **({"memory_save_requested": True}
                           if state.get("memory_save_requested") else {}),
                    }, index=False)
        service.store.put(ns, new_key, replacement, index=False)
    return {
        **maintain_event(method, delivery, request_id=new_attempt_id,
                         **{**options, "session": attempt_session}),
        "new_attempt_id": new_attempt_id, "reconciliation": reconciliation,
    }
