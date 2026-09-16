#!/usr/bin/env python3
"""Seal Product-11 labels only after two independent human attestations."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11 import (
    canonical_sha256,
    validate_a0_trace_seal,
    validate_human_seal,
    validate_x0_opportunity_assignments,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"
OUTPUT = ROOT / "data/labels/product11-human-instance-groups.jsonl"
DEFAULT_A0_TRACE = (
    ROOT / "artifacts/product11/p11-x0-a0-20260904f/product-trace.redacted.jsonl"
)


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


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite sealed output: {path}")
    path.write_text(text, encoding="utf-8")


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run(*, adjudicated: Path, a0_trace: Path, run_id: str) -> dict[str, Any]:
    if "formal" in adjudicated.name.casefold() or "longmemeval" in adjudicated.name.casefold():
        raise ValueError("Product-11 X0 refuses Formal/LongMemEval-named adjudication inputs")
    fixture = _load_json(FIXTURE)
    rows = _load_jsonl(adjudicated)
    trace_rows = _load_jsonl(a0_trace)
    validate_a0_trace_seal(trace_rows)
    summary = validate_human_seal(fixture, rows, require_opportunity_gate=False)
    opportunity = validate_x0_opportunity_assignments(fixture, rows, trace_rows)
    gate_passed = (
        opportunity["continuation_opportunity_count"] >= 8
        and opportunity["intra_source_opportunity_count"] >= 8
        and opportunity["control_or_already_complete_count"] >= 8
    )
    final_status = (
        "PASS_PRODUCT11_X0_HUMAN_SEAL"
        if gate_passed
        else "PARKED_PRODUCT11_INSUFFICIENT_HUMAN_SEALED_OPPORTUNITY"
    )
    header = rows[0]
    if header.get("source_fixture_file_sha256") != _sha256_file(FIXTURE):
        raise ValueError("human seal source fixture file digest does not match")
    if header.get("source_fixture_semantic_sha256") != canonical_sha256(fixture):
        raise ValueError("human seal source fixture semantic digest does not match")
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    timestamped = OUTPUT.with_name(f"{OUTPUT.stem}_{timestamp}{OUTPUT.suffix}")
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    _write_new(timestamped, text)
    if OUTPUT.exists():
        raise RuntimeError(
            "stable human label output already exists; archive/review before replacement"
        )
    OUTPUT.write_text(text, encoding="utf-8")
    receipt = {
        "schema_version": "milai-product11-x0-seal-receipt-v0.1",
        "run_id": run_id,
        "sealed_at": datetime.now(UTC).isoformat(),
        "source_fixture": str(FIXTURE.relative_to(ROOT)),
        "source_fixture_file_sha256": _sha256_file(FIXTURE),
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "adjudication_input": str(adjudicated.resolve()),
        "adjudication_input_sha256": _sha256_file(adjudicated),
        "a0_trace": str(a0_trace.resolve()),
        "a0_trace_sha256": _sha256_file(a0_trace),
        "timestamped_output": str(timestamped.relative_to(ROOT)),
        "stable_output": str(OUTPUT.relative_to(ROOT)),
        "human_label_sha256": _sha256_file(OUTPUT),
        **summary,
        **opportunity,
        "opportunity_gate_passed": gate_passed,
        "status": final_status,
    }
    receipt_path = ROOT / f"var/product11/{run_id}/x0-seal-receipt.json"
    _write_new(receipt_path, _json_text(receipt))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adjudicated", type=Path, required=True)
    parser.add_argument("--a0-trace", type=Path, default=DEFAULT_A0_TRACE)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            run(adjudicated=args.adjudicated, a0_trace=args.a0_trace, run_id=args.run_id),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
