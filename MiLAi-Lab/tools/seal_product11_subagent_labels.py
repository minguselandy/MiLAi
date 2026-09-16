#!/usr/bin/env python3
"""Seal Product-11 labels only from a verified immutable subagent merge chain."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11 import canonical_sha256, validate_a0_trace_seal
from milai_lab.product11_subagent import (
    ANNOTATOR_ROLE,
    REVIEWER_ROLE,
    validate_subagent_merge_chain,
    validate_subagent_orchestration_manifest,
    validate_subagent_proposal,
    validate_subagent_review_packet,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/labels/product11-subagent-instance-groups-v0.2.jsonl"


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
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
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
        raise RuntimeError(f"refusing to overwrite sealed subagent output: {path}")
    path.write_text(text, encoding="utf-8")


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _resolve_repository_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Product-11 subagent {label} path is invalid")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Product-11 subagent {label} escapes repository")
    lowered = path.name.casefold()
    if "formal" in lowered or "longmemeval" in lowered:
        raise ValueError("Product-11 subagent seal refuses Formal-named inputs")
    return path


def _expect_summary_path(summary: dict[str, Any], key: str, expected: Path) -> None:
    actual = _resolve_repository_path(summary.get(key), label=key)
    if actual != expected.resolve():
        raise ValueError(f"Product-11 subagent merge summary {key} path drifted")


def run(
    *,
    merge_summary: Path,
    run_id: str,
    supersedes_receipt: Path | None = None,
) -> dict[str, Any]:
    merge_summary = merge_summary.resolve()
    if not merge_summary.is_relative_to(ROOT):
        raise ValueError("Product-11 subagent merge summary escapes repository")
    summary = _load_json(merge_summary)
    manifest_path = _resolve_repository_path(
        summary.get("orchestration_manifest"), label="orchestration manifest"
    )
    manifest = _load_json(manifest_path)
    fixture_path = _resolve_repository_path(
        manifest.get("source_fixture"), label="source fixture"
    )
    trace_path = _resolve_repository_path(manifest.get("a0_trace"), label="A0 trace")
    producers = manifest.get("producers")
    if not isinstance(producers, dict):
        raise ValueError("Product-11 subagent manifest producer map is invalid")
    annotator_assignment = producers.get("annotator")
    reviewer_assignment = producers.get("reviewer")
    if not isinstance(annotator_assignment, dict) or not isinstance(
        reviewer_assignment, dict
    ):
        raise ValueError("Product-11 subagent manifest producer assignments are invalid")
    annotator_packet_path = _resolve_repository_path(
        annotator_assignment.get("packet"), label="annotator packet"
    )
    reviewer_packet_path = _resolve_repository_path(
        reviewer_assignment.get("packet"), label="reviewer packet"
    )
    annotator_proposal_path = _resolve_repository_path(
        annotator_assignment.get("expected_proposal"), label="annotator proposal"
    )
    reviewer_proposal_path = _resolve_repository_path(
        reviewer_assignment.get("expected_proposal"), label="reviewer proposal"
    )
    adjudicated_path = _resolve_repository_path(
        summary.get("adjudicated_output"), label="adjudicated output"
    )
    _expect_summary_path(summary, "annotator_packet", annotator_packet_path)
    _expect_summary_path(summary, "reviewer_packet", reviewer_packet_path)
    _expect_summary_path(summary, "annotator_proposal", annotator_proposal_path)
    _expect_summary_path(summary, "reviewer_proposal", reviewer_proposal_path)

    fixture = _load_json(fixture_path)
    rows = _load_jsonl(adjudicated_path)
    trace_rows = _load_jsonl(trace_path)
    validate_a0_trace_seal(trace_rows)
    fixture_sha = _sha256_file(fixture_path)
    trace_sha = _sha256_file(trace_path)
    manifest_sha = _sha256_file(manifest_path)
    annotator_packet_sha = _sha256_file(annotator_packet_path)
    reviewer_packet_sha = _sha256_file(reviewer_packet_path)
    annotator_proposal_sha = _sha256_file(annotator_proposal_path)
    reviewer_proposal_sha = _sha256_file(reviewer_proposal_path)
    adjudicated_sha = _sha256_file(adjudicated_path)
    manifest_validation = validate_subagent_orchestration_manifest(
        fixture,
        manifest,
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=trace_sha,
        packet_sha256_by_role={
            ANNOTATOR_ROLE: annotator_packet_sha,
            REVIEWER_ROLE: reviewer_packet_sha,
        },
    )
    validate_subagent_review_packet(
        fixture,
        _load_json(annotator_packet_path),
        expected_role=ANNOTATOR_ROLE,
        expected_fixture_file_sha256=fixture_sha,
    )
    validate_subagent_review_packet(
        fixture,
        _load_json(reviewer_packet_path),
        expected_role=REVIEWER_ROLE,
        expected_fixture_file_sha256=fixture_sha,
    )
    annotator_proposal = _load_json(annotator_proposal_path)
    reviewer_proposal = _load_json(reviewer_proposal_path)
    validate_subagent_proposal(
        fixture,
        annotator_proposal,
        expected_role=ANNOTATOR_ROLE,
        expected_identity=manifest_validation["producers"]["annotator"][
            "orchestrator_assigned_agent_id"
        ],
        expected_packet_sha256=annotator_packet_sha,
    )
    validate_subagent_proposal(
        fixture,
        reviewer_proposal,
        expected_role=REVIEWER_ROLE,
        expected_identity=manifest_validation["producers"]["reviewer"][
            "orchestrator_assigned_agent_id"
        ],
        expected_packet_sha256=reviewer_packet_sha,
    )
    chain = validate_subagent_merge_chain(
        fixture,
        rows,
        trace_rows,
        summary,
        annotator_proposal,
        reviewer_proposal,
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=trace_sha,
        adjudicated_sha256=adjudicated_sha,
        orchestration_manifest_sha256=manifest_sha,
        annotator_packet_sha256=annotator_packet_sha,
        reviewer_packet_sha256=reviewer_packet_sha,
        annotator_proposal_sha256=annotator_proposal_sha,
        reviewer_proposal_sha256=reviewer_proposal_sha,
    )
    gate_passed = bool(chain["opportunity_gate_passed"])
    final_status = (
        "PASS_PRODUCT11_X0_SUBAGENT_SEAL"
        if gate_passed
        else "PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY"
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    timestamped = OUTPUT.with_name(f"{OUTPUT.stem}_{timestamp}{OUTPUT.suffix}")
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    _write_new(timestamped, text)
    _write_new(OUTPUT, text)
    receipt = {
        "schema_version": "milai-product11-x0-subagent-seal-receipt-v0.2",
        "run_id": run_id,
        "sealed_at": datetime.now(UTC).isoformat(),
        "seal_mode": "SUBAGENT_SEALED_VERIFIED_CHAIN",
        "label_provenance": "SUBAGENT_SEALED",
        "human_adjudication_status": "NOT_PERFORMED",
        "model_generated_judgment": True,
        "claim_ceiling": "OPENED_DEVELOPMENT_MODEL_ADJUDICATED",
        "source_fixture": str(fixture_path.relative_to(ROOT)),
        "source_fixture_file_sha256": fixture_sha,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "a0_trace": str(trace_path.relative_to(ROOT)),
        "a0_trace_sha256": trace_sha,
        "orchestration_manifest": str(manifest_path.relative_to(ROOT)),
        "orchestration_manifest_sha256": manifest_sha,
        "merge_summary": str(merge_summary.relative_to(ROOT)),
        "merge_summary_sha256": _sha256_file(merge_summary),
        "adjudication_input": str(adjudicated_path.relative_to(ROOT)),
        "adjudication_input_sha256": adjudicated_sha,
        "timestamped_output": str(timestamped.relative_to(ROOT)),
        "stable_output": str(OUTPUT.relative_to(ROOT)),
        "subagent_label_sha256": _sha256_file(OUTPUT),
        "artifact_chain_verified": True,
        "chain_validation": chain,
        "continuation_opportunity_count": summary[
            "continuation_opportunity_count"
        ],
        "intra_source_opportunity_count": summary[
            "intra_source_opportunity_count"
        ],
        "control_or_already_complete_count": summary[
            "control_or_already_complete_count"
        ],
        "opportunity_gate_passed": gate_passed,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "status": final_status,
    }
    if supersedes_receipt is not None:
        supersedes_receipt = supersedes_receipt.resolve()
        if not supersedes_receipt.is_relative_to(ROOT) or not supersedes_receipt.is_file():
            raise ValueError("Product-11 superseded receipt is invalid")
        receipt["supersedes_receipt"] = str(supersedes_receipt.relative_to(ROOT))
        receipt["supersedes_receipt_sha256"] = _sha256_file(supersedes_receipt)
    receipt_path = ROOT / f"var/product11/{run_id}/x0-subagent-seal-receipt.json"
    _write_new(receipt_path, _json_text(receipt))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merge-summary", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--supersedes-receipt", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
