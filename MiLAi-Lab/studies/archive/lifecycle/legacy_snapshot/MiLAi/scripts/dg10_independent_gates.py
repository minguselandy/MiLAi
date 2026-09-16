from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation


class IndependentGateError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise IndependentGateError(reason)


def validate_tier2_human_audit(
    *,
    annotations: Sequence[Mapping[str, Any]],
    adjudication: Mapping[str, Any] | None,
    blind_package_sha256: str,
) -> dict[str, Any]:
    remediation._require_sha256(blind_package_sha256, "Tier 2 blind package")
    _require(len(annotations) == 2, "Tier 2 requires exactly two primary annotators")
    annotators = [item.get("annotator_id_hash") for item in annotations]
    _require(
        len(set(annotators)) == 2
        and all(isinstance(value, str) and len(value) == 64 for value in annotators),
        "Tier 2 annotators are not distinct and pseudonymous",
    )
    case_sets: list[set[str]] = []
    ratings: list[Mapping[str, Any]] = []
    for item in annotations:
        _require(item.get("evidence_class") == "HUMAN", "Tier 2 evidence is not human")
        _require(item.get("independent") is True, "Tier 2 annotator is not independent")
        _require(item.get("blind_package_sha256") == blind_package_sha256, "Tier 2 package mismatch")
        _require(item.get("arm_labels_visible") is False, "Tier 2 arm labels were visible")
        _require(item.get("model_judge_used") is False, "Tier 2 used a model judge")
        values = item.get("ratings")
        _require(isinstance(values, Mapping) and values, "Tier 2 ratings are absent")
        _require(all(isinstance(case_id, str) and case_id for case_id in values), "invalid Tier 2 case ID")
        case_sets.append(set(values))
        ratings.append(values)
    _require(case_sets[0] == case_sets[1], "Tier 2 annotator case coverage differs")
    conflicts = sorted(case_id for case_id in case_sets[0] if ratings[0][case_id] != ratings[1][case_id])
    adjudicated = 0
    if conflicts:
        _require(adjudication is not None, "Tier 2 conflicts require a third adjudicator")
        _require(adjudication.get("evidence_class") == "HUMAN", "adjudicator evidence is not human")
        adjudicator = adjudication.get("annotator_id_hash")
        _require(
            isinstance(adjudicator, str)
            and len(adjudicator) == 64
            and adjudicator not in set(annotators),
            "Tier 2 adjudicator is not a distinct third human",
        )
        resolutions = adjudication.get("resolutions")
        _require(isinstance(resolutions, Mapping), "Tier 2 adjudication resolutions are absent")
        _require(set(resolutions) == set(conflicts), "Tier 2 conflict adjudication coverage differs")
        adjudicated = len(resolutions)
    elif adjudication is not None:
        _require(not adjudication.get("resolutions"), "unexpected Tier 2 adjudication")
    return {
        "schema": "milai.dg10.tier2-human-audit.v1",
        "candidate_id": remediation.CANDIDATE,
        "status": "HUMAN_AUDIT_COMPLETE",
        "primary_annotator_count": 2,
        "case_count": len(case_sets[0]),
        "conflict_count": len(conflicts),
        "adjudicated_conflict_count": adjudicated,
        "blind_package_sha256": blind_package_sha256,
        "arm_labels_visible": False,
        "model_judge_used": False,
        "evidence_class": "HUMAN",
        "independent_acceptance": False,
        "audit_complete": True,
    }


def validate_independent_replay(receipt: Mapping[str, Any]) -> None:
    required = {
        "candidate_id",
        "evidence_class",
        "independent_acceptance",
        "bundle_sha256",
        "replay_transcript_sha256",
        "accepted_stages",
        "open_findings",
        "reviewer_role_separated",
    }
    _require(set(receipt) == required, "independent replay receipt key set drift")
    _require(receipt.get("candidate_id") == remediation.CANDIDATE, "cross-candidate independent replay")
    _require(receipt.get("evidence_class") == "INDEPENDENT", "replay is not independent evidence")
    _require(receipt.get("independent_acceptance") is True, "replay did not accept its stages")
    _require(receipt.get("reviewer_role_separated") is True, "reviewer role separation absent")
    remediation._require_sha256(receipt.get("bundle_sha256"), "review bundle")
    remediation._require_sha256(receipt.get("replay_transcript_sha256"), "replay transcript")
    stages = receipt.get("accepted_stages")
    _require(isinstance(stages, list) and set(stages) >= {"DG10-L1", "DG10-L2", "DG10-L3"}, "L1-L3 replay acceptance incomplete")
    findings = receipt.get("open_findings")
    _require(isinstance(findings, list), "independent replay finding list absent")


def _object(path: Path) -> dict[str, Any]:
    _require(
        path.is_file() and not remediation.has_symlink_component(path),
        f"decision artifact missing or unsafe: {path}",
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndependentGateError(f"decision artifact is invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"decision artifact is not an object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    lexical = path.absolute()
    _require(
        lexical.is_relative_to(remediation.ROOT.absolute())
        and not remediation.has_symlink_component(lexical),
        "decision artifact escapes repository or has a symlink component",
    )
    resolved = lexical.resolve()
    _require(
        resolved.is_relative_to(remediation.ROOT.resolve()),
        "decision artifact escapes repository",
    )
    return {
        "path": resolved.relative_to(remediation.ROOT).as_posix(),
        "sha256": remediation.sha256_file(resolved),
    }


def _document_reference(value: object) -> tuple[Path, dict[str, Any]]:
    try:
        target, document = authorization._verify_document_reference(value)
    except authorization.AuthorizationError as exc:
        raise IndependentGateError(str(exc)) from exc
    return target, document


def _verify_evidence(value: object) -> None:
    try:
        authorization._verify_evidence(value)
    except authorization.AuthorizationError as exc:
        raise IndependentGateError(str(exc)) from exc


def _validate_ai_run(reference: object, *, expected_scope: str) -> dict[str, Any]:
    target, value = _document_reference(reference)
    required = {
        "schema",
        "candidate_id",
        "scope",
        "model",
        "reasoning_effort",
        "cli_version",
        "process_exit_code",
        "provider_thread_id",
        "provider_thread_count",
        "turn_completed_count",
        "error_count",
        "output_schema_validation",
        "boundary_validation",
        "decision",
        "open_p0",
        "open_p1",
        "verdict_sha256",
        "raw_evidence_hashes",
        "raw_evidence",
    }
    _require(set(value) == required, "AI run receipt key set drift")
    expected_values = {
        "schema": "milai.dg10.ai-review-run-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "scope": expected_scope,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "process_exit_code": 0,
        "provider_thread_count": 1,
        "turn_completed_count": 1,
        "error_count": 0,
        "output_schema_validation": "PASS",
        "boundary_validation": "PASS",
        "decision": "PASS",
        "open_p0": 0,
        "open_p1": 0,
    }
    for key, expected in expected_values.items():
        _require(value.get(key) == expected, f"AI run invariant drift: {key}")
    _require(isinstance(value.get("cli_version"), str) and value["cli_version"], "AI CLI identity absent")
    _require(
        isinstance(value.get("provider_thread_id"), str) and value["provider_thread_id"],
        "AI provider thread absent",
    )
    remediation._require_sha256(value.get("verdict_sha256"), "AI verdict")
    raw = value.get("raw_evidence_hashes")
    _require(
        isinstance(raw, Mapping)
        and set(raw) == {"prompt", "response_schema", "output", "events", "stderr"},
        "AI raw evidence hash set drift",
    )
    for digest in raw.values():
        remediation._require_sha256(digest, "AI raw evidence")
    raw_evidence = value.get("raw_evidence")
    _require(
        isinstance(raw_evidence, Mapping)
        and set(raw_evidence)
        == {"prompt", "response_schema", "output", "events", "stderr", "process"},
        "AI raw evidence reference set drift",
    )
    raw_paths: dict[str, Path] = {}
    for key, raw_reference in raw_evidence.items():
        raw_path = authorization._verify_reference(raw_reference)
        raw_paths[key] = raw_path
        if key != "process":
            _require(remediation.sha256_file(raw_path) == raw[key], f"AI raw evidence drift: {key}")
    _require(
        remediation.ai_audit_stderr_is_nonfatal(raw_paths["stderr"].read_bytes()),
        "AI raw stderr contains an unclassified error",
    )
    process = _object(raw_paths["process"])
    _require(
        process.get("model") == "gpt-5.6-sol"
        and process.get("scope") == expected_scope
        and process.get("reasoning_effort") == "xhigh"
        and process.get("process_exit_code") == 0
        and process.get("sandbox") == "read-only"
        and process.get("ephemeral") is True
        and process.get("ignore_user_config") is True
        and process.get("ignore_rules") is True,
        "AI raw process provenance drift",
    )
    if expected_scope == "TEST_ACCESS_PRIMARY":
        bundle_root = remediation.ROOT.parent / (
            "evidence/dg10-candidate4-ai-test-access-review"
        )
        audit_root = remediation.ROOT.parent / (
            "evidence/dg10-candidate4-xhigh-ai-test-access-authority-audits"
        )
        attempt_prefix = "candidate.4-test-access-primary-"
    else:
        raise IndependentGateError(
            f"protected execution root is not yet materialized for {expected_scope}"
        )
    bundle_id = process.get("bundle_directory_id")
    attempt_id = process.get("attempt_id")
    _require(
        isinstance(bundle_id, str)
        and bundle_id.startswith("sha256-")
        and isinstance(attempt_id, str)
        and attempt_id.startswith(attempt_prefix),
        "AI protected execution identity drift",
    )
    provenance.validate_execution_attestation(
        process.get("execution_attestation"),
        bundle=(bundle_root / bundle_id).resolve(),
        output=(audit_root / attempt_id / "review-output.json").resolve(),
        materialized_runner=(
            remediation.ROOT / "scripts/run_dg10_candidate4_ai_audit.py"
        ),
        process=process,
    )
    bindings = {
        "prompt_sha256": "prompt",
        "response_schema_sha256": "response_schema",
        "output_sha256": "output",
        "events_sha256": "events",
        "stderr_sha256": "stderr",
    }
    for process_key, evidence_key in bindings.items():
        _require(process.get(process_key) == raw[evidence_key], f"AI process hash drift: {process_key}")
    events: list[dict[str, Any]] = []
    for line in raw_paths["events"].read_bytes().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IndependentGateError("AI raw event stream is invalid JSON") from exc
        _require(isinstance(event, dict), "AI raw event is not an object")
        events.append(event)
    threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    _require(
        threads == [value["provider_thread_id"]]
        and sum(event.get("type") == "turn.completed" for event in events) == 1
        and not any(event.get("type") in {"error", "turn.failed"} for event in events),
        "AI raw provider event provenance drift",
    )
    output = _object(raw_paths["output"])
    final_messages = [
        event["item"]["text"]
        for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    _require(bool(final_messages), "AI raw final event absent")
    try:
        final_output = json.loads(final_messages[-1])
    except json.JSONDecodeError as exc:
        raise IndependentGateError("AI raw final event is not JSON") from exc
    _require(final_output == output, "AI raw final event/output mismatch")
    return {**_reference(target), "thread_id": value["provider_thread_id"], "verdict_sha256": value["verdict_sha256"]}


def validate_ai_test_access_approval(
    receipt_path: Path, *, expected_inputs: Mapping[str, Any]
) -> dict[str, Any]:
    receipt_path = receipt_path.resolve()
    fixed = remediation.ROOT / (
        "docs/reports/DG-10-ai-test-access-approval-candidate.4-2026-08-22.json"
    )
    _require(receipt_path == fixed.resolve(), "AI test-access receipt is not fixed importer output")
    value = _object(receipt_path)
    required = {
        "schema",
        "candidate_id",
        "decision",
        "evidence_class",
        "policy_override_sha256",
        "identity_receipt",
        "open_p0",
        "open_p1",
        "inputs",
        "bundle_receipt",
        "primary_audits",
        "provider_thread_count",
        "semantic_verdict_sha256",
    }
    _require(set(value) == required, "AI test-access receipt key set drift")
    _require(
        value.get("schema") == "milai.dg10.ai-test-access-approval.v2"
        and value.get("candidate_id") == remediation.CANDIDATE
        and value.get("decision") == "APPROVE_ONE_FULL_TEST"
        and value.get("evidence_class") == "AI_INDEPENDENT"
        and value.get("policy_override_sha256")
        == remediation.sha256_file(remediation.AI_POLICY_OVERRIDE)
        and value.get("open_p0") == 0
        and value.get("open_p1") == 0
        and value.get("inputs") == dict(expected_inputs)
        and value.get("provider_thread_count") == 2,
        "AI test-access approval semantic drift",
    )
    identity_reference = value.get("identity_receipt")
    identity_target = authorization._verify_reference(identity_reference)
    _require(
        identity_target == authorization.ACTIVE_IDENTITIES.resolve(),
        "AI test-access active identity path drift",
    )
    authorization._verify_identity_receipt(identity_target)
    _document_reference(value.get("bundle_receipt"))
    audits = value.get("primary_audits")
    _require(isinstance(audits, list) and len(audits) == 2, "AI test-access audit denominator drift")
    runs = [_validate_ai_run(item, expected_scope="TEST_ACCESS_PRIMARY") for item in audits]
    _require(len({run["thread_id"] for run in runs}) == 2, "AI test-access threads are not distinct")
    _require(
        len({run["verdict_sha256"] for run in runs}) == 1
        and value.get("semantic_verdict_sha256") == runs[0]["verdict_sha256"],
        "AI test-access verdict conflict or drift",
    )
    return {"receipt": _reference(receipt_path), "primary_audits": runs}


def consume_ai_test_access_capability(
    receipt_path: Path,
    *,
    expected_inputs: Mapping[str, Any],
    consumption_path: Path,
) -> dict[str, Any]:
    approval = validate_ai_test_access_approval(
        receipt_path,
        expected_inputs=expected_inputs,
    )
    consumption_path = consumption_path.resolve()
    fixed = remediation.ROOT / (
        "docs/reports/DG-10-full-test-access-consumption-candidate.4-2026-08-22.json"
    )
    _require(consumption_path == fixed.resolve(), "full-test consumption path drift")
    receipt = {
        "schema": "milai.dg10.full-test-access-consumption.v1",
        "candidate_id": remediation.CANDIDATE,
        "approval_receipt": approval["receipt"],
        "approved_inputs": dict(expected_inputs),
        "approved_inputs_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"inputs": dict(expected_inputs)})
        ),
        "capability_use_count": 1,
        "remaining_full_test_uses": 0,
        "release_authorized": False,
    }
    try:
        remediation.atomic_write_new(
            consumption_path,
            remediation.encoded_json(receipt),
        )
    except remediation.RemediationError as exc:
        raise IndependentGateError("full-test capability was already consumed") from exc
    return receipt


def validate_tier2_ai_audit(receipt_path: Path) -> dict[str, Any]:
    value = _object(receipt_path.resolve())
    required = {
        "schema",
        "candidate_id",
        "status",
        "evidence_class",
        "policy_override_sha256",
        "blind_package_sha256",
        "primary_audits",
        "adjudication",
    }
    _require(set(value) == required, "Tier 2 AI receipt key set drift")
    _require(value.get("schema") == "milai.dg10.tier2-ai-audit.v1", "Tier 2 AI schema drift")
    _require(value.get("candidate_id") == remediation.CANDIDATE, "Tier 2 AI candidate drift")
    _require(value.get("status") == "AI_AUDIT_COMPLETE", "Tier 2 AI audit incomplete")
    _require(value.get("evidence_class") == "AI_INDEPENDENT", "Tier 2 evidence is not AI-independent")
    policy = remediation.AI_POLICY_OVERRIDE
    _require(policy.is_file(), "AI policy override absent")
    _require(value.get("policy_override_sha256") == remediation.sha256_file(policy), "Tier 2 AI policy drift")
    remediation._require_sha256(value.get("blind_package_sha256"), "Tier 2 blind package")
    primary = value.get("primary_audits")
    _require(isinstance(primary, list) and len(primary) == 2, "Tier 2 requires two primary AI audits")
    runs = [_validate_ai_run(item, expected_scope="TIER2_PRIMARY") for item in primary]
    _require(len({run["thread_id"] for run in runs}) == 2, "Tier 2 AI provider threads are not distinct")
    verdicts_conflict = len({run["verdict_sha256"] for run in runs}) != 1
    adjudication = value.get("adjudication")
    if verdicts_conflict:
        _require(adjudication is not None, "Tier 2 AI conflict requires adjudication")
        adjudicated = _validate_ai_run(adjudication, expected_scope="TIER2_ADJUDICATION")
        _require(
            adjudicated["thread_id"] not in {run["thread_id"] for run in runs},
            "Tier 2 AI adjudicator thread is not distinct",
        )
    else:
        _require(adjudication is None, "unexpected Tier 2 AI adjudication")
    return {
        "receipt": _reference(receipt_path),
        "primary_audit_count": 2,
        "provider_thread_count": 3 if verdicts_conflict else 2,
        "conflict_adjudicated": verdicts_conflict,
        "evidence_class": "AI_INDEPENDENT",
    }


def _validate_machine_gate(reference: object, *, expected_gate_id: str, source_root: str) -> dict[str, str]:
    target, value = _document_reference(reference)
    required = {
        "schema",
        "candidate_id",
        "gate_id",
        "result",
        "source_inventory_sha256",
        "evidence",
    }
    _require(set(value) == required, "machine gate receipt key set drift")
    _require(value.get("schema") == "milai.dg10.machine-gate-receipt.v1", "machine gate schema drift")
    _require(value.get("candidate_id") == remediation.CANDIDATE, "machine gate candidate drift")
    _require(value.get("gate_id") == expected_gate_id, "machine gate ID drift")
    _require(value.get("result") == "PASS", "machine gate did not pass")
    _require(value.get("source_inventory_sha256") == source_root, "machine gate source drift")
    _verify_evidence(value.get("evidence"))
    return _reference(target)


def _validate_replay(reference: object, *, source_root: str) -> dict[str, str]:
    target, value = _document_reference(reference)
    required = {
        "schema",
        "candidate_id",
        "status",
        "evidence_class",
        "accepted_stages",
        "source_inventory_sha256",
        "evidence",
    }
    _require(set(value) == required, "independent replay key set drift")
    _require(value.get("schema") == "milai.dg10.independent-replay.v2", "independent replay schema drift")
    _require(value.get("candidate_id") == remediation.CANDIDATE, "independent replay candidate drift")
    _require(value.get("status") == "PASS", "independent replay failed")
    _require(value.get("evidence_class") in {"DETERMINISTIC", "AI_INDEPENDENT"}, "independent replay evidence drift")
    _require(value.get("accepted_stages") == ["DG10-L1", "DG10-L2", "DG10-L3"], "independent replay stage drift")
    _require(value.get("source_inventory_sha256") == source_root, "independent replay source drift")
    _verify_evidence(value.get("evidence"))
    return _reference(target)


def _validate_claim_validation(reference: object, *, source_root: str) -> dict[str, str]:
    target, value = _document_reference(reference)
    required = {
        "schema",
        "candidate_id",
        "result",
        "aggregate_allowed",
        "source_inventory_sha256",
        "evidence",
    }
    _require(set(value) == required, "claim validation receipt key set drift")
    _require(value.get("schema") == "milai.dg10.claim-validation-receipt.v1", "claim validation schema drift")
    _require(value.get("candidate_id") == remediation.CANDIDATE, "claim validation candidate drift")
    _require(value.get("result") == "PASS" and value.get("aggregate_allowed") is True, "aggregate claim not validated")
    _require(value.get("source_inventory_sha256") == source_root, "claim validation source drift")
    _verify_evidence(value.get("evidence"))
    return _reference(target)


def _decision_digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "decision_payload_sha256"}
    return remediation.sha256_bytes(remediation.encoded_json(payload))


def controlled_decision(*, evidence_index_path: Path) -> dict[str, Any]:
    raise IndependentGateError(
        "RM-16 release is fail-closed until a fixed final importer replays every "
        "stage-specific raw gate and AI receipt"
    )
    index = _object(evidence_index_path.resolve())
    required = {
        "schema",
        "candidate_id",
        "identity_receipt",
        "r_stage_receipts",
        "l_stage_receipts",
        "machine_gate_receipts",
        "tier2_ai_audit",
        "sol_ai_audit",
        "independent_replay",
        "claim_validation",
        "policy_override",
        "r0_r2_aggregate",
    }
    _require(set(index) == required, "controlled decision evidence index key set drift")
    _require(index.get("schema") == "milai.dg10.controlled-decision-evidence-index.v1", "decision index schema drift")
    _require(index.get("candidate_id") == remediation.CANDIDATE, "decision index candidate drift")
    identity_target, _identity_document = _document_reference(index.get("identity_receipt"))
    try:
        identities = authorization._verify_identity_receipt(identity_target)
    except authorization.AuthorizationError as exc:
        raise IndependentGateError(str(exc)) from exc
    policy_target, _policy = _document_reference(index.get("policy_override"))
    _require(_reference(policy_target) == identities["policy_override"], "decision policy binding drift")
    aggregate_target, _aggregate_document = _document_reference(index.get("r0_r2_aggregate"))
    try:
        r0_r2_aggregate = authorization._verify_r0_r2_aggregate(
            aggregate_target, identities
        )
    except authorization.AuthorizationError as exc:
        raise IndependentGateError(str(exc)) from exc

    r_expected = [f"DG10-R{index}" for index in range(9)]
    l_expected = [f"DG10-L{index}" for index in range(1, 6)]
    normalized_stages: dict[str, list[dict[str, Any]]] = {}
    for key, expected in (("r_stage_receipts", r_expected), ("l_stage_receipts", l_expected)):
        references = index.get(key)
        _require(isinstance(references, list) and len(references) == len(expected), f"{key} denominator drift")
        by_stage: dict[str, Path] = {}
        for reference in references:
            target, document = _document_reference(reference)
            stage = document.get("stage_id")
            _require(isinstance(stage, str) and stage not in by_stage, f"{key} stage duplicated")
            by_stage[stage] = target
        _require(set(by_stage) == set(expected), f"{key} stage set drift")
        normalized_stages[key] = [
            authorization._verify_stage_receipt(by_stage[stage], expected_stage=stage, identities=identities)
            for stage in expected
        ]
    _require(
        normalized_stages["r_stage_receipts"][:3]
        == r0_r2_aggregate["stage_receipts"],
        "release R0-R2 stages are not from the fixed AI importer aggregate",
    )

    expected_machine = {"QUALITY", "BFCL", "SERVING", "SECURITY", "LEDGER"}
    machine = index.get("machine_gate_receipts")
    _require(isinstance(machine, list) and len(machine) == len(expected_machine), "machine gate denominator drift")
    machine_by_id: dict[str, object] = {}
    for item in machine:
        _require(isinstance(item, Mapping) and set(item) == {"gate_id", "receipt"}, "machine gate index drift")
        gate_id = item.get("gate_id")
        _require(isinstance(gate_id, str) and gate_id not in machine_by_id, "machine gate ID duplicated")
        machine_by_id[gate_id] = item.get("receipt")
    _require(set(machine_by_id) == expected_machine, "machine gate set drift")
    normalized_machine = {
        gate: _validate_machine_gate(
            machine_by_id[gate],
            expected_gate_id=gate,
            source_root=identities["source_inventory_sha256"],
        )
        for gate in sorted(expected_machine)
    }
    tier2_target, _tier2 = _document_reference(index.get("tier2_ai_audit"))
    tier2 = validate_tier2_ai_audit(tier2_target)
    sol = _validate_ai_run(index.get("sol_ai_audit"), expected_scope="FINAL_SEMANTIC_AUDIT")
    replay = _validate_replay(
        index.get("independent_replay"), source_root=identities["source_inventory_sha256"]
    )
    claim = _validate_claim_validation(
        index.get("claim_validation"), source_root=identities["source_inventory_sha256"]
    )
    checks = {
        "r0_r8_artifact_bound_accepted": True,
        "l1_l5_artifact_bound_accepted": True,
        "machine_gates_artifact_bound_pass": True,
        "tier2_ai_replacement_complete": True,
        "sol_open_p0_p1_zero": True,
        "independent_replay_pass": True,
        "claim_validator_pass": True,
    }
    result: dict[str, Any] = {
        "schema": "milai.dg10.remediation-controlled-decision.v2",
        "candidate_id": remediation.CANDIDATE,
        "evidence_index": _reference(evidence_index_path),
        "identity_receipt": identities["receipt"],
        "r0_r2_aggregate": r0_r2_aggregate["receipt"],
        "stage_receipts": normalized_stages,
        "machine_gate_receipts": normalized_machine,
        "tier2_ai_audit": tier2,
        "sol_ai_audit": sol,
        "independent_replay": replay,
        "claim_validation": claim,
        "result": "PASS",
        "checks": checks,
        "release_authorized": True,
        "full_test_result_may_be_claimed": True,
        "external_provider_beta_allowed": False,
        "production_ready_allowed": False,
        "schema_frozen_allowed": False,
        "independent_acceptance": True,
    }
    result["decision_payload_sha256"] = _decision_digest(result)
    return result


def authorize_release(decision: Mapping[str, Any]) -> None:
    raise IndependentGateError(
        "RM-16 release is disabled for the current candidate.4 author state"
    )
    required = {
        "schema",
        "candidate_id",
        "evidence_index",
        "identity_receipt",
        "r0_r2_aggregate",
        "stage_receipts",
        "machine_gate_receipts",
        "tier2_ai_audit",
        "sol_ai_audit",
        "independent_replay",
        "claim_validation",
        "result",
        "checks",
        "release_authorized",
        "full_test_result_may_be_claimed",
        "external_provider_beta_allowed",
        "production_ready_allowed",
        "schema_frozen_allowed",
        "independent_acceptance",
        "decision_payload_sha256",
    }
    _require(set(decision) == required, "controlled decision key set drift")
    _require(decision.get("decision_payload_sha256") == _decision_digest(decision), "controlled decision digest drift")
    reference = decision.get("evidence_index")
    target, _index = _document_reference(reference)
    recomputed = controlled_decision(evidence_index_path=target)
    _require(dict(decision) == recomputed, "controlled decision does not match bound artifacts")
    _require(
        decision.get("schema") == "milai.dg10.remediation-controlled-decision.v2"
        and decision.get("candidate_id") == remediation.CANDIDATE
        and decision.get("result") == "PASS"
        and decision.get("release_authorized") is True
        and decision.get("independent_acceptance") is True,
        "RM-16 release/rollback is not authorized",
    )
