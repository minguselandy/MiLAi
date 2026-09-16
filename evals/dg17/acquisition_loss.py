"""DG-17 A0 after-the-fact acquisition loss attribution.

The module deliberately separates label-free candidate/semantic replay from
gold-label attribution.  It is evaluation-plane code and is never imported by
the Runtime product path.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import numpy as np
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.domain.retrieval import QueryPlan

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg16.q4 import EvidenceUnit, build_units
from evals.dg17.q8_retrieval_ablation import (
    CANDIDATE_CAP,
    RETRIEVAL_METHODS,
    RRF_K,
    TOKEN_BUDGET,
    TYPED_REFERENCE,
    _expand_neighbors,
    _fit_ranked_units,
    _rank_desc,
    _resolve_rerank,
    _rrf,
    contains_forbidden_label_key,
    retrieval_query,
)
from evals.paper.adapters.baselines import _bm25_scores

Q6_CURRENT = "Q6_DETERMINISTIC_ONLY_2048"
PATHS = (Q6_CURRENT, *RETRIEVAL_METHODS, TYPED_REFERENCE)
LOSS_STAGES = frozenset(
    {
        "TERM_GENERATION",
        "CHANNEL_SELECTION",
        "LEXICAL_MATCH",
        "DENSE_MATCH",
        "TEMPORAL_FILTER",
        "ROLE_FILTER",
        "RANKING",
        "SESSION_CUTOFF",
        "FUSION",
        "EXPANSION",
        "PACKING",
        "INTERPRETATION",
        "BINDING",
        "NOT_LOST",
    }
)


class AcquisitionLossError(RuntimeError):
    """An A0 identity, label boundary, or denominator drifted."""


class DenseRetriever(Protocol):
    identity: dict[str, Any]

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...

    def metrics(self) -> Mapping[str, Any]: ...


class Reranker(Protocol):
    identity: dict[str, Any]

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[tuple[int, float]]: ...

    def metrics(self) -> Mapping[str, Any]: ...


TokenCounter = Callable[[str], int]
IndexTextProjector = Callable[[str], str]


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def build_label_free_trace(
    cases: Sequence[Any],
    *,
    plans: Mapping[str, QueryPlan],
    q6_receipt: Mapping[str, Any],
    dense: DenseRetriever,
    reranker: Reranker,
    token_count: TokenCounter,
    index_text_projector: IndexTextProjector,
    expected_q8_contexts: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replay all acquisition stages without loading answer-bearing labels."""

    case_ids = [str(case.case_id) for case in cases]
    if len(case_ids) != 10 or len(set(case_ids)) != 10 or set(plans) != set(case_ids):
        raise AcquisitionLossError("A0 case/plan denominator drifted")
    q6 = _q6_records(q6_receipt, case_ids=case_ids)
    expected_q8 = (
        _q8_context_records(expected_q8_contexts, case_ids=case_ids)
        if expected_q8_contexts is not None
        else None
    )
    dense_before = dict(dense.metrics())
    reranker_before = dict(reranker.metrics())
    trace_cases: list[dict[str, Any]] = []
    q8_replay_match: dict[str, bool] = {}

    for case in cases:
        case_id = str(case.case_id)
        plan = plans[case_id]
        if plan.memory_query_ir is None:
            raise AcquisitionLossError(f"A0 case {case_id} lacks MemoryQueryIR")
        units = list(build_units(case, "TURN"))
        if not units:
            raise AcquisitionLossError(f"A0 case {case_id} has no TURN units")
        unit_index = {_turn_ref(unit): index for index, unit in enumerate(units)}
        if len(unit_index) != len(units):
            raise AcquisitionLossError("A0 TURN identity is not unique")
        query = retrieval_query(plan, str(case.question))
        index_texts = [index_text_projector(unit.index_text) for unit in units]
        if any(not value for value in index_texts):
            raise AcquisitionLossError("A0 index projection produced empty text")

        corpus_vectors = dense.embed(index_texts)
        query_vector = dense.embed([query])[0]
        if corpus_vectors.shape[0] != len(units):
            raise AcquisitionLossError("A0 dense corpus cardinality drifted")
        bm25_scores = _bm25_scores(
            [value.split(" ") for value in index_texts], query.split(" ")
        )
        dense_scores = corpus_vectors @ query_vector
        bm25_rank = _rank_desc(bm25_scores)
        dense_rank = _rank_desc(dense_scores.tolist())
        rrf_rank = _rrf(bm25_rank, dense_rank)
        neighbor_rank = _expand_neighbors(units, bm25_rank[:CANDIDATE_CAP])
        bm25_candidates = bm25_rank[:CANDIDATE_CAP]
        reranked, _reranker_scores = _resolve_rerank(
            bm25_candidates,
            reranker.rerank(
                query,
                [index_texts[index] for index in bm25_candidates],
                top_n=len(bm25_candidates),
            ),
        )
        hybrid_candidates = rrf_rank[:CANDIDATE_CAP]
        hybrid_rank, _hybrid_scores = _resolve_rerank(
            hybrid_candidates,
            reranker.rerank(
                query,
                [index_texts[index] for index in hybrid_candidates],
                top_n=len(hybrid_candidates),
            ),
        )
        rankings = {
            "TURN_BM25": bm25_rank,
            "TURN_BM25_NEIGHBOR": neighbor_rank,
            "STRONG_DENSE": dense_rank,
            "REAL_RERANKER": reranked,
            "HYBRID": hybrid_rank,
        }
        selected_by_path: dict[str, list[str]] = {}
        candidate_by_path: dict[str, list[str]] = {}
        for path, ranking in rankings.items():
            cutoff = (
                ranking
                if path == "TURN_BM25_NEIGHBOR"
                else ranking[:CANDIDATE_CAP]
            )
            candidate_by_path[path] = [_turn_ref(units[index]) for index in cutoff]
            selected, _context = _fit_ranked_units(
                units, cutoff, budget=TOKEN_BUDGET, token_count=token_count
            )
            selected_by_path[path] = [_turn_ref(unit) for unit in selected]
            if expected_q8 is not None:
                expected = expected_q8[(case_id, path)]
                matched = selected_by_path[path] == expected
                q8_replay_match[f"{case_id}:{path}"] = matched
                if not matched:
                    raise AcquisitionLossError(
                        f"A0 Q8 selected-source replay drifted: {case_id}/{path}"
                    )

        q6_selected = [
            compact_lme_source_ref(str(value))
            for value in q6[case_id]["selected_source_refs"]
        ]
        if any(value not in unit_index for value in q6_selected):
            raise AcquisitionLossError("A0 Q6 selected source left frozen cases")
        selected_by_path[Q6_CURRENT] = q6_selected
        candidate_by_path[Q6_CURRENT] = q6_selected
        typed_selected = (
            expected_q8[(case_id, TYPED_REFERENCE)]
            if expected_q8 is not None
            else q6_selected
        )
        if any(value not in unit_index for value in typed_selected):
            raise AcquisitionLossError("A0 typed source left frozen cases")
        selected_by_path[TYPED_REFERENCE] = typed_selected
        candidate_by_path[TYPED_REFERENCE] = typed_selected

        semantic_by_path = {
            path: _semantic_trace(
                case,
                selected_refs=selected_by_path[path],
                plan=plan,
            )
            for path in PATHS
        }
        ranks_by_ref: list[dict[str, Any]] = []
        bm25_positions = _positions(bm25_rank)
        dense_positions = _positions(dense_rank)
        rrf_positions = _positions(rrf_rank)
        path_positions = {
            path: _positions(ranking) for path, ranking in rankings.items()
        }
        for index, unit in enumerate(units):
            ref = _turn_ref(unit)
            turn = case.sessions[unit.session_ordinal].turns[
                int(unit.unit_id.rsplit(":", 1)[1])
            ]
            ranks_by_ref.append(
                {
                    "source_turn_ref": ref,
                    "session_id": unit.session_id,
                    "session_ordinal": unit.session_ordinal,
                    "turn_ordinal": int(unit.unit_id.rsplit(":", 1)[1]),
                    "speaker": str(turn.role),
                    "raw_fts_rank": bm25_positions[index],
                    "raw_fts_score": round(float(bm25_scores[index]), 12),
                    "dense_rank": dense_positions[index],
                    "dense_score": round(float(dense_scores[index]), 12),
                    "rrf_rank": rrf_positions[index],
                    "path_ranks": {
                        path: positions.get(index)
                        for path, positions in path_positions.items()
                    },
                    "candidate_paths": [
                        path
                        for path in PATHS
                        if ref in candidate_by_path[path]
                    ],
                    "packed_paths": [
                        path for path in PATHS if ref in selected_by_path[path]
                    ],
                }
            )
        trace_cases.append(
            {
                "case_id": case_id,
                "query": str(case.question),
                "retrieval_query": query,
                "query_terms_generated": query.split(),
                "operator": plan.operator,
                "temporal_semantics_declared": str(plan.operator).startswith(
                    "TEMPORAL"
                ),
                "memory_query_ir_digest": canonical_sha256(
                    plan.memory_query_ir.model_dump(mode="json")
                ),
                "requirements": [
                    requirement.model_dump(mode="json")
                    for requirement in plan.memory_query_ir.requirements
                ],
                "candidate_cap": CANDIDATE_CAP,
                "rrf_k": RRF_K,
                "turn_count": len(units),
                "turns": ranks_by_ref,
                "selected_by_path": selected_by_path,
                "candidate_by_path": candidate_by_path,
                "semantic_by_path": semantic_by_path,
                "q6_sufficiency": q6[case_id]["sufficiency_decision"],
            }
        )

    archive = {
        "schema": "milai.dg17.a0-label-free-acquisition-trace.v0.1",
        "status": "SEALED_BEFORE_GOLD_ATTRIBUTION",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "labels_loaded": False,
        "label_fields_available_to_product_path": False,
        "product_path_label_access_count": 0,
        "formal_holdout_consumed": False,
        "reader_calls": 0,
        "automatic_retries": 0,
        "paths": list(PATHS),
        "case_count": len(trace_cases),
        "cases": trace_cases,
    }
    if contains_forbidden_label_key(archive):
        raise AcquisitionLossError("A0 gold field leaked into label-free trace")
    metrics = {
        "dense": _numeric_delta(dense_before, dict(dense.metrics())),
        "reranker": _numeric_delta(reranker_before, dict(reranker.metrics())),
        "q8_replay_cells": len(q8_replay_match),
        "q8_replay_match_count": sum(q8_replay_match.values()),
        "q8_replay_identity_equal": (
            all(q8_replay_match.values()) if q8_replay_match else None
        ),
    }
    return archive, metrics


def attribute_acquisition_losses(
    trace_archive: Mapping[str, Any],
    *,
    labels: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join gold spans only after the label-free trace is sealed."""

    if (
        trace_archive.get("status") != "SEALED_BEFORE_GOLD_ATTRIBUTION"
        or trace_archive.get("labels_loaded") is not False
        or trace_archive.get("product_path_label_access_count") != 0
    ):
        raise AcquisitionLossError("A0 trace was not sealed label-free")
    raw_cases = trace_archive.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 10 or len(labels) != 10:
        raise AcquisitionLossError("A0 scoring case denominator drifted")
    trace_cases = {str(row["case_id"]): row for row in raw_cases}
    if set(trace_cases) != set(labels):
        raise AcquisitionLossError("A0 trace/label case identity drifted")

    records: list[dict[str, Any]] = []
    unique_atoms: set[str] = set()
    for case_id, label in labels.items():
        trace = trace_cases[case_id]
        turns = {
            str(row["source_turn_ref"]): row for row in trace["turns"]
        }
        atoms = label.get("atoms")
        if not isinstance(atoms, list):
            raise AcquisitionLossError("A0 label atoms are malformed")
        for atom in atoms:
            atom_id = str(atom["atom_id"])
            source_ref = str(atom["source_turn_ref"])
            if atom_id in unique_atoms or source_ref not in turns:
                raise AcquisitionLossError("A0 atom identity left frozen trace")
            unique_atoms.add(atom_id)
            turn = turns[source_ref]
            for path in PATHS:
                semantic = trace["semantic_by_path"][path]
                interpretation, binding, runtime_requirement_ids = _semantic_outcome(
                    semantic,
                    source_ref=source_ref,
                    span_text=str(atom["span"]["text"]),
                    required_kinds={
                        str(requirement["interpretation_kind"])
                        for requirement in trace["requirements"]
                    },
                )
                candidate = path in turn["candidate_paths"]
                packed = path in turn["packed_paths"]
                raw_rank = int(turn["raw_fts_rank"])
                dense_rank = int(turn["dense_rank"])
                path_rank = turn["path_ranks"].get(path)
                recovered = (
                    path == "TURN_BM25_NEIGHBOR"
                    and raw_rank > CANDIDATE_CAP
                    and candidate
                )
                first_loss = _first_loss_stage(
                    path,
                    candidate=candidate,
                    packed=packed,
                    raw_rank=raw_rank,
                    raw_score=float(turn["raw_fts_score"]),
                    dense_rank=dense_rank,
                    path_rank=(int(path_rank) if path_rank is not None else None),
                    interpretation_created=interpretation,
                    binding_created=binding,
                )
                if first_loss not in LOSS_STAGES:
                    raise AcquisitionLossError("A0 first-loss taxonomy drifted")
                records.append(
                    {
                        "schema_version": "acquisition-loss-record-v0.1",
                        "case_id": case_id,
                        "acquisition_path": path,
                        "atom_id": atom_id,
                        "requirement_slot": str(atom["slot"]),
                        "gold_session_id": str(atom["session_id"]),
                        "gold_turn_id": source_ref,
                        "gold_span": dict(atom["span"]),
                        "query_terms_generated": list(
                            trace["query_terms_generated"]
                        ),
                        "lexical_match_possible": float(
                            turn["raw_fts_score"]
                        )
                        > 0,
                        "temporal_filter_included": (
                            _q6_temporal_filter(trace)
                            if path in {Q6_CURRENT, TYPED_REFERENCE}
                            else False
                        ),
                        "role_filter": "NONE",
                        "raw_fts_rank": raw_rank,
                        "enriched_fts_rank": None,
                        "dense_rank": dense_rank,
                        "temporal_rank": None,
                        "rank_after_fusion": (
                            int(path_rank) if path_rank is not None else None
                        ),
                        "survived_candidate_cutoff": candidate,
                        "survived_session_grouping": (
                            candidate
                            if path in {Q6_CURRENT, TYPED_REFERENCE}
                            else True
                        ),
                        "recovered_by_expansion": recovered,
                        "retained_by_context_packing": packed,
                        "interpretation_created": interpretation,
                        "binding_created": binding,
                        "runtime_binding_requirement_ids": runtime_requirement_ids,
                        "sufficiency_effect": (
                            "MATCH_BINDING_CREATED"
                            if binding
                            else (
                                "NO_MATCH_BINDING"
                                if interpretation
                                else "NOT_REACHED"
                            )
                        ),
                        "first_loss_stage": first_loss,
                    }
                )
    expected_records = 23 * len(PATHS)
    if len(unique_atoms) != 23 or len(records) != expected_records:
        raise AcquisitionLossError("A0 23-atom/path denominator drifted")
    summaries = _summaries(records)
    return records, {
        "unique_case_count": 10,
        "unique_required_evidence_count": len(unique_atoms),
        "record_count": len(records),
        "path_count": len(PATHS),
        "paths": summaries,
        "first_loss_stage_counts": dict(
            sorted(Counter(row["first_loss_stage"] for row in records).items())
        ),
        "all_records_have_exactly_one_first_loss": all(
            row["first_loss_stage"] in LOSS_STAGES for row in records
        ),
        "gold_label_product_path_access_count": 0,
    }


def _q6_records(
    receipt: Mapping[str, Any], *, case_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if (
        receipt.get("schema")
        != "milai.dg17.q6-sealed-same-snapshot-confirmation.v0.2"
    ):
        raise AcquisitionLossError("A0 Q6 receipt schema drifted")
    raw = receipt.get("records")
    if not isinstance(raw, list):
        raise AcquisitionLossError("A0 Q6 records are missing")
    result: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        if (
            row.get("policy") == "DG17_QUERY_SPECIFIC_STOP"
            and row.get("token_budget") == TOKEN_BUDGET
            and str(row.get("case_id")) in case_ids
        ):
            selected = row.get("selected_source_refs")
            sufficiency = row.get("sufficiency_decision")
            if not isinstance(selected, list) or not isinstance(sufficiency, Mapping):
                raise AcquisitionLossError("A0 Q6 trace is malformed")
            result[str(row["case_id"])] = {
                "selected_source_refs": [str(value) for value in selected],
                "sufficiency_decision": dict(sufficiency),
            }
    if set(result) != set(case_ids):
        raise AcquisitionLossError("A0 Q6 denominator drifted")
    return result


def _q8_context_records(
    archive: Mapping[str, Any], *, case_ids: Sequence[str]
) -> dict[tuple[str, str], list[str]]:
    if (
        archive.get("schema") != "milai.dg17.q8-label-free-contexts.v0.1"
        or archive.get("labels_loaded") is not False
        or archive.get("label_fields_available_to_retrieval_path") is not False
    ):
        raise AcquisitionLossError("A0 Q8 context archive is not label-free")
    rows = archive.get("records")
    if not isinstance(rows, list):
        raise AcquisitionLossError("A0 Q8 contexts are missing")
    result: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise AcquisitionLossError("A0 Q8 context row is malformed")
        key = (str(row.get("case_id")), str(row.get("method")))
        refs = row.get("selected_turn_refs")
        if not isinstance(refs, list):
            raise AcquisitionLossError("A0 Q8 selected refs are malformed")
        result[key] = [str(value) for value in refs]
    expected = {
        (case_id, path)
        for case_id in case_ids
        for path in (*RETRIEVAL_METHODS, TYPED_REFERENCE)
    }
    if set(result) != expected:
        raise AcquisitionLossError("A0 Q8 context denominator drifted")
    return result


def _semantic_trace(
    case: Any, *, selected_refs: Sequence[str], plan: QueryPlan
) -> dict[str, Any]:
    evidence = _evidence_items(case, selected_refs)
    spans = project_evidence_spans(evidence)
    interpretations = interpret_evidence_spans(spans)
    assert plan.memory_query_ir is not None
    bindings = bind_requirements(
        plan.memory_query_ir.requirements, interpretations, spans
    )
    return {
        "spans": [span.model_dump(mode="json") for span in spans],
        "interpretations": [
            interpretation.model_dump(mode="json")
            for interpretation in interpretations
        ],
        "bindings": [binding.model_dump(mode="json") for binding in bindings],
    }


def _evidence_items(case: Any, selected_refs: Sequence[str]) -> list[dict[str, Any]]:
    by_ref: dict[str, dict[str, Any]] = {}
    for session_ordinal, session in enumerate(case.sessions):
        for turn_ordinal, turn in enumerate(session.turns):
            ref = (
                f"{case.case_id}:s{session_ordinal}:"
                f"{session.session_id}:t{turn_ordinal}"
            )
            observed_at = normalize_lme_timestamp(str(session.observed_at))
            by_ref[ref] = {
                "evidence_id": hashlib.sha256(ref.encode()).hexdigest(),
                "source_ref": ref,
                "session_id": str(session.session_id),
                "content": f"{turn.role}: {turn.content}",
                "observed_at": observed_at,
                "captured_at": observed_at,
                "revoked": False,
                "denied": False,
                "retained": True,
            }
    try:
        return [by_ref[value] for value in selected_refs]
    except KeyError as exc:
        raise AcquisitionLossError("A0 selected Evidence left frozen case") from exc


def _semantic_outcome(
    semantic: Mapping[str, Any],
    *,
    source_ref: str,
    span_text: str,
    required_kinds: set[str],
) -> tuple[bool, bool, list[str]]:
    spans = semantic.get("spans")
    interpretations = semantic.get("interpretations")
    bindings = semantic.get("bindings")
    if not isinstance(spans, list) or not isinstance(interpretations, list) or not isinstance(bindings, list):
        raise AcquisitionLossError("A0 semantic trace is malformed")
    expected = _normalized(span_text)
    matching_span_ids = {
        str(span["span_id"])
        for span in spans
        if isinstance(span, Mapping)
        and str(span.get("source_turn_ref")) == source_ref
        and expected in _normalized(str(span.get("text", "")))
    }
    matching_interpretation_ids = {
        str(item["interpretation_id"])
        for item in interpretations
        if isinstance(item, Mapping)
        and str(item.get("span_id")) in matching_span_ids
        and str(item.get("kind")) in required_kinds
    }
    matched_requirements = sorted(
        {
            str(binding["requirement_id"])
            for binding in bindings
            if isinstance(binding, Mapping)
            and str(binding.get("interpretation_id"))
            in matching_interpretation_ids
            and binding.get("status") == "MATCH"
        }
    )
    return (
        bool(matching_interpretation_ids),
        bool(matched_requirements),
        matched_requirements,
    )


def _first_loss_stage(
    path: str,
    *,
    candidate: bool,
    packed: bool,
    raw_rank: int,
    raw_score: float,
    dense_rank: int,
    path_rank: int | None,
    interpretation_created: bool,
    binding_created: bool,
) -> str:
    if not candidate:
        if path in {Q6_CURRENT, TYPED_REFERENCE}:
            return "SESSION_CUTOFF"
        if path in {"TURN_BM25", "TURN_BM25_NEIGHBOR", "REAL_RERANKER"}:
            return "LEXICAL_MATCH" if raw_score <= 0 else "RANKING"
        if path == "STRONG_DENSE":
            return "DENSE_MATCH" if dense_rank <= 0 else "RANKING"
        if path == "HYBRID":
            return "FUSION"
        raise AcquisitionLossError(f"unknown A0 path: {path}")
    if path_rank is not None and path_rank <= 0:
        raise AcquisitionLossError("A0 rank must be one-based")
    if not packed:
        return "PACKING"
    if not interpretation_created:
        return "INTERPRETATION"
    if not binding_created:
        return "BINDING"
    return "NOT_LOST"


def _q6_temporal_filter(trace: Mapping[str, Any]) -> bool:
    sufficiency = trace.get("q6_sufficiency")
    proof = sufficiency.get("proof") if isinstance(sufficiency, Mapping) else None
    return bool(
        isinstance(proof, Mapping) and proof.get("bounded_scan_completed") is True
    )


def _summaries(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in PATHS:
        rows = [row for row in records if row["acquisition_path"] == path]
        if len(rows) != 23:
            raise AcquisitionLossError("A0 per-path denominator drifted")
        result[path] = {
            "required_evidence_denominator": 23,
            "candidate_hits": sum(
                bool(row["survived_candidate_cutoff"]) for row in rows
            ),
            "packed_hits": sum(
                bool(row["retained_by_context_packing"]) for row in rows
            ),
            "interpretation_hits": sum(
                bool(row["interpretation_created"]) for row in rows
            ),
            "binding_hits": sum(bool(row["binding_created"]) for row in rows),
            "not_lost": sum(row["first_loss_stage"] == "NOT_LOST" for row in rows),
            "first_loss_stage_counts": dict(
                sorted(Counter(row["first_loss_stage"] for row in rows).items())
            ),
        }
    return result


def _turn_ref(unit: EvidenceUnit) -> str:
    if len(unit.turn_refs) != 1:
        raise AcquisitionLossError("A0 primitive TURN unit changed")
    return str(unit.turn_refs[0])


def _positions(ranking: Sequence[int]) -> dict[int, int]:
    return {index: rank for rank, index in enumerate(ranking, start=1)}


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _numeric_delta(
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


__all__ = [
    "LOSS_STAGES",
    "PATHS",
    "Q6_CURRENT",
    "AcquisitionLossError",
    "DenseRetriever",
    "IndexTextProjector",
    "Reranker",
    "TokenCounter",
    "attribute_acquisition_losses",
    "build_label_free_trace",
    "canonical_sha256",
]
