#!/usr/bin/env python3
"""Prepare proposal-free Product-11 independent-human review inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11 import validate_a0_trace_seal
from milai_lab.product11_human import build_source_review_view, build_submission_rows

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"
A0_TRACE = ROOT / "artifacts/product11/p11-x0-a0-20260904f/product-trace.redacted.jsonl"
ANNOTATOR_TEMPLATE = (
    ROOT / "data/labels/product11-annotator.submission-template.v0.1.jsonl"
)
REVIEWER_TEMPLATE = (
    ROOT / "data/labels/product11-reviewer.submission-template.v0.1.jsonl"
)
SOURCE_VIEW = ROOT / "data/labels/product11-source-review-view.v0.1.json"


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


def _write_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"refusing to overwrite immutable human-workflow input: {path}")
        return
    path.write_text(text, encoding="utf-8")


def run(*, run_id: str) -> dict[str, Any]:
    fixture = _load_json(FIXTURE)
    trace_rows = _load_jsonl(A0_TRACE)
    trace_summary = validate_a0_trace_seal(trace_rows)
    fixture_sha = _sha256_file(FIXTURE)
    trace_sha = _sha256_file(A0_TRACE)
    annotator_rows = build_submission_rows(
        fixture,
        role="ANNOTATOR",
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=trace_sha,
    )
    reviewer_rows = build_submission_rows(
        fixture,
        role="INDEPENDENT_REVIEWER",
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=trace_sha,
    )
    source_view = build_source_review_view(
        fixture,
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=trace_sha,
        authoritative_packets=(
            "data/labels/product11-annotator.packet.v0.7.json",
            "data/labels/product11-reviewer.packet.v0.7.json",
        ),
    )
    _write_immutable(ANNOTATOR_TEMPLATE, _jsonl_text(annotator_rows))
    _write_immutable(REVIEWER_TEMPLATE, _jsonl_text(reviewer_rows))
    _write_immutable(SOURCE_VIEW, _json_text(source_view))
    summary = {
        "schema_version": "milai-product11-human-workflow-preparation-v0.1",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "AWAITING_TWO_INDEPENDENT_HUMAN_SUBMISSIONS",
        "source_fixture": str(FIXTURE.relative_to(ROOT)),
        "source_fixture_file_sha256": fixture_sha,
        "a0_trace": str(A0_TRACE.relative_to(ROOT)),
        "a0_trace_sha256": trace_sha,
        "a0_trace_seal": trace_summary,
        "annotator_template": str(ANNOTATOR_TEMPLATE.relative_to(ROOT)),
        "annotator_template_sha256": _sha256_file(ANNOTATOR_TEMPLATE),
        "reviewer_template": str(REVIEWER_TEMPLATE.relative_to(ROOT)),
        "reviewer_template_sha256": _sha256_file(REVIEWER_TEMPLATE),
        "source_review_view": str(SOURCE_VIEW.relative_to(ROOT)),
        "source_review_view_sha256": _sha256_file(SOURCE_VIEW),
        "human_complete_count": 0,
        "required_independent_humans": 2,
        "model_proposal_in_submission_templates": False,
        "product_output_in_source_review_view": False,
        "opportunity_fields_entered_by_humans": False,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }
    summary_path = ROOT / f"var/product11/{run_id}/summary.json"
    _write_immutable(summary_path, _json_text(summary))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(run(run_id=args.run_id), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
