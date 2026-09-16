"""Build and apply the minimal MF-03 event-identity sidecar."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

from milai.application.evidence_source import evidence_source_turn_identity
from milai.domain.formation_identity import (
    FormationEventIdentityClusterV01,
    FormationEventIdentitySidecarV01,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    RequirementBinding,
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "the",
        "to",
        "user",
        "was",
        "with",
    }
)
_POLICY = "formation-event-identity-v0.1"


def build_event_identity_sidecar(
    requirements: Sequence[EvidenceRequirementV02],
    bindings: Sequence[RequirementBinding],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    spans: Sequence[EvidenceSpan],
) -> FormationEventIdentitySidecarV01:
    """Cluster repeated event observations without replacing their raw Evidence."""

    requirement_by_id = {item.slot_id: item for item in requirements}
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {item.span_id: item for item in spans}
    grouped: dict[tuple[str, str], list[tuple[RequirementBinding, EvidenceSpan]]] = (
        defaultdict(list)
    )
    unresolved: set[str] = set()
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        requirement = requirement_by_id.get(binding.requirement_id)
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        if requirement is None or interpretation is None or interpretation.kind != "EVENT":
            continue
        span = span_by_id[interpretation.span_id]
        identity_key = _event_identity_key(requirement, interpretation, span)
        if identity_key is None:
            unresolved.add(interpretation.interpretation_id)
            identity_key = f"unresolved:{interpretation.interpretation_id}"
        grouped[(binding.requirement_id, identity_key)].append((binding, span))

    clusters: list[FormationEventIdentityClusterV01] = []
    for (requirement_id, identity_key), rows in sorted(grouped.items()):
        evidence_ids = sorted({span.source_evidence_id for _binding, span in rows})
        representative = min(
            (span for _binding, span in rows),
            key=_provenance_order,
        ).source_evidence_id
        interpretation_ids = sorted(
            {binding.interpretation_id for binding, _span in rows}
        )
        occurrence_key = identity_key.split("|", 1)[0]
        provisional = FormationEventIdentityClusterV01.model_construct(
            cluster_digest="0" * 64,
            requirement_id=requirement_id,
            identity_key=identity_key,
            representative_evidence_id=representative,
            source_evidence_ids=evidence_ids,
            interpretation_ids=interpretation_ids,
            occurrence_time_key=(
                None if occurrence_key.startswith("unresolved:") else occurrence_key
            ),
        )
        material = provisional.model_dump(mode="json", exclude={"cluster_digest"})
        clusters.append(
            FormationEventIdentityClusterV01(
                cluster_digest=canonical_sha256(material),
                **material,
            )
        )
    clusters.sort(key=lambda item: (item.requirement_id, item.identity_key))
    source_snapshot = canonical_sha256(
        [
            {
                "span_id": item.span_id,
                "evidence_id": item.source_evidence_id,
                "source_ref": item.source_turn_ref,
                "text": item.text,
            }
            for item in sorted(spans, key=lambda item: item.span_id)
        ]
    )
    duplicate_count = sum(len(item.source_evidence_ids) - 1 for item in clusters)
    provisional_sidecar = FormationEventIdentitySidecarV01.model_construct(
        sidecar_digest="0" * 64,
        source_snapshot_digest=source_snapshot,
        clusters=clusters,
        duplicate_evidence_count=duplicate_count,
        unresolved_interpretation_ids=sorted(unresolved),
    )
    sidecar_material = provisional_sidecar.model_dump(
        mode="json", exclude={"sidecar_digest"}
    )
    return FormationEventIdentitySidecarV01(
        sidecar_digest=canonical_sha256(sidecar_material),
        **sidecar_material,
    )


def select_event_identity_representatives(
    requirements: Sequence[EvidenceRequirementV02],
    bindings: Sequence[RequirementBinding],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    spans: Sequence[EvidenceSpan],
) -> tuple[list[RequirementBinding], FormationEventIdentitySidecarV01]:
    """Keep one MATCH per Evidence identity cluster; preserve all other rows."""

    sidecar = build_event_identity_sidecar(
        requirements,
        bindings,
        interpretations,
        spans,
    )
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {item.span_id: item for item in spans}
    representative_by_interpretation = {
        interpretation_id: cluster.representative_evidence_id
        for cluster in sidecar.clusters
        for interpretation_id in cluster.interpretation_ids
    }
    selected: list[RequirementBinding] = []
    for binding in bindings:
        representative = representative_by_interpretation.get(binding.interpretation_id)
        if binding.status == "MATCH" and representative is not None:
            interpretation = interpretation_by_id[binding.interpretation_id]
            evidence_id = span_by_id[interpretation.span_id].source_evidence_id
            if evidence_id != representative:
                continue
        selected.append(binding)
    return selected, sidecar


def _event_identity_key(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
) -> str | None:
    event_time = interpretation.event_time
    if event_time is None or event_time.start is None:
        return None
    event_end = event_time.end or event_time.start
    time_key = f"{event_time.start.isoformat()}/{event_end.isoformat()}"
    value = interpretation.value
    explicit_identity = (
        value.get("event_identity") if isinstance(value, Mapping) else None
    )
    if isinstance(explicit_identity, str) and explicit_identity:
        return f"{time_key}|explicit:{explicit_identity.casefold()}"
    if requirement.cardinality.maximum == 1:
        return f"{time_key}|singleton:{requirement.slot_id.casefold()}"
    terms = sorted(
        {
            word.casefold()
            for word in _WORD.findall(span.text)
            if len(word) > 2 and word.casefold() not in _STOP
        }
    )
    signature = "-".join(terms[:12]) or "event"
    return f"{time_key}|event:{signature}"


def _provenance_order(span: EvidenceSpan) -> tuple[object, ...]:
    turn_identity = evidence_source_turn_identity(span.source_turn_ref)
    session = turn_identity[0] if turn_identity is not None else span.session_id
    turn = turn_identity[1] if turn_identity is not None else 2**31 - 1
    return (
        span.source_timestamp.isoformat() if span.source_timestamp is not None else "",
        session,
        turn,
        span.start,
        span.source_evidence_id,
    )


__all__ = [
    "build_event_identity_sidecar",
    "select_event_identity_representatives",
]
