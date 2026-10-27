"""Literal metadata index over messages already visible to the functional Host.

No Store, provider, controller state or hidden receipt fields enter this module.
The caller must apply its ordinary visibility projection before building the index.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

PRESENTATION = "request_adjacent_metadata_v1"
INDEX_PREFIX = "\n\nVisible evidence metadata:\n"
EFFECT_FIELDS = (
    "schema", "scope", "mutation_receipts", "pending_mutation_call_refs",
    "confirmed_semantic_commit_receipt_refs", "confirmed_semantic_commit_count",
    "raw_capture_is_semantic_save", "reads_perform_semantic_writes", "semantic_completion",
)
MATERIAL_FIELDS = (
    "ref", "label", "kind", "id", "record_id", "revision", "version_view", "visibility",
    "body_delivered", "query_time", "source_metadata", "source_metadata_semantics",
)
SOURCE_HEADER_FIELDS = (
    "source", "role", "origin", "capture_context", "range", "source_characters",
    "reported_at", "captured_at", "calendar_context",
)


def request_adjacent_metadata(
    messages: Sequence[BaseMessage], effects: dict[str, Any], material: dict[str, Any],
) -> tuple[list[BaseMessage], dict[str, Any]]:
    """Append copies of visible metadata to the current question; preserve history.

    Unstructured tool errors have no typed evidence references to index. They stay
    in the original messages, and their skipped positions remain in the audit.
    Indexing a returned item does not certify its truth, freshness or sufficiency.
    """
    entries, provenance, unparsed = [], [], []
    for position, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or message.name != "milai_retrieve":
            continue
        try:
            packet = json.loads(str(message.content))
        except json.JSONDecodeError:
            unparsed.append(position)
            continue
        if not isinstance(packet, dict) or packet.get("schema") != "milai_retrieval_result_v1":
            continue
        for number, item in enumerate(packet["evidence"]):
            compact = {key: copy.deepcopy(item[key]) for key in MATERIAL_FIELDS if key in item}
            headers = [{key: copy.deepcopy(source[key]) for key in SOURCE_HEADER_FIELDS
                        if key in source} for source in item.get("evidence", [])]
            if headers:
                compact["source_headers_as_returned"] = headers
            entries.append(compact)
            provenance.append({"message_index": position, "evidence_index": number,
                "copied_fields": [key for key in MATERIAL_FIELDS if key in item],
                "source_header_count": len(headers)})
    index = {"current_request_receipt_fields": {
        key: copy.deepcopy(effects[key]) for key in EFFECT_FIELDS},
        **({"source_arrivals_as_shown": copy.deepcopy(material["source_arrivals"])}
           if "source_arrivals" in material else {}),
        "visible_retrieval_receipt_metadata": entries}
    position = next(i for i in range(len(messages) - 1, -1, -1)
                    if isinstance(messages[i], HumanMessage))
    question = messages[position]
    if not isinstance(question.content, str):
        raise ValueError("Request-adjacent metadata requires a text public question")
    suffix = INDEX_PREFIX + json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    presented = list(messages)
    presented[position] = question.model_copy(update={"content": question.content + suffix})
    return presented, {"event": "host_evidence_presentation", "mode": PRESENTATION,
        "index": index, "source_messages": provenance, "unparsed_tool_message_indices": unparsed,
        "current_question_index": position,
        "positions_in": "Projected wire messages before the ordinary system prompt",
        "information_scope": "Literal copies of already visible metadata; original messages "
                             "remain intact. No semantic sufficiency or new evidence inferred."}
