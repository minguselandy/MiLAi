"""Shared contracts for the public-dev Graphiti/OpenViking LME10 diagnostic."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FULL_LABEL_FREE_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
PUBLIC_DEV_SPLIT = ROOT / "var/dg14/splits/public-deidentified-dev-v1/source-ids.json"
EXPECTED_FULL_INPUT_SHA256 = (
    "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412"
)
EXPECTED_PUBLIC_DEV_SHA256 = (
    "91f502f79850b3dfb952c7094bc632615f6f69d8e40b8350ef292681b03913d2"
)
METHODS = ("GRAPHITI-OSS", "OPENVIKING-FIND")
BUDGETS = (512, 2048)


class ExternalLME10Error(RuntimeError):
    """The external public-development diagnostic contract drifted."""


@dataclass(frozen=True, slots=True)
class ExternalTurn:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ExternalSession:
    session_id: str
    observed_at: str
    turns: tuple[ExternalTurn, ...]


@dataclass(frozen=True, slots=True)
class ExternalCase:
    case_id: str
    category: str
    question: str
    question_at: str
    sessions: tuple[ExternalSession, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExternalLME10Error(f"JSON object required: {path}")
    return value


def load_cases() -> tuple[tuple[ExternalCase, ...], dict[str, Any]]:
    """Load exactly ten label-free cases selected by the frozen public-dev split."""

    identities = {
        "full_label_free_inputs": sha256_file(FULL_LABEL_FREE_INPUTS),
        "public_dev_split": sha256_file(PUBLIC_DEV_SPLIT),
    }
    if identities != {
        "full_label_free_inputs": EXPECTED_FULL_INPUT_SHA256,
        "public_dev_split": EXPECTED_PUBLIC_DEV_SHA256,
    }:
        raise ExternalLME10Error("frozen label-free input identity drifted")
    split = _object(PUBLIC_DEV_SPLIT)
    source_ids = split.get("source_ids")
    if (
        split.get("formal_holdout_consumed") is not False
        or split.get("formal_source_id_overlap") != []
        or not isinstance(source_ids, list)
        or len(source_ids) < 10
    ):
        raise ExternalLME10Error("public-development split contract drifted")
    selected = tuple(str(item) for item in source_ids[:10])
    frozen = _object(FULL_LABEL_FREE_INPUTS)
    if (
        frozen.get("paper_labels_opened") is not False
        or frozen.get("label_fields_accessed") is not False
        or frozen.get("forbidden_label_fields_present") is not False
    ):
        raise ExternalLME10Error("label-free input boundary drifted")
    rows = frozen.get("cases")
    if not isinstance(rows, list):
        raise ExternalLME10Error("label-free cases are missing")
    by_id = {
        str(row.get("source_id")): row for row in rows if isinstance(row, dict)
    }
    if any(case_id not in by_id for case_id in selected):
        raise ExternalLME10Error("selected public-development case is missing")
    cases: list[ExternalCase] = []
    for case_id in selected:
        row = by_id[case_id]
        raw_sessions = row.get("sessions")
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raise ExternalLME10Error(f"case {case_id} has no sessions")
        sessions: list[ExternalSession] = []
        for raw_session in raw_sessions:
            if not isinstance(raw_session, dict):
                raise ExternalLME10Error("session contract drifted")
            raw_turns = raw_session.get("turns")
            if not isinstance(raw_turns, list) or not raw_turns:
                raise ExternalLME10Error("turn contract drifted")
            sessions.append(
                ExternalSession(
                    session_id=str(raw_session["session_id"]),
                    observed_at=str(raw_session["observed_at"]),
                    turns=tuple(
                        ExternalTurn(role=str(turn["role"]), content=str(turn["content"]))
                        for turn in raw_turns
                        if isinstance(turn, dict)
                    ),
                )
            )
        cases.append(
            ExternalCase(
                case_id=case_id,
                category=str(row["category"]),
                question=str(row["question"]),
                question_at=str(row["question_date"]),
                sessions=tuple(sessions),
            )
        )
    if len(cases) != 10 or len({case.case_id for case in cases}) != 10:
        raise ExternalLME10Error("external diagnostic denominator drifted")
    return tuple(cases), {
        "case_count": 10,
        "source_ids": list(selected),
        "selection_policy": split.get("selection_policy"),
        "formal_source_id_overlap": [],
        "formal_holdout_consumed": False,
        "identities": identities,
    }


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ExternalLME10Error("cannot summarize an empty metric")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_scored(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["method_id"]), int(record["token_budget"]))].append(record)
    output: dict[str, Any] = {}
    for method in METHODS:
        output[method] = {}
        for budget in BUDGETS:
            cells = grouped[(method, budget)]
            if len(cells) != 10:
                raise ExternalLME10Error("scored cell denominator drifted")
            exact = [float(cell["answer_score"]["exact_match"]) for cell in cells]
            f1 = [float(cell["answer_score"]["normalized_f1"]) for cell in cells]
            hit = [float(cell["retrieval_score"]["hit_at_k"]) for cell in cells]
            recall = [
                float(cell["retrieval_score"]["relevant_coverage_at_k"])
                for cell in cells
            ]
            query = [float(cell["query_latency_ms"]) for cell in cells]
            answer_path = [
                float(cell["query_latency_ms"])
                + float(cell["provider"]["tokenize_latency_ms"])
                + float(cell["provider"]["provider_latency_ms"])
                for cell in cells
            ]
            output[method][str(budget)] = {
                "case_count": 10,
                "exact_match": round(mean(exact), 9),
                "normalized_f1": round(mean(f1), 9),
                "hit_at_k": round(mean(hit), 9),
                "relevant_coverage_at_k": round(mean(recall), 9),
                "query_latency_ms": {
                    "mean": round(mean(query), 6),
                    "p50": round(median(query), 6),
                    "p95": round(percentile(query, 0.95), 6),
                },
                "answer_path_latency_ms": {
                    "mean": round(mean(answer_path), 6),
                    "p50": round(median(answer_path), 6),
                    "p95": round(percentile(answer_path, 0.95), 6),
                },
                "context_tokens": round(
                    mean(float(cell["context_tokens"]) for cell in cells), 3
                ),
                "prompt_tokens": round(
                    mean(float(cell["provider"]["prompt_tokens"]) for cell in cells),
                    3,
                ),
            }
    return output
