"""Decode the XML tool format advertised by the deployed Qwen chat template.

Transport compatibility only: function names, schemas, arguments and native
benchmark tool dispatch are unchanged. Raw completions remain in the usage trace.
"""

from __future__ import annotations

import json
import re


def decode_tool_completion(text: str, tools: list[dict], request_id: str) -> dict:
    schemas = {item["function"]["name"]: item["function"].get("parameters", {}) for item in tools}
    blocks = list(
        re.finditer(
            r"<tool_call>\s*<function=([^>]+)>(.*?)</function>\s*</tool_call>", text, re.DOTALL
        )
    )
    if not blocks:
        return {"role": "assistant", "content": text}
    calls = []
    for index, block in enumerate(blocks):
        name, body = block.group(1).strip(), block.group(2)
        parameters = schemas.get(name, {}).get("properties", {})
        arguments = {}
        for match in re.finditer(r"<parameter=([^>]+)>(.*?)</parameter>", body, re.DOTALL):
            key, value = match.group(1).strip(), match.group(2).strip()
            kind = parameters.get(key, {}).get("type", "string")
            # A schema string stays a string even when it happens to look like a
            # JSON number/date. Structured parameters use their native JSON value.
            arguments[key] = value if kind == "string" else json.loads(value)
        calls.append(
            {
                "id": f"call_{request_id}_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        )
    content = text[: blocks[0].start()].strip()
    return {"role": "assistant", "content": content or None, "tool_calls": calls}
