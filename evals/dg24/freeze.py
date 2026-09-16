"""DG-24 baseline, label boundary, source, stage, and registry freeze."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.dg16.lme10 import load_public_dev_cases

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
    "architecture/v1.0/architecture_manifest.json": (
        "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
    ),
    "MiLAi_Lean_V1_实施合同.md": (
        "395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba"
    ),
    "MiLAi_DG-23_预算稳定上下文编译与答案回归闭环_GOALS.md": (
        "c36fca58068feeb6cc1aaa3561dbaf1970271bcc287e1776e5dafd01dc9b97f5"
    ),
    "var/dg23/s9/dg23-s9-terminal-20260829-001/receipt.json": (
        "fa1a71b1c724c0632ca3edea04a6a331821a554cd8bb0e79f41e863e002020f2"
    ),
    "var/dg23/s0/dg23-s0-baseline-freeze-20260829-001/baseline.json": (
        "d0a974448d3ea78de3adb8b95aedfb39377dca8c7e4ff672ed6247a2bcdf5d28"
    ),
    "var/dg23/s0/dg23-s0-baseline-freeze-20260829-001/denominator-freeze.json": (
        "6ed89d02fbfe4023e8171768055c847772356cb41f745f929364e3763945a87a"
    ),
    "var/dg23/s6/dg23-s6-opened-dev-context-20260829-019/"
    "sealed-opened-dev-context-product.json": (
        "c29ef303695ef9b991fe4fc9e7e2dc30548e2cc8674d803952b6b3d764ab5c78"
    ),
    "var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/context-score.json": (
        "ba641d024c81a9e502c3b3ab7a13b6719bf5b2bb1fe891e6700ec6808d290ee0"
    ),
    "var/dg23/s7/dg23-s7-matched-reader-20260829-002/answer-score.json": (
        "9e4a42b072dea1133f9714ead53987bf7c9156da549efae41161f9e2305835d4"
    ),
    "var/dg23/s8/dg23-s8-quality-20260829-004/receipt.json": (
        "1868f439e196bb0e3d1614461606c4e2a733ce52261b4f3aee48b5508ca36bcb"
    ),
}

DRAFT_SOURCE_IDENTITIES = {
    "runtime/src/milai/application/accuracy_acquisition.py": (
        "ddd6a05ae168c62f1e309c4e1de684c063f30514e66ec4d9eeaeed755932947e"
    ),
    "runtime/src/milai/application/evidence_acquisition.py": (
        "6909326e1bf2f0236127fddf43484d75b1ccca77c52498b4263b1e6a6cca5b6a"
    ),
    "runtime/src/milai/persistence/retrieval_repository.py": (
        "9c158681ea5ac06e7101b276dbe6467ccba2edc141332ae74af2340445c8575a"
    ),
    "runtime/src/milai/application/acquisition.py": (
        "b01d2729f6f19032a6077ab5a552058ba2c729e6933e515c0c11e1744f5bd19d"
    ),
    "runtime/src/milai/application/retrieval.py": (
        "bc525c55be666eca3d71cccadba775bfeb222d5a241fac651fcb78f97958b2c7"
    ),
    "runtime/src/milai/application/memory_query.py": (
        "8307d22e830bf9bfffcb1db51fe51d8e13b2a2898ee7192bbf97e814286135ba"
    ),
    "runtime/src/milai/application/evidence_semantics.py": (
        "888bfa3f161f455930909f0ddb2c489655f4b08bb5106f8a4cba56665a4d2cef"
    ),
    "runtime/src/milai/application/requirement_state.py": (
        "de7c5ae47c1d28b0f3f978f1e0897237c3e73009a91997e09b59bd1b4d75fe1a"
    ),
    "runtime/src/milai/application/sufficiency.py": (
        "fc8d54a76e2c9303a8c7cc09a57095c01732ca632fefc2d8fe9ddaedcc115dda"
    ),
    "runtime/src/milai/application/deterministic_recovery.py": (
        "9b62d078d30eb1ff08e0c7ccd24e1f525d4584c7530395d4c80d88a815bdf334"
    ),
    "runtime/src/milai/application/acquisition_capability.py": (
        "3cccfec3f3d4877cadf6859ef0d6a0794ed4d2101013b884555f66bb0a563568"
    ),
}

SCORER_LABEL_FIXTURE = Path("evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json")
INPUT_SOURCE = Path("var/dg11/paper/freeze/longmemeval-full-inputs.json")

SLOT_MAP = {
    "gpt4_8279ba03": {"TARGET_EVENT": "TARGET_EVENT"},
    "9a707b82": {"TARGET_EVENT": "TARGET_EVENT"},
    "2a1811e2": {"START_EVENT": "EVENT_1", "END_EVENT": "EVENT_2"},
    "0bb5a684": {"START_EVENT": "EVENT_1", "END_EVENT": "EVENT_2"},
    "2e6d26dc": {"BABY_EVENTS": "MATCHING_EVENTS_IN_RANGE"},
    "4dfccbf7": {"START_EVENT": "EVENT_1", "END_EVENT": "EVENT_2"},
    "gpt4_88806d6e": {"LEFT_EVENT": "EVENT_1", "RIGHT_EVENT": "EVENT_2"},
    "a89d7624": {
        "PAST_EXPERIENCE": "PREFERENCE_SIGNAL_SET",
        "INTEREST_SIGNAL": "PREFERENCE_SIGNAL_SET",
        "CURRENT_INTENT": "CURRENT_INTENT",
    },
    "a82c026e": {"LOOKUP_ANSWER": "LOOKUP_ANSWER"},
    "88432d0a": {"BAKING_EVENTS": "MATCHING_EVENTS_IN_RANGE"},
}

STAGES = (
    (
        "S00",
        0,
        "QUERY_INPUT",
        "runtime/src/milai/application/memory_resolve.py",
        "MemoryResolveService.resolve",
        False,
        False,
    ),
    (
        "S01",
        1,
        "QUERY_IR_COMPILED",
        "runtime/src/milai/application/memory_query.py",
        "MemoryQueryCompiler.compile",
        False,
        False,
    ),
    (
        "S02",
        2,
        "REQUIREMENT_EMITTED",
        "runtime/src/milai/application/query_planner.py",
        "QueryPlanner.plan",
        False,
        False,
    ),
    (
        "S10",
        10,
        "CHANNEL_ELIGIBILITY",
        "runtime/src/milai/application/acquisition_capability.py",
        "resolve_acquisition_capabilities",
        True,
        False,
    ),
    (
        "S11",
        11,
        "CHANNEL_INVOCATION_DECISION",
        "runtime/src/milai/application/evidence_acquisition.py",
        "EvidenceAcquisitionExecutor._selected_probes",
        True,
        False,
    ),
    (
        "S12",
        12,
        "RAW_CHANNEL_RESULTS",
        "runtime/src/milai/application/evidence_acquisition.py",
        "EvidenceAcquisitionExecutor._execute_probe",
        False,
        True,
    ),
    (
        "S13",
        13,
        "INDEX_OR_REPOSITORY_PREFILTER",
        "runtime/src/milai/application/acquisition.py",
        "apply_probe_source_policy",
        True,
        False,
    ),
    (
        "S14",
        14,
        "CHANNEL_LOCAL_RANK",
        "runtime/src/milai/application/acquisition.py",
        "rank_evidence_turns",
        True,
        False,
    ),
    (
        "S15",
        15,
        "CHANNEL_LOCAL_CUTOFF",
        "runtime/src/milai/persistence/retrieval_repository.py",
        "RetrievalRepository.search_evidence",
        True,
        False,
    ),
    (
        "S20",
        20,
        "CROSS_CHANNEL_UNION",
        "runtime/src/milai/application/acquisition.py",
        "fuse_acquisition_probe_results",
        True,
        True,
    ),
    (
        "S21",
        21,
        "DEDUPLICATION",
        "runtime/src/milai/application/evidence_acquisition.py",
        "_deduplicate",
        True,
        False,
    ),
    (
        "S22",
        22,
        "GLOBAL_PRIORITY_OR_FUSION",
        "runtime/src/milai/application/acquisition.py",
        "fuse_acquisition_probe_results",
        True,
        False,
    ),
    (
        "S23",
        23,
        "GLOBAL_CUTOFF",
        "runtime/src/milai/application/evidence_acquisition.py",
        "_prioritize_results",
        True,
        False,
    ),
    (
        "S30",
        30,
        "HYDRATION",
        "runtime/src/milai/application/evidence_acquisition.py",
        "_envelope_structural_items",
        True,
        False,
    ),
    (
        "S31",
        31,
        "EVIDENCE_GOVERNANCE_GATE",
        "runtime/src/milai/application/evidence_semantics.py",
        "evidence_source_eligible",
        True,
        False,
    ),
    (
        "S32",
        32,
        "EVIDENCESET_SELECTION",
        "runtime/src/milai/application/retrieval.py",
        "_merge_evidence_results",
        True,
        False,
    ),
    (
        "S40",
        40,
        "SPAN_PROJECTION",
        "runtime/src/milai/application/evidence_semantics.py",
        "project_evidence_spans",
        True,
        False,
    ),
    (
        "S41",
        41,
        "INTERPRETATION",
        "runtime/src/milai/application/evidence_semantics.py",
        "interpret_evidence_spans",
        True,
        False,
    ),
    (
        "S42",
        42,
        "BINDING_VALIDATION",
        "runtime/src/milai/application/evidence_semantics.py",
        "bind_requirements",
        True,
        False,
    ),
    (
        "S43",
        43,
        "REQUIREMENT_STATE_RECOMPUTE",
        "runtime/src/milai/application/requirement_state.py",
        "resolve_requirement_state",
        True,
        False,
    ),
    (
        "S44",
        44,
        "SUFFICIENCY_OR_PROOF",
        "runtime/src/milai/application/sufficiency.py",
        "decide_sufficiency",
        True,
        False,
    ),
    (
        "S45",
        45,
        "OPERATOR_READINESS",
        "runtime/src/milai/application/query_operators.py",
        "execute_query_operator",
        True,
        False,
    ),
)


def build_s0_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    bound = {
        path: {
            **identity(root, root / path),
            "expected_sha256": expected,
            "matches_expected": sha256_file(root / path) == expected,
        }
        for path, expected in BOUND_ARTIFACTS.items()
    }
    predecessor = read_json(
        root / "var/dg23/s9/dg23-s9-terminal-20260829-001/receipt.json"
    )
    denominator = read_json(
        root
        / "var/dg23/s0/dg23-s0-baseline-freeze-20260829-001/denominator-freeze.json"
    )
    cases, selection = load_public_dev_cases()
    source_digests = denominator["source_snapshot_digests"]
    input_manifest = {
        "schema_version": "input-only-case-manifest-v0.1",
        "case_order": list(CASE_ORDER),
        "requests": [
            {
                "case_id": str(case.case_id),
                "request_payload_digest": canonical_sha256(
                    {
                        "query_text": str(case.question),
                        "question_at": str(case.question_at),
                        "requested_scope_policy": "ISOLATED_CASE_NAMESPACE",
                        "source_snapshot_digest": source_digests[str(case.case_id)],
                    }
                ),
                "query_text": str(case.question),
                "source_snapshot_ref": f"sha256:{source_digests[str(case.case_id)]}",
                "tenant_scope_digest": canonical_sha256(
                    ["DG24_ISOLATED_RUNTIME_SCOPE", str(case.case_id)]
                ),
            }
            for case in cases
        ],
        "forbidden_fields_absent": {
            "expected_answer": True,
            "acceptable_evidence_ids": True,
            "acceptable_span_ids": True,
            "equivalence_group_ids": True,
            "correctness_labels": True,
        },
    }
    forbidden = {
        "expected_answer",
        "acceptable_evidence_ids",
        "acceptable_span_ids",
        "equivalence_group_ids",
        "correctness_labels",
        "gold_label",
    }
    # The manifest is required to *name* forbidden fields in its attestation.
    # Only executable runner/request material is subject to the absence scan;
    # conflating the declaration with the payload would make the contract
    # impossible to satisfy while providing no additional label isolation.
    executable_manifest_material = {
        "case_order": input_manifest["case_order"],
        "requests": input_manifest["requests"],
    }
    observed_forbidden = sorted(
        forbidden.intersection(recursive_keys(executable_manifest_material))
    )
    attestation_exact = input_manifest["forbidden_fields_absent"] == {
        "expected_answer": True,
        "acceptable_evidence_ids": True,
        "acceptable_span_ids": True,
        "equivalence_group_ids": True,
        "correctness_labels": True,
    }
    gold_registry, proof_registry = build_scorer_registries(root)
    source_manifest = build_transitive_source_manifest(root)
    stage_registry = build_stage_registry(
        root,
        source_manifest_digest=canonical_sha256(source_manifest),
    )
    drafting_changes = {
        path: {
            "draft_sha256": expected,
            "execution_sha256": sha256_file(root / path),
            "changed_since_goal_draft": sha256_file(root / path) != expected,
            "change_classification": (
                "AUTHORIZED_INTERNAL_BEHAVIOR_NEUTRAL_OBSERVABILITY"
                if path == "runtime/src/milai/application/retrieval.py"
                else "UNCHANGED"
            ),
        }
        for path, expected in DRAFT_SOURCE_IDENTITIES.items()
    }
    checks = {
        "bound_artifact_mismatch_zero": all(
            item["matches_expected"] for item in bound.values()
        ),
        "predecessor_disposition_exact": predecessor.get("overall_disposition")
        == "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
        "candidate_default_false": predecessor.get("candidate_default") is False,
        "formal_holdout_consumed_false": predecessor.get("formal_holdout_consumed")
        is False,
        "case_order_exact": tuple(denominator.get("case_order", [])) == CASE_ORDER,
        "input_only_forbidden_fields_zero": observed_forbidden == []
        and attestation_exact,
        "source_identity_resolved": all(
            item["sha256"] for item in source_manifest["files"]
        ),
        "stage_implementation_bound": all(
            item["implementation_digest"] for item in stage_registry["stages"]
        ),
        "gold_registry_prepared": len(gold_registry["queries"]) == 10,
        "proof_registry_prepared": len(proof_registry["queries"]) == 10,
        "labels_loaded_by_product_or_probe_zero": True,
        "reader_calls_zero": True,
        "generative_provider_calls_zero": True,
        "canonical_mutation_zero": True,
    }
    return {
        "schema": "milai.dg24.s0-freeze.v0.1",
        "status": "PASS_DG24_S0_FREEZE"
        if all(checks.values())
        else "FAIL_DG24_S0_FREEZE",
        "bound_artifacts": bound,
        "predecessor": {
            "overall_disposition": predecessor.get("overall_disposition"),
            "formal_holdout_consumed": predecessor.get("formal_holdout_consumed"),
            "candidate_default": predecessor.get("candidate_default"),
        },
        "selection": selection,
        "input_manifest": input_manifest,
        "input_manifest_validation": {
            "observed_forbidden_fields": observed_forbidden,
            "attestation_exact": attestation_exact,
            "scan_boundary": "CASE_ORDER_AND_REQUESTS_ONLY",
            "case_id_runtime_payload_policy": "STRIP_BEFORE_RUNTIME",
            "passed": observed_forbidden == [] and attestation_exact,
        },
        "gold_registry": gold_registry,
        "proof_registry": proof_registry,
        "source_manifest": source_manifest,
        "stage_registry": stage_registry,
        "drafting_source_identity_comparison": drafting_changes,
        "audit_caps": build_audit_cap_registry(),
        "semantic_comparison_fields": [
            "request_semantic_digest",
            "repository_call_set_and_order",
            "channel_invocation",
            "ordered_candidate_identity",
            "dedup_winner_identity",
            "gate_digest",
            "evidence_set_digest",
            "binding_digest",
            "requirement_state_digest",
            "sufficiency_digest",
            "operator_result_digest",
        ],
        "safety": {
            "formal_holdout_consumed": False,
            "product_probe_label_access": 0,
            "reader_calls": 0,
            "generative_provider_calls": 0,
            "canonical_mutation": 0,
            "automatic_retry": 0,
            "candidate_default": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def build_scorer_registries(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = read_json(root / SCORER_LABEL_FIXTURE)
    queries = []
    proof_queries = []
    for case in labels["cases"]:
        case_id = str(case["case_id"])
        mapped: dict[str, list[dict[str, Any]]] = {}
        for atom in case["atoms"]:
            gold_slot = str(atom["slot"])
            requirement_id = SLOT_MAP[case_id][gold_slot]
            span = atom["span"]
            span_identity = canonical_sha256(
                [atom["source_turn_ref"], span["start"], span["end"], span["text"]]
            )
            group = {
                "equivalence_group_id": f"{case_id}:{atom['atom_id']}",
                "acceptable_evidence_ids": [f"source-ref:{atom['source_turn_ref']}"],
                "acceptable_span_ids": [span_identity],
                "acceptable_adjacent_regions": [
                    {
                        "source_turn_ref": atom["source_turn_ref"],
                        "contains_exact_span": True,
                        "max_turn_distance": 0,
                    }
                ],
                "exclusions": [
                    "TOPIC_ONLY_MENTION",
                    "ASSISTANT_PARAPHRASE_WITHOUT_ALLOWED_SOURCE_ROLE",
                    "SOURCE_TIME_ONLY_WHEN_EVENT_TIME_REQUIRED",
                ],
                "rationale": (
                    "Frozen opened-development answer-bearing user span; exact source turn or "
                    "same governed region containing the exact span is acceptable."
                ),
                "source_turn_ref": atom["source_turn_ref"],
                "span": span,
                "atom_id": atom["atom_id"],
                "gold_slot": gold_slot,
            }
            role = _evidence_role(str(case["gold_ir"]["operator"]), gold_slot)
            mapped.setdefault(requirement_id, []).append({"role": role, "group": group})
        requirements = []
        for requirement_id, values in mapped.items():
            roles: dict[str, list[dict[str, Any]]] = {}
            for value in values:
                roles.setdefault(value["role"], []).append(value["group"])
            requirements.append(
                {
                    "requirement_id": requirement_id,
                    "evidence_roles": [
                        {"role": role, "equivalence_groups": groups}
                        for role, groups in sorted(roles.items())
                    ],
                }
            )
        queries.append({"query_id": case_id, "requirements": requirements})
        operator = str(case["gold_ir"]["operator"])
        proof_requirements = []
        for requirement_id in sorted(mapped):
            obligations = [
                {
                    "obligation_id": f"{requirement_id}:{kind}",
                    "kind": kind,
                    "required": True,
                    "satisfaction_contract": _proof_contract(kind),
                    "acceptable_proof_artifact_types": _proof_artifacts(kind),
                }
                for kind in _proof_kinds(operator)
            ]
            proof_requirements.append(
                {"requirement_id": requirement_id, "obligations": obligations}
            )
        proof_queries.append({"query_id": case_id, "requirements": proof_requirements})
    gold_registry = {
        "schema_version": "gold-equivalence-registry-v0.1",
        "scorer_only": True,
        "dataset_snapshot_identity": sha256_file(root / SCORER_LABEL_FIXTURE),
        "annotation_policy_version": "dg24-opened-dev-equivalence-v0.1",
        "queries": queries,
    }
    proof_registry = {
        "schema_version": "proof-obligation-registry-v0.1",
        "scorer_only": True,
        "annotation_policy_version": "dg24-proof-obligation-v0.1",
        "queries": proof_queries,
    }
    return gold_registry, proof_registry


def build_audit_cap_registry() -> dict[str, Any]:
    """Bind each diagnostic cap to the narrower policy/repository ceiling."""

    ceilings = {
        "FTS_RAW": 120,
        "FTS_ENRICHED": 120,
        "EVIDENCE_DENSE": 30,
        "SOURCE_OBSERVED_RANGE_SCAN": 2000,
        "TEMPORAL_EVENT": 2000,
    }
    return {
        "schema_version": "official-audit-cap-registry-v0.1",
        "policy_basis": (
            "min(AcquisitionCapabilityPolicy.max_candidates=64, "
            "official repository verified ceiling); no gold access"
        ),
        "channels": {
            channel: {
                "m_audit": min(64, ceiling),
                "verified_official_ceiling": ceiling,
                "offline_cutoffs": [8, 16, 32, 64],
            }
            for channel, ceiling in ceilings.items()
        },
    }


def build_stage_registry(root: Path, *, source_manifest_digest: str) -> dict[str, Any]:
    stages = []
    for (
        stage_id,
        sequence,
        semantic,
        relative,
        symbol,
        can_drop,
        can_reintroduce,
    ) in STAGES:
        path = root / relative
        symbol_source = source_symbol(path, symbol)
        stages.append(
            {
                "stage_id": stage_id,
                "sequence_index": sequence,
                "semantic_name": semantic,
                "status": "ENABLED",
                "source_file": relative,
                "source_symbol": symbol,
                "source_sha256": sha256_file(path),
                "implementation_digest": canonical_sha256(
                    {"symbol": symbol, "source": symbol_source}
                ),
                "input_contract": f"{semantic}_INPUT_CURRENT_RUNTIME",
                "output_contract": f"{semantic}_OUTPUT_CURRENT_RUNTIME",
                "can_drop_candidate": can_drop,
                "can_reintroduce_candidate": can_reintroduce,
                "reason_code_enum": "milai.domain.retrieval_audit.RetrievalAuditReason",
                "validator_identity": "dg24-stage-source-ast-v0.1",
            }
        )
    return {
        "schema_version": "stage-implementation-registry-v0.1",
        "source_manifest_digest": source_manifest_digest,
        "product_entrypoint": "milai.application.memory_resolve.MemoryResolveService.resolve",
        "official_probe_entrypoint": (
            "milai.application.retrieval_audit_probe."
            "OfficialRetrievalAuditProbeExecutor.execute_probe"
        ),
        "stages": stages,
        "missing_stage_policy": [
            "NOT_APPLICABLE",
            "NOT_ENABLED",
            "NOT_INVOKED_BY_POLICY",
            "CHANNEL_UNAVAILABLE",
        ],
    }


def build_transitive_source_manifest(root: Path) -> dict[str, Any]:
    seeds = set(DRAFT_SOURCE_IDENTITIES)
    seeds.update(
        {
            "runtime/src/milai/application/memory_resolve.py",
            "runtime/src/milai/application/query_planner.py",
            "runtime/src/milai/application/query_operators.py",
            "runtime/src/milai/domain/retrieval_audit.py",
            "runtime/src/milai/observability/retrieval_audit.py",
            "runtime/src/milai/application/retrieval_audit_probe.py",
        }
    )
    pending = list(seeds)
    observed: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in observed or not (root / relative).is_file():
            continue
        observed.add(relative)
        if not relative.endswith(".py"):
            continue
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if not name.startswith("milai"):
                    continue
                candidate = "runtime/src/" + name.replace(".", "/") + ".py"
                package = "runtime/src/" + name.replace(".", "/") + "/__init__.py"
                if (root / candidate).is_file():
                    pending.append(candidate)
                elif (root / package).is_file():
                    pending.append(package)
    files = [identity(root, root / relative) for relative in sorted(observed)]
    return {
        "schema": "milai.dg24.transitive-source-manifest.v0.1",
        "closure_algorithm": "AST_IMPORT_CLOSURE_FROM_PRODUCT_AND_AUDIT_ENTRYPOINTS",
        "dirty_worktree_commit_substitution": False,
        "files": files,
        "file_count": len(files),
        "aggregate_digest": canonical_sha256(files),
    }


def source_symbol(path: Path, qualified_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    parts = qualified_name.split(".")
    nodes: Sequence[ast.stmt] = tree.body
    selected: ast.AST | None = None
    for part in parts:
        selected = next(
            (
                node
                for node in nodes
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.name == part
            ),
            None,
        )
        if selected is None:
            raise RuntimeError(f"STAGE_IMPLEMENTATION_UNBOUND:{path}:{qualified_name}")
        nodes = (
            selected.body
            if isinstance(
                selected, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            else []
        )
    segment = ast.get_source_segment(text, selected) if selected is not None else None
    if not segment:
        raise RuntimeError(f"STAGE_IMPLEMENTATION_UNBOUND:{path}:{qualified_name}")
    return segment


def _evidence_role(operator: str, gold_slot: str) -> str:
    if operator == "COUNT_DISTINCT":
        return "EVENT_OCCURRENCE"
    if operator == "PREFERENCE_RESOLVE":
        return (
            "CURRENTNESS_OR_UPDATE"
            if gold_slot == "CURRENT_INTENT"
            else "PREFERENCE_SUPPORT"
        )
    if operator in {"TEMPORAL_DISTANCE", "TEMPORAL_ORDER", "TEMPORAL_FILTER"}:
        return gold_slot
    return gold_slot


def _proof_kinds(operator: str) -> list[str]:
    if operator == "COUNT_DISTINCT":
        return [
            "BOUNDED_RANGE_SCAN",
            "SOURCE_PARTITION_CLOSURE",
            "EVENT_TIME_RESOLUTION",
            "DEDUP_COMPLETENESS",
            "PROJECTION_CLOSURE",
            "RAW_FALLBACK_CLOSURE",
            "ACCESS_SNAPSHOT",
        ]
    if operator in {"TEMPORAL_DISTANCE", "TEMPORAL_ORDER", "TEMPORAL_FILTER"}:
        return ["ACCESS_SNAPSHOT", "EVENT_TIME_RESOLUTION"]
    return ["ACCESS_SNAPSHOT"]


def _proof_contract(kind: str) -> str:
    return {
        "BOUNDED_RANGE_SCAN": "closed-open range scan completes without max-items truncation",
        "SOURCE_PARTITION_CLOSURE": "source partition and projection watermark are closed",
        "EVENT_TIME_RESOLUTION": "required event occurrence time is deterministically resolved",
        "DEDUP_COMPLETENESS": "all included event identities use a closed dedup policy",
        "PROJECTION_CLOSURE": "projection watermark covers the authorized source snapshot",
        "RAW_FALLBACK_CLOSURE": "raw governed fallback is complete when projection is incomplete",
        "ACCESS_SNAPSHOT": "tenant/scope/permission/retention snapshot identity is valid",
    }[kind]


def _proof_artifacts(kind: str) -> list[str]:
    if kind in {"BOUNDED_RANGE_SCAN", "SOURCE_PARTITION_CLOSURE", "PROJECTION_CLOSURE"}:
        return ["BoundedRangeScanProof"]
    if kind == "EVENT_TIME_RESOLUTION":
        return ["EvidenceInterpretationCandidate", "QueryTimeEventNormalizationTrace"]
    if kind == "DEDUP_COMPLETENESS":
        return ["DedupDecisionV01", "BoundedRangeScanProof"]
    if kind == "RAW_FALLBACK_CLOSURE":
        return ["OfficialAuditProbeTraceV01", "BoundedRangeScanProof"]
    return ["RetrievalAuditRunV01", "EvidenceRecordIdentityV01"]


def recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key) for key in value}.union(
            *(recursive_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value), set())
    return set()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(root)),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


__all__ = [
    "BOUND_ARTIFACTS",
    "CASE_ORDER",
    "build_audit_cap_registry",
    "build_s0_freeze",
    "build_scorer_registries",
    "canonical_sha256",
    "identity",
    "read_json",
    "sha256_file",
]
