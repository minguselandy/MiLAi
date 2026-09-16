"""A6 matched Raw-Evidence dense productization evaluation.

The acquisition archive is built without answer-bearing labels.  Scoring is a
separate, after-the-fact operation over immutable source-turn identities.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Protocol, cast

import numpy as np
from milai.adapters import ProjectionIdentity, project_embedding_vector
from milai.application.acquisition import (
    apply_probe_source_policy,
    compile_acquisition_plan,
    fuse_acquisition_probe_results,
    probe_query,
)
from milai.application.evidence_dense import evidence_turn_embedding_text
from milai.application.query_planner import QueryPlanner
from milai.domain.acquisition import AcquisitionPlan, AcquisitionProbe
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.persistence.retrieval_repository import evidence_query_terms

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.q4 import build_units

A6_ARMS = ("FTS_RAW", "FTS_RAW_PLUS_EVIDENCE_DENSE_128")
CANDIDATE_CAP = 20
CONTEXT_TOKENS = 2_048
_FORBIDDEN_LABEL_KEYS = frozenset(
    {
        "answer",
        "answers",
        "answer_session_ids",
        "atoms",
        "gold_ir",
        "gold_operator",
        "join_relations",
        "required_slots",
        "scoring_labels",
    }
)


class A6DenseError(RuntimeError):
    """An A6 fixed control, projection, or denominator drifted."""


class DenseRetriever(Protocol):
    identity: dict[str, Any]

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...

    def metrics(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _PreparedCase:
    case_id: str
    question: str
    plan: QueryPlan
    turns: tuple[dict[str, Any], ...]
    corpus_digest: str


def estimate_a6_work(cases: Sequence[Any], *, candidate_cap: int = CANDIDATE_CAP) -> dict[str, Any]:
    """Compute the label-free execution denominator before any model call."""

    prepared = _prepare_cases(cases)
    dense_probe_count = 0
    event_filtered_probe_count = 0
    per_case: list[dict[str, Any]] = []
    for item in prepared:
        acquisition = _acquisition(item, dense=True, candidate_cap=candidate_cap)
        dense_probes = [probe for probe in acquisition.probes if probe.channel == "EVIDENCE_DENSE"]
        event_filtered = (
            len(dense_probes)
            if acquisition.global_constraints.event_occurrence_range is not None
            else 0
        )
        dense_probe_count += len(dense_probes) - event_filtered
        event_filtered_probe_count += event_filtered
        per_case.append(
            {
                "case_id": item.case_id,
                "turn_count": len(item.turns),
                "dense_probe_count": len(dense_probes),
                "executed_dense_probe_count": len(dense_probes) - event_filtered,
                "event_time_filtered_probe_count": event_filtered,
                "corpus_digest": item.corpus_digest,
            }
        )
    return {
        "case_count": len(prepared),
        "evidence_turn_count": sum(len(item.turns) for item in prepared),
        "executed_dense_probe_count": dense_probe_count,
        "event_time_filtered_probe_count": event_filtered_probe_count,
        "embedding_logical_item_ceiling": sum(len(item.turns) for item in prepared)
        + dense_probe_count,
        "per_case": per_case,
    }


def build_a6_label_free_archive(
    cases: Sequence[Any],
    *,
    dense: DenseRetriever,
    projection_identity: ProjectionIdentity,
    run_id: str,
    candidate_cap: int = CANDIDATE_CAP,
) -> dict[str, Any]:
    """Build both matched acquisition arms before labels become available."""

    if projection_identity.projection_dimensions != 128:
        raise A6DenseError("A6 product projection must be 128 dimensional")
    prepared = _prepare_cases(cases)
    if len(prepared) != 10:
        raise A6DenseError("A6 opened-development denominator must be ten cases")
    build_started = time.perf_counter()
    all_turns = [turn for item in prepared for turn in item.turns]
    embedding_inputs = [str(turn["embedding_text"]) for turn in all_turns]
    dense_before = dict(dense.metrics())
    corpus_call_started = time.perf_counter()
    source_matrix = dense.embed(embedding_inputs)
    corpus_call_wall_ms = (time.perf_counter() - corpus_call_started) * 1_000
    dense_after_corpus = dict(dense.metrics())
    _validate_source_matrix(
        source_matrix,
        rows=len(all_turns),
        dimensions=projection_identity.source_dimensions,
    )
    projection_started = time.perf_counter()
    projected_matrix = np.asarray(
        [
            project_embedding_vector(row.tolist(), projection_identity)
            for row in source_matrix
        ],
        dtype=np.float32,
    )
    corpus_projection_wall_ms = (time.perf_counter() - projection_started) * 1_000
    _validate_projected_matrix(projected_matrix, rows=len(all_turns))

    records: list[dict[str, Any]] = []
    cursor = 0
    query_projection_wall_ms = 0.0
    query_embedding_wall_ms = 0.0
    event_time_filtered_probe_count = 0
    for item in prepared:
        case_matrix = projected_matrix[cursor : cursor + len(item.turns)]
        cursor += len(item.turns)
        baseline = _acquisition(item, dense=False, candidate_cap=candidate_cap)
        candidate = _acquisition(item, dense=True, candidate_cap=candidate_cap)
        _assert_single_factor(baseline, candidate)

        baseline_started = time.perf_counter()
        baseline_probe_results = [
            (probe, _fts_candidates(probe, item.turns)) for probe in baseline.probes
        ]
        baseline_selected = fuse_acquisition_probe_results(
            baseline, baseline_probe_results
        )
        baseline_ms = (time.perf_counter() - baseline_started) * 1_000
        records.append(
            _trace_record(
                item,
                arm=A6_ARMS[0],
                acquisition=baseline,
                selected=baseline_selected,
                probe_dispositions=[
                    {
                        "probe_id": probe.probe_id,
                        "channel": probe.channel,
                        "status": "EXECUTED",
                        "candidate_count": len(results),
                        "candidate_limit": probe.candidate_limit,
                    }
                    for probe, results in baseline_probe_results
                ],
                latency_ms=baseline_ms,
            )
        )

        candidate_started = time.perf_counter()
        candidate_probe_results: list[
            tuple[AcquisitionProbe, Sequence[Mapping[str, Any]]]
        ] = []
        probe_dispositions: list[dict[str, Any]] = []
        for probe in candidate.probes:
            if probe.channel != "EVIDENCE_DENSE":
                results = _fts_candidates(probe, item.turns)
                status = "EXECUTED"
            elif candidate.global_constraints.event_occurrence_range is not None:
                results = []
                status = "EVENT_TIME_FILTER_UNAVAILABLE"
                event_time_filtered_probe_count += 1
            else:
                query_call_started = time.perf_counter()
                source_query = dense.embed([probe_query(probe)])
                query_embedding_wall_ms += (
                    time.perf_counter() - query_call_started
                ) * 1_000
                _validate_source_matrix(
                    source_query,
                    rows=1,
                    dimensions=projection_identity.source_dimensions,
                )
                query_projection_started = time.perf_counter()
                projected_query = np.asarray(
                    project_embedding_vector(
                        source_query[0].tolist(), projection_identity
                    ),
                    dtype=np.float32,
                )
                query_projection_wall_ms += (
                    time.perf_counter() - query_projection_started
                ) * 1_000
                dense_universe = _dense_universe(candidate, item.turns)
                universe_indices = [
                    int(turn["case_turn_index"]) for turn in dense_universe
                ]
                universe_matrix = case_matrix[universe_indices]
                scores = universe_matrix @ projected_query
                ranking = sorted(
                    range(len(dense_universe)),
                    key=lambda index: (
                        -float(scores[index]),
                        str(dense_universe[index]["source_ref"]),
                    ),
                )[: probe.candidate_limit]
                ranked: list[dict[str, Any]] = []
                for index in ranking:
                    row = _public_turn(dense_universe[index])
                    row["relevance_score"] = float(scores[index])
                    row["acquisition_channel"] = "EVIDENCE_DENSE"
                    ranked.append(row)
                results = apply_probe_source_policy(probe, ranked)
                status = "EXECUTED"
            candidate_probe_results.append((probe, results))
            probe_dispositions.append(
                {
                    "probe_id": probe.probe_id,
                    "channel": probe.channel,
                    "status": status,
                    "candidate_count": len(results),
                    "candidate_limit": probe.candidate_limit,
                }
            )
        candidate_selected = fuse_acquisition_probe_results(
            candidate, candidate_probe_results
        )
        candidate_ms = (time.perf_counter() - candidate_started) * 1_000
        records.append(
            _trace_record(
                item,
                arm=A6_ARMS[1],
                acquisition=candidate,
                selected=candidate_selected,
                probe_dispositions=probe_dispositions,
                latency_ms=candidate_ms,
            )
        )
    if cursor != len(all_turns):
        raise A6DenseError("A6 projected corpus cursor drifted")
    if contains_forbidden_label_key(records):
        raise A6DenseError("answer-bearing label leaked into A6 acquisition archive")
    dense_after_queries = dict(dense.metrics())
    archive = {
        "schema": "milai.dg17.a6-label-free-acquisition.v0.1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "label_fields_available_to_product_path": False,
        "historical_answer_reuse": False,
        "automatic_retries": 0,
        "arms": list(A6_ARMS),
        "record_count": len(records),
        "projection": {
            "identity": _projection_receipt(projection_identity),
            "embedding_input_identity": "evidence-turn-utf8-prefix-32768-v1",
            "full_turn_source_mutated": False,
            "turn_count": len(all_turns),
            "embedding_input_truncated_turn_count": sum(
                str(turn["embedding_text"]) != str(turn["content"])
                for turn in all_turns
            ),
        },
        "efficiency": {
            "build_wall_ms": round((time.perf_counter() - build_started) * 1_000, 6),
            "offline_corpus_embedding_wall_ms": round(corpus_call_wall_ms, 6),
            "offline_corpus_projection_wall_ms": round(corpus_projection_wall_ms, 6),
            "online_query_embedding_sequential_wall_ms": round(
                query_embedding_wall_ms, 6
            ),
            "online_query_projection_wall_ms": round(query_projection_wall_ms, 6),
            "dense_corpus_metrics": _numeric_metric_delta(
                dense_before, dense_after_corpus
            ),
            "dense_query_metrics": _numeric_metric_delta(
                dense_after_corpus, dense_after_queries
            ),
            "reranker_calls": 0,
        },
        "hard_filter_execution": {
            "scope": "IMMUTABLE_PER_CASE_TENANT_SCOPE; REAL_RLS_BOUND_SEPARATELY",
            "permission": "PUBLIC_FIXTURE_READABLE; REAL_PERMISSION_BOUND_SEPARATELY",
            "as_of_source_time": True,
            "source_observed_range": True,
            "event_occurrence_without_projection": "FAIL_CLOSED",
            "event_time_filtered_dense_probe_count": event_time_filtered_probe_count,
        },
        "records": records,
    }
    if len(records) != 20:
        raise A6DenseError("A6 matched record denominator drifted")
    return archive


def score_a6_archive(
    archive: Mapping[str, Any],
    *,
    labels: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply answer-bearing labels only after the acquisition archive is sealed."""

    raw_records = archive.get("records")
    if archive.get("labels_loaded") is not False or not isinstance(raw_records, list):
        raise A6DenseError("A6 label-free archive contract drifted")
    records = [cast(Mapping[str, Any], row) for row in raw_records]
    summaries = {
        arm: _score_arm(
            [row for row in records if row.get("arm") == arm], labels
        )
        for arm in A6_ARMS
    }
    baseline = summaries[A6_ARMS[0]]
    candidate = summaries[A6_ARMS[1]]
    regressions: dict[str, list[str]] = {}
    for case_id, baseline_case in baseline["case_metrics"].items():
        candidate_case = candidate["case_metrics"][case_id]
        lost = sorted(
            set(baseline_case["hit_source_refs"])
            - set(candidate_case["hit_source_refs"])
        )
        if lost:
            regressions[case_id] = lost
    atom_gain = int(candidate["answer_bearing_atom_hits"]) - int(
        baseline["answer_bearing_atom_hits"]
    )
    turn_gain = int(candidate["answer_bearing_source_turn_hits"]) - int(
        baseline["answer_bearing_source_turn_hits"]
    )
    ready_gain = int(candidate["operator_ready_cases"]) - int(
        baseline["operator_ready_cases"]
    )
    gates = {
        "required_evidence_atoms_at_least_9_of_23": int(
            candidate["answer_bearing_atom_hits"]
        )
        >= 9,
        "answer_bearing_turns_at_least_8_of_21": int(
            candidate["answer_bearing_source_turn_hits"]
        )
        >= 8,
        "positive_atom_mediator_gain": atom_gain > 0,
        "positive_turn_mediator_gain": turn_gain > 0,
        "positive_operator_ready_mediator_gain": ready_gain > 0,
        "baseline_gold_hits_retained": not regressions,
    }
    return {
        "schema": "milai.dg17.a6-matched-acquisition-score.v0.2",
        "status": "PASS" if all(gates.values()) else "CHARACTERIZED_PARTIAL",
        "arms": summaries,
        "delta": {
            "answer_bearing_atom_hits": atom_gain,
            "answer_bearing_source_turn_hits": turn_gain,
            "operator_ready_cases": ready_gain,
            "candidate_noise_count": int(candidate["candidate_noise_count"])
            - int(baseline["candidate_noise_count"]),
            "regressed_source_refs_by_case": regressions,
        },
        "gates": gates,
        "aggregate_gate_diagnostic": {
            "scope": "A1_THROUGH_A7_COMBINED;_NOT_AN_A6_SINGLE_FACTOR_GATE",
            "operator_ready_gain_required": 2,
            "a6_single_factor_observed_gain": ready_gain,
            "currently_satisfied_by_a6_alone": ready_gain >= 2,
        },
    }


def build_a6_receipt(
    *,
    run_id: str,
    archive_path: Path,
    execution_plan_path: Path,
    goal_path: Path,
    focused_postgres_receipt: Path,
    q8_receipt: Path,
    score: Mapping[str, Any],
    archive: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind product safety, matched quality, and the no-reranker decision."""

    focused = _load_object(focused_postgres_receipt)
    q8 = _load_object(q8_receipt)
    if focused.get("status") != "PASS":
        raise A6DenseError("A6 focused PostgreSQL gate did not pass")
    summaries = q8.get("summaries")
    if not isinstance(summaries, Mapping):
        raise A6DenseError("bound Q8 summary is unavailable")
    strong = cast(Mapping[str, Any], summaries.get("STRONG_DENSE"))
    reranker = cast(Mapping[str, Any], summaries.get("REAL_RERANKER"))
    hybrid = cast(Mapping[str, Any], summaries.get("HYBRID"))
    if not all(isinstance(value, Mapping) for value in (strong, reranker, hybrid)):
        raise A6DenseError("bound Q8 retrieval arms drifted")
    dense_pass = score.get("status") == "PASS"
    return {
        "schema": "milai.dg17.a6-dense-productization-decision.v0.1",
        "run_id": run_id,
        "status": "PASS" if dense_pass else "CHARACTERIZED_PARTIAL",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "formal_holdout_consumed": False,
        "bound_artifacts": {
            "goal": _identity(goal_path),
            "execution_plan": _identity(execution_plan_path),
            "label_free_acquisition_archive": _identity(archive_path),
            "focused_postgresql_gate": _identity(focused_postgres_receipt),
            "q8_authoritative_diagnostic": _identity(q8_receipt),
        },
        "product_path": {
            "primitive": "LOSSLESS_RAW_EVIDENCE_TURN",
            "projection": archive["projection"],
            "hard_filter_execution": archive["hard_filter_execution"],
            "fusion_policy": "RRF_K60_PER_SLOT_FTS_PLUS_EVIDENCE_DENSE_V1",
            "candidate_cap": CANDIDATE_CAP,
            "exact_or_current_state_dense_calls": 0,
            "reranker_candidate_pool_max": 0,
            "product_default_changed": False,
        },
        "matched_score": dict(score),
        "efficiency": archive["efficiency"],
        "disposition": {
            "raw_evidence_dense": (
                "ELIGIBLE_FOR_A7_SINGLE_FACTOR_LANE"
                if dense_pass
                else "PARKED_NO_SAFE_MATCHED_MEDIATOR_GAIN"
            ),
            "conditional_reranker": (
                "PARKED_NO_INCREMENTAL_Q8_GAIN_AND_NO_REQUIREMENT_AWARE_RECEIPT"
            ),
            "next_lane_may_enable_dense": dense_pass,
            "product_default_changed": False,
        },
        "reranker_decision_evidence": {
            "new_a6_reranker_calls": 0,
            "q8_strong_dense_coverage": strong.get("required_evidence_set_coverage"),
            "q8_real_reranker_coverage": reranker.get(
                "required_evidence_set_coverage"
            ),
            "q8_hybrid_coverage": hybrid.get("required_evidence_set_coverage"),
            "q8_strong_dense_retrieval_latency_ms": strong.get(
                "retrieval_latency_ms"
            ),
            "q8_real_reranker_retrieval_latency_ms": reranker.get(
                "retrieval_latency_ms"
            ),
            "claim": "NO_PRODUCT_RERANKER_ROLLOUT",
        },
        "gates": {
            **cast(Mapping[str, Any], score["gates"]),
            "real_postgresql_channel_pass": True,
            "lossless_full_turn_source": archive["projection"][
                "full_turn_source_mutated"
            ]
            is False,
            "event_time_without_projection_fails_closed": archive[
                "hard_filter_execution"
            ]["event_occurrence_without_projection"]
            == "FAIL_CLOSED",
            "reranker_calls_zero": archive["efficiency"]["reranker_calls"] == 0,
            "automatic_retries_zero": archive["automatic_retries"] == 0,
        },
        "label_boundary": {
            "label_free_archive_written_before_scoring": True,
            "product_path_label_access_count": 0,
            "labels_used_only_for_after_the_fact_source_identity_scoring": True,
            "reader_calls": 0,
            "historical_answer_reuse": 0,
        },
        "claim_boundary": {
            "a6_is_acquisition_mediator_only": True,
            "a1_through_a7_aggregate_operator_ready_gate_closed": False,
            "reader_quality_claim_authorized": False,
            "final_lme_authorized": False,
            "release_claim_authorized": False,
        },
    }


def contains_forbidden_label_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in _FORBIDDEN_LABEL_KEYS
            or contains_forbidden_label_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return any(contains_forbidden_label_key(item) for item in value)
    return False


def _prepare_cases(cases: Sequence[Any]) -> tuple[_PreparedCase, ...]:
    planner = QueryPlanner()
    prepared: list[_PreparedCase] = []
    case_ids: set[str] = set()
    for case in cases:
        case_id = str(case.case_id)
        if case_id in case_ids:
            raise A6DenseError("A6 case identity is duplicated")
        case_ids.add(case_id)
        as_of = _timestamp(str(case.question_at))
        plan = planner.plan(
            RetrievalRequest(
                route="L1",
                query=str(case.question),
                as_of=as_of,
                system_as_of=as_of,
            )
        )
        units = build_units(case, "TURN")
        speakers: dict[str, str] = {}
        for session_ordinal, session in enumerate(case.sessions):
            for turn_ordinal, turn in enumerate(session.turns):
                source_ref = (
                    f"{case_id}:s{session_ordinal}:{session.session_id}:t{turn_ordinal}"
                )
                speakers[source_ref] = str(turn.role)
        turns: list[dict[str, Any]] = []
        for index, unit in enumerate(units):
            if len(unit.turn_refs) != 1:
                raise A6DenseError("A6 TURN unit is not reconstructible")
            source_ref = unit.turn_refs[0]
            observed_at = _timestamp(unit.observed_at)
            if observed_at > as_of:
                continue
            content = unit.content
            turns.append(
                {
                    "evidence_id": hashlib.sha256(source_ref.encode()).hexdigest()[:24],
                    "source_ref": source_ref,
                    "subject_id": unit.session_id,
                    "observed_at": unit.observed_at,
                    "content": content,
                    "speaker": speakers[source_ref],
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                    "embedding_text": evidence_turn_embedding_text(unit.index_text),
                    "tokens": frozenset(evidence_query_terms(unit.index_text)),
                        "case_turn_index": len(turns),
                    }
                )
        if not turns:
            raise A6DenseError("A6 case has no as-of-eligible Evidence turns")
        digest = _canonical_sha256(
            [
                {
                    "source_ref": turn["source_ref"],
                    "content_sha256": hashlib.sha256(
                        str(turn["content"]).encode()
                    ).hexdigest(),
                    "observed_at": turn["observed_at"],
                    "speaker": turn["speaker"],
                }
                for turn in turns
            ]
        )
        prepared.append(
            _PreparedCase(
                case_id=case_id,
                question=str(case.question),
                plan=plan,
                turns=tuple(turns),
                corpus_digest=digest,
            )
        )
    return tuple(prepared)


def _acquisition(
    item: _PreparedCase, *, dense: bool, candidate_cap: int
) -> AcquisitionPlan:
    return compile_acquisition_plan(
        item.plan,
        query=item.question,
        principal_scope={"fixture_case_id": item.case_id},
        authority_floor="INFORMATIONAL",
        candidate_limit=candidate_cap,
        context_tokens=CONTEXT_TOKENS,
        enable_dense=dense,
    )


def _assert_single_factor(baseline: AcquisitionPlan, candidate: AcquisitionPlan) -> None:
    baseline_fts = [
        probe.model_dump(mode="json")
        for probe in baseline.probes
        if probe.channel != "EVIDENCE_DENSE"
    ]
    candidate_fts = [
        probe.model_dump(mode="json")
        for probe in candidate.probes
        if probe.channel != "EVIDENCE_DENSE"
    ]
    if baseline_fts != candidate_fts:
        raise A6DenseError("A6 candidate changed the baseline FTS probes or budgets")
    if candidate.fusion.global_cap != baseline.fusion.global_cap:
        raise A6DenseError("A6 candidate changed the matched candidate cap")


def _fts_candidates(
    probe: AcquisitionProbe, turns: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    query_terms = set(evidence_query_terms(probe_query(probe)))
    ranked: list[dict[str, Any]] = []
    for turn in turns:
        tokens = cast(frozenset[str], turn["tokens"])
        overlap = len(query_terms.intersection(tokens))
        if overlap == 0:
            continue
        candidate = _public_turn(turn)
        candidate["relevance_score"] = overlap / max(1, len(query_terms))
        candidate["acquisition_channel"] = probe.channel
        ranked.append(candidate)
    ranked.sort(
        key=lambda row: (-float(row["relevance_score"]), str(row["source_ref"]))
    )
    return apply_probe_source_policy(probe, ranked[: probe.candidate_limit])


def _dense_universe(
    acquisition: AcquisitionPlan, turns: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    source_range = acquisition.global_constraints.source_observed_range
    if source_range is None:
        return list(turns)
    start = source_range.get("start") or source_range.get("range_start")
    end = source_range.get("end") or source_range.get("range_end")
    start_at = _timestamp(str(start)) if isinstance(start, str) else None
    end_at = _timestamp(str(end)) if isinstance(end, str) else None
    return [
        turn
        for turn in turns
        if (start_at is None or _timestamp(str(turn["observed_at"])) >= start_at)
        and (end_at is None or _timestamp(str(turn["observed_at"])) <= end_at)
    ]


def _public_turn(turn: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in turn.items()
        if key not in {"embedding_text", "tokens", "case_turn_index"}
    }


def _trace_record(
    item: _PreparedCase,
    *,
    arm: str,
    acquisition: AcquisitionPlan,
    selected: Sequence[Mapping[str, Any]],
    probe_dispositions: Sequence[Mapping[str, Any]],
    latency_ms: float,
) -> dict[str, Any]:
    # The identity lookup proves selected bodies are the original full turns;
    # fusion rank is deliberately not used as a corpus index.
    source_contents = {
        str(turn["source_ref"]): str(turn["content"]) for turn in item.turns
    }
    lossless = all(
        isinstance(row.get("content"), str)
        and str(row["content"]) == source_contents.get(str(row["source_ref"]))
        for row in selected
    )
    if not lossless:
        raise A6DenseError("A6 fusion mutated or failed to hydrate a full Evidence turn")
    return {
        "case_id": item.case_id,
        "arm": arm,
        "question_sha256": hashlib.sha256(item.question.encode()).hexdigest(),
        "query_plan_digest": _canonical_sha256(item.plan.model_dump(mode="json")),
        "acquisition_plan_digest": _canonical_sha256(
            acquisition.model_dump(mode="json")
        ),
        "corpus_digest": item.corpus_digest,
        "source_turn_count": len(item.turns),
        "candidate_cap": acquisition.fusion.global_cap,
        "candidate_count": len(selected),
        "selected_source_refs": [str(row["source_ref"]) for row in selected],
        "selected": [
            {
                "source_ref": str(row["source_ref"]),
                "content_sha256": hashlib.sha256(str(row["content"]).encode()).hexdigest(),
                "content_utf8_bytes": len(str(row["content"]).encode()),
                "speaker": row.get("speaker"),
                "speaker_source": row.get("speaker_source"),
                "matched_slots": row["acquisition_candidate"]["matched_slots"],
                "matched_probes": row["acquisition_candidate"]["matched_probes"],
                "channel_ranks": row["acquisition_candidate"]["channel_ranks"],
                "matched_fields": row["acquisition_candidate"]["matched_fields"],
            }
            for row in selected
        ],
        "probe_dispositions": [dict(value) for value in probe_dispositions],
        "lossless_selected_turns": lossless,
        "acquisition_latency_ms": round(latency_ms, 6),
    }


def _score_arm(
    records: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if len(records) != 10:
        raise A6DenseError("A6 arm denominator drifted")
    atom_hits = atom_total = turn_hits = turn_total = ready = noise = selected_total = 0
    latencies: list[float] = []
    case_metrics: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = str(record["case_id"])
        label = labels.get(case_id)
        if not isinstance(label, Mapping):
            raise A6DenseError("A6 case label is missing")
        atoms = label.get("atoms")
        if not isinstance(atoms, list):
            raise A6DenseError("A6 atom labels drifted")
        selected = {str(value) for value in cast(list[Any], record["selected_source_refs"])}
        required_turns = {str(atom["source_turn_ref"]) for atom in atoms}
        hit_turns = selected.intersection(required_turns)
        case_atom_hits = sum(
            str(atom["source_turn_ref"]) in selected for atom in atoms
        )
        case_ready = required_turns.issubset(selected)
        atom_hits += case_atom_hits
        atom_total += len(atoms)
        turn_hits += len(hit_turns)
        turn_total += len(required_turns)
        ready += case_ready
        noise += len(selected - required_turns)
        selected_total += len(selected)
        latencies.append(float(record["acquisition_latency_ms"]))
        case_metrics[case_id] = {
            "atom_hits": case_atom_hits,
            "atom_denominator": len(atoms),
            "source_turn_hits": len(hit_turns),
            "source_turn_denominator": len(required_turns),
            "hit_source_refs": sorted(hit_turns),
            "operator_ready": case_ready,
            "candidate_count": len(selected),
        }
    if atom_total != 23 or turn_total != 21:
        raise A6DenseError("A6 answer-bearing denominator drifted")
    return {
        "case_count": 10,
        "answer_bearing_atom_hits": atom_hits,
        "answer_bearing_atom_denominator": atom_total,
        "answer_bearing_atom_recall": round(atom_hits / atom_total, 9),
        "answer_bearing_source_turn_hits": turn_hits,
        "answer_bearing_source_turn_denominator": turn_total,
        "answer_bearing_source_turn_recall": round(turn_hits / turn_total, 9),
        "operator_ready_cases": ready,
        "operator_ready_denominator": 10,
        "candidate_noise_count": noise,
        "selected_candidate_count": selected_total,
        "candidate_noise_rate": round(noise / selected_total, 9),
        "acquisition_latency_ms": _distribution(latencies),
        "case_metrics": case_metrics,
    }


def _validate_source_matrix(matrix: np.ndarray, *, rows: int, dimensions: int) -> None:
    if matrix.shape != (rows, dimensions) or not np.isfinite(matrix).all():
        raise A6DenseError("A6 source embedding matrix shape or values drifted")


def _validate_projected_matrix(matrix: np.ndarray, *, rows: int) -> None:
    if matrix.shape != (rows, 128) or not np.isfinite(matrix).all():
        raise A6DenseError("A6 projected embedding matrix shape or values drifted")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(np.abs(norms - 1.0) > 1e-4):
        raise A6DenseError("A6 projected embedding normalization drifted")


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(normalize_lme_timestamp(value).replace("Z", "+00:00"))


def _projection_receipt(identity: ProjectionIdentity) -> dict[str, Any]:
    return {
        "provider": identity.provider,
        "model_id": identity.model_id,
        "source_dimensions": identity.source_dimensions,
        "projection_dimensions": identity.projection_dimensions,
        "normalization": identity.normalization,
        "code_version": identity.code_version,
        "identity_key": identity.key,
    }


def _numeric_metric_delta(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for key, value in after.items():
        previous = before.get(key, 0)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isinstance(previous, (int, float))
            and not isinstance(previous, bool)
        ):
            result[key] = value - previous
    return result


def _distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise A6DenseError("cannot summarize empty A6 latency")
    return {
        "mean": round(mean(values), 6),
        "p50": round(median(values), 6),
        "p95": round(_percentile(values, 0.95), 6),
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise A6DenseError(f"A6 bound artifact is not an object: {path}")
    return value


__all__ = [
    "A6_ARMS",
    "CANDIDATE_CAP",
    "A6DenseError",
    "DenseRetriever",
    "build_a6_label_free_archive",
    "build_a6_receipt",
    "contains_forbidden_label_key",
    "estimate_a6_work",
    "score_a6_archive",
]
