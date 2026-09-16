"""Read-only SIM01 request accounting; no provider, tokenizer, model, or Product calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from v02_local_provider import accounting, read_events, write_json

LAB = Path(__file__).resolve().parents[1]
HISTORY = LAB / "artifacts/v02-local-vllm-simulation/local-sim-20260906b"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode())


def audit(root: Path) -> dict:
    baseline = json.loads((root / "baseline-manifest.json").read_text())["historical_sha256"]
    immutable = [p for p in baseline if not p.startswith("tools/")]
    for path in immutable:
        if sha(LAB / path) != baseline[path]:
            raise ValueError(f"HISTORICAL_IDENTITY_CHANGED: {path}")
    events = read_events(HISTORY / "provider-ledger.jsonl")
    reservations = {e["request_id"]: e for e in events if e["event"] == "RESERVED"}
    settlements = {e["request_id"]: e for e in events if e["event"] == "SETTLED"}
    rows = []
    for arm in ("G", "A", "B"):
        previous = []
        bootstrap = json.loads((HISTORY / arm / "bootstrap.json").read_text())
        layer = bootstrap["payload"].get("milai_lab_local_layered_v1", {})
        for path in sorted((HISTORY / arm).glob("*-request.json")):
            request = json.loads(path.read_text())
            key = path.name.removesuffix("-request.json")
            reserved, settled = reservations[key], settlements[key]
            payload = json.dumps(request, ensure_ascii=False).encode()
            if hashlib.sha256(payload).hexdigest() != reserved["payload_sha256"]:
                raise ValueError("ACTUAL_REQUEST_IDENTITY_CHANGED")
            messages = request["messages"]
            if messages[: len(previous)] != previous:
                raise ValueError("HISTORY_PREFIX_CHANGED")
            if reserved["prompt_tokens"] != settled["input_tokens"]:
                raise ValueError("TOKEN_BOUND_DID_NOT_MATCH")
            rows.append(
                {
                    "request_id": key,
                    "session": arm,
                    "request_sha256": sha(path),
                    "wire_payload_bytes": len(payload),
                    "input_tokens": settled["input_tokens"],
                    "output_tokens": settled["output_tokens"],
                    "raw_tokens": settled["input_tokens"] + settled["output_tokens"],
                    "message_count": len(messages),
                    "system_content_bytes": len(messages[0]["content"].encode()),
                    "initial_user_content_bytes": len(messages[1]["content"].encode()),
                    "bootstrap_l1_value_json_bytes": size(layer["l1"]) if layer else 0,
                    "bootstrap_prefetched_detail_json_bytes": (
                        size(bootstrap["prefetched_detail"])
                        if "prefetched_detail" in bootstrap
                        else 0
                    ),
                    "later_message_json_bytes": size(messages[2:]),
                    "previous_request_messages_resent": len(previous),
                    "previous_request_messages_json_bytes": size(previous) if previous else 0,
                    "response_schema_json_bytes": size(request["response_format"]),
                    "cached_input_tokens": (
                        settled.get("usage", {}).get("prompt_tokens_details") or {}
                    ).get("cached_tokens"),
                    "component_sizes_are_not_additive_token_attribution": True,
                }
            )
            previous = messages
    total = accounting(events)
    if len(rows) != total["requests"] or sum(r["raw_tokens"] for r in rows) != total["raw_tokens"]:
        raise ValueError("REQUEST_LEDGER_MISMATCH")
    full_action = {}
    for arm in ("A", "B"):
        result_path = HISTORY / arm / "result.json"
        answer = json.loads(json.loads(result_path.read_text())["answer"])
        reason = answer["reason"]
        # Inspectable literal anchors; these are not a general language judge.
        metric_terms = ("指标", "监控", "错误率", "p95")
        verify_terms = ("复核", "核对", "复查", "验证", "确认恢复", "检查恢复")
        verification_explicit = any(t in reason for t in verify_terms) and any(
            t in reason for t in metric_terms
        )
        full_action[arm] = {
            "source": "sources/02-approved-revision.md",
            "answer_artifact_sha256": sha(result_path),
            "mechanical_fields": {
                k: answer[k] for k in ("decision", "target", "destructive_change")
            },
            "after_rollback_metric_verification": (
                "UNDETERMINED_NEEDS_SEMANTIC_REVIEW"
                if verification_explicit
                else "REQUIRED_STEP_NOT_EXPLICITLY_DELIVERED"
            ),
            "full_action_pass": False if not verification_explicit else None,
            "notification_explicit": "通知" in reason,
            "all_other_semantic_dimensions": "NOT_SCORED",
            "scope": "Post-hoc source-anchored omission audit; not preregistered model effect",
        }
    a, b = total["sessions"]["A"]["raw_tokens"], total["sessions"]["B"]["raw_tokens"]
    result = {
        "status": "READ_ONLY_AUDIT_COMPLETE",
        "new_model_requests": 0,
        "new_model_tokens": 0,
        "historical_identity_checks": immutable,
        "requests": rows,
        "accounting": total,
        "b_minus_a_raw_tokens": b - a,
        "b_over_a_percent": (b / a - 1) * 100,
        "full_action_audit": full_action,
        "currency_cost": None,
        "token_component_attribution": "UNMEASURED",
        "cached_is_input_subset_not_additional_cost": True,
        "provider_contract_scope": "Historical loopback vLLM usage only",
    }
    write_json(root / "sim01-cost-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root)
    print(
        json.dumps(
            {
                "status": result["status"],
                "raw_tokens": result["accounting"]["raw_tokens"],
                "requests": len(result["requests"]),
                "b_over_a_percent": result["b_over_a_percent"],
            }
        )
    )
