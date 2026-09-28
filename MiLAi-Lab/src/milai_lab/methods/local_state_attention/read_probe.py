"""Read-only first-request views over a frozen Local State bank."""

from __future__ import annotations

import copy
import json
import math
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]

from milai_lab.methods.local_state_attention.integration import _render_view
from milai_lab.methods.local_state_attention.protocol import (
    READ_SELECTOR_PROMPT,
    UPDATE_SELECTOR_PROMPT,
    ControlResponseError,
    parse_json_response,
    read_selector_payload,
    selected_ids,
    selection_schema,
    state_directory,
)
from milai_lab.providers.contextual_vllm import VLLMClient

VIEW_MARKER = "[Local State working view:"


def sorted_states(bank: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [row["id"] for row in bank]
    if len(ids) != len(set(ids)) or any(not isinstance(key, str) or not key for key in ids):
        raise ValueError("LSA_PROBE_BANK_IDS_INVALID")
    return sorted(bank, key=lambda row: row["id"])


def query_top_two(bank: list[dict[str, Any]], query: str,
                  client: VLLMClient, model: str) -> list[dict[str, Any]]:
    states = sorted_states(bank)
    if not states:
        return []
    texts = [query, *(row["title"] + "\n" + row["content"] for row in states)]
    vectors = client.embed(texts, model)
    if len(vectors) != len(texts):
        raise ValueError("LSA_PROBE_EMBEDDING_COUNT_CHANGED")
    query_vector = vectors[0]

    def similarity(vector: list[float]) -> float:
        if len(vector) != len(query_vector):
            raise ValueError("LSA_PROBE_EMBEDDING_DIMENSION_CHANGED")
        denominator = math.sqrt(sum(value * value for value in query_vector)) * math.sqrt(
            sum(value * value for value in vector))
        if not denominator or not math.isfinite(denominator):
            raise ValueError("LSA_PROBE_EMBEDDING_NORM_INVALID")
        score = sum(left * right for left, right in zip(query_vector, vector,
                                                        strict=True)) / denominator
        if not math.isfinite(score):
            raise ValueError("LSA_PROBE_EMBEDDING_SCORE_INVALID")
        return score

    ranked = sorted(zip(states, vectors[1:], strict=True),
                    key=lambda item: (-similarity(item[1]), item[0]["id"]))
    return [row for row, _ in ranked[:2]]


def select_focus(bank: list[dict[str, Any]], query: str,
                 client: VLLMClient) -> list[dict[str, Any]]:
    states = sorted_states(bank)
    if not states:
        return []
    ids = [row["id"] for row in states]
    schema: dict[str, Any] = {
        "type": "object", "properties": {
            "focus": {"type": "array", "items": {"enum": ids}}},
        "required": ["focus"], "additionalProperties": False,
    }
    receipt = client.chat(
        [{"role": "system", "content": (
            "Choose only State identifiers useful to the current query. This is a read-only "
            "selection: do not edit States, answer the query, or infer future observations. "
            "Return exactly JSON {\"focus\":[...]} using only listed ids; empty is valid.")},
         {"role": "user", "content": json.dumps({"query": query, "states": states},
                                                ensure_ascii=False)}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "local_state_read_focus_v1", "strict": True, "schema": schema}},
    )
    try:
        choice = receipt["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError("LSA_PROBE_SELECTOR_INCOMPLETE")
        selected = json.loads(choice["message"]["content"])
        validate(selected, schema)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("LSA_PROBE_SELECTOR_INVALID") from error
    chosen = set(selected["focus"])
    return [row for row in states if row["id"] in chosen]


ANCHOR_PROMPT = (
    "From the current question and short State directory, return concise entity or "
    "topic anchors useful for retrieving the same States. Do not answer the question, "
    "edit States, or infer future observations. Return entity_anchors only."
)


def enhance_query(bank: list[dict[str, Any]], query: str,
                  client: VLLMClient) -> tuple[str, list[str]]:
    """Retain the entire original query as the retrieval query's exact prefix."""
    states = sorted_states(bank)
    schema: dict[str, Any] = {"type": "object", "properties": {
        "entity_anchors": {"type": "array", "items": {"type": "string", "minLength": 1},
                           "maxItems": 8}}, "required": ["entity_anchors"],
        "additionalProperties": False}
    receipt = client.chat(
        [{"role": "system", "content": ANCHOR_PROMPT},
         {"role": "user", "content": json.dumps(
             {"current_task": query, "directory": state_directory(states)},
             ensure_ascii=False)}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "local_state_query_anchors_v1", "strict": True, "schema": schema}})
    plan = parse_json_response(receipt)
    validate(plan, schema)
    anchors: list[str] = plan["entity_anchors"]
    augmented = (query + "\nEntity anchors: " + json.dumps(anchors, ensure_ascii=False)
                 if anchors else query)
    return augmented, anchors


def select_directory_a(bank: list[dict[str, Any]], query: str,
                       client: VLLMClient, *,
                       observations: list[dict[str, Any]] | None = None,
                       ) -> list[dict[str, Any]]:
    """Use the live LR/LRU directory A wire; old full-body focus remains separate."""
    states = sorted_states(bank)
    if not states:
        return []
    allowed = {row["id"] for row in states}
    receipt = client.chat(
        [{"role": "system", "content": READ_SELECTOR_PROMPT},
         {"role": "user", "content": json.dumps(
             read_selector_payload(query, observations or [], states),
             ensure_ascii=False)}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "local_state_read_selector_v1", "strict": True,
            "schema": selection_schema("read_ids", allowed)}})
    chosen = selected_ids(parse_json_response(receipt), "read_ids", allowed)
    if chosen is None:
        raise ValueError("LSA_READ_SELECTION_INVALID")
    ids = set(chosen)
    return [row for row in states if row["id"] in ids]


def select_directory_u(bank: list[dict[str, Any]],
                       observations: list[dict[str, Any]],
                       client: VLLMClient) -> list[dict[str, Any]]:
    """Select update candidates from actual observations, without a task field."""
    states = sorted_states(bank)
    if not states:
        return []
    allowed = {row["id"] for row in states}
    receipt = client.chat(
        [{"role": "system", "content": UPDATE_SELECTOR_PROMPT},
         {"role": "user", "content": json.dumps(
             {"new_observations": observations, "directory": state_directory(states)},
             ensure_ascii=False)}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "local_state_update_selector_v1", "strict": True,
            "schema": selection_schema("update_ids", allowed)}})
    chosen = selected_ids(parse_json_response(receipt), "update_ids", allowed)
    if chosen is None:
        raise ControlResponseError("LSA_UPDATE_SELECTION_INVALID")
    ids = set(chosen)
    return [row for row in states if row["id"] in ids]


def render_view(states: list[dict[str, Any]], context_text: str | None = None) -> str:
    if context_text is not None:
        return ("[Local State working view: diagnostic_only source context; "
                "original messages below remain unchanged.]\n" + context_text)
    return _render_view(sorted_states(states), [])


def replace_view(host_request: dict[str, Any], view: str) -> dict[str, Any]:
    """Replace only the trailing State view in the original first system copy."""
    request = copy.deepcopy(host_request)
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages or messages[0].get("role") != "system":
        raise ValueError("LSA_PROBE_FIRST_SYSTEM_MISSING")
    content = messages[0].get("content")
    if not isinstance(content, str):
        raise ValueError("LSA_PROBE_FIRST_SYSTEM_NOT_TEXT")
    start = content.find(VIEW_MARKER)
    if start < 1 or content[start - 1] != "\n" or content.find(VIEW_MARKER, start + 1) >= 0:
        raise ValueError("LSA_PROBE_ORIGINAL_VIEW_MISSING_OR_AMBIGUOUS")
    messages[0]["content"] = content[:start] + view
    return request


def first_action(receipt: dict[str, Any], host_request: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = receipt["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError("LSA_PROBE_HOST_INCOMPLETE")
        action = json.loads(choice["message"]["content"])
        schema = host_request["response_format"]["json_schema"]["schema"]
        validate(action, schema)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("LSA_PROBE_HOST_INVALID_ACTION") from error
    if not isinstance(action, dict):
        raise ValueError("LSA_PROBE_HOST_ACTION_NOT_OBJECT")
    return action
