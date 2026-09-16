from __future__ import annotations

import hashlib
import json
from typing import Any

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
RESPONSE_RULES = """Response contract:
- AVAILABLE: return status KNOWN, the exact version from memory as answer, memory_used true.
- NO_MEMORY or UNAVAILABLE: return status UNKNOWN, answer UNKNOWN, memory_used false.
- UNCERTAIN: return status UNCERTAIN, answer UNCERTAIN, memory_used false.
Never infer or guess a version."""
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "status": {"type": "string", "enum": ["KNOWN", "UNKNOWN", "UNCERTAIN"]},
        "memory_used": {"type": "boolean"},
    },
    "required": ["answer", "status", "memory_used"],
    "additionalProperties": False,
}


class F1ContractError(RuntimeError):
    pass


def parse_answer(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise F1ContractError("provider response is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise F1ContractError("provider choices are invalid")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise F1ContractError("provider answer content is missing")
    try:
        answer = json.loads(message["content"])
    except json.JSONDecodeError as exc:
        raise F1ContractError("provider answer is not JSON") from exc
    if (
        not isinstance(answer, dict)
        or set(answer) != {"answer", "status", "memory_used"}
        or not isinstance(answer["answer"], str)
        or answer["status"] not in {"KNOWN", "UNKNOWN", "UNCERTAIN"}
        or not isinstance(answer["memory_used"], bool)
    ):
        raise F1ContractError("provider answer violates the F1 contract")
    return answer


def request_payload(messages: list[dict[str, str]], logical_request_id: str) -> dict[str, Any]:
    effective = [dict(message) for message in messages]
    effective[0]["content"] = effective[0]["content"] + "\n\n" + RESPONSE_RULES
    return {
        "model": MODEL_ID,
        "messages": effective,
        "temperature": 0,
        "max_tokens": 96,
        "stream": False,
        "seed": int(hashlib.sha256(logical_request_id.encode()).hexdigest()[:16], 16)
        & ((1 << 63) - 1),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "milai_f1_agent_answer",
                "strict": True,
                "schema": ANSWER_SCHEMA,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "include_reasoning": False,
        "cache_salt": hashlib.sha256(f"milai-f1:{logical_request_id}".encode()).hexdigest(),
    }
