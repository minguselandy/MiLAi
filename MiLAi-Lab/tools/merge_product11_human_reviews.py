#!/usr/bin/env python3
"""Merge two complete independent Product-11 human submissions or report conflicts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11_human import merge_independent_submissions

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"
A0_TRACE = ROOT / "artifacts/product11/p11-x0-a0-20260904f/product-trace.redacted.jsonl"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected object at {path}:{line_number}")
        rows.append(value)
    return rows


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _jsonl_text(rows: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite Product-11 human merge output: {path}")
    path.write_text(text, encoding="utf-8")


def run(*, annotator: Path, reviewer: Path, run_id: str) -> dict[str, Any]:
    for path in (annotator, reviewer):
        lowered = path.name.casefold()
        if "formal" in lowered or "longmemeval" in lowered:
            raise ValueError("Product-11 human merge refuses Formal/LongMemEval-named inputs")
    fixture = _load_json(FIXTURE)
    trace_rows = _load_jsonl(A0_TRACE)
    result = merge_independent_submissions(
        fixture,
        trace_rows,
        _load_jsonl(annotator),
        _load_jsonl(reviewer),
        fixture_file_sha256=_sha256_file(FIXTURE),
        a0_trace_sha256=_sha256_file(A0_TRACE),
    )
    adjudicated_rows = result.pop("adjudicated_rows")
    output_dir = ROOT / f"var/product11/{run_id}"
    summary = {
        **result,
        "run_id": run_id,
        "merged_at": datetime.now(UTC).isoformat(),
        "annotator_submission": str(annotator.resolve()),
        "annotator_submission_sha256": _sha256_file(annotator),
        "reviewer_submission": str(reviewer.resolve()),
        "reviewer_submission_sha256": _sha256_file(reviewer),
    }
    if adjudicated_rows is not None:
        adjudicated_path = output_dir / "adjudicated.jsonl"
        _write_new(adjudicated_path, _jsonl_text(adjudicated_rows))
        summary["adjudicated_output"] = str(adjudicated_path.relative_to(ROOT))
        summary["adjudicated_output_sha256"] = _sha256_file(adjudicated_path)
    else:
        conflict_path = output_dir / "conflicts.json"
        _write_new(conflict_path, _json_text({"conflicts": summary["conflicts"]}))
        summary["conflict_report"] = str(conflict_path.relative_to(ROOT))
        summary["adjudicated_output"] = None
    _write_new(output_dir / "summary.json", _json_text(summary))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotator", type=Path, required=True)
    parser.add_argument("--reviewer", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            run(annotator=args.annotator, reviewer=args.reviewer, run_id=args.run_id),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
