"""Sealing and safety scoring for DG-20 S4 product-faithful integration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.dg14.benchmark import _atomic_json

PRODUCT_SCHEMA = "milai.dg20.s4-product-faithful-product.v0.1"
SEALED_SCHEMA = "milai.dg20.s4-product-faithful-sealed.v0.1"


class DG20S4EvaluationError(RuntimeError):
    """The S4 product artifact violates its fixed evaluation contract."""


def seal_s4_product(product: Mapping[str, Any], output_path: Path) -> dict[str, Any]:
    if product.get("schema") != PRODUCT_SCHEMA:
        raise DG20S4EvaluationError("unexpected S4 product schema")
    if product.get("labels_loaded") is not False:
        raise DG20S4EvaluationError("S4 product must remain label-free")
    payload = dict(product)
    payload["schema"] = SEALED_SCHEMA
    payload["status"] = "SEALED_PRODUCT_FAITHFUL_COMPLETE"
    _atomic_json(output_path, payload)
    return payload


def score_s4_product(sealed_path: Path) -> dict[str, Any]:
    sealed = _load_object(sealed_path)
    if sealed.get("schema") != SEALED_SCHEMA:
        raise DG20S4EvaluationError("unexpected sealed S4 schema")
    cases = _object_list(sealed.get("cases"), "cases")
    if int(sealed.get("case_count", -1)) != len(cases) or not cases:
        raise DG20S4EvaluationError("S4 case cardinality mismatch")

    complete_cases = 0
    complete_auxiliary_calls = 0
    ineligible_cases = 0
    ineligible_output_changes = 0
    executor_identity_matches = 0
    execution_mode_equivalence = 0
    runtime_decision_identity_matches = 0
    runtime_candidate_identity_matches = 0
    full_recompute_expected = 0
    full_recompute_passed = 0
    wrong_complete = 0
    wrong_scope = 0
    canonical_mutation = 0
    automatic_retries = 0
    provider_calls = 0
    extra_pass_violations = 0

    for raw in cases:
        case = _object(raw, "case")
        case_id = str(case.get("case_id"))
        baseline = _object(case.get("baseline"), "baseline")
        shadow = _object(case.get("shadow"), "shadow")
        product = _object(case.get("product"), "product")
        runtime = _object(case.get("runtime_candidate"), "runtime_candidate")
        shadow_final = _object(shadow.get("final"), "shadow.final")
        product_final = _object(product.get("final"), "product.final")
        shadow_decision = _object(shadow.get("decision"), "shadow.decision")
        product_decision = _object(product.get("decision"), "product.decision")
        runtime_recovery = _object(runtime.get("recovery"), "runtime.recovery")
        runtime_decision = _object(runtime_recovery.get("decision"), "runtime.decision")

        initial = _object(shadow.get("initial_requirement_state"), "initial state")
        initial_requirements = _object_list(initial.get("requirements"), "initial requirements")
        if all(
            _object(item, "initial requirement").get("status") == "SATISFIED"
            for item in initial_requirements
        ):
            complete_cases += 1
            complete_auxiliary_calls += int(shadow.get("extra_pass_count", -1))
            complete_auxiliary_calls += int(runtime_recovery.get("extra_pass_count", -1))
        if shadow_decision.get("selected_action") is None:
            ineligible_cases += 1
            ineligible_output_changes += int(
                case.get("ineligible_product_output_changed") is not False
            )

        identities = {
            str(sealed.get("executor_identity")),
            str(baseline.get("executor_identity")),
            str(shadow_final.get("executor_identity")),
            str(product_final.get("executor_identity")),
        }
        executor_identity_matches += int(len(identities) == 1)
        execution_mode_equivalence += int(
            shadow_final.get("candidate_refs") == product_final.get("candidate_refs")
            and shadow_final.get("binding_trace") == product_final.get("binding_trace")
            and shadow_final.get("requirement_state") == product_final.get("requirement_state")
            and shadow_final.get("sufficiency_decision")
            == product_final.get("sufficiency_decision")
            and shadow_decision.get("decision_digest") == product_decision.get("decision_digest")
        )
        runtime_decision_identity_matches += int(
            runtime_decision.get("decision_digest") == product_decision.get("decision_digest")
        )
        runtime_candidate_identity_matches += int(
            _is_ordered_subsequence(
                _string_list(runtime.get("evidence_source_refs")),
                _string_list(product_final.get("candidate_refs")),
            )
        )

        selected = product_decision.get("selected_action")
        if selected is not None:
            full_recompute_expected += 1
            final_state = _object(product_final.get("requirement_state"), "product final state")
            full_recompute_passed += int(
                int(final_state.get("state_epoch", -1)) == int(initial.get("state_epoch", -1)) + 1
                and product_final.get("action_digest")
                == _object(selected, "selected action").get("action_digest")
                and product_final.get("sufficiency_decision") is not None
            )

        final_state = _object(product_final.get("requirement_state"), "product final state")
        requirements = _object_list(final_state.get("requirements"), "requirements")
        complete = (
            _object(product_final.get("sufficiency_decision"), "sufficiency").get("status")
            == "COMPLETE"
        )
        wrong_complete += int(
            complete
            and any(
                _object(item, "requirement").get("status") != "SATISFIED" for item in requirements
            )
        )
        wrong_scope += sum(
            not str(value).startswith(f"{case_id}:s")
            for value in _string_list(product_final.get("candidate_refs"))
        )
        canonical_mutation += int(bool(product.get("canonical_mutation")))
        canonical_mutation += int(bool(runtime_recovery.get("canonical_mutation")))
        automatic_retries += int(product.get("automatic_retries", -1))
        automatic_retries += int(runtime_recovery.get("automatic_retries", -1))
        provider_calls += int(product.get("provider_calls", -1))
        provider_calls += int(runtime_recovery.get("provider_calls", -1))
        extra_pass_violations += int(int(product.get("extra_pass_count", 2)) > 1)
        extra_pass_violations += int(int(runtime_recovery.get("extra_pass_count", 2)) > 1)

    count = len(cases)
    hard_gate = {
        "deterministic_complete_auxiliary_calls": {
            "observed": complete_auxiliary_calls,
            "denominator": complete_cases * 2,
            "required": 0,
            "passed": complete_auxiliary_calls == 0,
        },
        "ineligible_path_product_output_change": {
            "observed": ineligible_output_changes,
            "denominator": ineligible_cases,
            "required": 0,
            "passed": ineligible_output_changes == 0,
        },
        "provider_unavailable_or_invalid_behavior": {
            "observed": sealed.get("residual_assist"),
            "required": "DETERMINISTIC_ONLY",
            "passed": sealed.get("residual_assist") == "DETERMINISTIC_ONLY",
        },
        "official_executor_identity": {
            "observed": executor_identity_matches,
            "denominator": count,
            "required": count,
            "passed": executor_identity_matches == count,
        },
        "product_shadow_execution_equivalence": {
            "observed": execution_mode_equivalence,
            "denominator": count,
            "required": count,
            "passed": execution_mode_equivalence == count,
        },
        "runtime_decision_identity": {
            "observed": runtime_decision_identity_matches,
            "denominator": count,
            "required": count,
            "passed": runtime_decision_identity_matches == count,
        },
        "runtime_context_candidate_provenance": {
            "observed": runtime_candidate_identity_matches,
            "denominator": count,
            "required": count,
            "passed": runtime_candidate_identity_matches == count,
        },
        "full_sufficiency_recompute": {
            "observed": full_recompute_passed,
            "denominator": full_recompute_expected,
            "required": full_recompute_expected,
            "passed": full_recompute_passed == full_recompute_expected,
        },
        "wrong_complete": {
            "observed": wrong_complete,
            "required": 0,
            "passed": wrong_complete == 0,
        },
        "wrong_scope_authority_revoke": {
            "observed": wrong_scope,
            "required": 0,
            "passed": wrong_scope == 0,
        },
        "canonical_mutation": {
            "observed": canonical_mutation,
            "required": 0,
            "passed": canonical_mutation == 0,
        },
        "automatic_retries": {
            "observed": automatic_retries,
            "required": 0,
            "passed": automatic_retries == 0,
        },
        "provider_calls": {
            "observed": provider_calls,
            "required": 0,
            "passed": provider_calls == 0,
        },
        "extra_acquisition_pass_violations": {
            "observed": extra_pass_violations,
            "required": 0,
            "passed": extra_pass_violations == 0,
        },
        "formal_holdout_consumed": {
            "observed": bool(sealed.get("formal_holdout_consumed")),
            "required": False,
            "passed": sealed.get("formal_holdout_consumed") is False,
        },
    }
    passed = all(bool(_object(item, "gate").get("passed")) for item in hard_gate.values())
    return {
        "schema": "milai.dg20.s4-product-faithful-score.v0.1",
        "run_id": sealed.get("run_id"),
        "disposition": (
            "PASS_S4_ONE_PASS_PRODUCT_FAITHFUL_INTEGRATION"
            if passed
            else "FAILED_PRODUCT_PATH_FIDELITY"
        ),
        "enter_s5": passed,
        "formal_holdout_consumed": False,
        "hard_gate": hard_gate,
        "metrics": {
            "case_count": count,
            "complete_case_count": complete_cases,
            "ineligible_case_count": ineligible_cases,
            "selected_action_case_count": full_recompute_expected,
        },
    }


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _object(value, str(path))


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG20S4EvaluationError(f"{field} must be an object")
    return value


def _object_list(value: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DG20S4EvaluationError(f"{field} must be an object list")
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DG20S4EvaluationError("expected string list")
    return value


def _is_ordered_subsequence(values: list[str], source: list[str]) -> bool:
    position = 0
    for value in values:
        try:
            position = source.index(value, position) + 1
        except ValueError:
            return False
    return True
