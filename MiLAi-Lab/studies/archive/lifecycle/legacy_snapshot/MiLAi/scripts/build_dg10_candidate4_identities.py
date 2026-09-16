from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

DEFAULT_SOURCE_INVENTORY = ROOT / (
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.21-2026-08-22.json"
)
DEFAULT_ENVIRONMENT_IDENTITY = ROOT / (
    "docs/reports/DG-10-environment-identity-candidate.4.21-2026-08-22.json"
)
DEFAULT_MODEL_IDENTITY = ROOT / (
    "docs/reports/DG-10-model-identity-candidate.4.21-2026-08-22.json"
)
DEFAULT_AUTHORIZATION_IDENTITIES = ROOT / (
    "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json"
)
DEFAULT_CLOSURE_REPORT = ROOT / (
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.28-2026-08-22.json"
)
DEFAULT_MODEL_PROBE = ROOT / (
    "docs/reports/DG-10-model-probe-candidate.4-2026-08-22.json"
)


class CandidateIdentityError(remediation.RemediationError):
    pass


def _safe_files(root: Path, pattern: str) -> list[Path]:
    return [
        path
        for path in root.glob(pattern)
        if path.is_file()
        and not path.is_symlink()
        and not any(
            part in {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
            for part in path.parts
        )
    ]


def source_paths() -> list[Path]:
    paths: list[Path] = [
        remediation.GOALS,
        ROOT / "AGENTS.md",
        ROOT / "codex_sol_max.md",
        ROOT / "codex_sol_xhigh.md",
        ROOT / "MiLAi_Lean_V1_实施合同.md",
        ROOT / "MiLAi_Logical_Architecture_v1_设计文档.md",
        ROOT / "docs/reviews/DG-10-r0-r2-ai-blind-semantic-audit-receipt-candidate.3-2026-08-22.json",
        ROOT / "evals/dg10/.python-version",
        ROOT / "evals/dg10/pyproject.toml",
        ROOT / "evals/dg10/uv.lock",
        ROOT / "evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl",
        ROOT / "runtime/.python-version",
        ROOT / "runtime/README.md",
        ROOT / "runtime/alembic.ini",
        ROOT / "runtime/compose.yaml",
        ROOT / "runtime/pyproject.toml",
        ROOT / "runtime/uv.lock",
    ]
    patterns = (
        "scripts/*.py",
        "tests/*.py",
        "architecture/v1.0/**/*",
        "integrations/**/*.py",
        "integrations/*/.python-version",
        "integrations/*/pyproject.toml",
        "integrations/*/uv.lock",
        "integrations/openworker-mcp/README.md",
        "integrations/openworker-mcp/**/*.json",
        "integrations/openworker-mcp/**/*.sh",
        "integrations/openworker-mcp/**/Dockerfile",
        "evals/agent_efficiency/*.py",
        "evals/agent_efficiency/*.json",
        "evals/agent_efficiency/*.md",
        "evals/agent_integration/**/*.py",
        "runtime/src/**/*",
        "runtime/migrations/**/*.py",
        "runtime/migrations/script.py.mako",
        "runtime/tests/**/*.py",
        "runtime/docker/**/*",
        "docs/contracts/*",
    )
    for pattern in patterns:
        paths.extend(_safe_files(ROOT, pattern))
    allowed_contract_suffixes = {".json", ".yaml", ".yml", ".md"}
    paths = [
        path
        for path in paths
        if path.is_file()
        and "wheelhouse" not in path.parts
        and "dist" not in path.parts
        and (
            "docs/contracts" not in path.parts
            or path.suffix in allowed_contract_suffixes
        )
    ]
    return sorted(set(paths))


def build_source_inventory() -> dict[str, object]:
    inventory = remediation.canonical_inventory(source_paths())
    return {
        "schema": "milai.dg10.candidate-source-inventory.v1",
        "candidate_id": remediation.CANDIDATE,
        **inventory,
    }


def _reference(path: Path) -> dict[str, str]:
    lexical = path.absolute()
    if (
        not lexical.is_relative_to(ROOT.absolute())
        or remediation.has_symlink_component(lexical)
        or not lexical.is_file()
    ):
        raise CandidateIdentityError(f"identity evidence is missing or unsafe: {lexical}")
    return {
        "path": lexical.relative_to(ROOT.absolute()).as_posix(),
        "sha256": remediation.sha256_file(lexical),
    }


def _identity(schema: str, evidence_paths: list[Path]) -> dict[str, object]:
    evidence = [_reference(path) for path in evidence_paths]
    if not evidence:
        raise CandidateIdentityError("identity evidence is empty")
    return {
        "schema": schema,
        "candidate_id": remediation.CANDIDATE,
        "identity_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"evidence": evidence})
        ),
        "evidence": evidence,
    }


def build_environment_identity(*, closure_report: Path) -> dict[str, object]:
    return _identity(
        "milai.dg10.environment-identity.v1",
        [
            ROOT / "evals/dg10/.python-version",
            ROOT / "evals/dg10/pyproject.toml",
            ROOT / "evals/dg10/uv.lock",
            ROOT / "evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl",
            closure_report,
        ],
    )


def build_model_identity(*, model_probe: Path) -> dict[str, object]:
    return _identity("milai.dg10.model-identity.v1", [model_probe])


def build_authorization_identities(
    *, source_inventory: Path, environment_identity: Path, model_identity: Path
) -> dict[str, object]:
    return {
        "schema": "milai.dg10.authorization-identities.v1",
        "candidate_id": remediation.CANDIDATE,
        "source_inventory": _reference(source_inventory),
        "environment_identity": _reference(environment_identity),
        "model_identity": _reference(model_identity),
        "policy_override": _reference(remediation.AI_POLICY_OVERRIDE),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate.4 bound identities")
    parser.add_argument("--source-inventory", type=Path, default=DEFAULT_SOURCE_INVENTORY)
    parser.add_argument("--environment-identity", type=Path, default=DEFAULT_ENVIRONMENT_IDENTITY)
    parser.add_argument("--model-identity", type=Path, default=DEFAULT_MODEL_IDENTITY)
    parser.add_argument("--authorization-identities", type=Path, default=DEFAULT_AUTHORIZATION_IDENTITIES)
    parser.add_argument("--closure-report", type=Path, default=DEFAULT_CLOSURE_REPORT)
    parser.add_argument("--model-probe", type=Path, default=DEFAULT_MODEL_PROBE)
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--skip-source-inventory", action="store_true")
    args = parser.parse_args()
    if args.source_only and args.skip_source_inventory:
        parser.error("--source-only and --skip-source-inventory are mutually exclusive")
    source_inventory = args.source_inventory.absolute()
    if args.skip_source_inventory:
        if (
            not source_inventory.is_file()
            or remediation.has_symlink_component(source_inventory)
        ):
            raise CandidateIdentityError("active source inventory is absent or unsafe")
    else:
        remediation.atomic_write_new(
            source_inventory, remediation.encoded_json(build_source_inventory())
        )
    if args.source_only:
        print(json.dumps({"source_inventory": str(source_inventory)}, sort_keys=True))
        return
    environment_identity = args.environment_identity.absolute()
    model_identity = args.model_identity.absolute()
    remediation.atomic_write_new(
        environment_identity,
        remediation.encoded_json(
            build_environment_identity(closure_report=args.closure_report.absolute())
        ),
    )
    remediation.atomic_write_new(
        model_identity,
        remediation.encoded_json(build_model_identity(model_probe=args.model_probe.absolute())),
    )
    authorization_identities = args.authorization_identities.absolute()
    remediation.atomic_write_new(
        authorization_identities,
        remediation.encoded_json(
            build_authorization_identities(
                source_inventory=source_inventory,
                environment_identity=environment_identity,
                model_identity=model_identity,
            )
        ),
    )
    print(
        json.dumps(
            {
                "source_inventory": str(source_inventory),
                "environment_identity": str(environment_identity),
                "model_identity": str(model_identity),
                "authorization_identities": str(authorization_identities),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
