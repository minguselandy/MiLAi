"""Lean MF-03 Formation sidecar effect over the sealed development obligations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from milai.adapters.formation_extraction_v01 import (
    FormationExtractionExecutionV01,
    LoopbackFormationExtractionAdapterV01,
)
from milai.application.formation_extraction import build_formation_sidecar
from milai.domain.formation_artifact import (
    FormationArtifactSidecarV01,
    FormationEventCandidateV01,
)
from milai.domain.requirement_state import canonical_sha256

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases
from evals.mf01.labels import SUPPLEMENT, FormationLabelSeal, build_label_seal

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
_MF03_KINDS = {
    "ENTITY_MENTION",
    "ENTITY_IDENTITY",
    "EVENT_MENTION",
    "EVENT_IDENTITY",
    "EVENT_OCCURRENCE_TIME",
}
_NEGATED_OR_DURATIVE_EVENT = re.compile(
    r"\b(?:did\s+not|didn't)\s+(?:move|stay|live|work|travel|visit|attend|buy|"
    r"start|stop|cancel)|\b(?:staying|living)\b",
    re.IGNORECASE,
)
_CROSS_TEMPORAL = re.compile(
    r"\b(?P<count>a|an|few|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>days?|weeks?|months?)\s+(?P<relation>after|before)\s+"
    r"(?P<anchor>[^.!?]+)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    {"a", "an", "and", "after", "before", "few", "my", "of", "the", "weeks"}
)


class MF03EffectError(RuntimeError):
    """The sealed source set, model batch, or Formation score drifted."""


@dataclass(frozen=True, slots=True)
class ResidualBatch:
    case_id: str
    target_evidence_id: str
    source_records: tuple[dict[str, Any], ...]
    reason: str


def execute_mf03_effect(
    root: Path,
    *,
    adapter: LoopbackFormationExtractionAdapterV01,
) -> dict[str, Any]:
    """Run deterministic Formation, then only the diagnosed model residuals."""

    root = root.resolve()
    seal = build_label_seal(root)
    source_records = load_formation_sources(root, seal)
    deterministic = build_formation_sidecar(source_records)
    batches = derive_residual_batches(source_records, deterministic)
    if len(batches) != 2 or {item.reason for item in batches} != {
        "NO_DETERMINISTIC_EVENT",
        "CROSS_EVIDENCE_TIME_UNRESOLVED",
    }:
        raise MF03EffectError("MF03_RESIDUAL_BATCH_DENOMINATOR_DRIFT")

    def extract(batch: ResidualBatch) -> tuple[ResidualBatch, FormationExtractionExecutionV01]:
        return (
            batch,
            adapter.extract(
                sources=batch.source_records,
                target_evidence_ids=[batch.target_evidence_id],
            ),
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        executions = list(executor.map(extract, batches))
    proposals = [
        proposal
        for _batch, execution in executions
        for proposal in execution.proposals
    ]
    treatment = build_formation_sidecar(
        source_records,
        model_event_proposals=proposals,
        model_identity=f"{MODEL_ID}:mf03-v01",
        model_calls=len(executions),
    )
    usage: list[dict[str, Any]] = [
        {
            "case_id": batch.case_id,
            "target_evidence_id": batch.target_evidence_id,
            "reason": batch.reason,
            "context_evidence_ids": [
                str(item["evidence_id"]) for item in batch.source_records
            ],
            "response_id": execution.response_id,
            "proposal_count": len(execution.proposals),
            "proposals": [
                proposal.model_dump(mode="json") for proposal in execution.proposals
            ],
            "prompt_tokens": execution.prompt_tokens,
            "completion_tokens": execution.completion_tokens,
            "latency_ms": round(execution.latency_ms, 3),
            "automatic_retries": execution.automatic_retries,
        }
        for batch, execution in executions
    ]
    output: dict[str, Any] = {
        "schema": "milai.mf03.formation-effect-unscored.v0.1",
        "source_scope": {
            "sealed_obligation_kinds": sorted(_MF03_KINDS),
            "source_record_count": len(source_records),
            "model_visible_labels": False,
            "model_visible_expected_values": False,
            "formal_holdout_used": False,
        },
        "deterministic_sidecar": deterministic.model_dump(mode="json"),
        "treatment_sidecar": treatment.model_dump(mode="json"),
        "residual_batches": [
            {
                "case_id": item.case_id,
                "target_evidence_id": item.target_evidence_id,
                "source_evidence_ids": [
                    str(value["evidence_id"]) for value in item.source_records
                ],
                "reason": item.reason,
            }
            for item in batches
        ],
        "model_usage": usage,
        "cost": {
            "model_calls": len(executions),
            "automatic_retries": sum(int(item["automatic_retries"]) for item in usage),
            "prompt_tokens": sum(int(item["prompt_tokens"]) for item in usage),
            "completion_tokens": sum(int(item["completion_tokens"]) for item in usage),
            "aggregate_latency_ms": round(
                sum(float(item["latency_ms"]) for item in usage), 3
            ),
            "reader_calls": 0,
            "canonical_mutations": 0,
            "database_writes": 0,
        },
        "candidate_feature_flag": "OFF",
        "formal_holdout_used": False,
    }
    output["unscored_digest"] = canonical_sha256(output)
    return output


def derive_residual_batches(
    source_records: Sequence[Mapping[str, Any]],
    deterministic: FormationArtifactSidecarV01,
) -> list[ResidualBatch]:
    """Select model work by missing formation capability, never case identity."""

    sources = {str(item["evidence_id"]): item for item in source_records}
    events_by_source: dict[str, list[FormationEventCandidateV01]] = {}
    for event in deterministic.event_candidates:
        events_by_source.setdefault(event.span.evidence_id, []).append(event)
    by_case: dict[str, list[Mapping[str, Any]]] = {}
    for source in source_records:
        by_case.setdefault(str(source["case_id"]), []).append(source)

    batches: list[ResidualBatch] = []
    for evidence_id, source in sorted(sources.items()):
        content = str(source["content"])
        events = events_by_source.get(evidence_id, [])
        if not events and _NEGATED_OR_DURATIVE_EVENT.search(content) is not None:
            batches.append(
                ResidualBatch(
                    case_id=str(source["case_id"]),
                    target_evidence_id=evidence_id,
                    source_records=(dict(source),),
                    reason="NO_DETERMINISTIC_EVENT",
                )
            )
            continue
        cross = _CROSS_TEMPORAL.search(content)
        if cross is None or not events or any(item.occurrence_time for item in events):
            continue
        anchors = _anchor_sources(
            cross.group("anchor"),
            source,
            by_case[str(source["case_id"])],
        )
        if not anchors:
            continue
        batches.append(
            ResidualBatch(
                case_id=str(source["case_id"]),
                target_evidence_id=evidence_id,
                source_records=(dict(source), *[dict(item) for item in anchors]),
                reason="CROSS_EVIDENCE_TIME_UNRESOLVED",
            )
        )
    return sorted(
        batches,
        key=lambda item: (item.case_id, item.target_evidence_id),
    )


def load_formation_sources(
    root: Path,
    seal: FormationLabelSeal,
) -> list[dict[str, Any]]:
    """Hydrate the pre-registered source identities without exposing labels to models."""

    opened = {case.case_id: case for case in load_public_dev_cases()[0]}
    supplement = _object(root / SUPPLEMENT)
    synthetic = {
        str(item["case_id"]): item
        for item in _sequence(supplement.get("synthetic_cases"), "synthetic cases")
    }
    needed = {
        (item.case_id, item.evidence_id, item.source_ref)
        for item in seal.labels
        if item.obligation_kind in _MF03_KINDS
    }
    output: list[dict[str, Any]] = []
    for case_id, evidence_id, source_ref in sorted(needed):
        if case_id in opened:
            case = opened[case_id]
            session_ordinal, turn_ordinal = _compact_ordinals(source_ref)
            session = case.sessions[session_ordinal]
            turn = session.turns[turn_ordinal]
            observed_at = normalize_lme_timestamp(str(session.observed_at))
            content = str(turn.content)
        else:
            synthetic_case = synthetic.get(case_id)
            if not isinstance(synthetic_case, Mapping):
                raise MF03EffectError("MF03_SYNTHETIC_SOURCE_MISSING")
            observed_at = str(synthetic_case["observed_at"])
            content = str(synthetic_case["content"])
        output.append(
            {
                "case_id": case_id,
                "evidence_id": evidence_id,
                "source_ref": source_ref,
                "session_id": case_id,
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "observed_at": observed_at,
                "content": content,
                "content_hash": canonical_sha256(content),
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "access_decision": "ALLOWED",
            }
        )
    if len(output) != 24:
        raise MF03EffectError("MF03_SOURCE_RECORD_DENOMINATOR_DRIFT")
    return output


def score_mf03_effect(
    root: Path,
    unscored: Mapping[str, Any],
) -> dict[str, Any]:
    """Score direct Formation obligations after the sidecars are sealed."""

    seal = build_label_seal(root.resolve())
    deterministic = FormationArtifactSidecarV01.model_validate(
        unscored["deterministic_sidecar"]
    )
    treatment = FormationArtifactSidecarV01.model_validate(
        unscored["treatment_sidecar"]
    )
    baseline = _score_sidecar(seal, deterministic)
    result = _score_sidecar(seal, treatment)
    checks = {
        "entity_mention_recall_one": result["ENTITY_MENTION"]["recall"] == 1.0,
        "entity_identity_recall_one": result["ENTITY_IDENTITY"]["recall"] == 1.0,
        "event_mention_recall_one": result["EVENT_MENTION"]["recall"] == 1.0,
        "event_identity_recall_one": result["EVENT_IDENTITY"]["recall"] == 1.0,
        "event_time_accuracy_one": result["EVENT_OCCURRENCE_TIME"]["recall"] == 1.0,
        "identity_collision_zero": result["EVENT_IDENTITY"]["identity_collisions"] == 0,
        "model_output_rejection_zero": not treatment.rejected_model_outputs,
        "canonical_mutation_zero": treatment.canonical_mutation is False,
        "automatic_retry_zero": unscored["cost"]["automatic_retries"] == 0,
    }
    passed = all(checks.values())
    output: dict[str, Any] = {
        "schema": "milai.mf03.formation-effect-score.v0.1",
        "unscored_digest": unscored["unscored_digest"],
        "baseline": baseline,
        "treatment": result,
        "delta": {
            kind: result[kind]["covered"] - baseline[kind]["covered"]
            for kind in sorted(_MF03_KINDS)
        },
        "checks": checks,
        "status": "PASS_MF03_FORMATION_IDENTITY_TIME" if passed else "NEEDS_REPAIR",
        "next_route": "DG28_CHARLOTTE_FORMATION_CONSUMPTION_REPLAY",
    }
    output["score_digest"] = canonical_sha256(output)
    return output


def _score_sidecar(
    seal: FormationLabelSeal,
    sidecar: FormationArtifactSidecarV01,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    event_assignment: dict[str, str] = {}
    for kind in sorted(_MF03_KINDS):
        labels = [item for item in seal.labels if item.obligation_kind == kind]
        covered = 0
        for label in labels:
            if kind.startswith("ENTITY"):
                entity_candidates = [
                    item
                    for item in sidecar.entity_candidates
                    if item.span.evidence_id == label.evidence_id
                    and _span_matches(item.span.start, item.span.end, label.span_start, label.span_end)
                ]
                matched = bool(entity_candidates)
                if kind == "ENTITY_IDENTITY":
                    matched = any(
                        item.identity_key
                        in {label.expected, *label.acceptable_alternatives}
                        for item in entity_candidates
                    )
            else:
                event_candidates = [
                    item
                    for item in sidecar.event_candidates
                    if item.span.evidence_id == label.evidence_id
                    and _span_matches(item.span.start, item.span.end, label.span_start, label.span_end)
                ]
                if kind == "EVENT_MENTION":
                    matched = bool(event_candidates)
                elif kind == "EVENT_IDENTITY":
                    event_candidates = _identity_candidates(
                        label.obligation_id, event_candidates
                    )
                    matched = bool(event_candidates)
                    if matched:
                        event_assignment[label.obligation_id] = event_candidates[
                            0
                        ].event_identity_key
                else:
                    event_candidates = [
                        item
                        for item in sidecar.event_candidates
                        if item.span.evidence_id == label.evidence_id
                    ]
                    matched = any(
                        _time_matches(label.expected, item)
                        for item in event_candidates
                    )
            covered += int(matched)
        output[kind] = {
            "covered": covered,
            "denominator": len(labels),
            "recall": covered / len(labels) if labels else 1.0,
        }
    identity_values = list(event_assignment.values())
    output["EVENT_IDENTITY"]["identity_collisions"] = len(identity_values) - len(
        set(identity_values)
    )
    return output


def _identity_candidates(
    obligation_id: str,
    candidates: Sequence[FormationEventCandidateV01],
) -> list[FormationEventCandidateV01]:
    suffix = obligation_id.split(":", 1)[0].rsplit("-", 1)[-1].casefold()
    subject_matches = [
        item
        for item in candidates
        if item.primary_subject is not None
        and item.primary_subject.casefold() == suffix
    ]
    return subject_matches or list(candidates)


def _time_matches(expected: str, candidate: FormationEventCandidateV01) -> bool:
    if candidate.occurrence_time is None:
        return False
    if expected.startswith("valid_to="):
        expected_date = expected.split("=", 1)[1]
        return (
            candidate.occurrence_time.end is not None
            and candidate.occurrence_time.end.date().isoformat() == expected_date
        )
    expected_date = expected.split("=", 1)[-1]
    return (
        candidate.occurrence_time.start is not None
        and candidate.occurrence_time.start.date().isoformat() == expected_date
    )


def _anchor_sources(
    anchor_text: str,
    target: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    wanted = _terms(anchor_text)
    scored = []
    for candidate in candidates:
        if candidate["evidence_id"] == target["evidence_id"]:
            continue
        score = len(wanted.intersection(_terms(str(candidate["content"]))))
        if score >= 2:
            scored.append((score, str(candidate["evidence_id"]), candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:2]]


def _terms(value: str) -> set[str]:
    return {
        item.casefold()
        for item in _WORD.findall(value)
        if len(item) > 2 and item.casefold() not in _STOP
    }


def _span_matches(
    candidate_start: int,
    candidate_end: int,
    label_start: int,
    label_end: int,
) -> bool:
    return candidate_start <= label_start and candidate_end >= label_end


def _compact_ordinals(source_ref: str) -> tuple[int, int]:
    parts = source_ref.split(":")
    try:
        return int(parts[1].removeprefix("s")), int(parts[-1].removeprefix("t"))
    except (IndexError, ValueError) as error:
        raise MF03EffectError("MF03_COMPACT_SOURCE_REF_INVALID") from error


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MF03EffectError(f"MF03_JSON_OBJECT_REQUIRED:{path}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MF03EffectError(f"MF03_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = [
    "MODEL_ID",
    "MF03EffectError",
    "ResidualBatch",
    "derive_residual_batches",
    "execute_mf03_effect",
    "load_formation_sources",
    "score_mf03_effect",
]
