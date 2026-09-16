"""Lean MF-04 effect over the sealed direct state/change obligations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from milai.application.state_change_formation import build_state_change_sidecar
from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateChangeSidecarV01,
    FormationStateTransitionV01,
)
from milai.domain.requirement_state import canonical_sha256

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases
from evals.mf01.labels import (
    SUPPLEMENT,
    FormationLabelSeal,
    FormationObligationLabel,
    build_label_seal,
)

_KINDS = {"STATE_ASSERTION", "STATE_TRANSITION"}


class MF04EffectError(RuntimeError):
    """The sealed source set or state/change score drifted."""


def execute_mf04_effect(root: Path) -> dict[str, Any]:
    """Form source-grounded sidecars without model or Canonical calls."""

    root = root.resolve()
    seal = build_label_seal(root)
    sources = load_state_change_sources(root, seal)
    sidecar = build_state_change_sidecar(sources)
    score = score_state_change_sidecar(seal, sidecar)
    checks = {
        "state_assertion_recall_one": score["STATE_ASSERTION"]["recall"] == 1.0,
        "state_assertion_precision_one": score["STATE_ASSERTION"]["precision"] == 1.0,
        "state_transition_recall_one": score["STATE_TRANSITION"]["recall"] == 1.0,
        "state_transition_precision_one": score["STATE_TRANSITION"]["precision"] == 1.0,
        "temporary_interval_closed": any(
            item.relation == "TEMPORARILY_CONSTRAINS"
            and item.valid_time is not None
            and item.valid_time.end is not None
            and item.valid_time.end.date().isoformat() == "2026-09-05"
            for item in sidecar.transitions
        ),
        "canonical_mutation_zero": sidecar.canonical_mutation is False,
    }
    passed = all(checks.values())
    output: dict[str, Any] = {
        "schema": "milai.mf04.state-change-effect.v0.1",
        "status": "PASS_MF04_STATE_CHANGE_FORMATION" if passed else "NEEDS_REPAIR",
        "execution_authority": "USER_20260830_REPAIR_THEN_CONTINUE",
        "source_scope": {
            "sealed_obligation_kinds": sorted(_KINDS),
            "source_record_count": len(sources),
            "direct_obligation_count": sum(
                1 for item in seal.labels if item.obligation_kind in _KINDS
            ),
            "formal_holdout_used": False,
        },
        "sidecar": sidecar.model_dump(mode="json"),
        "metrics": score,
        "checks": checks,
        "cost": {
            "model_calls": 0,
            "reader_calls": 0,
            "database_writes": 0,
            "canonical_mutations": 0,
            "automatic_retries": 0,
        },
        "next_route": "EV01_GOVERNED_PROMOTION_BRIDGE" if passed else "MF04_REPAIR",
        "experimental_feature_flags": "OFF",
        "formal_holdout_used": False,
    }
    output["result_digest"] = canonical_sha256(output)
    return output


def load_state_change_sources(
    root: Path,
    seal: FormationLabelSeal,
) -> list[dict[str, Any]]:
    """Hydrate each exact source once without exposing labels to Formation."""

    opened = {case.case_id: case for case in load_public_dev_cases()[0]}
    supplement = _object(root / SUPPLEMENT)
    synthetic = {
        str(item["case_id"]): item
        for item in _sequence(supplement.get("synthetic_cases"), "synthetic cases")
        if isinstance(item, Mapping)
    }
    source_keys = sorted(
        {
            (item.case_id, item.evidence_id, item.source_ref)
            for item in seal.labels
            if item.obligation_kind in _KINDS
        }
    )
    output: list[dict[str, Any]] = []
    for case_id, evidence_id, source_ref in source_keys:
        if case_id in opened:
            session_ordinal, turn_ordinal = _compact_ordinals(source_ref)
            session = opened[case_id].sessions[session_ordinal]
            turn = session.turns[turn_ordinal]
            content = str(turn.content)
            observed_at = normalize_lme_timestamp(str(session.observed_at))
        else:
            source = synthetic.get(case_id)
            if not isinstance(source, Mapping):
                raise MF04EffectError(f"MF04_SYNTHETIC_SOURCE_MISSING:{case_id}")
            content = str(source["content"])
            observed_at = str(source["observed_at"])
        output.append(
            {
                "case_id": case_id,
                "evidence_id": evidence_id,
                "source_ref": source_ref,
                "speaker": "user",
                "observed_at": observed_at,
                "content": content,
                "content_hash": canonical_sha256(content),
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "access_decision": "ALLOWED",
            }
        )
    if len(output) != 6:
        raise MF04EffectError("MF04_SOURCE_RECORD_DENOMINATOR_DRIFT")
    return output


def score_state_change_sidecar(
    seal: FormationLabelSeal,
    sidecar: FormationStateChangeSidecarV01,
) -> dict[str, Any]:
    """Score exact grounded spans plus the typed state/change meaning."""

    labels_by_kind = {
        kind: [item for item in seal.labels if item.obligation_kind == kind]
        for kind in _KINDS
    }
    assertion_matches = {
        item.artifact_digest
        for item in sidecar.assertions
        if any(_assertion_matches(label, item) for label in labels_by_kind["STATE_ASSERTION"])
    }
    transition_matches = {
        item.artifact_digest
        for item in sidecar.transitions
        if any(_transition_matches(label, item) for label in labels_by_kind["STATE_TRANSITION"])
    }
    assertion_covered = sum(
        any(_assertion_matches(label, item) for item in sidecar.assertions)
        for label in labels_by_kind["STATE_ASSERTION"]
    )
    transition_covered = sum(
        any(_transition_matches(label, item) for item in sidecar.transitions)
        for label in labels_by_kind["STATE_TRANSITION"]
    )
    return {
        "STATE_ASSERTION": _metric(
            assertion_covered,
            len(labels_by_kind["STATE_ASSERTION"]),
            len(assertion_matches),
            len(sidecar.assertions),
        ),
        "STATE_TRANSITION": _metric(
            transition_covered,
            len(labels_by_kind["STATE_TRANSITION"]),
            len(transition_matches),
            len(sidecar.transitions),
        ),
    }


def _assertion_matches(
    label: FormationObligationLabel,
    item: FormationStateAssertionV01,
) -> bool:
    if not _span_matches(label, item.span.evidence_id, item.span.start, item.span.end):
        return False
    value = item.value if isinstance(item.value, Mapping) else {}
    expected = label.expected
    if expected == label.span_text:
        expected_predicate = (
            "current_intent" if "thinking of" in expected.casefold() else "music_interest"
        )
        return (
            item.predicate == expected_predicate
            and item.promotion_disposition == "QUERY_LOCAL_ONLY"
        )
    if expected == "residence=Shanghai":
        return item.predicate == "residence" and value.get("location") == "Shanghai"
    if expected == "residence=Hangzhou":
        return item.predicate == "residence" and value.get("location") == "Hangzhou"
    if expected == "seat_preference=aisle_over_window":
        return (
            item.predicate == "seat_preference"
            and value.get("preferred") == "aisle seats"
            and value.get("over") == "window seats"
        )
    if expected == "temporary_location=Suzhou":
        return (
            item.predicate == "temporary_location"
            and value.get("location") == "Suzhou"
            and item.valid_time is not None
        )
    return False


def _transition_matches(
    label: FormationObligationLabel,
    item: FormationStateTransitionV01,
) -> bool:
    if not _span_matches(label, item.span.evidence_id, item.span.start, item.span.end):
        return False
    if label.expected == "residence:Shanghai->Hangzhou":
        return (
            item.relation == "UPDATES"
            and item.previous_value == {"location": "Shanghai"}
            and item.new_value == {"location": "Hangzhou"}
        )
    if label.expected == "RETRACT_HANGZHOU_AND_RESTORE_SHANGHAI":
        return (
            item.relation == "CORRECTS"
            and item.previous_value == {"location": "Hangzhou"}
            and item.new_value == {"location": "Shanghai"}
        )
    if label.expected == "temporary_location:unset->Suzhou->expires":
        return (
            item.relation == "TEMPORARILY_CONSTRAINS"
            and item.previous_value is None
            and item.new_value == {"location": "Suzhou"}
            and item.valid_time is not None
        )
    return False


def _span_matches(
    label: FormationObligationLabel,
    evidence_id: str,
    start: int,
    end: int,
) -> bool:
    return (
        evidence_id == label.evidence_id
        and start == label.span_start
        and end == label.span_end
    )


def _metric(
    covered: int,
    denominator: int,
    accepted: int,
    produced: int,
) -> dict[str, Any]:
    return {
        "covered": covered,
        "denominator": denominator,
        "recall": covered / denominator if denominator else 1.0,
        "accepted": accepted,
        "produced": produced,
        "precision": accepted / produced if produced else 1.0,
    }


def _compact_ordinals(source_ref: str) -> tuple[int, int]:
    parts = source_ref.split(":")
    try:
        return int(parts[1].removeprefix("s")), int(parts[-1].removeprefix("t"))
    except (IndexError, ValueError) as error:
        raise MF04EffectError("MF04_COMPACT_SOURCE_REF_INVALID") from error


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MF04EffectError(f"MF04_JSON_OBJECT_REQUIRED:{path}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MF04EffectError(f"MF04_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = [
    "MF04EffectError",
    "execute_mf04_effect",
    "load_state_change_sources",
    "score_state_change_sidecar",
]
