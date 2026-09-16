#!/usr/bin/env python3
"""Join a frozen A0 trace to model proposals without asserting a human X0 seal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11 import (
    InstanceGroup,
    canonical_sha256,
    classify_x0_opportunity,
    distinct_instance_coverage,
    validate_source_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "data/fixtures/product11-opened-dev24.v0.6.json"
DEFAULT_CANDIDATE = ROOT / "data/labels/product11-instance-groups.candidate.v0.7.jsonl"
DEFAULT_TRACE = (
    ROOT / "artifacts/product11/p11-x0-a0-20260904f/product-trace.redacted.jsonl"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"expected only JSON objects: {path}")
    return rows


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = _load_json(args.source_fixture)
    fixture_summary = validate_source_fixture(fixture)
    candidate_rows = _load_jsonl(args.candidate_labels)
    trace_rows = _load_jsonl(args.a0_trace)
    if len(candidate_rows) != 25 or len(trace_rows) != 24:
        raise ValueError("Product-11 proxy audit requires 24 candidate and trace rows")
    header = candidate_rows[0]
    if (
        header.get("record_type") != "manifest"
        or header.get("model_assisted_proxy") is not True
        or header.get("human_adjudication_status") != "PENDING"
        or header.get("formal_files_accessed") is not False
        or header.get("formal_cases_scored") != 0
        or header.get("source_fixture_file_sha256") != _sha256_file(args.source_fixture)
        or header.get("source_fixture_semantic_sha256") != canonical_sha256(fixture)
    ):
        raise ValueError("Product-11 candidate proxy header is invalid")
    case_ids = [str(case["case_id"]) for case in fixture["cases"]]
    candidates = {str(row["case_id"]): row for row in candidate_rows[1:]}
    traces = {str(row["case_id"]): row for row in trace_rows}
    if list(candidates) != case_ids or list(traces) != case_ids:
        raise ValueError("Product-11 proxy audit case order drifted")
    if any(row.get("status") != "TRACE_COMPLETE" for row in trace_rows):
        raise ValueError("Product-11 A0 trace is incomplete")

    case_views: list[dict[str, Any]] = []
    opportunity_counts: Counter[str] = Counter()
    for source_case in fixture["cases"]:
        case_id = str(source_case["case_id"])
        proposal = candidates[case_id]
        trace = traces[case_id]
        groups = tuple(
            InstanceGroup.from_mapping(group) for group in proposal["instance_groups"]
        )
        identity_sets = trace.get("identity_sets")
        if not isinstance(identity_sets, Mapping):
            raise ValueError(f"case {case_id} has no identity sets")
        visible_evidence = _strings(identity_sets.get("rendered_evidence_ids"))
        visible_turns = _strings(identity_sets.get("rendered_turn_refs"))
        direct_evidence = _strings(identity_sets.get("post_identity_evidence_ids"))
        direct_turns = _strings(identity_sets.get("post_identity_turn_refs"))
        raw_evidence = _strings(identity_sets.get("raw_evidence_ids"))
        raw_turns = _strings(identity_sets.get("raw_turn_refs"))
        frontier_evidence = sorted(set(raw_evidence).difference(visible_evidence))
        frontier_turns = sorted(set(raw_turns).difference(visible_turns))
        ref_to_scope = {
            str(turn["turn_ref"]): (str(session["source_id"]), str(session["session_id"]))
            for session in source_case["sessions"]
            for turn in session["turns"]
        }
        coarse_refs = set(direct_turns).union(visible_turns)
        coarse_sources = sorted(
            {ref_to_scope[ref][0] for ref in coarse_refs if ref in ref_to_scope}
        )
        coarse_sessions = sorted(
            {ref_to_scope[ref][1] for ref in coarse_refs if ref in ref_to_scope}
        )
        classification = classify_x0_opportunity(
            groups,
            visible_evidence_ids=visible_evidence,
            visible_turn_refs=visible_turns,
            direct_evidence_ids=direct_evidence,
            direct_turn_refs=direct_turns,
            frontier_evidence_ids=frontier_evidence,
            frontier_turn_refs=frontier_turns,
            selected_coarse_source_ids=coarse_sources,
            selected_coarse_session_ids=coarse_sessions,
        )
        for key, value in classification.items():
            opportunity_counts[key] += bool(value)
        coverage = distinct_instance_coverage(
            groups,
            visible_evidence_ids=visible_evidence,
            visible_turn_refs=visible_turns,
        )
        case_views.append(
            {
                "schema_version": "milai-product11-x0-proxy-case-view-v0.1",
                "case_id": case_id,
                "label_provenance": "MODEL_ASSISTED_PROPOSAL_ONLY",
                "human_adjudication_status": "PENDING",
                "distinct_instance_coverage": coverage,
                "raw_candidate_turn_refs": raw_turns,
                "direct_anchor_turn_refs": direct_turns,
                "host_visible_turn_refs": visible_turns,
                "persistable_unseen_frontier_turn_refs": frontier_turns,
                "selected_coarse_source_ids": coarse_sources,
                "selected_coarse_session_ids": coarse_sessions,
                **classification,
            }
        )
    _write_jsonl(args.output / "case-view.jsonl", case_views)
    continuation = opportunity_counts["continuation_opportunity"]
    intra_source = opportunity_counts["intra_source_opportunity"]
    controls = opportunity_counts["control_or_already_complete"]
    proxy_ready = continuation >= 8 and intra_source >= 8 and controls >= 8
    summary = {
        "schema_version": "milai-product11-x0-proxy-audit-summary-v0.1",
        "status": (
            "PASS_PRODUCT11_X0_PROXY_OPPORTUNITY_SUBSTRATE"
            if proxy_ready
            else "FAIL_PRODUCT11_X0_PROXY_OPPORTUNITY_SUBSTRATE"
        ),
        "audited_at": datetime.now(UTC).isoformat(),
        "case_count": fixture_summary["case_count"],
        "continuation_opportunity_count": continuation,
        "intra_source_opportunity_count": intra_source,
        "control_or_already_complete_count": controls,
        "thresholds": {"continuation_gte": 8, "intra_source_gte": 8, "control_gte": 8},
        "candidate_label_provenance": "MODEL_ASSISTED_PROPOSAL_ONLY",
        "human_adjudication_status": "PENDING_NOT_EVALUATED",
        "x0_gate_status": "NOT_EVALUATED_WITH_HUMAN_LABELS",
        "effect_claim_status": "NOT_TESTED",
        "source_fixture_sha256": _sha256_file(args.source_fixture),
        "candidate_labels_sha256": _sha256_file(args.candidate_labels),
        "a0_trace_sha256": _sha256_file(args.a0_trace),
        "case_view_sha256": _sha256_file(args.output / "case-view.jsonl"),
        "labels_loaded_after_frozen_trace": True,
        "product_label_access": 0,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "product_behavior_written": False,
    }
    _write_json(args.output / "summary.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--candidate-labels", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--a0-trace", type=Path, default=DEFAULT_TRACE)
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
