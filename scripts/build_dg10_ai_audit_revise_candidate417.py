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
    "candidate.4-primary-017"
)
BUNDLE = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-review/"
    "sha256-c9675b542a785fea9abbb9163464dd3cabd91310ddc355980a0d736c5f6b1643"
)
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.14.json"
)
AUTHORITY_POLICY_SHA256 = (
    "5b7044c7c87b4e4721db18bf89f80e5d3035dde6be13f6401977ca941364104d"
)
EXPECTED_RAW_HASHES = {
    "events.jsonl": "beedc7a7d478d2c4ff9bff61f9cf5d219a7608d07613c44698afce32224377d3",
    "process.json": "167ffbe5c573689932effd1aa07720218825972a249bb464d413506f6db20d94",
    "review-output.json": "89dde8469cc38fb3e85abaaa942fc040a3c096260a10c944dbb05375fdfee92e",
    "stderr.log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.17-2026-08-22.json"
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise remediation.RemediationError(reason)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"historical AI material is not an object: {path}")
    return value


def _verify_historical_signature(process: Mapping[str, Any]) -> None:
    _require(
        remediation.sha256_file(AUTHORITY_POLICY) == AUTHORITY_POLICY_SHA256,
        "historical AI authority policy drift",
    )
    policy = _object(AUTHORITY_POLICY)
    attestation = process.get("execution_attestation")
    _require(
        isinstance(attestation, Mapping)
        and attestation.get("schema") == "milai.dg10.ai-execution-attestation.v2"
        and attestation.get("channel") == "SEPARATE_UID_ED25519_LIVE_CODEX_V2"
        and attestation.get("authority_policy_sha256") == AUTHORITY_POLICY_SHA256
        and attestation.get("key_id") == policy["key_id"]
        and attestation.get("public_key_sha256") == policy["public_key_sha256"],
        "historical AI execution authority identity drift",
    )
    statement = attestation.get("signed_statement")
    _require(
        isinstance(statement, Mapping)
        and statement.get("schema") == "milai.dg10.ai-execution-signed-statement.v2"
        and statement.get("authority_uid") == policy["authority_uid"]
        and statement.get("authority_gid") == policy["authority_gid"]
        and statement.get("signed_after_terminal_output_hashes") is True
        and statement.get("process")
        == {key: value for key, value in process.items() if key != "execution_attestation"},
        "historical AI signed statement drift",
    )
    try:
        public_raw = base64.b64decode(policy["public_key_base64"], validate=True)
        signature = base64.b64decode(attestation["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature,
            remediation.encoded_json(dict(statement)),
        )
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise remediation.RemediationError(
            "historical AI execution signature verification failed"
        ) from exc


def build() -> dict[str, Any]:
    _require(
        ATTEMPT.is_dir()
        and not ATTEMPT.is_symlink()
        and ATTEMPT.stat().st_uid == 998
        and ATTEMPT.stat().st_gid == 998
        and stat.S_IMODE(ATTEMPT.stat().st_mode) == 0o700,
        "historical protected AI attempt root drift",
    )
    for name, expected in EXPECTED_RAW_HASHES.items():
        path = ATTEMPT / name
        _require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == 998
            and path.stat().st_gid == 998
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            and remediation.sha256_file(path) == expected,
            f"historical protected AI attempt drift: {name}",
        )
    process = _object(ATTEMPT / "process.json")
    _verify_historical_signature(process)
    _require(
        process.get("attempt_id") == "candidate.4-primary-017"
        and process.get("bundle_directory_id") == BUNDLE.name
        and process.get("model") == "gpt-5.6-sol"
        and process.get("reasoning_effort") == "xhigh"
        and process.get("process_exit_code") == 0
        and process.get("termination_reason") == "COMPLETED"
        and process.get("output_sha256") == EXPECTED_RAW_HASHES["review-output.json"]
        and process.get("events_sha256") == EXPECTED_RAW_HASHES["events.jsonl"]
        and process.get("stderr_sha256") == EXPECTED_RAW_HASHES["stderr.log"],
        "historical protected AI process semantics drift",
    )
    _require((ATTEMPT / "stderr.log").read_bytes() == b"", "historical AI stderr drift")
    review = _object(ATTEMPT / "review-output.json")
    _require(
        review.get("candidate_id") == remediation.CANDIDATE
        and review.get("audit_role") == "PRIMARY"
        and review.get("overall_disposition") == "REVISE"
        and review.get("bootstrap_policy_disposition")
        == "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL"
        and review.get("open_p0_count") == 6
        and review.get("open_p1_count") == 3
        and review.get("open_p2_count") == 1
        and isinstance(review.get("findings"), list)
        and len(review["findings"]) == 10
        and {item.get("finding_id") for item in review["findings"]}
        >= {"DG10-C4-AI-027", "DG10-C4-AI-028"},
        "historical AI REVISE semantics drift",
    )
    events = [json.loads(line) for line in (ATTEMPT / "events.jsonl").read_bytes().splitlines()]
    _require(
        sum(item.get("type") == "thread.started" for item in events) == 1
        and sum(item.get("type") == "turn.completed" for item in events) == 1
        and not any(item.get("type") in {"error", "turn.failed"} for item in events),
        "historical AI event stream drift",
    )
    messages = [
        item["item"]["text"]
        for item in events
        if item.get("type") == "item.completed"
        and isinstance(item.get("item"), Mapping)
        and item["item"].get("type") == "agent_message"
    ]
    _require(messages and json.loads(messages[-1]) == review, "historical AI output continuity drift")
    return {
        "schema": "milai.dg10.r0-r2-ai-audit-revise-receipt.v2",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": process["attempt_id"],
        "bundle_directory_id": process["bundle_directory_id"],
        "model": process["model"],
        "reasoning_effort": process["reasoning_effort"],
        "closed_set_validation": {
            "status": "PASS",
            "execution_attestation": "V2_SEPARATE_UID_ED25519_SIGNATURE_VERIFIED",
            "authority_policy_sha256": AUTHORITY_POLICY_SHA256,
            "acceptance_effect": False,
            "unbound_evidence_paths": [],
        },
        "review_result": review,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits/"
                "candidate.4-primary-017"
            ),
            "hashes": EXPECTED_RAW_HASHES,
        },
        "accepted_stages": [],
        "model_run_authorized": False,
        "release_authorized": False,
        "status": "VALID_PROTECTED_V2_REVISE_NO_ACCEPTANCE_EFFECT",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze candidate.4-primary-017 AI REVISE")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = build()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
