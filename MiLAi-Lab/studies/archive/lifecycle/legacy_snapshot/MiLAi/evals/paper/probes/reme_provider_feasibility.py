"""Exercise ReMe's official AgentScope OpenAI wrapper against local vLLM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscope.message import UserMsg
from reme.components.as_llm import OpenAIAsLLM


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    component = OpenAIAsLLM(
        credential={"api_key": "vllm-api-key", "base_url": args.vllm_base_url},
        max_retries=0,
        model=args.model,
        parameters={"max_tokens": 32, "temperature": 0},
        stream=False,
    )
    await component.start()
    if component.model is None:
        raise RuntimeError("ReMe OpenAIAsLLM did not construct its model")
    call_started = time.perf_counter()
    response = await component.model(
        [UserMsg("pe03", "Reply with exactly PE03_REME_OK.")]
    )
    latency_ms = (time.perf_counter() - call_started) * 1000
    await component.close()
    text = "\n".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )
    usage = response.usage
    usage_value = (
        {
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_input_tokens": usage.cache_input_tokens,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "time_seconds": usage.time,
        }
        if usage is not None
        else None
    )
    gates = {
        "official_reme_openai_wrapper": component.__class__.__module__.startswith(
            "reme."
        ),
        "provider_response_nonempty": bool(text.strip()),
        "provider_usage_captured": usage_value is not None
        and usage_value["input_tokens"] > 0
        and usage_value["output_tokens"] > 0,
    }
    payload: dict[str, Any] = {
        "development_ai_reviews": 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": gates,
        "latency_ms": round(latency_ms, 3),
        "model": args.model,
        "paper_labels_opened": False,
        "provider_response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "schema": "milai.dg11.pe03.reme-provider-feasibility.v1",
        "started_at": started_at.isoformat(),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "system_id": "REME-OSS",
        "usage": usage_value,
        "vllm_base_url": args.vllm_base_url,
        "work_package": "DG11-PE03",
    }
    _atomic_json(args.output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-FP8")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860/v1")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(
        json.dumps(
            {"status": result["status"], "system_id": result["system_id"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
