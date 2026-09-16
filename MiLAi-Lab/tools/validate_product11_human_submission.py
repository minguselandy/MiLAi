#!/usr/bin/env python3
"""Validate one Product-11 human submission without reading the other role."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from milai_lab.product11_human import (
    ANNOTATOR_ROLE,
    REVIEWER_ROLE,
    validate_independent_submission,
)

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


def run(*, submission: Path, role: str) -> dict[str, Any]:
    lowered = submission.name.casefold()
    if "formal" in lowered or "longmemeval" in lowered:
        raise ValueError("Product-11 human validation refuses Formal/LongMemEval-named inputs")
    return validate_independent_submission(
        _load_json(FIXTURE),
        _load_jsonl(submission),
        expected_role=role,
        fixture_file_sha256=_sha256_file(FIXTURE),
        a0_trace_sha256=_sha256_file(A0_TRACE),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--role", choices=(ANNOTATOR_ROLE, REVIEWER_ROLE), required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            run(submission=args.submission, role=args.role),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
