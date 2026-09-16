#!/usr/bin/env python3
"""Merge Product-11 proposals through an immutable pre-execution manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11_subagent import (
    ANNOTATOR_ROLE,
    REVIEWER_ROLE,
    merge_independent_subagent_proposals,
    validate_subagent_orchestration_manifest,
    validate_subagent_review_packet,
)

ROOT = Path(__file__).resolve().parents[1]


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
        raise RuntimeError(f"refusing to overwrite Product-11 subagent output: {path}")
    path.write_text(text, encoding="utf-8")


def _resolve_manifest_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Product-11 subagent manifest {label} path is invalid")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Product-11 subagent manifest {label} escapes repository")
    lowered = path.name.casefold()
    if "formal" in lowered or "longmemeval" in lowered:
        raise ValueError("Product-11 subagent merge refuses Formal-named inputs")
    return path


def _envelope(
    *,
    producer: dict[str, Any],
    isolation: dict[str, Any],
    output_sha256: str,
) -> dict[str, Any]:
    return {
        "kind": "SUBAGENT",
        "orchestrator_assigned_agent_id": producer[
            "orchestrator_assigned_agent_id"
        ],
        "invocation_id": producer["invocation_id"],
        "model_id": producer["model_id"],
        "role": producer["role"],
        "input_bundle_sha256": producer["packet_sha256"],
        "output_sha256": output_sha256,
        "peer_output_supplied": isolation["peer_output_supplied"],
        "proposal_output_supplied": isolation["proposal_output_supplied"],
        "a0_trace_supplied": isolation["a0_trace_supplied"],
        "treatment_output_supplied": isolation["treatment_output_supplied"],
    }


def run(*, orchestration_manifest: Path) -> dict[str, Any]:
    manifest = _load_json(orchestration_manifest)
    fixture_path = _resolve_manifest_path(
        manifest.get("source_fixture"), label="source fixture"
    )
    trace_path = _resolve_manifest_path(manifest.get("a0_trace"), label="A0 trace")
    producers = manifest.get("producers")
    if not isinstance(producers, dict):
        raise ValueError("Product-11 subagent manifest producer map is invalid")
    annotator_assignment = producers.get("annotator")
    reviewer_assignment = producers.get("reviewer")
    if not isinstance(annotator_assignment, dict) or not isinstance(
        reviewer_assignment, dict
    ):
        raise ValueError("Product-11 subagent manifest producer assignments are invalid")
    annotator_packet_path = _resolve_manifest_path(
        annotator_assignment.get("packet"), label="annotator packet"
    )
    reviewer_packet_path = _resolve_manifest_path(
        reviewer_assignment.get("packet"), label="reviewer packet"
    )
    annotator_path = _resolve_manifest_path(
        annotator_assignment.get("expected_proposal"), label="annotator proposal"
    )
    reviewer_path = _resolve_manifest_path(
        reviewer_assignment.get("expected_proposal"), label="reviewer proposal"
    )
    fixture = _load_json(fixture_path)
    fixture_sha = _sha256_file(fixture_path)
    trace_sha = _sha256_file(trace_path)
    annotator_packet_sha = _sha256_file(annotator_packet_path)
    reviewer_packet_sha = _sha256_file(reviewer_packet_path)
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
    annotator_sha = _sha256_file(annotator_path)
    reviewer_sha = _sha256_file(reviewer_path)
    manifest_sha = _sha256_file(orchestration_manifest)
    isolation = manifest_validation["isolation"]
    result = merge_independent_subagent_proposals(
        fixture,
        _load_jsonl(trace_path),
        _load_json(annotator_path),
        _load_json(reviewer_path),
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=trace_sha,
        annotator_packet_sha256=annotator_packet_sha,
        reviewer_packet_sha256=reviewer_packet_sha,
        annotator_proposal_sha256=annotator_sha,
        reviewer_proposal_sha256=reviewer_sha,
        orchestration_manifest_sha256=manifest_sha,
        annotator_envelope=_envelope(
            producer=manifest_validation["producers"]["annotator"],
            isolation=isolation,
            output_sha256=annotator_sha,
        ),
        reviewer_envelope=_envelope(
            producer=manifest_validation["producers"]["reviewer"],
            isolation=isolation,
            output_sha256=reviewer_sha,
        ),
    )
    adjudicated_rows = result.pop("adjudicated_rows")
    run_id = str(manifest["run_id"])
    output_dir = ROOT / f"var/product11/{run_id}"
    summary = {
        **result,
        "run_id": run_id,
        "merged_at": datetime.now(UTC).isoformat(),
        "orchestration_manifest": str(orchestration_manifest.resolve().relative_to(ROOT)),
        "orchestration_manifest_sha256": manifest_sha,
        "annotator_packet": str(annotator_packet_path.relative_to(ROOT)),
        "annotator_packet_sha256": annotator_packet_sha,
        "reviewer_packet": str(reviewer_packet_path.relative_to(ROOT)),
        "reviewer_packet_sha256": reviewer_packet_sha,
        "annotator_proposal": str(annotator_path.relative_to(ROOT)),
        "annotator_proposal_sha256": annotator_sha,
        "reviewer_proposal": str(reviewer_path.relative_to(ROOT)),
        "reviewer_proposal_sha256": reviewer_sha,
    }
    if adjudicated_rows is not None:
        output = output_dir / "subagent-adjudicated.jsonl"
        _write_new(output, _jsonl_text(adjudicated_rows))
        summary["adjudicated_output"] = str(output.relative_to(ROOT))
        summary["adjudicated_output_sha256"] = _sha256_file(output)
    else:
        conflict = output_dir / "subagent-conflicts.json"
        _write_new(conflict, _json_text({"conflicts": summary["conflicts"]}))
        summary["conflict_report"] = str(conflict.relative_to(ROOT))
        summary["adjudicated_output"] = None
    _write_new(output_dir / "subagent-merge-summary.json", _json_text(summary))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orchestration-manifest", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
