"""Question-local evidence packs over existing Source ranges and immutable revisions."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.edit_units import read_revision_evidence
from milai_lab.memory.retrieval import flat_bm25_rank, merge_candidates
from milai_lab.memory.service import MemoryService
from milai_lab.memory.working_set import material_ref, plan_delivery
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.edit_memory import EditMemory


def unit_closure(state: dict[str, Any], unit_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Follow declared condition/exception edges, never textual similarity."""
    selected = {unit_id}
    changed = True
    while changed:
        previous = len(selected)
        for relation in state.get("relations", []):
            source, target = relation["source_unit"], relation["target_unit"]
            if target in selected:
                selected.add(source)
            if source == unit_id or (
                    source in selected and relation["relation_type"] == "overrides"):
                selected.add(target)
        changed = len(selected) != previous
    return ([unit["unit_id"] for unit in state["units"] if unit["unit_id"] in selected],
            [relation for relation in state.get("relations", [])
             if relation["source_unit"] in selected and relation["target_unit"] in selected])


def build_evidence_packs(
    service: MemoryService, question: str, date: str, originals: list[dict[str, Any]],
    records: list[dict[str, Any]], *,
    tokenization: Literal["rawrag_space", "unicode_v1"] = "unicode_v1",
    calendar_context: str | None = None,
) -> list[dict[str, Any]]:
    """Split only the captured pool; keep complete exchanges and one preceding exchange.

    Full captured parent ranges stay program-side for explicit context expansion.
    No later session source, semantic formation or new retrieval enters this pool.
    """
    source_packs = []
    for material in originals:
        turns = json.loads(material["text"])
        if not turns:
            continue
        starts = [i for i, turn in enumerate(turns) if turn["role"] == "user"]
        if not starts or starts[0] != 0:
            starts.insert(0, 0)
        for ordinal, (start, end) in enumerate(zip(starts, [*starts[1:], len(turns)], strict=True)):
            context_start = starts[max(0, ordinal - 1)]
            focused = turns[start:end]
            descriptors = material["source_ranges"][context_start:end]
            source_packs.append({
                **material, "id": f"{material['id']}:exchange:{start}",
                "source_ranges": descriptors,
                "turn_range": [material["turn_range"][0] + context_start,
                               material["turn_range"][0] + end],
                "text": json.dumps(turns[context_start:end], ensure_ascii=False),
                "focus_source_ranges": material["source_ranges"][start:end],
                "context_source_ranges": material["source_ranges"],
                "context_turn_range": material["turn_range"],
                "index_text": " ".join(turn["content"] for turn in focused),
                "pack_kind": "exchange_with_previous_context",
            })
    # Search within the identical original pool. RawRAG's own fixed path is unchanged.
    ranked = flat_bm25_rank(source_packs, question, len(source_packs),
                           tokenization=tokenization)
    semantic = []
    for row in records:
        version = row["value"]
        state = version.get("edit_state")
        if not state:
            continue
        hit = row.get("retrieval_navigation", {}).get("unit_id")
        ids, relations = (unit_closure(state, hit) if hit else
                          ([unit["unit_id"] for unit in state["units"]],
                           state.get("relations", [])))
        selected_units = [unit for unit in state["units"] if unit["unit_id"] in ids]
        handles = list(dict.fromkeys(ref["evidence_id"] for item in [*selected_units, *relations]
                                    for ref in item["evidence_refs"]))
        view = EditMemory.revision_view(version, query_time=date,
                                       query_calendar_context=calendar_context)
        view["units"] = [unit for unit in view["units"] if unit["unit_id"] in ids]
        view["relations"] = copy.deepcopy(relations)
        semantic.append({
            "kind": "semantic_view", "id": row["id"], "record_id": row["id"],
            "revision": version["revision"], "scope": version["scope"],
            "matter_description": state.get("matter_description", version["scope"]),
            "applicability": view, "selected_unit_ids": ids,
            "revision_evidence": read_revision_evidence(service, {"revision_evidence": handles}),
            "index_text": "\n".join(unit["text"] for unit in selected_units),
            "pack_kind": "supported_semantic_units",
        })
    return merge_candidates([ranked, semantic])


def open_evidence_packs(
    service: MemoryService, materials: list[dict[str, Any]], *, expand_context: bool = False,
) -> list[dict[str, Any]]:
    """Reopen selected exact sources/versions under current visibility, without search."""
    result = []
    for original in materials:
        item = copy.deepcopy(original)
        if item["kind"] == "original_source":
            if expand_context:
                item["source_ranges"] = item.get("context_source_ranges", item["source_ranges"])
                item["turn_range"] = item.get("context_turn_range", item["turn_range"])
            actual = service.read_source_materials([item])[0]
            focus = {span["source_ref"] for span in item.get(
                "focus_source_ranges", item["source_ranges"])}
            current_text = " ".join(turn["content"] for turn in json.loads(actual["text"])
                                    if turn["source_ref"] in focus)
            result.append({**item, **actual, "index_text": current_text})
        else:
            actual = service.read(item["record_id"], item["revision"])
            if not actual["ok"]:
                result.append({"kind": "semantic_view", "record_id": item["record_id"],
                               "visibility": actual["status"], "body_delivered": False})
                continue
            # A retained interpretation never bypasses current support visibility.
            evidence = []
            for span in item["revision_evidence"]:
                source = service.source(span["source_ref"])
                if source is None:
                    continue
                descriptor = {"kind": "original_source", "id": span["source_ref"],
                              "session_id": source["session"], "turn_range": [0, 1],
                              "source_ranges": [span]}
                evidence.extend(json.loads(service.read_source_materials([descriptor])[0]["text"]))
            result.append({**item, "support_turns": evidence})
    return result


def project_pack(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Short labels and literal evidence; locations and operation handles stay in the pool."""
    result: dict[str, Any] = {"label": f"e{index}", "kind": item["kind"]}
    if item.get("visibility") not in (None, "visible"):
        result["visibility"] = item["visibility"]
    if item.get("body_delivered") is False:
        return result
    turns = (json.loads(item["text"]) if item["kind"] == "original_source"
             else item.get("support_turns", []))
    sources = {turn["source_ref"]: f"e{index}:s{i}" for i, turn in enumerate(turns)}
    result["evidence"] = [{"source": sources[turn["source_ref"]], **{
        key: turn[key] for key in ("role", "origin", "content", "occurred_at", "observed_at",
                                   "calendar_context", "range") if key in turn},
        "report_time": turn.get("occurred_at", turn.get("timestamp")),
    } for turn in turns]
    if item["kind"] == "semantic_view":
        view = item["applicability"]
        ids = {unit["unit_id"]: f"u{i}" for i, unit in enumerate(view["units"])}
        result.update(scope=item["scope"], matter=item["matter_description"])
        result["units"] = [{"unit": ids[unit["unit_id"]], **{
            key: copy.deepcopy(unit[key]) for key in ("text", "role", "applicability", "temporal")
            if key in unit}, "assertion": {
                key: sources.get(value, "support_not_opened") if key == "source_ref" else value
                for key, value in unit.get("assertion", {}).items()
                if key not in {"source_revision"}
            }} for unit in view["units"]]
        result["relations"] = [{"source": ids[link["source_unit"]],
                                "target": ids[link["target_unit"]],
                                "relation_type": link["relation_type"]}
                               for link in view.get("relations", [])]
    return result


def pack_candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
    """An explicitly incomplete navigation excerpt, never an evidence body."""
    text = item.get("index_text", "") if item.get("body_delivered") is not False else ""
    return {"item_index": index, "kind": item["kind"], "navigation_only": True,
            "excerpt": text[:160], "excerpt_truncated": len(text) > 160,
            "date": item.get("date"), "visibility": item.get("visibility", "visible"),
            "can_expand_context": bool(item.get("context_source_ranges"))}


def read_question_pack(
    question: str, date: str, materials: list[dict[str, Any]], *, snapshot_id: str,
    open_materials: Callable[[list[dict[str, Any]], bool], list[dict[str, Any]]],
    messages_for: Callable[[list[dict[str, Any]]], list[dict[str, str]]],
    fits: Callable[[list[dict[str, str]]], bool],
    call: Callable[[str, list[dict[str, str]], dict[str, Any] | None], str],
    save: Callable[[dict[str, Any]], None], state: dict[str, Any], max_calls: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Select a budgeted pack; reopen more only for a stated evidence gap.

    Every decision uses the existing main Reader and one cumulative call limit.
    Candidate paging carries navigation only; it never forces all bodies into the Reader.
    State and HTTP caching are owned by the normal caller, not a second persistence layer.
    """
    refs = [material_ref(snapshot_id, i) for i in range(len(materials))]
    state.setdefault("steps", 0)
    state.setdefault("resident_refs", [])
    state.setdefault("opened_indices", [])
    state.setdefault("context_indices", [])
    state.setdefault("excluded_indices", [])
    state.setdefault("task", "lookup")
    state.setdefault("gap", None)
    state.setdefault("candidate_page", 0)
    state["retrieval_snapshot"] = snapshot_id
    state["evidence_policy"] = "question_pack_v1"

    def opened(indices: list[int]) -> list[dict[str, Any]]:
        return [open_materials([materials[i]], i in state["context_indices"])[0] for i in indices]

    def evidence_messages(indices: list[int]) -> list[dict[str, str]]:
        projected = [project_pack(item, i)
                     for i, item in zip(indices, opened(indices), strict=True)]
        return messages_for(projected)

    visible = open_materials(materials, False)
    directory = [pack_candidate(item, i) for i, item in enumerate(visible)]
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "answer": {"type": ["string", "null"]},
            "item_indices": {"type": "array", "uniqueItems": True,
                             "items": {"type": "integer", "enum": list(range(len(materials)))}}
                            if materials else {"type": "array", "maxItems": 0},
            "expand_context": {"type": "array", "uniqueItems": True,
                               "items": {"type": "integer", "enum": list(range(len(materials)))}}
                              if materials else {"type": "array", "maxItems": 0},
            "gap": {"type": ["string", "null"]},
            "task": {"enum": ["lookup", "range"]},
            "candidate_page": {"type": "integer", "minimum": 0},
        }, "required": ["answer", "item_indices", "expand_context", "gap", "task",
                         "candidate_page"],
    }

    def response_schema(indices: list[int]) -> dict[str, Any]:
        selected_schema = copy.deepcopy(schema)
        if not indices:
            selected_schema["properties"]["answer"] = {"type": "null"}
        return selected_schema

    def packet(indices: list[int], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages = evidence_messages(indices)
        payload = json.loads(messages[1]["content"])
        payload.update(candidates=candidates, candidate_page=state["candidate_page"],
                       admitted_indices=indices, excluded_indices=state["excluded_indices"],
                       evidence_gap=state["gap"], task=state["task"],
                       unopened_candidates=len(materials) - len(state["opened_indices"]),
                       coverage="retrieved_pool_only_not_full_history",
                       response_schema=response_schema(indices))
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        messages[0]["content"] += (
            "\nReturn JSON following response_schema. Candidate excerpts are only navigation; "
            "answer solely from supplied evidence bodies. If you can answer the original question, "
            "put the complete answer in answer. Otherwise set answer=null and item_indices to the "
            "necessary evidence in priority order (the next set replaces the current set). "
            "Only request another read for a specific gap in gap: missing subject, condition, "
            "negation, date, historical evidence or a needed live observation. expand_context "
            "reopens the captured parent exchange/session for those indices; it never adds later "
            "sources. For ordinary lookup, stop when evidence suffices; do not scan all pending "
            "candidates. For counting/enumeration use task=range, cover the requested range and "
            "state any incomplete coverage; retrieved candidates alone do not establish a full "
            "history. Candidate pages only locate evidence. Internal reading plans never replace "
            "the original question or its constraints. If the evidence cannot resolve the gap, "
            "answer the supported part and state the missing information."
        )
        return messages

    # A genuinely small complete pool keeps a one-call ordinary answer path.
    all_indices = list(range(len(materials)))
    if not state["steps"] and fits(evidence_messages(all_indices)):
        state.update(resident_refs=refs, opened_indices=all_indices, active_stage="answer")
        save(state)
        answer = call("answer", evidence_messages(all_indices), None)
        state.update(answer=answer, complete=True, delivery_plan={"body_delivered": True}, steps=1)
        save(state)
        return answer, visible

    if state.get("complete") and "answer" in state:
        return state["answer"], opened(state["opened_indices"])

    # Partition only navigation, using the full empty-evidence wrapper's actual cost.
    pages = plan_delivery([{"index": i} for i in all_indices], lambda rows: fits(packet(
        [], [directory[row["index"]] for row in rows])))
    catalogs = [[directory[row["index"]] for row in page] for page in pages["pages"]] or [[]]
    state["candidate_page_count"] = len(catalogs)
    while state["steps"] < max_calls:
        indices = [ref["item_index"] for ref in state["resident_refs"]]
        final_slot = state["steps"] == max_calls - 1 or state.get("final_only", False)
        if final_slot:
            messages = evidence_messages(indices)
            stop = ("No further evidence was requested." if state.get("final_only") else
                    "The total read budget is exhausted.")
            messages[0]["content"] += (
                "\n" + stop + " Answer the supported part of the original "
                "question and explicitly state the remaining gap; do not claim complete range "
                "coverage or invent unavailable information."
            )
            payload = json.loads(messages[1]["content"])
            payload.update(evidence_gap=state["gap"], excluded_indices=state["excluded_indices"],
                           coverage="retrieved_pool_only_not_full_history")
            messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            state["active_stage"] = "answer"
            save(state)
            answer = call("answer", messages, None)
        else:
            page = min(state["candidate_page"], len(catalogs) - 1)
            candidates = catalogs[page]
            # Exclude navigation from an evidence-bearing Reader packet when it cannot fit;
            # a further read can revisit that page with a smaller pack.
            messages = packet(indices, candidates)
            if not fits(messages):
                messages = packet(indices, [])
            stage = f"view/pack-{state['steps']}"
            state["active_stage"] = stage
            save(state)
            active_schema = response_schema(indices)
            response = parse_object(call(stage, messages, active_schema), reject_duplicate_keys=True)
            Draft202012Validator(active_schema).validate(response)
            answer = response["answer"]
            state["task"] = response["task"]
            if answer is None:
                previous = (indices, state["context_indices"], page)
                state.update(gap=response["gap"], candidate_page=response["candidate_page"],
                             context_indices=response["expand_context"])
                wanted = response["item_indices"]
                accepted: list[int] = []
                for index in wanted:
                    if fits(packet([*accepted, index], [])):
                        accepted.append(index)
                state["excluded_indices"] = [i for i in wanted if i not in accepted]
                state["resident_refs"] = [refs[i] for i in accepted]
                state["opened_indices"] = list(dict.fromkeys([*state["opened_indices"], *accepted]))
                if ((indices and not response["gap"]) or previous == (
                        accepted, state["context_indices"], state["candidate_page"])):
                    # No new evidence or explicit gap: use the remaining final-answer slot.
                    state["final_only"] = True
        state["steps"] += 1
        if answer is not None:
            state.update(answer=answer, complete=True, delivery_plan={"body_delivered": True},
                         coverage_complete=False)
            save(state)
            return answer, opened(state["opened_indices"])
        save(state)
    raise ValueError("READ_PACK_CALL_LIMIT_INVALID")
