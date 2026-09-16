#!/usr/bin/env python3
"""Rescore one sealed A6 label-free archive without any model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg17.a6_dense_productization import (
    A6DenseError,
    build_a6_receipt,
    score_a6_archive,
)
from evals.dg17.measurement import load_answer_bearing_labels

DEFAULT_SOURCE = (
    ROOT / "var/dg17/a6/dg17-a6-productization-20260827-001"
)
DEFAULT_ARCHIVE_SHA256 = (
    "364cf3caa981dc9e9a7148e8cac806241e1123544134d2220895f0d8fb8deb07"
)
DEFAULT_EXECUTION_PLAN_SHA256 = (
    "7300050fb7f145d060f4ee5240e82b45902d2cc832df20c468524259018a07ab"
)
DEFAULT_GOAL = ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md"
DEFAULT_POSTGRES = (
    ROOT
    / "var/dg17/a6/dg17-a6-evidence-dense-20260827-004/focused-postgres-001.json"
)
DEFAULT_Q8 = (
    ROOT / "var/dg17/q8/dg17-q8-retrieval-ablation-20260827-002/receipt.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--archive-sha256", default=DEFAULT_ARCHIVE_SHA256)
    parser.add_argument(
        "--execution-plan-sha256", default=DEFAULT_EXECUTION_PLAN_SHA256
    )
    parser.add_argument("--goal", type=Path, default=DEFAULT_GOAL)
    parser.add_argument("--focused-postgres-receipt", type=Path, default=DEFAULT_POSTGRES)
    parser.add_argument("--q8-receipt", type=Path, default=DEFAULT_Q8)
    args = parser.parse_args()

    if args.output_root.exists():
        raise A6DenseError("A6 rescore output exists; choose a fresh run ID")
    args.output_root.mkdir(parents=True)
    archive_path = args.source_root / "label-free-acquisition.json"
    execution_plan_path = args.source_root / "execution-plan.json"
    _assert_sha(archive_path, args.archive_sha256)
    _assert_sha(execution_plan_path, args.execution_plan_sha256)
    archive = _load_object(archive_path)
    if archive.get("labels_loaded") is not False:
        raise A6DenseError("A6 source archive is not label-free")
    rescore_plan = {
        "schema": "milai.dg17.a6-rescore-plan.v0.1",
        "run_id": args.run_id,
        "status": "SEALED_BEFORE_LABEL_LOAD",
        "reason": "CORRECT_AGGREGATE_GATE_ATTRIBUTION_ONLY",
        "model_calls": 0,
        "embedding_calls": 0,
        "reader_calls": 0,
        "reranker_calls": 0,
        "automatic_retries": 0,
        "source_archive": _identity(archive_path),
        "source_execution_plan": _identity(execution_plan_path),
    }
    plan_path = args.output_root / "rescore-plan.json"
    _atomic_json(plan_path, rescore_plan)

    _envelope, labeled_cases, labels = load_answer_bearing_labels()
    archive_case_ids = tuple(
        dict.fromkeys(str(row["case_id"]) for row in archive["records"])
    )
    if tuple(str(case.case_id) for case in labeled_cases) != archive_case_ids:
        raise A6DenseError("A6 rescore case order drifted")
    score = score_a6_archive(archive, labels=labels)
    score_path = args.output_root / "score.json"
    _atomic_json(score_path, score)
    receipt = build_a6_receipt(
        run_id=args.run_id,
        archive_path=archive_path,
        execution_plan_path=execution_plan_path,
        goal_path=args.goal,
        focused_postgres_receipt=args.focused_postgres_receipt,
        q8_receipt=args.q8_receipt,
        score=score,
        archive=archive,
    )
    receipt["bound_artifacts"]["rescore_plan"] = _identity(plan_path)
    receipt["bound_artifacts"]["score"] = _identity(score_path)
    receipt["supersession"] = {
        "source_receipt": _identity(args.source_root / "receipt.json"),
        "scope": "DECISION_GATE_ATTRIBUTION_ONLY",
        "source_label_free_archive_changed": False,
        "source_execution_plan_changed": False,
        "new_model_calls": 0,
        "new_embedding_calls": 0,
        "new_reader_calls": 0,
        "new_reranker_calls": 0,
        "automatic_retries": 0,
    }
    receipt_path = args.output_root / "receipt.json"
    _atomic_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": _sha256(receipt_path),
                "delta": score["delta"],
                "disposition": receipt["disposition"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise A6DenseError(f"A6 JSON artifact is not an object: {path}")
    return value


def _assert_sha(path: Path, expected: str) -> None:
    if _sha256(path) != expected:
        raise A6DenseError(f"A6 rescore source identity drifted: {path}")


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
