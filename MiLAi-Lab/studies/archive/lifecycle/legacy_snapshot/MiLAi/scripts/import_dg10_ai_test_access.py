from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_independent_gates as gates
from scripts import dg10_remediation as remediation
from scripts.import_dg10_candidate4_ai_audits import _verify_bundle

DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json"
)
DEFAULT_BUNDLE_ROOT = ROOT.parent / "evidence/dg10-candidate4-ai-test-access-review"
DEFAULT_AUDIT_ROOT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-test-access-authority-audits"
)
DEFAULT_BUNDLE_RECEIPT = ROOT / (
    "docs/reports/DG-10-ai-test-access-review-bundle-candidate.4-2026-08-22.json"
)
DEFAULT_IDENTITIES = ROOT / (
    "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json"
)


class TestAccessImportError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise TestAccessImportError(reason)


def _require_nonfatal_ai_stderr(raw: bytes) -> None:
    _require(
        remediation.ai_audit_stderr_is_nonfatal(raw),
        "AI test-access stderr contains an unclassified error",
    )


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TestAccessImportError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    path = path.resolve()
    _require(path.is_relative_to(ROOT) and path.is_file() and not path.is_symlink(), "unsafe evidence")
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": remediation.sha256_file(path)}


def _events(path: Path) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    for line in path.read_bytes().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TestAccessImportError("AI event stream contains invalid JSON") from exc
        _require(isinstance(event, dict), "AI event is not an object")
        events.append(event)
    threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    _require(
        len(threads) == 1
        and isinstance(threads[0], str)
        and threads[0]
        and sum(event.get("type") == "turn.completed" for event in events) == 1
        and not any(event.get("type") in {"error", "turn.failed"} for event in events),
        "AI event provenance drift",
    )
    return events, threads[0]


def _validate_attempt(
    attempt: Path,
    *,
    bundle: Path,
    bundle_id: str,
    bundle_entries_sha256: str,
    expected_inputs: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    attempt = attempt.resolve()
    _require(
        attempt.parent == DEFAULT_AUDIT_ROOT.resolve()
        and attempt.name.startswith("candidate.4-test-access-primary-"),
        "AI test-access attempt is outside the fixed protected audit root",
    )
    files = {
        name: attempt / name
        for name in ("process.json", "review-output.json", "events.jsonl", "stderr.log")
    }
    _require(
        attempt.is_dir()
        and stat.S_IMODE(attempt.stat().st_mode) == 0o700
        and all(
            path.is_file()
            and not path.is_symlink()
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            for path in files.values()
        ),
        "AI test-access attempt mode or file drift",
    )
    process = _object(files["process.json"])
    _require(
        process.get("candidate_id") == remediation.CANDIDATE
        and process.get("scope") == "TEST_ACCESS_PRIMARY"
        and process.get("model") == "gpt-5.6-sol"
        and process.get("reasoning_effort") == "xhigh"
        and process.get("process_exit_code") == 0
        and process.get("bundle_directory_id") == bundle_id
        and process.get("sandbox") == "read-only"
        and process.get("ephemeral") is True
        and process.get("ignore_user_config") is True
        and process.get("ignore_rules") is True,
        "AI test-access process provenance drift",
    )
    bindings = {
        "prompt_sha256": bundle / "audit-prompt.md",
        "response_schema_sha256": bundle / "audit-response.schema.json",
        "events_sha256": files["events.jsonl"],
        "stderr_sha256": files["stderr.log"],
        "output_sha256": files["review-output.json"],
    }
    for key, path in bindings.items():
        _require(process.get(key) == remediation.sha256_file(path), f"AI process hash drift: {key}")
    provenance.validate_execution_attestation(
        process.get("execution_attestation"),
        bundle=bundle,
        output=files["review-output.json"],
        materialized_runner=(
            bundle / "current-source/scripts/run_dg10_candidate4_ai_audit.py"
        ),
        process=process,
    )
    _require_nonfatal_ai_stderr(files["stderr.log"].read_bytes())
    events, _thread = _events(files["events.jsonl"])
    output = _object(files["review-output.json"])
    required = {
        "schema_version",
        "review_type",
        "authority",
        "candidate_id",
        "model_requested",
        "audit_role",
        "bundle_entries_sha256",
        "inputs",
        "decision",
        "open_p0_count",
        "open_p1_count",
        "findings",
        "rationale",
    }
    _require(set(output) == required, "AI test-access output key set drift")
    _require(
        output.get("schema_version") == "1.0"
        and output.get("review_type") == "AI_TEST_ACCESS_AUDIT"
        and output.get("authority") == "AI_INDEPENDENT_PER_USER_POLICY"
        and output.get("candidate_id") == remediation.CANDIDATE
        and output.get("model_requested") == "gpt-5.6-sol"
        and output.get("audit_role") == "PRIMARY"
        and output.get("bundle_entries_sha256") == bundle_entries_sha256
        and output.get("inputs") == dict(expected_inputs)
        and output.get("decision") == "APPROVE_ONE_FULL_TEST"
        and output.get("open_p0_count") == 0
        and output.get("open_p1_count") == 0
        and isinstance(output.get("rationale"), str),
        "AI test-access output did not approve the exact bound inputs",
    )
    findings = output.get("findings")
    _require(isinstance(findings, list), "AI test-access findings are not a list")
    finding_keys = {
        "finding_id",
        "severity",
        "status",
        "title",
        "rationale",
        "evidence_paths",
        "required_action",
    }
    _require(
        all(
            isinstance(finding, Mapping)
            and set(finding) == finding_keys
            and finding.get("severity") in {"P0", "P1", "P2", "P3"}
            and finding.get("status") in {"OPEN", "CLOSED", "ACCEPTED_RISK"}
            and isinstance(finding.get("evidence_paths"), list)
            for finding in findings
        ),
        "AI test-access finding schema drift",
    )
    recomputed_p0 = sum(
        finding["severity"] == "P0" and finding["status"] == "OPEN"
        for finding in findings
    )
    recomputed_p1 = sum(
        finding["severity"] == "P1" and finding["status"] == "OPEN"
        for finding in findings
    )
    _require(
        output["open_p0_count"] == recomputed_p0 == 0
        and output["open_p1_count"] == recomputed_p1 == 0,
        "AI test-access open finding count drift",
    )
    final_messages = [
        event["item"]["text"]
        for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    _require(bool(final_messages), "AI test-access final event absent")
    try:
        final_output = json.loads(final_messages[-1])
    except json.JSONDecodeError as exc:
        raise TestAccessImportError("AI test-access final event is not JSON") from exc
    _require(final_output == output, "AI test-access final event/output mismatch")
    semantic = {
        "candidate_id": remediation.CANDIDATE,
        "inputs": dict(expected_inputs),
        "decision": output["decision"],
        "open_p0": 0,
        "open_p1": 0,
    }
    return process, remediation.sha256_bytes(remediation.encoded_json(semantic))


def import_approval(
    *,
    bundle: Path,
    bundle_receipt_path: Path,
    attempt_paths: Sequence[Path],
    inputs: Mapping[str, Path],
    identity_receipt_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    _require(len(attempt_paths) == 2, "exactly two AI test-access primaries required")
    _require(
        bundle_receipt_path.resolve() == DEFAULT_BUNDLE_RECEIPT.resolve()
        and identity_receipt_path.resolve() == DEFAULT_IDENTITIES.resolve(),
        "test-access importer requires fixed bundle and identity receipts",
    )
    bundle_receipt = _object(bundle_receipt_path.resolve())
    manifest, _paths = _verify_bundle(bundle.resolve(), bundle_receipt)
    _require(
        bundle.resolve()
        == (DEFAULT_BUNDLE_ROOT / str(bundle_receipt["bundle_directory_id"])).resolve(),
        "test-access bundle path substitution",
    )
    identities = gates.authorization._verify_identity_receipt(
        identity_receipt_path.resolve()
    )
    _require(
        manifest.get("closure", {}).get("source_entries_sha256")
        == identities["source_inventory_sha256"],
        "test-access bundle source identity drift",
    )
    expected_inputs = {key: _reference(path) for key, path in sorted(inputs.items())}
    validated = [
        _validate_attempt(
            attempt,
            bundle=bundle.resolve(),
            bundle_id=str(bundle_receipt["bundle_directory_id"]),
            bundle_entries_sha256=str(manifest["bundle_entries_sha256"]),
            expected_inputs=expected_inputs,
        )
        for attempt in attempt_paths
    ]
    semantic_hashes = [item[1] for item in validated]
    _require(len(set(semantic_hashes)) == 1, "AI test-access semantic verdict conflict")
    output_path = output_path.resolve()
    run_paths = [
        output_path.parent / f"DG-10-ai-test-access-primary-{index}-candidate.4-2026-08-22.json"
        for index in (1, 2)
    ]
    raw_directories = [
        output_path.parent / f"DG-10-ai-test-access-primary-{index}-candidate.4-raw-2026-08-22"
        for index in (1, 2)
    ]
    _require(
        not output_path.exists()
        and not any(path.exists() for path in [*run_paths, *raw_directories]),
        "refusing to overwrite immutable test-access evidence",
    )
    threads: list[str] = []
    for index, (attempt, process, semantic_sha256) in enumerate(
        zip(attempt_paths, (item[0] for item in validated), semantic_hashes, strict=True)
    ):
        attempt = attempt.resolve()
        sources = {
            "prompt": bundle.resolve() / "audit-prompt.md",
            "response_schema": bundle.resolve() / "audit-response.schema.json",
            "output": attempt / "review-output.json",
            "events": attempt / "events.jsonl",
            "stderr": attempt / "stderr.log",
            "process": attempt / "process.json",
        }
        names = {
            "prompt": "prompt.md",
            "response_schema": "response.schema.json",
            "output": "output.json",
            "events": "events.jsonl",
            "stderr": "stderr.log",
            "process": "process.json",
        }
        raw_evidence: dict[str, dict[str, str]] = {}
        for key, source in sources.items():
            target = raw_directories[index] / names[key]
            remediation.atomic_write_new(target, source.read_bytes())
            raw_evidence[key] = _reference(target)
        _events_value, thread = _events(attempt / "events.jsonl")
        threads.append(thread)
        raw_hashes = {
            key: remediation.sha256_file(source)
            for key, source in sources.items()
            if key != "process"
        }
        run = {
            "schema": "milai.dg10.ai-review-run-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "scope": "TEST_ACCESS_PRIMARY",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "cli_version": process["cli_version"],
            "process_exit_code": 0,
            "provider_thread_id": thread,
            "provider_thread_count": 1,
            "turn_completed_count": 1,
            "error_count": 0,
            "output_schema_validation": "PASS",
            "boundary_validation": "PASS",
            "decision": "PASS",
            "open_p0": 0,
            "open_p1": 0,
            "verdict_sha256": semantic_sha256,
            "raw_evidence_hashes": raw_hashes,
            "raw_evidence": raw_evidence,
        }
        remediation.atomic_write_new(run_paths[index], remediation.encoded_json(run))
        gates._validate_ai_run(_reference(run_paths[index]), expected_scope="TEST_ACCESS_PRIMARY")
    _require(len(set(threads)) == 2, "AI test-access provider threads are not distinct")
    approval = {
        "schema": "milai.dg10.ai-test-access-approval.v2",
        "candidate_id": remediation.CANDIDATE,
        "decision": "APPROVE_ONE_FULL_TEST",
        "evidence_class": "AI_INDEPENDENT",
        "policy_override_sha256": remediation.sha256_file(remediation.AI_POLICY_OVERRIDE),
        "identity_receipt": _reference(identity_receipt_path.resolve()),
        "open_p0": 0,
        "open_p1": 0,
        "inputs": expected_inputs,
        "bundle_receipt": _reference(bundle_receipt_path.resolve()),
        "primary_audits": [_reference(path) for path in run_paths],
        "provider_thread_count": 2,
        "semantic_verdict_sha256": semantic_hashes[0],
    }
    remediation.atomic_write_new(output_path, remediation.encoded_json(approval))
    gates.validate_ai_test_access_approval(output_path, expected_inputs=expected_inputs)
    return approval


def main() -> None:
    parser = argparse.ArgumentParser(description="Import two xhigh AI test-access audits")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, required=True)
    parser.add_argument("--identity-receipt", type=Path, default=DEFAULT_IDENTITIES)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--case-manifest", type=Path, required=True)
    parser.add_argument("--attempt-ledger", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--hard-safety", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    approval = import_approval(
        bundle=args.bundle,
        bundle_receipt_path=args.bundle_receipt,
        attempt_paths=args.attempt,
        inputs={
            "results": args.results,
            "case_manifest": args.case_manifest,
            "attempt_ledger": args.attempt_ledger,
            "topology": args.topology,
            "hard_safety": args.hard_safety,
        },
        identity_receipt_path=args.identity_receipt,
        output_path=args.output,
    )
    print(json.dumps({"decision": approval["decision"], "provider_thread_count": 2}, sort_keys=True))


if __name__ == "__main__":
    main()
