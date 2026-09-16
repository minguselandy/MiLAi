#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.product03_opportunity import (  # noqa: E402
    compare_mechanisms,
    select_allowed_treatment,
)
from run_product03_opportunity_probe import _load_artifact_cases  # noqa: E402


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize Product-03 P1 opportunity evidence")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    baseline_terminal = json.loads(
        (args.baseline / "terminal.json").read_text(encoding="utf-8")
    )
    diagnostic_terminal = json.loads(
        (args.diagnostic / "terminal.json").read_text(encoding="utf-8")
    )
    if (
        baseline_terminal.get("status") != "PASS_PRODUCT03_A0_CAPTURED"
        or diagnostic_terminal.get("status") != "PASS_PRODUCT03_T1_SELECTED"
        or baseline_terminal.get("product_lock_digest")
        != diagnostic_terminal.get("product_lock_digest")
    ):
        parser.error("source opportunity terminals are not matched PASS evidence")

    diagnostic_cases = _load_artifact_cases(args.diagnostic)
    selected_ids = {case.case_id for case in diagnostic_cases}
    comparison = compare_mechanisms(
        [
            case
            for case in _load_artifact_cases(args.baseline)
            if case.case_id in selected_ids
        ],
        diagnostic_cases,
    )
    selected = select_allowed_treatment(comparison)
    started_at = datetime.now(UTC)
    run_id = f"product03-opportunity-final-{started_at:%Y%m%dT%H%M%SZ}"
    artifacts = RunArtifacts(args.output)
    sources = {
        "baseline_terminal_sha256": _sha256_file(args.baseline / "terminal.json"),
        "diagnostic_terminal_sha256": _sha256_file(args.diagnostic / "terminal.json"),
        "baseline_cases_sha256": _sha256_file(args.baseline / "cases.jsonl"),
        "diagnostic_cases_sha256": _sha256_file(args.diagnostic / "cases.jsonl"),
    }
    artifacts.write_json(
        "run.json",
        {
            "schema_version": "milai-product03-opportunity-final-run-v1",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "status": "ANALYSIS_ONLY",
            "source_artifacts": sources,
            "product_lock_digest": baseline_terminal["product_lock_digest"],
            "selection_sha256": diagnostic_terminal["selection_sha256"],
            "product_calls": 0,
            "reader_calls": 0,
            "answer_calls": 0,
            "judge_calls": 0,
            "formal_holdout_consumed": False,
        },
    )
    metrics = {
        "schema_version": "milai-product03-opportunity-final-metrics-v1",
        "run_id": run_id,
        "comparison": comparison,
        "dense_only_disposition": "ORACLE_ONLY_NOT_PRODUCT_TREATMENT",
        "selected_treatment": selected,
        "selection_rule": "MAX_NEW_ROLE_GROUPS_THEN_MIN_CANDIDATES_AMONG_ALLOWED_ADDITIVE_T1",
        "product_calls": 0,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "formal_holdout_consumed": False,
    }
    artifacts.write_json("metrics.json", metrics)
    finished_at = datetime.now(UTC)
    terminal = {
        "schema_version": "milai-product03-opportunity-final-terminal-v1",
        "run_id": run_id,
        "status": (
            "PASS_PRODUCT03_T1_SELECTED"
            if selected is not None
            else "NO_SIMPLE_CHANNEL_OPPORTUNITY"
        ),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "product_lock_digest": baseline_terminal["product_lock_digest"],
        "selection_sha256": diagnostic_terminal["selection_sha256"],
        "metrics_sha256": _canonical_sha256(metrics),
        "selected_treatment": selected,
        "product_calls": 0,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "canonical_mutation_count": 0,
        "formal_holdout_consumed": False,
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 0 if selected is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
