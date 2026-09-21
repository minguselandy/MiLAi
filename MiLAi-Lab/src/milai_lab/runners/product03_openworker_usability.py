#!/usr/bin/env python3
"""Black-box Product 03 local OpenWorker usability runner.

The runner imports no MiLAi Product implementation modules.  It uses the
published MCP stdio interface for governed fixture writes and the native
OpenWorker HTTP/CLI surface for answer operations.
"""

# The executable compatibility path remains in ``tools/``.

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters, stdio_client


def _environment(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MILAI_") and "=" in line:
            name, value = line.split("=", 1)
            result[name] = value
    return result


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _command(arguments: list[str], *, timeout: int = 240) -> bytes:
    completed = subprocess.run(  # noqa: S603 - fixed docker argv plus bounded local inputs
        arguments,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {arguments[0]}")
    return completed.stdout


async def _tool_call(
    executable: Path,
    *,
    profile: str,
    token: str,
    base_url: str,
    tool: str,
    arguments: dict[str, Any],
    scope_project: str = "orchid-release",
) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=str(executable),
        args=["--profile", profile, "--max-retries", "0"],
        env={
            "MILAI_BASE_URL": base_url,
            "MILAI_AGENT_TOKEN": token,
            "MILAI_AGENT_SCOPE_JSON": json.dumps(
                {"project_ids": [scope_project]}, separators=(",", ":")
            ),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_AGENT_MAX_LIMIT": "50",
        },
    )
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        result = await client.call_tool(tool, arguments)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError(f"{profile}:{tool} failed")
    return dict(result.structured_content)


async def _create_claim(
    args: argparse.Namespace,
    environment: dict[str, str],
    *,
    label: str,
    subject: str,
    predicate: str,
    claim_type: str,
    value: str,
    scope_project: str,
    speaker: str | None = None,
) -> dict[str, Any]:
    capture = await _tool_call(
        args.mcp_executable,
        profile="submitter",
        token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_evidence_capture",
        arguments={
            "operation_id": f"{args.run_id}-{label}-capture",
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"product03://{_digest(args.run_id)[:16]}/{label}",
            "subject_id": subject,
            "speaker": speaker,
            "observed_at": datetime.now(UTC).isoformat(),
            "content": f"Synthetic {predicate} is {value}",
            "permission_snapshot": {
                "readable": True,
                "scope": "synthetic-product03",
            },
            "confirmation": "CAPTURE",
            "retention_state": "READABLE",
            "data_classification": "SYNTHETIC",
        },
        scope_project=scope_project,
    )
    evidence_id = capture.get("evidence_id")
    if not isinstance(evidence_id, str):
        raise RuntimeError("claim capture did not return evidence identity")
    proposal = await _tool_call(
        args.mcp_executable,
        profile="submitter",
        token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_proposal_create",
        arguments={
            "operation_id": f"{args.run_id}-{label}-proposal",
            "proposal": {
                "operation": "CREATE",
                "supporting_evidence_refs": [evidence_id],
                "requested_authority": "INFORMATIONAL",
                "scope_predicate": {"project_ids": [scope_project]},
                "model_id": "deterministic-product03-fixture",
                "template_version": "v1",
                "input_snapshot_hash": _digest(
                    {
                        "evidence_id": evidence_id,
                        "predicate": predicate,
                        "value": value,
                    }
                ),
                "proposed_patch": {
                    "subject_id": subject,
                    "predicate": predicate,
                    "claim_type": claim_type,
                    "payload": {"state_key": predicate, "value": value},
                    "authority": "INFORMATIONAL",
                    "confidence": 1.0,
                },
            },
            "confirmation": "SUBMIT",
        },
        scope_project=scope_project,
    )
    proposal_id = proposal.get("proposal_id")
    if not isinstance(proposal_id, str):
        raise RuntimeError("claim proposal did not return proposal identity")
    review = await _tool_call(
        args.mcp_executable,
        profile="reviewer",
        token=environment["MILAI_AGENT_REVIEWER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_memory_review",
        arguments={
            "proposal_id": proposal_id,
            "operation_id": f"{args.run_id}-{label}-review",
            "decision": "APPROVE",
            "policy_version": "product03-synthetic-fixture-v1",
            "reason_code": "SYNTHETIC_FIXTURE_OBSERVATION_VERIFIED",
            "confirmation": "APPROVE",
        },
        scope_project=scope_project,
    )
    return {
        "label": label,
        "value": value,
        "scope_project": scope_project,
        "evidence_id": evidence_id,
        "proposal_id": proposal_id,
        "claim_id": review.get("claim_id"),
        "claim_version_id": review.get("claim_version_id"),
        "outbox_id": review.get("outbox_id"),
    }


async def _supersede_target(
    args: argparse.Namespace,
    environment: dict[str, str],
    current: dict[str, Any],
    value: str,
) -> dict[str, Any]:
    capture = await _tool_call(
        args.mcp_executable,
        profile="submitter",
        token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_evidence_capture",
        arguments={
            "operation_id": f"{args.run_id}-target-correction-capture",
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"product03://{_digest(args.run_id)[:16]}/target-correction",
            "subject_id": "orchid-release",
            "observed_at": datetime.now(UTC).isoformat(),
            "content": f"Synthetic corrected release.target is {value}",
            "permission_snapshot": {
                "readable": True,
                "scope": "synthetic-product03",
            },
            "confirmation": "CAPTURE",
            "retention_state": "READABLE",
            "data_classification": "SYNTHETIC",
        },
    )
    evidence_id = capture.get("evidence_id")
    claim_id = current.get("claim_id")
    claim_version_id = current.get("claim_version_id")
    if not all(isinstance(item, str) for item in (evidence_id, claim_id, claim_version_id)):
        raise RuntimeError("target correction identities are incomplete")
    proposal = await _tool_call(
        args.mcp_executable,
        profile="submitter",
        token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_proposal_create",
        arguments={
            "operation_id": f"{args.run_id}-target-correction-proposal",
            "proposal": {
                "operation": "SUPERSEDE",
                "target_claim_id": claim_id,
                "expected_version_id": claim_version_id,
                "supporting_evidence_refs": [evidence_id],
                "requested_authority": "INFORMATIONAL",
                "scope_predicate": {"project_ids": ["orchid-release"]},
                "model_id": "deterministic-product03-fixture",
                "template_version": "v1",
                "input_snapshot_hash": _digest(
                    {"evidence_id": evidence_id, "claim_id": claim_id, "value": value}
                ),
                "proposed_patch": {
                    "payload": {"state_key": "release.target", "value": value},
                    "authority": "INFORMATIONAL",
                    "confidence": 1.0,
                },
            },
            "confirmation": "SUBMIT",
        },
    )
    proposal_id = proposal.get("proposal_id")
    if not isinstance(proposal_id, str):
        raise RuntimeError("target correction proposal identity is missing")
    review = await _tool_call(
        args.mcp_executable,
        profile="reviewer",
        token=environment["MILAI_AGENT_REVIEWER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_memory_review",
        arguments={
            "proposal_id": proposal_id,
            "operation_id": f"{args.run_id}-target-correction-review",
            "decision": "APPROVE",
            "policy_version": "product03-synthetic-fixture-v1",
            "reason_code": "SYNTHETIC_CORRECTION_VERIFIED",
            "confirmation": "APPROVE",
        },
    )
    return {
        "label": "target-correction",
        "old_value": current.get("value"),
        "value": value,
        "evidence_id": evidence_id,
        "proposal_id": proposal_id,
        "claim_id": review.get("claim_id"),
        "claim_version_id": review.get("claim_version_id"),
        "outbox_id": review.get("outbox_id"),
    }


async def _seed_suite(args: argparse.Namespace) -> dict[str, Any]:
    environment = _environment(args.runtime_env)
    current = json.loads(args.initial_fixture.read_text(encoding="utf-8"))
    decision = await _create_claim(
        args,
        environment,
        label="decision-assistant",
        subject="orchid-release",
        predicate="release.decision",
        claim_type="PROJECT_DECISION",
        value="GATE-GREEN-275",
        scope_project="orchid-release",
        speaker="assistant",
    )
    revoked = await _create_claim(
        args,
        environment,
        label="database-revoked",
        subject="orchid-release",
        predicate="release.database",
        claim_type="PROJECT_CONFIG",
        value="DB-REVOKED-991",
        scope_project="orchid-release",
    )
    revoke = await _tool_call(
        args.mcp_executable,
        profile="operator",
        token=environment["MILAI_AGENT_OPERATOR_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_evidence_revoke",
        arguments={
            "evidence_id": revoked["evidence_id"],
            "operation_id": f"{args.run_id}-database-revoke",
            "reason_code": "SOURCE_REMOVED",
            "confirmation": "REVOKE",
        },
    )
    wrong_scope = await _create_claim(
        args,
        environment,
        label="wrong-scope-target",
        subject="outside-orchid-release",
        predicate="release.target",
        claim_type="PROJECT_STATE",
        value="FORBIDDEN-SCOPE-441",
        scope_project="outside-orchid-release",
    )
    correction = await _supersede_target(
        args,
        environment,
        current,
        "AURORA-QUARTZ-8421",
    )
    private = {
        "run_id": args.run_id,
        "initial": current,
        "decision": decision,
        "revoked": {**revoked, "revocation": revoke},
        "wrong_scope": wrong_scope,
        "correction": correction,
    }
    _write_private(args.output, private)
    return {
        "schema": "milai.product03.fixture-suite-receipt.v1",
        "status": "SEEDED",
        "writer_profiles": ["submitter", "reviewer", "operator"],
        "canonical_mutations": 4,
        "revocations": 1,
        "value_sha256": {
            label: hashlib.sha256(value.encode()).hexdigest()
            for label, value in {
                "decision": decision["value"],
                "revoked": revoked["value"],
                "wrong_scope": wrong_scope["value"],
                "corrected": correction["value"],
            }.items()
        },
    }


async def _seed_evidence_pair(args: argparse.Namespace) -> dict[str, Any]:
    environment = _environment(args.runtime_env)
    specifications = (
        (
            "total",
            "product03-cross-session-total",
            "I spent exactly $132 on coffee mugs for my coworkers.",
        ),
        (
            "count",
            "product03-cross-session-count",
            "I purchased exactly 11 coffee mugs for my coworkers.",
        ),
    )
    receipts: list[dict[str, Any]] = []
    for ordinal, (label, session_id, content) in enumerate(specifications, start=1):
        receipt = await _tool_call(
            args.mcp_executable,
            profile="submitter",
            token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
            base_url=environment["MILAI_BASE_URL"],
            tool="milai_evidence_capture",
            arguments={
                "operation_id": f"{args.run_id}-cross-session-{label}",
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": (
                    f"product03://{_digest(args.run_id)[:16]}/cross-session/{label}"
                ),
                "subject_id": "product03-coffee-mugs",
                "speaker": "user",
                "source_context": {
                    "session_id": session_id,
                    "turn_id": f"turn-{ordinal}",
                    "turn_ordinal": ordinal,
                    "round_id": f"round-{ordinal}",
                    "round_ordinal": ordinal,
                    "previous_turn_id": None,
                    "next_turn_id": None,
                },
                "observed_at": datetime.now(UTC).isoformat(),
                "content": content,
                "permission_snapshot": {
                    "readable": True,
                    "scope": "synthetic-product03",
                    "project_ids": ["orchid-release"],
                },
                "confirmation": "CAPTURE",
                "retention_state": "READABLE",
                "data_classification": "SYNTHETIC",
            },
        )
        evidence_id = receipt.get("evidence_id")
        if not isinstance(evidence_id, str):
            raise RuntimeError("cross-session capture did not return evidence identity")
        receipts.append(
            {
                "label": label,
                "session_id": session_id,
                "evidence_id": evidence_id,
            }
        )
    _write_private(args.output, receipts)
    return {
        "schema": "milai.product03.cross-session-fixture.v1",
        "status": "SEEDED",
        "evidence_count": len(receipts),
        "distinct_source_sessions": len({item["session_id"] for item in receipts}),
        "evidence_id_sha256": [
            hashlib.sha256(str(item["evidence_id"]).encode()).hexdigest()
            for item in receipts
        ],
    }


_FLOW_SPECS: tuple[dict[str, Any], ...] = (
    {
        "flow_id": "exact_current",
        "session": "A",
        "prompt": (
            "What is the current release target for orchid-release? "
            "Answer with the exact target value."
        ),
        "expected": ("AURORA-QUARTZ-8421",),
        "forbidden": ("CALYPSO-NEBULA-7319", "FORBIDDEN-SCOPE-441"),
    },
    {
        "flow_id": "same_session_continuation",
        "session": "A",
        "prompt": "Please repeat that current target in one full sentence.",
        "expected": ("AURORA-QUARTZ-8421",),
        "forbidden": ("CALYPSO-NEBULA-7319", "FORBIDDEN-SCOPE-441"),
    },
    {
        "flow_id": "paraphrased_recall",
        "session": "B",
        "prompt": "Which deployment target is orchid-release presently aiming at?",
        "expected": ("AURORA-QUARTZ-8421",),
        "forbidden": ("CALYPSO-NEBULA-7319", "FORBIDDEN-SCOPE-441"),
    },
    {
        "flow_id": "assistant_answer_memory",
        "session": "C",
        "prompt": "What is the current governed release decision for orchid-release?",
        "expected": ("GATE-GREEN-275",),
        "forbidden": (),
    },
    {
        "flow_id": "new_session_recollection",
        "session": "D",
        "prompt": "In this fresh session, recall orchid-release's current release target.",
        "expected": ("AURORA-QUARTZ-8421",),
        "forbidden": ("CALYPSO-NEBULA-7319", "FORBIDDEN-SCOPE-441"),
    },
    {
        "flow_id": "two_evidence_comparison",
        "session": "E",
        "prompt": (
            "State both the current release target and the current governed release "
            "decision for orchid-release, and distinguish their roles."
        ),
        "expected": ("AURORA-QUARTZ-8421", "GATE-GREEN-275"),
        "forbidden": ("CALYPSO-NEBULA-7319",),
    },
    {
        "flow_id": "multi_fact_continuation",
        "session": "E",
        "prompt": (
            "Continue: which current release target for orchid-release pairs with "
            "governed decision GATE-GREEN-275? Include both values in one sentence."
        ),
        "expected": ("AURORA-QUARTZ-8421", "GATE-GREEN-275"),
        "forbidden": ("CALYPSO-NEBULA-7319",),
    },
    {
        "flow_id": "correction_obsolete_suppression",
        "session": "F",
        "prompt": (
            "Give the corrected current release target for orchid-release, not an obsolete value."
        ),
        "expected": ("AURORA-QUARTZ-8421",),
        "forbidden": ("CALYPSO-NEBULA-7319",),
    },
    {
        "flow_id": "scope_isolation",
        "session": "G",
        "prompt": "What is the release target for outside-orchid-release?",
        "expected": (),
        "forbidden": ("FORBIDDEN-SCOPE-441",),
        "negative": True,
    },
    {
        "flow_id": "revoked_evidence",
        "session": "H",
        "prompt": "What is the current release database for orchid-release?",
        "expected": (),
        "forbidden": ("DB-REVOKED-991",),
        "negative": True,
    },
    {
        "flow_id": "no_memory_abstention",
        "session": "I",
        "prompt": "What is the current zephyr launch color code?",
        "expected": (),
        "forbidden": (
            "AURORA-QUARTZ-8421",
            "GATE-GREEN-275",
            "FORBIDDEN-SCOPE-441",
            "DB-REVOKED-991",
        ),
        "negative": True,
    },
    {
        "flow_id": "cross_session_composition",
        "session": "J",
        "prompt": (
            "How much did I spend on each coffee mug for my coworkers? "
            "Answer with the computed dollars per item."
        ),
        "expected": ("$12",),
        "expected_any": (
            "per item",
            "per coffee mug",
            "each coffee mug",
            "each mug",
        ),
        "forbidden": (),
    },
)


def _create_session(container: str, title: str) -> str:
    raw = _command(
        [
            "docker",
            "exec",
            container,
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--user",
            "opencode:openworker-local",
            "--request",
            "POST",
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            json.dumps({"title": title}, separators=(",", ":")),
            (
                "http://127.0.0.1:4096/session?"
                "directory=%2Fopenworker%2Fruntime"
            ),
        ],
        timeout=30,
    )
    value = json.loads(raw)
    session_id = value.get("id") if isinstance(value, dict) else None
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("OpenCode session identity is missing")
    return session_id


def _native_turn(container: str, session_id: str, prompt: str) -> str:
    _command(
        [
            "docker",
            "exec",
            "--workdir",
            "/openworker/runtime",
            "--env",
            "OPENCODE_CONFIG_DIR=/openworker/runtime",
            container,
            "opencode",
            "run",
            "--attach",
            "http://127.0.0.1:4096",
            "--password",
            "openworker-local",
            "--format",
            "json",
            "--model",
            "openworker/Qwen3.6-35B-A3B-FP8",
            "--session",
            session_id,
            "--dir",
            "/openworker/runtime",
            prompt,
        ]
    )
    raw = _command(
        [
            "docker",
            "exec",
            container,
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--user",
            "opencode:openworker-local",
            (
                f"http://127.0.0.1:4096/session/{session_id}/message?"
                "directory=%2Fopenworker%2Fruntime"
            ),
        ],
        timeout=30,
    )
    messages = json.loads(raw)
    answers = [
        part.get("text")
        for message in messages
        if isinstance(message, dict)
        and isinstance(message.get("info"), dict)
        and message["info"].get("role") == "assistant"
        for part in message.get("parts", [])
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    if not answers:
        raise RuntimeError("native OpenCode operation returned no assistant text")
    return answers[-1]  # type: ignore[return-value]


def _run_flows(args: argparse.Namespace) -> dict[str, Any]:
    requested_ids = set(args.flow_ids or ())
    selected = tuple(
        spec
        for spec in _FLOW_SPECS
        if not requested_ids or spec["flow_id"] in requested_ids
    )[: args.limit]
    missing_ids = requested_ids - {str(spec["flow_id"]) for spec in selected}
    if missing_ids:
        raise ValueError(f"unknown or excluded flow IDs: {sorted(missing_ids)}")
    sessions: dict[str, str] = {}
    raw_results: list[dict[str, Any]] = []
    compact: list[dict[str, Any]] = []
    unknown_markers = (
        "unknown",
        "not available",
        "cannot determine",
        "can't determine",
        "do not have",
        "don't have",
        "no memory",
        "unavailable",
    )
    for spec in selected:
        session_ref = str(spec["session"])
        if session_ref not in sessions:
            sessions[session_ref] = _create_session(
                args.container,
                f"Product03 {args.run_label} {session_ref}",
            )
        answer = _native_turn(
            args.container,
            sessions[session_ref],
            str(spec["prompt"]),
        )
        normalized = answer.casefold()
        expected = tuple(str(value) for value in spec["expected"])
        forbidden = tuple(str(value) for value in spec["forbidden"])
        expected_any = tuple(str(value) for value in spec.get("expected_any", ()))
        expected_present = all(value.casefold() in normalized for value in expected) and (
            not expected_any
            or any(value.casefold() in normalized for value in expected_any)
        )
        forbidden_absent = all(value.casefold() not in normalized for value in forbidden)
        negative_typed = not spec.get("negative") or any(
            marker in normalized for marker in unknown_markers
        )
        passed = expected_present and forbidden_absent and negative_typed
        raw_results.append(
            {
                "flow_id": spec["flow_id"],
                "session_id": sessions[session_ref],
                "prompt": spec["prompt"],
                "answer": answer,
                "passed": passed,
            }
        )
        compact.append(
            {
                "flow_id": spec["flow_id"],
                "passed": passed,
                "expected_present": expected_present,
                "forbidden_absent": forbidden_absent,
                "negative_typed": negative_typed,
                "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                "answer_chars": len(answer),
            }
        )
    _write_private(args.output, raw_results)
    return {
        "schema": "milai.product03.openworker-flows.v1",
        "run_label": args.run_label,
        "native_operations": len(compact),
        "session_count": len(sessions),
        "passed": sum(item["passed"] is True for item in compact),
        "failed": sum(item["passed"] is False for item in compact),
        "flows": compact,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.5))
    return ordered[index]


def _run_load(args: argparse.Namespace) -> dict[str, Any]:
    sessions = [
        _create_session(args.container, f"Product03 OW3 load {index:02d}")
        for index in range(16)
    ]
    initial_specs = (
        (
            "What is the current release target for orchid-release? Answer exactly.",
            ("AURORA-QUARTZ-8421",),
            False,
        ),
        (
            "What is the current governed release decision for orchid-release?",
            ("GATE-GREEN-275",),
            False,
        ),
        (
            "How much did I spend on each coffee mug for my coworkers? "
            "Answer with the computed dollars per item.",
            ("$12 per item",),
            False,
        ),
        (
            "What is the current zephyr launch color code?",
            (),
            True,
        ),
    )
    continuation_specs = (
        (
            "Continue by repeating orchid-release's current target exactly.",
            ("AURORA-QUARTZ-8421",),
            False,
        ),
        (
            "Continue: what is the current governed release decision for "
            "orchid-release? Answer exactly.",
            ("GATE-GREEN-275",),
            False,
        ),
        (
            "Continue: how much did I spend on each coffee mug for my coworkers? "
            "Answer with the computed dollars per item.",
            ("$12 per item",),
            False,
        ),
        (
            "Continue: what is the current zephyr launch color code?",
            (),
            True,
        ),
    )
    rows: list[dict[str, Any]] = []

    def execute(index: int, phase: str) -> dict[str, Any]:
        prompt, expected, negative = (
            initial_specs[index % len(initial_specs)]
            if phase == "initial"
            else continuation_specs[index % len(continuation_specs)]
        )
        started = time.perf_counter()
        answer = _native_turn(args.container, sessions[index], prompt)
        elapsed_ms = (time.perf_counter() - started) * 1_000
        normalized = answer.casefold()
        expected_present = all(value.casefold() in normalized for value in expected)
        typed_negative = not negative or any(
            marker in normalized
            for marker in (
                "unknown",
                "memory_insufficient",
                "cannot determine",
                "unavailable",
            )
        )
        return {
            "operation_index": index + (0 if phase == "initial" else 16),
            "phase": phase,
            "session_id": sessions[index],
            "prompt": prompt,
            "answer": answer,
            "elapsed_ms": round(elapsed_ms, 3),
            "passed": expected_present and typed_negative,
            "negative": negative,
        }

    phase_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        rows.extend(executor.map(lambda index: execute(index, "initial"), range(16)))
    initial_wall_ms = (time.perf_counter() - phase_started) * 1_000
    phase_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        rows.extend(executor.map(lambda index: execute(index, "continuation"), range(16)))
    continuation_wall_ms = (time.perf_counter() - phase_started) * 1_000
    _write_private(args.output, rows)
    latencies = [float(row["elapsed_ms"]) for row in rows]
    return {
        "schema": "milai.product03.openworker-load.v1",
        "native_operations": len(rows),
        "sessions": len(sessions),
        "continuation_operations": sum(row["phase"] == "continuation" for row in rows),
        "negative_operations": sum(row["negative"] is True for row in rows),
        "passed": sum(row["passed"] is True for row in rows),
        "failed": sum(row["passed"] is False for row in rows),
        "concurrency_sequence": [4, 8],
        "phase_wall_ms": {
            "concurrency_4": round(initial_wall_ms, 3),
            "concurrency_8": round(continuation_wall_ms, 3),
        },
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3),
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "max": round(max(latencies), 3),
        },
    }


async def _seed(args: argparse.Namespace) -> dict[str, Any]:
    environment = _environment(args.runtime_env)
    required = {
        "MILAI_BASE_URL",
        "MILAI_AGENT_SUBMITTER_TOKEN",
        "MILAI_AGENT_REVIEWER_TOKEN",
        "MILAI_AGENT_OPERATOR_TOKEN",
    }
    if not required <= set(environment):
        raise RuntimeError("Runtime role environment is incomplete")
    run_id = args.run_id
    value = args.value
    observed_at = datetime.now(UTC).isoformat()
    capture = await _tool_call(
        args.mcp_executable,
        profile="submitter",
        token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_evidence_capture",
        arguments={
            "operation_id": f"{run_id}-capture-target",
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"product03://{_digest(run_id)[:16]}/release-target",
            "subject_id": "orchid-release",
            "observed_at": observed_at,
            "content": f"Synthetic orchid-release current release target is {value}",
            "permission_snapshot": {
                "readable": True,
                "scope": "synthetic-product03",
            },
            "confirmation": "CAPTURE",
            "retention_state": "READABLE",
            "data_classification": "SYNTHETIC",
        },
    )
    evidence_id = capture.get("evidence_id")
    if not isinstance(evidence_id, str):
        raise RuntimeError("capture did not return evidence identity")
    snapshot_hash = _digest(
        {"evidence_id": evidence_id, "state_key": "release.target", "value": value}
    )
    proposal = await _tool_call(
        args.mcp_executable,
        profile="submitter",
        token=environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_proposal_create",
        arguments={
            "operation_id": f"{run_id}-propose-target",
            "proposal": {
                "operation": "CREATE",
                "supporting_evidence_refs": [evidence_id],
                "requested_authority": "INFORMATIONAL",
                "scope_predicate": {"project_ids": ["orchid-release"]},
                "model_id": "deterministic-product03-fixture",
                "template_version": "v1",
                "input_snapshot_hash": snapshot_hash,
                "proposed_patch": {
                    "subject_id": "orchid-release",
                    "predicate": "release.target",
                    "claim_type": "PROJECT_STATE",
                    "payload": {"state_key": "release.target", "value": value},
                    "authority": "INFORMATIONAL",
                    "confidence": 1.0,
                },
            },
            "confirmation": "SUBMIT",
        },
    )
    proposal_id = proposal.get("proposal_id")
    if not isinstance(proposal_id, str):
        raise RuntimeError("proposal did not return proposal identity")
    review = await _tool_call(
        args.mcp_executable,
        profile="reviewer",
        token=environment["MILAI_AGENT_REVIEWER_TOKEN"],
        base_url=environment["MILAI_BASE_URL"],
        tool="milai_memory_review",
        arguments={
            "proposal_id": proposal_id,
            "operation_id": f"{run_id}-review-target",
            "decision": "APPROVE",
            "policy_version": "product03-synthetic-fixture-v1",
            "reason_code": "SYNTHETIC_FIXTURE_OBSERVATION_VERIFIED",
            "confirmation": "APPROVE",
        },
    )
    private = {
        "run_id": run_id,
        "value": value,
        "evidence_id": evidence_id,
        "proposal_id": proposal_id,
        "claim_id": review.get("claim_id"),
        "claim_version_id": review.get("claim_version_id"),
        "outbox_id": review.get("outbox_id"),
    }
    _write_private(args.output, private)
    return {
        "schema": "milai.product03.fixture-receipt.v1",
        "status": "SEEDED",
        "writer_profiles": ["submitter", "reviewer"],
        "data_boundary": "SYNTHETIC",
        "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
        "evidence_id_sha256": hashlib.sha256(evidence_id.encode()).hexdigest(),
        "proposal_id_sha256": hashlib.sha256(proposal_id.encode()).hexdigest(),
        "claim_id_sha256": hashlib.sha256(str(review.get("claim_id")).encode()).hexdigest(),
        "canonical_outbox_sequence": review.get("canonical_commit_seq"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed")
    seed.add_argument("--runtime-env", type=Path, required=True)
    seed.add_argument("--mcp-executable", type=Path, required=True)
    seed.add_argument("--run-id", required=True)
    seed.add_argument("--value", required=True)
    seed.add_argument("--output", type=Path, required=True)
    suite = commands.add_parser("seed-suite")
    suite.add_argument("--runtime-env", type=Path, required=True)
    suite.add_argument("--mcp-executable", type=Path, required=True)
    suite.add_argument("--run-id", required=True)
    suite.add_argument("--initial-fixture", type=Path, required=True)
    suite.add_argument("--output", type=Path, required=True)
    evidence_pair = commands.add_parser("seed-evidence-pair")
    evidence_pair.add_argument("--runtime-env", type=Path, required=True)
    evidence_pair.add_argument("--mcp-executable", type=Path, required=True)
    evidence_pair.add_argument("--run-id", required=True)
    evidence_pair.add_argument("--output", type=Path, required=True)
    flows = commands.add_parser("run-flows")
    flows.add_argument("--container", required=True)
    flows.add_argument("--run-label", required=True)
    flows.add_argument("--limit", type=int, default=len(_FLOW_SPECS))
    flows.add_argument("--flow-ids", nargs="*")
    flows.add_argument("--output", type=Path, required=True)
    load = commands.add_parser("run-load")
    load.add_argument("--container", required=True)
    load.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "seed":
        print(json.dumps(asyncio.run(_seed(args)), sort_keys=True))
    elif args.command == "seed-suite":
        print(json.dumps(asyncio.run(_seed_suite(args)), sort_keys=True))
    elif args.command == "seed-evidence-pair":
        print(json.dumps(asyncio.run(_seed_evidence_pair(args)), sort_keys=True))
    elif args.command == "run-flows":
        print(json.dumps(_run_flows(args), sort_keys=True))
    elif args.command == "run-load":
        print(json.dumps(_run_load(args), sort_keys=True))


if __name__ == "__main__":
    main()
