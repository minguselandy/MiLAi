"""Outcome-blind LongMemEval hierarchy and label-free Runtime case mapping.

The metadata loader is deliberately called only through the authority-first B0
runner.  It reads the frozen structural fields needed for stratification, keeps
the two existing DG-11 formal partitions out of development selection, and
never copies answer text or gold session identities into an experiment artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evals.dg14.contracts import DG14HistoryEvent, normalize_lme_timestamp
from evals.gdpm.b0_canary_contract import CanaryCaseMetadata
from evals.gdpm.b0_canary_runner import CanarySelectionInputs
from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = (
    ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
)
LABEL_FREE_INPUT_PATH = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
PROTECTED_MANIFESTS = (
    ROOT / "var/dg11/splits/v1/paper-test-v1/source-ids.json",
    ROOT / "var/dg11/splits/v1/generalization-v2/source-ids.json",
)

EXPECTED_DATASET_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
EXPECTED_LABEL_FREE_INPUT_SHA256 = (
    "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412"
)
EXPECTED_PROTECTED_MANIFEST_SHA256 = (
    "73cbd2609a616301d8f06e709bcddd22832b1e30a35b9d5a6388565ff7cd3bd2",
    "0d3b69fc6ece6c6c1d07584cb5a4f7c3b532289cf2338912d3d285c7fbe76dfd",
)
QUERY_CAPABILITIES = (
    "knowledge-update",
    "multi-session",
    "single-session-assistant",
    "single-session-preference",
    "single-session-user",
    "temporal-reasoning",
)
CONTEXT_SIZE_THRESHOLD_UTF8_BYTES = 490_102
PARENT_CASE_COUNT = 128
POPULATION_CASE_COUNT = 500
ELIGIBLE_DEVELOPMENT_CASE_COUNT = 300
_PARENT_SALT = "gdpm-b0-parent-128-order-v1"
_DATASET_FIELDS = {
    "answer",
    "answer_session_ids",
    "haystack_dates",
    "haystack_session_ids",
    "haystack_sessions",
    "question",
    "question_date",
    "question_id",
    "question_type",
}


class B0LongMemEvalError(RuntimeError):
    """The frozen LongMemEval hierarchy or case mapping drifted."""


@dataclass(frozen=True, slots=True)
class B0RuntimeCase:
    """Label-free view accepted by the product-isomorphic Runtime adapter."""

    case_id: str
    category: str
    question: str
    question_at: str
    sessions: tuple[Any, ...]
    history_events: tuple[DG14HistoryEvent, ...]

    @property
    def source_id(self) -> str:
        return self.case_id


def load_selection_inputs() -> CanarySelectionInputs:
    """Build the deterministic 128-parent/500-population selection hierarchy."""

    _require_sha(DATASET_PATH, EXPECTED_DATASET_SHA256, "LongMemEval dataset")
    _require_sha(
        LABEL_FREE_INPUT_PATH,
        EXPECTED_LABEL_FREE_INPUT_SHA256,
        "label-free LongMemEval input",
    )
    raw_rows = _load_json(DATASET_PATH)
    if not isinstance(raw_rows, list) or len(raw_rows) != POPULATION_CASE_COUNT:
        raise B0LongMemEvalError("LongMemEval population is not exactly 500 cases")

    _partition, frozen_cases = load_inputs(LABEL_FREE_INPUT_PATH)
    population_ids = tuple(case.source_id for case in frozen_cases)
    if len(population_ids) != POPULATION_CASE_COUNT:
        raise B0LongMemEvalError("label-free population is not exactly 500 cases")
    frozen_categories = {case.source_id: case.category for case in frozen_cases}
    frozen_content_sizes = {
        case.source_id: _label_free_history_content_utf8_bytes(case)
        for case in frozen_cases
    }

    rows_by_id: dict[str, Mapping[str, Any]] = {}
    content_sizes: list[int] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping) or set(raw) != _DATASET_FIELDS:
            raise B0LongMemEvalError("LongMemEval structural row schema drifted")
        source_id = raw.get("question_id")
        if not isinstance(source_id, str) or not source_id or source_id in rows_by_id:
            raise B0LongMemEvalError("LongMemEval source identity is invalid")
        rows_by_id[source_id] = raw
        content_sizes.append(frozen_content_sizes[source_id])
    if set(rows_by_id) != set(population_ids):
        raise B0LongMemEvalError("dataset and label-free population identities differ")
    ordered_sizes = sorted(content_sizes)
    if (
        ordered_sizes[249] != 490_040
        or ordered_sizes[250] != CONTEXT_SIZE_THRESHOLD_UTF8_BYTES
        or sum(value < CONTEXT_SIZE_THRESHOLD_UTF8_BYTES for value in ordered_sizes)
        != 250
    ):
        raise B0LongMemEvalError("frozen context-size threshold no longer bisects 500")

    protected_sets, protected_receipts = _load_protected_source_ids(population_ids)
    protected_ids = set().union(*protected_sets)
    eligible_ids = set(population_ids) - protected_ids
    if len(eligible_ids) != ELIGIBLE_DEVELOPMENT_CASE_COUNT:
        raise B0LongMemEvalError("development/formal partition denominator drifted")

    metadata_by_id: dict[str, CanaryCaseMetadata] = {}
    for source_id, raw in rows_by_id.items():
        capability = raw.get("question_type")
        if capability not in QUERY_CAPABILITIES:
            raise B0LongMemEvalError("LongMemEval query capability drifted")
        if frozen_categories[source_id] != capability:
            raise B0LongMemEvalError("dataset and label-free capability differ")
        answerability = "ABSTENTION" if source_id.endswith("_abs") else "ANSWERABLE"
        bucket = (
            "NONE"
            if answerability == "ABSTENTION"
            else _gold_session_bucket(raw.get("answer_session_ids"))
        )
        metadata_by_id[source_id] = CanaryCaseMetadata.from_mapping(
            {
                "source_id": source_id,
                "gold_session_bucket": bucket,
                "answerability": answerability,
                "query_capability": capability,
                "context_size": (
                    "SHORT"
                    if frozen_content_sizes[source_id]
                    < CONTEXT_SIZE_THRESHOLD_UTF8_BYTES
                    else "NEAR_BUDGET"
                ),
                # LongMemEval's `_abs` companion cases are the benchmark's
                # structurally declared hard-negative relation variants.
                "relation_hard_negative": answerability == "ABSTENTION",
            }
        )

    eligible_metadata = tuple(metadata_by_id[source_id] for source_id in eligible_ids)
    selected_parent = _select_parent_128(eligible_metadata)
    parent_ids = tuple(item.source_id for item in selected_parent)
    population_manifest = _seal_manifest(
        {
            "schema_version": "mila-gdpm-population-500-manifest-v0.1",
            "case_count": POPULATION_CASE_COUNT,
            "source_ids": list(population_ids),
            "source_ids_sha256": _digest(list(population_ids)),
            "dataset": {
                "path": str(DATASET_PATH),
                "sha256": EXPECTED_DATASET_SHA256,
            },
            "label_free_inputs": {
                "path": str(LABEL_FREE_INPUT_PATH),
                "sha256": EXPECTED_LABEL_FREE_INPUT_SHA256,
                "partition": _partition,
            },
        }
    )
    parent_manifest = _seal_manifest(
        {
            "schema_version": "mila-gdpm-development-parent-128-manifest-v0.1",
            "case_count": PARENT_CASE_COUNT,
            "source_ids": list(parent_ids),
            "source_ids_sha256": _digest(list(parent_ids)),
            "metadata": [asdict(item) for item in selected_parent],
            "coverage": _coverage(selected_parent),
            "selection_policy": {
                "identity": "METADATA_OUTCOME_BLIND_PARENT_128_V1",
                "tie_breaker": f"SHA256({_PARENT_SALT}\\0source_id)",
                "context_size_measure": "sum(turn.content UTF-8 bytes)",
                "context_size_threshold_utf8_bytes": (
                    CONTEXT_SIZE_THRESHOLD_UTF8_BYTES
                ),
                "eligible_development_case_count": (
                    ELIGIBLE_DEVELOPMENT_CASE_COUNT
                ),
                "protected_source_ids_excluded": True,
            },
            "protected_partitions": protected_receipts,
            "protected_union": {
                "case_count": len(protected_ids),
                "source_ids_sha256": _digest(sorted(protected_ids)),
                "status": "NOT_CONSUMED_BY_GDPM_DEVELOPMENT_SELECTION",
            },
            "population_500_manifest_sha256": population_manifest[
                "manifest_digest"
            ],
            "forbidden_selection_fields": [
                "answer",
                "gold_session_ids",
                "system_result",
                "treatment_opportunity",
                "treatment_rank",
            ],
        }
    )
    return CanarySelectionInputs(
        metadata_pool=selected_parent,
        parent_128_source_ids=parent_ids,
        population_500_source_ids=population_ids,
        parent_128_manifest=parent_manifest,
        population_500_manifest=population_manifest,
        required_query_capabilities=QUERY_CAPABILITIES,
    )


def load_runtime_cases(case_ids: tuple[str, ...]) -> Mapping[str, B0RuntimeCase]:
    """Load exactly the requested cases from the sealed label-free input."""

    _require_sha(
        LABEL_FREE_INPUT_PATH,
        EXPECTED_LABEL_FREE_INPUT_SHA256,
        "label-free LongMemEval input",
    )
    _partition, cases = load_inputs(LABEL_FREE_INPUT_PATH)
    selected = set(case_ids)
    if len(case_ids) != len(selected):
        raise B0LongMemEvalError("requested Runtime case identities are duplicated")
    result = {
        case.source_id: _runtime_case(case)
        for case in cases
        if case.source_id in selected
    }
    if set(result) != selected:
        raise B0LongMemEvalError("requested Runtime case identities are incomplete")
    return result


def _runtime_case(case: LongMemEvalCase) -> B0RuntimeCase:
    events = tuple(
        DG14HistoryEvent.from_mapping(
            {
                "case_id": case.source_id,
                "session_ordinal": session_ordinal,
                "original_session_id": session.session_id,
                "turn_ordinal": turn_ordinal,
                "role": turn.role,
                "content": turn.content,
                "observed_at": normalize_lme_timestamp(session.observed_at),
            }
        )
        for session_ordinal, session in enumerate(case.sessions)
        for turn_ordinal, turn in enumerate(session.turns)
    )
    return B0RuntimeCase(
        case_id=case.source_id,
        category=case.category,
        question=case.question,
        question_at=case.question_at,
        sessions=case.sessions,
        history_events=events,
    )


def _select_parent_128(
    cases: Sequence[CanaryCaseMetadata],
) -> tuple[CanaryCaseMetadata, ...]:
    if len(cases) != ELIGIBLE_DEVELOPMENT_CASE_COUNT:
        raise B0LongMemEvalError("parent selector requires exactly 300 eligible cases")
    required = {
        *(f"gold:{value}" for value in ("ONE", "TWO", "THREE_TO_SIX")),
        "answerability:ANSWERABLE",
        "answerability:ABSTENTION",
        "context:SHORT",
        "context:NEAR_BUDGET",
        *(f"capability:{value}" for value in QUERY_CAPABILITIES),
        "relation_hard_negative:true",
    }
    remaining = set(required)
    available = list(cases)
    selected: list[CanaryCaseMetadata] = []
    while remaining:
        ranked = sorted(
            available,
            key=lambda item: (
                -len(_tags(item).intersection(remaining)),
                _parent_order_key(item.source_id),
            ),
        )
        if not ranked or not _tags(ranked[0]).intersection(remaining):
            raise B0LongMemEvalError(
                f"eligible development pool cannot cover {sorted(remaining)}"
            )
        candidate = ranked[0]
        selected.append(candidate)
        available.remove(candidate)
        remaining.difference_update(_tags(candidate))
    selected.extend(
        sorted(available, key=lambda item: _parent_order_key(item.source_id))[
            : PARENT_CASE_COUNT - len(selected)
        ]
    )
    if len(selected) != PARENT_CASE_COUNT:
        raise B0LongMemEvalError("parent selector did not produce exactly 128 cases")
    return tuple(sorted(selected, key=lambda item: _parent_order_key(item.source_id)))


def _tags(item: CanaryCaseMetadata) -> set[str]:
    result = {
        f"gold:{item.gold_session_bucket}",
        f"answerability:{item.answerability}",
        f"context:{item.context_size}",
        f"capability:{item.query_capability}",
    }
    if item.relation_hard_negative:
        result.add("relation_hard_negative:true")
    return result


def _coverage(cases: Sequence[CanaryCaseMetadata]) -> dict[str, object]:
    return {
        "gold_session_bucket": dict(
            sorted(Counter(item.gold_session_bucket for item in cases).items())
        ),
        "answerability": dict(
            sorted(Counter(item.answerability for item in cases).items())
        ),
        "query_capability": dict(
            sorted(Counter(item.query_capability for item in cases).items())
        ),
        "context_size": dict(
            sorted(Counter(item.context_size for item in cases).items())
        ),
        "relation_hard_negative_count": sum(
            item.relation_hard_negative for item in cases
        ),
    }


def _load_protected_source_ids(
    population_ids: Sequence[str],
) -> tuple[tuple[set[str], ...], list[dict[str, object]]]:
    population = set(population_ids)
    sets: list[set[str]] = []
    receipts: list[dict[str, object]] = []
    for path, expected_sha in zip(
        PROTECTED_MANIFESTS, EXPECTED_PROTECTED_MANIFEST_SHA256, strict=True
    ):
        _require_sha(path, expected_sha, "protected source-ID manifest")
        raw = _load_json(path)
        if (
            not isinstance(raw, Mapping)
            or raw.get("schema") != "milai.dg11.recovery-source-ids.v1"
            or raw.get("status") != "FROZEN_UNCONSUMED"
            or raw.get("case_count") != 100
            or not isinstance(raw.get("source_ids"), list)
            or len(raw["source_ids"]) != 100
            or len(set(raw["source_ids"])) != 100
        ):
            raise B0LongMemEvalError("protected source-ID manifest drifted")
        source_ids = set(raw["source_ids"])
        if not source_ids.issubset(population):
            raise B0LongMemEvalError("protected source IDs leave the 500 population")
        sets.append(source_ids)
        receipts.append(
            {
                "path": str(path),
                "sha256": expected_sha,
                "split": raw.get("split"),
                "case_count": 100,
                "source_ids_sha256": raw.get("source_ids_sha256"),
                "status": raw.get("status"),
                "labels_or_case_content_accessed": False,
            }
        )
    if sets[0].intersection(sets[1]):
        raise B0LongMemEvalError("protected source-ID partitions overlap")
    return tuple(sets), receipts


def _label_free_history_content_utf8_bytes(case: LongMemEvalCase) -> int:
    # Measure only the already-frozen label-free view.  In particular, the raw
    # dataset's per-turn `has_answer` marker is neither read nor copied.
    return sum(
        len(turn.content.encode("utf-8"))
        for session in case.sessions
        for turn in session.turns
    )


def _gold_session_bucket(value: object) -> str:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise B0LongMemEvalError("gold-session structural metadata is invalid")
    count = len(set(value))
    if count == 1:
        return "ONE"
    if count == 2:
        return "TWO"
    if 3 <= count <= 6:
        return "THREE_TO_SIX"
    raise B0LongMemEvalError("gold-session count is outside the frozen 1-6 strata")


def _parent_order_key(source_id: str) -> str:
    return hashlib.sha256(f"{_PARENT_SALT}\0{source_id}".encode()).hexdigest()


def _seal_manifest(material: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(material)
    return {**value, "manifest_digest": _digest(value)}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise B0LongMemEvalError(f"invalid frozen JSON: {path}") from exc


def _require_sha(path: Path, expected: str, label: str) -> None:
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise B0LongMemEvalError(f"cannot read {label}: {path}") from exc
    if actual != expected:
        raise B0LongMemEvalError(f"{label} byte identity drifted")


__all__ = [
    "CONTEXT_SIZE_THRESHOLD_UTF8_BYTES",
    "DATASET_PATH",
    "LABEL_FREE_INPUT_PATH",
    "PROTECTED_MANIFESTS",
    "QUERY_CAPABILITIES",
    "B0LongMemEvalError",
    "B0RuntimeCase",
    "load_runtime_cases",
    "load_selection_inputs",
]
