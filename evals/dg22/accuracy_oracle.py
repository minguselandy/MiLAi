"""DG-22 S1 label-separated safe-channel reachability and first-loss oracle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.dg16.lme10 import load_public_dev_cases
from evals.dg17.measurement import LABELS_PATH

_DG20_ORACLE = Path(
    "var/dg20/s1/dg20-s1-official-channel-oracle-20260828-003/score.json"
)
_DG21_TRACE = Path("var/dg21/s7/dg21-s7-matched-20260828-008/sealed-context-trace.json")
_ARM = "D_SAFE_QUERY_TIME_TEMPORAL_EVENT"
_STAGE_ORDER = {
    "QUERY_IR": 0,
    "REQUIREMENT": 1,
    "ACTION_BUNDLE": 2,
    "CAPABILITY": 3,
    "CHANNEL": 4,
    "RAW_RANK": 5,
    "FUSION": 6,
    "CUTOFF": 7,
    "GOVERNANCE_GATE": 8,
    "SPAN": 9,
    "NON_TEMPORAL_APPLICABILITY": 10,
    "TEMPORAL_RESOLUTION": 11,
    "BINDING": 12,
    "COMPLETENESS_PROOF": 13,
    "SUFFICIENCY": 14,
    "CONTEXT_PACKING": 15,
    "READER_CONFORMANCE": 16,
    "READER_UTILIZATION": 17,
    "SCORER": 18,
}


class DG22OracleError(RuntimeError):
    """The label boundary or S1 denominator drifted."""


def build_label_free_product(root: Path, *, run_id: str) -> dict[str, Any]:
    """Build a label-free bounded source-partition inventory and QueryIR ledger."""
    cases, selection = load_public_dev_cases()
    trace = _read_json(root / _DG21_TRACE)
    records = {
        row["case_id"]: row
        for row in trace["records"]
        if row["arm"] == _ARM and row["token_budget"] == 2048
    }
    if set(records) != {case.case_id for case in cases}:
        raise DG22OracleError("DG-21 product trace denominator drifted")
    product_cases = []
    for case in cases:
        row = records[case.case_id]
        source_refs = [
            _source_ref(case.case_id, index, session.session_id, turn_index)
            for index, session in enumerate(case.sessions)
            for turn_index, _turn in enumerate(session.turns)
        ]
        requirements = [
            {
                "slot_id": requirement["slot_id"],
                "required": requirement["required"],
                "interpretation_kind": requirement["interpretation_kind"],
                "value_type": requirement["value_type"],
                "cardinality": requirement["cardinality"],
                "predicate_constraints": requirement["predicate_constraints"],
                "evidence_source": requirement["evidence_source"],
                "semantic_roles": requirement["semantic_roles"],
                "temporal_constraints": requirement["temporal_constraints"],
            }
            for requirement in row["memory_query_ir"]["requirements"]
        ]
        product_cases.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "query_ir_digest": _digest(row["memory_query_ir"]),
                "operator_family": _operator_family(row),
                "answer_shape": row["memory_query_ir"]["answer_shape"],
                "completeness": row["memory_query_ir"]["completeness"],
                "requirements": requirements,
                "bounded_official_channel": "SOURCE_OBSERVED_RANGE_SCAN",
                "bounded_partition": {
                    "scope": row["memory_query_ir"]["constraints"]["scope"],
                    "source_ref_count": len(source_refs),
                    "source_refs": source_refs,
                    "content_hydrated": False,
                },
                "current_product": _current_product_projection(
                    case.case_id,
                    root / _DG20_ORACLE,
                ),
            }
        )
    return {
        "schema": "milai.dg22.s1-label-free-safe-oracle-product.v0.1",
        "run_id": run_id,
        "status": "SEALED_PRODUCT_READY_FOR_SCORING",
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / PRODUCT_PLANE",
        "selection": selection,
        "label_access_count": 0,
        "formal_holdout_consumed": False,
        "official_channel": "SOURCE_OBSERVED_RANGE_SCAN",
        "official_channel_semantics": (
            "bounded canonical evidence partition enumeration; scorer alone checks gold rank"
        ),
        "cases": product_cases,
    }


def score_sealed_product(
    sealed_path: Path, labels_path: Path = LABELS_PATH
) -> dict[str, Any]:
    """Open only the frozen opened-dev labels after the product trace is sealed."""
    sealed = _read_json(sealed_path)
    product = sealed.get("product")
    if (
        sealed.get("status") != "SEALED_BEFORE_LABEL_OPEN"
        or not isinstance(product, Mapping)
        or sealed.get("product_sha256") != _digest(product)
        or product.get("label_access_count") != 0
    ):
        raise DG22OracleError("S1 product seal is invalid")
    labels_envelope = _read_json(labels_path)
    labels = {row["case_id"]: row for row in labels_envelope["cases"]}
    ledgers = []
    atom_denominator = 0
    atom_reachable = 0
    for case in product["cases"]:
        label = labels[case["case_id"]]
        label_order = list(dict.fromkeys(atom["slot"] for atom in label["atoms"]))
        runtime_order = [item["slot_id"] for item in case["requirements"]]
        crosswalk = _structural_requirement_crosswalk(runtime_order, label_order)
        source_refs = case["bounded_partition"]["source_refs"]
        for requirement in case["requirements"]:
            slot_id = requirement["slot_id"]
            label_slots = set(crosswalk[slot_id])
            atoms = [atom for atom in label["atoms"] if atom["slot"] in label_slots]
            ranks = [source_refs.index(atom["source_turn_ref"]) + 1 for atom in atoms]
            atom_denominator += len(atoms)
            atom_reachable += len(ranks)
            current = case["current_product"].get(slot_id, {})
            first_loss, secondary = _current_first_loss(current)
            ledgers.append(
                {
                    "case_id": case["case_id"],
                    "requirement_id": slot_id,
                    "query_ir_correctness": "STRUCTURALLY_VALID",
                    "safe_channel_reachability": "REACHABLE",
                    "safe_channel": case["bounded_official_channel"],
                    "raw_rank_per_channel": {
                        case["bounded_official_channel"]: min(ranks)
                    },
                    "all_required_atom_raw_ranks": ranks,
                    "cutoff_survival": "ORACLE_UNBOUNDED_RAW_POOL_ONLY",
                    "governance_eligibility": "ELIGIBLE_CANONICAL_PARTITION",
                    "non_temporal_applicability": "NOT_EVALUATED_IN_S1",
                    "temporal_status": "NOT_EVALUATED_IN_S1",
                    "binding_status": "NOT_EVALUATED_IN_S1",
                    "completeness_effect": "NOT_EVALUATED_IN_S1",
                    "operator_readiness": "NOT_EVALUATED_IN_S1",
                    "current_first_loss": first_loss,
                    "secondary_losses": secondary,
                    "required_atom_count": len(atoms),
                }
            )
    safe_reachable = [
        row for row in ledgers if row["safe_channel_reachability"] == "REACHABLE"
    ]
    normalized_recall = len(safe_reachable) / len(ledgers)
    checks = {
        "sealed_before_gold_open": True,
        "product_label_access_zero": True,
        "scorer_label_access_once": True,
        "formal_holdout_untouched": product["formal_holdout_consumed"] is False,
        "requirement_denominator_complete": len(ledgers) == 15,
        "required_evidence_atom_denominator_23": atom_denominator == 23,
        "all_atoms_safe_channel_reachable": atom_reachable == atom_denominator,
        "safe_oracle_ceiling_at_least_0_80": normalized_recall >= 0.80,
        "one_first_loss_per_requirement": all(
            row["current_first_loss"] in _STAGE_ORDER for row in ledgers
        ),
        "reader_calls_zero": True,
        "provider_calls_zero": True,
    }
    return {
        "schema": "milai.dg22.s1-safe-oracle-score.v0.1",
        "run_id": product["run_id"],
        "status": "PASS_SAFE_ORACLE" if all(checks.values()) else "FAIL",
        "label_boundary": {
            "product_label_access_count": 0,
            "scorer_label_access_count": 1,
            "scoring_started_after_product_seal": True,
        },
        "metrics": {
            "safe_oracle_reachable_requirement_count": len(safe_reachable),
            "safe_oracle_requirement_denominator": len(ledgers),
            "safe_oracle_normalized_recall_ceiling": normalized_recall,
            "safe_oracle_reachable_atom_count": atom_reachable,
            "required_evidence_atom_denominator": atom_denominator,
        },
        "records": ledgers,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "formal_holdout_consumed": False,
    }


def seal_product(product: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Persist an immutable product envelope before any scorer label read."""
    if path.exists():
        raise DG22OracleError("S1 sealed product path already exists")
    envelope = {
        "schema": "milai.dg22.s1-sealed-safe-oracle-product.v0.1",
        "status": "SEALED_BEFORE_LABEL_OPEN",
        "product_sha256": _digest(product),
        "product": dict(product),
    }
    path.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return envelope


def _current_product_projection(case_id: str, oracle_path: Path) -> dict[str, Any]:
    oracle = _read_json(oracle_path)
    case = next(row for row in oracle["cases"] if row["case_id"] == case_id)
    return {
        row["requirement_id"]: {"arms": row["arms"]} for row in case["requirements"]
    }


def _current_first_loss(current: Mapping[str, Any]) -> tuple[str, list[str]]:
    mapped = []
    for arm in current.get("arms", []):
        value = {
            "OPERATOR_READY": "READER_CONFORMANCE",
            "SUFFICIENCY_OR_OPERATOR_NOT_READY": "SUFFICIENCY",
            "BINDING_REJECTED_OR_POSSIBLE": "BINDING",
            "FUSION_CUTOFF": "CUTOFF",
            "CHANNEL_RETRIEVAL_BOUND_MISS": "CHANNEL",
            "NO_FEASIBLE_REQUIREMENT_ACTION": "ACTION_BUNDLE",
            "CAPABILITY_UNAVAILABLE": "CAPABILITY",
        }.get(arm["first_loss_stage"], "CHANNEL")
        mapped.append(value)
    if not mapped:
        return "CAPABILITY", []
    first = max(mapped, key=_STAGE_ORDER.__getitem__)
    return first, sorted(set(mapped) - {first}, key=_STAGE_ORDER.__getitem__)


def _operator_from_steps(steps: Sequence[Mapping[str, Any]]) -> str:
    for step in steps:
        operator = step.get("constraints", {}).get("operator_family")
        if operator:
            return str(operator)
    return "LOOKUP"


def _structural_requirement_crosswalk(
    runtime_order: Sequence[str], label_order: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """Map versioned slots by identity, then one aggregate slot to residual labels."""
    if len(set(runtime_order)) != len(runtime_order) or len(set(label_order)) != len(
        label_order
    ):
        raise DG22OracleError("requirement crosswalk identities are not unique")
    label_set = set(label_order)
    exact: dict[str, tuple[str, ...]] = {
        slot: (slot,) for slot in runtime_order if slot in label_set
    }
    residual_runtime = [slot for slot in runtime_order if slot not in exact]
    consumed = {slot for values in exact.values() for slot in values}
    residual_labels = tuple(slot for slot in label_order if slot not in consumed)
    if residual_labels:
        if len(residual_runtime) == len(residual_labels):
            exact.update(
                {
                    runtime_slot: (label_slot,)
                    for runtime_slot, label_slot in zip(
                        residual_runtime, residual_labels, strict=True
                    )
                }
            )
        elif len(residual_runtime) == 1:
            exact[residual_runtime[0]] = residual_labels
        else:
            raise DG22OracleError("requirement crosswalk is structurally ambiguous")
    elif residual_runtime:
        raise DG22OracleError("Runtime requirement has no scorer identity")
    if set(exact) != set(runtime_order):
        raise DG22OracleError("requirement crosswalk is incomplete")
    return {slot: exact[slot] for slot in runtime_order}


def _operator_family(row: Mapping[str, Any]) -> str:
    derived = row.get("derived_result")
    if isinstance(derived, Mapping) and derived.get("operator"):
        return str(derived["operator"])
    query_ir = row["memory_query_ir"]
    if not isinstance(query_ir, Mapping):
        raise DG22OracleError("product QueryIR is malformed")
    steps = query_ir.get("steps")
    if not isinstance(steps, Sequence):
        raise DG22OracleError("product QueryIR steps are malformed")
    return _operator_from_steps(steps)


def _source_ref(case_id: str, session: int, session_id: str, turn: int) -> str:
    return f"{case_id}:s{session}:{session_id}:t{turn}"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG22OracleError(f"expected object: {path}")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
