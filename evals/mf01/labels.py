"""Typed S1 label seal for the MF-01 formation first-loss audit."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Self

from milai.domain.requirement_state import canonical_sha256
from pydantic import BaseModel, ConfigDict, Field, model_validator

ObligationKind = Literal[
    "EPISODE_BOUNDARY",
    "ENTITY_MENTION",
    "ENTITY_IDENTITY",
    "EVENT_MENTION",
    "EVENT_IDENTITY",
    "EVENT_OCCURRENCE_TIME",
    "STATE_ASSERTION",
    "STATE_TRANSITION",
    "CANONICAL_DISPOSITION",
    "RETRIEVAL_PROJECTION",
]
ALL_OBLIGATION_KINDS: tuple[ObligationKind, ...] = (
    "EPISODE_BOUNDARY",
    "ENTITY_MENTION",
    "ENTITY_IDENTITY",
    "EVENT_MENTION",
    "EVENT_IDENTITY",
    "EVENT_OCCURRENCE_TIME",
    "STATE_ASSERTION",
    "STATE_TRANSITION",
    "CANONICAL_DISPOSITION",
    "RETRIEVAL_PROJECTION",
)

RAW_SNAPSHOT = Path("var/dg11/paper/freeze/longmemeval-full-inputs.json")
BASE_LABELS = Path("evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json")
SUPPLEMENT = Path(
    "evals/mf01/fixtures/formation-first-loss-label-supplement.v0.1.json"
)


class MF01LabelError(RuntimeError):
    """The S1 label seal is incomplete, ambiguous, or source-inexact."""


class FormationObligationLabel(BaseModel):
    """One source-grounded, scorer-visible lifecycle obligation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    speaker: Literal["user"] = "user"
    obligation_id: str = Field(min_length=1)
    obligation_kind: ObligationKind
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    span_text: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    acceptable_alternatives: list[str] = Field(default_factory=list)
    expected_canonical_disposition: Literal[
        "NOT_APPLICABLE_QUERY_EVIDENCE_ONLY",
        "GOVERNED_REVIEW_REQUIRED",
        "AUTHORIZED_REJECTION",
    ]
    annotation_status: Literal[
        "IMPORTED_SEALED_OPENED_DEVELOPMENT",
        "SEALED_SYNTHETIC_LOCAL",
    ]
    origin: Literal["DG17_OPENED_DEVELOPMENT", "MF01_SYNTHETIC_LOCAL"]

    @model_validator(mode="after")
    def validate_span_and_alternatives(self) -> Self:
        if self.span_end - self.span_start != len(self.span_text):
            raise ValueError("label span width must equal Python character length")
        if self.acceptable_alternatives != sorted(
            set(self.acceptable_alternatives)
        ):
            raise ValueError("acceptable alternatives must be sorted and unique")
        return self


class FormationLabelSeal(BaseModel):
    """Fully expanded and digest-addressed MF-01 S1 label set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["milai.mf01.formation-label-seal.v0.1"] = (
        "milai.mf01.formation-label-seal.v0.1"
    )
    labels: list[FormationObligationLabel]
    counts_by_kind: dict[str, int]
    counts_by_origin: dict[str, int]
    case_count: int = Field(ge=1)
    label_count: int = Field(ge=1)
    scope_coverage: float = Field(ge=0.0, le=1.0)
    determinability: float = Field(ge=0.0, le=1.0)
    adequate_for_s2_entry_review: bool
    formal_holdout_used: Literal[False] = False
    seal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        if self.label_count != len(self.labels):
            raise ValueError("label count drift")
        if self.case_count != len({item.case_id for item in self.labels}):
            raise ValueError("case count drift")
        observed_counts = Counter(item.obligation_kind for item in self.labels)
        if self.counts_by_kind != dict(sorted(observed_counts.items())):
            raise ValueError("obligation-kind count drift")
        observed_origins = Counter(item.origin for item in self.labels)
        if self.counts_by_origin != dict(sorted(observed_origins.items())):
            raise ValueError("origin count drift")
        if len({item.obligation_id for item in self.labels}) != len(self.labels):
            raise ValueError("obligation identities must be globally unique")
        material = self.model_dump(mode="json", exclude={"seal_digest"})
        if self.seal_digest != canonical_sha256(material):
            raise ValueError("label seal digest mismatch")
        return self


def build_label_seal(root: Path) -> FormationLabelSeal:
    """Validate raw spans and expand the frozen DG-17 import plus local supplement."""

    root = root.resolve()
    raw_path = root / RAW_SNAPSHOT
    base_path = root / BASE_LABELS
    supplement_path = root / SUPPLEMENT
    supplement = _object(supplement_path)
    if supplement.get("schema") != "milai.mf01.formation-label-supplement.v0.1":
        raise MF01LabelError("MF01_SUPPLEMENT_SCHEMA_DRIFT")
    if supplement.get("annotation_status") != "SEALED_FOR_S1":
        raise MF01LabelError("MF01_SUPPLEMENT_NOT_SEALED")
    policy = _object_value(supplement.get("adequacy_policy"), "adequacy policy")
    if policy.get("formal_holdout_allowed") is not False:
        raise MF01LabelError("MF01_FORMAL_HOLDOUT_POLICY_DRIFT")

    raw = _object(raw_path)
    base = _object(base_path)
    if base.get("schema") != "milai.dg17.answer-bearing-labels.v0.1":
        raise MF01LabelError("MF01_BASE_LABEL_SCHEMA_DRIFT")
    if base.get("input_sha256") != _sha256_file(raw_path):
        raise MF01LabelError("MF01_RAW_SNAPSHOT_IDENTITY_DRIFT")
    raw_cases = {
        str(case["source_id"]): case
        for value in _list_value(raw.get("cases"), "raw cases")
        for case in [_object_value(value, "raw case")]
    }
    labels = _expand_base_labels(base, raw_cases)
    labels.extend(_synthetic_labels(supplement))
    labels.sort(key=lambda item: (item.case_id, item.obligation_id))

    counts = Counter(item.obligation_kind for item in labels)
    origins = Counter(item.origin for item in labels)
    minimum = int(policy["minimum_labels_per_obligation_kind"])
    scope = 1.0
    determinability = sum(bool(item.expected) for item in labels) / len(labels)
    adequate = (
        all(counts.get(kind, 0) >= minimum for kind in ALL_OBLIGATION_KINDS)
        and scope >= float(policy["required_scope_coverage"])
        and determinability >= float(policy["required_determinability"])
    )
    material: dict[str, Any] = {
        "schema_version": "milai.mf01.formation-label-seal.v0.1",
        "labels": [item.model_dump(mode="json") for item in labels],
        "counts_by_kind": dict(sorted(counts.items())),
        "counts_by_origin": dict(sorted(origins.items())),
        "case_count": len({item.case_id for item in labels}),
        "label_count": len(labels),
        "scope_coverage": scope,
        "determinability": determinability,
        "adequate_for_s2_entry_review": adequate,
        "formal_holdout_used": False,
    }
    return FormationLabelSeal(**material, seal_digest=canonical_sha256(material))


def _expand_base_labels(
    base: dict[str, Any],
    raw_cases: dict[str, dict[str, Any]],
) -> list[FormationObligationLabel]:
    output: list[FormationObligationLabel] = []
    mapping: dict[str, tuple[ObligationKind, ...]] = {
        "EVENT": (
            "EVENT_MENTION",
            "EVENT_IDENTITY",
            "CANONICAL_DISPOSITION",
            "RETRIEVAL_PROJECTION",
        ),
        "PREFERENCE_SIGNAL": (
            "STATE_ASSERTION",
            "CANONICAL_DISPOSITION",
            "RETRIEVAL_PROJECTION",
        ),
    }
    for raw_case in _list_value(base.get("cases"), "base cases"):
        case = _object_value(raw_case, "base case")
        case_id = str(case["case_id"])
        source_case = raw_cases.get(case_id)
        if source_case is None:
            raise MF01LabelError(f"MF01_BASE_CASE_SOURCE_MISSING:{case_id}")
        for raw_atom in _list_value(case.get("atoms"), f"atoms {case_id}"):
            atom = _object_value(raw_atom, "base atom")
            atom_type = str(atom["atom_type"])
            kinds = mapping.get(atom_type)
            if kinds is None:
                raise MF01LabelError(f"MF01_BASE_ATOM_TYPE_UNMAPPED:{atom_type}")
            session_ordinal = int(atom["session_ordinal"])
            turn_ordinal = int(atom["turn_ordinal"])
            sessions = _list_value(source_case.get("sessions"), "raw sessions")
            if session_ordinal >= len(sessions):
                raise MF01LabelError("MF01_BASE_SESSION_ORDINAL_INVALID")
            session = _object_value(sessions[session_ordinal], "raw session")
            if str(session["session_id"]) != str(atom["session_id"]):
                raise MF01LabelError("MF01_BASE_SESSION_IDENTITY_DRIFT")
            turns = _list_value(session.get("turns"), "raw turns")
            if turn_ordinal >= len(turns):
                raise MF01LabelError("MF01_BASE_TURN_ORDINAL_INVALID")
            turn = _object_value(turns[turn_ordinal], "raw turn")
            if turn.get("role") != "user" or atom.get("speaker") != "user":
                raise MF01LabelError("MF01_BASE_SOURCE_ROLE_INVALID")
            content = str(turn["content"])
            span = _object_value(atom.get("span"), "base atom span")
            start, end, text = int(span["start"]), int(span["end"]), str(span["text"])
            if content[start:end] != text:
                raise MF01LabelError("MF01_BASE_SOURCE_SPAN_DRIFT")
            source_ref = str(atom["source_turn_ref"])
            expected_by_kind = {
                "EVENT_MENTION": text,
                "EVENT_IDENTITY": f"event:{case_id}:{atom['atom_id']}",
                "STATE_ASSERTION": text,
                "CANONICAL_DISPOSITION": "NOT_APPLICABLE_QUERY_EVIDENCE_ONLY",
                "RETRIEVAL_PROJECTION": f"source-ref:{source_ref}",
            }
            for kind in kinds:
                output.append(
                    FormationObligationLabel(
                        case_id=case_id,
                        evidence_id=f"opened-dev:{source_ref}",
                        source_ref=source_ref,
                        obligation_id=f"{atom['atom_id']}:{kind}",
                        obligation_kind=kind,
                        span_start=start,
                        span_end=end,
                        span_text=text,
                        expected=expected_by_kind[kind],
                        acceptable_alternatives=[],
                        expected_canonical_disposition=(
                            "NOT_APPLICABLE_QUERY_EVIDENCE_ONLY"
                        ),
                        annotation_status="IMPORTED_SEALED_OPENED_DEVELOPMENT",
                        origin="DG17_OPENED_DEVELOPMENT",
                    )
                )
    return output


def _synthetic_labels(supplement: dict[str, Any]) -> list[FormationObligationLabel]:
    output: list[FormationObligationLabel] = []
    for raw_case in _list_value(supplement.get("synthetic_cases"), "synthetic cases"):
        case = _object_value(raw_case, "synthetic case")
        content = str(case["content"])
        if case.get("speaker") != "user":
            raise MF01LabelError("MF01_SYNTHETIC_SOURCE_ROLE_INVALID")
        for raw_label in _list_value(case.get("labels"), "synthetic labels"):
            label = _object_value(raw_label, "synthetic label")
            material = {
                "case_id": str(case["case_id"]),
                "evidence_id": str(case["evidence_id"]),
                "source_ref": str(case["source_ref"]),
                "speaker": "user",
                **label,
                "origin": "MF01_SYNTHETIC_LOCAL",
            }
            parsed = FormationObligationLabel.model_validate(material)
            if content[parsed.span_start : parsed.span_end] != parsed.span_text:
                raise MF01LabelError(
                    f"MF01_SYNTHETIC_SOURCE_SPAN_DRIFT:{parsed.obligation_id}"
                )
            output.append(parsed)
    return output


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _object_value(value, str(path))


def _object_value(value: object, source: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MF01LabelError(f"MF01_JSON_OBJECT_REQUIRED:{source}")
    return value


def _list_value(value: object, source: str) -> list[Any]:
    if not isinstance(value, list):
        raise MF01LabelError(f"MF01_JSON_LIST_REQUIRED:{source}")
    return value


__all__ = [
    "ALL_OBLIGATION_KINDS",
    "BASE_LABELS",
    "RAW_SNAPSHOT",
    "SUPPLEMENT",
    "FormationLabelSeal",
    "FormationObligationLabel",
    "MF01LabelError",
    "ObligationKind",
    "build_label_seal",
]
