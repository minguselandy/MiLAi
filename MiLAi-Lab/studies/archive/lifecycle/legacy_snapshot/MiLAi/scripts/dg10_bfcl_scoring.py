from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation

CASE_COUNT = 216
MULTI_TURN_COUNT = 80
SUPPORTED_SINGLE_TURN_COUNT = 122
IRRELEVANCE_NO_CALL_COUNT = 24
MAX_STEPS = 20
THRESHOLDS = {
    "overall_accuracy": 0.80,
    "supported_single_turn_accuracy": 0.85,
    "multi_turn_accuracy": 0.50,
    "irrelevance_no_call_accuracy": 0.80,
}
FOCUSED_CASES = frozenset(
    {
        "no_call_irrelevant_function",
        "missing_function",
        "missing_parameter",
        "parallel_and_parallel_multiple",
        "long_context_compaction",
        "repeated_identical_call",
        "two_state_and_three_state_cycle",
        "tool_result_oversize",
        "step_19_success_step_20_fail",
        "javascript_and_java_dependency_closure",
    }
)
ACTIVE_CASE_MANIFEST = remediation.ROOT / (
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.15-2026-08-22.json"
)
# Tests may override this value. Production resolves the digest from the active,
# fully verified candidate source inventory, avoiding a code/manifest hash cycle.
ACTIVE_CASE_MANIFEST_SHA256: str | None = None
ACTIVE_ACCEPTANCE_CONTRACT = remediation.ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.18.json"
)
ACTIVE_EXECUTION_IDENTITY = remediation.ROOT / (
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.13-2026-08-22.json"
)
ACTIVE_BFCL_ATTEMPT_LEDGER = remediation.ROOT / (
    "var/dg10/bfcl-candidate.4/attempts.jsonl"
)


class BfclScoringError(remediation.RemediationError):
    pass


@dataclass(frozen=True, slots=True)
class BfclCase:
    case_id: str
    attempt_id: str
    ledger_attempt_ids: tuple[str, ...]
    category: str
    passed: bool
    terminal: bool
    steps: int
    candidate_id: str
    worker_environment_sha256: str
    adapter_sha256: str
    ledger_sha256: str
    language: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise BfclScoringError(reason)


def capability_gate(
    *,
    native_protocol_supported: bool,
    native_probe_terminal: bool,
    native_probe_tool_calls_valid: bool,
    adapted_protocol_frozen: bool,
) -> dict[str, Any]:
    _require(
        all(
            isinstance(value, bool)
            for value in (
                native_protocol_supported,
                native_probe_terminal,
                native_probe_tool_calls_valid,
                adapted_protocol_frozen,
            )
        ),
        "BFCL capability inputs must be boolean",
    )
    if native_protocol_supported:
        passed = native_probe_terminal and native_probe_tool_calls_valid
        mode = "NATIVE_DEDICATED_INSTANCE" if passed else "NATIVE_PROBE_FAILED"
    else:
        passed = adapted_protocol_frozen
        mode = "ADAPTED_LOCAL_NON_LIVE" if passed else "CAPABILITY_GATE_FAILED"
    return {
        "schema": "milai.dg10.bfcl-capability.v1",
        "candidate_id": remediation.CANDIDATE,
        "gate_pass": passed,
        "execution_mode": mode,
        "native_protocol_supported": native_protocol_supported,
        "native_probe_terminal": native_probe_terminal,
        "native_probe_tool_calls_valid": native_probe_tool_calls_valid,
        "adapted_protocol_frozen": adapted_protocol_frozen,
        "official_leaderboard_claim_allowed": native_protocol_supported and passed,
        "adapted_result_must_be_labeled": not native_protocol_supported,
        "independent_acceptance": False,
    }


def validate_focused_results(results: Mapping[str, bool]) -> dict[str, Any]:
    _require(set(results) == FOCUSED_CASES, "BFCL focused case set drift")
    _require(
        all(isinstance(passed, bool) for passed in results.values()),
        "BFCL focused result is not boolean",
    )
    failures = sorted(name for name, passed in results.items() if passed is not True)
    return {
        "schema": "milai.dg10.bfcl-focused-gate.v1",
        "candidate_id": remediation.CANDIDATE,
        "case_count": len(results),
        "results": dict(sorted(results.items())),
        "failures": failures,
        "gate_pass": not failures,
    }


def _validated_capability(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "candidate_id",
        "gate_pass",
        "execution_mode",
        "native_protocol_supported",
        "native_probe_terminal",
        "native_probe_tool_calls_valid",
        "adapted_protocol_frozen",
        "official_leaderboard_claim_allowed",
        "adapted_result_must_be_labeled",
        "independent_acceptance",
    }
    _require(set(value) == required, "BFCL capability receipt key set drift")
    expected = capability_gate(
        native_protocol_supported=value.get("native_protocol_supported"),
        native_probe_terminal=value.get("native_probe_terminal"),
        native_probe_tool_calls_valid=value.get("native_probe_tool_calls_valid"),
        adapted_protocol_frozen=value.get("adapted_protocol_frozen"),
    )
    _require(dict(value) == expected, "BFCL capability receipt semantics drift")
    return expected


def _validated_focused(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "candidate_id",
        "case_count",
        "results",
        "failures",
        "gate_pass",
    }
    _require(set(value) == required, "BFCL focused receipt key set drift")
    results = value.get("results")
    _require(isinstance(results, Mapping), "BFCL focused results are absent")
    expected = validate_focused_results(results)
    _require(dict(value) == expected, "BFCL focused receipt semantics drift")
    return expected


def _accuracy(rows: Sequence[BfclCase]) -> float:
    _require(bool(rows), "BFCL metric denominator is empty")
    return sum(row.passed for row in rows) / len(rows)


def _aware_datetime(value: object, *, label: str) -> datetime:
    _require(isinstance(value, str) and value, f"{label} is absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BfclScoringError(f"{label} is invalid") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{label} lacks timezone")
    return parsed


def _material_reference(value: object, *, label: str) -> Path:
    _require(
        isinstance(value, Mapping) and set(value) == {"path", "sha256", "size"},
        f"{label} reference drift",
    )
    relative = value.get("path")
    _require(isinstance(relative, str) and relative, f"{label} path absent")
    parsed = PurePosixPath(relative)
    _require(not parsed.is_absolute() and ".." not in parsed.parts, f"{label} path unsafe")
    lexical = (remediation.ROOT / parsed).absolute()
    _require(
        not remediation.has_symlink_component(lexical),
        f"{label} path has a symlink component",
    )
    target = lexical.resolve()
    _require(
        target.is_relative_to(remediation.ROOT.resolve()) and target.is_file(),
        f"{label} missing or unsafe",
    )
    remediation._require_sha256(value.get("sha256"), label)
    _require(
        remediation.sha256_file(target) == value.get("sha256")
        and target.stat().st_size == value.get("size"),
        f"{label} bytes drift",
    )
    return target


def _source_pinned_manifest_sha256() -> str:
    if ACTIVE_CASE_MANIFEST_SHA256 is not None:
        remediation._require_sha256(
            ACTIVE_CASE_MANIFEST_SHA256,
            "BFCL active case manifest",
        )
        return ACTIVE_CASE_MANIFEST_SHA256
    try:
        identities = authorization._verify_identity_receipt(
            authorization.ACTIVE_IDENTITIES
        )
        source_reference = identities["source_inventory"]
        source_path = authorization._verify_reference(source_reference)
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (authorization.AuthorizationError, OSError, json.JSONDecodeError) as exc:
        raise BfclScoringError(
            "BFCL active source identity cannot pin the case manifest"
        ) from exc
    entries = source.get("entries") if isinstance(source, Mapping) else None
    _require(isinstance(entries, list), "BFCL source inventory entries absent")
    relative = ACTIVE_CASE_MANIFEST.absolute().relative_to(
        remediation.ROOT.absolute()
    ).as_posix()
    matches = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("path") == relative
    ]
    _require(len(matches) == 1, "BFCL case manifest is not source-inventory pinned")
    digest = matches[0].get("sha256")
    remediation._require_sha256(digest, "BFCL active case manifest")
    return str(digest)


def _execution_identity(
    reference: object, *, manifest_frozen_at: datetime
) -> dict[str, Any]:
    _require(
        isinstance(reference, Mapping) and set(reference) == {"path", "sha256"},
        "BFCL execution identity reference drift",
    )
    relative = reference.get("path")
    _require(isinstance(relative, str) and relative, "BFCL execution identity path absent")
    parsed = PurePosixPath(relative)
    _require(not parsed.is_absolute() and ".." not in parsed.parts, "BFCL execution identity path unsafe")
    lexical = (remediation.ROOT / parsed).absolute()
    _require(
        not remediation.has_symlink_component(lexical),
        "BFCL execution identity path has a symlink component",
    )
    target = lexical.resolve()
    _require(
        target == ACTIVE_EXECUTION_IDENTITY.resolve()
        and target.is_file()
        and not remediation.has_symlink_component(ACTIVE_EXECUTION_IDENTITY),
        "BFCL execution identity is not the fixed preregistration",
    )
    remediation._require_sha256(reference.get("sha256"), "BFCL execution identity")
    _require(
        remediation.sha256_file(target) == reference.get("sha256"),
        "BFCL execution identity hash drift",
    )
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclScoringError("BFCL execution identity is invalid") from exc
    required = {
        "schema",
        "candidate_id",
        "frozen_at",
        "worker_closure",
        "worker_environment",
        "adapter",
        "upstream_bfcl",
        "attempt_ledger",
        "raw_receipt_root",
        "per_case_identity_fields",
        "result_access_before_freeze_allowed",
    }
    _require(isinstance(value, Mapping) and set(value) == required, "BFCL execution identity key set drift")
    _require(value.get("schema") == "milai.dg10.bfcl-execution-identity.v1", "BFCL execution identity schema drift")
    _require(value.get("candidate_id") == remediation.CANDIDATE, "BFCL execution identity candidate drift")
    identity_frozen_at = _aware_datetime(value.get("frozen_at"), label="BFCL execution identity frozen_at")
    _require(identity_frozen_at < manifest_frozen_at, "BFCL execution identity was not frozen before the case manifest")
    worker_closure_path = _material_reference(
        value.get("worker_closure"), label="BFCL worker closure"
    )
    try:
        worker_closure = json.loads(worker_closure_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclScoringError("BFCL worker closure is invalid") from exc
    closure_required = {
        "schema",
        "candidate_id",
        "frozen_at",
        "coherent_r2_closure",
        "environment",
        "adapter",
        "verification",
        "upstream_bfcl",
    }
    _require(
        isinstance(worker_closure, Mapping)
        and set(worker_closure) == closure_required
        and worker_closure.get("schema") == "milai.dg10.bfcl-worker-closure.v1"
        and worker_closure.get("candidate_id") == remediation.CANDIDATE,
        "BFCL worker closure schema drift",
    )
    closure_frozen_at = _aware_datetime(
        worker_closure.get("frozen_at"), label="BFCL worker closure frozen_at"
    )
    _require(
        closure_frozen_at < identity_frozen_at,
        "BFCL worker closure was not frozen before the execution identity",
    )
    _material_reference(
        worker_closure.get("coherent_r2_closure"),
        label="BFCL coherent R2 closure",
    )
    identities: dict[str, str] = {}
    for name in ("worker_environment", "adapter"):
        descriptor = value.get(name)
        _require(
            isinstance(descriptor, Mapping)
            and set(descriptor) == {"identity_sha256", "materials"},
            f"BFCL {name} identity drift",
        )
        materials = descriptor.get("materials")
        _require(isinstance(materials, list) and materials, f"BFCL {name} materials absent")
        for index, item in enumerate(materials):
            _material_reference(item, label=f"BFCL {name} material {index}")
        expected = remediation.sha256_bytes(
            remediation.encoded_json({"materials": materials})
        )
        _require(descriptor.get("identity_sha256") == expected, f"BFCL {name} identity hash drift")
        closure_name = "environment" if name == "worker_environment" else name
        _require(
            worker_closure.get(closure_name) == descriptor,
            f"BFCL {name} differs from the coherent worker closure",
        )
        identities[f"{name}_sha256"] = expected
    upstream = value.get("upstream_bfcl")
    _require(
        isinstance(upstream, Mapping)
        and set(upstream)
        == {"git_head", "tracked_file_count", "canonical_entries_sha256"},
        "BFCL upstream identity drift",
    )
    _require(
        worker_closure.get("upstream_bfcl") == upstream,
        "BFCL upstream differs from the coherent worker closure",
    )
    _require(
        upstream.get("git_head") == "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
        and upstream.get("tracked_file_count") == 192,
        "BFCL upstream denominator drift",
    )
    remediation._require_sha256(upstream.get("canonical_entries_sha256"), "BFCL upstream tree")
    ledger = value.get("attempt_ledger")
    _require(
        isinstance(ledger, Mapping)
        and set(ledger)
        == {"path", "schema", "mode", "append_only", "expected_case_count"},
        "BFCL attempt-ledger identity drift",
    )
    _material_reference(ledger.get("schema"), label="BFCL attempt-ledger schema")
    _require(
        ledger.get("path") == ACTIVE_BFCL_ATTEMPT_LEDGER.relative_to(remediation.ROOT).as_posix()
        and ledger.get("mode") == "0600"
        and ledger.get("append_only") is True
        and ledger.get("expected_case_count") == CASE_COUNT,
        "BFCL attempt-ledger preregistration drift",
    )
    _require(
        value.get("raw_receipt_root") == "var/dg10/bfcl-candidate.4/raw-receipts"
        and value.get("per_case_identity_fields")
        == [
            "candidate_id",
            "ledger_attempt_ids",
            "worker_environment_sha256",
            "adapter_sha256",
            "ledger_sha256",
        ]
        and value.get("result_access_before_freeze_allowed") is False,
        "BFCL per-case execution binding drift",
    )
    return {
        **identities,
        "ledger_path": ACTIVE_BFCL_ATTEMPT_LEDGER.resolve(),
        "worker_closure_path": worker_closure_path,
        "worker_closure_sha256": remediation.sha256_file(worker_closure_path),
    }


def _case_manifest(
    path: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], datetime, dict[str, Any]]:
    lexical = path.absolute()
    _require(
        not remediation.has_symlink_component(lexical),
        "BFCL case manifest path has a symlink component",
    )
    resolved = lexical.resolve()
    _require(resolved == ACTIVE_CASE_MANIFEST.resolve(), "BFCL case manifest path is not preregistered")
    _require(resolved.is_file(), "BFCL case manifest is missing or unsafe")
    active_manifest_sha256 = _source_pinned_manifest_sha256()
    _require(
        remediation.sha256_file(resolved) == active_manifest_sha256,
        "BFCL active case manifest hash drift",
    )
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclScoringError("BFCL case manifest is absent or invalid") from exc
    required = {
        "schema",
        "candidate_id",
        "frozen_at",
        "acceptance_contract",
        "case_count",
        "cases",
        "execution_identity",
        "dependency_closure",
    }
    _require(isinstance(value, Mapping) and set(value) == required, "BFCL case manifest key set drift")
    _require(value.get("schema") == "milai.dg10.bfcl-case-manifest.v2", "BFCL case manifest schema drift")
    _require(value.get("candidate_id") == remediation.CANDIDATE, "BFCL case manifest candidate drift")
    frozen_at = _aware_datetime(value.get("frozen_at"), label="BFCL manifest frozen_at")
    acceptance = value.get("acceptance_contract")
    _require(
        isinstance(acceptance, Mapping) and set(acceptance) == {"path", "sha256"},
        "BFCL acceptance contract reference drift",
    )
    acceptance_path = acceptance.get("path")
    _require(isinstance(acceptance_path, str) and acceptance_path, "BFCL acceptance path absent")
    parsed_acceptance = PurePosixPath(acceptance_path)
    _require(
        not parsed_acceptance.is_absolute() and ".." not in parsed_acceptance.parts,
        "BFCL acceptance path unsafe",
    )
    lexical_acceptance = (remediation.ROOT / parsed_acceptance).absolute()
    _require(
        not remediation.has_symlink_component(lexical_acceptance),
        "BFCL acceptance contract path has a symlink component",
    )
    acceptance_target = lexical_acceptance.resolve()
    _require(
        acceptance_target == ACTIVE_ACCEPTANCE_CONTRACT.resolve()
        and acceptance_target.is_file()
        and not remediation.has_symlink_component(ACTIVE_ACCEPTANCE_CONTRACT),
        "BFCL acceptance contract is not the active frozen contract",
    )
    remediation._require_sha256(acceptance.get("sha256"), "BFCL acceptance contract")
    _require(
        remediation.sha256_file(acceptance_target) == acceptance.get("sha256"),
        "BFCL acceptance contract hash drift",
    )
    cases = value.get("cases")
    _require(isinstance(cases, list) and value.get("case_count") == CASE_COUNT, "BFCL case manifest denominator drift")
    indexed: dict[str, Mapping[str, Any]] = {}
    case_keys = {
        "case_id",
        "supported_single_turn",
        "multi_turn",
        "irrelevance_no_call",
        "language",
    }
    for item in cases:
        _require(isinstance(item, Mapping) and set(item) == case_keys, "BFCL case manifest row drift")
        case_id = item.get("case_id")
        _require(isinstance(case_id, str) and case_id and case_id not in indexed, "BFCL manifest case ID invalid")
        for key in ("supported_single_turn", "multi_turn", "irrelevance_no_call"):
            _require(isinstance(item.get(key), bool), "BFCL manifest category flag invalid")
        _require(item.get("language") in {"python", "javascript", "java"}, "BFCL manifest language invalid")
        indexed[case_id] = item
    _require(len(indexed) == CASE_COUNT, "BFCL manifest case IDs repeat")
    _require(sum(bool(item["multi_turn"]) for item in cases) == MULTI_TURN_COUNT, "BFCL multi-turn denominator must be 80")
    _require(
        sum(bool(item["supported_single_turn"]) for item in cases)
        == SUPPORTED_SINGLE_TURN_COUNT,
        "BFCL supported single-turn denominator must be 122",
    )
    _require(
        sum(bool(item["irrelevance_no_call"]) for item in cases)
        == IRRELEVANCE_NO_CALL_COUNT,
        "BFCL no-call denominator must be 24",
    )
    closure = value.get("dependency_closure")
    _require(
        isinstance(closure, Mapping) and set(closure) == {"python", "javascript", "java"},
        "language dependency closure set drift",
    )
    digests: dict[str, str] = {}
    for language, reference in closure.items():
        _require(
            isinstance(reference, Mapping) and set(reference) == {"path", "sha256"},
            "language dependency reference drift",
        )
        relative = reference.get("path")
        _require(isinstance(relative, str) and relative, "language dependency path absent")
        parsed = PurePosixPath(relative)
        _require(not parsed.is_absolute() and ".." not in parsed.parts, "language dependency path unsafe")
        lexical_dependency = (remediation.ROOT / parsed).absolute()
        _require(
            not remediation.has_symlink_component(lexical_dependency),
            "language dependency path has a symlink component",
        )
        target = lexical_dependency.resolve()
        _require(
            target.is_relative_to(remediation.ROOT.resolve()) and target.is_file(),
            "language dependency file missing or unsafe",
        )
        remediation._require_sha256(reference.get("sha256"), f"{language} dependency closure")
        _require(
            remediation.sha256_file(target) == reference.get("sha256"),
            f"{language} dependency closure hash drift",
        )
        digests[str(language)] = str(reference["sha256"])
    execution_identity = _execution_identity(
        value.get("execution_identity"), manifest_frozen_at=frozen_at
    )
    _require(
        all(
            reference.get("sha256")
            == execution_identity["worker_closure_sha256"]
            and (remediation.ROOT / str(reference.get("path"))).resolve()
            == execution_identity["worker_closure_path"]
            for reference in closure.values()
        ),
        "language dependency closure differs from the coherent worker closure",
    )
    return indexed, digests, frozen_at, execution_identity


def build_homogeneous_dev_gate(
    rows: Sequence[BfclCase],
    *,
    capability: Mapping[str, Any],
    focused: Mapping[str, Any],
    case_manifest_path: Path,
    results_accessed_at: str,
) -> dict[str, Any]:
    manifest, dependency_closure, frozen_at, execution_identity = _case_manifest(
        case_manifest_path.absolute()
    )
    accessed_at = _aware_datetime(results_accessed_at, label="BFCL results_accessed_at")
    _require(accessed_at > frozen_at, "BFCL results were accessed before preregistration freeze")
    capability_receipt = _validated_capability(capability)
    focused_receipt = _validated_focused(focused)
    _require(len(rows) == CASE_COUNT, "BFCL dev denominator must be 216")
    _require(
        all(
            isinstance(row.case_id, str)
            and bool(row.case_id)
            and isinstance(row.attempt_id, str)
            and bool(row.attempt_id)
            and isinstance(row.category, str)
            and bool(row.category)
            and isinstance(row.passed, bool)
            and isinstance(row.terminal, bool)
            and isinstance(row.steps, int)
            and not isinstance(row.steps, bool)
            for row in rows
        ),
        "BFCL case field type drift",
    )
    _require(len({row.case_id for row in rows}) == CASE_COUNT, "BFCL case IDs repeat")
    _require(len({row.attempt_id for row in rows}) == CASE_COUNT, "BFCL attempt IDs repeat")
    _require(all(row.terminal is True for row in rows), "BFCL dev contains non-terminal attempts")
    _require(all(1 <= row.steps <= MAX_STEPS for row in rows), "BFCL step ceiling drift")
    _require(
        all(
            len(row.ledger_attempt_ids) == row.steps
            and len(row.ledger_attempt_ids) == len(set(row.ledger_attempt_ids))
            and all(
                isinstance(attempt_id, str) and bool(attempt_id)
                for attempt_id in row.ledger_attempt_ids
            )
            for row in rows
        ),
        "BFCL model-call ledger binding drift",
    )
    ledger_attempt_ids = [
        attempt_id for row in rows for attempt_id in row.ledger_attempt_ids
    ]
    _require(
        len(ledger_attempt_ids) == len(set(ledger_attempt_ids)),
        "BFCL ledger attempt IDs repeat across cases",
    )
    _require({row.candidate_id for row in rows} == {remediation.CANDIDATE}, "BFCL candidate splice")
    ledger_path = execution_identity["ledger_path"]
    _require(
        ledger_path == ACTIVE_BFCL_ATTEMPT_LEDGER.resolve()
        and ledger_path.is_file()
        and not remediation.has_symlink_component(ACTIVE_BFCL_ATTEMPT_LEDGER),
        "fixed BFCL attempt ledger is absent or unsafe",
    )
    try:
        ledger = remediation.reconcile_attempt_ledger(
            ledger_path, candidate_id=remediation.CANDIDATE
        )
        snapshots = remediation.read_attempt_ledger(ledger_path)
    except remediation.RemediationError as exc:
        raise BfclScoringError(str(exc)) from exc
    final_by_attempt = {item["attempt_id"]: item for item in snapshots}
    expected_model_call_count = sum(row.steps for row in rows)
    _require(
        ledger["complete"] is True
        and ledger["attempt_count"] == expected_model_call_count
        and ledger["known_completed_calls"] == expected_model_call_count
        and ledger["retained_successful_calls"] == expected_model_call_count
        and len(final_by_attempt) == expected_model_call_count,
        "BFCL fixed attempt ledger is incomplete",
    )
    ledger_sha256 = remediation.sha256_file(ledger_path)
    for label, values, expected in (
        (
            "worker environment",
            {row.worker_environment_sha256 for row in rows},
            execution_identity["worker_environment_sha256"],
        ),
        (
            "adapter",
            {row.adapter_sha256 for row in rows},
            execution_identity["adapter_sha256"],
        ),
        ("attempt ledger", {row.ledger_sha256 for row in rows}, ledger_sha256),
    ):
        _require(values == {expected}, f"BFCL {label} differs from frozen execution identity")
    _require(
        set(ledger_attempt_ids) == set(final_by_attempt)
        and all(
            final_by_attempt[attempt_id]["case_id"] == row.case_id
            and final_by_attempt[attempt_id]["phase"] == "BFCL_DEV"
            and final_by_attempt[attempt_id]["arm"]
            == capability_receipt["execution_mode"]
            and final_by_attempt[attempt_id]["attempt_state"] == "FINALIZED"
            and final_by_attempt[attempt_id]["planned_model_calls"] == 1
            and final_by_attempt[attempt_id]["planned_mcp_calls"] == 0
            and len(final_by_attempt[attempt_id]["native_request_ids"]) == 1
            and final_by_attempt[attempt_id]["provider_terminal"] is True
            and final_by_attempt[attempt_id]["agent_terminal"] is True
            and final_by_attempt[attempt_id]["parser_terminal"] is True
            and final_by_attempt[attempt_id]["retention_state"] == "retained"
            and final_by_attempt[attempt_id]["failure_reason_code"] == "SUCCESS"
            for row in rows
            for attempt_id in row.ledger_attempt_ids
        ),
        "BFCL per-case receipt differs from the fixed attempt ledger",
    )
    _require({row.case_id for row in rows} == set(manifest), "BFCL row set differs from frozen manifest")
    _require(
        all(row.language == manifest[row.case_id]["language"] for row in rows),
        "BFCL row language differs from frozen manifest",
    )
    expected_category = {
        case_id: (
            "multi_turn"
            if item["multi_turn"]
            else "irrelevance_no_call"
            if item["irrelevance_no_call"]
            else "supported_single_turn"
        )
        for case_id, item in manifest.items()
    }
    _require(
        all(row.category == expected_category[row.case_id] for row in rows),
        "BFCL row category differs from frozen manifest",
    )
    multi = [row for row in rows if manifest[row.case_id]["multi_turn"]]
    single = [row for row in rows if manifest[row.case_id]["supported_single_turn"]]
    no_call = [row for row in rows if manifest[row.case_id]["irrelevance_no_call"]]
    _require(len(multi) == MULTI_TURN_COUNT, "BFCL multi-turn denominator must be 80")
    metrics = {
        "overall_accuracy": _accuracy(rows),
        "supported_single_turn_accuracy": _accuracy(single),
        "multi_turn_accuracy": _accuracy(multi),
        "irrelevance_no_call_accuracy": _accuracy(no_call),
    }
    threshold_results = {
        name: metrics[name] >= minimum for name, minimum in THRESHOLDS.items()
    }
    _require({row.language for row in rows} <= set(dependency_closure), "unbound BFCL language")
    capability_pass = capability_receipt["gate_pass"] is True
    focused_pass = focused_receipt["gate_pass"] is True
    gate_pass = all(threshold_results.values()) and capability_pass and focused_pass
    return {
        "schema": "milai.dg10.bfcl-homogeneous-dev.v1",
        "candidate_id": remediation.CANDIDATE,
        "stage_id": "DG10-R5",
        "stage_state": "AUTHOR_CANDIDATE" if gate_pass else "REVISE",
        "case_count": len(rows),
        "multi_turn_case_count": len(multi),
        "supported_single_turn_case_count": len(single),
        "irrelevance_no_call_case_count": len(no_call),
        "case_manifest_sha256": remediation.sha256_file(case_manifest_path.resolve()),
        "case_manifest_frozen_at": frozen_at.isoformat(),
        "execution_identity_sha256": remediation.sha256_file(
            ACTIVE_EXECUTION_IDENTITY.resolve()
        ),
        "worker_environment_sha256": execution_identity["worker_environment_sha256"],
        "adapter_sha256": execution_identity["adapter_sha256"],
        "attempt_ledger_sha256": ledger_sha256,
        "attempt_ledger_model_call_count": expected_model_call_count,
        "results_accessed_at": accessed_at.isoformat(),
        "max_steps": MAX_STEPS,
        "homogeneous": True,
        "metrics": metrics,
        "thresholds": dict(THRESHOLDS),
        "threshold_results": threshold_results,
        "capability": capability_receipt,
        "focused": focused_receipt,
        "dependency_closure": dict(dependency_closure),
        "gate_pass": gate_pass,
        "official_leaderboard_claim_allowed": capability_receipt[
            "official_leaderboard_claim_allowed"
        ]
        is True,
        "full_test_authorized": False,
        "independent_acceptance": False,
    }
