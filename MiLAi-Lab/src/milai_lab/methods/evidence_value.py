"""Incremental evidence value over the same visible pool and common Reader.

The model estimates task gain conditioned on the already opened evidence. The
program measures incremental Reader input cost and opens one affordable positive
choice. Values are predictions, not correctness labels or a trained-model claim.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.working_set import plan_delivery
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.evidence_reading import (
    SOURCE_REUSE_INSTRUCTIONS,
    pack_candidate,
    pack_coverage,
    project_packs,
    read_question_pack,
)

VALUE_INSTRUCTIONS = (
    "Choose the next evidence action for the original question. Nominate up to three options. "
    "Estimate each nominated "
    "candidate's marginal task gain given the evidence already opened, not standalone relevance "
    "or answer confidence. State which answer distinction it could resolve: subject, date, "
    "negation, condition or exception. Equivalent support already present can make a highly "
    "relevant source add no value. The supplied input cost is measured by the program. "
    "action=open opens a candidate body; supplement addresses a specific gap and may expand "
    "an already opened candidate to its captured context; answer stops acquisition. Values "
    "range from -1 to 1; a nonpositive gain does not justify another read. Candidate excerpts "
    "only locate evidence; they are not evidence bodies. Missing evidence does not establish "
    "the opposite answer. candidate_page can request another navigation page. For range "
    "counting/enumeration use task=range; this first value policy delegates coverage to the "
    "existing range reader and does not claim a new aggregation method. Return the schema."
)


def value_schema(size: int) -> dict[str, Any]:
    return {"title": "evidence_value_v1", "type": "object", "additionalProperties": False,
        "properties": {
            "action": {"enum": ["open", "supplement", "answer"]},
            "values": {"type": "array", "maxItems": 3, "items": {"type": "object",
                "additionalProperties": False, "properties": {
                    "item_index": {"type": "integer", "minimum": 0, "maximum": size - 1},
                    "expand_context": {"type": "boolean"},
                    "gain": {"type": "number", "minimum": -1, "maximum": 1},
                    "answer_distinction": {"type": "string"},
                }, "required": ["item_index", "expand_context", "gain", "answer_distinction"]}},
            "gap": {"type": ["string", "null"]},
            "task": {"enum": ["lookup", "range"]},
            "candidate_page": {"type": "integer", "minimum": 0},
        }, "required": ["action", "values", "gap", "task", "candidate_page"]}


def read_by_evidence_value(
    question: str, date: str, materials: list[dict[str, Any]], *, snapshot_id: str,
    open_materials: Callable[[list[dict[str, Any]], bool], list[dict[str, Any]]],
    messages_for: Callable[[list[dict[str, Any]]], list[dict[str, str]]],
    fits: Callable[[list[dict[str, str]]], bool],
    measure: Callable[[list[dict[str, str]]], int],
    call: Callable[[str, list[dict[str, str]], dict[str, Any] | None], str],
    save: Callable[[dict[str, Any]], None], state: dict[str, Any], max_calls: int,
    source_scope: dict[str, Any] | None = None, direct_pool_size: int = 4,
) -> tuple[str, list[dict[str, Any]]]:
    """One conditional-value trajectory, within the existing read-call budget."""
    common: dict[str, Any] = {"snapshot_id": snapshot_id, "open_materials": open_materials,
              "messages_for": messages_for, "fits": fits, "call": call, "save": save,
              "max_calls": max_calls, "source_scope": source_scope}
    if len(materials) <= direct_pool_size:
        state["value_branch"] = "small_pool_common_reader"
        return read_question_pack(question, date, materials, state=state, **common)
    state.setdefault("steps", 0)
    state.setdefault("opened_indices", [])
    state.setdefault("context_indices", [])
    state.setdefault("candidate_page", 0)
    state.setdefault("value_trace", [])
    state.setdefault("candidate_cost_evaluations", 0)
    state.setdefault("source_pack_opens", 0)
    state["evidence_policy"] = "evidence_value_v1"
    state["value_estimator"] = "prompt_only_same_model; untrained_gain_predictions"
    state["retrieval_snapshot"] = snapshot_id

    def opened(indices: list[int], context: list[int] | None = None) -> list[dict[str, Any]]:
        selected_context = state["context_indices"] if context is None else context
        state["source_pack_opens"] += len(indices)
        return [open_materials([materials[index]], index in selected_context)[0]
                for index in indices]

    def save_range(value: dict[str, Any]) -> None:
        state["range_state"] = copy.deepcopy(value)
        state["active_stage"] = value.get("active_stage", state.get("active_stage"))
        state["total_steps"] = state["steps"] + value.get("steps", 0)
        save(state)

    def answer_messages(
        indices: list[int], context: list[int] | None = None,
    ) -> list[dict[str, str]]:
        rows = opened(indices, context)
        messages = messages_for(project_packs(rows, indices))
        messages[0]["content"] += "\n" + SOURCE_REUSE_INSTRUCTIONS
        payload = json.loads(messages[1]["content"])
        payload.update(source_coverage=pack_coverage(materials, rows, scope=source_scope),
                       evidence_gap=state.get("gap"))
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return messages

    if state.get("complete"):
        return state["answer"], opened(state["opened_indices"])
    if state.get("value_branch") == "range_common_reader":
        return read_question_pack(question, date, materials, state=state["range_state"],
            **{**common, "max_calls": max_calls - state["steps"],
               "save": save_range})

    visible = open_materials(materials, False)
    state["source_pack_opens"] += len(materials)
    state["candidate_inventory_count"] = len(materials)
    directory = [pack_candidate(item, index) for index, item in enumerate(visible)]
    schema = value_schema(len(materials))

    def packet(candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages = answer_messages(state["opened_indices"])
        messages[0]["content"] += "\n" + VALUE_INSTRUCTIONS
        payload = json.loads(messages[1]["content"])
        payload.update(candidates=candidates, candidate_page=state["candidate_page"],
                       already_opened=state["opened_indices"], response_schema=schema)
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return messages

    pages = plan_delivery(directory, lambda rows: fits(packet(rows)))["pages"] or [[]]
    state["candidate_page_count"] = len(pages)
    while state["steps"] < max_calls - 1 and not state.get("value_stop"):
        page = min(state["candidate_page"], len(pages) - 1)
        indices = state["opened_indices"]
        base_cost = measure(answer_messages(indices))
        candidates = []
        for candidate in pages[page]:
            index = candidate["item_index"]
            expand = index in indices
            if expand and (index in state["context_indices"]
                           or not candidate["can_expand_context"]):
                continue
            chosen = list(dict.fromkeys([*indices, index]))
            context = list(dict.fromkeys([*state["context_indices"], index])) if expand else None
            cost = measure(answer_messages(chosen, context)) - base_cost
            state["candidate_cost_evaluations"] += 1
            candidates.append({**candidate, "expand_context": expand,
                               "incremental_input_tokens": max(0, cost)})
        messages = packet(candidates)
        # Newly opened bodies can reduce room for navigation; keep the body and
        # use a smaller actual navigation page, without reading omitted candidates.
        if not fits(messages):
            smaller = plan_delivery(candidates, lambda rows: fits(packet(rows)))["pages"]
            if not smaller:
                state["value_stop"] = "selection_input_exhausted"
                break
            candidates = smaller[0]
            messages = packet(candidates)
        stage = f"view/value-{state['steps']}"
        state["active_stage"] = stage
        save(state)
        response = parse_object(call(stage, messages, schema), reject_duplicate_keys=True)
        Draft202012Validator(schema).validate(response)
        state["steps"] += 1
        state["gap"] = response["gap"]
        state["candidate_page"] = min(response["candidate_page"], len(pages) - 1)
        trace: dict[str, Any] = {"before_indices": list(indices), "response": response,
                                 "selected": None}
        state["value_trace"].append(trace)
        if response["task"] == "range":
            state.update(value_branch="range_common_reader", range_state={})
            save(state)
            return read_question_pack(question, date, materials, state=state["range_state"],
                **{**common, "max_calls": max_calls - state["steps"],
                   "save": save_range})
        if response["action"] == "answer" or (
                response["action"] == "supplement" and not response["gap"]):
            state["value_stop"] = "model_stopped" if response["action"] == "answer" else "no_gap"
            save(state)
            break
        offers: list[tuple[float, int, dict[str, Any], list[int], list[int] | None, int]] = []
        seen: set[tuple[int, bool]] = set()
        for value in response["values"]:
            index, expand = value["item_index"], value["expand_context"]
            if (index, expand) in seen:
                continue
            seen.add((index, expand))
            if value["gain"] <= 0 or visible[index].get("body_delivered") is False:
                continue
            if index in indices and (not expand or index in state["context_indices"]):
                continue
            if expand and not materials[index].get("context_source_ranges"):
                continue
            chosen = list(dict.fromkeys([*indices, index]))
            context = list(dict.fromkeys([*state["context_indices"], index])) if expand else None
            proposed = answer_messages(chosen, context)
            if fits(proposed):
                cost = max(0, measure(proposed) - measure(answer_messages(indices)))
                offers.append((value["gain"] / max(1, cost), -index, value, chosen, context, cost))
        if offers:
            _, _, value, chosen, context, cost = max(offers, key=lambda item: item[:2])
            trace.update(selected=copy.deepcopy(value), incremental_input_tokens=cost)
            state["opened_indices"] = chosen
            if context is not None:
                state["context_indices"] = context
        elif state["candidate_page"] == page:
            state["value_stop"] = "no_positive_affordable_increment"
        save(state)
    state["active_stage"] = "answer"
    save(state)
    answer = call("answer", answer_messages(state["opened_indices"]), None)
    state.update(answer=answer, complete=True, steps=state["steps"] + 1,
                 delivery_plan={"body_delivered": bool(state["opened_indices"])},
                 range_coverage=pack_coverage(materials, opened(state["opened_indices"]),
                                              scope=source_scope))
    save(state)
    return answer, opened(state["opened_indices"])
