from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation
from scripts import dg10_stage_ledger as stage_ledger
from scripts.import_dg10_candidate4_ai_audits import _verify_bundle

DEFAULT_BUNDLE_ROOT = ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r3-review"
DEFAULT_AUDIT_ROOT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r3-authority-audits"
)
DEFAULT_BUNDLE_RECEIPT = ROOT / (
    "docs/reports/DG-10-r3-ai-review-bundle-candidate.4-2026-08-22.json"
)
DEFAULT_IDENTITIES = ROOT / (
    "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json"
)
DEFAULT_OUTPUT_DIRECTORY = ROOT / "docs/reviews"
AGGREGATE = DEFAULT_OUTPUT_DIRECTORY / "DG-10-r3-ai-audit-candidate.4-2026-08-22.json"
STAGE_RECEIPT = DEFAULT_OUTPUT_DIRECTORY / (
    "DG-10-dg10-r3-ai-stage-receipt-candidate.4-2026-08-22.json"
)


class R3ImportError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise R3ImportError(reason)


def _require_nonfatal_ai_stderr(raw: bytes) -> None:
    _require(
        remediation.ai_audit_stderr_is_nonfatal(raw),
        "R3 AI stderr contains an unclassified error",
    )


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R3ImportError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    target = path.resolve()
    _require(
        target.is_relative_to(ROOT.resolve())
        and target.is_file()
        and not target.is_symlink(),
        "R3 evidence is missing or unsafe",
    )
    return {
        "path": target.relative_to(ROOT.resolve()).as_posix(),
        "sha256": remediation.sha256_file(target),
    }


def _events(path: Path) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    for raw in path.read_bytes().splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise R3ImportError("R3 AI event stream contains invalid JSON") from exc
        _require(isinstance(event, dict), "R3 AI event is not an object")
        events.append(event)
    threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    _require(
        len(threads) == 1
        and isinstance(threads[0], str)
        and threads[0]
        and sum(event.get("type") == "turn.completed" for event in events) == 1
        and not any(event.get("type") in {"error", "turn.failed"} for event in events),
        "R3 AI event provenance drift",
    )
    return events, threads[0]


def _validate_evidence_paths(
    bundle: Path, values: object, manifest_paths: set[str]
) -> list[str]:
    _require(isinstance(values, list) and values, "R3 audit evidence paths absent")
    _require(len(values) == len(set(values)), "R3 audit evidence path repeats")
    for value in values:
        _require(isinstance(value, str) and value, "R3 audit evidence path invalid")
        parsed = PurePosixPath(value)
        _require(
            not parsed.is_absolute()
            and ".." not in parsed.parts
            and (value in manifest_paths or value == "review-manifest.json"),
            "R3 audit cites unbound evidence",
        )
        target = (bundle / parsed).resolve()
        _require(target.is_relative_to(bundle) and target.is_file(), "R3 evidence absent")
    return [str(value) for value in values]


def _validate_attempt(
    attempt: Path,
    *,
    bundle: Path,
    bundle_id: str,
    bundle_entries_sha256: str,
    manifest_paths: set[str],
) -> tuple[dict[str, Any], str, str]:
    attempt = attempt.resolve()
    _require(
        attempt.parent == DEFAULT_AUDIT_ROOT.resolve()
        and attempt.name.startswith("candidate.4-r3-primary-")
        and attempt.is_dir()
        and stat.S_IMODE(attempt.stat().st_mode) == 0o700,
        "R3 attempt is outside the fixed protected audit root",
    )
    files = {
        name: attempt / name
        for name in ("process.json", "review-output.json", "events.jsonl", "stderr.log")
    }
    _require(
        all(
            path.is_file()
            and not path.is_symlink()
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            for path in files.values()
        ),
        "R3 attempt file or mode drift",
    )
    process = _object(files["process.json"])
    _require(
        process.get("candidate_id") == remediation.CANDIDATE
        and process.get("attempt_id") == attempt.name
        and process.get("scope") == "R3_PRIMARY"
        and process.get("model") == "gpt-5.6-sol"
        and process.get("reasoning_effort") == "xhigh"
        and process.get("process_exit_code") == 0
        and process.get("termination_reason") == "COMPLETED"
        and process.get("bundle_directory_id") == bundle_id
        and process.get("sandbox") == "read-only"
        and process.get("ephemeral") is True
        and process.get("ignore_user_config") is True
        and process.get("ignore_rules") is True,
        "R3 AI process provenance drift",
    )
    bindings = {
        "prompt_sha256": bundle / "audit-prompt.md",
        "response_schema_sha256": bundle / "audit-response.schema.json",
        "events_sha256": files["events.jsonl"],
        "stderr_sha256": files["stderr.log"],
        "output_sha256": files["review-output.json"],
    }
    for key, path in bindings.items():
        _require(process.get(key) == remediation.sha256_file(path), f"R3 process hash drift: {key}")
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
    events, thread = _events(files["events.jsonl"])
    output = _object(files["review-output.json"])
    required = {
        "schema_version",
        "review_type",
        "authority",
        "candidate_id",
        "model_requested",
        "audit_role",
        "bundle_entries_sha256",
        "decision",
        "open_p0_count",
        "open_p1_count",
        "findings",
        "rationale",
        "evidence_paths",
    }
    _require(set(output) == required, "R3 AI output key set drift")
    _require(
        output.get("schema_version") == "1.0"
        and output.get("review_type") == "AI_R3_SEMANTIC_AUDIT"
        and output.get("authority") == "AI_INDEPENDENT_PER_USER_POLICY"
        and output.get("candidate_id") == remediation.CANDIDATE
        and output.get("model_requested") == "gpt-5.6-sol"
        and output.get("audit_role") == "PRIMARY"
        and output.get("bundle_entries_sha256") == bundle_entries_sha256
        and output.get("decision") == "ACCEPT_R3"
        and output.get("open_p0_count") == 0
        and output.get("open_p1_count") == 0
        and isinstance(output.get("findings"), list)
        and isinstance(output.get("rationale"), str)
        and output["rationale"],
        "R3 AI output does not accept the exact bundle",
    )
    _validate_evidence_paths(bundle, output.get("evidence_paths"), manifest_paths)
    open_p0 = sum(
        item.get("severity") == "P0" and item.get("status") == "OPEN"
        for item in output["findings"]
        if isinstance(item, Mapping)
    )
    open_p1 = sum(
        item.get("severity") == "P1" and item.get("status") == "OPEN"
        for item in output["findings"]
        if isinstance(item, Mapping)
    )
    _require(open_p0 == open_p1 == 0, "R3 AI finding denominator drift")
    final_messages = [
        event["item"]["text"]
        for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    _require(bool(final_messages), "R3 AI final event absent")
    try:
        final_output = json.loads(final_messages[-1])
    except json.JSONDecodeError as exc:
        raise R3ImportError("R3 AI final event is not JSON") from exc
    _require(final_output == output, "R3 AI final event/output mismatch")
    semantic = {
        "candidate_id": remediation.CANDIDATE,
        "bundle_entries_sha256": bundle_entries_sha256,
        "decision": "ACCEPT_R3",
        "open_p0": 0,
        "open_p1": 0,
    }
    return process, thread, remediation.sha256_bytes(remediation.encoded_json(semantic))


def import_r3(
    *,
    bundle: Path,
    bundle_receipt_path: Path,
    identity_receipt_path: Path,
    attempt_paths: Sequence[Path],
) -> dict[str, Any]:
    _require(len(attempt_paths) == 2, "exactly two protected R3 primaries required")
    _require(
        bundle_receipt_path.resolve() == DEFAULT_BUNDLE_RECEIPT.resolve()
        and identity_receipt_path.resolve() == DEFAULT_IDENTITIES.resolve(),
        "R3 importer requires fixed bundle and identities",
    )
    bundle_receipt = _object(bundle_receipt_path.resolve())
    manifest, manifest_paths = _verify_bundle(bundle.resolve(), bundle_receipt)
    _require(
        bundle.resolve()
        == (DEFAULT_BUNDLE_ROOT / str(bundle_receipt["bundle_directory_id"])).resolve(),
        "R3 bundle path substitution",
    )
    identities = authorization._verify_identity_receipt(identity_receipt_path.resolve())
    _require(
        manifest.get("closure", {}).get("source_entries_sha256")
        == identities["source_inventory_sha256"],
        "R3 bundle source identity drift",
    )
    validated = [
        _validate_attempt(
            path,
            bundle=bundle.resolve(),
            bundle_id=str(bundle_receipt["bundle_directory_id"]),
            bundle_entries_sha256=str(bundle_receipt["bundle_entries_sha256"]),
            manifest_paths=manifest_paths,
        )
        for path in attempt_paths
    ]
    threads = [item[1] for item in validated]
    verdicts = [item[2] for item in validated]
    _require(len(set(threads)) == 2, "R3 provider threads are not distinct")
    _require(len(set(verdicts)) == 1, "R3 semantic verdict conflict")
    ledger = stage_ledger.reconcile_stage_ledger()
    current = ledger.get("current_entries", {}).get("DG10-R3")
    _require(
        isinstance(current, Mapping)
        and current.get("stage_state") == "REVIEW_REQUIRED"
        and current.get("source_inventory_sha256")
        == identities["source_inventory_sha256"],
        "R3 ledger is not at the fixed review checkpoint",
    )
    run_paths = [
        DEFAULT_OUTPUT_DIRECTORY
        / f"DG-10-r3-ai-primary-{index}-candidate.4-2026-08-22.json"
        for index in (1, 2)
    ]
    raw_directories = [
        DEFAULT_OUTPUT_DIRECTORY
        / f"DG-10-r3-ai-primary-{index}-candidate.4-raw-2026-08-22"
        for index in (1, 2)
    ]
    _require(
        not any(path.exists() for path in [*run_paths, *raw_directories, AGGREGATE, STAGE_RECEIPT]),
        "refusing to overwrite immutable R3 evidence",
    )
    for index, (attempt, process, thread, verdict) in enumerate(
        zip(
            attempt_paths,
            (item[0] for item in validated),
            threads,
            verdicts,
            strict=True,
        )
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
        run = {
            "schema": "milai.dg10.ai-review-run-receipt.v1",
            "candidate_id": remediation.CANDIDATE,
            "scope": "R3_PRIMARY",
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
            "verdict_sha256": verdict,
            "raw_evidence_hashes": {
                key: remediation.sha256_file(source)
                for key, source in sources.items()
                if key != "process"
            },
            "raw_evidence": raw_evidence,
        }
        remediation.atomic_write_new(run_paths[index], remediation.encoded_json(run))
    aggregate = {
        "schema": "milai.dg10.r3-ai-audit.v1",
        "candidate_id": remediation.CANDIDATE,
        "status": "AI_INDEPENDENT_R3_ACCEPTED",
        "evidence_class": "AI_INDEPENDENT",
        "policy_override_sha256": identities["policy_override"]["sha256"],
        "identity_receipt": identities["receipt"],
        "bundle_receipt": _reference(bundle_receipt_path.resolve()),
        "primary_audits": [_reference(path) for path in run_paths],
        "provider_thread_count": 2,
        "semantic_verdict_sha256": verdicts[0],
        "open_p0": 0,
        "open_p1": 0,
        "model_run_authorized_by_audit": False,
        "test_access_authorized": False,
        "release_authorized": False,
    }
    remediation.atomic_write_new(AGGREGATE, remediation.encoded_json(aggregate))
    stage_receipt = {
        "schema": "milai.dg10.stage-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "stage_id": "DG10-R3",
        "stage_state": "ACCEPTED",
        "evidence_class": "AI_INDEPENDENT",
        "independent_acceptance": True,
        "source_inventory_sha256": identities["source_inventory_sha256"],
        "environment_identity_sha256": identities["environment_identity_sha256"],
        "model_identity_sha256": identities["model_identity_sha256"],
        "policy_override_sha256": identities["policy_override"]["sha256"],
        "open_p0": 0,
        "open_p1": 0,
        "evidence": [_reference(AGGREGATE)],
    }
    remediation.atomic_write_new(STAGE_RECEIPT, remediation.encoded_json(stage_receipt))
    stage_ledger.append_stage_state(
        stage_id="DG10-R3",
        stage_state="ACCEPTED",
        evidence_class="AI_INDEPENDENT",
        source_inventory_sha256=identities["source_inventory_sha256"],
        receipt_path=STAGE_RECEIPT,
    )
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description="Import two protected xhigh R3 AI reviews")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, default=DEFAULT_BUNDLE_RECEIPT)
    parser.add_argument("--identity-receipt", type=Path, default=DEFAULT_IDENTITIES)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    result = import_r3(
        bundle=args.bundle,
        bundle_receipt_path=args.bundle_receipt,
        identity_receipt_path=args.identity_receipt,
        attempt_paths=args.attempt,
    )
    print(json.dumps({"status": result["status"], "provider_thread_count": 2}, sort_keys=True))


if __name__ == "__main__":
    main()
