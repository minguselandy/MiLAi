"""DG-16 Q4 matched Evidence-unit ablation on the frozen opened-dev slice."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from milai.application.query_planner import QueryPlanner
from milai.domain.evidence_composition import query_spec_from_plan
from milai.domain.retrieval import RetrievalRequest

from evals.dg14.benchmark import (
    OPENED_DEV_CASE_IDS,
    OPENED_DEV_INPUT_PATH,
    OpenedDevCase,
    load_opened_dev,
)
from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg14.provider import ProviderResult
from evals.dg16.q0 import load_evaluation_fixture
from evals.paper.adapters.baselines import _bm25_scores
from evals.paper.scorers.longmemeval import score_answer

UNIT_KINDS = ("CHUNK", "TURN", "TURN_NEIGHBOR", "EPISODE")
TOP_K = 3
TOKEN_BUDGET = 2_048
CHUNK_BYTES = 1_600


class Q4Provider(Protocol):
    def answer(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        token_budget: int,
    ) -> ProviderResult: ...


TokenCounter = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class EvidenceUnit:
    unit_id: str
    kind: str
    session_id: str
    session_ordinal: int
    observed_at: str
    index_text: str
    content: str
    turn_refs: tuple[str, ...]


def _source_turn_ref(
    case: OpenedDevCase, session_ordinal: int, turn_ordinal: int
) -> str:
    session = case.sessions[session_ordinal]
    return (
        f"{case.case_id}:s{session_ordinal}:{session.session_id}:t{turn_ordinal}"
    )


def _split_utf8(value: str, maximum_bytes: int) -> tuple[str, ...]:
    remaining = value.strip()
    fragments: list[str] = []
    while remaining:
        used = cutoff = last_space = 0
        for index, character in enumerate(remaining):
            width = len(character.encode("utf-8"))
            if used + width > maximum_bytes:
                break
            used += width
            cutoff = index + 1
            if character.isspace():
                last_space = cutoff
        if cutoff == len(remaining):
            fragments.append(remaining)
            break
        if last_space >= max(1, cutoff // 2):
            cutoff = last_space
        fragment = remaining[:cutoff].strip()
        if not fragment:
            raise RuntimeError("Q4 chunk splitter made no progress")
        fragments.append(fragment)
        remaining = remaining[cutoff:].lstrip()
    return tuple(fragments)


def _append_chunk_unit(
    units: list[EvidenceUnit],
    *,
    session_id: str,
    session_ordinal: int,
    observed_at: str,
    current_text: list[str],
    current_refs: list[str],
) -> None:
    if not current_text:
        return
    content = "\n\n".join(current_text)
    units.append(
        EvidenceUnit(
            f"{session_id}:chunk:{len(units)}",
            "CHUNK",
            session_id,
            session_ordinal,
            observed_at,
            content,
            content,
            tuple(dict.fromkeys(current_refs)),
        )
    )
    current_text.clear()
    current_refs.clear()


def build_units(case: OpenedDevCase, kind: str) -> tuple[EvidenceUnit, ...]:
    """Build one reconstructible representation without consulting labels."""

    if kind not in UNIT_KINDS:
        raise ValueError("unknown Q4 Evidence unit")
    units: list[EvidenceUnit] = []
    for session_ordinal, session in enumerate(case.sessions):
        turns = tuple(session.turns)
        refs = tuple(
            _source_turn_ref(case, session_ordinal, turn_ordinal)
            for turn_ordinal in range(len(turns))
        )
        if kind == "EPISODE":
            user_text = " ".join(
                turn.content for turn in turns if turn.role == "user"
            )
            if user_text:
                units.append(
                    EvidenceUnit(
                        f"{session.session_id}:episode",
                        kind,
                        session.session_id,
                        session_ordinal,
                        normalize_lme_timestamp(session.observed_at),
                        user_text,
                        "\n\n".join(
                            f"{turn.role}: {turn.content}" for turn in turns
                        ),
                        refs,
                    )
                )
            continue
        if kind in {"TURN", "TURN_NEIGHBOR"}:
            for turn_ordinal, turn in enumerate(turns):
                selected_ordinals = (
                    tuple(
                        range(
                            max(0, turn_ordinal - 1),
                            min(len(turns), turn_ordinal + 2),
                        )
                    )
                    if kind == "TURN_NEIGHBOR"
                    else (turn_ordinal,)
                )
                units.append(
                    EvidenceUnit(
                        f"{session.session_id}:turn:{turn_ordinal}",
                        kind,
                        session.session_id,
                        session_ordinal,
                        normalize_lme_timestamp(session.observed_at),
                        turn.content,
                        "\n\n".join(
                            f"{turns[index].role}: {turns[index].content}"
                            for index in selected_ordinals
                        ),
                        tuple(refs[index] for index in selected_ordinals),
                    )
                )
            continue
        fragments: list[tuple[str, str]] = []
        for turn_ordinal, turn in enumerate(turns):
            prefix = f"{turn.role}: "
            for fragment in _split_utf8(
                turn.content, CHUNK_BYTES - len(prefix.encode("utf-8"))
            ):
                fragments.append((prefix + fragment, refs[turn_ordinal]))
        current_text: list[str] = []
        current_refs: list[str] = []
        for fragment, turn_ref in fragments:
            candidate = "\n\n".join([*current_text, fragment])
            if current_text and len(candidate.encode("utf-8")) > CHUNK_BYTES:
                _append_chunk_unit(
                    units,
                    session_id=session.session_id,
                    session_ordinal=session_ordinal,
                    observed_at=normalize_lme_timestamp(session.observed_at),
                    current_text=current_text,
                    current_refs=current_refs,
                )
            current_text.append(fragment)
            current_refs.append(turn_ref)
        _append_chunk_unit(
            units,
            session_id=session.session_id,
            session_ordinal=session_ordinal,
            observed_at=normalize_lme_timestamp(session.observed_at),
            current_text=current_text,
            current_refs=current_refs,
        )
    return tuple(units)


def _render(unit: EvidenceUnit) -> str:
    return (
        f"[Evidence unit={unit.kind} id={unit.unit_id} "
        f"session_id={unit.session_id} observed_at={unit.observed_at}]\n"
        f"{unit.content}"
    )


def _fit_context(
    units: Sequence[EvidenceUnit], budget: int, token_count: TokenCounter
) -> tuple[str, bool]:
    value = "\n\n".join(_render(unit) for unit in units)
    if token_count(value) <= budget:
        return value, False
    low, high = 0, len(value)
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = value[:middle].rstrip()
        if token_count(candidate) <= budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best, True


def retrieve_cell(
    case: OpenedDevCase,
    kind: str,
    *,
    token_count: TokenCounter,
) -> dict[str, Any]:
    units = build_units(case, kind)
    started = time.perf_counter()
    scores = _bm25_scores(
        [unit.index_text.split(" ") for unit in units],
        case.question.split(" "),
    )
    ranked = sorted(
        range(len(units)), key=lambda index: (scores[index], index), reverse=True
    )
    selected = [units[index] for index in ranked[:TOP_K]]
    selected.sort(
        key=lambda unit: (unit.observed_at, unit.session_ordinal, unit.unit_id)
    )
    context, truncated = _fit_context(selected, TOKEN_BUDGET, token_count)
    query_latency_ms = (time.perf_counter() - started) * 1_000
    turn_refs = [turn_ref for unit in selected for turn_ref in unit.turn_refs]
    return {
        "case_id": case.case_id,
        "unit": kind,
        "context": context,
        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
        "context_tokens": token_count(context),
        "context_truncated": truncated,
        "candidate_count": len(units),
        "selected_unit_count": len(selected),
        "selected_units": [asdict(unit) for unit in selected],
        "selected_turn_refs": turn_refs,
        "duplicated_evidence": len(turn_refs) - len(set(turn_refs)),
        "query_latency_ms": round(query_latency_ms, 6),
        "retriever": "BM25_OKAPI_0.2.2_COMPAT",
        "candidate_cap": TOP_K,
        "token_budget": TOKEN_BUDGET,
    }


def _query_spec_receipt(case: OpenedDevCase) -> dict[str, Any]:
    reference_time = datetime.fromisoformat(
        normalize_lme_timestamp(case.question_at).replace("Z", "+00:00")
    )
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=case.question,
            as_of=reference_time,
            system_as_of=reference_time,
        )
    )
    spec = query_spec_from_plan(plan)
    return (
        spec.model_dump(mode="json")
        if spec is not None
        else {
            "schema_version": "query-spec-v0.1",
            "operator": None,
            "answer_type": "LOOKUP",
        }
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 6)


def run_q4_ablation(
    *, run_id: str, provider: Q4Provider, token_count: TokenCounter
) -> dict[str, Any]:
    """Run all 20 matched cells; labels enter only after contexts are frozen."""

    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    if tuple(case.case_id for case in cases) != OPENED_DEV_CASE_IDS:
        raise RuntimeError("Q4 opened-development case order drifted")
    contexts = [
        retrieve_cell(case, kind, token_count=token_count)
        for case in cases
        for kind in UNIT_KINDS
    ]
    fixture = load_evaluation_fixture(cases=cases)
    labels = {item["case_id"]: item for item in fixture["cases"]}
    case_index = {case.case_id: case for case in cases}
    records: list[dict[str, Any]] = []
    for context_record in contexts:
        case_id = context_record["case_id"]
        kind = context_record["unit"]
        case = case_index[case_id]
        label = labels[case_id]
        atoms = label["required_atoms"]
        context = context_record["context"]
        atom_hits = [atom["span"]["text"] in context for atom in atoms]
        selected_sessions = {
            unit["session_id"] for unit in context_record["selected_units"]
        }
        boundary_losses = sum(
            atom["session_id"] in selected_sessions and not hit
            for atom, hit in zip(atoms, atom_hits, strict=True)
        )
        provider_result = provider.answer(
            run_id=run_id,
            case_id=case_id,
            method_id=f"DG16-Q4-{kind}",
            question=case.question,
            question_as_of=case.question_at,
            memory_context=context,
            token_budget=TOKEN_BUDGET,
        )
        score = score_answer(provider_result.answer, label["answers"])
        records.append(
            {
                **context_record,
                "query_spec": _query_spec_receipt(case),
                "required_atom_count": len(atoms),
                "answer_bearing_atom_hits": atom_hits,
                "answer_bearing_recall": sum(atom_hits) / len(atoms),
                "evidence_set_complete": all(atom_hits),
                "boundary_loss_count": boundary_losses,
                "prediction": provider_result.answer,
                "score": score,
                "reader": {
                    "prompt_sha256": provider_result.prompt_sha256,
                    "prompt_tokens": provider_result.prompt_tokens,
                    "memory_tokens": provider_result.memory_tokens,
                    "completion_tokens": provider_result.completion_tokens,
                    "provider_latency_ms": provider_result.provider_latency_ms,
                    "provider_calls": provider_result.provider_calls,
                    "context_truncated": provider_result.context_truncated,
                },
            }
        )
    summaries: dict[str, dict[str, Any]] = {}
    for kind in UNIT_KINDS:
        selected = [record for record in records if record["unit"] == kind]
        total_atoms = sum(record["required_atom_count"] for record in selected)
        summaries[kind] = {
            "case_count": len(selected),
            "answer_bearing_recall": sum(
                sum(record["answer_bearing_atom_hits"]) for record in selected
            )
            / total_atoms,
            "evidence_set_completeness": sum(
                record["evidence_set_complete"] for record in selected
            )
            / len(selected),
            "boundary_loss_rate": sum(
                record["boundary_loss_count"] for record in selected
            )
            / total_atoms,
            "mean_context_tokens": sum(
                record["context_tokens"] for record in selected
            )
            / len(selected),
            "query_latency_p95_ms": _percentile(
                [record["query_latency_ms"] for record in selected], 0.95
            ),
            "duplicated_evidence": sum(
                record["duplicated_evidence"] for record in selected
            ),
            "reader_exact_match": sum(
                record["score"]["exact_match"] for record in selected
            )
            / len(selected),
            "reader_normalized_f1": sum(
                record["score"]["normalized_f1"] for record in selected
            )
            / len(selected),
            "paired_case_outcomes": {
                record["case_id"]: record["score"]["exact_match"]
                for record in selected
            },
        }
    best = max(
        UNIT_KINDS,
        key=lambda kind: (
            summaries[kind]["reader_exact_match"],
            summaries[kind]["evidence_set_completeness"],
            summaries[kind]["answer_bearing_recall"],
            -summaries[kind]["mean_context_tokens"],
        ),
    )
    return {
        "schema": "milai.dg16.q4-evidence-unit-ablation.v1",
        "status": "SUCCEEDED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "formal_holdout_consumed": False,
        "label_fields_available_to_product_path": False,
        "run_id": run_id,
        "case_count": len(cases),
        "cell_count": len(records),
        "fixed_controls": {
            "retriever": "BM25_OKAPI_0.2.2_COMPAT",
            "candidate_cap": TOP_K,
            "token_budget": TOKEN_BUDGET,
            "reader_prompt": "FROZEN_DG14",
            "query_spec_by_case": {
                case.case_id: _query_spec_receipt(case) for case in cases
            },
        },
        "units": list(UNIT_KINDS),
        "records": records,
        "summaries": summaries,
        "selection": {
            "selected_unit": best,
            "rule": (
                "reader EM, then Evidence completeness, atom recall, then lower token cost"
            ),
            "production_default_frozen": False,
            "reason": "N=5 opened-development ablation only",
        },
    }


__all__ = ["UNIT_KINDS", "build_units", "retrieve_cell", "run_q4_ablation"]
