from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_holdout, dg11_recovery
from scripts import dg11_state

DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg11/splits/v1"
V1_INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
V1_SCORED = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/scored-records.json"
V1_CURRENT_CONTEXTS = (
    ROOT / "var/dg11/runs/dg11-holdout-20260823-001/contexts-dg11-current.json"
)
V1_DG10_CONTEXTS = (
    ROOT / "var/dg11/runs/dg11-holdout-20260823-001/contexts-dg10-frozen.json"
)


def _source_manifest(
    *, name: str, source_ids: tuple[str, ...], allocation: dict[str, int], consumption: Path
) -> dict[str, Any]:
    return {
        "schema": "milai.dg11.recovery-source-ids.v1",
        "split": name,
        "case_count": len(source_ids),
        "source_ids": list(source_ids),
        "source_ids_sha256": dg11_holdout.digest(source_ids),
        "category_allocation": allocation,
        "consumption_record_path": str(consumption.relative_to(ROOT)),
        "status": "FROZEN_UNCONSUMED",
    }


def freeze(dataset_path: Path, output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        raise dg11_recovery.RecoveryError(f"recovery freeze exists: {output_root}")
    rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    v1_inputs = json.loads(V1_INPUTS.read_text(encoding="utf-8"))
    pre_v1 = dg11_holdout.consumed_source_ids()
    v1_ids = {str(value) for value in v1_inputs["source_ids"]}
    if len(pre_v1) != 200 or len(v1_ids) != 100 or pre_v1.intersection(v1_ids):
        raise dg11_recovery.RecoveryError("consumed 300-case boundary drifted")
    consumed = pre_v1.union(v1_ids)
    partition = dg11_recovery.partition_remaining(rows, consumed)
    v2_ids = tuple(partition["generalization_v2"])
    paper_ids = tuple(partition["paper_test_v1"])
    v2_inputs = dg11_holdout.label_free_inputs(rows, v2_ids)
    paper_inputs = dg11_holdout.label_free_inputs(rows, paper_ids)

    scored = json.loads(V1_SCORED.read_text(encoding="utf-8"))
    current_contexts = json.loads(V1_CURRENT_CONTEXTS.read_text(encoding="utf-8"))
    dg10_contexts = json.loads(V1_DG10_CONTEXTS.read_text(encoding="utf-8"))
    error_matrix = dg11_recovery.build_v1_error_matrix(
        rows,
        scored["records"],
        current_contexts["records"],
        dg10_contexts["records"],
        tuple(str(value) for value in v1_inputs["source_ids"]),
    )

    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    try:
        os.chmod(temporary, 0o700)
        v2_root = temporary / "generalization-v2"
        paper_root = temporary / "paper-test-v1"
        v2_consumption = output_root / "generalization-v2/consumption.json"
        paper_consumption = output_root / "paper-test-v1/consumption.json"
        v2_manifest = _source_manifest(
            name="DG11_GENERALIZATION_V2",
            source_ids=v2_ids,
            allocation=partition["generalization_v2_allocation"],
            consumption=v2_consumption,
        )
        paper_manifest = _source_manifest(
            name="DG11_LME_PAPER_TEST_V1",
            source_ids=paper_ids,
            allocation=partition["paper_test_v1_allocation"],
            consumption=paper_consumption,
        )
        dg11_state.atomic_json(v2_root / "source-ids.json", v2_manifest)
        dg11_state.atomic_json(v2_root / "label-free-inputs.json", v2_inputs)
        dg11_state.atomic_json(paper_root / "source-ids.json", paper_manifest)
        dg11_state.atomic_json(paper_root / "label-free-inputs.json", paper_inputs)
        dg11_state.atomic_json(temporary / "v1-error-matrix.json", error_matrix)
        manifest = {
            "schema": "milai.dg11.recovery-splits-freeze.v1",
            "status": "PASS",
            "work_package": "DG11-R00",
            "run_id": "dg11-r00-freeze-20260823-001",
            "frozen_at": datetime.now(UTC).isoformat(),
            "dataset_path": str(dataset_path),
            "dataset_sha256": dg11_state.sha256(dataset_path),
            "dataset_case_count": len(rows),
            "split_seed_sha256": hashlib.sha256(
                dg11_recovery.RECOVERY_SPLIT_SEED.encode()
            ).hexdigest(),
            "consumed_before_recovery_count": len(consumed),
            "consumed_before_recovery_source_ids_sha256": dg11_holdout.digest(
                sorted(consumed)
            ),
            "generalization_v2": {
                **v2_manifest,
                "source_ids_manifest_path": str(
                    (output_root / "generalization-v2/source-ids.json").relative_to(ROOT)
                ),
                "label_free_inputs_path": str(
                    (output_root / "generalization-v2/label-free-inputs.json").relative_to(
                        ROOT
                    )
                ),
                "label_free_inputs_sha256": dg11_state.sha256(
                    v2_root / "label-free-inputs.json"
                ),
            },
            "paper_test_v1": {
                **paper_manifest,
                "source_ids_manifest_path": str(
                    (output_root / "paper-test-v1/source-ids.json").relative_to(ROOT)
                ),
                "label_free_inputs_path": str(
                    (output_root / "paper-test-v1/label-free-inputs.json").relative_to(
                        ROOT
                    )
                ),
                "label_free_inputs_sha256": dg11_state.sha256(
                    paper_root / "label-free-inputs.json"
                ),
            },
            "candidate_identity": {
                "status": "PLACEHOLDER",
                "value": None,
                "must_be_filled_by": "DG11-R06",
            },
            "v1_error_matrix_path": str(
                (output_root / "v1-error-matrix.json").relative_to(ROOT)
            ),
            "v1_error_denominator": error_matrix["case_count"],
            "provider_requests": 0,
            "hidden_provider_calls": 0,
            "development_ai_reviews": 0,
            "gates": {
                "remaining_split_overlap_zero": not bool(set(v2_ids).intersection(paper_ids)),
                "overlap_with_consumed_300_zero": not bool(
                    set(v2_ids).union(paper_ids).intersection(consumed)
                ),
                "paper_label_fields_zero": paper_inputs["label_fields_present"] is False,
                "generalization_label_fields_zero": v2_inputs["label_fields_present"]
                is False,
                "v1_error_denominator_100": error_matrix["case_count"] == 100,
                "provider_answer_calls_zero": True,
            },
        }
        dg11_state.atomic_json(temporary / "freeze-manifest.json", manifest)
        if not all(manifest["gates"].values()):
            raise dg11_recovery.RecoveryError("DG11-R00 gate failed")
        os.replace(temporary, output_root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    result = {
        "schema": "milai.dg11.recovery-result.v1",
        "run_id": manifest["run_id"],
        "work_package": "DG11-R00",
        "status": "PASS",
        "decision": "KEEP",
        "provider_requests": 0,
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "summary": {
            "consumed_before_recovery": 300,
            "generalization_v2_cases": 100,
            "paper_test_v1_cases": 100,
            "v1_error_denominator": 100,
        },
        "gates": manifest["gates"],
    }
    dg11_state.atomic_json(output_root / "result.json", result)
    dg11_state.atomic_json(ROOT / "var/dg11/dev/latest-result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": result["run_id"],
            "work_package": "DG11-R00",
            "status": "PASS",
            "decision": "KEEP",
            "provider_requests": 0,
            "development_ai_reviews": 0,
            "metrics": result["summary"],
        }
    )
    state = json.loads(dg11_state.CURRENT_STATE.read_text(encoding="utf-8"))
    recovery = state.setdefault("recovery_work_packages", {})
    recovery["DG11-R00"] = "PASS"
    state["recovery_phase"] = "R00_PASS"
    state["latest_result"] = result["run_id"]
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    result = freeze(args.dataset.resolve(), args.output_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
