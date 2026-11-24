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


# Each optional histogram is updated once when a request finishes on the frozen
# engine. Per-iteration gauges can include another request still in flight.
FINISHED_HISTOGRAMS = {
    "request_queue_time_seconds": "queue_seconds",
    "request_prefill_time_seconds": "prefill_seconds",
    "request_decode_time_seconds": "decode_seconds",
    "request_prefill_kv_computed_tokens": "computed_prompt_tokens",
}
OPTIONAL_AXES = {
    f"vllm:{histogram}_{stat}": f"{axis}_{stat}"
    for histogram, axis in FINISHED_HISTOGRAMS.items()
    for stat in ("sum", "count")
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
            metric = line.partition("{")[0]
            axis = AXES.get(metric) or OPTIONAL_AXES.get(metric)
            if axis and label in line.partition("}")[0]:
                numbers[axis] = numbers.get(axis, 0.0) + float(line.rsplit(None, 1)[-1])
        if set(AXES.values()) <= numbers.keys() and all(math.isfinite(v) for v in numbers.values()):
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
    if not set(AXES.values()) <= (before.keys() & after.keys()):
        return unknown
    delta = {k: after[k] - before[k] for k in before.keys() & after.keys()}
    exact = (
        delta["completed"] == charged
        and delta["input_tokens"] == sum(c["reader_input_tokens"] for c in costs)
        and delta["output_tokens"] == sum(c["reader_output_tokens"] for c in costs)
        and delta["running_seconds"] >= 0
    )
    if not exact:
        return unknown
    result = {"vllm_running_seconds": delta["running_seconds"], "matched_requests": charged}
    for axis in FINISHED_HISTOGRAMS.values():
        value = delta.get(axis + "_sum")
        if (
            delta.get(axis + "_count") != charged
            or value is None
            or not math.isfinite(value)
            or value < 0
        ):
            continue
        if axis == "computed_prompt_tokens":
            if value > delta["input_tokens"] or value != int(value):
                continue
            result["vllm_cached_prompt_tokens"] = int(delta["input_tokens"] - value)
        result["vllm_" + axis] = value
    return result
