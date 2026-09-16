from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_holdout
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_f0 as f0

DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
DEFAULT_FREEZE_ROOT = ROOT / "var/dg11/holdout/v1"
DG10_CANDIDATE = ROOT / "var/dg10/final/candidate"


def code_identity() -> str:
    return f0._tree_identity(
        [
            ROOT / "evals/benchmark/dg11_holdout.py",
            ROOT / "evals/benchmark/dg11_holdout_context_worker.py",
            ROOT / "scripts/freeze_dg11_holdout.py",
            ROOT / "scripts/run_dg11_holdout.py",
            ROOT / "runtime/src",
            ROOT / "integrations/mcp/src",
            ROOT / "integrations/python-client/src",
            ROOT / "integrations/openworker-mcp/src",
        ]
    )


def frozen_wheels() -> dict[str, dict[str, Any]]:
    manifest = json.loads(
        (DG10_CANDIDATE / "freeze-manifest.json").read_text(encoding="utf-8")
    )
    names = {
        "client_wheel": "milai_client-*.whl",
        "mcp_wheel": "milai_mcp-*.whl",
        "runtime_wheel": "milai_runtime-*.whl",
        "openworker_wheel": "milai_openworker_mcp-*.whl",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, pattern in names.items():
        matches = list((DG10_CANDIDATE / "packages").glob(pattern))
        expected = manifest["package_artifacts"][name]["sha256"]
        if len(matches) != 1 or dg11_state.sha256(matches[0]) != expected:
            raise dg11_holdout.HoldoutError(f"DG10 frozen wheel drifted: {name}")
        result[name] = {
            "path": str(matches[0].relative_to(ROOT)),
            "sha256": expected,
            "bytes": matches[0].stat().st_size,
        }
    return result


def freeze(dataset: Path, freeze_root: Path) -> dict[str, Any]:
    if freeze_root.exists():
        raise dg11_holdout.HoldoutError(f"holdout freeze already exists: {freeze_root}")
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise dg11_holdout.HoldoutError("LongMemEval source is not an array")
    source_ids, allocation = dg11_holdout.stratified_source_ids(rows)
    inputs = dg11_holdout.label_free_inputs(rows, source_ids)
    if dg11_holdout.allocation_from_inputs(inputs) != allocation:
        raise dg11_holdout.HoldoutError("frozen category allocation drifted")

    freeze_root.mkdir(parents=True, exist_ok=False)
    os.chmod(freeze_root, 0o700)
    inputs_path = freeze_root / "holdout-inputs.json"
    dg11_state.atomic_json(inputs_path, inputs)
    schedules = [list(dg11_holdout.schedule(index)) for index in range(len(source_ids))]
    schedule_counts = {
        arm: [
            sum(schedule[position] == arm for schedule in schedules)
            for position in range(len(dg11_holdout.ARMS))
        ]
        for arm in dg11_holdout.ARMS
    }
    manifest = {
        "schema": "milai.dg11.holdout-freeze.v1",
        "status": "FROZEN",
        "frozen_at": datetime.now(UTC).isoformat(),
        "split_seed_sha256": hashlib.sha256(
            dg11_holdout.SPLIT_SEED.encode()
        ).hexdigest(),
        "generation_seed_namespace_sha256": hashlib.sha256(
            dg11_holdout.GENERATION_SEED_NAMESPACE.encode()
        ).hexdigest(),
        "dataset_path": str(dataset.resolve()),
        "dataset_sha256": dg11_state.sha256(dataset),
        "case_count": dg11_holdout.CASE_COUNT,
        "arms": list(dg11_holdout.ARMS),
        "native_answer_requests": dg11_holdout.CASE_COUNT
        * len(dg11_holdout.ARMS),
        "source_ids": list(source_ids),
        "source_ids_sha256": dg11_holdout.digest(source_ids),
        "excluded_source_ids_sha256": dg11_holdout.digest(
            sorted(dg11_holdout.consumed_source_ids())
        ),
        "category_allocation": allocation,
        "selection": "DETERMINISTIC_PROPORTIONAL_STRATIFIED_CATEGORY_ROUND_ROBIN",
        "schedule": "FROZEN_FOUR_BY_FOUR_CYCLIC_LATIN_SQUARE",
        "schedule_position_counts_per_arm": schedule_counts,
        "holdout_inputs_path": str(inputs_path.relative_to(ROOT)),
        "holdout_inputs_sha256": dg11_state.sha256(inputs_path),
        "label_fields_in_inputs": False,
        "labels_opened": False,
        "consumption_path": str((freeze_root / "consumption.json").relative_to(ROOT)),
        "prompt_contract_sha256": benchmark.prompt_contract_sha256(),
        "model_id": benchmark.MODEL_ID,
        "memory_token_budget": benchmark.MEMORY_TOKEN_BUDGET,
        "max_output_tokens": benchmark.MAX_OUTPUT_TOKENS,
        "code_identity": code_identity(),
        "dg10_frozen_wheels": frozen_wheels(),
        "development_ai_reviews": 0,
    }
    dg11_state.atomic_json(freeze_root / "freeze-manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze a label-free DG11 holdout")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--freeze-root", type=Path, default=DEFAULT_FREEZE_ROOT)
    args = parser.parse_args()
    manifest = freeze(args.dataset.resolve(), args.freeze_root.resolve())
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "case_count": manifest["case_count"],
                "category_allocation": manifest["category_allocation"],
                "labels_opened": manifest["labels_opened"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
