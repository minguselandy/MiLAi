from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
CANDIDATE = "candidate.1"
DEFAULT_RECEIPT = (
    ROOT / f"docs/reviews/DG-10-sol-final-audit-receipt-{CANDIDATE}-{DATE}.json"
)
EXPECTED_TOP_LEVEL_KEYS = {
    "schema_version",
    "review_kind",
    "decision",
    "model",
    "reasoning_effort",
    "cli_version",
    "bundle_entries_sha256",
    "manifest_sha256",
    "prompt_sha256",
    "response_schema_sha256",
    "acceptance_authorized",
    "quality_outcome",
    "summary",
    "open_p0_p1_count",
    "findings",
    "coverage",
    "unverified",
}
EXPECTED_COVERAGE = {
    "claim_traceability",
    "benchmark_boundaries",
    "same_model_call_accounting",
    "memory_quality_tiers",
    "bfcl_semantics",
    "serving_accounting",
    "mcp_security_governance",
    "package_rollback_privacy",
    "status_inflation",
}


class ReviewImportError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReviewImportError(f"JSON is not an object: {path.name}")
    return value


def _manifest(bundle: Path) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    manifest_path = bundle / "review-manifest.json"
    manifest = _load_object(manifest_path)
    entries = manifest.get("entries")
    if (
        manifest.get("schema") != "milai.dg10.frozen-review-manifest.v1"
        or not isinstance(entries, list)
        or manifest.get("entry_count") != len(entries)
    ):
        raise ReviewImportError("review manifest contract drift")
    indexed: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ReviewImportError("review manifest entry drift")
        path = str(entry["path"])
        target = bundle / path
        if path in indexed or not target.is_file() or target.is_symlink():
            raise ReviewImportError("review manifest path drift")
        if _sha256(target) != entry.get("sha256") or target.stat().st_size != entry.get(
            "size"
        ):
            raise ReviewImportError("review bundle byte drift")
        indexed[path] = entry
    canonical = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if canonical != manifest.get("bundle_entries_sha256"):
        raise ReviewImportError("review bundle canonical digest drift")
    if bundle.name != f"sha256-{canonical}":
        raise ReviewImportError("review bundle directory identity drift")
    return manifest, indexed


def _validate_review_shape(review: Mapping[str, Any]) -> None:
    if set(review) != EXPECTED_TOP_LEVEL_KEYS:
        raise ReviewImportError("review top-level schema drift")
    expected_values = {
        "schema_version": "1",
        "review_kind": "AI_ADVERSARIAL_EVIDENCE_AUDIT_NOT_HUMAN_APPROVAL",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
        "cli_version": "codex-cli 0.147.0",
        "acceptance_authorized": False,
    }
    for key, expected in expected_values.items():
        if review.get(key) != expected:
            raise ReviewImportError(f"review invariant drift: {key}")
    if review.get("decision") not in {
        "NO_GO_EVIDENCE_SUPPORTED",
        "REVISE_NO_GO_EVIDENCE",
        "REJECT_EVIDENCE_BUNDLE",
    }:
        raise ReviewImportError("review decision drift")
    if review.get("quality_outcome") not in {"BELOW_TARGET", "NOT_EVALUABLE"}:
        raise ReviewImportError("review quality outcome drift")
    if not isinstance(review.get("summary"), str) or not review["summary"]:
        raise ReviewImportError("review summary drift")
    coverage = review.get("coverage")
    if (
        not isinstance(coverage, dict)
        or set(coverage) != EXPECTED_COVERAGE
        or any(
            value not in {"VERIFIED", "PARTIAL", "UNVERIFIED"}
            for value in coverage.values()
        )
    ):
        raise ReviewImportError("review coverage drift")
    if not isinstance(review.get("unverified"), list):
        raise ReviewImportError("review unverified drift")


def _validate_findings(
    review: Mapping[str, Any], bundle: Path, entries: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise ReviewImportError("review findings drift")
    ids: set[str] = set()
    severities: dict[str, int] = {name: 0 for name in ("P0", "P1", "P2", "P3")}
    citation_count = 0
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {
            "id",
            "severity",
            "criterion",
            "statement",
            "evidence",
            "reproduction",
            "release_effect",
            "recommendation",
        }:
            raise ReviewImportError("finding schema drift")
        finding_id = finding.get("id")
        severity = finding.get("severity")
        evidence = finding.get("evidence")
        if (
            not isinstance(finding_id, str)
            or not finding_id.startswith("DG10-SOL-")
            or finding_id in ids
            or severity not in severities
            or not isinstance(evidence, list)
            or not evidence
        ):
            raise ReviewImportError("finding identity/severity/evidence drift")
        ids.add(finding_id)
        severities[str(severity)] += 1
        for citation in evidence:
            if not isinstance(citation, dict) or set(citation) != {
                "file",
                "line",
                "sha256",
            }:
                raise ReviewImportError("finding citation schema drift")
            file = citation.get("file")
            line = citation.get("line")
            if not isinstance(file, str) or file not in entries:
                raise ReviewImportError("finding citation outside manifest")
            if citation.get("sha256") != entries[file].get("sha256"):
                raise ReviewImportError("finding citation digest drift")
            target_lines = (bundle / file).read_text(encoding="utf-8").splitlines()
            if (
                not isinstance(line, int)
                or isinstance(line, bool)
                or line < 1
                or line > len(target_lines)
                or not target_lines[line - 1].strip()
            ):
                raise ReviewImportError("finding citation line drift")
            citation_count += 1
    p0_p1 = severities["P0"] + severities["P1"]
    if review.get("open_p0_p1_count") != p0_p1:
        raise ReviewImportError("review P0/P1 count drift")
    return {
        "finding_count": len(findings),
        "citation_count": citation_count,
        "severity_counts": severities,
        "open_p0_p1_count": p0_p1,
    }


def _events(path: Path) -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ReviewImportError(f"event line is not an object: {number}")
        values.append(value)
    started = [value for value in values if value.get("type") == "thread.started"]
    completed = [value for value in values if value.get("type") == "turn.completed"]
    if (
        len(started) != 1
        or len(completed) != 1
        or not isinstance(started[0].get("thread_id"), str)
    ):
        raise ReviewImportError("Codex event/thread terminal contract drift")
    return {
        "event_count": len(values),
        "provider_thread_count": 1,
        "provider_thread_id": started[0]["thread_id"],
        "terminal_turn_count": 1,
        "usage": completed[0].get("usage"),
    }


def import_review(
    *,
    bundle: Path,
    output: Path,
    events: Path,
    stderr: Path,
    exit_code: int,
) -> dict[str, Any]:
    if exit_code != 0:
        raise ReviewImportError("Codex process exit code is nonzero")
    manifest, entries = _manifest(bundle)
    review = _load_object(output)
    _validate_review_shape(review)
    expected_digests = {
        "bundle_entries_sha256": manifest["bundle_entries_sha256"],
        "manifest_sha256": _sha256(bundle / "review-manifest.json"),
        "prompt_sha256": _sha256(bundle / "review-prompt.md"),
        "response_schema_sha256": _sha256(bundle / "response.schema.json"),
    }
    for key, expected in expected_digests.items():
        if review.get(key) != expected:
            raise ReviewImportError(f"review self-binding drift: {key}")
    finding_summary = _validate_findings(review, bundle, entries)
    event_summary = _events(events)
    return {
        "schema": "milai.dg10.sol-final-audit-receipt.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "CRG01_SOL_REVIEW_CANDIDATE_IMPORTED_NOT_ACCEPTANCE",
        "review_kind": review["review_kind"],
        "model": review["model"],
        "reasoning_effort": review["reasoning_effort"],
        "cli_version": review["cli_version"],
        "process_exit_code": exit_code,
        "output_schema_validation": "PASS_ENFORCED_BY_CODEX_CLI_AND_IMPORTER_INVARIANTS",
        "bundle": {
            "bundle_entries_sha256": manifest["bundle_entries_sha256"],
            "manifest_sha256": expected_digests["manifest_sha256"],
            "entry_count": manifest["entry_count"],
            "path_class": "REPO_EXTERNAL_READ_ONLY_MATERIALIZED_WORKSPACE",
        },
        "raw_evidence": {
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "output_sha256": _sha256(output),
            "output_size": output.stat().st_size,
            "events_sha256": _sha256(events),
            "events_size": events.stat().st_size,
            "stderr_sha256": _sha256(stderr),
            "stderr_size": stderr.stat().st_size,
        },
        "provider": event_summary,
        "review_result": {
            "decision": review["decision"],
            "quality_outcome": review["quality_outcome"],
            "acceptance_authorized": review["acceptance_authorized"],
            "summary_sha256": hashlib.sha256(review["summary"].encode()).hexdigest(),
            **finding_summary,
            "coverage": review["coverage"],
            "unverified_count": len(review["unverified"]),
        },
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "gate_results": {
            "CRG-00": "BUNDLE_VALIDATED",
            "CRG-01": "REVIEW_CANDIDATE_IMPORTED",
            "CRG-02": "DENIED_L4_REVISE_BELOW_TARGET_AND_NOT_CONTROLLED_ACCEPTANCE",
        },
        "release_effect": {
            "may_accept_candidate": False,
            "may_authorize_test": False,
            "may_override_tier1": False,
            "may_promote_local_vllm_mcp_agent_candidate": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the DG-10 Sol final audit")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--events-jsonl", type=Path, required=True)
    parser.add_argument("--stderr-log", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    receipt = import_review(
        bundle=args.bundle.resolve(),
        output=args.output_json.resolve(),
        events=args.events_jsonl.resolve(),
        stderr=args.stderr_log.resolve(),
        exit_code=args.exit_code,
    )
    receipt_path = args.receipt.resolve()
    if receipt_path.exists():
        raise ReviewImportError(f"refusing to overwrite review receipt: {receipt_path}")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(receipt_path, 0o600)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "decision": receipt["review_result"]["decision"],
                "open_p0_p1_count": receipt["review_result"]["open_p0_p1_count"],
                "receipt": str(receipt_path),
                "receipt_sha256": _sha256(receipt_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
