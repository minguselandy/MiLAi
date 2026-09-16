"""Fixed local HTTP-shaped replay, never a tokenizer or model measurement.

Successful scripted outputs come from the complete frozen offline references.
The original Provider/Session/auditors still decide acceptance. Simulated token
counts preserve accounting paths, not the actual token length of these bytes.
No endpoint, handler, output override or live transport is accepted by the public
factory; the dedicated CPU process must already have its socket guard installed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from v0213_provider import TOKENIZE_KEYS
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_http import strict_http_json
from v0222_scoped_cpu_batch import OfflineBatch
from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard

MOCK_PROMPT_TOKENS = 100
MOCK_COMPLETION_TOKENS = 20


def _scripted_transport(identity: dict, outputs: tuple[str, ...]) -> httpx.MockTransport:
    """Pure script engine for unit tests too; this function grants no admission."""
    queue = iter(outputs)
    counted = None
    generated = 0

    def handle(request):
        nonlocal counted, generated
        route = request.url.path
        if request.method == "GET" and route == "/v1/models":
            return httpx.Response(
                200,
                json={"data": [{"id": identity["model"], "max_model_len": identity["context"]}]},
            )
        if request.method == "GET" and route == "/version":
            return httpx.Response(200, json={"version": identity["version"]})
        if request.method != "POST" or route not in {"/tokenize", "/v1/chat/completions"}:
            raise ProviderStop("CPU_REPLAY_ROUTE_NOT_IN_FIXED_SCRIPT")
        body = strict_http_json(request.content.decode("utf-8"))
        if body.get("model") != identity["model"]:
            raise ProviderStop("CPU_REPLAY_MODEL_DRIFT")
        if route == "/tokenize":
            counted = body
            return httpx.Response(200, json={"count": MOCK_PROMPT_TOKENS})
        if counted is None or fingerprint(counted) != fingerprint(
            {key: body[key] for key in TOKENIZE_KEYS}
        ):
            raise ProviderStop("CPU_REPLAY_REQUIRES_EXACT_ACTUAL_TOKENIZE_INPUT")
        counted = None
        try:
            raw = next(queue)
        except StopIteration as exc:
            raise ProviderStop("CPU_REPLAY_COMPLETE_SCRIPT_EXHAUSTED_NO_RETRY") from exc
        generated += 1
        return httpx.Response(
            200,
            json={
                "id": f"CPU_MOCK_ONLY-{generated}",
                "usage": {
                    "prompt_tokens": MOCK_PROMPT_TOKENS,
                    "completion_tokens": MOCK_COMPLETION_TOKENS,
                    "total_tokens": MOCK_PROMPT_TOKENS + MOCK_COMPLETION_TOKENS,
                },
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            },
        )

    return httpx.MockTransport(handle)


def make_mock_transport(batch: OfflineBatch, episode: str | None = None) -> httpx.MockTransport:
    require_cpu_network_guard()
    if (
        type(batch) is not OfflineBatch
        or batch.auth.get("execution_mode") != CPU_MODE
        or batch.auth.get("real_http_allowed") is not False
        or batch.auth.get("mock_cost_is_not_real_cost") is not True
    ):
        raise ProviderStop("EXACT_CPU_BATCH_REQUIRED_FOR_SCRIPTED_TRANSPORT")
    outputs = []
    if episode is not None:
        spec = batch.spec(episode)
        references = [row for row in batch.references(spec["stage"]) if row["episode"] == episode]
        total = 1 if spec["stage"] == "P3" else len(spec["actions"]) + 2
        if [row["turn"] for row in references] != list(range(1, total + 1)):
            raise ProviderStop("CPU_REPLAY_COMPLETE_ORDERED_REFERENCE_OUTPUTS_REQUIRED")
        for row in references:
            path = Path(row["output"])
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != row["hashes"]["output"]:
                raise ProviderStop("CPU_REPLAY_REFERENCE_OUTPUT_DRIFT")
            raw = strict_http_json(data.decode("utf-8"))["raw"]
            if type(raw) is not str:
                raise ProviderStop("CPU_REPLAY_EXACT_RAW_STRING_REQUIRED")
            outputs.append(raw)
    return _scripted_transport(batch.plan["http_identity"], tuple(outputs))
