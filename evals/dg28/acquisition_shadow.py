"""Build a read-only identity union from frozen official acquisition outputs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from milai.domain.requirement_state import canonical_sha256

ATTRIBUTIONS = Path(
    "var/dg24/s6/dg24-s6-scoring-20260829-003/requirement-loss-attributions.json"
)
OFFICIAL_PROBES = Path(
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
    "sealed-official-probe-traces.json"
)
CHANNELS = (
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
)
OFFICIAL_EXECUTOR = "milai-official-retrieval-audit-probe-v0.1"
OFFICIAL_REPOSITORY = "milai.persistence.RetrievalRepository"
_LONG_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)


class DG28PreparationError(RuntimeError):
    """The official acquisition snapshot or identity union is invalid."""


def build_acquisition_shadow(root: Path) -> dict[str, Any]:
    """Freeze the seven targets and union official channel outputs by Evidence ID."""

    root = root.resolve()
    targets = _targets(_json(root / ATTRIBUTIONS))
    probe_bundle = _mapping(_json(root / OFFICIAL_PROBES), "probe bundle")
    if probe_bundle.get("schema") != "milai.dg24.sealed-official-probe-collection.v0.1":
        raise DG28PreparationError("DG28_OFFICIAL_PROBE_SCHEMA_DRIFT")
    traces: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for raw_record in _sequence(probe_bundle.get("records"), "probe records"):
        record = _mapping(raw_record, "probe record")
        trace = _mapping(record.get("trace"), "official trace")
        key = (
            str(record.get("case_id")),
            str(trace.get("requirement_id")),
            str(trace.get("channel")),
        )
        if key in traces:
            raise DG28PreparationError("DG28_DUPLICATE_OFFICIAL_QUERY_CHANNEL")
        traces[key] = trace

    pairs = sorted({(item["case_id"], item["requirement_id"]) for item in targets})
    records: list[dict[str, Any]] = []
    for case_id, requirement_id in pairs:
        candidates: dict[str, dict[str, Any]] = {}
        calls: list[dict[str, Any]] = []
        for channel in CHANNELS:
            trace_value = traces.get((case_id, requirement_id, channel))
            if trace_value is None:
                raise DG28PreparationError(
                    f"DG28_OFFICIAL_QUERY_CHANNEL_MISSING:{case_id}:{requirement_id}:{channel}"
                )
            trace = trace_value
            if (
                trace.get("official_executor_identity") != OFFICIAL_EXECUTOR
                or trace.get("repository_identity") != OFFICIAL_REPOSITORY
                or trace.get("product_binding_consumed") is not False
            ):
                raise DG28PreparationError("DG28_OFFICIAL_EXECUTOR_IDENTITY_DRIFT")
            occurrences = _sequence(
                trace.get("returned_occurrences"), "returned occurrences"
            )
            calls.append(
                {
                    "channel": channel,
                    "disposition": trace.get("disposition"),
                    "reason_code": trace.get("reason_code"),
                    "requested_audit_cap": trace.get("requested_audit_cap"),
                    "returned_occurrence_count": len(occurrences),
                    "request_identity": trace.get("request_identity"),
                    "query_digest": trace.get("query_digest"),
                    "index_identity": trace.get("index_identity"),
                    "official_executor_identity": trace.get(
                        "official_executor_identity"
                    ),
                    "repository_identity": trace.get("repository_identity"),
                    "historical_official_call_count": 1,
                    "new_call_during_preparation": False,
                }
            )
            for raw_occurrence in occurrences:
                occurrence = _mapping(raw_occurrence, "occurrence")
                if occurrence.get("channel") != channel:
                    raise DG28PreparationError("DG28_OCCURRENCE_CHANNEL_DRIFT")
                evidence = _mapping(
                    occurrence.get("evidence_record_identity"), "evidence identity"
                )
                evidence_id = str(evidence.get("evidence_id", ""))
                source_ref = str(evidence.get("source_ref", ""))
                if not evidence_id or _source_case_id(source_ref) != case_id:
                    raise DG28PreparationError("DG28_EVIDENCE_SCOPE_IDENTITY_DRIFT")
                identity = {
                    "evidence_id": evidence_id,
                    "source_ref": source_ref,
                    "content_hash": evidence.get("content_hash"),
                    "observed_at": evidence.get("observed_at"),
                    "permission_snapshot_digest": evidence.get(
                        "permission_snapshot_digest"
                    ),
                    "retention_snapshot_digest": evidence.get(
                        "retention_snapshot_digest"
                    ),
                    "tenant_scope_digest": evidence.get("tenant_scope_digest"),
                }
                existing = candidates.get(evidence_id)
                if existing is None:
                    existing = {**identity, "channel_lineage": []}
                    candidates[evidence_id] = existing
                elif any(existing[key] != value for key, value in identity.items()):
                    raise DG28PreparationError("DG28_CROSS_CHANNEL_EVIDENCE_IDENTITY_DRIFT")
                lineage = existing["channel_lineage"]
                if not isinstance(lineage, list):
                    raise DG28PreparationError("DG28_CHANNEL_LINEAGE_SHAPE_INVALID")
                lineage.append(
                    {
                        "channel": channel,
                        "raw_rank": occurrence.get("raw_rank"),
                        "raw_score": occurrence.get("raw_score"),
                        "occurrence_id": occurrence.get("occurrence_id"),
                        "request_identity": occurrence.get("request_identity"),
                        "channel_query_digest": occurrence.get(
                            "channel_query_digest"
                        ),
                        "index_identity": trace.get("index_identity"),
                    }
                )
        candidate_rows = [candidates[key] for key in sorted(candidates)]
        group_rows = [
            item
            for item in targets
            if item["case_id"] == case_id
            and item["requirement_id"] == requirement_id
        ]
        target_hits = [
            {
                "equivalence_group_id": group["equivalence_group_id"],
                "acceptable_source_turn_ref": group["acceptable_source_turn_ref"],
                "candidate_evidence_ids": [
                    candidate["evidence_id"]
                    for candidate in candidate_rows
                    if _compact_source_ref(str(candidate["source_ref"]))
                    == group["acceptable_source_turn_ref"]
                ],
            }
            for group in group_rows
        ]
        records.append(
            {
                "case_id": case_id,
                "requirement_id": requirement_id,
                "target_group_count": len(group_rows),
                "channel_calls": calls,
                "union_candidates": candidate_rows,
                "union_candidate_count": len(candidate_rows),
                "target_group_candidate_hits": target_hits,
                "identity_dedup_only": True,
                "gate_executed": False,
                "binding_executed": False,
                "sufficiency_executed": False,
                "reader_executed": False,
            }
        )
    output: dict[str, Any] = {
        "schema": "milai.dg28.acquisition-only-shadow.v0.1",
        "target_groups": targets,
        "target_group_count": len(targets),
        "query_requirement_count": len(pairs),
        "channels": list(CHANNELS),
        "records": records,
        "official_probe_run_id": probe_bundle.get("run_id"),
        "official_executor_identity": OFFICIAL_EXECUTOR,
        "repository_identity": OFFICIAL_REPOSITORY,
        "new_official_calls": 0,
        "historical_official_calls_replayed": len(pairs) * len(CHANNELS),
        "candidate_feature_flag": "OFF",
        "formal_holdout_used": False,
        "decision_chain_entered": False,
    }
    output["shadow_digest"] = canonical_sha256(output)
    return output


def _targets(value: object) -> list[dict[str, str]]:
    rows = []
    for raw in _sequence(value, "attributions"):
        item = _mapping(raw, "attribution")
        reason = str(item.get("first_loss_reason"))
        if reason not in {"CHANNEL_ELIGIBLE_NOT_INVOKED", "CHANNEL_CUTOFF_DROP"}:
            continue
        rows.append(
            {
                "case_id": str(item["query_id"]),
                "requirement_id": str(item["requirement_id"]),
                "equivalence_group_id": str(item["equivalence_group_id"]),
                "evidence_role": str(item["evidence_role"]),
                "acceptable_source_turn_ref": str(
                    item["acceptable_source_turn_ref"]
                ),
                "preregistered_first_loss_reason": reason,
            }
        )
    rows.sort(key=lambda item: (item["case_id"], item["equivalence_group_id"]))
    reasons = {item["preregistered_first_loss_reason"] for item in rows}
    if len(rows) != 7 or reasons != {
        "CHANNEL_ELIGIBLE_NOT_INVOKED",
        "CHANNEL_CUTOFF_DROP",
    }:
        raise DG28PreparationError("DG28_TARGET_DENOMINATOR_DRIFT")
    return rows


def _source_case_id(source_ref: str) -> str | None:
    match = _LONG_SOURCE_REF.match(source_ref)
    return unquote(match.group(1)) if match is not None else None


def _compact_source_ref(value: str) -> str:
    match = _LONG_SOURCE_REF.match(value)
    if match is None:
        return value.split("?", 1)[0]
    case_id, session_ordinal, session_id, turn_ordinal = match.groups()
    return f"{unquote(case_id)}:s{session_ordinal}:{unquote(session_id)}:t{turn_ordinal}"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG28PreparationError(f"DG28_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG28PreparationError(f"DG28_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = [
    "ATTRIBUTIONS",
    "CHANNELS",
    "OFFICIAL_PROBES",
    "DG28PreparationError",
    "build_acquisition_shadow",
]
