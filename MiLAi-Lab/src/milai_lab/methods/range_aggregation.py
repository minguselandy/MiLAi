"""Bounded source-chunk extraction and a common final Reader, without a new fact store."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.working_set import plan_delivery
from milai_lab.methods.edit_maintenance import parse_object

Materials = list[dict[str, Any]]
Messages = list[dict[str, str]]


def aggregate_source_range(
    materials: Materials, *,
    open_materials: Callable[[Materials, bool], Materials],
    project: Callable[[Materials, list[int]], Materials],
    messages_for: Callable[[Materials], Messages],
    coverage: Callable[[Materials, list[dict[str, Any]] | None], dict[str, Any]],
    fits: Callable[[Messages], bool],
    call: Callable[[str, Messages, dict[str, Any] | None], str],
    save: Callable[[dict[str, Any]], None], state: dict[str, Any], max_calls: int,
) -> tuple[str, Materials]:
    """Summaries carry original pool indices; input coverage is not extraction correctness.

    Reserve one final call. If calls or summary capacity run out, retain explicit
    missing coverage instead of claiming an exact total. Original range visibility
    is rechecked before the summaries reach the final Reader.
    """
    state["evidence_policy"] = "range_aggregate_v1"
    if state.get("complete"):
        return state["answer"], open_materials(
            [materials[i] for i in state["opened_indices"]], False)
    aggregate = state.setdefault("range_aggregation", {"maps": []})
    raw_indices = [i for i, item in enumerate(materials) if item["kind"] == "original_source"]
    visible = dict(zip(raw_indices, open_materials(
        [materials[i] for i in raw_indices], False), strict=True))

    def map_schema(indices: list[int]) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "facts": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "source_indices": {"type": "array", "minItems": 1,
                                       "items": {"type": "integer", "enum": indices}},
                }, "required": ["text", "source_indices"]}},
            "unresolved": {"type": "array", "items": {"type": "string"}},
        }, "required": ["facts", "unresolved"]}

    def map_messages(indices: list[int], opened: Materials,
                     schema: dict[str, Any] | None = None) -> Messages:
        messages = messages_for(project(opened, indices))
        messages[0]["content"] += (
            "\nExtract source-bound facts needed for the original range/counting request. "
            "This is one chunk, not the complete history. Keep entity/event identities, values, "
            "dates, corrections, cancellations, conditions and uncertainty so later chunks can "
            "be combined. Do not output a final count or infer unseen events. Repeated mentions "
            "are not new events. source_indices names the delivered e labels' numeric indices; "
            "it is provenance, not a new event identity. Return response_schema JSON."
        )
        payload = json.loads(messages[1]["content"])
        payload.update(response_schema=map_schema(indices) if schema is None else schema,
                       chunk_only=True)
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return messages

    if "pages" not in aggregate:
        plan = plan_delivery([{"index": i} for i in raw_indices], lambda rows: fits(map_messages(
            [r["index"] for r in rows], [visible[r["index"]] for r in rows])), monotone=True)
        aggregate.update(pages=[[row["index"] for row in page] for page in plan["pages"]],
                         unavailable_indices=[row["index"] for row in plan["unavailable_refs"]])
        save(state)
    while len(aggregate["maps"]) < len(aggregate["pages"]) and state["steps"] < max_calls - 1:
        index = len(aggregate["maps"])
        indices = aggregate["pages"][index]
        opened = open_materials([materials[i] for i in indices], False)
        available = [i for i, item in zip(indices, opened, strict=True)
                     if item.get("body_delivered") is not False and item["source_ranges"]]
        if not available:
            aggregate["maps"].append({"indices": indices, "status": "source_unavailable",
                "facts": [], "unresolved": [], "input_ranges": []})
            save(state)
            continue
        schema = map_schema(available)
        messages = map_messages(indices, opened, schema)
        stage = f"view/range-map-{index}"
        state["active_stage"] = stage
        save(state)
        response = parse_object(call(stage, messages, schema),
                                reject_duplicate_keys=True)
        Draft202012Validator(schema).validate(response)
        aggregate["maps"].append({"indices": indices, "status": "mapped", **response,
            "input_ranges": [span for item in opened for span in item["source_ranges"]]})
        state["steps"] += 1
        state["opened_indices"] = list(dict.fromkeys([*state["opened_indices"], *indices]))
        save(state)

    mapped_indices = list(dict.fromkeys(i for chunk in aggregate["maps"] for i in chunk["indices"]))
    live = dict(zip(mapped_indices, open_materials(
        [materials[i] for i in mapped_indices], False), strict=True))
    retained, dropped = [], []
    for index, chunk in enumerate(aggregate["maps"]):
        if coverage([live[i] for i in chunk["indices"]], chunk["input_ranges"])["complete"]:
            retained.append(index)
        else:
            dropped.append(index)

    def represented(indices: list[int]) -> Materials:
        return [{"kind": "original_source", "source_ranges": aggregate["maps"][i]["input_ranges"]}
                for i in indices]

    def final_messages(indices: list[int]) -> Messages:
        summaries = [{"kind": "range_summary", "label": f"chunk-{i}",
            "facts": aggregate["maps"][i]["facts"],
            "unresolved": aggregate["maps"][i]["unresolved"]}
                     for i in indices]
        messages = messages_for(summaries)
        messages[0]["content"] += (
            "\nAnswer the original request using these model-extracted, source-indexed facts. "
            "Apply corrections/cancellations and dates, and merge repeated mentions of the same "
            "real-world item; do not sum chunk counts or count citations as events. The summaries "
            "are interpretations, not new original observations. Coverage describes raw ranges "
            "read by the mapper and represented here, not extraction correctness. If coverage "
            "or facts are incomplete, state the supported part and the unresolved range rather "
            "than inventing an exact total. Cite original source indices when useful."
        )
        payload = json.loads(messages[1]["content"])
        payload.update(range_aggregation={
            "raw_input_coverage": coverage(represented(list(range(len(aggregate["maps"])))), None),
            "summary_coverage": coverage(represented(indices), None),
            "planned_chunks": len(aggregate["pages"]), "processed_chunks": len(aggregate["maps"]),
            "mapped_chunks": sum(c["status"] == "mapped" for c in aggregate["maps"]),
            "included_chunks": indices, "source_unavailable_chunks": dropped,
            "extraction_correctness": "unverified_model_interpretation",
        })
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return messages

    summary_plan = plan_delivery([{"index": i} for i in retained], lambda rows: fits(
        final_messages([row["index"] for row in rows])), monotone=True)
    included = ([row["index"] for row in summary_plan["pages"][0]]
                if summary_plan["pages"] else [])
    aggregate.update(retained_chunks=included, source_unavailable_chunks=dropped,
                     unpresented_chunks=[i for i in retained if i not in included])
    state.update(active_stage="answer", resident_refs=[],
                 range_coverage=coverage(represented(included), None))
    save(state)
    answer = call("answer", final_messages(included), None)
    state.update(answer=answer, complete=True, steps=state["steps"] + 1,
                 coverage_complete=state["range_coverage"]["complete"],
                 delivery_plan={"body_delivered": bool(included), "kind": "range_summaries"})
    save(state)
    return answer, [live[i] for i in mapped_indices]
