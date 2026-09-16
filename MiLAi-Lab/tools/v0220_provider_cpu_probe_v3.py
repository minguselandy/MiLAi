"""Standalone container CPU probe. No engine is created, no completion request is sent.

Read a previously saved request from stdin. Reuse installed vLLM validation and
exception wrapping to explain the observed public HTTP error without settling it.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import inspect
import json
import sys
import traceback
from types import SimpleNamespace


async def probe(request: dict) -> dict:
    # Imported only inside an explicit CPU diagnostic process in the existing image.
    from vllm.config.structured_outputs import StructuredOutputsConfig
    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
    from vllm.entrypoints.serve.utils.error_response import create_error_response
    from vllm.v1.engine.async_llm import AsyncLLM
    from vllm.v1.engine.input_processor import InputProcessor

    counts = {"input_validation_entered": 0, "post_validation_reached": 0, "engine_submissions": 0}
    processor = InputProcessor.__new__(InputProcessor)
    processor.model_config = SimpleNamespace(
        max_logprobs=20, is_diffusion=False, logits_processor_pattern=None, logits_processors=None
    )
    processor.speculative_config = None
    processor.structured_outputs_config = StructuredOutputsConfig()
    processor.renderer = SimpleNamespace(tokenizer=object())

    def stop_before_any_lora_or_engine(*args, **kwargs):
        counts["post_validation_reached"] += 1
        raise RuntimeError("CPU_PROBE_STOP_AFTER_PARAMETER_VALIDATION_NO_ENGINE")

    processor._validate_lora = stop_before_any_lora_or_engine
    sampling = ChatCompletionRequest.model_validate(request).to_sampling_params(4096, {})

    async def add_request(request_id, prompt, params, **kwargs):
        counts["input_validation_entered"] += 1
        return processor.process_inputs(request_id, prompt, params, supported_tasks=("generate",))

    harness = SimpleNamespace(add_request=add_request, log_requests=False)
    observed = None
    try:
        async for _ in AsyncLLM.generate(
            harness, {"type": "token", "prompt_token_ids": [1]}, sampling, "cpu-shadow-only"
        ):
            raise AssertionError("NO_OUTPUT_ALLOWED_WITHOUT_ENGINE")
    except Exception as exc:
        cause = exc.__cause__
        observed = {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "cause_type": type(cause).__name__ if cause else None,
            "cause_message": str(cause) if cause else None,
            "cause_frames": [
                {"file": f.filename, "line": f.lineno, "function": f.name}
                for f in traceback.extract_tb(cause.__traceback__)
            ]
            if cause
            else [],
            "public_error": create_error_response(exc).model_dump(),
        }
    source_objects = [
        AsyncLLM.generate,
        InputProcessor.process_inputs,
        InputProcessor._validate_params,
        create_error_response,
    ]
    sources = {
        str(obj.__qualname__): {
            "source_file": inspect.getsourcefile(obj),
            "source": inspect.getsource(obj),
            "sha256": hashlib.sha256(inspect.getsource(obj).encode()).hexdigest(),
        }
        for obj in source_objects
    }
    return {
        "profile": "CPU_VALIDATION_AND_REAL_EXCEPTION_WRAPPER_NO_ENGINE",
        "counts": counts,
        "observed": observed,
        "sources": sources,
        "versions": {p: importlib.metadata.version(p) for p in ("vllm", "xgrammar", "llguidance")},
        "stubs": "No engine. Non-diffusion model metadata and non-Mistral tokenizer sentinel; "
        "rendered prompt replaced by one token because rejection occurs before prompt processing.",
        "historical_usage": "UNRESOLVED_NOT_INFERRED_FROM_CPU_REPRODUCTION",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe(json.load(sys.stdin)))))
