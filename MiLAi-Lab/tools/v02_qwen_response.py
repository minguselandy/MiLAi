"""Decode completed Qwen XML tool output into Responses items, without choosing tools.

The deployed tokenizer wraps parameter values in one optional LF on either side.
String contents are otherwise retained verbatim. Non-string JSON values use the
advertised parameter schema; malformed markup is a protocol failure, never repaired.
"""

from __future__ import annotations

import copy
import json
import re

from v02_local_provider import LocalGateError

CALL = re.compile(r"<tool_call>\s*<function=([^>]+)>(.*?)</function>\s*</tool_call>", re.S)
PARAM = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.S)


def parameter_value(value: str, schema: dict):
    value = value.removeprefix("\n").removesuffix("\n")
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    for branch in schema.get("anyOf", []) + schema.get("oneOf", []):
        kind = branch.get("type", [])
        kinds += [kind] if isinstance(kind, str) else kind
    if not kinds or "string" in kinds:
        return value
    # Invalid typed values still reach the actual tool's argument validator.
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def decode_response(response: dict, tools: list[dict]) -> dict:
    definitions = {}
    for tool in tools:
        members = tool["tools"] if tool["type"] == "namespace" else [tool]
        for member in members:
            namespace = tool["name"] if tool["type"] == "namespace" else None
            name = (namespace + "__" if namespace else "") + member["name"]
            definitions[name] = (namespace, member)
    result = copy.deepcopy(response)
    output = []
    for item in result["output"]:
        if item["type"] != "message":
            output.append(item)
            continue
        parts = item["content"]
        if not any("<tool_call>" in p.get("text", "") for p in parts):
            output.append(item)
            continue
        if len(parts) != 1 or parts[0]["type"] != "output_text":
            raise LocalGateError("QWEN_MULTIPART_TOOL_MARKUP_UNSUPPORTED")
        text = parts[0]["text"]
        position = 0
        for match in CALL.finditer(text):
            prefix = text[position:match.start()]
            if "<tool_call>" in prefix:
                raise LocalGateError("QWEN_MALFORMED_TOOL_MARKUP")
            if prefix.strip():
                output.append({**item, "id": item["id"] + f"_text_{len(output)}",
                               "content": [{**parts[0], "text": prefix}]})
            name, body = match.groups()
            if name not in definitions:
                raise LocalGateError("QWEN_UNADVERTISED_TOOL")
            namespace, definition = definitions[name]
            arguments = {}
            cursor = 0
            for param in PARAM.finditer(body):
                if body[cursor:param.start()].strip() or param[1] in arguments:
                    raise LocalGateError("QWEN_MALFORMED_OR_DUPLICATE_PARAMETER")
                schema = definition.get("parameters", {}).get("properties", {}).get(param[1], {})
                arguments[param[1]] = parameter_value(param[2], schema)
                cursor = param.end()
            if body[cursor:].strip():
                raise LocalGateError("QWEN_INCOMPLETE_PARAMETER")
            identity = f"{response['id']}_{len(output)}"
            call = {"type": "function_call", "id": "fc_" + identity,
                    "call_id": "call_" + identity, "name": definition["name"],
                    "arguments": json.dumps(arguments, ensure_ascii=False), "status": "completed"}
            if namespace:
                call["namespace"] = namespace
            output.append(call)
            position = match.end()
        if text[position:].strip():
            raise LocalGateError("QWEN_INCOMPLETE_CALL_OR_SUFFIX")
    result["output"] = output
    return result


def response_events(response: dict) -> bytes:
    """Buffered completed response; no claim of live token streaming."""
    events = [{"type": "response.created",
               "response": {**response, "status": "in_progress", "output": []}}]
    for index, item in enumerate(response["output"]):
        events.extend([
            {"type": "response.output_item.added", "output_index": index, "item": item},
            {"type": "response.output_item.done", "output_index": index, "item": item}])
    events.append({"type": "response.completed", "response": response})
    return b"".join(("event: " + event["type"] + "\ndata: " + json.dumps(
        {**event, "sequence_number": i}, ensure_ascii=False) + "\n\n").encode()
        for i, event in enumerate(events))
