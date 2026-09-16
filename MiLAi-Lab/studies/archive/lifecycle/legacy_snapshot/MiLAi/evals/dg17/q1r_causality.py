"""Fail-closed contracts for the DG-17 Q1R matched causality lane."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from evals.dg14.provider import full_provider_contract_sha256
from evals.paper.provider import prompt_contract_sha256, serialized_prompt

POLICIES = ("DG16_ANY_EVIDENCE_STOP", "DG17_QUERY_SPECIFIC_STOP")
EXPECTED_BUDGETS = (512, 2048)
CONTEXT_ARCHIVE_SCHEMA = "milai.dg17.q1r-context-pairs.v0.1"
GENERATION_ARCHIVE_SCHEMA = "milai.dg17.q1r-generations.v0.1"
_HEX64 = frozenset("0123456789abcdef")
_OPAQUE_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_OPAQUE_SHA256 = re.compile(r"(?i)\b[0-9a-f]{64}\b")
_ALLOWED_MEDIATOR_ROOTS = frozenset(
    {
        "acquisition_trace",
        "binding_annotations",
        "derived_result",
        "evidence_prose",
        "memory_status",
        "scope_authority",
        "selected_order",
        "selected_source_refs",
        "speaker_time",
        "sufficiency",
        "truncation",
    }
)


class Q1RCausalityError(RuntimeError):
    """A Q1R input or execution receipt violated the matched contract."""


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_context_archive(
    archive: Mapping[str, Any],
    *,
    case_ids: Sequence[str],
    budgets: Sequence[int] = EXPECTED_BUDGETS,
) -> list[dict[str, Any]]:
    """Validate and return a sealed two-policy, same-snapshot context denominator."""

    expected_cells = {
        (case_id, int(budget), policy)
        for case_id in case_ids
        for budget in budgets
        for policy in POLICIES
    }
    if (
        archive.get("schema") != CONTEXT_ARCHIVE_SCHEMA
        or archive.get("status") != "SUCCEEDED"
        or archive.get("label_fields_available") is not False
        or archive.get("historical_answer_reuse") is not False
    ):
        raise Q1RCausalityError("Q1R context archive envelope is invalid")
    snapshots = archive.get("snapshots")
    records = archive.get("records")
    if not isinstance(snapshots, list) or not isinstance(records, list):
        raise Q1RCausalityError("Q1R context archive lacks snapshots or records")
    snapshot_by_case: dict[str, str] = {}
    for raw in snapshots:
        if not isinstance(raw, Mapping):
            raise Q1RCausalityError("Q1R snapshot entry is malformed")
        case_id = _required_text(raw, "case_id")
        digest = _required_digest(raw, "evidence_snapshot_digest")
        snapshot = raw.get("evidence_snapshot")
        if snapshot is None or canonical_sha256(snapshot) != digest:
            raise Q1RCausalityError("Q1R Evidence snapshot digest is invalid")
        if case_id in snapshot_by_case:
            raise Q1RCausalityError("Q1R case has multiple Evidence snapshots")
        snapshot_by_case[case_id] = digest
    if set(snapshot_by_case) != set(case_ids):
        raise Q1RCausalityError("Q1R Evidence snapshot denominator drifted")

    indexed: dict[tuple[str, int, str], dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise Q1RCausalityError("Q1R context record is malformed")
        record = dict(raw)
        case_id = _required_text(record, "case_id")
        budget = _required_positive_int(record, "token_budget")
        policy = _required_text(record, "policy")
        key = (case_id, budget, policy)
        if key not in expected_cells or key in indexed:
            raise Q1RCausalityError("Q1R context cell denominator drifted")
        if record.get("evidence_snapshot_digest") != snapshot_by_case.get(case_id):
            raise Q1RCausalityError("Q1R policy arms do not share the sealed snapshot")
        context = _required_text(record, "context")
        identity = record.get("context_identity")
        if not isinstance(identity, Mapping):
            raise Q1RCausalityError("Q1R context identity is missing")
        reader_digest = _required_digest(identity, "reader_context_digest")
        _required_digest(identity, "semantic_context_digest")
        if hashlib.sha256(context.encode("utf-8")).hexdigest() != reader_digest:
            raise Q1RCausalityError("Q1R exact Reader Context digest drifted")
        if record.get("context_sha256") != reader_digest:
            raise Q1RCausalityError("Q1R archived context digest disagrees with Runtime")
        mapping = identity.get("receipt_mapping")
        if not isinstance(mapping, list) or not mapping:
            raise Q1RCausalityError("Q1R true-ID to alias receipt mapping is missing")
        if _OPAQUE_UUID.search(context) or _OPAQUE_SHA256.search(context):
            raise Q1RCausalityError("Q1R Reader Context exposes an opaque identity")
        if any(value in context for value in _receipt_opaque_values(mapping)):
            raise Q1RCausalityError("Q1R Reader Context exposes mapped true provenance")
        mediators = record.get("semantic_mediators")
        if not isinstance(mediators, Mapping):
            raise Q1RCausalityError("Q1R semantic mediator receipt is missing")
        if record.get("semantic_mediator_digest") != canonical_sha256(mediators):
            raise Q1RCausalityError("Q1R semantic mediator digest drifted")
        indexed[key] = record
    if set(indexed) != expected_cells or archive.get("record_count") != len(expected_cells):
        raise Q1RCausalityError("Q1R context record denominator is incomplete")
    return [indexed[key] for key in sorted(indexed)]


def build_generation_schedule(
    records: Sequence[Mapping[str, Any]],
    *,
    case_ids: Sequence[str],
    budgets: Sequence[int] = EXPECTED_BUDGETS,
    planned_window_id: str,
) -> list[dict[str, Any]]:
    """Create a balanced, adjacent-arm schedule for one planned run window."""

    if not planned_window_id:
        raise Q1RCausalityError("Q1R planned run window ID is required")
    indexed = {
        (str(row["case_id"]), int(row["token_budget"]), str(row["policy"])): row
        for row in records
    }
    schedule: list[dict[str, Any]] = []
    for case_ordinal, case_id in enumerate(case_ids):
        for budget_ordinal, budget in enumerate(budgets):
            order = list(POLICIES)
            if (case_ordinal + budget_ordinal) % 2:
                order.reverse()
            for policy in order:
                key = (case_id, int(budget), policy)
                if key not in indexed:
                    raise Q1RCausalityError("Q1R schedule input is incomplete")
                schedule.append(
                    {
                        "ordinal": len(schedule),
                        "planned_window_id": planned_window_id,
                        "case_id": case_id,
                        "token_budget": int(budget),
                        "policy": policy,
                    }
                )
    return schedule


def audit_generation_pairs(
    generations: Sequence[Mapping[str, Any]],
    *,
    questions: Mapping[str, tuple[str, str]],
    budgets: Sequence[int] = EXPECTED_BUDGETS,
) -> list[dict[str, Any]]:
    """Audit prompt identity, fresh calls, and allowlisted policy mediators."""

    indexed = {
        (str(row.get("case_id")), int(row.get("token_budget", -1)), str(row.get("policy"))): row
        for row in generations
    }
    expected = {
        (case_id, int(budget), policy)
        for case_id in questions
        for budget in budgets
        for policy in POLICIES
    }
    if len(generations) != len(expected) or set(indexed) != expected:
        raise Q1RCausalityError("Q1R generation denominator drifted")

    audited: list[dict[str, Any]] = []
    native_request_ids: set[str] = set()
    for case_id in questions:
        question, question_as_of = questions[case_id]
        for budget in budgets:
            arms = [indexed[(case_id, int(budget), policy)] for policy in POLICIES]
            for arm in arms:
                provider = arm.get("provider")
                if not isinstance(provider, Mapping):
                    raise Q1RCausalityError("Q1R Provider receipt is missing")
                _validate_fresh_provider_call(
                    arm,
                    provider,
                    question=question,
                    question_as_of=question_as_of,
                    native_request_ids=native_request_ids,
                )
            audited.append(_audit_pair(arms[0], arms[1]))
    return audited


def _audit_pair(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    case_id = str(left["case_id"])
    budget = int(left["token_budget"])
    left_provider = _mapping(left, "provider")
    right_provider = _mapping(right, "provider")
    invariant_failures: list[str] = []
    if left.get("evidence_snapshot_digest") != right.get("evidence_snapshot_digest"):
        invariant_failures.append("EVIDENCE_SNAPSHOT_DIFF")
    if left.get("planned_window_id") != right.get("planned_window_id"):
        invariant_failures.append("PLANNED_WINDOW_DIFF")
    if abs(int(left.get("call_ordinal", -100)) - int(right.get("call_ordinal", 100))) != 1:
        invariant_failures.append("ARMS_NOT_ADJACENT")
    for field in ("seed", "generation_contract_sha256", "prompt_contract_sha256"):
        if left_provider.get(field) != right_provider.get(field):
            invariant_failures.append(f"{field.upper()}_DIFF")

    left_mediators = _mapping(left, "semantic_mediators")
    right_mediators = _mapping(right, "semantic_mediators")
    mediator_diff_paths = _diff_paths(left_mediators, right_mediators)
    unexplained = sorted(
        path
        for path in mediator_diff_paths
        if path.split(".", 1)[0].split("[", 1)[0] not in _ALLOWED_MEDIATOR_ROOTS
    )
    left_identity = _mapping(left, "context_identity")
    right_identity = _mapping(right, "context_identity")
    semantic_equal = (
        left_identity.get("semantic_context_digest")
        == right_identity.get("semantic_context_digest")
    )
    context_equal = left.get("context") == right.get("context")
    prompt_equal = left_provider.get("prompt_sha256") == right_provider.get("prompt_sha256")
    if not mediator_diff_paths and not semantic_equal:
        invariant_failures.append("UNEXPLAINED_SEMANTIC_DIGEST_DIFF")
    if not mediator_diff_paths and not context_equal:
        invariant_failures.append("UNEXPLAINED_READER_CONTEXT_DIFF")
    if context_equal != prompt_equal:
        invariant_failures.append("PROMPT_CONTEXT_IDENTITY_MISMATCH")
    if mediator_diff_paths and semantic_equal:
        invariant_failures.append("SEMANTIC_DIGEST_OMITS_MEDIATOR_DIFF")
    if unexplained:
        invariant_failures.append("NON_ALLOWLISTED_MEDIATOR_DIFF")
    causally_valid = not invariant_failures
    return {
        "case_id": case_id,
        "token_budget": budget,
        "evidence_snapshot_digest": left.get("evidence_snapshot_digest"),
        "semantic_context_equal": semantic_equal,
        "reader_context_equal": context_equal,
        "exact_prompt_equal": prompt_equal,
        "answer_equal": left.get("answer") == right.get("answer"),
        "mediator_diff_paths": mediator_diff_paths,
        "unexplained_mediator_diff_paths": unexplained,
        "invariant_failures": invariant_failures,
        "quality_attribution": (
            "CAUSALLY_VALID"
            if causally_valid
            else "CONFOUNDED / EXCLUDED FROM CAUSAL CLAIM"
        ),
    }


def planned_stability_diagnostics(
    generations: Sequence[Mapping[str, Any]],
    pair_audits: Sequence[Mapping[str, Any]],
    *,
    previously_correct_2048: frozenset[str],
) -> list[dict[str, Any]]:
    """Predeclare frozen prompts that require three diagnostic repeats."""

    indexed = {
        (str(row["case_id"]), int(row["token_budget"]), str(row["policy"])): row
        for row in generations
    }
    requested: dict[tuple[str, int, str], dict[str, set[str]]] = {}

    def request(key: tuple[str, int, str], reason: str) -> None:
        row = indexed[key]
        prompt_digest = str(_mapping(row, "provider").get("prompt_sha256"))
        prompt_key = (key[0], key[1], prompt_digest)
        entry = requested.setdefault(
            prompt_key, {"policies": set(), "reasons": set()}
        )
        entry["policies"].add(key[2])
        entry["reasons"].add(reason)

    for audit in pair_audits:
        case_id = str(audit["case_id"])
        budget = int(audit["token_budget"])
        if audit.get("semantic_context_equal") is True and audit.get("answer_equal") is False:
            for policy in POLICIES:
                request(
                    (case_id, budget, policy),
                    "SEMANTICALLY_EQUIVALENT_CONTEXT_ANSWER_FLIP",
                )
    for key, row in indexed.items():
        case_id, budget, policy = key
        score = row.get("answer_score")
        if (
            policy == "DG17_QUERY_SPECIFIC_STOP"
            and budget == 2048
            and case_id in previously_correct_2048
            and isinstance(score, Mapping)
            and score.get("exact_match") == 0
        ):
            request(key, "PREVIOUSLY_CORRECT_REGRESSION")
    return [
        {
            "case_id": key[0],
            "token_budget": key[1],
            "policies": sorted(entry["policies"]),
            "prompt_sha256": key[2],
            "trigger_reasons": sorted(entry["reasons"]),
            "frozen_prompt": True,
            "independent_repeats_planned": 3,
            "automatic_retry": False,
            "primary_result_replacement_allowed": False,
        }
        for key, entry in sorted(requested.items())
    ]


def _validate_fresh_provider_call(
    arm: Mapping[str, Any],
    provider: Mapping[str, Any],
    *,
    question: str,
    question_as_of: str,
    native_request_ids: set[str],
) -> None:
    if arm.get("generation_source") != "FRESH_PROVIDER_CALL":
        raise Q1RCausalityError("Q1R historical answer reuse is forbidden")
    if provider.get("provider_calls") != 1 or arm.get("automatic_retries") != 0:
        raise Q1RCausalityError("Q1R main cell must have exactly one Provider call")
    if provider.get("context_truncated") is not False:
        raise Q1RCausalityError("Q1R Provider changed the frozen Runtime Context")
    identity = _mapping(arm, "context_identity")
    if provider.get("context_sha256") != identity.get("reader_context_digest"):
        raise Q1RCausalityError("Q1R Provider Context bytes differ from Runtime bytes")
    expected_prompt = hashlib.sha256(
        serialized_prompt(
            question=question,
            question_as_of=question_as_of,
            memory_context=str(arm["context"]),
        ).encode("utf-8")
    ).hexdigest()
    if provider.get("prompt_sha256") != expected_prompt:
        raise Q1RCausalityError("Q1R exact serialized prompt digest drifted")
    if provider.get("prompt_contract_sha256") != prompt_contract_sha256():
        raise Q1RCausalityError("Q1R prompt contract identity drifted")
    if provider.get("generation_contract_sha256") != full_provider_contract_sha256():
        raise Q1RCausalityError("Q1R generation contract identity drifted")
    native_id = _required_text(provider, "native_request_id")
    if native_id in native_request_ids:
        raise Q1RCausalityError("Q1R Provider native request ID was reused")
    native_request_ids.add(native_id)


def _diff_paths(left: object, right: object, prefix: str = "") -> list[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        paths: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{prefix}[{index}]"
            if index >= len(left) or index >= len(right):
                paths.append(child)
            else:
                paths.extend(_diff_paths(left[index], right[index], child))
        return paths
    return [] if left == right else [prefix or "$"]


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, Mapping):
        raise Q1RCausalityError(f"Q1R {key} receipt is missing")
    return raw


def _receipt_opaque_values(mapping: Sequence[object]) -> set[str]:
    values: set[str] = set()
    for raw in mapping:
        if not isinstance(raw, Mapping):
            raise Q1RCausalityError("Q1R receipt mapping entry is malformed")
        for key in ("evidence_ids", "source_turn_refs", "claim_versions"):
            entries = raw.get(key)
            if not isinstance(entries, list):
                raise Q1RCausalityError("Q1R receipt mapping provenance is malformed")
            values.update(value for value in entries if isinstance(value, str) and value)
        issue_revisions = raw.get("issue_revisions")
        if not isinstance(issue_revisions, list):
            raise Q1RCausalityError("Q1R receipt issue mapping is malformed")
        for revision in issue_revisions:
            if not isinstance(revision, Mapping):
                raise Q1RCausalityError("Q1R receipt issue revision is malformed")
            issue_id = revision.get("issue_id")
            if isinstance(issue_id, str) and issue_id:
                values.add(issue_id)
    return values


def _required_text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise Q1RCausalityError(f"Q1R {key} must be a non-empty string")
    return raw


def _required_digest(value: Mapping[str, Any], key: str) -> str:
    raw = _required_text(value, key)
    if len(raw) != 64 or any(character not in _HEX64 for character in raw):
        raise Q1RCausalityError(f"Q1R {key} must be a lowercase SHA-256 digest")
    return raw


def _required_positive_int(value: Mapping[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        raise Q1RCausalityError(f"Q1R {key} must be a positive integer")
    return raw
