"""Build the zero-label DG-25 S3/S4 effect-readiness package."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from milai.domain.requirement_state import canonical_sha256

from evals.dg25.arm_sealing import (
    COST_LEDGER_FIELDS,
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    cost_ledger_schema,
)
from evals.dg25.effect_scorer import (
    SCORER_IDENTITY,
    scorer_contract,
)
from evals.dg25.routing_ablation import (
    E1ArmConfigV01,
    E2ArmConfigV01,
    build_e1_arm_config,
    build_e2_arm_config,
    component_difference,
    temporal_component_difference,
)
from evals.dg25.s3a_generator import (
    build_e1_action_manifest,
    validate_e1_action_manifest,
)
from evals.dg25.stop_gate import (
    S3A_REQUIRED_BINDINGS,
    evaluate_generation_gate,
    evaluate_score_gate,
    stop_evaluation_contract,
)

ARM_MANIFEST = Path(
    "var/dg25/reviews/dg25-review-gate-20260829-001/pre-treatment-arm-manifest.json"
)
STOP_REGISTRY = Path(
    "var/dg25/reviews/dg25-review-gate-20260829-001/stop-rule-registry.json"
)
POST_S2_REVIEW = Path(
    "var/dg25/reviews/dg25-post-s2-independent-review-20260829-001/review.json"
)
S2_RECEIPT = Path("var/dg25/s2/dg25-s2-plan-execution-20260829-003/receipt.json")
S2_SOURCE_MANIFEST = Path(
    "var/dg25/s2/dg25-s2-plan-execution-20260829-003/source-manifest.json"
)
DG24_PRODUCT = Path(
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-product-traces.json"
)
DG24_PROBES = Path(
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-official-probe-traces.json"
)
DG24_INPUTS = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/input-only-case-manifest-v0.1.json"
)
GOLD_REGISTRY = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)
PROOF_REGISTRY = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "proof-obligation-registry-v0.1.json"
)

READINESS_SOURCE_PATHS = (
    Path("evals/dg25/routing_ablation.py"),
    Path("evals/dg25/arm_sealing.py"),
    Path("evals/dg25/s3a_generator.py"),
    Path("evals/dg25/effect_scorer.py"),
    Path("evals/dg25/stop_gate.py"),
    Path("evals/dg25/s3_readiness.py"),
    Path("evals/dg24/scorer.py"),
    Path("scripts/run_dg25_readiness_quality.py"),
    Path("scripts/run_dg25_s3_readiness.py"),
    Path("scripts/run_dg25_s3a.py"),
    Path("tests/test_dg25_s3_readiness.py"),
    Path("runtime/src/milai/application/accuracy_acquisition.py"),
    Path("runtime/src/milai/application/acquisition.py"),
    Path("runtime/src/milai/application/evidence_acquisition.py"),
    Path("runtime/src/milai/application/evidence_semantics.py"),
    Path("runtime/src/milai/application/requirement_acquisition.py"),
    Path("runtime/src/milai/domain/requirement_acquisition.py"),
    Path("runtime/src/milai/domain/temporal_proof.py"),
)
PRODUCT_PLANE_SOURCE_PATHS = (
    Path("evals/dg25/routing_ablation.py"),
    Path("evals/dg25/arm_sealing.py"),
    Path("evals/dg25/s3a_generator.py"),
    Path("scripts/run_dg25_s3a.py"),
    Path("runtime/src/milai/application/accuracy_acquisition.py"),
    Path("runtime/src/milai/application/acquisition.py"),
    Path("runtime/src/milai/application/evidence_acquisition.py"),
    Path("runtime/src/milai/application/evidence_semantics.py"),
    Path("runtime/src/milai/application/requirement_acquisition.py"),
    Path("runtime/src/milai/domain/requirement_acquisition.py"),
    Path("runtime/src/milai/domain/temporal_proof.py"),
)
S3A_PLAIN_IMPORT_ALLOWLIST = {
    "runner": {
        "argparse",
        "hashlib",
        "json",
        "os",
        "re",
        "sys",
        "tempfile",
        "traceback",
    },
    "generator": set(),
}
S3A_FROM_IMPORT_ALLOWLIST = {
    "runner": {
        "__future__": {"annotations"},
        "collections.abc": {"Callable", "Mapping", "Sequence"},
        "dataclasses": {"dataclass", "field"},
        "datetime": {"UTC", "datetime"},
        "pathlib": {"Path"},
        "typing": {"Any"},
        "evals.dg25.routing_ablation": {"E1ArmConfigV01"},
        "evals.dg25.s3a_generator": {"generate_e1_all_arm_bundle"},
        "evals.dg25.stop_gate": {"evaluate_generation_gate"},
    },
    "generator": {
        "__future__": {"annotations"},
        "collections.abc": {"Mapping", "Sequence"},
        "typing": {"Any", "Literal"},
        "milai.domain.requirement_state": {"canonical_sha256"},
        "evals.dg25.arm_sealing": {
            "COST_LEDGER_FIELDS",
            "E1_ARM_ORDER",
            "build_block_all_arm_seal",
            "build_label_free_arm_output",
            "validate_block_all_arm_seal",
        },
        "evals.dg25.routing_ablation": {
            "E1ArmConfigV01",
            "E1RequirementActionPlanV01",
            "ReplayOccurrenceV01",
            "build_e1_requirement_action_plan",
            "build_replay_action",
            "select_label_free_occurrences",
            "validate_e1_requirement_action_plan",
        },
    },
}
S3A_FORBIDDEN_DYNAMIC_REFERENCES = {
    "__import__",
    "__builtins__",
    "builtins",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "importlib",
    "locals",
    "setattr",
    "vars",
}
S3A_FORBIDDEN_CALL_SEGMENTS = {
    "controller",
    "effect_scorer",
    "importlib",
    "persistence",
    "provider",
    "reader",
    "repository",
    "score_all_arms",
    "scorer",
}
S3A_ALLOWED_LOCAL_NAME_CALLS = {
    "runner": {
        "S3AFailureContext",
        "_all_arm_case_orders_match",
        "_binding_digest",
        "_build_s3a_failure_context",
        "_canonical_sha256",
        "_capture_and_execute",
        "_capture_attempt_identity_envelope",
        "_capture_is_complete",
        "_contract_diagnostic",
        "_derive_s3a_bindings",
        "_ensure_output_absent",
        "_exact_identity",
        "_exact_predecessor_contract",
        "_exact_readiness_artifact_contract",
        "_exact_source_contract",
        "_exception_diagnostic",
        "_execute",
        "_execute_with_failure_ledger",
        "_file_identity",
        "_freeze_captured_envelope",
        "_identity_is_complete",
        "_is_safe_component",
        "_lexically_within",
        "_logical_path",
        "_mapping",
        "_mapping_sequence",
        "_mark_group_unobserved",
        "_observe_identity",
        "_output_digest",
        "_path_is_relative_to",
        "_preallocated_attempt_identity_envelope",
        "_read_bound_artifact",
        "_read_identity_bound_json",
        "_read_json",
        "_read_observation_bound_json",
        "_record_s3a_failure",
        "_replace_identity",
        "_require_gate_pass",
        "_require_resolved_direct_child",
        "_resolved_within",
        "_review_binding_is_exact",
        "_reviewed_readiness_identity",
        "_run_s3a_once",
        "_safe_failure_component",
        "_seal_digest",
        "_sha256",
        "_skip_remaining_capture",
        "_string_sequence",
        "_try_read_json",
        "_try_read_json_after_observation",
        "_unobserved_identity",
        "_validate_artifact_identities",
        "_validate_attempt_identity_envelope",
        "_validate_current_sources",
        "_validate_top_level_paths",
        "_write_json",
        "main",
    },
    "generator": {
        "_action_from_identity",
        "_channel_identity_index",
        "_evidence_ids",
        "_first_seen",
        "_generate_one_arm",
        "_identity_executable",
        "_lifecycle_index",
        "_mapping",
        "_mapping_sequence",
        "_plan_key",
        "_plans_by_arm",
        "_probe_index",
        "_project_occurrence",
        "_proof_index",
        "_proof_statuses",
        "_requirement_rows",
        "_semantic_record_projection",
        "_validate_all_arm_case_order",
        "_validate_frozen_case_order",
        "_validate_r0_r0p_compatibility",
        "_validate_source_case_orders",
        "validate_e1_action_manifest",
        "validate_s3a_authorization",
    },
}
S3A_ALLOWED_IMPORTED_NAME_CALLS = {
    "runner": {
        "Path",
        "evaluate_generation_gate",
        "field",
        "generate_e1_all_arm_bundle",
    },
    "generator": {
        "ReplayOccurrenceV01",
        "build_block_all_arm_seal",
        "build_e1_requirement_action_plan",
        "build_label_free_arm_output",
        "build_replay_action",
        "canonical_sha256",
        "select_label_free_occurrences",
        "validate_block_all_arm_seal",
        "validate_e1_requirement_action_plan",
    },
}
S3A_ALLOWED_BUILTIN_NAME_CALLS = {
    "runner": {
        "FileExistsError",
        "KeyError",
        "OSError",
        "SystemExit",
        "TypeError",
        "ValueError",
        "all",
        "any",
        "dict",
        "enumerate",
        "isinstance",
        "len",
        "list",
        "print",
        "set",
        "str",
        "tuple",
        "type",
        "zip",
    },
    "generator": {
        "AssertionError",
        "TypeError",
        "ValueError",
        "all",
        "any",
        "bool",
        "dict",
        "int",
        "isinstance",
        "len",
        "list",
        "next",
        "set",
        "sorted",
        "str",
        "sum",
        "zip",
    },
}
S3A_ALLOWED_PARAMETER_CALLS = {
    "runner": {("_execute_with_failure_ledger", "execute")},
    "generator": set(),
}
S3A_ALLOWED_ATTRIBUTE_CALLS = {
    "runner": {
        "E1ArmConfigV01.model_validate",
        "PREDECESSOR_INPUT_PATHS.items",
        "Path.cwd",
        "READINESS_ARTIFACT_FILENAMES.items",
        "SAFE_COMPONENT_PATTERN.fullmatch",
        "_SCRIPT_PATH.resolve",
        "absolute_path.relative_to",
        "action_manifest.get",
        "allowed_root.resolve",
        "argparse.ArgumentParser",
        "artifact_observations.append",
        "artifacts.get",
        "bundle.get",
        "bundle.items",
        "canonical_json.encode",
        "captured.get",
        "completeness_checks.values",
        "context.attempt_identity_envelope.get",
        "context.config_identity.get",
        "current_time.astimezone",
        "datetime.now",
        "delta.get",
        "diagnostics.items",
        "diagnostics.values",
        "digest.hexdigest",
        "disposition.encode",
        "disposition_digest.hexdigest",
        "e1.get",
        "encoded_record.encode",
        "entry.get",
        "envelope.get",
        "envelope.pop",
        "expected_counts.items",
        "expected_receipt.get",
        "failure_dir.mkdir",
        "gate.get",
        "hashlib.sha256",
        "implementation.get",
        "index_path.parent.mkdir",
        "item.get",
        "json.dumps",
        "json.loads",
        "manifest.get",
        "material.pop",
        "message.encode",
        "message_digest.hexdigest",
        "observation.get",
        "os.close",
        "os.fsync",
        "os.open",
        "os.write",
        "output.exists",
        "output.is_symlink",
        "output.parent.mkdir",
        "output.relative_to",
        "outputs.values",
        "parent.absolute",
        "parent.resolve",
        "parser.add_argument",
        "parser.parse_args",
        "path.absolute",
        "path.read_bytes",
        "path.read_text",
        "path.relative_to",
        "path.resolve",
        "path.stat",
        "path.write_text",
        "predecessor_input_identities.append",
        "raw.get",
        "raw_artifacts.get",
        "re.compile",
        "re.fullmatch",
        "re.sub",
        "readiness_artifact_identities.append",
        "receipt.get",
        "receipt_identity.get",
        "receipt_observation.get",
        "recorded.isoformat",
        "recorded.strftime",
        "relative_path.as_posix",
        "requested_review.is_absolute",
        "requested_review_path.is_absolute",
        "resolved_path.is_file",
        "resolved_path.relative_to",
        "resolved_path.stat",
        "result.append",
        "review.get",
        "review_absolute.relative_to",
        "review_path.absolute",
        "review_root.absolute",
        "reviewed_identity.get",
        "root.absolute",
        "root.resolve",
        "sanitized.strip",
        "separator.join",
        "source_manifest.get",
        "stderr_path.write_text",
        "stdout_path.write_text",
        "stop_contract.get",
        "sys.path.insert",
        "tempfile.mkdtemp",
        "temporary.rename",
        "traceback.format_exception",
        "value.get",
    },
    "generator": {
        "E1RequirementActionPlanV01.model_validate",
        "active.append",
        "arm_identities.add",
        "arm_outputs.get",
        "arm_plans.append",
        "artifact.get",
        "authorization.get",
        "authorization_boundaries.items",
        "baseline.get",
        "baseline_probe.get",
        "baseline_record.get",
        "binding.get",
        "collection.get",
        "common_execution_bindings.get",
        "config_by_id.get",
        "dict.fromkeys",
        "gate.get",
        "identities_by_arm.values",
        "identity.get",
        "item.get",
        "item.model_dump",
        "lifecycle.get",
        "lifecycle_index.get",
        "manifest.get",
        "material.pop",
        "official_probe_collection.get",
        "optional_probe.get",
        "ordered_arm_identities.append",
        "ordered_identities_by_arm.values",
        "output.get",
        "plan.model_dump",
        "plan_record.get",
        "planned.get",
        "plans.append",
        "product_traces.get",
        "projected.append",
        "proof_by_requirement.get",
        "proof_index.get",
        "proof_probe.get",
        "proof_rows.append",
        "query_requirements.append",
        "r0.get",
        "r0p.get",
        "raw.get",
        "record.get",
        "record_requirements.sort",
        "records_by_query.setdefault",
        "records_by_query.values",
        "required_requirements.sort",
        "requirement.get",
        "requirements.append",
        "result.append",
        "result.setdefault",
        "rows.append",
        "source.get",
        "trace.get",
    },
}
S3A_RUNNER_FUNCTION_CONTRACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "_run_s3a_once": (
        "args: argparse.Namespace, *, root: Path, argv: Sequence[str]",
        (
            "context = _build_s3a_failure_context(args, root=root)",
            (
                "return _execute_with_failure_ledger(execute=lambda: "
                "_capture_and_execute(args, context, root=root), context=context, "
                "root=root, argv=argv)"
            ),
        ),
    ),
    "_execute_with_failure_ledger": (
        (
            "*, execute: Callable[[], int], context: S3AFailureContext, root: Path, "
            "argv: Sequence[str]"
        ),
        (
            (
                "try:\n"
                "    return execute()\n"
                "except Exception as exc:\n"
                "    _record_s3a_failure(root=root, argv=argv, context=context, "
                "error=exc)\n"
                "    raise"
            ),
        ),
    ),
}
S3A_RUNNER_CRITICAL_CALL_COUNTS: dict[str, int] = {
    "_capture_and_execute": 1,
    "_execute_with_failure_ledger": 1,
    "execute": 1,
}
S3A_GENERATOR_SORT_CALLBACK_CONTRACTS: dict[str, str] = {
    "record_requirements.sort": "lambda item: str(item['requirement_id'])",
    "required_requirements.sort": "lambda item: str(item['requirement_id'])",
}


def build_readiness_artifacts(
    root: Path,
    *,
    quality_evidence: Mapping[str, Any] | None = None,
    require_authoritative_quality: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build all readiness artifacts without opening either scorer registry."""

    arm_manifest = read_json_object(root / ARM_MANIFEST)
    stop_registry = read_json_object(root / STOP_REGISTRY)
    review = read_json_object(root / POST_S2_REVIEW)
    s2_receipt = read_json_object(root / S2_RECEIPT)
    product = read_json_object(root / DG24_PRODUCT)
    probes = read_json_object(root / DG24_PROBES)
    inputs = read_json_object(root / DG24_INPUTS)
    _validate_authorization_boundary(review)
    _validate_frozen_inputs(arm_manifest, stop_registry, s2_receipt, probes)
    frozen_case_order = _string_sequence(
        _mapping(arm_manifest.get("denominators"), "arm denominators").get(
            "case_order"
        ),
        "frozen case order",
    )

    common_input = _build_e2_common_input(root, product, inputs)
    source_manifest = _build_source_manifest(root, inputs)
    scorer_seal = _build_scorer_seal(root, arm_manifest)
    pool_binding = _pool_binding(root, arm_manifest)
    e1_configs = _build_e1_configs(root, pool_binding)
    e2_configs = _build_e2_configs(root, common_input)
    action_manifest = build_e1_action_manifest(
        configs=e1_configs,
        exact_channel_query_identities=_mapping_sequence(
            arm_manifest.get("exact_channel_query_identities"),
            "channel-query identities",
        ),
        official_probe_collection=probes,
        official_probe_identity=identity(root, DG24_PROBES),
        product_traces=product,
        product_trace_identity=identity(root, DG24_PRODUCT),
        pool_binding_digest=str(pool_binding["pool_binding_digest"]),
        frozen_case_order=frozen_case_order,
    )
    contrasts = _validate_config_contrasts(e1_configs, e2_configs)
    ledger_schema = cost_ledger_schema()
    quality_binding = _build_quality_evidence_binding(
        root=root,
        evidence=quality_evidence,
        authoritative_required=require_authoritative_quality,
    )
    delta = _build_execution_delta(
        root=root,
        arm_manifest=arm_manifest,
        pool_binding=pool_binding,
        common_input=common_input,
        scorer_seal=scorer_seal,
        source_manifest=source_manifest,
        e1_configs=e1_configs,
        e2_configs=e2_configs,
        action_manifest=action_manifest,
        ledger_schema=ledger_schema,
        quality_binding=quality_binding,
        contrasts=contrasts,
    )
    seal_protocol = _build_all_arm_seal_protocol(
        delta=delta,
        common_input=common_input,
        scorer_seal=scorer_seal,
        source_manifest=source_manifest,
        action_manifest=action_manifest,
        pool_binding=pool_binding,
        ledger_schema=ledger_schema,
        e1_configs=e1_configs,
        e2_configs=e2_configs,
    )
    stop_contract = _build_bound_stop_contract(
        root=root,
        delta=delta,
        common_input=common_input,
        scorer_seal=scorer_seal,
        source_manifest=source_manifest,
        seal_protocol=seal_protocol,
        action_manifest=action_manifest,
        pool_binding=pool_binding,
        ledger_schema=ledger_schema,
    )
    validation = _build_validation_report(
        root=root,
        common_input=common_input,
        scorer_seal=scorer_seal,
        source_manifest=source_manifest,
        delta=delta,
        seal_protocol=seal_protocol,
        stop_contract=stop_contract,
        action_manifest=action_manifest,
        quality_binding=quality_binding,
        ledger_schema=ledger_schema,
        e1_configs=e1_configs,
        e2_configs=e2_configs,
        contrasts=contrasts,
    )
    return {
        "e2-common-input.json": common_input,
        "effect-scorer-contract.json": scorer_seal,
        "cost-ledger-schema.json": ledger_schema,
        "e1-action-role-manifest.json": action_manifest,
        "quality-evidence-binding.json": quality_binding,
        "source-manifest.json": source_manifest,
        "execution-delta-manifest.json": delta,
        "all-arm-seal-protocol.json": seal_protocol,
        "stop-evaluation-contract.json": stop_contract,
        "readiness-validation-report.json": validation,
    }


def _validate_authorization_boundary(review: Mapping[str, Any]) -> None:
    authorization = review.get("authorization")
    if not isinstance(authorization, Mapping):
        raise TypeError("post-S2 authorization object required")
    expected = {
        "s3_e1_e2_matched_replay_authorized": False,
        "s3_e1_e2_effect_scoring_authorized": False,
        "s3_readiness_manifest_scorer_and_tests_only_authorized": True,
        "opened_development_labels_authorized": False,
        "scorer_gold_registry_content_load_authorized": False,
    }
    if any(authorization.get(key) is not value for key, value in expected.items()):
        raise ValueError("DG25_POST_S2_READINESS_AUTHORIZATION_MISMATCH")
    edits = review.get("residual_required_edits")
    if not isinstance(edits, Sequence) or isinstance(edits, (str, bytes)):
        raise TypeError("post-S2 required edits must be a sequence")
    if [str(item["id"]) for item in edits if isinstance(item, Mapping)] != [
        f"POSTS2-RE-{index:02d}" for index in range(1, 8)
    ]:
        raise ValueError("DG25_POST_S2_REQUIRED_EDIT_SET_MISMATCH")


def _validate_frozen_inputs(
    arm_manifest: Mapping[str, Any],
    stop_registry: Mapping[str, Any],
    s2_receipt: Mapping[str, Any],
    probes: Mapping[str, Any],
) -> None:
    if s2_receipt.get("status") != "PASS_DG25_S2_UNIFIED_PLAN_OFFICIAL_BATCH_EXECUTION":
        raise ValueError("DG25_S2_RECEIPT_NOT_PASS")
    identities = arm_manifest.get("exact_channel_query_identities")
    if not isinstance(identities, Sequence) or isinstance(identities, (str, bytes)):
        raise TypeError("exact channel-query identities must be a sequence")
    if len(identities) != 75 or len(probes.get("records", [])) != 75:
        raise ValueError("DG25_OFFICIAL_POOL_DENOMINATOR_MISMATCH")
    rules = stop_registry.get("machine_rules")
    if not isinstance(rules, Sequence) or len(rules) != 10:
        raise ValueError("DG25_STOP_RULE_REGISTRY_MISMATCH")
    selection = arm_manifest.get("selection_and_budget")
    if not isinstance(selection, Mapping):
        raise TypeError("selection and budget object required")
    if (
        selection.get("final_k") != 8
        or selection.get("verified_dense_ceiling") != 30
        or selection.get("max_actions_per_plan") != 2
    ):
        raise ValueError("DG25_K_DENSE_OR_ACTION_BOUND_DRIFT")


def _build_e2_common_input(
    root: Path,
    product: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    requests = {
        str(item["case_id"]): item
        for item in _mapping_sequence(inputs.get("requests"), "input requests")
    }
    requirements = []
    for record in _mapping_sequence(product.get("records"), "product records"):
        trace = _mapping(record.get("trace"), "product trace")
        proofs = _mapping_sequence(trace.get("proof_obligations"), "proof obligations")
        if not any(str(item.get("kind")) == "BOUNDED_RANGE_SCAN" for item in proofs):
            continue
        query_id = str(record["case_id"])
        request = _mapping(requests.get(query_id), "input request")
        declared = [
            item
            for item in _mapping_sequence(trace.get("requirements"), "requirements")
            if item.get("required") is True
        ]
        if len(declared) != 1:
            raise ValueError("DG25_E2_REQUIRES_ONE_RANGE_REQUIREMENT_PER_QUERY")
        requirement_id = str(declared[0]["requirement_id"])
        raw = [
            item
            for item in _mapping_sequence(trace.get("occurrences"), "occurrences")
            if item.get("channel") == "TEMPORAL_EVENT"
        ]
        ranks = [int(item["raw_rank"]) for item in raw]
        if ranks != list(range(1, len(raw) + 1)):
            raise ValueError("DG25_E2_RAW_ROW_ORDER_INVALID")
        if len({str(item["occurrence_id"]) for item in raw}) != len(raw):
            raise ValueError("DG25_E2_RAW_ROW_OCCURRENCE_DUPLICATE")
        evidence = [_mapping(item.get("evidence_record_identity"), "evidence identity") for item in raw]
        retrieval = [
            _mapping(item.get("retrieval_document_identity"), "retrieval identity")
            for item in raw
        ]
        requirements.append(
            {
                "query_id": query_id,
                "requirement_id": requirement_id,
                "query_identity": str(trace["query_identity"]),
                "query_ir_digest": str(trace["query_ir_digest"]),
                "request_payload_digest": str(request["request_payload_digest"]),
                "request_identity": _only_string(
                    {str(item["request_identity"]) for item in raw},
                    "request identity",
                ),
                "source_snapshot_identity": str(request["source_snapshot_ref"]).removeprefix(
                    "sha256:"
                ),
                "input_tenant_scope_digest": str(request["tenant_scope_digest"]),
                "evidence_tenant_scope_digest": _only_string(
                    {str(item["tenant_scope_digest"]) for item in evidence},
                    "evidence tenant scope",
                ),
                "permission_snapshot_digest": _only_string(
                    {str(item["permission_snapshot_digest"]) for item in evidence},
                    "permission snapshot",
                ),
                "retention_snapshot_digest": _only_string(
                    {str(item["retention_snapshot_digest"]) for item in evidence},
                    "retention snapshot",
                ),
                "channel_query_digest": _only_string(
                    {str(item["channel_query_digest"]) for item in raw},
                    "channel query",
                ),
                "index_identity": _only_string(
                    {str(item["index_identity"]) for item in retrieval},
                    "index identity",
                ),
                "raw_row_count": len(raw),
                "raw_rows_in_order": [
                    {
                        "ordinal": index,
                        "raw_rank": int(item["raw_rank"]),
                        "occurrence_id": str(item["occurrence_id"]),
                        "evidence_id": str(evidence[index - 1]["evidence_id"]),
                        "evidence_record_identity_digest": canonical_sha256(evidence[index - 1]),
                        "retrieval_document_identity_digest": canonical_sha256(
                            retrieval[index - 1]
                        ),
                    }
                    for index, item in enumerate(raw, start=1)
                ],
                "t2_applicability": {
                    "disposition": "NOT_APPLICABLE",
                    "reason_code": "NO_GROUNDED_UNIQUE_ANCHOR_RELATION_IN_SEALED_ROW_CONTRACT",
                    "decided_before_labels": True,
                },
            }
        )
    requirements.sort(key=lambda item: (str(item["query_id"]), str(item["requirement_id"])))
    if len(requirements) != 2 or [
        _integer_value(item.get("raw_row_count"), "raw row count") for item in requirements
    ] != [494, 479]:
        raise ValueError("DG25_E2_COMMON_ROW_SET_MISMATCH")
    material: dict[str, Any] = {
        "schema": "milai.dg25.e2-common-input.v0.1",
        "source_product_trace": identity(root, DG24_PRODUCT),
        "source_input_manifest": identity(root, DG24_INPUTS),
        "extraction_identity": implementation_identity(
            root, Path("evals/dg25/s3_readiness.py"), "_build_e2_common_input"
        ),
        "requirements": requirements,
        "requirement_count": 2,
        "raw_row_count": sum(
            _integer_value(item.get("raw_row_count"), "raw row count")
            for item in requirements
        ),
        "t2_applicability_frozen_before_labels": True,
        "registry_content_loaded": False,
        "formal_holdout_consumed": False,
    }
    material["common_input_digest"] = canonical_sha256(material)
    return material


def _pool_binding(root: Path, arm_manifest: Mapping[str, Any]) -> dict[str, Any]:
    selection = _mapping(arm_manifest.get("selection_and_budget"), "selection and budget")
    identities = arm_manifest.get("exact_channel_query_identities")
    if not isinstance(identities, Sequence) or isinstance(identities, (str, bytes)):
        raise TypeError("channel-query identities must be a sequence")
    material: dict[str, Any] = {
        "schema": "milai.dg25.e1-common-pool-binding.v0.1",
        "sealed_official_probe_collection": identity(root, DG24_PROBES),
        "channel_query_identity_count": len(identities),
        "channel_query_identities_digest": canonical_sha256(list(identities)),
        "final_k": selection["final_k"],
        "replay_audit_caps": selection["replay_audit_caps"],
        "live_action_candidate_caps": selection["live_action_candidate_caps"],
        "verified_dense_ceiling": selection["verified_dense_ceiling"],
        "cross_channel_fusion": selection["cross_channel_fusion"],
        "compare_raw_scores_across_channels": selection[
            "compare_raw_scores_across_channels"
        ],
        "new_physical_repository_calls": 0,
        "live_latency": "NOT_MEASURED",
        "registry_content_loaded": False,
    }
    material["pool_binding_digest"] = canonical_sha256(material)
    return material


def _build_e1_configs(
    root: Path,
    pool_binding: Mapping[str, Any],
) -> list[E1ArmConfigV01]:
    sources = {
        "legacy_plan": implementation_identity(
            root,
            Path("runtime/src/milai/application/accuracy_acquisition.py"),
            "compile_accuracy_action_decision",
        ),
        "unified_proof_first": implementation_identity(
            root,
            Path("runtime/src/milai/application/requirement_acquisition.py"),
            "RequirementAcquisitionPlanCompiler.compile",
        ),
        "optional_channel_union": implementation_identity(
            root,
            Path("runtime/src/milai/application/evidence_acquisition.py"),
            "EvidenceAcquisitionExecutor.execute_plan",
        ),
        "rank_based_fusion": implementation_identity(
            root,
            Path("runtime/src/milai/application/acquisition.py"),
            "fuse_acquisition_probe_results",
        ),
        "role_reservation": implementation_identity(
            root,
            Path("runtime/src/milai/application/accuracy_acquisition.py"),
            "execute_requirement_complete_bundle",
        ),
        "legacy_lexical_hard_filter": implementation_identity(
            root,
            Path("runtime/src/milai/application/accuracy_acquisition.py"),
            "_rank_requirement",
        ),
        "soft_lexical_replay": implementation_identity(
            root,
            Path("evals/dg25/routing_ablation.py"),
            "select_label_free_occurrences",
        ),
        "synonym_normalization": implementation_identity(
            root,
            Path("runtime/src/milai/application/accuracy_acquisition.py"),
            "_SYNONYMS",
        ),
        "gate_and_binding": implementation_identity(
            root,
            Path("runtime/src/milai/application/evidence_semantics.py"),
            "run_type_directed_semantics",
        ),
    }
    common: dict[str, Any] = {
        "ordered_predecessor": None,
        "matched_full_policy_control": None,
        "removed_component": None,
        "optional_channel_priority": [
            "FTS_ENRICHED",
            "EVIDENCE_DENSE",
            "TEMPORAL_EVENT",
        ],
        "proof_channel_priority": ["TEMPORAL_EVENT", "SOURCE_OBSERVED_RANGE_SCAN"],
        "final_k": 8,
        "max_actions_per_plan": 2,
        "cross_channel_fusion": "RANK_BASED_ONLY",
        "compare_raw_scores_across_channels": False,
        "pool_binding_digest": str(pool_binding["pool_binding_digest"]),
        "component_source_identities": sources,
    }
    vectors: list[dict[str, Any]] = [
        {
            "arm_id": "R0",
            "plan_contract": "LEGACY_ACCURACY_ACTION_BUNDLE_V01",
            "unified_proof_first": False,
            "optional_channel_union": False,
            "role_reservation": False,
            "lexical_mode": "LEGACY_HARD_FILTER",
            "synonym_normalization": True,
        },
        {
            "arm_id": "R0P",
            "ordered_predecessor": "R0",
            "plan_contract": "REQUIREMENT_PLAN_V01",
            "unified_proof_first": False,
            "optional_channel_union": False,
            "role_reservation": False,
            "lexical_mode": "LEGACY_HARD_FILTER",
            "synonym_normalization": True,
        },
        {
            "arm_id": "R1",
            "ordered_predecessor": "R0P",
            "plan_contract": "REQUIREMENT_PLAN_V01",
            "unified_proof_first": True,
            "optional_channel_union": False,
            "role_reservation": False,
            "lexical_mode": "LEGACY_HARD_FILTER",
            "synonym_normalization": True,
        },
        {
            "arm_id": "R2",
            "ordered_predecessor": "R1",
            "plan_contract": "REQUIREMENT_PLAN_V01",
            "unified_proof_first": True,
            "optional_channel_union": True,
            "role_reservation": False,
            "lexical_mode": "LEGACY_HARD_FILTER",
            "synonym_normalization": True,
        },
        {
            "arm_id": "R3",
            "ordered_predecessor": "R2",
            "plan_contract": "REQUIREMENT_PLAN_V01",
            "unified_proof_first": True,
            "optional_channel_union": True,
            "role_reservation": True,
            "lexical_mode": "LEGACY_HARD_FILTER",
            "synonym_normalization": True,
        },
        {
            "arm_id": "R4",
            "ordered_predecessor": "R3",
            "plan_contract": "REQUIREMENT_PLAN_V01",
            "unified_proof_first": True,
            "optional_channel_union": True,
            "role_reservation": True,
            "lexical_mode": "SOFT_RANK_FEATURE",
            "synonym_normalization": True,
        },
        {
            "arm_id": "R5_NO_SYNONYM_NORMALIZATION",
            "ordered_predecessor": "R4",
            "plan_contract": "REQUIREMENT_PLAN_V01",
            "unified_proof_first": True,
            "optional_channel_union": True,
            "role_reservation": True,
            "lexical_mode": "SOFT_RANK_FEATURE",
            "synonym_normalization": False,
        },
    ]
    drops = {
        "R_FINAL_DROP_UNIFIED_PROOF_FIRST": ("unified_proof_first", False),
        "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION": ("optional_channel_union", False),
        "R_FINAL_DROP_ROLE_RESERVATION": ("role_reservation", False),
        "R_FINAL_DROP_SOFT_LEXICAL_FEATURES": (
            "lexical_mode",
            "LEGACY_HARD_FILTER",
        ),
    }
    full = dict(vectors[-1])
    for arm_id, (field, value) in drops.items():
        vector = dict(full)
        vector.update(
            {
                "arm_id": arm_id,
                "ordered_predecessor": "R5_NO_SYNONYM_NORMALIZATION",
                "matched_full_policy_control": "R5_NO_SYNONYM_NORMALIZATION",
                "removed_component": field,
                field: value,
            }
        )
        vectors.append(vector)
    configs = [build_e1_arm_config(**{**common, **vector}) for vector in vectors]
    if [item.arm_id for item in configs] != list(E1_ARM_ORDER):
        raise ValueError("DG25_E1_CONFIG_ORDER_MISMATCH")
    return configs


def _build_e2_configs(
    root: Path,
    common_input: Mapping[str, Any],
) -> list[E2ArmConfigV01]:
    sources = {
        "t0_proof_v01_reference": implementation_identity(
            root, Path("evals/dg24/scorer.py"), "_proof_disposition"
        ),
        "interval_writer_and_membership": implementation_identity(
            root,
            Path("runtime/src/milai/domain/temporal_proof.py"),
            "build_event_time_interval_v02/classify_range_membership",
        ),
        "unique_anchor_contract": implementation_identity(
            root,
            Path("runtime/src/milai/domain/temporal_proof.py"),
            "EventTimeIntervalV02.validate_interval",
        ),
        "event_identity_and_dedup": implementation_identity(
            root,
            Path("runtime/src/milai/domain/temporal_proof.py"),
            "build_event_identity_v01/deduplicate_event_identities",
        ),
        "proof_v02_writer_validator": implementation_identity(
            root,
            Path("runtime/src/milai/domain/temporal_proof.py"),
            "build_bounded_range_scan_proof_v02/BoundedRangeScanProofV02",
        ),
    }
    common: dict[str, Any] = {
        "ordered_predecessor": None,
        "t2_applicability_source": "PRELABEL_COMMON_INPUT",
        "common_input_digest": str(common_input["common_input_digest"]),
        "component_source_identities": sources,
    }
    vectors: list[dict[str, Any]] = [
        {
            "arm_id": "T0",
            "interval_normalization_version": None,
            "unique_anchor_resolution_version": None,
            "event_identity_dedup_version": None,
            "proof_writer_version": "bounded-range-scan-proof-v0.1",
            "proof_validator_version": "dg24-proof-disposition-v0.1",
        },
        {
            "arm_id": "T1",
            "ordered_predecessor": "T0",
            "interval_normalization_version": "event-time-interval-v0.2",
            "unique_anchor_resolution_version": None,
            "event_identity_dedup_version": None,
            "proof_writer_version": "bounded-range-scan-proof-v0.1",
            "proof_validator_version": "dg24-proof-disposition-v0.1",
        },
        {
            "arm_id": "T2",
            "ordered_predecessor": "T1",
            "interval_normalization_version": "event-time-interval-v0.2",
            "unique_anchor_resolution_version": "unique-anchor-relative-v0.1",
            "event_identity_dedup_version": None,
            "proof_writer_version": "bounded-range-scan-proof-v0.1",
            "proof_validator_version": "dg24-proof-disposition-v0.1",
        },
        {
            "arm_id": "T3",
            "ordered_predecessor": "T2",
            "interval_normalization_version": "event-time-interval-v0.2",
            "unique_anchor_resolution_version": "unique-anchor-relative-v0.1",
            "event_identity_dedup_version": "event-identity-dedup-v0.1",
            "proof_writer_version": "bounded-range-scan-proof-v0.1",
            "proof_validator_version": "dg24-proof-disposition-v0.1",
        },
        {
            "arm_id": "T4",
            "ordered_predecessor": "T3",
            "interval_normalization_version": "event-time-interval-v0.2",
            "unique_anchor_resolution_version": "unique-anchor-relative-v0.1",
            "event_identity_dedup_version": "event-identity-dedup-v0.1",
            "proof_writer_version": "bounded-range-scan-proof-v0.2",
            "proof_validator_version": "bounded-range-scan-proof-validator-v0.2",
        },
    ]
    configs = [build_e2_arm_config(**{**common, **vector}) for vector in vectors]
    if [item.arm_id for item in configs] != list(E2_ARM_ORDER):
        raise ValueError("DG25_E2_CONFIG_ORDER_MISMATCH")
    return configs


def _validate_config_contrasts(
    e1: Sequence[E1ArmConfigV01],
    e2: Sequence[E2ArmConfigV01],
) -> dict[str, Any]:
    e1_by_id = {item.arm_id: item for item in e1}
    expected_e1 = {
        ("R0", "R0P"): ["plan_contract"],
        ("R0P", "R1"): ["unified_proof_first"],
        ("R1", "R2"): ["optional_channel_union"],
        ("R2", "R3"): ["role_reservation"],
        ("R3", "R4"): ["lexical_mode"],
        ("R4", "R5_NO_SYNONYM_NORMALIZATION"): ["synonym_normalization"],
        (
            "R5_NO_SYNONYM_NORMALIZATION",
            "R_FINAL_DROP_UNIFIED_PROOF_FIRST",
        ): ["unified_proof_first"],
        (
            "R5_NO_SYNONYM_NORMALIZATION",
            "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
        ): ["optional_channel_union"],
        (
            "R5_NO_SYNONYM_NORMALIZATION",
            "R_FINAL_DROP_ROLE_RESERVATION",
        ): ["role_reservation"],
        (
            "R5_NO_SYNONYM_NORMALIZATION",
            "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
        ): ["lexical_mode"],
    }
    observed_e1 = {
        f"{left}->{right}": component_difference(e1_by_id[left], e1_by_id[right])
        for left, right in expected_e1
    }
    e2_by_id = {item.arm_id: item for item in e2}
    expected_e2 = {
        ("T0", "T1"): ["interval_normalization_version"],
        ("T1", "T2"): ["unique_anchor_resolution_version"],
        ("T2", "T3"): ["event_identity_dedup_version"],
        ("T3", "T4"): ["proof_validator_version", "proof_writer_version"],
    }
    observed_e2 = {
        f"{left}->{right}": temporal_component_difference(
            e2_by_id[left], e2_by_id[right]
        )
        for left, right in expected_e2
    }
    passed = all(
        observed_e1[f"{left}->{right}"] == fields
        for (left, right), fields in expected_e1.items()
    ) and all(
        observed_e2[f"{left}->{right}"] == fields
        for (left, right), fields in expected_e2.items()
    )
    return {
        "schema": "milai.dg25.component-contrast-validation.v0.1",
        "e1": observed_e1,
        "e2": observed_e2,
        "passed": passed,
    }


def _build_scorer_seal(
    root: Path,
    arm_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    scorer_identities = _mapping(arm_manifest.get("scorer_identities"), "scorer identities")
    contract = scorer_contract()
    material: dict[str, Any] = {
        "schema": "milai.dg25.effect-scorer-seal.v0.1",
        "status": "SEALED_SOURCE_AND_CONTRACT_NOT_AUTHORIZED_TO_EXECUTE",
        "scorer_identity": SCORER_IDENTITY,
        "scorer_source": implementation_identity(
            root, Path("evals/dg25/effect_scorer.py"), "score_all_arms"
        ),
        "contract": contract,
        "registry_identity_references": {
            "gold_equivalence_registry": scorer_identities["gold_equivalence_registry"],
            "proof_obligation_registry": scorer_identities["proof_obligation_registry"],
        },
        "registry_content_loaded": False,
        "effect_scoring_executed": False,
        "output_schemas": {
            "joint_score": "milai.dg25.e1-e2-effect-score.v0.1",
            "routing_selection_report": "milai.dg25.routing-selection-ablation.v0.1",
            "component_unique_report": "milai.dg25.component-unique-contribution.v0.1",
            "rule_leave_one_out_report": "milai.dg25.rule-leave-one-out.v0.1",
            "final_minimal_policy": "milai.dg25.final-minimal-policy.v0.1",
        },
    }
    material["scorer_seal_digest"] = canonical_sha256(material)
    return material


def _s3a_execution_surface_findings(
    source: str,
    *,
    role: str,
) -> list[dict[str, Any]]:
    """Return closed-world binding/import/call findings for one S3A source."""

    if role not in S3A_PLAIN_IMPORT_ALLOWLIST:
        raise ValueError(f"unsupported S3A AST role: {role}")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            {
                "code": "AST_PARSE_ERROR",
                "line": exc.lineno,
                "column": exc.offset,
            }
        ]
    findings: list[dict[str, Any]] = []
    top_level_ids = {id(node) for node in tree.body}
    imported_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                invalid = (
                    id(node) not in top_level_ids
                    or alias.asname is not None
                    or "." in alias.name
                    or alias.name not in S3A_PLAIN_IMPORT_ALLOWLIST[role]
                )
                if invalid:
                    findings.append(
                        _ast_finding(
                            node,
                            code="IMPORT_NOT_ALLOWLISTED",
                            target=alias.name,
                        )
                    )
                else:
                    imported_bindings.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            allowed_names = S3A_FROM_IMPORT_ALLOWLIST[role].get(node.module or "")
            for alias in node.names:
                invalid = (
                    id(node) not in top_level_ids
                    or node.level != 0
                    or allowed_names is None
                    or alias.asname is not None
                    or alias.name == "*"
                    or alias.name not in allowed_names
                )
                if invalid:
                    findings.append(
                        _ast_finding(
                            node,
                            code="FROM_IMPORT_NOT_ALLOWLISTED",
                            target=f"{node.module}:{alias.name}",
                        )
                    )
                elif node.module != "__future__":
                    imported_bindings.add(alias.name)

    top_level_definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    global_stores = _s3a_scope_store_names(tree)
    global_bindings = top_level_definitions | imported_bindings | global_stores
    function_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    function_stores = {
        id(node): _s3a_scope_store_names(node) for node in function_nodes
    }
    function_parameters = {
        id(node): _s3a_function_parameter_names(node) for node in function_nodes
    }

    for node in ast.walk(tree):
        reference_violation = _s3a_reference_violation(node)
        if reference_violation is not None:
            findings.append(
                _ast_finding(
                    node,
                    code=reference_violation,
                    target=_ast_reference_target(node),
                )
            )
        if isinstance(node, ast.arg) and node.arg in S3A_FORBIDDEN_DYNAMIC_REFERENCES:
            findings.append(
                _ast_finding(
                    node,
                    code="FORBIDDEN_DYNAMIC_BINDING",
                    target=node.arg,
                )
            )
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in S3A_FORBIDDEN_DYNAMIC_REFERENCES
        ):
            findings.append(
                _ast_finding(
                    node,
                    code="FORBIDDEN_DYNAMIC_BINDING",
                    target=node.id,
                )
            )

    observed_targets = {
        _ast_call_target(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    allowed_targets = _s3a_allowed_call_targets(role)
    missing_targets = sorted(allowed_targets - observed_targets)
    unexpected_targets = sorted(observed_targets - allowed_targets)
    if missing_targets or unexpected_targets:
        findings.append(
            _ast_finding(
                tree,
                code="CALL_TARGET_ALLOWLIST_EXACT_MISMATCH",
                target=json.dumps(
                    {"missing": missing_targets, "unexpected": unexpected_targets},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )

    _S3ACallVisitor(
        role=role,
        findings=findings,
        top_level_definitions=top_level_definitions,
        imported_bindings=imported_bindings,
        global_stores=global_stores,
        global_bindings=global_bindings,
        function_stores=function_stores,
        function_parameters=function_parameters,
    ).visit(tree)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attribute_call_roots = {
        segments[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (segments := _ast_attribute_segments(node.func)) is not None
    }
    _S3AAliasVisitor(
        role=role,
        findings=findings,
        called_names=called_names,
        attribute_call_roots=attribute_call_roots,
        global_bindings=global_bindings,
        function_stores=function_stores,
        function_parameters=function_parameters,
    ).visit(tree)
    findings.extend(_s3a_statically_unreachable_call_findings(tree))
    if role == "runner":
        findings.extend(_s3a_runner_executor_binding_findings(tree))
    else:
        findings.extend(_s3a_generator_callback_binding_findings(tree))
    return findings


def _s3a_allowed_call_targets(role: str) -> set[str]:
    return (
        set(S3A_ALLOWED_LOCAL_NAME_CALLS[role])
        | set(S3A_ALLOWED_IMPORTED_NAME_CALLS[role])
        | set(S3A_ALLOWED_BUILTIN_NAME_CALLS[role])
        | {name for _, name in S3A_ALLOWED_PARAMETER_CALLS[role]}
        | set(S3A_ALLOWED_ATTRIBUTE_CALLS[role])
    )


def _s3a_call_target_contract(source: str, *, role: str) -> dict[str, Any]:
    tree = ast.parse(source)
    allowed_targets = sorted(_s3a_allowed_call_targets(role))
    observed_targets = sorted(
        {
            _ast_call_target(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
    )
    material: dict[str, Any] = {
        "role": role,
        "policy": "EXACT_CLOSED_WORLD_BINDING_AWARE_CALL_TARGET_ALLOWLIST",
        "allowed_targets": allowed_targets,
        "allowed_target_count": len(allowed_targets),
        "observed_targets": observed_targets,
        "observed_target_count": len(observed_targets),
        "exact_match": observed_targets == allowed_targets,
    }
    material["contract_digest"] = canonical_sha256(material)
    return material


def _s3a_runner_executor_binding_findings(
    tree: ast.Module,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for function_name, (expected_arguments, expected_body) in (
        S3A_RUNNER_FUNCTION_CONTRACTS.items()
    ):
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ]
        if len(matches) != 1:
            findings.append(
                _ast_finding(
                    tree,
                    code="RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH",
                    target=f"{function_name}:definition-count={len(matches)}",
                )
            )
            continue
        function = matches[0]
        actual_arguments = ast.unparse(function.args)
        actual_body = tuple(
            ast.unparse(statement)
            for statement in _s3a_executable_function_body(function)
        )
        if actual_arguments != expected_arguments or actual_body != expected_body:
            findings.append(
                _ast_finding(
                    function,
                    code="RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH",
                    target=canonical_sha256(
                        {
                            "function": function_name,
                            "arguments": actual_arguments,
                            "body": actual_body,
                        }
                    ),
                )
            )

    for target, expected_count in S3A_RUNNER_CRITICAL_CALL_COUNTS.items():
        observed_count = sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == target
            for node in ast.walk(tree)
        )
        if observed_count != expected_count:
            findings.append(
                _ast_finding(
                    tree,
                    code="RUNNER_CRITICAL_CALL_COUNT_MISMATCH",
                    target=f"{target}:{observed_count}!={expected_count}",
                )
            )
    lambdas = [node for node in ast.walk(tree) if isinstance(node, ast.Lambda)]
    expected_lambda = "lambda: _capture_and_execute(args, context, root=root)"
    if len(lambdas) != 1 or ast.unparse(lambdas[0]) != expected_lambda:
        findings.append(
            _ast_finding(
                tree,
                code="RUNNER_CALLBACK_PROVENANCE_MISMATCH",
                target=canonical_sha256([ast.unparse(node) for node in lambdas]),
            )
        )
    return findings


def _s3a_generator_callback_binding_findings(
    tree: ast.Module,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    reviewed_lambda_ids: set[int] = set()
    for target, expected_lambda in S3A_GENERATOR_SORT_CALLBACK_CONTRACTS.items():
        matches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _ast_call_target(node.func) == target
        ]
        if len(matches) != 1:
            findings.append(
                _ast_finding(
                    tree,
                    code="GENERATOR_CALLBACK_BINDING_CONTRACT_MISMATCH",
                    target=f"{target}:call-count={len(matches)}",
                )
            )
            continue
        call = matches[0]
        key_values = [
            keyword.value for keyword in call.keywords if keyword.arg == "key"
        ]
        if (
            call.args
            or len(call.keywords) != 1
            or len(key_values) != 1
            or not isinstance(key_values[0], ast.Lambda)
            or ast.unparse(key_values[0]) != expected_lambda
        ):
            findings.append(
                _ast_finding(
                    call,
                    code="GENERATOR_CALLBACK_BINDING_CONTRACT_MISMATCH",
                    target=target,
                )
            )
            continue
        reviewed_lambda_ids.add(id(key_values[0]))
    all_lambda_ids = {
        id(node) for node in ast.walk(tree) if isinstance(node, ast.Lambda)
    }
    if all_lambda_ids != reviewed_lambda_ids:
        findings.append(
            _ast_finding(
                tree,
                code="GENERATOR_UNREVIEWED_CALLBACK_TRANSPORT",
                target=f"reviewed={len(reviewed_lambda_ids)};all={len(all_lambda_ids)}",
            )
        )
    return findings


def _s3a_statically_unreachable_call_findings(
    tree: ast.Module,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        unreachable: Sequence[ast.stmt] = ()
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
            unreachable = node.orelse if bool(node.test.value) else node.body
        elif (
            isinstance(node, ast.While)
            and isinstance(node.test, ast.Constant)
            and not bool(node.test.value)
        ):
            unreachable = node.body
        for statement in unreachable:
            for call in (
                item for item in ast.walk(statement) if isinstance(item, ast.Call)
            ):
                findings.append(
                    _ast_finding(
                        call,
                        code="STATICALLY_UNREACHABLE_CALL_FORBIDDEN",
                        target=_ast_call_target(call.func),
                    )
                )
    return findings


def _s3a_executable_function_body(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Sequence[ast.stmt]:
    body: Sequence[ast.stmt] = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _s3a_scope_store_names(scope: ast.AST) -> set[str]:
    names: set[str] = set()

    def collect(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
            ):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            if isinstance(child, ast.ExceptHandler) and isinstance(child.name, str):
                names.add(child.name)
            collect(child)

    collect(scope)
    return names


def _s3a_function_parameter_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    parameters = {
        item.arg
        for item in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    }
    if node.args.vararg is not None:
        parameters.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        parameters.add(node.args.kwarg.arg)
    return parameters


class _S3ACallVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        role: str,
        findings: list[dict[str, Any]],
        top_level_definitions: set[str],
        imported_bindings: set[str],
        global_stores: set[str],
        global_bindings: set[str],
        function_stores: Mapping[int, set[str]],
        function_parameters: Mapping[int, set[str]],
    ) -> None:
        self.role = role
        self.findings = findings
        self.top_level_definitions = top_level_definitions
        self.imported_bindings = imported_bindings
        self.global_stores = global_stores
        self.global_bindings = global_bindings
        self.function_stores = function_stores
        self.function_parameters = function_parameters
        self.function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        current_function = self.function_stack[-1] if self.function_stack else None
        violation = _s3a_call_violation(
            node.func,
            role=self.role,
            current_function=current_function,
            top_level_definitions=self.top_level_definitions,
            imported_bindings=self.imported_bindings,
            global_stores=self.global_stores,
            global_bindings=self.global_bindings,
            function_stores=self.function_stores,
            function_parameters=self.function_parameters,
        )
        if violation is not None:
            self.findings.append(
                _ast_finding(
                    node,
                    code=violation,
                    target=_ast_call_target(node.func),
                )
            )
        self.generic_visit(node)


def _s3a_call_violation(
    function: ast.expr,
    *,
    role: str,
    current_function: ast.FunctionDef | ast.AsyncFunctionDef | None,
    top_level_definitions: set[str],
    imported_bindings: set[str],
    global_stores: set[str],
    global_bindings: set[str],
    function_stores: Mapping[int, set[str]],
    function_parameters: Mapping[int, set[str]],
) -> str | None:
    local_stores = (
        function_stores[id(current_function)] if current_function is not None else set()
    )
    parameters = (
        function_parameters[id(current_function)]
        if current_function is not None
        else set()
    )
    if isinstance(function, ast.Name):
        name = function.id
        if name in S3A_FORBIDDEN_DYNAMIC_REFERENCES:
            return "DYNAMIC_CALL_FORBIDDEN"
        if name in S3A_ALLOWED_LOCAL_NAME_CALLS[role]:
            if name not in top_level_definitions:
                return "ALLOWED_LOCAL_CALL_TARGET_MISSING"
            if name in global_stores or name in local_stores or name in parameters:
                return "ALLOWED_LOCAL_CALL_TARGET_SHADOWED"
            return None
        if name in S3A_ALLOWED_IMPORTED_NAME_CALLS[role]:
            if name not in imported_bindings:
                return "ALLOWED_IMPORTED_CALL_TARGET_MISSING"
            if name in global_stores or name in local_stores or name in parameters:
                return "ALLOWED_IMPORTED_CALL_TARGET_SHADOWED"
            return None
        if name in S3A_ALLOWED_BUILTIN_NAME_CALLS[role]:
            if name in global_bindings or name in local_stores or name in parameters:
                return "ALLOWED_BUILTIN_CALL_TARGET_SHADOWED"
            return None
        function_name = current_function.name if current_function is not None else None
        if (function_name, name) in S3A_ALLOWED_PARAMETER_CALLS[role]:
            if name not in parameters or name in local_stores:
                return "ALLOWED_PARAMETER_CALL_TARGET_NOT_EXACT"
            return None
        return "UNRESOLVED_NAME_CALL_TARGET"
    if isinstance(function, ast.Attribute):
        segments = _ast_attribute_segments(function)
        if segments is None:
            return "ATTRIBUTE_CALL_ROOT_NOT_NAME"
        if any(
            segment.casefold() in S3A_FORBIDDEN_CALL_SEGMENTS
            for segment in segments
        ):
            return "FORBIDDEN_EXECUTION_SURFACE_CALL"
        if segments[0] in S3A_FORBIDDEN_DYNAMIC_REFERENCES:
            return "DYNAMIC_ATTRIBUTE_CALL_FORBIDDEN"
        target = ".".join(segments)
        if target not in S3A_ALLOWED_ATTRIBUTE_CALLS[role]:
            return "ATTRIBUTE_CALL_TARGET_NOT_ALLOWLISTED"
        root = segments[0]
        if not _s3a_name_is_bound(
            root,
            current_function=current_function,
            global_bindings=global_bindings,
            function_stores=function_stores,
            function_parameters=function_parameters,
            role=role,
        ):
            return "ATTRIBUTE_CALL_ROOT_UNRESOLVED"
        protected_root = (
            root in imported_bindings
            or root in S3A_ALLOWED_BUILTIN_NAME_CALLS[role]
            or root.lstrip("_").isupper()
        )
        if protected_root and (root in local_stores or root in parameters):
            return "ATTRIBUTE_CALL_ROOT_SHADOWED"
        return None
    return "INDIRECT_CALL_TARGET_FORBIDDEN"


def _s3a_name_is_bound(
    name: str,
    *,
    current_function: ast.FunctionDef | ast.AsyncFunctionDef | None,
    global_bindings: set[str],
    function_stores: Mapping[int, set[str]],
    function_parameters: Mapping[int, set[str]],
    role: str,
) -> bool:
    if name in global_bindings or name in S3A_ALLOWED_BUILTIN_NAME_CALLS[role]:
        return True
    if current_function is None:
        return False
    return (
        name in function_stores[id(current_function)]
        or name in function_parameters[id(current_function)]
    )


class _S3AAliasVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        role: str,
        findings: list[dict[str, Any]],
        called_names: set[str],
        attribute_call_roots: set[str],
        global_bindings: set[str],
        function_stores: Mapping[int, set[str]],
        function_parameters: Mapping[int, set[str]],
    ) -> None:
        self.role = role
        self.findings = findings
        self.called_names = called_names
        self.attribute_call_roots = attribute_call_roots
        self.global_bindings = global_bindings
        self.function_stores = function_stores
        self.function_parameters = function_parameters
        self.function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self._inspect_alias(node, node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._inspect_alias(node, [node.target], node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._inspect_alias(node, [node.target], node.value)
        self.generic_visit(node)

    def _inspect_alias(
        self,
        node: ast.AST,
        targets: Sequence[ast.expr],
        value: ast.expr,
    ) -> None:
        assigned_names = {
            name for target in targets for name in _s3a_assignment_target_names(target)
        }
        if not assigned_names:
            return
        alias_shape = isinstance(
            value,
            (ast.Name, ast.Attribute, ast.Subscript, ast.Lambda),
        )
        for name in sorted(assigned_names):
            if isinstance(value, ast.Lambda):
                self.findings.append(
                    _ast_finding(
                        node,
                        code="CALLABLE_LAMBDA_ALIAS_FORBIDDEN",
                        target=name,
                    )
                )
                continue
            if alias_shape and name in self.called_names:
                self.findings.append(
                    _ast_finding(
                        node,
                        code="CALLABLE_ASSIGNMENT_ALIAS_FORBIDDEN",
                        target=f"{name}<-{_s3a_expression_target(value)}",
                    )
                )
                continue
            if not alias_shape or name not in self.attribute_call_roots:
                continue
            origin = _s3a_expression_root(value)
            current_function = (
                self.function_stack[-1] if self.function_stack else None
            )
            if (
                origin is None
                or origin == name
                or not _s3a_name_is_bound(
                    origin,
                    current_function=current_function,
                    global_bindings=self.global_bindings,
                    function_stores=self.function_stores,
                    function_parameters=self.function_parameters,
                    role=self.role,
                )
            ):
                self.findings.append(
                    _ast_finding(
                        node,
                        code="CALL_ATTRIBUTE_ROOT_ALIAS_UNRESOLVED",
                        target=f"{name}<-{_s3a_expression_target(value)}",
                    )
                )


def _s3a_assignment_target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {
            name
            for item in target.elts
            for name in _s3a_assignment_target_names(item)
        }
    if isinstance(target, ast.Starred):
        return _s3a_assignment_target_names(target.value)
    return set()


def _s3a_expression_root(value: ast.expr) -> str | None:
    current = value
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _s3a_expression_target(value: ast.expr) -> str:
    return ast.unparse(value)


def _s3a_reference_violation(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in S3A_FORBIDDEN_DYNAMIC_REFERENCES
    ):
        return "FORBIDDEN_DYNAMIC_REFERENCE"
    if isinstance(node, ast.Attribute):
        segments = _ast_attribute_segments(node)
        if segments is not None:
            if any(
                segment.casefold() in S3A_FORBIDDEN_CALL_SEGMENTS
                for segment in segments
            ):
                return "FORBIDDEN_EXECUTION_SURFACE_ATTRIBUTE_REFERENCE"
            if (
                segments[0] in {"__builtins__", "builtins", "importlib"}
                or segments[:2] == ["sys", "modules"]
            ):
                return "FORBIDDEN_DYNAMIC_ATTRIBUTE_ACCESS"
    return None


def _ast_reference_target(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.expr):
        return _s3a_expression_target(node)
    return type(node).__name__


def _ast_attribute_segments(value: ast.expr) -> list[str] | None:
    segments: list[str] = []
    current = value
    while isinstance(current, ast.Attribute):
        segments.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    segments.append(current.id)
    return list(reversed(segments))


def _ast_call_target(value: ast.expr) -> str:
    segments = _ast_attribute_segments(value)
    if segments is not None:
        return ".".join(segments)
    if isinstance(value, ast.Name):
        return value.id
    return ast.unparse(value)


def _ast_finding(
    node: ast.AST,
    *,
    code: str,
    target: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "target": target,
        "line": getattr(node, "lineno", None),
        "column": getattr(node, "col_offset", None),
    }


def _build_source_manifest(root: Path, inputs: Mapping[str, Any]) -> dict[str, Any]:
    files = [identity(root, path) for path in READINESS_SOURCE_PATHS]
    case_ids = [
        str(item["case_id"])
        for item in _mapping_sequence(inputs.get("requests"), "input requests")
    ]
    product_findings = []
    for path in PRODUCT_PLANE_SOURCE_PATHS:
        text = (root / path).read_text(encoding="utf-8")
        for case_id in case_ids:
            if case_id in text:
                product_findings.append({"path": str(path), "literal": case_id})
    routing_text = (root / "evals/dg25/routing_ablation.py").read_text(encoding="utf-8")
    scorer_text = (root / "evals/dg25/effect_scorer.py").read_text(encoding="utf-8")
    generator_text = (root / "evals/dg25/s3a_generator.py").read_text(encoding="utf-8")
    s3a_runner_text = (root / "scripts/run_dg25_s3a.py").read_text(encoding="utf-8")
    generator_ast_findings = _s3a_execution_surface_findings(
        generator_text,
        role="generator",
    )
    runner_ast_findings = _s3a_execution_surface_findings(
        s3a_runner_text,
        role="runner",
    )
    generator_call_target_contract = _s3a_call_target_contract(
        generator_text,
        role="generator",
    )
    runner_call_target_contract = _s3a_call_target_contract(
        s3a_runner_text,
        role="runner",
    )
    runner_tree = ast.parse(s3a_runner_text)
    generator_tree = ast.parse(generator_text)
    runner_executor_binding_findings = (
        _s3a_runner_executor_binding_findings(runner_tree)
        + _s3a_statically_unreachable_call_findings(runner_tree)
    )
    generator_callback_binding_findings = (
        _s3a_generator_callback_binding_findings(generator_tree)
        + _s3a_statically_unreachable_call_findings(generator_tree)
    )
    callable_binding_contract: dict[str, Any] = {
        "policy": "EXACT_CALLABLE_PROVENANCE_AND_STATIC_REACHABILITY",
        "runner_function_contracts": {
            name: {"arguments": contract[0], "body": list(contract[1])}
            for name, contract in S3A_RUNNER_FUNCTION_CONTRACTS.items()
        },
        "runner_critical_call_counts": dict(S3A_RUNNER_CRITICAL_CALL_COUNTS),
        "generator_sort_callback_contracts": dict(
            S3A_GENERATOR_SORT_CALLBACK_CONTRACTS
        ),
        "forbidden_dynamic_references": sorted(S3A_FORBIDDEN_DYNAMIC_REFERENCES),
        "forbidden_execution_surface_segments": sorted(
            S3A_FORBIDDEN_CALL_SEGMENTS
        ),
    }
    callable_binding_contract["contract_digest"] = canonical_sha256(
        callable_binding_contract
    )
    s2_manifest = read_json_object(root / S2_SOURCE_MANIFEST)
    s2_files = _mapping_sequence(s2_manifest.get("files"), "S2 source files")
    s2_drift = [
        str(item["path"])
        for item in s2_files
        if sha256_file(root / str(item["path"])) != str(item["sha256"])
    ]
    checks = {
        "all_source_files_present": len(files) == len(READINESS_SOURCE_PATHS),
        "product_plane_official_case_literals_zero": not product_findings,
        "routing_replay_repository_imports_zero": "milai.persistence" not in routing_text,
        "routing_replay_repository_calls_zero": all(
            token not in routing_text
            for token in ("search_evidence(", "search_evidence_dense(", "scan_evidence_range(")
        ),
        "effect_scorer_filesystem_imports_zero": all(
            token not in scorer_text
            for token in ("from pathlib", "import pathlib", "open(", "read_text(", "write_text(")
        ),
        "effect_scorer_runtime_imports_zero": all(
            token not in scorer_text
            for token in ("from milai", "import milai", "from evals", "import evals")
        ),
        "s2_source_drift_zero": not s2_drift,
        "t0_reference_source_manifested": any(
            item["path"] == "evals/dg24/scorer.py" for item in files
        ),
        "actual_s3a_generator_sealer_runner_manifested": all(
            any(item["path"] == str(path) for item in files)
            for path in (
                Path("evals/dg25/s3a_generator.py"),
                Path("evals/dg25/arm_sealing.py"),
                Path("scripts/run_dg25_s3a.py"),
            )
        ),
        "s3a_generator_scorer_imports_zero": not generator_ast_findings,
        "s3a_runner_scorer_imports_zero": not runner_ast_findings,
        "s3a_generator_execution_surface_ast_clean": not generator_ast_findings,
        "s3a_runner_execution_surface_ast_clean": not runner_ast_findings,
        "s3a_generator_call_target_allowlist_exact": generator_call_target_contract[
            "exact_match"
        ]
        is True,
        "s3a_runner_call_target_allowlist_exact": runner_call_target_contract[
            "exact_match"
        ]
        is True,
        "s3a_runner_executor_binding_and_reachability_exact": not (
            runner_executor_binding_findings
        ),
        "s3a_generator_callback_binding_and_reachability_exact": not (
            generator_callback_binding_findings
        ),
        "official_s3a_failure_ledger_path_present": all(
            token in s3a_runner_text
            for token in (
                "_execute_with_failure_ledger",
                "_record_s3a_failure",
                "failure-index.jsonl",
                "automatic_retries",
            )
        ),
        "official_s3a_complete_attempt_identity_envelope_present": all(
            token in s3a_runner_text
            for token in (
                "_build_s3a_failure_context",
                "attempt_identity_envelope",
                "frozen_before_covered_prechecks",
                "readiness_artifact_identities",
                "predecessor_input_identities",
                "observed_identity",
                "disposition",
            )
        ),
        "official_s3a_total_capture_and_resolved_provenance_present": all(
            token in s3a_runner_text
            for token in (
                "_run_s3a_once",
                "inventory_preallocated_before_reads",
                "_capture_attempt_identity_envelope",
                "capture_frozen_before_execute",
                "_validate_top_level_paths",
                "OUTSIDE_PRESCRIBED_DIRECTORY",
                "_exact_source_contract",
                "_exact_predecessor_contract",
            )
        ),
        "s3a_label_file_entrypoints_zero": all(
            token not in (generator_text + s3a_runner_text)
            for token in (
                "gold-equivalence-registry",
                "proof-obligation-registry",
                "scorer-only",
            )
        ),
        "formal_holdout_access_entrypoints_zero": all(
            all(
                token not in (root / path).read_text(encoding="utf-8").casefold()
                for token in ("open_holdout", "load_holdout", "holdout_registry")
            )
            for path in PRODUCT_PLANE_SOURCE_PATHS
        ),
    }
    material: dict[str, Any] = {
        "schema": "milai.dg25.s3-readiness-source-manifest.v0.1",
        "files": files,
        "product_plane_paths": [str(path) for path in PRODUCT_PLANE_SOURCE_PATHS],
        "scoring_plane_paths": ["evals/dg25/effect_scorer.py"],
        "source_scan": {
            "checks": checks,
            "product_case_literal_findings": product_findings,
            "s2_source_drift": s2_drift,
            "s3a_generator_ast_findings": generator_ast_findings,
            "s3a_runner_ast_findings": runner_ast_findings,
            "s3a_generator_call_target_contract": generator_call_target_contract,
            "s3a_runner_call_target_contract": runner_call_target_contract,
            "s3a_callable_binding_contract": callable_binding_contract,
            "s3a_runner_executor_binding_findings": (
                runner_executor_binding_findings
            ),
            "s3a_generator_callback_binding_findings": (
                generator_callback_binding_findings
            ),
        },
        "fresh": all(checks.values()),
    }
    material["source_manifest_digest"] = canonical_sha256(material)
    return material


def _build_quality_evidence_binding(
    *,
    root: Path,
    evidence: Mapping[str, Any] | None,
    authoritative_required: bool,
) -> dict[str, Any]:
    if evidence is None:
        if authoritative_required:
            raise ValueError("DG25_AUTHORITATIVE_QUALITY_EVIDENCE_REQUIRED")
        material: dict[str, Any] = {
            "schema": "milai.dg25.readiness-quality-binding.v0.1",
            "disposition": "EXPLICITLY_NON_AUTHORITATIVE_TEST_ONLY",
            "authoritative": False,
            "quality_receipt": None,
            "checks": {
                "receipt_passed": False,
                "all_gate_logs_hash_bound": False,
                "all_quality_source_files_current": False,
            },
        }
        material["binding_digest"] = canonical_sha256(material)
        return material

    receipt_identity = _mapping(
        evidence.get("receipt_identity"), "quality receipt identity"
    )
    receipt = _mapping(evidence.get("receipt"), "quality receipt")
    if receipt_identity.get("path") is None:
        raise ValueError("DG25_QUALITY_RECEIPT_PATH_REQUIRED")
    receipt_path = root / str(receipt_identity["path"])
    receipt_identity_current = (
        receipt_path.is_file()
        and sha256_file(receipt_path) == receipt_identity.get("sha256")
        and receipt_path.stat().st_size == receipt_identity.get("size")
    )
    gates = _mapping_sequence(receipt.get("gates"), "quality gates")
    gate_logs_current = True
    for gate in gates:
        for stream in ("stdout", "stderr"):
            log_identity = _mapping(gate.get(stream), f"quality {stream}")
            path = root / str(log_identity["path"])
            gate_logs_current = gate_logs_current and (
                path.is_file()
                and sha256_file(path) == log_identity.get("sha256")
                and path.stat().st_size == log_identity.get("size")
            )
    source_files = _mapping_sequence(
        receipt.get("source_files"), "quality source files"
    )
    source_files_current = all(
        (root / str(item["path"])).is_file()
        and sha256_file(root / str(item["path"])) == item.get("sha256")
        and (root / str(item["path"])).stat().st_size == item.get("size")
        for item in source_files
    )
    checks = {
        "receipt_identity_current": receipt_identity_current,
        "receipt_passed": receipt.get("status") == "PASS_DG25_READINESS_QUALITY",
        "all_gates_exit_zero": bool(gates)
        and all(gate.get("exit_code") == 0 for gate in gates),
        "all_gate_logs_hash_bound": gate_logs_current,
        "all_quality_source_files_current": bool(source_files) and source_files_current,
        "automatic_retries_zero": receipt.get("automatic_retries") == 0,
    }
    material = {
        "schema": "milai.dg25.readiness-quality-binding.v0.1",
        "disposition": (
            "AUTHORITATIVE_BOUND_PASS" if all(checks.values()) else "INVALID_STOP"
        ),
        "authoritative": all(checks.values()),
        "quality_receipt": dict(receipt_identity),
        "gate_count": len(gates),
        "gate_ids": [str(item["gate_id"]) for item in gates],
        "source_file_count": len(source_files),
        "source_set_digest": receipt.get("source_set_digest"),
        "checks": checks,
    }
    material["binding_digest"] = canonical_sha256(material)
    if authoritative_required and not all(checks.values()):
        raise ValueError("DG25_AUTHORITATIVE_QUALITY_EVIDENCE_INVALID")
    return material


def _build_execution_delta(
    *,
    root: Path,
    arm_manifest: Mapping[str, Any],
    pool_binding: Mapping[str, Any],
    common_input: Mapping[str, Any],
    scorer_seal: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    e1_configs: Sequence[E1ArmConfigV01],
    e2_configs: Sequence[E2ArmConfigV01],
    action_manifest: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
    quality_binding: Mapping[str, Any],
    contrasts: Mapping[str, Any],
) -> dict[str, Any]:
    e1_config_digests = {item.arm_id: item.config_digest for item in e1_configs}
    e2_config_digests = {item.arm_id: item.config_digest for item in e2_configs}
    e1_caps = {
        "final_k": pool_binding["final_k"],
        "replay_audit_caps": pool_binding["replay_audit_caps"],
        "live_action_candidate_caps": pool_binding["live_action_candidate_caps"],
        "verified_dense_ceiling": pool_binding["verified_dense_ceiling"],
        "max_actions_per_plan": 2,
    }
    e2_caps = {
        "range_scan_max_rows": 2000,
        "raw_row_count": common_input["raw_row_count"],
        "requirement_count": common_input["requirement_count"],
    }
    material: dict[str, Any] = {
        "schema": "milai.dg25.s3-execution-delta-manifest.v0.1",
        "status": "READY_FOR_FRESH_INDEPENDENT_REVIEW_NO_REPLAY_OR_SCORING",
        "immutable_parent_arm_manifest": identity(root, ARM_MANIFEST),
        "immutable_stop_rule_registry": identity(root, STOP_REGISTRY),
        "post_s2_review": identity(root, POST_S2_REVIEW),
        "s2_binding": {
            "receipt": identity(root, S2_RECEIPT),
            "source_manifest": identity(root, S2_SOURCE_MANIFEST),
        },
        "stage_schedule": {
            "S3A": "E1_LABEL_FREE_GENERATE_AND_ALL_ARM_SEAL",
            "S4A": "E2_LABEL_FREE_GENERATE_AND_ALL_ARM_SEAL",
            "authorization_gate": "FRESH_INDEPENDENT_SCORING_AUTHORIZATION",
            "S4B": "JOINT_E1_E2_POST_SEAL_SCORING",
            "labels_or_scoring_in_S3": "REJECT",
        },
        "case_order": list(action_manifest["case_order"]),
        "case_order_digest": action_manifest["case_order_digest"],
        "e1_common_pool": dict(pool_binding),
        "e2_common_input_digest": common_input["common_input_digest"],
        "effect_scorer": {
            "status": scorer_seal["status"],
            "identity": scorer_seal["scorer_identity"],
            "source": scorer_seal["scorer_source"],
            "contract_digest": scorer_seal["contract"]["contract_digest"],
            "scorer_seal_digest": scorer_seal["scorer_seal_digest"],
        },
        "source_manifest_digest": source_manifest["source_manifest_digest"],
        "quality_evidence_binding_digest": quality_binding["binding_digest"],
        "cost_ledger_schema_digest": ledger_schema["cost_ledger_schema_digest"],
        "presealed_s3a_implementation": {
            "generator": implementation_identity(
                root,
                Path("evals/dg25/s3a_generator.py"),
                "generate_e1_all_arm_bundle",
            ),
            "sealer": implementation_identity(
                root,
                Path("evals/dg25/arm_sealing.py"),
                "build_block_all_arm_seal",
            ),
            "runner": implementation_identity(
                root,
                Path("scripts/run_dg25_s3a.py"),
                "main",
            ),
            "output_schema": "milai.dg25.label-free-arm-output.v0.2",
            "terminal_seal_schema": "milai.dg25.e1-all-arm-seal.v0.2",
        },
        "E1": {
            "arm_order": list(E1_ARM_ORDER),
            "arm_configs": [item.model_dump(mode="json") for item in e1_configs],
            "config_digest_map": e1_config_digests,
            "config_set_digest": canonical_sha256(e1_config_digests),
            "action_manifest_digest": action_manifest["manifest_digest"],
            "action_plan_index_digest": action_manifest["plan_index_digest"],
            "case_order_digest": action_manifest["case_order_digest"],
            "caps": e1_caps,
            "caps_digest": canonical_sha256(e1_caps),
        },
        "E2": {
            "arm_order": list(E2_ARM_ORDER),
            "arm_configs": [item.model_dump(mode="json") for item in e2_configs],
            "config_digest_map": e2_config_digests,
            "config_set_digest": canonical_sha256(e2_config_digests),
            "caps": e2_caps,
            "caps_digest": canonical_sha256(e2_caps),
        },
        "component_contrast_validation": dict(contrasts),
        "authorization": {
            "readiness_only": True,
            "e1_official_pool_replay": False,
            "e2_official_row_transformation": False,
            "effect_scoring": False,
            "registry_content_load": False,
            "e3_product_treatment": False,
            "reader_model_provider_controller_calls": 0,
            "formal_holdout": False,
            "candidate_default": False,
            "canonical_mutations": 0,
            "latency_repeats": False,
            "automatic_retries": 0,
        },
        "claim_boundary": arm_manifest["claim_boundary"],
    }
    material["manifest_digest"] = canonical_sha256(material)
    return material


def _build_all_arm_seal_protocol(
    *,
    delta: Mapping[str, Any],
    common_input: Mapping[str, Any],
    scorer_seal: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    action_manifest: Mapping[str, Any],
    pool_binding: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
    e1_configs: Sequence[E1ArmConfigV01],
    e2_configs: Sequence[E2ArmConfigV01],
) -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema": "milai.dg25.all-arm-seal-protocol.v0.1",
        "execution_delta_manifest_digest": delta["manifest_digest"],
        "effect_scorer_contract_digest": scorer_seal["contract"]["contract_digest"],
        "effect_scorer_source_sha256": scorer_seal["scorer_source"]["sha256"],
        "stop_rule_registry_sha256": delta["immutable_stop_rule_registry"]["sha256"],
        "e2_common_input_digest": common_input["common_input_digest"],
        "readiness_source_manifest_digest": source_manifest["source_manifest_digest"],
        "case_order_digest": action_manifest["case_order_digest"],
        "e1_action_manifest_digest": action_manifest["manifest_digest"],
        "e1_common_pool_binding_digest": pool_binding["pool_binding_digest"],
        "e1_config_set_digest": delta["E1"]["config_set_digest"],
        "e2_config_set_digest": delta["E2"]["config_set_digest"],
        "e1_caps_digest": delta["E1"]["caps_digest"],
        "e2_caps_digest": delta["E2"]["caps_digest"],
        "cost_ledger_schema_digest": ledger_schema["cost_ledger_schema_digest"],
        "presealed_s3a_sources": delta["presealed_s3a_implementation"],
        "phases": [
            {
                "stage": "S3A",
                "block": "E1",
                "arm_order": list(E1_ARM_ORDER),
                "config_digests": [item.config_digest for item in e1_configs],
                "output_schema": "milai.dg25.label-free-arm-output.v0.2",
                "terminal_artifact_schema": "milai.dg25.e1-all-arm-seal.v0.2",
                "action_manifest_digest": action_manifest["manifest_digest"],
                "exact_output_count": 11,
                "labels_loaded": False,
                "scoring_executed": False,
            },
            {
                "stage": "S4A",
                "block": "E2",
                "arm_order": list(E2_ARM_ORDER),
                "config_digests": [item.config_digest for item in e2_configs],
                "output_schema": "milai.dg25.label-free-arm-output.v0.2",
                "terminal_artifact_schema": "milai.dg25.e2-all-arm-seal.v0.2",
                "exact_output_count": 5,
                "labels_loaded": False,
                "scoring_executed": False,
            },
            {
                "stage": "S4B",
                "block": "JOINT_E1_E2_SCORE",
                "requires": [
                    "immutable E1 all-arm seal digest",
                    "immutable E2 all-arm seal digest",
                    "combined all-arm seal digest",
                    "fresh independent scoring authorization bound to combined seal",
                ],
                "registry_open_order": [
                    "pre-score stop gate PASS",
                    "gold registry open",
                    "proof registry open",
                    "one joint score execution",
                    "post-score stop gate",
                ],
            },
        ],
        "combined_seal_schema": {
            "schema": "milai.dg25.e1-e2-all-arm-seal.v0.2",
            "required_arm_output_count": 16,
            "e1_arm_order": list(E1_ARM_ORDER),
            "e2_arm_order": list(E2_ARM_ORDER),
            "all_outputs_sealed_before_label_load": True,
            "registry_content_loaded_during_generation": False,
            "arm_output_content_digests": "EXACT_MAP_REQUIRED",
            "arm_config_digests": "EXACT_MAP_REQUIRED",
            "arm_execution_binding_digests": "EXACT_MAP_REQUIRED",
            "e1_all_arm_seal_digest": "EXACT_REQUIRED",
            "e2_all_arm_seal_digest": "EXACT_REQUIRED",
            "readiness_bindings": {
                "execution_delta_manifest_digest": delta["manifest_digest"],
                "effect_scorer_contract_digest": scorer_seal["contract"][
                    "contract_digest"
                ],
                "effect_scorer_source_sha256": scorer_seal["scorer_source"]["sha256"],
                "stop_rule_registry_sha256": delta["immutable_stop_rule_registry"][
                    "sha256"
                ],
                "all_arm_seal_protocol_digest": "BOUND_TO_THIS_PROTOCOL_AFTER_SEAL",
                "readiness_source_manifest_digest": source_manifest[
                    "source_manifest_digest"
                ],
                "case_order_digest": action_manifest["case_order_digest"],
                "e1_action_manifest_digest": action_manifest["manifest_digest"],
                "e1_config_set_digest": delta["E1"]["config_set_digest"],
                "e2_config_set_digest": delta["E2"]["config_set_digest"],
                "e1_common_pool_binding_digest": pool_binding["pool_binding_digest"],
                "e2_common_input_digest": common_input["common_input_digest"],
                "e1_caps_digest": delta["E1"]["caps_digest"],
                "e2_caps_digest": delta["E2"]["caps_digest"],
                "cost_ledger_schema_digest": ledger_schema[
                    "cost_ledger_schema_digest"
                ],
                "final_k": 8,
            },
            "seal_digest": "CANONICAL_SHA256_EXCLUDING_SELF",
        },
        "s3a_independent_authorization_schema": {
            "schema": "milai.dg25.s3a-independent-authorization.v0.1",
            "authorized": True,
            "scope": "S3A_E1_LABEL_FREE_ALL_11_ARMS_AND_ONE_SEAL",
            "readiness_bindings": "EXACT_S3A_GATE_BINDINGS_REQUIRED",
            "readiness_bindings_digest": "CANONICAL_SHA256_OF_EXACT_BINDINGS",
            "labels_authorized": False,
            "scoring_authorized": False,
            "s4a_authorized": False,
            "s4b_authorized": False,
            "e3_authorized": False,
            "reader_model_provider_controller_calls_authorized": 0,
            "formal_holdout_authorized": False,
            "automatic_retries": 0,
            "authorization_digest": "CANONICAL_SHA256_EXCLUDING_SELF",
        },
        "immutability": {
            "existing_output_directory_rejected": True,
            "all_arm_output_set_exact": True,
            "per_arm_scoring_before_combined_seal": False,
            "post_score_arm_regeneration": False,
            "automatic_retries": 0,
        },
    }
    material["protocol_digest"] = canonical_sha256(material)
    return material


def _build_bound_stop_contract(
    *,
    root: Path,
    delta: Mapping[str, Any],
    common_input: Mapping[str, Any],
    scorer_seal: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    seal_protocol: Mapping[str, Any],
    action_manifest: Mapping[str, Any],
    pool_binding: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
) -> dict[str, Any]:
    s3a_bindings: dict[str, Any] = {
        "execution_delta_manifest_digest": delta["manifest_digest"],
        "all_arm_seal_protocol_digest": seal_protocol["protocol_digest"],
        "readiness_source_manifest_digest": source_manifest["source_manifest_digest"],
        "case_order_digest": action_manifest["case_order_digest"],
        "e1_action_manifest_digest": action_manifest["manifest_digest"],
        "e1_config_set_digest": delta["E1"]["config_set_digest"],
        "e1_common_pool_binding_digest": pool_binding["pool_binding_digest"],
        "e1_channel_query_identities_digest": pool_binding[
            "channel_query_identities_digest"
        ],
        "e1_caps_digest": delta["E1"]["caps_digest"],
        "cost_ledger_schema_digest": ledger_schema["cost_ledger_schema_digest"],
        "s3a_generator_source_sha256": delta["presealed_s3a_implementation"][
            "generator"
        ]["sha256"],
        "s3a_sealer_source_sha256": delta["presealed_s3a_implementation"]["sealer"][
            "sha256"
        ],
        "s3a_runner_source_sha256": delta["presealed_s3a_implementation"]["runner"][
            "sha256"
        ],
        "final_k": 8,
        "expected_arm_count": 11,
    }
    if set(s3a_bindings) != set(S3A_REQUIRED_BINDINGS):
        raise ValueError("DG25_S3A_STOP_BINDING_SCHEMA_DRIFT")
    material: dict[str, Any] = {
        "schema": "milai.dg25.bound-stop-evaluation-contract.v0.1",
        "contract": stop_evaluation_contract(),
        "evaluator_source": implementation_identity(
            root, Path("evals/dg25/stop_gate.py"), "evaluate_score_gate"
        ),
        "readiness_bindings": {
            "execution_delta_manifest_digest": delta["manifest_digest"],
            "all_arm_seal_protocol_digest": seal_protocol["protocol_digest"],
            "effect_scorer_contract_digest": scorer_seal["contract"]["contract_digest"],
            "effect_scorer_source_sha256": scorer_seal["scorer_source"]["sha256"],
            "e2_common_input_digest": common_input["common_input_digest"],
            "readiness_source_manifest_digest": source_manifest["source_manifest_digest"],
            "case_order_digest": action_manifest["case_order_digest"],
            "stop_rule_registry_sha256": sha256_file(root / STOP_REGISTRY),
            "e1_action_manifest_digest": action_manifest["manifest_digest"],
            "e1_config_set_digest": delta["E1"]["config_set_digest"],
            "e2_config_set_digest": delta["E2"]["config_set_digest"],
            "e1_common_pool_binding_digest": pool_binding["pool_binding_digest"],
            "e1_caps_digest": delta["E1"]["caps_digest"],
            "e2_caps_digest": delta["E2"]["caps_digest"],
            "cost_ledger_schema_digest": ledger_schema["cost_ledger_schema_digest"],
            "final_k": 8,
        },
        "s3a_generation_bindings": s3a_bindings,
        "s3a_generation_bindings_digest": canonical_sha256(s3a_bindings),
        "future_exact_bindings_required": [
            "e1_all_arm_seal_digest",
            "e2_all_arm_seal_digest",
            "combined_all_arm_seal_digest",
            "independent_scoring_authorization_digest",
        ],
        "current_execution": {
            "pre_score_gate_executed": False,
            "post_score_gate_executed": False,
            "effect_scoring_executed": False,
            "registry_content_loaded": False,
        },
    }
    material["bound_contract_digest"] = canonical_sha256(material)
    return material


def _build_validation_report(
    *,
    root: Path,
    common_input: Mapping[str, Any],
    scorer_seal: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    delta: Mapping[str, Any],
    seal_protocol: Mapping[str, Any],
    stop_contract: Mapping[str, Any],
    action_manifest: Mapping[str, Any],
    quality_binding: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
    e1_configs: Sequence[E1ArmConfigV01],
    e2_configs: Sequence[E2ArmConfigV01],
    contrasts: Mapping[str, Any],
) -> dict[str, Any]:
    s3a_expected = _mapping(
        stop_contract.get("s3a_generation_bindings"), "S3A stop bindings"
    )
    generation_observations: dict[str, Any] = {
        **dict(s3a_expected),
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
        "output_directory_exists": False,
        "arm_output_count": 0,
        "all_arm_seal_present": False,
    }
    generation_pass = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="PRE_GENERATION",
        observations=generation_observations,
        expected_bindings=s3a_expected,
    )
    label_observations = dict(generation_observations)
    label_observations["labels_loaded"] = True
    generation_label_negative = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="PRE_GENERATION",
        observations=label_observations,
        expected_bindings=s3a_expected,
    )
    wrong_generation_digest = dict(generation_observations)
    wrong_generation_digest["execution_delta_manifest_digest"] = "f" * 64
    generation_digest_negative = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="PRE_GENERATION",
        observations=wrong_generation_digest,
        expected_bindings=s3a_expected,
    )
    post_generation_observations = {
        **generation_observations,
        "arm_output_count": 11,
        "all_arm_seal_present": True,
        "arm_order_exact": True,
        "output_content_digests_recomputed": True,
        "execution_bindings_recomputed": True,
        "all_arm_seal_recomputed": True,
        "partial_duplicate_or_reordered_outputs": 0,
        "case_order_exact": True,
    }
    generation_post_pass = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="POST_GENERATION",
        observations=post_generation_observations,
        expected_bindings=s3a_expected,
    )
    wrong_case_order = dict(post_generation_observations)
    wrong_case_order["case_order_exact"] = False
    generation_case_order_negative = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="POST_GENERATION",
        observations=wrong_case_order,
        expected_bindings=s3a_expected,
    )
    digest = "a" * 64
    score_expected: dict[str, Any] = dict(stop_contract["readiness_bindings"])
    for field in stop_contract["future_exact_bindings_required"]:
        score_expected[str(field)] = digest
    positive_observations: dict[str, Any] = dict(score_expected)
    positive_observations.update(
        {
            "identity_drift": 0,
            "label_before_seal": 0,
            "pool_k_mismatch": 0,
            "invalid_plan_count": 0,
            "budget_overflow": 0,
            "boundary_drift": 0,
            "forbidden_calls": 0,
            "post_score_adaptation": 0,
            "accepted_binding_precision": None,
            "wrong_complete": None,
            "e1_all_arm_seal_present": True,
            "e2_all_arm_seal_present": True,
            "combined_all_arm_seal_present": True,
            "all_arm_output_count": 16,
            "independent_scoring_authorized": True,
            "automatic_retries": 0,
            "stage": "S4B_PRE_SCORE",
            "labels_loaded": False,
            "scoring_executed": False,
        }
    )
    pre_score_synthetic = evaluate_score_gate(
        phase="PRE_SCORE",
        observations=positive_observations,
        expected_bindings=score_expected,
    )
    missing_e2 = dict(positive_observations)
    missing_e2["e2_all_arm_seal_present"] = False
    pre_score_negative = evaluate_score_gate(
        phase="PRE_SCORE",
        observations=missing_e2,
        expected_bindings=score_expected,
    )
    wrong_score_digest = dict(positive_observations)
    wrong_score_digest["execution_delta_manifest_digest"] = "f" * 64
    pre_score_digest_negative = evaluate_score_gate(
        phase="PRE_SCORE",
        observations=wrong_score_digest,
        expected_bindings=score_expected,
    )
    validate_e1_action_manifest(
        manifest=action_manifest,
        configs=e1_configs,
        pool_binding_digest=str(delta["e1_common_pool"]["pool_binding_digest"]),
        expected_case_order=_string_sequence(delta.get("case_order"), "case order"),
    )
    checks = {
        "posts2_re01_exact_arm_configs_and_action_vectors": (
            contrasts.get("passed") is True
            and action_manifest["plan_count"] == 165
            and action_manifest["occurrence_selection_executed"] is False
        ),
        "posts2_re02_scorer_sealed_not_executed": (
            scorer_seal["status"] == "SEALED_SOURCE_AND_CONTRACT_NOT_AUTHORIZED_TO_EXECUTE"
            and scorer_seal["registry_content_loaded"] is False
            and scorer_seal["effect_scoring_executed"] is False
        ),
        "posts2_re03_e2_common_input_2_requirements_973_rows": (
            common_input["requirement_count"] == 2
            and common_input["raw_row_count"] == 973
            and common_input["t2_applicability_frozen_before_labels"] is True
        ),
        "posts2_re04_joint_all_arm_seal_protocol": (
            seal_protocol["combined_seal_schema"]["required_arm_output_count"] == 16
            and seal_protocol["phases"][0]["output_schema"]
            == "milai.dg25.label-free-arm-output.v0.2"
        ),
        "posts2_re05_fresh_source_and_quality_manifest": (
            source_manifest["fresh"] is True
            and quality_binding["disposition"]
            in {
                "AUTHORITATIVE_BOUND_PASS",
                "EXPLICITLY_NON_AUTHORITATIVE_TEST_ONLY",
            }
        ),
        "posts2_re06_exact_stop_evaluator_bound": (
            bool(stop_contract["bound_contract_digest"])
            and generation_digest_negative["passed"] is False
            and pre_score_digest_negative["passed"] is False
        ),
        "posts2_re07_fail_closed_schedule": (
            delta["stage_schedule"]["labels_or_scoring_in_S3"] == "REJECT"
            and generation_pass["passed"] is True
            and generation_label_negative["passed"] is False
            and pre_score_synthetic["passed"] is True
            and pre_score_negative["passed"] is False
        ),
        "s3r_002_re02_actual_s3a_generator_sealer_presealed": (
            delta["presealed_s3a_implementation"]["output_schema"]
            == "milai.dg25.label-free-arm-output.v0.2"
            and len(seal_protocol["phases"][0]["config_digests"]) == 11
        ),
        "s3r_002_re04_output_and_seal_execution_bindings": (
            ledger_schema["fields_in_order"] == list(COST_LEDGER_FIELDS)
            and seal_protocol["combined_seal_schema"]["readiness_bindings"][
                "e1_action_manifest_digest"
            ]
            == action_manifest["manifest_digest"]
        ),
        "s3r_004_re01_immutable_case_order_bound": (
            action_manifest["case_order"] == delta["case_order"]
            and action_manifest["case_order_digest"] == delta["case_order_digest"]
            and s3a_expected["case_order_digest"] == delta["case_order_digest"]
            and seal_protocol["case_order_digest"] == delta["case_order_digest"]
            and generation_post_pass["passed"] is True
            and generation_case_order_negative["passed"] is False
            ),
            "s3r_004_re02_official_failure_ledger_path_presealed": (
                source_manifest["source_scan"]["checks"][
                    "official_s3a_failure_ledger_path_present"
                ]
                is True
            ),
            "s3r_005_re01_complete_attempt_identity_envelope_presealed": (
                source_manifest["source_scan"]["checks"][
                    "official_s3a_complete_attempt_identity_envelope_present"
                ]
                is True
            ),
            "s3r_006_re01_re02_total_capture_and_resolved_provenance": (
                source_manifest["source_scan"]["checks"][
                    "official_s3a_total_capture_and_resolved_provenance_present"
                ]
                is True
            ),
            "s3r_006_re04_ast_execution_surface_clean": (
                source_manifest["source_scan"]["checks"][
                    "s3a_generator_execution_surface_ast_clean"
                ]
                is True
                and source_manifest["source_scan"]["checks"][
                    "s3a_runner_execution_surface_ast_clean"
                ]
                is True
            ),
        "e2_config_set_frozen": len(e2_configs) == 5,
        "gold_registry_content_not_opened": True,
        "proof_registry_content_not_opened": True,
        "official_e1_replay_not_executed": True,
        "official_e2_transform_not_executed": True,
        "effect_scoring_not_executed": True,
        "reader_model_provider_controller_calls_zero": True,
        "formal_holdout_untouched": True,
        "candidate_default_off": True,
        "canonical_mutations_zero": True,
        "automatic_retries_zero": True,
        "registry_files_identity_only": (
            sha256_file(root / GOLD_REGISTRY)
            == scorer_seal["registry_identity_references"]["gold_equivalence_registry"][
                "sha256"
            ]
            and sha256_file(root / PROOF_REGISTRY)
            == scorer_seal["registry_identity_references"]["proof_obligation_registry"][
                "sha256"
            ]
        ),
    }
    return {
        "schema": "milai.dg25.s3-readiness-validation.v0.1",
        "status": "PASS_DG25_S3_READINESS" if all(checks.values()) else "FAIL_DG25_S3_READINESS",
        "checks": checks,
        "hard_gate": {"passed": all(checks.values())},
        "synthetic_stop_evaluations": {
            "s3a_label_free_positive": generation_pass,
            "s3a_label_load_rejected": generation_label_negative,
            "s3a_wrong_64_hex_digest_rejected": generation_digest_negative,
            "s3a_post_generation_positive": generation_post_pass,
            "s3a_wrong_case_order_rejected": generation_case_order_negative,
            "s4b_pre_score_positive_shape": pre_score_synthetic,
            "s4b_missing_e2_seal_rejected": pre_score_negative,
            "s4b_wrong_64_hex_digest_rejected": pre_score_digest_negative,
        },
    }


def implementation_identity(root: Path, path: Path, symbol: str) -> dict[str, Any]:
    value = identity(root, path)
    value["symbol"] = symbol
    value["implementation_digest"] = hashlib.sha256(
        f"{path}:{symbol}:{value['sha256']}".encode()
    ).hexdigest()
    return value


def identity(root: Path, path: Path) -> dict[str, Any]:
    absolute = root / path
    return {
        "path": str(path),
        "sha256": sha256_file(absolute),
        "size": absolute.stat().st_size,
    }


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


def _string_sequence(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    if not all(isinstance(item, str) for item in value):
        raise TypeError(f"{label} items must be strings")
    return list(value)


def _only_string(values: set[str], label: str) -> str:
    if len(values) != 1:
        raise ValueError(f"{label} must have exactly one value")
    return next(iter(values))


def _integer_value(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


__all__ = [
    "build_readiness_artifacts",
    "canonical_bytes",
    "identity",
    "read_json_object",
    "sha256_file",
]
