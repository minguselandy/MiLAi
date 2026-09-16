"""Zero-model native client check of the same budget/codec gateway used by probes."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from run_v02_native_session import run
from v02_local_provider import ENDPOINT, MODEL, write_json


def check(root: Path) -> dict:
    calls = []

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        calls.append(body)
        assert len(calls) <= 2
        text = ('<tool_call>\n<function=exec_command>\n<parameter=cmd>\npwd\n</parameter>'
                '\n</function>\n</tool_call>' if len(calls) == 1 else "Gateway check completed.")
        return httpx.Response(200, json={"id": f"resp_fixed_{len(calls)}", "object": "response",
            "model": MODEL, "created_at": int(time.time()), "status": "completed",
            "output": [{"type": "message", "id": f"msg_fixed_{len(calls)}", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": text,
                                                      "annotations": []}]}],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}})

    allocation = {"provider_base_url": ENDPOINT, "model": MODEL,
        "paid_model_allocations_authorized": 0, "request_timeout_seconds": 10,
        "model_transport_enabled": True, "new_model_tokens_authorized": 2000,
        "new_model_allocations_authorized": 1, "local_sessions": ["fixture"],
        "session_token_limit": 2000, "batch_token_limit": 2000, "max_requests_per_session": 2,
        "request_input_token_limit": 1000, "max_output_tokens": 300,
        "request_raw_token_limit": 1000, "output_codec": "qwen_xml", "session_deadline_seconds": 60}
    report = run(root, allocation, "Report the current directory name.", "fixture",
                 transport=httpx.MockTransport(respond))
    first = json.loads((root / "fixture-001-decoded.json").read_text())["output"][0]
    result = next((item for item in calls[1]["input"] if item.get("type") == "function_call_output"
                   and item["call_id"] == first["call_id"]), None) if len(calls) == 2 else None
    presented = result is not None and "/workspace" in result["output"]
    report.update(actual_model_generations=0, actual_tokenize_requests=0,
                  tool_result_in_next_request=presented)
    write_json(root / "gateway-check.json", report)
    assert report["status"] == "COMPLETED" and report["tool_result_in_next_request"]
    assert report["container_absent"] and not report["accounting"]["pending"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.root.resolve())))
