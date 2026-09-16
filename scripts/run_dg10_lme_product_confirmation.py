from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import lme_product_smoke as benchmark
from scripts.run_dg10_lme_product_smoke import (
    DEFAULT_DATASET,
    ENDPOINT,
    FREEZE_ROOT,
    run_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consume the frozen one-time 50-case LongMemEval confirmation split"
    )
    parser.add_argument(
        "--run-id",
        default=(
            "lme-confirmation-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument(
        "--freeze-manifest",
        type=Path,
        default=FREEZE_ROOT / "freeze-manifest-002.json",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run_benchmark(
        args.run_id,
        args.package_run_id,
        phase="CONFIRMATION",
        source_ids=benchmark.CONFIRMATION_SOURCE_IDS,
        dataset=args.dataset.resolve(),
        endpoint=args.endpoint,
        freeze_manifest=args.freeze_manifest.resolve(),
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "provider_requests": result["provider_requests"],
                "quality_gate_status": result["quality_gate_status"],
                "deltas": result["deltas_vs_strongest_baseline"],
                "category_deltas": result[
                    "category_deltas_vs_strongest_baseline"
                ],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
