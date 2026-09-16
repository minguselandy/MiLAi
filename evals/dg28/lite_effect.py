"""Lean DG-28 effect over the frozen official lexical channel outputs.

The treatment is deliberately small: FTS_RAW@10 and FTS_ENRICHED@20 are
unioned by Evidence identity, hydrated from the frozen label-free source
snapshot, and passed through the current deterministic DecisionBoundary.
No new acquisition, model, Reader, or canonical write is performed here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

from milai.application.decision_boundary import decide_deterministic_boundary
from milai.domain.acquisition import AcquisitionPlan, CandidateEnvelope
from milai.domain.decision_boundary import DecisionBoundaryResultV02
from milai.domain.requirement_state import canonical_sha256

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg26.stateview_reranking import load_experiment_inputs
from evals.dg27.decision_boundary import (
    DG26_LOCK,
    GOLD_REGISTRY,
    _case_inputs,
    _compact_source_ref,
    _gold_groups,
    _proofs_by_case,
)
from evals.dg28.acquisition_shadow import build_acquisition_shadow

RAW_CAP = 10
ENRICHED_CAP = 20
CHANNEL_CAPS = {"FTS_RAW": RAW_CAP, "FTS_ENRICHED": ENRICHED_CAP}
_LONG_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)


class DG28LiteEffectError(RuntimeError):
    """The frozen source identity or lean treatment contract drifted."""


def execute_lite_effect(root: Path) -> dict[str, Any]:
    """Run baseline and lexical-union treatment without consulting labels."""

    root = root.resolve()
    inputs = load_experiment_inputs(root, root / DG26_LOCK)
    proofs = _proofs_by_case(root)
    baseline_cases = _case_inputs(inputs)
    shadow = build_acquisition_shadow(root)
    source_cases, selection = load_public_dev_cases()
    source_by_case = {case.case_id: case for case in source_cases}

    baseline_rows: list[dict[str, Any]] = []
    treatment_rows: list[dict[str, Any]] = []
    for raw_record in _sequence(shadow.get("records"), "shadow records"):
        record = _mapping(raw_record, "shadow record")
        case_id = str(record["case_id"])
        requirement_id = str(record["requirement_id"])
        context = inputs.contexts[case_id]
        if context.requirement_ids != (requirement_id,):
            raise DG28LiteEffectError("DG28_LITE_EXPECTS_ONE_TARGET_REQUIREMENT")

        baseline_case = baseline_cases[case_id]
        baseline_decision = decide_deterministic_boundary(
            plan=context.acquisition_plan,
            query_ir=context.query_ir,
            acquisition_capability_digest=str(baseline_case["capability_digest"]),
            candidates=cast(Sequence[CandidateEnvelope], baseline_case["candidates"]),
            source_records=list(
                cast(Mapping[str, Mapping[str, Any]], baseline_case["source_by_id"]).values()
            ),
            completion_proof=proofs[case_id],
        )
        baseline_rows.append(
            _decision_row(
                case_id,
                requirement_id,
                cast(Sequence[CandidateEnvelope], baseline_case["candidates"]),
                baseline_decision,
            )
        )

        selected = select_lite_candidates(record)
        plan = _lite_plan(context.acquisition_plan, requirement_id, len(selected))
        candidates, source_records = _hydrate_lite_candidates(
            case_id=case_id,
            requirement_id=requirement_id,
            selected=selected,
            source_case=source_by_case[case_id],
        )
        capability_digest = canonical_sha256(
            {
                "policy": "DG28_LITE_OFFICIAL_LEXICAL_UNION_V01",
                "channels": CHANNEL_CAPS,
                "candidate_ids": [item.candidate_id for item in candidates],
                "historical_official_probe_run_id": shadow[
                    "official_probe_run_id"
                ],
            }
        )
        treatment_decision = decide_deterministic_boundary(
            plan=plan,
            query_ir=context.query_ir,
            acquisition_capability_digest=capability_digest,
            candidates=candidates,
            source_records=source_records,
            completion_proof=proofs[case_id],
        )
        treatment_rows.append(
            _decision_row(
                case_id,
                requirement_id,
                candidates,
                treatment_decision,
            )
        )

    output: dict[str, Any] = {
        "schema": "milai.dg28.lite-unscored-effect.v0.1",
        "policy": {
            "channels": CHANNEL_CAPS,
            "fusion": "IDENTITY_DEDUP_RRF_K60",
            "model_planner": False,
            "dense": False,
            "temporal_channel": False,
            "second_round": False,
        },
        "source_selection": selection,
        "baseline": baseline_rows,
        "treatment": treatment_rows,
        "cost": {
            "new_official_acquisition_calls": 0,
            "historical_official_outputs_replayed": 6,
            "model_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "automatic_retries": 0,
        },
        "candidate_feature_flag": "OFF",
        "formal_holdout_used": False,
    }
    output["unscored_digest"] = canonical_sha256(output)
    return output


def score_lite_effect(root: Path, unscored: Mapping[str, Any]) -> dict[str, Any]:
    """Open the development scorer only after both decisions are sealed."""

    root = root.resolve()
    shadow = build_acquisition_shadow(root)
    targets = [
        _mapping(value, "target group")
        for value in _sequence(shadow.get("target_groups"), "target groups")
    ]
    gold_value = _json_object(root / GOLD_REGISTRY)
    groups = _gold_groups(gold_value)
    target_ids = {str(item["equivalence_group_id"]) for item in targets}
    relevant_keys = {
        (str(item["case_id"]), str(item["requirement_id"])) for item in targets
    }
    relevant_groups = {
        key: refs for key, refs in groups.items() if key[:2] in relevant_keys
    }
    if len(target_ids) != 7 or len(relevant_groups) != 10:
        raise DG28LiteEffectError("DG28_LITE_SCORER_DENOMINATOR_DRIFT")

    baseline_rows = [
        _mapping(value, "baseline row")
        for value in _sequence(unscored.get("baseline"), "baseline rows")
    ]
    treatment_rows = [
        _mapping(value, "treatment row")
        for value in _sequence(unscored.get("treatment"), "treatment rows")
    ]
    baseline = _arm_metrics(baseline_rows, relevant_groups, target_ids)
    treatment = _arm_metrics(treatment_rows, relevant_groups, target_ids)
    baseline_binding_groups = set(cast(list[str], baseline["binding_group_ids"]))
    treatment_binding_groups = set(cast(list[str], treatment["binding_group_ids"]))
    lost = sorted(baseline_binding_groups - treatment_binding_groups)

    baseline_candidate_sources = {
        _compact_source_ref(str(source))
        for row in baseline_rows
        for source in _sequence(row.get("candidate_sources"), "baseline candidates")
    }
    treatment_candidate_sources = {
        _compact_source_ref(str(source))
        for row in treatment_rows
        for source in _sequence(row.get("candidate_sources"), "treatment candidates")
    }
    treatment_accepted_sources = {
        _compact_source_ref(str(source))
        for row in treatment_rows
        for source in _sequence(row.get("accepted_sources"), "treatment accepted")
    }
    new_sources = treatment_candidate_sources - baseline_candidate_sources
    gold_sources = {source for refs in relevant_groups.values() for source in refs}
    useful_new_sources = new_sources & treatment_accepted_sources & gold_sources

    checks = {
        "target_candidate_recall_complete": treatment[
            "target_candidate_groups"
        ]
        == 7,
        "target_binding_gain_positive": treatment["target_binding_groups"]
        > baseline["target_binding_groups"],
        "accepted_binding_precision_one": treatment[
            "accepted_binding_precision"
        ]
        == 1.0,
        "baseline_binding_group_non_regression": not lost,
        "wrong_complete_zero": treatment["wrong_complete"] == 0,
        "only_preregistered_lexical_channels": unscored["policy"]["channels"]
        == CHANNEL_CAPS,
        "new_external_calls_zero": all(
            int(unscored["cost"][key]) == 0
            for key in (
                "new_official_acquisition_calls",
                "model_calls",
                "reader_calls",
                "canonical_mutations",
                "automatic_retries",
            )
        ),
    }
    passed = all(checks.values())
    output: dict[str, Any] = {
        "schema": "milai.dg28.lite-effect-score.v0.1",
        "unscored_digest": unscored["unscored_digest"],
        "denominators": {
            "query_requirements": len(relevant_keys),
            "target_groups": len(target_ids),
            "all_relevant_groups": len(relevant_groups),
        },
        "baseline": baseline,
        "treatment": treatment,
        "delta": {
            "target_candidate_groups": treatment["target_candidate_groups"]
            - baseline["target_candidate_groups"],
            "target_binding_groups": treatment["target_binding_groups"]
            - baseline["target_binding_groups"],
            "all_binding_groups": treatment["all_binding_groups"]
            - baseline["all_binding_groups"],
            "candidate_count": treatment["candidate_count"]
            - baseline["candidate_count"],
        },
        "efficiency": {
            "new_candidate_sources": len(new_sources),
            "useful_new_candidate_sources": len(useful_new_sources),
            "useful_new_candidate_rate": (
                len(useful_new_sources) / len(new_sources) if new_sources else 0.0
            ),
            "additional_official_calls": 0,
            "model_calls": 0,
        },
        "baseline_binding_groups_lost": lost,
        "remaining_target_binding_groups": sorted(
            target_ids
            - set(cast(list[str], treatment["target_binding_group_ids"]))
        ),
        "checks": checks,
        "status": "PASS_DG28_LITE_RETRIEVAL_GAIN" if passed else "NEEDS_REPAIR",
        "next_route": (
            "MF03_EVENT_TIME_GROUNDING_FOR_RETRIEVED_UNBOUND_EVIDENCE"
            if passed
            else "REPAIR_DG28_LITE_WITHOUT_EXPANDING_CHANNELS"
        ),
        "dg29_refinding_entry": False,
        "dg29_reason": "NO_FRESH_DISCOVERY_GAP_AFTER_LEXICAL_UNION",
    }
    output["score_digest"] = canonical_sha256(output)
    return output


def select_lite_candidates(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select only the two predeclared lexical channels and fuse by RRF."""

    selected: list[dict[str, Any]] = []
    for raw_candidate in _sequence(record.get("union_candidates"), "union candidates"):
        candidate = dict(_mapping(raw_candidate, "union candidate"))
        qualifying = [
            dict(lineage)
            for raw_lineage in _sequence(
                candidate.get("channel_lineage"), "channel lineage"
            )
            for lineage in [_mapping(raw_lineage, "channel lineage")]
            if str(lineage.get("channel")) in CHANNEL_CAPS
            and _valid_rank(lineage.get("raw_rank"))
            and int(lineage["raw_rank"])
            <= CHANNEL_CAPS[str(lineage["channel"])]
        ]
        if not qualifying:
            continue
        qualifying.sort(key=lambda item: (str(item["channel"]), int(item["raw_rank"])))
        candidate["selected_channel_lineage"] = qualifying
        candidate["lite_fusion_score"] = sum(
            1.0 / (60 + int(item["raw_rank"])) for item in qualifying
        )
        selected.append(candidate)
    selected.sort(
        key=lambda item: (-float(item["lite_fusion_score"]), str(item["evidence_id"]))
    )
    expected = {"2e6d26dc": 24, "88432d0a": 10, "a82c026e": 10}
    case_id = str(record["case_id"])
    if len(selected) != expected.get(case_id):
        raise DG28LiteEffectError(f"DG28_LITE_CANDIDATE_DENOMINATOR_DRIFT:{case_id}")
    return selected


def _hydrate_lite_candidates(
    *,
    case_id: str,
    requirement_id: str,
    selected: Sequence[Mapping[str, Any]],
    source_case: Any,
) -> tuple[list[CandidateEnvelope], list[dict[str, Any]]]:
    candidates: list[CandidateEnvelope] = []
    source_records: list[dict[str, Any]] = []
    for fusion_rank, item in enumerate(selected, start=1):
        source = _source_record(case_id, item, source_case)
        source_records.append(source)
        lineages = [
            _mapping(value, "selected lineage")
            for value in _sequence(
                item.get("selected_channel_lineage"), "selected lineages"
            )
        ]
        channel_ranks = {
            str(value["channel"]): int(value["raw_rank"]) for value in lineages
        }
        channel_scores = {
            str(value["channel"]): float(value["raw_score"])
            for value in lineages
            if isinstance(value.get("raw_score"), (int, float))
            and not isinstance(value.get("raw_score"), bool)
        }
        probe_ids = {
            channel: f"dg28:{requirement_id}:{channel.lower()}"
            for channel in channel_ranks
        }
        candidates.append(
            CandidateEnvelope(
                candidate_id=str(item["evidence_id"]),
                source_evidence_id=str(item["evidence_id"]),
                source_turn_ref=str(item["source_ref"]),
                subject_id=str(source.get("subject_id") or source["session_id"]),
                session_id=str(source["session_id"]),
                turn_id=str(source.get("turn_id") or item["source_ref"]),
                identity_source="STRUCTURED_TURN_METADATA",
                speaker=cast(Any, source["speaker"]),
                speaker_source="STRUCTURED_TURN_METADATA",
                source_observed_at=cast(datetime, source["observed_at"]),
                matched_probes=sorted(probe_ids.values()),
                matched_slots=[requirement_id],
                channel_ranks=channel_ranks,
                channel_scores=channel_scores,
                probe_ranks={probe_ids[key]: value for key, value in channel_ranks.items()},
                probe_scores={
                    probe_ids[key]: value for key, value in channel_scores.items()
                },
                fusion_rank=fusion_rank,
                fusion_score=float(item["lite_fusion_score"]),
                matched_fields=sorted(
                    "raw_text" if key == "FTS_RAW" else "enriched_lexical_projection"
                    for key in channel_ranks
                ),
                body_ref=str(item["source_ref"]),
                body_hydrated=True,
            )
        )
    return candidates, source_records


def _source_record(
    case_id: str,
    candidate: Mapping[str, Any],
    source_case: Any,
) -> dict[str, Any]:
    source_ref = str(candidate["source_ref"])
    match = _LONG_SOURCE_REF.match(source_ref)
    if match is None:
        raise DG28LiteEffectError("DG28_LITE_SOURCE_REF_INVALID")
    source_case_id, session_ordinal, session_id, turn_ordinal = match.groups()
    if unquote(source_case_id) != case_id or source_case.case_id != case_id:
        raise DG28LiteEffectError("DG28_LITE_SOURCE_CASE_MISMATCH")
    session = source_case.sessions[int(session_ordinal)]
    if session.session_id != unquote(session_id):
        raise DG28LiteEffectError("DG28_LITE_SOURCE_SESSION_MISMATCH")
    turn = session.turns[int(turn_ordinal)]
    captured_body = f"{turn.role}: {turn.content}"
    if hashlib.sha256(captured_body.encode()).hexdigest() != candidate["content_hash"]:
        raise DG28LiteEffectError("DG28_LITE_CONTENT_HASH_MISMATCH")
    observed_at = datetime.fromisoformat(
        normalize_lme_timestamp(str(session.observed_at)).replace("Z", "+00:00")
    )
    if observed_at.isoformat() != candidate["observed_at"]:
        raise DG28LiteEffectError("DG28_LITE_OBSERVED_AT_MISMATCH")
    return {
        "evidence_id": str(candidate["evidence_id"]),
        "source_ref": source_ref,
        "content_hash": str(candidate["content_hash"]),
        "observed_at": observed_at,
        "speaker": str(turn.role),
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "session_id": session.session_id,
        "content": captured_body,
        "permission_snapshot": {"readable": True},
        "permission_snapshot_digest": candidate["permission_snapshot_digest"],
        "retention_snapshot_digest": candidate["retention_snapshot_digest"],
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
    }


def _lite_plan(
    baseline: AcquisitionPlan,
    requirement_id: str,
    candidate_count: int,
) -> AcquisitionPlan:
    raw_probe = baseline.probes[0].model_copy(
        update={
            "probe_id": f"dg28:{requirement_id}:fts_raw",
            "channel": "FTS_RAW",
            "candidate_limit": RAW_CAP,
        }
    )
    enriched_probe = baseline.probes[0].model_copy(
        update={
            "probe_id": f"dg28:{requirement_id}:fts_enriched",
            "channel": "FTS_ENRICHED",
            "candidate_limit": ENRICHED_CAP,
        }
    )
    material = baseline.model_dump(mode="python")
    material.update(
        {
            "probes": [
                raw_probe.model_dump(mode="python"),
                enriched_probe.model_dump(mode="python"),
            ],
            "fusion": {
                "policy_identity": "DG28_LITE_IDENTITY_DEDUP_RRF_K60",
                "rrf_k": 60,
                "per_slot_quota": {requirement_id: candidate_count},
                "global_cap": candidate_count,
            },
            "budget": {
                "latency_ms": baseline.budget.latency_ms,
                "candidate_count": candidate_count,
                "hydrate_count": candidate_count,
                "context_tokens": baseline.budget.context_tokens,
            },
        }
    )
    return AcquisitionPlan.model_validate(material)


def _decision_row(
    case_id: str,
    requirement_id: str,
    candidates: Sequence[CandidateEnvelope],
    decision: DecisionBoundaryResultV02,
) -> dict[str, Any]:
    source_by_id = {item.source_evidence_id: item.source_turn_ref for item in candidates}
    return {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "candidate_count": len(candidates),
        "candidate_sources": [item.source_turn_ref for item in candidates],
        "accepted_sources": [
            source_by_id[item.evidence_id] for item in decision.accepted_bindings
        ],
        "accepted_binding_count": len(decision.accepted_bindings),
        "requirement_status": next(
            item.status
            for item in decision.requirement_state.requirements
            if item.requirement_id == requirement_id
        ),
        "sufficiency": decision.sufficiency_decision.status,
        "operator_ready": decision.operator_ready,
        "decision_digest": canonical_sha256(decision.model_dump(mode="json")),
    }


def _valid_rank(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _arm_metrics(
    rows: Sequence[Mapping[str, Any]],
    groups: Mapping[tuple[str, str, str], set[str]],
    target_ids: set[str],
) -> dict[str, Any]:
    row_by_key = {
        (str(row["case_id"]), str(row["requirement_id"])): row for row in rows
    }
    candidate_group_ids: set[str] = set()
    binding_group_ids: set[str] = set()
    accepted_sources: set[tuple[str, str, str]] = set()
    for key, row in row_by_key.items():
        candidate_sources = {
            _compact_source_ref(str(value))
            for value in _sequence(row.get("candidate_sources"), "candidate sources")
        }
        binding_sources = {
            _compact_source_ref(str(value))
            for value in _sequence(row.get("accepted_sources"), "accepted sources")
        }
        accepted_sources.update((key[0], key[1], value) for value in binding_sources)
        for (case_id, requirement_id, group_id), refs in groups.items():
            if (case_id, requirement_id) != key:
                continue
            if candidate_sources & refs:
                candidate_group_ids.add(group_id)
            if binding_sources & refs:
                binding_group_ids.add(group_id)
    valid_sources = {
        (case_id, requirement_id, source)
        for (case_id, requirement_id, _group_id), refs in groups.items()
        for source in refs
    }
    valid_accepted = accepted_sources & valid_sources
    wrong_complete = 0
    for key, row in row_by_key.items():
        if row.get("sufficiency") != "COMPLETE" and row.get("operator_ready") is not True:
            continue
        required_group_ids = {
            group_id
            for case_id, requirement_id, group_id in groups
            if (case_id, requirement_id) == key
        }
        if not required_group_ids.issubset(binding_group_ids):
            wrong_complete += 1
    return {
        "candidate_count": sum(int(row["candidate_count"]) for row in rows),
        "accepted_source_count": len(accepted_sources),
        "valid_accepted_source_count": len(valid_accepted),
        "accepted_binding_precision": (
            len(valid_accepted) / len(accepted_sources) if accepted_sources else 1.0
        ),
        "candidate_group_ids": sorted(candidate_group_ids),
        "binding_group_ids": sorted(binding_group_ids),
        "target_candidate_group_ids": sorted(candidate_group_ids & target_ids),
        "target_binding_group_ids": sorted(binding_group_ids & target_ids),
        "target_candidate_groups": len(candidate_group_ids & target_ids),
        "target_binding_groups": len(binding_group_ids & target_ids),
        "all_candidate_groups": len(candidate_group_ids),
        "all_binding_groups": len(binding_group_ids),
        "wrong_complete": wrong_complete,
        "operator_ready_queries": sum(row.get("operator_ready") is True for row in rows),
    }


def _json_object(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG28LiteEffectError(f"DG28_LITE_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG28LiteEffectError(f"DG28_LITE_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG28LiteEffectError(f"DG28_LITE_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = [
    "CHANNEL_CAPS",
    "DG28LiteEffectError",
    "execute_lite_effect",
    "score_lite_effect",
    "select_lite_candidates",
]
