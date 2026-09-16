#!/usr/bin/env python3
"""Build DG-17 Q0 measurement receipt and optionally run the 40-cell oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for path in (ROOT, RUNTIME_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evals.dg14.provider import MatchedVllmProvider
from evals.dg17.measurement import (
    ORACLE_PROMPT_LIMIT,
    build_q0_receipt,
    run_oracle_ladder,
)
from evals.paper.provider import MODEL_ID, _post_json, messages


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _token_count(base_url: str, case: Any, context: str) -> int:
    response, _headers = _post_json(
        base_url,
        "/tokenize",
        {
            "model": MODEL_ID,
            "messages": messages(case.question, case.question_at, context),
            "add_generation_prompt": True,
            "add_special_tokens": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=60,
    )
    count = response.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise RuntimeError("vLLM tokenizer returned an invalid count")
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument(
        "--oracle",
        action="store_true",
        help="Run A-D with the frozen matched vLLM; otherwise emit measurement only.",
    )
    args = parser.parse_args()

    receipt = build_q0_receipt()
    if args.oracle:
        provider = MatchedVllmProvider(
            args.base_url, prompt_token_budget=ORACLE_PROMPT_LIMIT
        )
        receipt = run_oracle_ladder(
            receipt,
            provider=provider,
            token_count=lambda case, context: _token_count(
                args.base_url, case, context
            ),
            run_id=args.run_id,
        )
        receipt["reader"] = {
            "base_url": args.base_url,
            "model_id": MODEL_ID,
            "prompt_token_limit": ORACLE_PROMPT_LIMIT,
            "automatic_retries": 0,
        }
    receipt["run_id"] = args.run_id
    output_dir = ROOT / "var/dg17/q0" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    payload = _canonical(receipt) + b"\n"
    output_path = output_dir / "receipt.json"
    output_path.write_bytes(payload)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(output_path.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(payload).hexdigest(),
                "aggregate": receipt["aggregate"],
                "oracle_status": receipt["oracle_ladder"]["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
