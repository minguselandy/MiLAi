from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

PREVIOUS = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.12.json"
)
PREVIOUS_SHA256 = "f1ebb5a76806a3b079a594071e2a4850c576c9324a17d784f8933d74ae3672fb"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.13.json"
)
AUTHORITY_POLICY_SHA256 = (
    "003bf73ec0069c696bcef8ee2ec938483fc9a6170afda48663caec869a70ae26"
)
EXECUTION_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.13-2026-08-22.json"
)
EXECUTION_FAILURE_SHA256 = (
    "7b9b7a145e6e7097bf0fc4330e2998c29725222b9584481f4b135b3a924dd7c8"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.13.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.12 AI provenance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    _bound(EXECUTION_FAILURE, EXECUTION_FAILURE_SHA256, "AI failure receipt drift")
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "effective_at": "2026-08-22T19:57:00+08:00",
            "supersedes": {
                "path": PREVIOUS.relative_to(ROOT).as_posix(),
                "sha256": PREVIOUS_SHA256,
            },
            "authority_policy": {
                "path": AUTHORITY_POLICY.relative_to(ROOT).as_posix(),
                "sha256": AUTHORITY_POLICY_SHA256,
                "key_id": "ed25519-sha256-3587bd4a2fb4d5c65f59e2a9b7e5127afe5f4ddd1792966fd37497e2e25c855d",
                "authority_uid": 998,
                "authority_gid": 998,
            },
            "historical_execution_failure": {
                "path": EXECUTION_FAILURE.relative_to(ROOT).as_posix(),
                "sha256": EXECUTION_FAILURE_SHA256,
                "status": "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT",
                "remediated_reason_code": (
                    "DUPLICATE_KNOWN_MODEL_REFRESH_STDERR_DIAGNOSTIC"
                ),
            },
        }
    )
    import_policy = dict(value["import_policy"])
    import_policy["stderr_allowlist"] = (
        "EMPTY_OR_ONE_EXACT_ASCII_TIMESTAMPED_DIAGNOSTIC_WITH_ONE_LF"
    )
    import_policy["duplicate_or_noncanonical_stderr_action"] = "REJECT_FAIL_CLOSED"
    value["import_policy"] = import_policy
    required = list(value["required_runtime_attestations"])
    required.append(
        "codex_executable_and_code_mode_host_uid_gid_mode_are_policy_frozen_and_replayed"
    )
    value["required_runtime_attestations"] = required
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.13 strict stderr and executable-owner provenance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
