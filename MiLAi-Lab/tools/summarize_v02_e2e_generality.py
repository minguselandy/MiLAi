"""Evidence-bound local request observations, never a semantic or generalization judge."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from v02_local_provider import accounting, read_events, write_json


def observe_requests(root: Path, arm: str) -> list[dict[str, Any]]:
    events = read_events(root / "provider-ledger.jsonl")
    rows = []
    for reservation in (e for e in events if e["event"] == "RESERVED" and e["session"] == arm):
        key = reservation["request_id"]
        if Path(key).name != key:
            raise ValueError("UNSAFE_REQUEST_ID")
        path = root / arm / f"{key}-request.json"
        request = json.loads(path.read_text())
        payload_hash = hashlib.sha256(json.dumps(request, ensure_ascii=False).encode()).hexdigest()
        if payload_hash != reservation["payload_sha256"]:
            raise ValueError("REQUEST_CONTENT_IDENTITY_MISMATCH")
        associated = [e for e in events if e["request_id"] == key]
        settled = [e for e in associated if e["event"] == "SETTLED"]
        if len(settled) > 1:
            raise ValueError("DUPLICATE_SETTLEMENT")
        status = "RESERVED_ONLY_NOT_PROVEN_SUBMITTED"
        if any(e["event"] in {"DISPATCH_ATTEMPT", "OUTCOME_UNKNOWN"} for e in associated):
            status = "SUBMISSION_UNKNOWN"
        receipt_path = root / arm / f"{key}-http.json"
        if settled and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            body = json.loads(receipt["body"])
            usage = body.get("usage", {})
            if (
                receipt["status_code"] == 200
                and usage.get("prompt_tokens") == settled[0]["input_tokens"]
                and usage.get("completion_tokens") == settled[0]["output_tokens"]
                and body.get("id") == settled[0].get("provider_request_id")
            ):
                status = "PROVIDER_RESPONSE_CONFIRMED"
        rows.append(
            {
                "request_id": key,
                "submission": status,
                "payload_sha256": payload_hash,
                "messages": request["messages"],
            }
        )
    return rows


def span_observation(requests: list[dict[str, Any]], span: str) -> dict[str, Any]:
    """Literal locations in actual recorded input. No inference about interpretation."""
    if not span:
        raise ValueError("EMPTY_SPAN_HAS_NO_EVIDENCE_VALUE")
    matches = []
    for request in requests:
        for index, message in enumerate(request["messages"]):
            content = message.get("content")
            if not isinstance(content, str):
                continue
            offset = content.find(span)
            if offset >= 0:
                matches.append(
                    {
                        "request_id": request["request_id"],
                        "message_index": index,
                        "character_offset": offset,
                        "characters": len(span),
                        "submission": request["submission"],
                    }
                )
    confirmed = any(m["submission"] == "PROVIDER_RESPONSE_CONFIRMED" for m in matches)
    unknown = any(m["submission"] == "SUBMISSION_UNKNOWN" for m in matches)
    return {
        "status": "CONFIRMED_INPUT"
        if confirmed
        else ("INPUT_SUBMISSION_UNKNOWN" if unknown else "NOT_PROVEN_PRESENTED"),
        "matches": matches,
        "correct_interpretation": "NOT_EVALUATED",
    }


def summarize(root: Path) -> dict[str, Any]:
    events = read_events(root / "provider-ledger.jsonl")
    requests = {arm: observe_requests(root, arm) for arm in ("G", "A", "B")}
    return {
        "status": "REQUEST_AUDIT_ONLY_E2E_UNVERIFIED",
        "new_model_requests": 0,
        "accounting": accounting(events),
        "requests": {
            arm: [{k: v for k, v in r.items() if k != "messages"} for r in rows]
            for arm, rows in requests.items()
        },
        "claims": {
            key: "NOT_EVALUATED"
            for key in (
                "semantic_fidelity",
                "task_correctness",
                "save_increment",
                "layering_increment",
                "holdout_generalization",
                "model_representation_robustness",
            )
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; preserve prior audit")
    write_json(args.output, summarize(args.root))
