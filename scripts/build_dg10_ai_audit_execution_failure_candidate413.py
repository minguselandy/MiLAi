from __future__ import annotations

import argparse
import base64
import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

ATTEMPT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits/"
    "candidate.4-primary-015"
)
BUNDLE_RECEIPT = ROOT / (
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.13-2026-08-22.json"
)
HISTORICAL_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.12.json"
)
PREVIOUS_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.12-2026-08-22.json"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.13-2026-08-22.json"
)
EXPECTED_HASHES = {
    "events.jsonl": "237e68901ada32e05ebf2f8db22de17b119033678e66d010fb0260df84695d13",
    "process.json": "5b5cf4c9571cbae290907ce0260740dc46927a835ebcf34a49e2e5d5a01ea6d5",
    "review-output.json": "694a4f670d69369265a5d046341a08b4c5ebcf32fa675b1f7c0c36aeef2c5fb3",
    "stderr.log": "2a4cd8353f071f6877032af65b4b5d52083848c1a71a4e5c708623e374932734",
}
EXPECTED_BUNDLE_RECEIPT_SHA256 = (
    "8fe24998a089bf9fc5a65677a94862609fdb64d537c5b3183e27fc30551858eb"
)
EXPECTED_HISTORICAL_POLICY_SHA256 = (
    "75074a9dd87df854b35d25f967b8acb475b8ef92bb2bc69c2b78e6ad274d571f"
)
EXPECTED_PREVIOUS_FAILURE_SHA256 = (
    "77ab8f76b1a662d3f2b5f3d9c946356d4745fa9a4e5986e181b18a7164057e2e"
)
EXPECTED_FINDINGS = ("DG10-C4-AI-027", "DG10-C4-AI-028")


class AuditExecutionFailureError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditExecutionFailureError(reason)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditExecutionFailureError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON object absent: {path}")
    return value


def _verify_historical_signature(
    process: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    attestation = process.get("execution_attestation")
    _require(isinstance(attestation, Mapping), "historical execution attestation absent")
    statement = attestation.get("signed_statement")
    _require(
        attestation.get("schema") == "milai.dg10.ai-execution-attestation.v2"
        and attestation.get("channel") == "SEPARATE_UID_ED25519_LIVE_CODEX_V2"
        and attestation.get("authority_policy_sha256")
        == EXPECTED_HISTORICAL_POLICY_SHA256
        and attestation.get("key_id") == policy.get("key_id")
        and attestation.get("public_key_sha256") == policy.get("public_key_sha256")
        and isinstance(statement, Mapping),
        "historical execution authority identity drift",
    )
    expected_process = {
        key: value for key, value in process.items() if key != "execution_attestation"
    }
    _require(
        statement.get("process") == expected_process
        and statement.get("authority_uid") == policy.get("authority_uid")
        and statement.get("authority_gid") == policy.get("authority_gid")
        and statement.get("signed_after_terminal_output_hashes") is True,
        "historical signed process claims drift",
    )
    try:
        public_raw = base64.b64decode(policy.get("public_key_base64"), validate=True)
        signature = base64.b64decode(
            attestation.get("signature_base64"), validate=True
        )
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature,
            remediation.encoded_json(dict(statement)),
        )
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise AuditExecutionFailureError(
            "historical execution signature verification failed"
        ) from exc


def build_receipt() -> dict[str, Any]:
    _require(
        remediation.sha256_file(BUNDLE_RECEIPT)
        == EXPECTED_BUNDLE_RECEIPT_SHA256
        and remediation.sha256_file(HISTORICAL_POLICY)
        == EXPECTED_HISTORICAL_POLICY_SHA256
        and remediation.sha256_file(PREVIOUS_FAILURE)
        == EXPECTED_PREVIOUS_FAILURE_SHA256,
        "candidate.4.13 predecessor evidence drift",
    )
    policy = _object(HISTORICAL_POLICY)
    _require(
        ATTEMPT.is_dir()
        and not ATTEMPT.is_symlink()
        and ATTEMPT.stat().st_uid == policy["authority_uid"]
        and ATTEMPT.stat().st_gid == policy["authority_gid"]
        and stat.S_IMODE(ATTEMPT.stat().st_mode) == 0o700,
        "failed AI attempt directory identity drift",
    )
    files = {name: ATTEMPT / name for name in EXPECTED_HASHES}
    for name, expected in EXPECTED_HASHES.items():
        path = files[name]
        _require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == policy["authority_uid"]
            and path.stat().st_gid == policy["authority_gid"]
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            and remediation.sha256_file(path) == expected,
            f"failed AI attempt raw evidence drift: {name}",
        )
    process = _object(files["process.json"])
    _verify_historical_signature(process, policy)
    output = _object(files["review-output.json"])
    findings = output.get("findings")
    events = [json.loads(line) for line in files["events.jsonl"].read_bytes().splitlines()]
    final_messages = [
        event["item"]["text"]
        for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    _require(
        process.get("attempt_id") == ATTEMPT.name
        and process.get("scope") == "R0_R2_PRIMARY"
        and process.get("process_exit_code") == 0
        and process.get("termination_reason") == "COMPLETED"
        and process.get("model") == "gpt-5.6-sol"
        and process.get("reasoning_effort") == "xhigh"
        and process.get("bundle_directory_id")
        == "sha256-cb50b1fa09db57db851c9b598356204dfcd72782fc2bced227f5b82c32ca4b0e"
        and sum(event.get("type") == "thread.started" for event in events) == 1
        and sum(event.get("type") == "turn.completed" for event in events) == 1
        and not any(event.get("type") in {"error", "turn.failed"} for event in events)
        and final_messages
        and json.loads(final_messages[-1]) == output
        and output.get("overall_disposition") == "REVISE"
        and output.get("bootstrap_policy_disposition")
        == "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL"
        and isinstance(findings, list)
        and tuple(item.get("finding_id") for item in findings) == EXPECTED_FINDINGS,
        "failed AI attempt terminal semantics drift",
    )
    stderr = files["stderr.log"].read_bytes()
    lines = stderr.splitlines(keepends=True)
    _require(
        len(lines) == 5
        and all(
            line.endswith(
                (
                    " " + remediation.AI_AUDIT_MODEL_REFRESH_DIAGNOSTIC + "\n"
                ).encode("ascii")
            )
            for line in lines
        )
        and not remediation.ai_audit_stderr_is_nonfatal(stderr),
        "duplicate known stderr diagnostic was not reproduced",
    )
    return {
        "schema": "milai.dg10.ai-audit-execution-failure-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT",
        "attempt_id": ATTEMPT.name,
        "scope": "R0_R2_PRIMARY",
        "reason_code": "DUPLICATE_KNOWN_MODEL_REFRESH_STDERR_DIAGNOSTIC",
        "supersedes_failure": {
            "path": PREVIOUS_FAILURE.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_PREVIOUS_FAILURE_SHA256,
        },
        "failure_boundary": {
            "historical_signed_separate_uid_execution_attestation_valid": True,
            "strict_stderr_classification_valid": False,
            "semantic_output_observed_but_not_accepted": True,
            "audit_acceptance_effect": "NONE",
            "model_run_authorized": False,
            "test_access_authorized": False,
            "release_authorized": False,
        },
        "observed_nonaccepting_findings": [
            {
                "finding_id": item["finding_id"],
                "severity": item["severity"],
                "title": item["title"],
            }
            for item in findings
        ],
        "remediation_required": {
            "stderr_allowlist": (
                "EMPTY_OR_ONE_EXACT_ASCII_TIMESTAMPED_DIAGNOSTIC_WITH_ONE_LF"
            ),
            "reject_duplicate_prefix_suffix_crlf_and_undecodable_bytes": True,
            "freeze_codex_and_helper_uid_gid_mode_in_policy_and_replay": True,
            "rerun_only_after_full_deterministic_rebuild": True,
        },
        "bundle_receipt": {
            "path": BUNDLE_RECEIPT.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_BUNDLE_RECEIPT_SHA256,
        },
        "historical_authority_policy": {
            "path": HISTORICAL_POLICY.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_HISTORICAL_POLICY_SHA256,
        },
        "raw_attempt": {
            "path_class": "REPO_EXTERNAL_AUTHORITY_OWNED_0700_ATTEMPT",
            "files": [
                {"name": name, "sha256": digest}
                for name, digest in sorted(EXPECTED_HASHES.items())
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.13 duplicate-stderr AI execution failure"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    receipt = build_receipt()
    remediation.atomic_write_new(output, remediation.encoded_json(receipt))
    print(json.dumps({"output": str(output), "status": receipt["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
