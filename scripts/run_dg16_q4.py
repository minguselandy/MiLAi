#!/usr/bin/env python3
"""Run the DG-16 Q4 matched Evidence-unit ablation with the frozen vLLM reader."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import DEFAULT_TOKENIZER, _atomic_json, _local_token_counter
from evals.dg14.provider import MatchedVllmProvider, full_provider_contract
from evals.dg16.q4 import run_q4_ablation
from evals.paper.provider import MODEL_ID


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    args = parser.parse_args()

    provider = MatchedVllmProvider(args.base_url)
    receipt = run_q4_ablation(
        run_id=args.run_id,
        provider=provider,
        token_count=_local_token_counter(args.tokenizer),
    )
    receipt["reader"] = {
        "base_url": args.base_url,
        "model_id": MODEL_ID,
        "provider_contract": full_provider_contract(),
        "automatic_retries": 0,
    }
    output_dir = ROOT / "var/dg16/q4" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "receipt.json"
    _atomic_json(output_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(output_path.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                "selection": receipt["selection"],
                "summaries": receipt["summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
