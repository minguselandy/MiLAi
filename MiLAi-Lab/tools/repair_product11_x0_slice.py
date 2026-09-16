#!/usr/bin/env python3
"""Create the treatment-blind Product-11 X0 slice repair from the first A0 trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import prepare_product11_x0 as prep
from milai_lab.product11 import canonical_sha256, validate_source_fixture

ROOT = Path(__file__).resolve().parents[1]
SUPERSEDED_TRACE = ROOT / "artifacts/product11/p11-x0-a0-20260904e/product-trace.redacted.jsonl"
FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"
MANIFEST = ROOT / "data/manifests/product11-opened-dev24.v0.7.json"
CANDIDATE = ROOT / "data/labels/product11-instance-groups.candidate.v0.7.jsonl"
ADJUDICATION = ROOT / "data/labels/product11-human-adjudication.template.v0.7.jsonl"
ANNOTATOR = ROOT / "data/labels/product11-annotator.packet.v0.7.json"
REVIEWER = ROOT / "data/labels/product11-reviewer.packet.v0.7.json"

_CONTINUATION_CATEGORY = {
    "p11-c01": "clothing items",
    "p11-c02": "supplements",
    "p11-c03": "cities",
    "p11-c04": "appointments",
    "p11-c05": "gifts",
    "p11-c06": "novels",
    "p11-c07": "responsibilities",
    "p11-c08": "restaurants",
}

_INTRA_SOURCE_TURNS: dict[str, list[list[str]]] = {
    "p11-c09": [[
        "The power tools I purchased included a cordless drill.",
        "The receipt was emailed.",
        "The next one was a circular saw.",
        "I compared safety glasses.",
        "The final one was an orbital sander.",
    ]],
    "p11-c10": [[
        "The pantry staples I restocked included rice.",
        "The rice went on the bottom shelf.",
        "I cleaned the jars.",
        "Lentils came next.",
        "I wrote a note for later.",
        "Olive oil was the final one.",
    ]],
    "p11-c11": [[
        "The courses I enrolled in included statistics.",
        "Classes begin Monday.",
        "Ceramics was the next one.",
        "I bought notebooks.",
        "Spanish conversation completed my schedule.",
    ]],
    "p11-c12": [[
        "The plants I added to the balcony included basil.",
        "It needs morning sun.",
        "Rosemary came next.",
        "I changed the watering can.",
        "A dwarf lemon tree was the final one.",
    ]],
    "p11-c13": [[
        "The apartment repairs I completed included fixing the leaking kitchen tap.",
        "The plumber visit was cancelled.",
        "Next was replacement of the hallway light switch.",
        "I measured the bedroom wall.",
        "The balcony latch was the final fix.",
    ]],
    "p11-c14": [[
        "The workouts I completed this week included a five-kilometre run.",
        "The run felt easier than last week.",
        "I washed my shoes.",
        "Next was a yoga class.",
        "I made dinner.",
        "A swim session was the final one.",
    ]],
    "p11-c15": [[
        "The subscriptions I renewed included the city newspaper.",
        "The old music trial expired.",
        "The cloud backup plan was next.",
        "I changed my password.",
        "The museum membership was the final one.",
    ]],
    "p11-c16": [[
        "The art supplies I bought included watercolour paper.",
        "The shop was crowded.",
        "A sable brush came next.",
        "I checked a frame size.",
        "Masking fluid was the final one.",
    ]],
}

_CONTROL_PREFIX = {
    "p11-c17": "bicycle purchased",
    "p11-c18": "document renewed",
    "p11-c19": "phone currently using",
    "p11-c20": "mugs bought",
    "p11-c21": "appointment mentioned twice",
    "p11-c22": "pet adopted",
    "p11-c23": "travel bookings confirmed",
    "p11-c24": "shoes packed",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _jsonl_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _write_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"refusing to overwrite immutable output: {path}")
        return
    path.write_text(text, encoding="utf-8")


def _verify_superseded_a0() -> dict[str, int]:
    rows = [
        json.loads(line)
        for line in SUPERSEDED_TRACE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 24 or any(row.get("status") != "TRACE_COMPLETE" for row in rows):
        raise ValueError("superseded A0 trace is not a complete 24-case trace")
    return {
        "case_count": len(rows),
        "empty_candidate_case_count": sum(
            int(row.get("counts", {}).get("scanned_occurrences", 0)) == 0 for row in rows
        ),
        "candidate_occurrence_count": sum(
            int(row.get("counts", {}).get("scanned_occurrences", 0)) for row in rows
        ),
    }


def _continuation_distractors(question: str, category: str) -> list[list[str]]:
    padding = " ".join(["neutralcontext"] * 250)
    return [
        [
            (
                f"Index-only distractor {session_index:02d}-{turn_index:02d} for "
                f"{category}; query wording {question}; {padding}"
            )
            for turn_index in range(3)
        ]
        for session_index in range(6)
    ]


def _repaired_specs() -> list[dict[str, Any]]:
    specs = deepcopy(prep._specs())
    for spec in specs:
        case_id = str(spec["case_id"])
        stratum = str(spec["intended_stratum"])
        turns = spec["session_turns"]
        assert isinstance(turns, list)
        if stratum == "CONTINUATION":
            category = _CONTINUATION_CATEGORY[case_id]
            required = {
                (int(session_index), int(turn_index))
                for group in spec["group_members"]
                for session_index, turn_index in group
            }
            for session_index, session in enumerate(turns):
                assert isinstance(session, list)
                for turn_index, text in enumerate(session):
                    if (session_index, turn_index) in required:
                        session[turn_index] = f"Retrieval category {category}. {text}"
            turns.extend(_continuation_distractors(str(spec["question"]), category))
        elif stratum == "INTRA_SOURCE":
            spec["session_turns"] = deepcopy(_INTRA_SOURCE_TURNS[case_id])
        else:
            required = {
                (int(session_index), int(turn_index))
                for group in spec["group_members"]
                for session_index, turn_index in group
            }
            prefix = _CONTROL_PREFIX[case_id]
            for session_index, session in enumerate(turns):
                assert isinstance(session, list)
                for turn_index, text in enumerate(session):
                    if (session_index, turn_index) in required:
                        session[turn_index] = f"Category {prefix}. {text}"
    return specs


def run(run_id: str) -> dict[str, Any]:
    superseded_summary = _verify_superseded_a0()
    materialized = [prep._materialize(spec) for spec in _repaired_specs()]
    cases = [case for case, _ in materialized]
    proposals = [proposal for _, proposal in materialized]
    fixture = {
        "schema_version": "milai-product11-opened-dev-v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "created_for": "MILA-PRODUCT-11-X0-A0-INFORMED-REPAIR-V5-FINAL",
        "selection_basis": "source structure plus treatment-blind frozen A0 trace only",
        "supersedes_fixture": "product11-opened-dev24.v0.5.json",
        "case_ids": [case["case_id"] for case in cases],
        "cases": cases,
    }
    fixture_summary = validate_source_fixture(fixture)
    fixture_text = _json_text(fixture)
    fixture_file_sha256 = hashlib.sha256(fixture_text.encode()).hexdigest()
    fixture_semantic_sha256 = canonical_sha256(fixture)
    _write_immutable(FIXTURE, fixture_text)

    manifest = {
        "schema_version": "milai-product11-dataset-manifest-v0.7",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "selection_basis": "TREATMENT_BLIND_A0",
        "superseded_a0_trace_sha256": _sha256_file(SUPERSEDED_TRACE),
        "files": {FIXTURE.name: fixture_file_sha256},
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "case_count": 24,
        "case_order_sha256": fixture_summary["case_order_sha256"],
    }
    manifest_text = _json_text(manifest)
    _write_immutable(MANIFEST, manifest_text)

    proposal_header = {
        "record_type": "manifest",
        "schema_version": "milai-product11-instance-group-candidate-v0.7",
        "classification": "MODEL_ASSISTED_PROPOSAL_ONLY",
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "case_count": 24,
        "model_assisted_proxy": True,
        "human_adjudication_status": "PENDING",
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }
    proposal_text = _jsonl_text([proposal_header, *proposals])
    _write_immutable(CANDIDATE, proposal_text)

    adjudication_header = {
        "record_type": "manifest",
        "schema_version": "milai-product11-human-instance-groups-v0.1",
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "case_count": 24,
        "human_adjudication_status": "PENDING",
        "model_assisted_proxy": True,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }
    adjudication_rows = [
        {
            **proposal,
            "annotator": {"kind": "PENDING_HUMAN", "id": "", "signed_at": "", "attestation": ""},
            "reviewer": {"kind": "PENDING_HUMAN", "id": "", "signed_at": "", "attestation": ""},
            "adjudication_notes": "Replace the proposal with two-human adjudicated labels.",
        }
        for proposal in proposals
    ]
    _write_immutable(ADJUDICATION, _jsonl_text([adjudication_header, *adjudication_rows]))

    _write_immutable(
        ANNOTATOR,
        _json_text(
            prep._packet(
                packet_id="P11-X0-ANNOTATOR-A-V07",
                role="ANNOTATOR",
                cases=cases,
                fixture_file_sha256=fixture_file_sha256,
                fixture_semantic_sha256=fixture_semantic_sha256,
            )
        ),
    )
    _write_immutable(
        REVIEWER,
        _json_text(
            prep._packet(
                packet_id="P11-X0-REVIEWER-B-V07",
                role="INDEPENDENT_REVIEWER",
                cases=cases,
                fixture_file_sha256=fixture_file_sha256,
                fixture_semantic_sha256=fixture_semantic_sha256,
            )
        ),
    )
    summary = {
        "schema_version": "milai-product11-x0-preparation-summary-v0.2",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "X0_REPAIRED_SLICE_AWAITING_A0_AND_HUMAN_ADJUDICATION",
        "repair_basis": superseded_summary,
        "source_fixture": str(FIXTURE.relative_to(ROOT)),
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "dataset_manifest": str(MANIFEST.relative_to(ROOT)),
        "dataset_manifest_file_sha256": hashlib.sha256(manifest_text.encode()).hexdigest(),
        "candidate_labels": str(CANDIDATE.relative_to(ROOT)),
        "candidate_labels_file_sha256": hashlib.sha256(proposal_text.encode()).hexdigest(),
        "human_adjudication_template": str(ADJUDICATION.relative_to(ROOT)),
        "annotator_packet": str(ANNOTATOR.relative_to(ROOT)),
        "reviewer_packet": str(REVIEWER.relative_to(ROOT)),
        "fixture_summary": fixture_summary,
        "human_adjudication_complete_count": 0,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "product_behavior_written": False,
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
    print(json.dumps(run(args.run_id), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
