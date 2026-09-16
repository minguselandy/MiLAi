#!/usr/bin/env python3
"""Create immutable source-only packets and a pre-execution Product-11 manifest."""

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
    ORCHESTRATION_SCHEMA,
    REVIEWER_ROLE,
    build_subagent_review_packet,
    validate_subagent_orchestration_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"
A0_TRACE = ROOT / "artifacts/product11/p11-x0-a0-20260904f/product-trace.redacted.jsonl"
ANNOTATOR_PACKET = ROOT / "data/labels/product11-subagent-annotator.packet.v0.1.json"
REVIEWER_PACKET = ROOT / "data/labels/product11-subagent-reviewer.packet.v0.1.json"


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


def _write_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"refusing to overwrite immutable subagent input: {path}")
        return
    path.write_text(text, encoding="utf-8")


def run(
    *,
    run_id: str,
    annotator_identity: str,
    reviewer_identity: str,
    annotator_invocation_id: str,
    reviewer_invocation_id: str,
    model_id: str,
) -> dict[str, Any]:
    fixture = _load_json(FIXTURE)
    validate_a0_trace_seal(_load_jsonl(A0_TRACE))
    fixture_sha = _sha256_file(FIXTURE)
    a0_trace_sha = _sha256_file(A0_TRACE)
    annotator_packet = build_subagent_review_packet(
        fixture,
        role=ANNOTATOR_ROLE,
        packet_id="P11-X0-SUBAGENT-ANNOTATOR-V01",
        fixture_file_sha256=fixture_sha,
    )
    reviewer_packet = build_subagent_review_packet(
        fixture,
        role=REVIEWER_ROLE,
        packet_id="P11-X0-SUBAGENT-REVIEWER-V01",
        fixture_file_sha256=fixture_sha,
    )
    _write_immutable(ANNOTATOR_PACKET, _json_text(annotator_packet))
    _write_immutable(REVIEWER_PACKET, _json_text(reviewer_packet))
    annotator_packet_sha = _sha256_file(ANNOTATOR_PACKET)
    reviewer_packet_sha = _sha256_file(REVIEWER_PACKET)
    output_dir = ROOT / f"var/product11/{run_id}"
    manifest = {
        "schema_version": ORCHESTRATION_SCHEMA,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "created_before_execution": True,
        "status": "SEALED_BEFORE_SUBAGENT_EXECUTION",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "source_fixture": str(FIXTURE.relative_to(ROOT)),
        "source_fixture_file_sha256": fixture_sha,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "a0_trace": str(A0_TRACE.relative_to(ROOT)),
        "a0_trace_sha256": a0_trace_sha,
        "producers": {
            "annotator": {
                "role": ANNOTATOR_ROLE,
                "orchestrator_assigned_agent_id": annotator_identity,
                "invocation_id": annotator_invocation_id,
                "model_id": model_id,
                "packet": str(ANNOTATOR_PACKET.relative_to(ROOT)),
                "packet_sha256": annotator_packet_sha,
                "expected_proposal": str(
                    (output_dir / "annotator-proposal.json").relative_to(ROOT)
                ),
            },
            "reviewer": {
                "role": REVIEWER_ROLE,
                "orchestrator_assigned_agent_id": reviewer_identity,
                "invocation_id": reviewer_invocation_id,
                "model_id": model_id,
                "packet": str(REVIEWER_PACKET.relative_to(ROOT)),
                "packet_sha256": reviewer_packet_sha,
                "expected_proposal": str(
                    (output_dir / "reviewer-proposal.json").relative_to(ROOT)
                ),
            },
        },
        "isolation": {
            "peer_output_supplied": False,
            "proposal_output_supplied": False,
            "a0_trace_supplied": False,
            "treatment_output_supplied": False,
        },
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }
    validate_subagent_orchestration_manifest(
        fixture,
        manifest,
        fixture_file_sha256=fixture_sha,
        a0_trace_sha256=a0_trace_sha,
        packet_sha256_by_role={
            ANNOTATOR_ROLE: annotator_packet_sha,
            REVIEWER_ROLE: reviewer_packet_sha,
        },
    )
    manifest_path = output_dir / "subagent-orchestration-manifest.json"
    if manifest_path.exists():
        raise RuntimeError(f"refusing to reuse a subagent run manifest: {manifest_path}")
    _write_immutable(manifest_path, _json_text(manifest))
    return {
        **manifest,
        "orchestration_manifest": str(manifest_path.relative_to(ROOT)),
        "orchestration_manifest_sha256": _sha256_file(manifest_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--annotator-identity", required=True)
    parser.add_argument("--reviewer-identity", required=True)
    parser.add_argument("--annotator-invocation-id", required=True)
    parser.add_argument("--reviewer-invocation-id", required=True)
    parser.add_argument("--model-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
