"""A4 raw-vs-enriched lexical acquisition evaluation."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from milai.application.acquisition import (
    compile_acquisition_plan,
    fuse_acquisition_probe_results,
    probe_query,
)
from milai.application.lexical_cues import (
    compile_lexical_cue_set,
    enriched_lexical_terms,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import EvidenceRequirementV02
from milai.persistence.retrieval_repository import evidence_query_terms

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg17.measurement import load_answer_bearing_labels


def run_a4_evaluation(
    *,
    run_id: str,
    fixture_path: Path,
    goal_path: Path,
    focused_postgres_receipt: Path,
    candidate_cap: int = 20,
) -> dict[str, Any]:
    fixture_report = _score_declared_fixtures(fixture_path)
    _label_envelope, cases, labels = load_answer_bearing_labels()
    raw_traces = [_acquire_case(case, enriched=False, candidate_cap=candidate_cap) for case in cases]
    enriched_traces = [
        _acquire_case(case, enriched=True, candidate_cap=candidate_cap) for case in cases
    ]
    raw = _score_arm(raw_traces, labels)
    enriched = _score_arm(enriched_traces, labels)
    regressions = [
        case_id
        for case_id in raw["case_metrics"]
        if set(raw["case_metrics"][case_id]["hit_source_refs"])
        - set(enriched["case_metrics"][case_id]["hit_source_refs"])
    ]
    turn_gain = int(enriched["answer_bearing_source_turn_hits"]) - int(
        raw["answer_bearing_source_turn_hits"]
    )
    promote = turn_gain > 0 and not regressions and fixture_report["all_expected"]
    focused = _load_object(focused_postgres_receipt)
    if focused.get("status") != "PASS":
        raise ValueError("A4 focused PostgreSQL gate did not pass")
    return {
        "schema": "milai.dg17.a4-lexical-enrichment-evaluation.v0.1",
        "run_id": run_id,
        "status": "PASS",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / OPENED_DEV_FIXTURES",
        "formal_holdout_consumed": False,
        "bound_artifacts": {
            "goal": _identity(goal_path),
            "declared_fixtures": _identity(fixture_path),
            "focused_postgres_gate": _identity(focused_postgres_receipt),
        },
        "policy": {
            "baseline": "FTS_RAW_REQUIREMENT_SURFACES",
            "candidate": "FTS_RAW_PLUS_FTS_ENRICHED_GENERIC_MORPHOLOGY_V1",
            "candidate_cap": candidate_cap,
            "semantic_synonym_table": False,
            "dense_query_mutated": False,
            "model_calls": 0,
        },
        "arms": {"FTS_RAW": raw, "FTS_RAW_PLUS_ENRICHED": enriched},
        "delta": {
            "answer_bearing_source_turn_hits": turn_gain,
            "answer_bearing_atom_hits": int(enriched["answer_bearing_atom_hits"])
            - int(raw["answer_bearing_atom_hits"]),
            "operator_ready_cases": int(enriched["operator_ready_cases"])
            - int(raw["operator_ready_cases"]),
            "candidate_noise_count": int(enriched["candidate_noise_count"])
            - int(raw["candidate_noise_count"]),
            "regressed_case_ids": regressions,
        },
        "declared_generalization": fixture_report,
        "disposition": {
            "A4": (
                "CANDIDATE_FOR_NEXT_SINGLE_FACTOR_MATCHED_LANE"
                if promote
                else "PARKED_NO_MATERIAL_MEDIATOR_GAIN"
            ),
            "product_default_changed": False,
            "next_lane_may_enable": promote,
        },
        "gates": {
            "real_postgresql_channel_pass": True,
            "unseen_fixture_expectations_pass": fixture_report["all_expected"],
            "gold_source_gain_positive": turn_gain > 0,
            "previous_gold_hits_retained": not regressions,
            "semantic_negative_false_matches_zero": fixture_report[
                "negative_false_match_count"
            ]
            == 0,
            "automatic_retries_zero": True,
        },
        "label_boundary": {
            "label_free_traces_built_before_scoring": True,
            "product_path_label_access_count": 0,
            "runtime_imports_report": False,
        },
        "claim_boundary": {
            "mechanism_generalization_claim": "DECLARED_FIXTURES_ONLY",
            "final_lme_authorized": False,
            "release_claim_authorized": False,
        },
    }


def _acquire_case(case: Any, *, enriched: bool, candidate_cap: int) -> dict[str, Any]:
    started = time.perf_counter()
    as_of = datetime.fromisoformat(
        normalize_lme_timestamp(str(case.question_at)).replace("Z", "+00:00")
    )
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=str(case.question),
            as_of=as_of,
            system_as_of=as_of,
        )
    )
    acquisition = compile_acquisition_plan(
        plan,
        query=str(case.question),
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=candidate_cap,
        context_tokens=2_048,
        enable_enriched=enriched,
    )
    turns: list[dict[str, Any]] = []
    for session_ordinal, session in enumerate(case.sessions):
        for turn_ordinal, turn in enumerate(session.turns):
            source_ref = (
                f"{case.case_id}:s{session_ordinal}:{session.session_id}:t{turn_ordinal}"
            )
            turns.append(
                {
                    "evidence_id": hashlib.sha256(source_ref.encode()).hexdigest()[:24],
                    "source_ref": source_ref,
                    "subject_id": str(session.session_id),
                    "content": str(turn.content),
                    "speaker": str(turn.role),
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                    "tokens": set(evidence_query_terms(str(turn.content))),
                }
            )
    probe_results = []
    for probe in acquisition.probes:
        query_terms = set(evidence_query_terms(probe_query(probe)))
        candidates: list[dict[str, Any]] = []
        for turn in turns:
            overlap = len(query_terms.intersection(turn["tokens"]))
            if overlap == 0:
                continue
            candidate = {key: value for key, value in turn.items() if key != "tokens"}
            candidate["relevance_score"] = overlap / max(1, len(query_terms))
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (-float(item["relevance_score"]), str(item["source_ref"]))
        )
        probe_results.append((probe, candidates[: probe.candidate_limit]))
    selected = fuse_acquisition_probe_results(acquisition, probe_results)
    return {
        "case_id": str(case.case_id),
        "selected_source_refs": [str(item["source_ref"]) for item in selected],
        "candidate_count": len(selected),
        "probe_count": len(acquisition.probes),
        "channels": sorted({probe.channel for probe in acquisition.probes}),
        "latency_ms": (time.perf_counter() - started) * 1_000,
    }


def _score_arm(
    traces: Sequence[Mapping[str, Any]], labels: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    atom_hits = atom_total = turn_hits = turn_total = ready = noise = selected_total = 0
    latencies: list[float] = []
    case_metrics: dict[str, dict[str, Any]] = {}
    for trace in traces:
        case_id = str(trace["case_id"])
        selected = {str(value) for value in trace["selected_source_refs"]}
        atoms = labels[case_id]["atoms"]
        gold_turns = {str(atom["source_turn_ref"]) for atom in atoms}
        hit_turns = selected.intersection(gold_turns)
        case_atom_hits = sum(str(atom["source_turn_ref"]) in selected for atom in atoms)
        atom_hits += case_atom_hits
        atom_total += len(atoms)
        turn_hits += len(hit_turns)
        turn_total += len(gold_turns)
        ready += gold_turns.issubset(selected)
        noise += len(selected - gold_turns)
        selected_total += len(selected)
        latencies.append(float(trace["latency_ms"]))
        case_metrics[case_id] = {
            "atom_hits": case_atom_hits,
            "atom_denominator": len(atoms),
            "source_turn_hits": len(hit_turns),
            "source_turn_denominator": len(gold_turns),
            "hit_source_refs": sorted(hit_turns),
            "candidate_count": len(selected),
            "operator_ready": gold_turns.issubset(selected),
        }
    return {
        "answer_bearing_atom_hits": atom_hits,
        "answer_bearing_atom_denominator": atom_total,
        "answer_bearing_atom_recall": round(atom_hits / atom_total, 9),
        "answer_bearing_source_turn_hits": turn_hits,
        "answer_bearing_source_turn_denominator": turn_total,
        "answer_bearing_source_turn_recall": round(turn_hits / turn_total, 9),
        "operator_ready_cases": ready,
        "operator_ready_denominator": len(traces),
        "candidate_noise_count": noise,
        "selected_candidate_count": selected_total,
        "candidate_noise_rate": round(noise / selected_total, 9),
        "latency_ms": {
            "mean": round(mean(latencies), 6),
            "p95": round(_percentile(latencies, 0.95), 6),
        },
        "case_metrics": case_metrics,
    }


def _score_declared_fixtures(path: Path) -> dict[str, Any]:
    fixture = _load_object(path)
    rows = fixture.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("A4 fixture set is empty")
    results: list[dict[str, Any]] = []
    strata: defaultdict[str, list[bool]] = defaultdict(list)
    negative_false_matches = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("A4 fixture row must be an object")
        requirement = EvidenceRequirementV02(
            slot_id=str(row["case_id"]),
            interpretation_kind="STATE_OBSERVATION",
            entity_constraints=[str(value) for value in row["surface_terms"]],
        )
        cues = compile_lexical_cue_set(requirement)
        evidence_tokens = set(evidence_query_terms(str(row["evidence"])))
        raw_match = bool(set(cues.surface_terms).intersection(evidence_tokens))
        enriched_match = bool(set(enriched_lexical_terms(cues)).intersection(evidence_tokens))
        expected_raw = bool(row["expected_raw"])
        expected_enriched = bool(row["expected_enriched"])
        passed = raw_match == expected_raw and enriched_match == expected_enriched
        stratum = str(row["stratum"])
        strata[stratum].append(passed)
        if not expected_enriched and enriched_match:
            negative_false_matches += 1
        results.append(
            {
                "case_id": str(row["case_id"]),
                "stratum": stratum,
                "raw_match": raw_match,
                "enriched_match": enriched_match,
                "passed": passed,
            }
        )
    return {
        "case_count": len(results),
        "all_expected": all(item["passed"] for item in results),
        "negative_false_match_count": negative_false_matches,
        "per_stratum": {
            key: {"passed": sum(values), "denominator": len(values)}
            for key, values in sorted(strata.items())
        },
        "cases": results,
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.999999)))
    return ordered[index]


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


__all__ = ["run_a4_evaluation"]
