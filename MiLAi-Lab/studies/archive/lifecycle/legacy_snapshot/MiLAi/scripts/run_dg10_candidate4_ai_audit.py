from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path("/cra/memory/mx_memory/MiLAi")
AUTHORITY_CODE_ROOT = Path(__file__).resolve().parents[1]
if str(AUTHORITY_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTHORITY_CODE_ROOT))

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_remediation as remediation

ROOT = PROJECT_ROOT
DEFAULT_BUNDLE_ROOT = ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r0-r2-review"
DEFAULT_OUTPUT_ROOT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits"
)
FIXED_ROOTS = {
    "R0_R2_PRIMARY": (DEFAULT_BUNDLE_ROOT, DEFAULT_OUTPUT_ROOT),
    "TEST_ACCESS_PRIMARY": (
        ROOT.parent / "evidence/dg10-candidate4-ai-test-access-review",
        ROOT.parent
        / "evidence/dg10-candidate4-xhigh-ai-test-access-authority-audits",
    ),
    "R3_PRIMARY": (
        ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r3-review",
        ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r3-authority-audits",
    ),
}
DEFAULT_TIMEOUT_SECONDS = 900


class AuditRunError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditRunError(reason)


def _write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def run_audit(
    *,
    bundle: Path,
    output_root: Path,
    attempt_id: str,
    timeout_seconds: int,
    scope: str = "R0_R2_PRIMARY",
) -> tuple[Path, int]:
    policy = provenance.load_authority_policy()
    provenance.assert_current_authority_process(
        policy=policy,
        runner_path=Path(__file__),
    )
    _require(
        os.geteuid() == policy["authority_uid"]
        and os.getegid() == policy["authority_gid"],
        "AI audit runner requires the separately protected authority identity",
    )
    bundle = bundle.resolve()
    _require(bundle.is_dir() and not bundle.is_symlink(), "AI review bundle is absent or unsafe")
    prompt_path = bundle / "audit-prompt.md"
    schema_path = bundle / "audit-response.schema.json"
    manifest_path = bundle / "review-manifest.json"
    for path in (prompt_path, schema_path, manifest_path):
        _require(
            path.is_file()
            and not path.is_symlink()
            and stat.S_IMODE(path.stat().st_mode) == 0o444,
            "AI review control file is absent or not read-only",
        )
    _require(
        all(
            stat.S_IMODE(path.stat().st_mode) == (0o555 if path.is_dir() else 0o444)
            for path in [bundle, *bundle.rglob("*")]
        ),
        "AI review bundle mode drift",
    )
    _require(
        attempt_id.startswith("candidate.4-")
        and attempt_id.replace("-", "").replace(".", "").isalnum(),
        "AI audit attempt ID invalid",
    )
    _require(scope in FIXED_ROOTS, "AI audit scope invalid")
    _require(
        isinstance(timeout_seconds, int)
        and not isinstance(timeout_seconds, bool)
        and 60 <= timeout_seconds <= 3600,
        "AI audit timeout is outside the fixed safe range",
    )
    output_root = output_root.resolve()
    expected_output_root = Path(policy["protected_attempt_roots"][scope]).resolve()
    _require(output_root == expected_output_root, "AI audit attempt-root substitution")
    _require(
        output_root.is_dir()
        and not output_root.is_symlink()
        and not remediation.has_symlink_component(output_root)
        and output_root.stat().st_uid == policy["authority_uid"]
        and output_root.stat().st_gid == policy["authority_gid"]
        and stat.S_IMODE(output_root.stat().st_mode) == 0o700,
        "AI audit attempt root is not owned by the protected authority",
    )
    attempt = output_root / attempt_id
    attempt.mkdir(mode=0o700)
    output = attempt / "review-output.json"
    codex = provenance.pinned_codex()
    command = provenance.build_command(codex=codex, bundle=bundle, output=output)
    version = subprocess.run(
        [str(codex), "--version"],
        check=False,
        capture_output=True,
        timeout=30,
        env=provenance.codex_child_environment(policy=policy),
    )
    _require(version.returncode == 0 and version.stdout, "Codex CLI identity unavailable")
    termination_reason = "COMPLETED"
    runtime_observations: dict[str, object] | None = None
    try:
        stdout, stderr, returncode, runtime_observations = (
            provenance.execute_pinned_codex(
                command=command,
                prompt=prompt_path.read_bytes(),
                timeout_seconds=timeout_seconds,
                runner_path=Path(__file__),
            )
        )
    except subprocess.TimeoutExpired as exc:
        termination_reason = "TIMEOUT"
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        captured_stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        stderr = captured_stderr + b"\nAI_AUDIT_TIMEOUT_FAIL_CLOSED\n"
        returncode = 124
    except KeyboardInterrupt:
        termination_reason = "OPERATOR_INTERRUPTED"
        stdout = b""
        stderr = b"AI_AUDIT_OPERATOR_INTERRUPTED_FAIL_CLOSED\n"
        returncode = 130
    _write_new(attempt / "events.jsonl", stdout)
    _write_new(attempt / "stderr.log", stderr)
    if output.exists():
        output.chmod(0o600)
    process_claims = {
        "schema": "milai.dg10.ai-audit-process.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": attempt_id,
        "scope": scope,
        "audit_role": "PRIMARY",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "cli_version": version.stdout.decode(errors="replace").strip(),
        "process_exit_code": returncode,
        "termination_reason": termination_reason,
        "timeout_seconds": timeout_seconds,
        "bundle_directory_id": bundle.name,
        "prompt_sha256": remediation.sha256_file(prompt_path),
        "response_schema_sha256": remediation.sha256_file(schema_path),
        "events_sha256": remediation.sha256_file(attempt / "events.jsonl"),
        "stderr_sha256": remediation.sha256_file(attempt / "stderr.log"),
        "output_sha256": remediation.sha256_file(output) if output.is_file() else None,
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_rules": True,
    }
    execution_attestation = (
        provenance.sign_execution_attestation(
            process_claims=process_claims,
            runtime_observations=runtime_observations,
        )
        if runtime_observations is not None and output.is_file()
        else None
    )
    metadata = {
        **process_claims,
        "execution_attestation": execution_attestation,
    }
    remediation.atomic_write_new(attempt / "process.json", remediation.encoded_json(metadata))
    return attempt, returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a candidate.4 primary Sol/xhigh AI audit")
    parser.add_argument(
        "--scope", choices=tuple(FIXED_ROOTS), default="R0_R2_PRIMARY"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS
    )
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    bundle_root, output_root = FIXED_ROOTS[args.scope]
    _require(
        bundle.parent == bundle_root.resolve(),
        "AI audit CLI requires the fixed scope review root",
    )
    attempt, returncode = run_audit(
        bundle=bundle,
        output_root=output_root,
        attempt_id=args.attempt_id,
        timeout_seconds=args.timeout_seconds,
        scope=args.scope,
    )
    print(json.dumps({"attempt": str(attempt), "process_exit_code": returncode}, sort_keys=True))
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
