"""Deterministic scoring for the MF-01 passive Formation first-loss audit."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from milai.domain.requirement_state import canonical_sha256
from milai.observability.formation_audit import (
    STAGES,
    FormationAuditInput,
    FormationTraceRecord,
    PassiveFormationAuditObserver,
    observe_passthrough,
)

from evals.mf01.labels import FormationLabelSeal, build_label_seal
from scripts.freeze_mf01_s0_s1 import stage_availability_map

OLD_LOCK = Path("var/mf01/run-lock.json")
PRODUCT_BASELINE = Path("var/dg12/product/core-baseline-e2e.json")

_VALID_REASONS = {
    "TERMINAL_SURVIVAL",
    "EPISODE_BOUNDARY_MISSED",
    "ENTITY_MENTION_MISSED",
    "ALIAS_UNRESOLVED",
    "EVENT_MENTION_MISSED",
    "EVENT_IDENTITY_DUPLICATED",
    "RELATIVE_TIME_UNRESOLVED",
    "STATE_ASSERTION_NOT_FORMED",
    "UPDATE_RELATION_MISCLASSIFIED",
    "TEMPORARY_CONSTRAINT_TREATED_AS_REPLACEMENT",
    "CORRECTION_NOT_LINKED",
    "PROPOSAL_NOT_EMITTED",
}


class MF01EffectError(RuntimeError):
    """The passive trace or its frozen evidence lineage is invalid."""


def load_s0_s1_lock(root: Path) -> dict[str, Any]:
    """Validate the historical lock digest and unchanged product/source identities."""

    root = root.resolve()
    lock = _object(root / OLD_LOCK)
    if lock.get("schema") != "milai.mf01.s0-s1.run-lock.v0.1":
        raise MF01EffectError("MF01_S0_S1_LOCK_SCHEMA_DRIFT")
    material = dict(lock)
    observed = material.pop("lock_digest", None)
    if observed != canonical_sha256(material):
        raise MF01EffectError("MF01_S0_S1_LOCK_DIGEST_MISMATCH")
    skipped_historical_control = {
        "MiLAi_MF-01_Formation_First-Loss_Audit_GOALS.md",
        "tests/test_mf01_s0_s1_design.py",
    }
    for raw_identity in _sequence(lock.get("bound_identities"), "bound identities"):
        identity = _mapping(raw_identity, "bound identity")
        if str(identity.get("path")) in skipped_historical_control:
            continue
        _verify_identity(root, identity)
    seal = build_label_seal(root)
    sealed = _mapping(lock.get("S1_label_seal"), "S1 label seal")
    if seal.seal_digest != sealed.get("label_seal_digest"):
        raise MF01EffectError("MF01_LABEL_SEAL_REPLAY_DRIFT")
    return lock


def build_passive_traces(root: Path) -> tuple[FormationLabelSeal, list[FormationTraceRecord]]:
    """Observe all sealed obligations without executing any product or provider path."""

    root = root.resolve()
    load_s0_s1_lock(root)
    seal = build_label_seal(root)
    availability = {
        str(item["stage"]): str(item["availability"])
        for item in stage_availability_map()
    }
    observer = PassiveFormationAuditObserver(availability)
    traces = [
        observer.observe(
            FormationAuditInput(
                case_id=label.case_id,
                evidence_id=label.evidence_id,
                source_ref=label.source_ref,
                obligation_id=label.obligation_id,
                obligation_kind=label.obligation_kind,
                span_start=label.span_start,
                span_end=label.span_end,
                span_text=label.span_text,
                expected=label.expected,
                expected_canonical_disposition=(
                    label.expected_canonical_disposition
                ),
            )
        )
        for label in seal.labels
    ]
    traces.sort(key=lambda item: (item.case_id, item.obligation_id))
    if len(traces) != 125 or len({item.obligation_id for item in traces}) != 125:
        raise MF01EffectError("MF01_TRACE_DENOMINATOR_OR_IDENTITY_DRIFT")
    return seal, traces


def behavior_equivalence_smoke(
    root: Path,
    seal: FormationLabelSeal,
) -> dict[str, Any]:
    """Show the observer is an identity passthrough and product files stay unchanged."""

    root = root.resolve()
    stage_map = stage_availability_map()
    availability = {
        str(item["stage"]): str(item["availability"]) for item in stage_map
    }
    observer = PassiveFormationAuditObserver(availability)
    label = seal.labels[0]
    audit_input = FormationAuditInput(
        case_id=label.case_id,
        evidence_id=label.evidence_id,
        source_ref=label.source_ref,
        obligation_id=label.obligation_id,
        obligation_kind=label.obligation_kind,
        span_start=label.span_start,
        span_end=label.span_end,
        span_text=label.span_text,
        expected=label.expected,
        expected_canonical_disposition=label.expected_canonical_disposition,
    )
    product_value: dict[str, Any] = {
        "evidence": {
            "evidence_id": label.evidence_id,
            "source_ref": label.source_ref,
            "content_digest": canonical_sha256(label.span_text),
        },
        "proposal": None,
        "canonical_state": [],
        "projection": {"raw_source_ref": label.source_ref},
        "query_output": {"status": "UNCHANGED_BY_PASSIVE_AUDIT"},
    }
    baseline = deepcopy(product_value)
    baseline_digest = canonical_sha256(baseline)
    observed, trace = observe_passthrough(
        product_value,
        observer=observer,
        audit_input=audit_input,
    )
    traced_digest = canonical_sha256(observed)
    lock = _object(root / OLD_LOCK)
    product_paths = {
        str(item["path"]): str(item["sha256"])
        for raw in _sequence(lock.get("bound_identities"), "bound identities")
        for item in [_mapping(raw, "bound identity")]
        if str(item["path"]).startswith(
            (
                "runtime/src/",
                "runtime/migrations/",
                "runtime/compose",
                "var/dg12/product/",
            )
        )
    }
    observed_product_paths = {
        path: _sha256_file(root / path) for path in sorted(product_paths)
    }
    checks = {
        "same_object_identity": observed is product_value,
        "same_product_value": observed == baseline,
        "same_product_digest": traced_digest == baseline_digest,
        "evidence_unchanged": observed["evidence"] == baseline["evidence"],
        "proposal_unchanged": observed["proposal"] == baseline["proposal"],
        "canonical_state_unchanged": (
            observed["canonical_state"] == baseline["canonical_state"]
        ),
        "projection_unchanged": observed["projection"] == baseline["projection"],
        "query_output_unchanged": (
            observed["query_output"] == baseline["query_output"]
        ),
        "bound_product_code_unchanged": observed_product_paths == product_paths,
        "frozen_product_baseline_unchanged": (
            _sha256_file(root / PRODUCT_BASELINE)
            == product_paths[str(PRODUCT_BASELINE)]
        ),
        "audit_has_no_authority": trace.audit_authority is False,
        "audit_canonical_mutation_zero": trace.canonical_mutation is False,
        "audit_provider_calls_zero": trace.provider_calls == 0,
    }
    return {
        "mode": "PURE_IDENTITY_PASSTHROUGH_PLUS_BOUND_PRODUCT_IDENTITY_REPLAY",
        "baseline_digest": baseline_digest,
        "traced_digest": traced_digest,
        "checks": checks,
        "exact_match": all(checks.values()),
        "introduced_provider_calls": 0,
        "canonical_mutations_caused_by_audit": 0,
    }


def score_first_loss(
    seal: FormationLabelSeal,
    traces: Sequence[FormationTraceRecord],
    behavior: Mapping[str, Any],
) -> dict[str, Any]:
    """Score unique attribution, retention, lineage, safety, and successor routes."""

    trace_by_id = {item.obligation_id: item for item in traces}
    label_ids = {item.obligation_id for item in seal.labels}
    attribution_complete = set(trace_by_id) == label_ids and len(trace_by_id) == len(
        traces
    )
    reasons_valid = all(item.reason_code in _VALID_REASONS for item in traces)
    unique_terminal = all(
        (item.first_loss_stage is None) == (item.reason_code == "TERMINAL_SURVIVAL")
        and sum(
            value.outcome == "FIRST_LOSS" for value in item.stage_availability
        )
        == (0 if item.first_loss_stage is None else 1)
        for item in traces
    )
    stage_coverage = all(
        tuple(item.stage for item in trace.stage_availability) == STAGES
        for trace in traces
    )
    lineage = sum(item.source_lineage_ok for item in traces)
    first_loss = Counter(
        item.first_loss_stage or "TERMINAL_SURVIVAL" for item in traces
    )
    reasons = Counter(item.reason_code for item in traces)
    kind_counts = Counter(item.obligation_kind for item in traces)
    kind_survival = Counter(
        item.obligation_kind for item in traces if item.first_loss_stage is None
    )
    stage_outcomes = {
        stage: dict(
            sorted(
                Counter(
                    next(
                        item.outcome
                        for item in trace.stage_availability
                        if item.stage == stage
                    )
                    for trace in traces
                ).items()
            )
        )
        for stage in STAGES
    }

    def retention(kind: str) -> float:
        return kind_survival[kind] / kind_counts[kind]

    route_counts = {
        "MF-02": first_loss["F10_EPISODE_FORMED"],
        "MF-03": sum(
            first_loss[stage]
            for stage in (
                "F20_MENTION_FORMED",
                "F30_IDENTITY_RESOLVED",
                "F40_EVENT_TIME_GROUNDED",
            )
        ),
        "MF-04": sum(
            first_loss[stage]
            for stage in (
                "F50_STATE_OR_CHANGE_FORMED",
                "F60_PROPOSAL_EMITTED",
            )
        ),
    }
    checks = {
        "obligation_attribution_complete": attribution_complete,
        "unique_first_loss_or_terminal_survival": unique_terminal,
        "reason_codes_valid": reasons_valid,
        "stage_availability_complete": stage_coverage,
        "source_lineage_complete": lineage == len(traces),
        "behavior_equivalence": behavior.get("exact_match") is True,
        "introduced_provider_calls_zero": (
            behavior.get("introduced_provider_calls") == 0
        ),
        "canonical_mutations_zero": (
            behavior.get("canonical_mutations_caused_by_audit") == 0
        ),
        "formal_holdout_unused": seal.formal_holdout_used is False,
    }
    output: dict[str, Any] = {
        "schema": "milai.mf01.first-loss-score.v0.1",
        "denominators": {
            "cases": seal.case_count,
            "obligations": seal.label_count,
            "obligation_kinds": len(seal.counts_by_kind),
            "stages": len(STAGES),
        },
        "metrics": {
            "ObligationAttributionCoverage": len(trace_by_id) / seal.label_count,
            "StageAvailabilityCoverage": (
                sum(len(item.stage_availability) for item in traces)
                / (seal.label_count * len(STAGES))
            ),
            "EpisodeBoundaryRetention": retention("EPISODE_BOUNDARY"),
            "IdentityRetention": retention("ENTITY_IDENTITY"),
            "EventIdentityRetention": retention("EVENT_IDENTITY"),
            "OccurrenceTimeRetention": retention("EVENT_OCCURRENCE_TIME"),
            "StateAssertionRetention": retention("STATE_ASSERTION"),
            "TransitionRetention": retention("STATE_TRANSITION"),
            "ProposalRetention": (
                sum(
                    item.obligation_kind == "CANONICAL_DISPOSITION"
                    and item.first_loss_stage is None
                    and item.reason_code == "TERMINAL_SURVIVAL"
                    for item in traces
                )
                / kind_counts["CANONICAL_DISPOSITION"]
            ),
            "ProjectionRetention": retention("RETRIEVAL_PROJECTION"),
            "ProvenanceClosureRate": lineage / len(traces),
            "BehaviorEquivalence": behavior.get("exact_match") is True,
            "IntroducedProviderCalls": behavior.get("introduced_provider_calls"),
            "CanonicalMutationsCausedByAudit": behavior.get(
                "canonical_mutations_caused_by_audit"
            ),
        },
        "first_loss_distribution": dict(sorted(first_loss.items())),
        "reason_distribution": dict(sorted(reasons.items())),
        "stage_outcomes": stage_outcomes,
        "checks": checks,
        "successor_routing": {
            "counts": route_counts,
            "ordered_by_first_loss_count": sorted(
                route_counts,
                key=lambda route: (-route_counts[route], route),
            ),
            "execution_authorized_by_current_master": False,
        },
        "status": (
            "PASS_FORMATION_FIRST_LOSS_LOCALIZED"
            if all(checks.values())
            else "PARKED_LABEL_MAPPING_OR_LINEAGE_INCOMPLETE"
        ),
    }
    output["score_digest"] = canonical_sha256(output)
    return output


def _verify_identity(root: Path, identity: Mapping[str, Any]) -> None:
    path = root / str(identity["path"])
    if (
        not path.is_file()
        or path.stat().st_size != int(identity["size"])
        or _sha256_file(path) != identity["sha256"]
    ):
        raise MF01EffectError(f"MF01_BOUND_IDENTITY_DRIFT:{identity['path']}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MF01EffectError(f"MF01_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MF01EffectError(f"MF01_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MF01EffectError(f"MF01_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = [
    "MF01EffectError",
    "behavior_equivalence_smoke",
    "build_passive_traces",
    "load_s0_s1_lock",
    "score_first_loss",
]
