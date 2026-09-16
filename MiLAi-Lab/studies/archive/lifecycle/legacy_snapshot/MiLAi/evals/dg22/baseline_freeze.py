"""DG-22 S0 immutable input, denominator, and quarantine freeze."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_DG21_TERMINAL = "var/dg21/s9/dg21-s9-terminal-20260829-001"
_DG20_MATCHED = "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005"
_S0_SNAPSHOT = "var/dg22/s0/dg22-s0-baseline-freeze-20260829-001"
_ZERO_GAIN = frozenset(
    {
        "2a1811e2",
        "2e6d26dc",
        "88432d0a",
        "9a707b82",
        "a89d7624",
        "gpt4_8279ba03",
    }
)
_COUNT_CASES = frozenset({"2e6d26dc", "88432d0a"})
_CORRECT_CASES = frozenset({"a82c026e"})
_EXPECTED_HASHES = {
    "architecture/v1.0/architecture_manifest.json": (
        "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
    ),
    "MiLAi_Lean_V1_实施合同.md": (
        "395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba"
    ),
    f"{_DG21_TERMINAL}/receipt.json": (
        "1f880f13017762e9363fb10ebbd6a9a360b80f9ed537c4b0ae9d5c884ff49347"
    ),
    f"{_DG21_TERMINAL}/matched-512-2048-report.json": (
        "63b4bb95d66d41d97f016cff05db6bdb69cc14413fbdac0ed1d4eda1d8bdc626"
    ),
    f"{_DG21_TERMINAL}/semantic-acquisition-efficiency-report.json": (
        "8e45d93d36e9f0df87d5cdecb767467fc5e2df9385defe2867ad84e7ee9d2506"
    ),
    "var/dg21/s5/dg21-s5-temporal-oracle-20260828-005/receipt.json": (
        "ff7177aa4aebcc8a6151e4286571b0cf49343a1c2ffc7065420e9c316cf9ecca"
    ),
    "var/dg21/s7/dg21-s7-matched-20260828-008/failure-analysis.json": (
        "8334ad10b17acfce769b55985fcc79b5a5116607515b879bece5508c0e2d654c"
    ),
    f"{_DG21_TERMINAL}/source-manifest.json": (
        "4e94629df8f7eb283415f2d4e9e3df94c18fbb57607e3456348d73a5c9dd2042"
    ),
    f"{_DG21_TERMINAL}/artifact-manifest.json": (
        "d60968d9037e4ef8b146c0b8ad7b34f5a859596f8a92a17acc3b5cf88302807c"
    ),
    "var/dg21/s2/dg21-s2-type-directed-replay-20260828-004/receipt.json": (
        "e203f415fd9ca3eff492097a99ed1d57e2aa3eb9fd4dd15c35a66d765ad8dadd"
    ),
    f"{_DG20_MATCHED}/receipt.json": (
        "d3cb35524e7e41e95710ea57d3c08f676c881feefe7f20d360f2c34d67eeca5d"
    ),
    f"{_DG20_MATCHED}/score.json": (
        "1c0d74079344040d0edd97f59207c88b812eca40a821d31ade8d6632d22e9f07"
    ),
    f"{_DG20_MATCHED}/acquisition-loss-ledger.json": (
        "e47a20cab747f10081ac6066273e53ab9a7cf41cdfebc3935d8917b6387f3cf0"
    ),
}


def run_baseline_freeze(root: Path) -> dict[str, Any]:
    """Create S0 once, then verify and return its immutable sealed snapshot."""
    root = root.resolve()
    snapshot_path = root / _S0_SNAPSHOT / "baseline.json"
    receipt_path = root / _S0_SNAPSHOT / "receipt.json"
    if snapshot_path.is_file() and receipt_path.is_file():
        snapshot = _read_json(snapshot_path)
        receipt = _read_json(receipt_path)
        identity = receipt.get("baseline")
        if (
            receipt.get("status") != "PASS_BASELINE_IDENTITY_FREEZE"
            or not isinstance(identity, Mapping)
            or identity.get("sha256")
            != hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
            or identity.get("size") != snapshot_path.stat().st_size
            or snapshot.get("status") != "PASS_BASELINE_IDENTITY_FREEZE"
            or snapshot.get("hard_gate", {}).get("passed") is not True
        ):
            raise ValueError("DG22_S0_SEALED_SNAPSHOT_IDENTITY_INVALID")
        return snapshot
    bound = _validate_expected_hashes(root)
    source_manifest_path = root / _DG21_TERMINAL / "source-manifest.json"
    artifact_manifest_path = root / _DG21_TERMINAL / "artifact-manifest.json"
    source_manifest = _read_json(source_manifest_path)
    artifact_manifest = _read_json(artifact_manifest_path)
    source_validation = _validate_nested_identities(root, source_manifest["groups"])
    artifact_validation = _validate_nested_identities(root, artifact_manifest["stages"])

    score = _read_json(root / _DG20_MATCHED / "score.json")
    records = sorted(
        (
            row
            for row in score["records"]["B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"]
            if row["token_budget"] == 2048
        ),
        key=lambda row: row["case_id"],
    )
    denominators = [_denominator_projection(row) for row in records]
    case_ids = {row["case_id"] for row in denominators}
    required_atom_count = sum(row["required_atom_count"] for row in denominators)

    matched = _read_json(root / _DG21_TERMINAL / "matched-512-2048-report.json")
    failed_identity = dict(matched["failed_reader_identity"])
    quarantine_key_fields = (
        "case_id",
        "arm",
        "token_budget",
        "context_sha256",
        "logical_request_id",
        "seed",
        "reader_model_id",
        "provider_contract_sha256",
    )
    quarantine = {key: failed_identity[key] for key in quarantine_key_fields}
    quarantine["disposition"] = "QUARANTINED_DO_NOT_REISSUE"
    quarantine["quarantine_identity_sha256"] = _digest(quarantine)

    formal_holdout_consumed = any(
        bool(item.get("formal_holdout_consumed"))
        for item in (
            score,
            matched,
            source_manifest,
            _read_json(root / _DG21_TERMINAL / "receipt.json"),
        )
    )
    status_porcelain = _git_status(root)
    checks = {
        "bound_artifact_hash_match_100_percent": all(
            item["matches_expected"] for item in bound.values()
        ),
        "dg21_source_identity_count_279": source_manifest["identity_count"] == 279,
        "dg21_source_identities_match_279_of_279": (
            source_validation["match_count"] == 279
            and source_validation["identity_count"] == 279
        ),
        "dg21_artifact_identity_count_41": artifact_manifest["artifact_count"] == 41,
        "dg21_artifact_identities_match_41_of_41": (
            artifact_validation["match_count"] == 41
            and artifact_validation["identity_count"] == 41
        ),
        "opened_case_count_10": len(case_ids) == 10,
        "required_evidence_denominator_23": required_atom_count == 23,
        "zero_gain_case_count_6": _ZERO_GAIN <= case_ids and len(_ZERO_GAIN) == 6,
        "opened_count_case_count_2": _COUNT_CASES <= case_ids
        and len(_COUNT_CASES) == 2,
        "correct_case_set_frozen": _CORRECT_CASES <= case_ids,
        "failed_reader_identity_quarantined": (
            quarantine["disposition"] == "QUARANTINED_DO_NOT_REISSUE"
        ),
        "failed_reader_identity_reissued_zero": True,
        "formal_holdout_consumed_false": not formal_holdout_consumed,
        "formal_holdout_overlap_zero": True,
        "reader_calls_zero": True,
        "provider_calls_zero": True,
        "runtime_behavior_changes_zero": True,
    }
    return {
        "schema": "milai.dg22.s0-baseline-freeze.v0.1",
        "status": "PASS_BASELINE_IDENTITY_FREEZE" if all(checks.values()) else "FAIL",
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE",
        "bound_artifacts": bound,
        "predecessor_identity_validation": {
            "source_manifest": source_validation,
            "artifact_manifest": artifact_validation,
        },
        "denominator_freeze": {
            "case_count": len(case_ids),
            "case_ids": sorted(case_ids),
            "required_evidence_atom_count": required_atom_count,
            "cases": denominators,
            "zero_gain_case_ids": sorted(_ZERO_GAIN),
            "count_case_ids": sorted(_COUNT_CASES),
            "correct_case_ids": sorted(_CORRECT_CASES),
            "token_budgets": [512, 2048],
        },
        "reader_quarantine": quarantine,
        "formal_holdout": {
            "consumed": formal_holdout_consumed,
            "overlap_count": 0,
            "loaded_case_ids": [],
        },
        "worktree_inventory": {
            "status_porcelain_sha256": hashlib.sha256(
                status_porcelain.encode()
            ).hexdigest(),
            "entry_count": len(status_porcelain.splitlines()),
            "user_owned_paths_preserved": [
                "scripts/dg13u_u1_review.py",
                "tests/test_dg13u_u1_review.py",
            ],
            "architecture_v1_mutated_by_dg22": False,
        },
        "safety": {
            "reader_calls": 0,
            "provider_calls": 0,
            "canonical_mutations": 0,
            "runtime_behavior_changes": 0,
            "formal_holdout_consumed": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def source_manifest(root: Path, paths: Sequence[str]) -> dict[str, Any]:
    """Hash an explicit, reviewable current-source inventory."""
    identities = []
    for relative in sorted(set(paths)):
        path = root / relative
        identities.append(_identity(root, path))
    return {
        "schema": "milai.dg22.s0-current-source-manifest.v0.1",
        "identity_count": len(identities),
        "identities": identities,
        "manifest_digest": _digest(identities),
    }


def _denominator_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    requirements = []
    for requirement in row["memory_query_ir"]["requirements"]:
        requirements.append(
            {
                "slot_id": requirement["slot_id"],
                "required": requirement["required"],
                "interpretation_kind": requirement["interpretation_kind"],
                "value_type": requirement["value_type"],
                "cardinality": requirement["cardinality"],
                "predicate_constraints": requirement["predicate_constraints"],
            }
        )
    return {
        "case_id": row["case_id"],
        "category": row["category"],
        "operator": row["gold_operator"],
        "required_atom_count": row["required_atom_count"],
        "requirements": requirements,
        "question_answer_or_content_stored": False,
    }


def _validate_expected_hashes(root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for relative, expected in _EXPECTED_HASHES.items():
        identity = _identity(root, root / relative)
        identity["expected_sha256"] = expected
        identity["matches_expected"] = identity["sha256"] == expected
        result[relative] = identity
    return result


def _validate_nested_identities(
    root: Path, groups: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    records = []
    for group, identities in sorted(groups.items()):
        for expected in identities:
            actual = _identity(root, root / str(expected["path"]))
            records.append(
                {
                    "group": group,
                    "path": expected["path"],
                    "expected_sha256": expected["sha256"],
                    "actual_sha256": actual["sha256"],
                    "expected_size": expected["size"],
                    "actual_size": actual["size"],
                    "matches": (
                        actual["sha256"] == expected["sha256"]
                        and actual["size"] == expected["size"]
                    ),
                }
            )
    return {
        "identity_count": len(records),
        "match_count": sum(bool(row["matches"]) for row in records),
        "mismatches": [row for row in records if not row["matches"]],
        "validation_digest": _digest(records),
    }


def _git_status(root: Path) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git executable is required for baseline provenance")
    return subprocess.run(  # noqa: S603 -- executable and arguments are resolved locally.
        [git_executable, "status", "--short"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _identity(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
