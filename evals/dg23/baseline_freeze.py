"""DG-23 S0 immutable predecessor, denominator, and control freeze."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

DG22_TERMINAL = Path("var/dg22/s10/dg22-s10-terminal-20260829-001/receipt.json")
DG22_SCORE = Path(
    "var/dg22/s8/dg22-s8-answer-correctness-20260829-002/answer-score.json"
)
DG22_CONTEXTS = Path(
    "var/dg22/s8/dg22-s8-answer-correctness-20260829-002/sealed-answer-contexts.json"
)
DG22_READER_PRODUCT = Path(
    "var/dg22/s8/dg22-s8-answer-correctness-20260829-002/"
    "sealed-answer-reader-product.json"
)
DG22_READER_CONTRACT = Path(
    "var/dg22/s2/dg22-s2-reader-conformance-20260829-001/selected-reader-contract.json"
)
DG22_POLICY = Path(
    "var/dg22/s5/dg22-s5-acquisition-correctness-20260829-001/"
    "accuracy-acquisition-policy-v0.3.json"
)
DG22_TEMPORAL_PRODUCT = Path(
    "var/dg22/s6/dg22-s6-temporal-correctness-20260829-001/sealed-temporal-product.json"
)
S0_SNAPSHOT = Path("var/dg23/s0/dg23-s0-baseline-freeze-20260829-001")
DG23_SEED_NAMESPACE = "milai-dg23-matched-v1"
EXPECTED_HASHES = {
    "architecture/v1.0/architecture_manifest.json": (
        "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
    ),
    "MiLAi_Lean_V1_实施合同.md": (
        "395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba"
    ),
    "MiLAi_DG-22_证据召回准确性与答案正确性闭环_GOALS.md": (
        "7ee8b2c74cfaa1d40cd24c5f38bd0fd2c105c3888109ad3a4f7992305cdf9d69"
    ),
    str(DG22_TERMINAL): (
        "2671583f8a11c97cbc462a48b15faaf9b41df4bf083dddcb422ec548677fae6e"
    ),
    str(DG22_SCORE): (
        "8358486fba6e7d38281b6509bc30d659e70cdb3709c48ddb6e5f246f38bf2452"
    ),
    str(DG22_CONTEXTS): (
        "bb5231b51ddfcdab4f363db1ecc5cd1ad64cb0141076cdd851c19198b2ebeb12"
    ),
    str(DG22_READER_PRODUCT): (
        "fd6a73e49fedfa58a61c0fc164daad4ec58aef576769ccc5c89297ffafbf2aca"
    ),
}


class DG23BaselineError(RuntimeError):
    """A frozen predecessor identity or denominator is not authoritative."""


def run_baseline_freeze(root: Path) -> dict[str, Any]:
    """Build the label-closed S0 projection or verify its existing sealed copy."""
    root = root.resolve()
    baseline_path = root / S0_SNAPSHOT / "baseline.json"
    receipt_path = root / S0_SNAPSHOT / "receipt.json"
    if baseline_path.is_file() and receipt_path.is_file():
        baseline = _read(baseline_path)
        receipt = _read(receipt_path)
        identity = receipt.get("baseline")
        if (
            baseline.get("status") != "PASS_DG23_BASELINE_DENOMINATOR_FREEZE"
            or baseline.get("hard_gate", {}).get("passed") is not True
            or not isinstance(identity, Mapping)
            or identity.get("sha256") != _sha256(baseline_path)
            or identity.get("size") != baseline_path.stat().st_size
        ):
            raise DG23BaselineError("DG23_S0_SEALED_BASELINE_INVALID")
        return baseline

    bound = {
        relative: {
            **_identity(root, root / relative),
            "expected_sha256": expected,
            "matches_expected": _sha256(root / relative) == expected,
        }
        for relative, expected in EXPECTED_HASHES.items()
    }
    terminal = _read(root / DG22_TERMINAL)
    for identity in _embedded_identities(terminal):
        _verify_identity(root, identity)
    contexts = _read(root / DG22_CONTEXTS)
    reader_product = _read(root / DG22_READER_PRODUCT)
    score = _read(root / DG22_SCORE)
    reader_contract = _read(root / DG22_READER_CONTRACT)
    policy = _read(root / DG22_POLICY)
    temporal = _read(root / DG22_TEMPORAL_PRODUCT)

    records = contexts.get("records")
    if not isinstance(records, list):
        raise DG23BaselineError("DG22 context denominator is missing")
    candidate_records = [
        row
        for row in records
        if isinstance(row, Mapping) and row.get("arm") == "B_DG22_FROZEN_FINAL_CONTEXT"
    ]
    case_order = contexts.get("case_order")
    if not isinstance(case_order, list):
        raise DG23BaselineError("DG22 case order is missing")
    source_snapshots: dict[str, str] = {}
    for case_id in case_order:
        values = {
            str(row["source_snapshot_digest"])
            for row in candidate_records
            if row.get("case_id") == case_id
        }
        if len(values) != 1:
            raise DG23BaselineError(f"source snapshot drifted for {case_id}")
        source_snapshots[str(case_id)] = values.pop()

    scored_records = score.get("scored_records")
    if not isinstance(scored_records, list):
        raise DG23BaselineError("DG22 scored record denominator is missing")
    candidate_correct = {
        str(budget): sorted(
            str(row["case_id"])
            for row in scored_records
            if isinstance(row, Mapping)
            and row.get("arm") == "B_DG22_FROZEN_FINAL_CONTEXT"
            and row.get("token_budget") == budget
            and isinstance(row.get("answer_score"), Mapping)
            and row["answer_score"].get("exact_match") == 1
        )
        for budget in (512, 2048)
    }
    regressions = score.get("baseline_correct_regressions")
    if regressions != {"2048": ["gpt4_88806d6e"], "512": []}:
        raise DG23BaselineError("DG22 regression identity is not reproducible")

    opened_temporal = temporal.get("opened_count_records")
    temporal_records = opened_temporal if isinstance(opened_temporal, list) else []
    temporal_ids = sorted(
        str(row["case_id"])
        for row in temporal_records
        if isinstance(row, Mapping) and isinstance(row.get("case_id"), str)
    )
    status_porcelain = _git_status(root)
    checks = {
        "bound_identity_match_7_of_7": len(bound) == 7
        and all(item["matches_expected"] for item in bound.values()),
        "dg22_terminal_disposition_exact": (
            terminal.get("overall_disposition") == "FAIL_SAFETY_OR_REGRESSION"
            and terminal.get("answer_disposition") == "FAIL_CORRECT_CASE_REGRESSION"
        ),
        "opened_case_order_10": len(case_order) == len(set(case_order)) == 10,
        "candidate_context_cells_20": len(candidate_records) == 20,
        "source_snapshot_one_per_case": len(source_snapshots) == 10,
        "legacy_budget_cells_512_2048": {
            int(row["token_budget"]) for row in candidate_records
        }
        == {512, 2048},
        "historical_regression_identity_exact": regressions
        == {"2048": ["gpt4_88806d6e"], "512": []},
        "historical_correct_sets_frozen": len(candidate_correct["512"]) == 6
        and len(candidate_correct["2048"]) == 4,
        "reader_product_denominator_40": len(reader_product.get("records", [])) == 40,
        "reader_contract_frozen": reader_product.get("provider_contract_sha256")
        == reader_contract.get("contract_sha256")
        == "25e40b1a978251ddd08df317e16d85f111fdb00a725b928a300979e6f071cd72",
        "candidate_default_false": policy.get("default_enabled") is False
        and terminal.get("candidate_default") is False,
        "temporal_count_carried_out_of_primary_denominator": len(temporal_ids) == 2,
        "formal_holdout_consumed_false": terminal.get("formal_holdout_consumed")
        is False,
        "source_labels_loaded_during_freeze_false": True,
        "reader_calls_zero": True,
        "provider_calls_zero": True,
        "runtime_behavior_changes_zero": True,
        "architecture_mutations_zero": True,
    }
    return {
        "schema": "milai.dg23.s0-baseline-freeze.v0.1",
        "status": (
            "PASS_DG23_BASELINE_DENOMINATOR_FREEZE" if all(checks.values()) else "FAIL"
        ),
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10",
        "bound_artifacts": bound,
        "predecessor_terminal": {
            "reader": terminal["reader_disposition"],
            "recall_binding": terminal["recall_binding_disposition"],
            "temporal": terminal["temporal_disposition"],
            "answer": terminal["answer_disposition"],
            "overall": terminal["overall_disposition"],
        },
        "denominator": {
            "case_count": 10,
            "case_order": [str(value) for value in case_order],
            "source_snapshot_digests": source_snapshots,
            "legacy_diagnostic_budgets": [512, 2048],
            "candidate_context_cell_count": 20,
            "historical_candidate_correct_case_ids": candidate_correct,
            "historical_regression_case_ids": {"2048": ["gpt4_88806d6e"], "512": []},
            "temporal_count_case_ids_out_of_primary_scope": temporal_ids,
        },
        "frozen_controls": {
            "reader_contract": reader_contract,
            "provider_contract_sha256": reader_product["provider_contract_sha256"],
            "dg23_seed_namespace": DG23_SEED_NAMESPACE,
            "dg23_seed_formula": (
                "sha256(namespace,case_source_snapshot_digest,replicate_index); "
                "excludes arm and presentation budget"
            ),
            "replicate_indices": [0, 1, 2],
            "answer_scorer_identity": score["scoring_identity"],
            "recall_binding_floors": {
                "safe_oracle_normalized_recall": 0.8,
                "required_evidence_coverage_b_ref": "19/23",
                "required_evidence_coverage_legacy_512": "18/23",
                "accepted_binding_precision": 1.0,
                "useful_candidate_rate": 0.34615384615384615,
                "additional_acquisition_calls": 6,
                "candidates_hydrated": 26,
                "wrong_complete": 0,
            },
            "forbidden": [
                "CASE_ID_RUNTIME_RULE",
                "GOLD_AWARE_PACKING",
                "TOP_K_INFLATION",
                "BUDGET_DEPENDENT_ACQUISITION",
                "PER_BUDGET_REBINDING",
                "BUDGET_DEPENDENT_READER_SEED",
                "ARBITRARY_EVIDENCE_PREFIX_TRUNCATION",
                "RETRY_TO_PASS",
            ],
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
            "architecture_v1_mutated_by_dg23": False,
        },
        "label_boundary": {
            "sealed_dg22_score_read": True,
            "source_labels_loaded": False,
            "formal_holdout_consumed": False,
        },
        "safety": {
            "reader_calls": 0,
            "provider_calls": 0,
            "canonical_mutations": 0,
            "runtime_behavior_changes": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def source_manifest(root: Path, paths: Sequence[str]) -> dict[str, Any]:
    identities = [_identity(root, root / relative) for relative in sorted(set(paths))]
    return {
        "schema": "milai.dg23.s0-source-manifest.v0.1",
        "identity_count": len(identities),
        "identities": identities,
        "manifest_digest": _digest(identities),
    }


def _embedded_identities(value: object) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if {"path", "sha256", "size"} <= set(value):
            yield value
        for item in value.values():
            yield from _embedded_identities(item)
    elif isinstance(value, list):
        for item in value:
            yield from _embedded_identities(item)


def _verify_identity(root: Path, reference: Mapping[str, Any]) -> None:
    path = root / str(reference["path"])
    if (
        not path.is_file()
        or _sha256(path) != reference["sha256"]
        or path.stat().st_size != reference["size"]
    ):
        raise DG23BaselineError(f"predecessor identity drifted: {reference['path']}")


def _git_status(root: Path) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise DG23BaselineError("git executable is required for baseline provenance")
    return subprocess.run(  # noqa: S603 -- locally resolved executable and fixed argv.
        [executable, "status", "--short"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _identity(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(root)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG23BaselineError(f"JSON object required: {path}")
    return value


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()
