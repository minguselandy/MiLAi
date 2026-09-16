"""Authority-first contract for the GDPM B0 24-case context-only canary.

This module deliberately does not know a benchmark path or load benchmark data.
The future canary runner must pass its case loader through
``authorize_then_load`` so an unauthorized process cannot inspect case metadata.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

CANARY_CASE_COUNT = 24
SELECTION_POLICY = "METADATA_OUTCOME_BLIND_V1"
GOLD_SESSION_BUCKETS = ("ONE", "TWO", "THREE_TO_SIX", "NONE")
ANSWERABILITY_CLASSES = ("ANSWERABLE", "ABSTENTION")
CONTEXT_SIZE_CLASSES = ("SHORT", "NEAR_BUDGET")

_COMMON_AUTHORITY = {
    "active_block": "MILA-ML-EVAL-00",
    "execution_authorized": "true",
    "execution_scope": "B0_24_CASE_CONTEXT_ONLY_CANARY",
    "active_case_scope": "B0_24_CASE_CONTEXT_ONLY_CANARY",
    "active_run_scope": "GDPM_B0_24_CASE_CONTEXT_ONLY_CANARY",
    "authorized_case_count": str(CANARY_CASE_COUNT),
    "selection_metadata_access_authorized": "true",
    "benchmark_case_execution_authorized": "true",
    "reader_answer_judge_calls_authorized": "false",
    "formal_holdout_authorized": "false",
}
_MASTER_AUTHORITY = {
    "document_id": "MILA-ML-MASTER",
    "version": "2.0",
    "status": "ACTIVE_EXECUTION_MASTER",
    "active_goal": "MILA-GDPM-01@0.2",
    **_COMMON_AUTHORITY,
}
_GOAL_AUTHORITY = {
    "document_id": "MILA-GDPM-01",
    "version": "0.2",
    "status": "ACTIVE_B0_24_CASE_CANARY",
    **_COMMON_AUTHORITY,
    "canonical_schema_change_authorized": "false",
    "product_default_enable_authorized": "false",
    "public_mcp_change_authorized": "false",
}

_ALLOWED_METADATA_FIELDS = {
    "answerability",
    "context_size",
    "gold_session_bucket",
    "query_capability",
    "relation_hard_negative",
    "source_id",
}
_FORBIDDEN_SELECTION_FIELDS = {
    "answer",
    "answer_session_ids",
    "gold_lexical_terms",
    "gold_session_ids",
    "judge_score",
    "reader_correct",
    "system_correct",
    "treatment_opportunity",
    "treatment_rank",
    "treatment_recovered",
}
_T = TypeVar("_T")


class B0CanaryContractError(RuntimeError):
    """The 24-case canary authority or metadata contract failed closed."""


@dataclass(frozen=True, slots=True)
class CanaryAuthorityReceipt:
    master_sha256: str
    goal_sha256: str
    case_count: int = CANARY_CASE_COUNT
    scope: str = "B0_24_CASE_CONTEXT_ONLY_CANARY"
    reader_answer_judge_calls: int = 0
    formal_holdout_consumed: bool = False


@dataclass(frozen=True, slots=True)
class CanaryCaseMetadata:
    """Only the structural fields permitted for outcome-blind selection."""

    source_id: str
    gold_session_bucket: str
    answerability: str
    query_capability: str
    context_size: str
    relation_hard_negative: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CanaryCaseMetadata:
        fields = set(value)
        forbidden = sorted(fields.intersection(_FORBIDDEN_SELECTION_FIELDS))
        if forbidden:
            raise B0CanaryContractError(
                f"outcome/gold-content fields are forbidden in selection metadata: {forbidden}"
            )
        if fields != _ALLOWED_METADATA_FIELDS:
            raise B0CanaryContractError(
                "canary metadata fields drifted: "
                f"missing={sorted(_ALLOWED_METADATA_FIELDS - fields)}, "
                f"extra={sorted(fields - _ALLOWED_METADATA_FIELDS)}"
            )
        source_id = value["source_id"]
        bucket = value["gold_session_bucket"]
        answerability = value["answerability"]
        capability = value["query_capability"]
        context_size = value["context_size"]
        relation_hard_negative = value["relation_hard_negative"]
        if not isinstance(source_id, str) or not source_id:
            raise B0CanaryContractError("canary source_id is empty")
        if bucket not in GOLD_SESSION_BUCKETS:
            raise B0CanaryContractError("invalid gold-session bucket")
        if answerability not in ANSWERABILITY_CLASSES:
            raise B0CanaryContractError("invalid answerability class")
        if not isinstance(capability, str) or not capability.strip():
            raise B0CanaryContractError("query capability is empty")
        if context_size not in CONTEXT_SIZE_CLASSES:
            raise B0CanaryContractError("invalid context-size class")
        if not isinstance(relation_hard_negative, bool):
            raise B0CanaryContractError("relation-hard-negative flag is not boolean")
        if answerability == "ABSTENTION" and bucket != "NONE":
            raise B0CanaryContractError(
                "abstention metadata must not invent a gold-session count"
            )
        if answerability == "ANSWERABLE" and bucket == "NONE":
            raise B0CanaryContractError(
                "answerable metadata requires a structural gold-session bucket"
            )
        return cls(
            source_id=source_id,
            gold_session_bucket=str(bucket),
            answerability=str(answerability),
            query_capability=capability.strip(),
            context_size=str(context_size),
            relation_hard_negative=relation_hard_negative,
        )


def assert_b0_canary_authorized(
    *, master_path: Path, goal_path: Path
) -> CanaryAuthorityReceipt:
    """Fail before case access unless both authority documents agree exactly."""

    return assert_canary_authorized(
        master_path=master_path,
        goal_path=goal_path,
        master_authority=_MASTER_AUTHORITY,
        goal_authority=_GOAL_AUTHORITY,
        scope="B0_24_CASE_CONTEXT_ONLY_CANARY",
    )


def assert_canary_authorized(
    *,
    master_path: Path,
    goal_path: Path,
    master_authority: Mapping[str, str],
    goal_authority: Mapping[str, str],
    scope: str,
) -> CanaryAuthorityReceipt:
    """Validate an explicit successor authority profile before any case access."""

    master = _frontmatter(master_path)
    goal = _frontmatter(goal_path)
    if not scope.strip():
        raise B0CanaryContractError("canary scope is empty")
    _require_authority(master, master_authority, "Master", scope)
    _require_authority(goal, goal_authority, "Goal", scope)
    return CanaryAuthorityReceipt(
        master_sha256=_sha256(master_path),
        goal_sha256=_sha256(goal_path),
        scope=scope,
    )


def authorize_then_load(
    *, master_path: Path, goal_path: Path, loader: Callable[[], _T]
) -> tuple[CanaryAuthorityReceipt, _T]:
    """Establish authority before invoking a benchmark or metadata loader."""

    receipt = assert_b0_canary_authorized(
        master_path=master_path,
        goal_path=goal_path,
    )
    return receipt, loader()


def freeze_canary_manifest(
    *,
    cases: Sequence[CanaryCaseMetadata],
    parent_128_source_ids: Sequence[str],
    population_500_source_ids: Sequence[str],
    parent_128_manifest: Mapping[str, Any],
    population_500_manifest: Mapping[str, Any],
    required_query_capabilities: Sequence[str],
) -> dict[str, Any]:
    """Select 24 from a 128-case metadata pool and freeze the nested manifest."""

    if len(cases) != 128:
        raise B0CanaryContractError("canary selector requires the exact 128-case pool")
    source_ids = tuple(item.source_id for item in cases)
    if len(set(source_ids)) != 128:
        raise B0CanaryContractError("128-case metadata pool contains duplicate IDs")
    parent_ids = tuple(parent_128_source_ids)
    if len(parent_ids) != 128 or len(set(parent_ids)) != 128:
        raise B0CanaryContractError("parent development manifest must contain 128 IDs")
    if set(source_ids) != set(parent_ids):
        raise B0CanaryContractError("metadata pool differs from its 128-case parent")
    population_ids = tuple(population_500_source_ids)
    if len(population_ids) != 500 or len(set(population_ids)) != 500:
        raise B0CanaryContractError("population manifest must contain 500 unique IDs")
    if not set(parent_ids).issubset(population_ids):
        raise B0CanaryContractError("128-case parent is not nested in the 500 population")
    parent_128_manifest_sha256 = _verify_parent_manifest(
        parent_128_manifest,
        label="parent-128",
        expected_count=128,
        expected_source_ids=parent_ids,
    )
    population_500_manifest_sha256 = _verify_parent_manifest(
        population_500_manifest,
        label="population-500",
        expected_count=500,
        expected_source_ids=population_ids,
    )
    capabilities = tuple(required_query_capabilities)
    if (
        len(capabilities) < 2
        or len(set(capabilities)) != len(capabilities)
        or any(not isinstance(item, str) or not item.strip() for item in capabilities)
    ):
        raise B0CanaryContractError(
            "required query-capability strata must contain unique nonempty values"
        )
    selected = _select_cases(cases, capabilities)
    coverage = _coverage(selected)
    missing = {
        "gold_session_bucket": sorted(
            {"ONE", "TWO", "THREE_TO_SIX"}
            - set(coverage["gold_session_bucket"])
        ),
        "answerability": sorted(
            set(ANSWERABILITY_CLASSES) - set(coverage["answerability"])
        ),
        "context_size": sorted(
            set(CONTEXT_SIZE_CLASSES) - set(coverage["context_size"])
        ),
    }
    missing = {name: values for name, values in missing.items() if values}
    if missing:
        raise B0CanaryContractError(f"canary metadata coverage is incomplete: {missing}")
    missing_capabilities = sorted(set(capabilities) - set(coverage["query_capability"]))
    if missing_capabilities:
        raise B0CanaryContractError(
            f"canary query-capability coverage is incomplete: {missing_capabilities}"
        )
    if coverage["relation_hard_negative_count"] < 1:
        raise B0CanaryContractError("canary lacks a relation hard negative")
    ordered = tuple(sorted(selected, key=lambda item: _case_order_key(item.source_id)))
    material: dict[str, Any] = {
        "schema_version": "mila-gdpm-b0-canary-manifest-v0.1",
        "selection_policy": {
            "identity": SELECTION_POLICY,
            "required_query_capabilities": list(capabilities),
            "tie_breaker": "SHA256(gdpm-b0-canary-order-v1\\0source_id)",
        },
        "case_count": CANARY_CASE_COUNT,
        "cases": [asdict(item) for item in ordered],
        "case_ids_sha256": _digest([item.source_id for item in ordered]),
        "coverage": coverage,
        "nesting": {
            "parent_128_case_count": 128,
            "parent_128_manifest_sha256": parent_128_manifest_sha256,
            "population_500_case_count": 500,
            "population_500_manifest_sha256": population_500_manifest_sha256,
        },
        "selection_fields": sorted(_ALLOWED_METADATA_FIELDS - {"source_id"}),
        "forbidden_selection_fields": sorted(_FORBIDDEN_SELECTION_FIELDS),
        "reader_answer_judge_calls_authorized": False,
        "formal_holdout_authorized": False,
    }
    return {**material, "manifest_digest": _digest(material)}


def required_authority_delta() -> dict[str, dict[str, str]]:
    """Return the exact Master/Goal scalar fields needed for the next run."""

    return {
        "master": dict(_MASTER_AUTHORITY),
        "goal": dict(_GOAL_AUTHORITY),
    }


def _coverage(cases: Sequence[CanaryCaseMetadata]) -> dict[str, Any]:
    buckets = Counter(item.gold_session_bucket for item in cases)
    answerability = Counter(item.answerability for item in cases)
    capabilities = Counter(item.query_capability for item in cases)
    context_sizes = Counter(item.context_size for item in cases)
    return {
        "gold_session_bucket": dict(sorted(buckets.items())),
        "answerability": dict(sorted(answerability.items())),
        "query_capability": dict(sorted(capabilities.items())),
        "context_size": dict(sorted(context_sizes.items())),
        "relation_hard_negative_count": sum(
            item.relation_hard_negative for item in cases
        ),
    }


def _select_cases(
    cases: Sequence[CanaryCaseMetadata], required_capabilities: Sequence[str]
) -> tuple[CanaryCaseMetadata, ...]:
    required_tags = {
        *(f"gold:{value}" for value in ("ONE", "TWO", "THREE_TO_SIX")),
        *(f"answerability:{value}" for value in ANSWERABILITY_CLASSES),
        *(f"context:{value}" for value in CONTEXT_SIZE_CLASSES),
        *(f"capability:{value}" for value in required_capabilities),
        "relation_hard_negative:true",
    }
    remaining = set(required_tags)
    available = list(cases)
    selected: list[CanaryCaseMetadata] = []
    while remaining:
        ranked = sorted(
            available,
            key=lambda item: (
                -len(_selection_tags(item).intersection(remaining)),
                _case_order_key(item.source_id),
            ),
        )
        if not ranked:
            break
        candidate = ranked[0]
        covered = _selection_tags(candidate).intersection(remaining)
        if not covered:
            break
        selected.append(candidate)
        available.remove(candidate)
        remaining.difference_update(covered)
    if remaining:
        raise B0CanaryContractError(
            f"128-case metadata pool cannot cover required strata: {sorted(remaining)}"
        )
    for candidate in sorted(available, key=lambda item: _case_order_key(item.source_id)):
        if len(selected) == CANARY_CASE_COUNT:
            break
        selected.append(candidate)
    if len(selected) != CANARY_CASE_COUNT:
        raise B0CanaryContractError("metadata selector did not produce exactly 24 cases")
    return tuple(selected)


def _selection_tags(item: CanaryCaseMetadata) -> set[str]:
    tags = {
        f"gold:{item.gold_session_bucket}",
        f"answerability:{item.answerability}",
        f"context:{item.context_size}",
        f"capability:{item.query_capability}",
    }
    if item.relation_hard_negative:
        tags.add("relation_hard_negative:true")
    return tags


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise B0CanaryContractError(f"cannot read authority document: {path}") from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise B0CanaryContractError(f"authority frontmatter is missing: {path}")
    body = text[4:].split("\n---\n", 1)[0]
    values: dict[str, str] = {}
    for line in body.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().strip('"').strip("'")
        if value:
            values[key] = value
    return values


def _require_authority(
    actual: Mapping[str, str],
    expected: Mapping[str, str],
    label: str,
    scope: str,
) -> None:
    drift = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if drift:
        raise B0CanaryContractError(
            f"{label} does not authorize {scope}: {drift}"
        )


def _case_order_key(source_id: str) -> str:
    return hashlib.sha256(f"gdpm-b0-canary-order-v1\0{source_id}".encode()).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _verify_parent_manifest(
    value: Mapping[str, Any],
    *,
    label: str,
    expected_count: int,
    expected_source_ids: Sequence[str],
) -> str:
    """Verify manifest material instead of trusting a caller-supplied digest."""

    material = dict(value)
    digest = material.pop("manifest_digest", None)
    if not isinstance(digest, str) or not _is_sha256(digest):
        raise B0CanaryContractError(f"{label} manifest digest is invalid")
    if digest != _digest(material):
        raise B0CanaryContractError(f"{label} manifest material differs from its digest")
    source_ids = material.get("source_ids")
    if (
        material.get("case_count") != expected_count
        or not isinstance(source_ids, list)
        or len(source_ids) != expected_count
        or len(set(source_ids)) != expected_count
        or set(source_ids) != set(expected_source_ids)
    ):
        raise B0CanaryContractError(f"{label} manifest source identity drifted")
    return digest
