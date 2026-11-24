"""Match vLLM serving-time intervals to completed requests and provider token totals."""

from __future__ import annotations

import json
import math
from urllib.parse import urljoin, urlsplit

import httpx

AXES = {
    "vllm:request_inference_time_seconds_count": "completed",
    "vllm:request_inference_time_seconds_sum": "running_seconds",
    "vllm:request_prompt_tokens_sum": "input_tokens",
    "vllm:request_generation_tokens_sum": "output_tokens",
}


def snapshot(host):
    # The research host exposes anonymous metrics beside the local Reader API.
    # Deployments without local vLLM metrics retain the separate client timing.
    if urlsplit(host["base_url"]).hostname not in {"127.0.0.1", "::1", "localhost"}:
        return None
    try:
        response = httpx.get(urljoin(host["base_url"], "/metrics"), timeout=1.5, trust_env=False)
        response.raise_for_status()
        numbers = {}
        label = "model_name=" + json.dumps(host["model"])
        for line in response.text.splitlines():
            axis = AXES.get(line.partition("{")[0])
            if axis and label in line.partition("}")[0]:
                numbers[axis] = numbers.get(axis, 0.0) + float(line.rsplit(None, 1)[-1])
        if len(numbers) == len(AXES) and all(math.isfinite(v) for v in numbers.values()):
            return numbers
    except (httpx.HTTPError, ValueError):
        pass
    return None


def interval(before, after, charged, costs):
    unknown = {"vllm_running_seconds": None, "matched_requests": 0}
    if not before or not after or not charged or len(costs) != charged:
        return unknown
    if any(
        c.get("reader_usage_source") != "provider"
        or any(type(c.get(k)) is not int for k in ("reader_input_tokens", "reader_output_tokens"))
        for c in costs
    ):
        return unknown
    delta = {k: after[k] - value for k, value in before.items()}
    exact = (
        delta["completed"] == charged
        and delta["input_tokens"] == sum(c["reader_input_tokens"] for c in costs)
        and delta["output_tokens"] == sum(c["reader_output_tokens"] for c in costs)
        and delta["running_seconds"] >= 0
    )
    if exact:
        return {"vllm_running_seconds": delta["running_seconds"], "matched_requests": charged}
    return unknown
