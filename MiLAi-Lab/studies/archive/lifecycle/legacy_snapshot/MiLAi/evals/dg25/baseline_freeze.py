"""DG-25 S0 predecessor, denominator, source, and authorization freeze."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.dg25.artifacts import canonical_sha256, file_identity, sha256_file

CASE_ORDER = (
    "gpt4_8279ba03",
    "9a707b82",
    "2a1811e2",
    "0bb5a684",
    "2e6d26dc",
    "4dfccbf7",
    "gpt4_88806d6e",
    "a89d7624",
    "a82c026e",
    "88432d0a",
)

BOUND_ARTIFACTS = {
    "architecture/v1.0/architecture_manifest.json": "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e",
    "MiLAi_Lean_V1_实施合同.md": "395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba",
    "MiLAi_DG-24_检索首损点审计与候选生命周期归因_GOALS.md": "ba3b136c3e510f7829d50af7d50c7aef5de86b04c31e82507c6f647db5347d27",
    "var/dg24/s8/dg24-s8-terminal-20260829-003/receipt.json": "fff0f5ce8ab7b230c49923308f37c080d1eab58776d298a075cda513790a6aa0",
    "var/dg24/s6/dg24-s6-scoring-20260829-003/first-loss-distribution.json": "a782ff232707cc909db679bf1bd68135b547bcb1d997cc0f3c3ac0ca07d4d128",
    "var/dg24/s6/dg24-s6-scoring-20260829-003/requirement-loss-attributions.json": "d62448bc7ca22034a117abdf881fee56b7f2c5eeee34a19a7bfbb2b1fb1d40eb",
    "var/dg24/s6/dg24-s6-scoring-20260829-003/proof-obligation-traces.json": "83fed146a0f0cb4963fb184a1c7cc7c538f89396135d5c7fadeb2c7efa72575c",
    "var/dg24/s6/dg24-s6-scoring-20260829-003/channel-availability-report.json": "83785ff4a25194eabc1f32edfb50cfe7bb07e8490d58621035904ec80defa529",
    "var/dg24/s6/dg24-s6-scoring-20260829-003/successor-routing-report.json": "543685a2ae072a786ceac70b92a9f2b5f1915cd928e8f8473cff7458a0f8d2d5",
    "var/dg24/s6/dg24-s6-scoring-20260829-003/rule-feature-attribution-report.json": "d88381767e832d503d546618411ad537a799ef6cc7a4badff44fd54b5c3c2e53",
    "var/dg24/s0/dg24-s0-freeze-20260829-008/stage-implementation-registry-v0.1.json": "d8b51869b657ff4dc3bcdbb70fe9e35aaf110dc39c7ff25df6c09e146817a934",
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/gold-equivalence-registry-v0.1.json": "c13789936296695027191f3c625c99e49e5725db189fd53791d207879226493a",
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/proof-obligation-registry-v0.1.json": "a2e40b175c33ebc453253e1596f680285c33e13e6b8141cd6a0d5be6158ba26a",
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-product-traces.json": "463e1dae44e8f9239f037f9e5525fc168a4b7f161fe3c54125de49e4266f300d",
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-official-probe-traces.json": "b10805d13cb7ace90a035050b4a32d17842a818e8dbc14e157055e572c2100e0",
    "var/dg23/s9/dg23-s9-terminal-20260829-001/receipt.json": "fa1a71b1c724c0632ca3edea04a6a331821a554cd8bb0e79f41e863e002020f2",
    "var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/context-score.json": "ba641d024c81a9e502c3b3ab7a13b6719bf5b2bb1fe891e6700ec6808d290ee0",
    "var/dg23/s7/dg23-s7-matched-reader-20260829-002/answer-score.json": "9e4a42b072dea1133f9714ead53987bf7c9156da549efae41161f9e2305835d4",
    "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json": "4a88cb030e67cce456b1dfe159fce177a5ace4b972f11af2a6674639c52dc876",
    "var/dg11/paper/freeze/longmemeval-full-inputs.json": "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412",
}

RUNTIME_SOURCE_IDENTITIES = {
    "runtime/src/milai/application/accuracy_acquisition.py": "ddd6a05ae168c62f1e309c4e1de684c063f30514e66ec4d9eeaeed755932947e",
    "runtime/src/milai/application/deterministic_recovery.py": "9b62d078d30eb1ff08e0c7ccd24e1f525d4584c7530395d4c80d88a815bdf334",
    "runtime/src/milai/application/acquisition_capability.py": "3cccfec3f3d4877cadf6859ef0d6a0794ed4d2101013b884555f66bb0a563568",
    "runtime/src/milai/application/acquisition_execution_policy.py": "c3708f0777925c2175e7c3505159e90c2b1ab7244e92043e9557ea495cae08db",
    "runtime/src/milai/application/evidence_acquisition.py": "6909326e1bf2f0236127fddf43484d75b1ccca77c52498b4263b1e6a6cca5b6a",
    "runtime/src/milai/application/acquisition.py": "b01d2729f6f19032a6077ab5a552058ba2c729e6933e515c0c11e1744f5bd19d",
    "runtime/src/milai/application/memory_query.py": "8307d22e830bf9bfffcb1db51fe51d8e13b2a2898ee7192bbf97e814286135ba",
    "runtime/src/milai/application/query_planner.py": "1f4abb484ae0012a7648eec0d9699ed233f863ad989b787e7a7a656cad7a28a6",
    "runtime/src/milai/application/appointment_composition.py": "3e57c2b528dff2da9c5ee25ae3d884d2e7987c75fc4e2b3a6122b02a2638d323",
    "runtime/src/milai/application/evidence_semantics.py": "888bfa3f161f455930909f0ddb2c489655f4b08bb5106f8a4cba56665a4d2cef",
    "runtime/src/milai/application/requirement_state.py": "de7c5ae47c1d28b0f3f978f1e0897237c3e73009a91997e09b59bd1b4d75fe1a",
    "runtime/src/milai/application/sufficiency.py": "fc8d54a76e2c9303a8c7cc09a57095c01732ca632fefc2d8fe9ddaedcc115dda",
    "runtime/src/milai/application/query_operators.py": "592fac4614aa906f760ce372caec99697571a37ebb0ad80df9107469ffd60ba4",
    "runtime/src/milai/application/retrieval.py": "ae9baf98a46e67d56f5f7d13a8cec3eeaed041e89ef88e586c2989a7d925218a",
    "runtime/src/milai/persistence/retrieval_repository.py": "9c158681ea5ac06e7101b276dbe6467ccba2edc141332ae74af2340445c8575a",
}

GOLD_REGISTRY = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)
PROOF_REGISTRY = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "proof-obligation-registry-v0.1.json"
)
PROOF_TRACES = Path(
    "var/dg24/s6/dg24-s6-scoring-20260829-003/proof-obligation-traces.json"
)
PRODUCT_TRACES = Path(
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-product-traces.json"
)

PRE_DG25_WORKTREE = {
    "captured_at": "2026-08-29T22:07:11+08:00",
    "head": "651099ba8cffc2675961bb9250ba44c158efccb5",
    "tracked_file_count": 6,
    "status_porcelain_z_sha256": "b072e0caac7511589ff7b37beaa3a0389c9353948a40ebdf5586c3fe357a853b",
    "status_entry_count": 551,
    "status_counts": {"tracked_modified": 2, "untracked": 549},
    "protected_diffs": {
        "scripts/dg13u_u1_review.py": "5469b6ac14898ca55d92489f47ec4868893b40060912f06ed24d6ae5360ee476",
        "tests/test_dg13u_u1_review.py": "588b98756db645a5ee93090245e6e510945145bfd86ec235074b44717929e4cd",
    },
}


class DG25BaselineError(RuntimeError):
    """A predecessor or S0 boundary is malformed."""


def build_baseline_freeze(
    root: Path,
    *,
    review_receipt: Path | None = None,
    owner_waiver: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if review_receipt is not None and owner_waiver is not None:
        raise DG25BaselineError("review receipt and owner waiver are mutually exclusive")

    bound = _bound_identities(root, BOUND_ARTIFACTS)
    runtime_sources = _bound_identities(root, RUNTIME_SOURCE_IDENTITIES)
    dg24_terminal = _read_object(
        root / "var/dg24/s8/dg24-s8-terminal-20260829-003/receipt.json"
    )
    dg23_terminal = _read_object(
        root / "var/dg23/s9/dg23-s9-terminal-20260829-001/receipt.json"
    )
    dg23_context = _read_object(
        root / "var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/context-score.json"
    )
    dg23_answer = _read_object(
        root / "var/dg23/s7/dg23-s7-matched-reader-20260829-002/answer-score.json"
    )
    product = _read_object(root / PRODUCT_TRACES)
    gold = _read_object(root / GOLD_REGISTRY)
    proof_registry = _read_object(root / PROOF_REGISTRY)
    proof_traces = _read_array(root / PROOF_TRACES)

    case_order = tuple(str(row.get("case_id")) for row in _object_list(product, "records"))
    evidence_groups = [
        group
        for query in _object_list(gold, "queries")
        for requirement in _object_list(query, "requirements")
        for role in _object_list(requirement, "evidence_roles")
        for group in _object_list(role, "equivalence_groups")
    ]
    proof_obligations = [
        obligation
        for query in _object_list(proof_registry, "queries")
        for requirement in _object_list(query, "requirements")
        for obligation in _object_list(requirement, "obligations")
    ]
    proof_dispositions = Counter(str(row.get("disposition")) for row in proof_traces)
    first_loss = _read_object(
        root / "var/dg24/s6/dg24-s6-scoring-20260829-003/first-loss-distribution.json"
    )
    context_metrics = _mapping(dg23_context.get("metrics"), "DG23 context metrics")
    candidate_answers = _mapping(
        _mapping(dg23_answer.get("summaries"), "DG23 summaries").get(
            "B_DG23_BUDGET_INVARIANT_CONTEXT"
        ),
        "DG23 candidate answer summary",
    )
    reference_answers = _mapping(
        candidate_answers.get("REFERENCE_B_REF"), "DG23 REFERENCE_B_REF summary"
    )
    answer_em = [
        int(_mapping(reference_answers.get(str(index)), "replicate")["exact_match_count"])
        for index in range(3)
    ]
    answer_f1 = [
        float(_mapping(reference_answers.get(str(index)), "replicate")["normalized_f1"])
        for index in range(3)
    ]
    review_gate = _review_gate(root, review_receipt=review_receipt, owner_waiver=owner_waiver)
    forbidden_findings = _runtime_case_id_findings(root)
    protected_diff_checks = _protected_diff_checks(root)

    technical_checks = {
        "bound_artifacts_match_20_of_20": len(bound) == 20
        and all(item["matches_expected"] for item in bound.values()),
        "runtime_sources_match_15_of_15": len(runtime_sources) == 15
        and all(item["matches_expected"] for item in runtime_sources.values()),
        "dg24_terminal_exact": dg24_terminal.get("status")
        == "PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED",
        "dg23_terminal_exact": dg23_terminal.get("overall_disposition")
        == "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
        "case_order_10_exact": case_order == CASE_ORDER,
        "evidence_group_denominator_23": len(evidence_groups) == 23,
        "proof_obligation_denominator_37": len(proof_obligations) == 37
        and len(proof_traces) == 37,
        "proof_baseline_35_satisfied_2_failed": proof_dispositions
        == Counter({"SATISFIED": 35, "VALIDATION_FAILED": 2}),
        "first_loss_distribution_exact": first_loss.get("counts")
        == {
            "TERMINAL_SURVIVAL": 13,
            "CHANNEL_ELIGIBLE_NOT_INVOKED": 6,
            "CHANNEL_CUTOFF_DROP": 1,
            "NO_CHANNEL_RETRIEVED_GOLD": 3,
        },
        "dg23_mediator_baseline_exact": context_metrics.get(
            "required_evidence_coverage_reference"
        )
        == 22
        and context_metrics.get("accepted_binding_precision") == 1
        and context_metrics.get("additional_acquisition_calls") == 4
        and context_metrics.get("candidates_hydrated") == 18
        and context_metrics.get("useful_candidate_rate") == 1
        and context_metrics.get("wrong_complete") == 0,
        "dg23_answer_baseline_exact": answer_em == [4, 4, 4]
        and answer_f1 == [0.474263765, 0.470909091, 0.478605605],
        "candidate_default_false": dg24_terminal.get("safety", {}).get(
            "candidate_default"
        )
        is False,
        "formal_holdout_untouched": dg24_terminal.get("safety", {}).get(
            "formal_holdout_consumed"
        )
        is False
        and product.get("formal_holdout_consumed") is False,
        "canonical_mutation_zero": dg24_terminal.get("safety", {}).get(
            "canonical_mutations"
        )
        == 0,
        "runtime_case_id_findings_zero": forbidden_findings == [],
        "protected_user_diffs_unchanged": all(protected_diff_checks.values()),
        "treatment_executed_zero": dg24_terminal.get("result_summary", {}).get(
            "treatment_executed"
        )
        is False,
    }
    review_passed = review_gate["passed"] is True
    all_checks = {**technical_checks, "ablation_review_or_owner_waiver": review_passed}
    technical_passed = all(technical_checks.values())
    stage_passed = technical_passed and review_passed
    if stage_passed:
        status = "PASS_DG25_S0_BASELINE_DENOMINATOR_REVIEW_FREEZE"
    elif technical_passed and review_gate["status"] == "PENDING":
        status = "PENDING_INDEPENDENT_ABLATION_REVIEW_OR_OWNER_WAIVER"
    else:
        status = "FAIL_DG25_S0_BASELINE_DENOMINATOR_REVIEW_FREEZE"

    return {
        "schema": "milai.dg25.s0-baseline-freeze.v0.1",
        "status": status,
        "bound_artifacts": bound,
        "runtime_source_baseline": runtime_sources,
        "denominators": {
            "case_count": len(case_order),
            "case_order": list(case_order),
            "evidence_group_count": len(evidence_groups),
            "evidence_group_ids_digest": canonical_sha256(
                sorted(str(group.get("equivalence_group_id")) for group in evidence_groups)
            ),
            "proof_obligation_count": len(proof_obligations),
            "proof_obligation_ids_digest": canonical_sha256(
                sorted(str(item.get("obligation_id")) for item in proof_obligations)
            ),
            "proof_baseline_dispositions": dict(sorted(proof_dispositions.items())),
            "reader_replicate_indices": [0, 1, 2],
        },
        "predecessor_baselines": {
            "dg24_terminal": dg24_terminal["status"],
            "dg24_first_loss_distribution": first_loss["counts"],
            "dg23_terminal": dg23_terminal["overall_disposition"],
            "dg23_mediator": {
                "required_evidence_coverage_reference": context_metrics[
                    "required_evidence_coverage_reference"
                ],
                "accepted_binding_precision": context_metrics[
                    "accepted_binding_precision"
                ],
                "additional_acquisition_calls": context_metrics[
                    "additional_acquisition_calls"
                ],
                "candidates_hydrated": context_metrics["candidates_hydrated"],
                "useful_candidate_rate": context_metrics["useful_candidate_rate"],
                "wrong_complete": context_metrics["wrong_complete"],
            },
            "dg23_reader_reference_b_ref": {"em": answer_em, "normalized_f1": answer_f1},
        },
        "review_gate": review_gate,
        "preexisting_worktree": {
            **PRE_DG25_WORKTREE,
            "protected_diff_checks": protected_diff_checks,
        },
        "forbidden_runtime_findings": forbidden_findings,
        "label_boundary": {
            "product_input_is_label_free": True,
            "scorer_registries_read_for_denominator_only": True,
            "treatment_executed": False,
            "formal_holdout_consumed": False,
        },
        "safety": {
            "candidate_default": False,
            "formal_holdout_consumed": False,
            "canonical_mutations": 0,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
            "reader_calls": 0,
            "planner_controller_residual_provider_calls": 0,
            "automatic_retries": 0,
        },
        "hard_gate": {
            "technical_passed": technical_passed,
            "review_passed": review_passed,
            "passed": stage_passed,
            "checks": all_checks,
        },
    }


def build_source_config_index_snapshot_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    sources = [
        file_identity(root, root / relative)
        for relative in sorted(RUNTIME_SOURCE_IDENTITIES)
    ]
    boundaries = {
        "architecture_v1": _tree_identity(root, root / "architecture/v1.0"),
        "public_mcp_contracts": _tree_identity(root, root / "contracts/agent/v1"),
        "postgresql_migrations": _tree_identity(root, root / "runtime/migrations"),
    }
    snapshots = [
        file_identity(root, root / PRODUCT_TRACES),
        file_identity(
            root,
            root
            / "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
            "sealed-official-probe-traces.json",
        ),
        file_identity(
            root,
            root / "var/dg11/paper/freeze/longmemeval-full-inputs.json",
        ),
    ]
    return {
        "schema": "milai.dg25.s0-source-config-index-snapshot-manifest.v0.1",
        "runtime_sources": sources,
        "runtime_source_manifest_digest": canonical_sha256(sources),
        "boundary_tree_identities": boundaries,
        "snapshot_and_index_trace_identities": snapshots,
        "candidate_default": False,
        "formal_holdout_consumed": False,
    }


def _bound_identities(
    root: Path, expected: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    return {
        relative: {
            **file_identity(root, root / relative),
            "expected_sha256": digest,
            "matches_expected": sha256_file(root / relative) == digest,
        }
        for relative, digest in expected.items()
    }


def _review_gate(
    root: Path,
    *,
    review_receipt: Path | None,
    owner_waiver: Path | None,
) -> dict[str, Any]:
    selected = review_receipt or owner_waiver
    if selected is None:
        return {
            "status": "PENDING",
            "passed": False,
            "reason": "INDEPENDENT_REVIEW_OR_EXPLICIT_OWNER_WAIVER_REQUIRED_BEFORE_S2",
            "artifact": None,
        }
    path = selected if selected.is_absolute() else root / selected
    payload = _read_object(path)
    if review_receipt is not None:
        passed = (
            payload.get("schema") == "milai.dg25.ablation-independent-review.v0.1"
            and payload.get("reviewer_is_independent") is True
            and payload.get("disposition") == "ACCEPT"
            and payload.get("reviewed_blocks") == ["E1", "E2"]
        )
        kind = "INDEPENDENT_REVIEW"
    else:
        scopes = payload.get("waived_requirements")
        passed = (
            payload.get("schema") == "milai.dg25.owner-review-waiver.v0.1"
            and payload.get("owner_authorized") is True
            and isinstance(scopes, list)
            and "INDEPENDENT_ABLATION_REVIEW_BEFORE_S2" in scopes
        )
        kind = "OWNER_WAIVER"
    return {
        "status": "ACCEPTED" if passed else "REJECTED",
        "passed": passed,
        "kind": kind,
        "artifact": file_identity(root, path),
    }


def _runtime_case_id_findings(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for relative in sorted(RUNTIME_SOURCE_IDENTITIES):
        text = (root / relative).read_text(encoding="utf-8")
        for case_id in CASE_ORDER:
            if case_id in text:
                findings.append({"path": relative, "case_id": case_id})
    return findings


def _protected_diff_checks(root: Path) -> dict[str, bool]:
    executable = shutil.which("git")
    if executable is None:
        raise DG25BaselineError("git executable is required for worktree provenance")
    checks: dict[str, bool] = {}
    protected_diffs = PRE_DG25_WORKTREE["protected_diffs"]
    if not isinstance(protected_diffs, Mapping):
        raise DG25BaselineError("protected worktree diff registry is malformed")
    for relative, expected in protected_diffs.items():
        completed = subprocess.run(
            [executable, "diff", "--", str(relative)],
            cwd=root,
            check=True,
            capture_output=True,
        )
        checks[str(relative)] = (
            hashlib.sha256(completed.stdout).hexdigest() == expected
        )
    return checks


def _tree_identity(root: Path, directory: Path) -> dict[str, Any]:
    files = [
        file_identity(root, path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return {
        "path": directory.resolve().relative_to(root).as_posix(),
        "file_count": len(files),
        "files_digest": canonical_sha256(files),
    }


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG25BaselineError(f"JSON object required: {path}")
    return value


def _read_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DG25BaselineError(f"JSON object array required: {path}")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG25BaselineError(f"mapping required: {name}")
    return value


def _object_list(value: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise DG25BaselineError(f"object list required: {key}")
    return items
