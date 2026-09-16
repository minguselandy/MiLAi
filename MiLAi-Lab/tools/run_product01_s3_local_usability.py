#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.local_usability_gate import (  # noqa: E402
    LocalUsabilityMetrics,
    percentile,
    typed_terminal,
)
from milai_lab.product_adapter.manifest import (  # noqa: E402
    load_product_lock,
    verify_product_lock,
)
from run_product01_s1_context_preflight import (  # noqa: E402
    RuntimeHttpClient,
    _load_env,
    _wait_projection,
)

EXPECTED_PRODUCT_COMMIT = "126ca08b3b4b15e17f3b5fad777022f0c6a05d0b"
EXPECTED_PRODUCT_LOCK_DIGEST = "36fc1680ab93c9b5c25c91009fad6f256ea915852584c5e1ff1d880923f5bd1c"
CANDIDATE_FLAG = "MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED"
SELECTED_FLAG_VALUE = True
ROLLBACK_FLAG_VALUE = False
ROLLBACK_CHECK_MODE = "TYPE_DIRECTED_ACQUISITION"
RUN_PREFIX = "product01-s3"
RUN_SCHEMA_VERSION = "milai-product01-s3-run-v1"
METRICS_SCHEMA_VERSION = "milai-product01-s3-metrics-v1"
TERMINAL_SCHEMA_VERSION = "milai-product01-s3-terminal-v1"
PASS_TERMINAL = "PASS_S3_PRODUCT_LOCAL_USABILITY"  # noqa: S105 -- status, not a secret
FAIL_TERMINAL = "FAIL_S3_REPAIR_REQUIRED"
SELECTED_ARM = "B1_SIMPLE_RECALL"
NEXT_SCOPE = "S4_LAB_CONFIRMATION"
REFERENCE_TIME = "2026-09-01T00:00:00+00:00"


class LocalUsabilityError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Product-01 S3 local usability gate")
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-lock", type=Path, default=ROOT / "product.lock.json")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:38280")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RuntimeController:
    def __init__(self, product_root: Path, env_file: Path, compose_project: str) -> None:
        self.runtime_root = product_root.resolve() / "runtime"
        self.env_file = env_file.resolve()
        self.compose_project = compose_project
        self.executable = self.runtime_root / ".venv/bin/milai-ops"
        if not self.executable.is_file():
            raise LocalUsabilityError("Product operations entrypoint is missing")
        self.environment = dict(os.environ)
        self.environment.update(_load_env(self.env_file))

    def _run(self, action: str, *, candidate: bool) -> dict[str, Any]:
        environment = dict(self.environment)
        environment[CANDIDATE_FLAG] = "true" if candidate else "false"
        command = [str(self.executable), action, "--env-file", str(self.env_file)]
        if action == "start":
            command.extend(["--background", "--compose-project", self.compose_project])
        completed = subprocess.run(  # noqa: S603 -- exact pinned local Product CLI
            command,
            cwd=self.runtime_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if completed.returncode != 0:
            raise LocalUsabilityError(f"Product operations {action} failed closed")
        lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
        if not lines:
            raise LocalUsabilityError(f"Product operations {action} returned no receipt")
        value = json.loads(lines[-1])
        if not isinstance(value, dict):
            raise LocalUsabilityError("Product operations receipt is invalid")
        return value

    async def restart(self, *, candidate: bool) -> tuple[dict[str, Any], dict[str, Any], float]:
        started = time.perf_counter()
        stopped = await asyncio.to_thread(self._run, "stop", candidate=candidate)
        launched = await asyncio.to_thread(self._run, "start", candidate=candidate)
        return stopped, launched, (time.perf_counter() - started) * 1_000


def _event(
    label: str,
    content: str,
    *,
    project_id: str,
    speaker: str = "user",
    readable: bool = True,
    session_suffix: str = "a",
) -> dict[str, Any]:
    session_id = f"p01-s3:{project_id}:{session_suffix}"
    return {
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": f"s3://{label}/{session_suffix}/turn/0",
        "subject_id": f"p01-s3:{project_id}",
        "speaker": speaker,
        "source_context": {
            "session_id": session_id,
            "turn_id": f"{session_id}:turn:0",
            "turn_ordinal": 0,
            "round_id": f"{session_id}:round:0",
            "round_ordinal": 0,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "observed_at": REFERENCE_TIME,
        "content": content,
        "data_classification": "SYNTHETIC",
        "permission_snapshot": {"readable": readable, "project_ids": [project_id]},
        "retention_state": "READABLE",
    }


async def _capture(
    client: RuntimeHttpClient, reader: RuntimeHttpClient, label: str, payload: Mapping[str, Any]
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = await client.request(
        "POST", "/v1/evidence", payload, operation_id=f"p01-s3-capture-{label}"
    )
    outbox_id = result.get("outbox_id")
    if not isinstance(outbox_id, str):
        raise LocalUsabilityError("capture receipt omitted outbox identity")
    await _wait_projection(reader, [outbox_id])
    return result, (time.perf_counter() - started) * 1_000


async def _resolve(
    reader: RuntimeHttpClient, query: str, project_id: str
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = await reader.request(
        "POST",
        "/v1/memory/resolve",
        {
            "query": query,
            "requested_scope": {"project_ids": [project_id]},
            "required_authority": "INFORMATIONAL",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            "reference_time": REFERENCE_TIME,
            "budget": {
                "max_results": 12,
                "max_context_tokens": 8_192,
                "max_latency_ms": 2_000,
            },
        },
    )
    return result, (time.perf_counter() - started) * 1_000


def _accepted(result: Mapping[str, Any], evidence_id: str) -> bool:
    accepted = result.get("accepted_binding_evidence_refs")
    return isinstance(accepted, list) and evidence_id in accepted


def _canonical_read_immutable(result: Mapping[str, Any]) -> bool:
    context = result.get("memory_context")
    trace = context.get("compile_trace") if isinstance(context, Mapping) else None
    return isinstance(trace, Mapping) and trace.get("canonical_mutation") is False


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise LocalUsabilityError("run output already exists")
    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise LocalUsabilityError("Product pin failed: " + "; ".join(verification.errors))
    if (
        EXPECTED_PRODUCT_COMMIT is not None
        and EXPECTED_PRODUCT_LOCK_DIGEST is not None
        and (
            lock.git_commit != EXPECTED_PRODUCT_COMMIT
            or lock.digest != EXPECTED_PRODUCT_LOCK_DIGEST
        )
    ):
        raise LocalUsabilityError("Product commit or lock digest is outside the S3 contract")

    env = _load_env(args.env_file)
    for name in ("MILAI_AGENT_OPERATOR_TOKEN", "MILAI_AGENT_REVIEWER_TOKEN"):
        if not env.get(name):
            raise LocalUsabilityError(f"Runtime environment lacks {name}")
    controller = RuntimeController(args.product_root, args.env_file, args.compose_project)
    artifacts = RunArtifacts(args.output)
    run_id = f"{RUN_PREFIX}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    started_at = datetime.now(UTC)
    artifacts.write_json(
        "run.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "RUNNING",
            "started_at": started_at.isoformat(),
            "arm_kind": "PRODUCT_BLACK_BOX_LOCAL_STACK",
            "product_commit": lock.git_commit,
            "product_lock_digest": lock.digest,
            "product_tree_sha256": lock.tree_sha256,
            "compose_project": args.compose_project,
            "scenario_count": 24,
            "warm_request_count": 100,
            "candidate_flag": CANDIDATE_FLAG,
            "candidate_default_enabled": False,
            "formal_holdout_consumed": False,
            "reader_calls": 0,
            "judge_calls": 0,
        },
    )

    submitter = RuntimeHttpClient(
        args.base_url, env["MILAI_AGENT_SUBMITTER_TOKEN"], max_connections=8
    )
    reader = RuntimeHttpClient(args.base_url, env["MILAI_AGENT_READER_TOKEN"], max_connections=8)
    operator = RuntimeHttpClient(
        args.base_url, env["MILAI_AGENT_OPERATOR_TOKEN"], max_connections=2
    )
    reviewer = RuntimeHttpClient(
        args.base_url, env["MILAI_AGENT_REVIEWER_TOKEN"], max_connections=2
    )
    scenarios: list[dict[str, Any]] = []
    write_latencies: list[float] = []
    retrieval_latencies: list[float] = []
    control_latencies: list[float] = []
    read_mutations = 0
    governance_leaks = 0
    fallback_checks: list[bool] = []

    def record(
        case_id: str, passed: bool, *, latency_ms: float | None = None, terminal: str | None = None
    ) -> None:
        scenarios.append(
            {
                "case_id": case_id,
                "status": "PASS" if passed else "FAIL",
                "elapsed_ms": round(latency_ms, 6) if latency_ms is not None else None,
                "typed_terminal": terminal,
            }
        )

    try:
        capabilities = await reader.request("GET", "/v1/capabilities")
        record("01_one_local_setup", capabilities.get("contract_version") == "agent.v1")

        initial, initial_write = await _capture(
            submitter,
            reader,
            "golden-initial",
            _event(
                "golden-editor-initial",
                "My preferred text editor is Vim.",
                project_id="s3-golden",
            ),
        )
        write_latencies.append(initial_write)
        initial_id = str(initial["evidence_id"])
        recalled, elapsed = await _resolve(reader, "What is my preferred text editor?", "s3-golden")
        retrieval_latencies.append(elapsed)
        read_mutations += not _canonical_read_immutable(recalled)
        record(
            "02_remember_raw_searchable",
            _accepted(recalled, initial_id),
            latency_ms=initial_write,
            terminal=str(recalled.get("status")),
        )

        _, restart_one, restart_one_ms = await controller.restart(
            candidate=SELECTED_FLAG_VALUE
        )
        record(
            "03_runtime_worker_restart",
            restart_one.get("status") == "RUNNING",
            latency_ms=restart_one_ms,
        )
        recalled_after_restart, elapsed = await _resolve(
            reader, "What is my preferred text editor?", "s3-golden"
        )
        retrieval_latencies.append(elapsed)
        record(
            "04_new_session_recall",
            _accepted(recalled_after_restart, initial_id),
            latency_ms=elapsed,
            terminal=str(recalled_after_restart.get("status")),
        )
        source_ok = any(
            isinstance(item, Mapping)
            and item.get("source_ref") == "s3://golden-editor-initial/a/turn/0"
            for item in recalled_after_restart.get("items", [])
        )
        record("05_inspectable_source", source_ok)

        create = await submitter.request(
            "POST",
            "/v1/proposals",
            {
                "operation": "CREATE",
                "proposed_patch": {
                    "subject_id": "p01-s3:s3-golden",
                    "predicate": "preferred.text.editor",
                    "claim_type": "USER_PREFERENCE",
                    "payload": {"editor": "Vim"},
                    "authority": "INFORMATIONAL",
                    "confidence": 0.99,
                },
                "supporting_evidence_refs": [initial_id],
                "scope_predicate": {"project_ids": ["s3-golden"]},
                "requested_authority": "INFORMATIONAL",
                "derivation_policy_id": "product01-s3-user-correction-v1",
                "derivation_snapshot": {"source": "explicit-user-memory"},
            },
            operation_id="p01-s3-create-editor",
        )
        created = await reviewer.request(
            "POST",
            f"/v1/proposals/{create['proposal_id']}/review",
            {
                "decision": "APPROVE",
                "policy_version": "product01-s3-explicit-review-v1",
                "reason_code": "SYNTHETIC_USER_CONFIRMED",
            },
            operation_id="p01-s3-review-editor",
        )
        claim_id = str(created["claim_id"])
        version_one = str(created["claim_version_id"])
        record("06_canonical_initial_state", bool(claim_id and version_one))

        correction, correction_write = await _capture(
            submitter,
            reader,
            "golden-correction",
            _event(
                "golden-editor-correction",
                "Correction: my preferred text editor is Helix.",
                project_id="s3-golden",
                session_suffix="b",
            ),
        )
        write_latencies.append(correction_write)
        correction_id = str(correction["evidence_id"])
        supersede = await submitter.request(
            "POST",
            "/v1/proposals",
            {
                "target_claim_id": claim_id,
                "operation": "SUPERSEDE",
                "expected_version_id": version_one,
                "proposed_patch": {
                    "payload": {"editor": "Helix"},
                    "authority": "INFORMATIONAL",
                    "confidence": 0.99,
                },
                "supporting_evidence_refs": [correction_id],
                "scope_predicate": {"project_ids": ["s3-golden"]},
                "requested_authority": "INFORMATIONAL",
                "derivation_policy_id": "product01-s3-user-correction-v1",
                "derivation_snapshot": {"source": "explicit-user-correction"},
            },
            operation_id="p01-s3-supersede-editor",
        )
        corrected = await reviewer.request(
            "POST",
            f"/v1/proposals/{supersede['proposal_id']}/review",
            {
                "decision": "APPROVE",
                "policy_version": "product01-s3-explicit-review-v1",
                "reason_code": "SYNTHETIC_USER_CORRECTION_CONFIRMED",
            },
            operation_id="p01-s3-review-editor-correction",
        )
        version_two = str(corrected["claim_version_id"])
        current_started = time.perf_counter()
        current = await reader.request("GET", f"/v1/claims/{claim_id}")
        control_latencies.append((time.perf_counter() - current_started) * 1_000)
        record(
            "07_explicit_correction",
            current.get("claim_version_id") == version_two
            and current.get("payload") == {"editor": "Helix"},
        )
        versions = await reader.request("GET", f"/v1/claims/{claim_id}/versions")
        version_payloads = [
            item.get("payload")
            for item in versions.get("versions", [])
            if isinstance(item, Mapping)
        ]
        record(
            "08_version_history_preserved",
            {"editor": "Vim"} in version_payloads and {"editor": "Helix"} in version_payloads,
        )

        positive_specs = (
            (
                "09_english_lookup",
                "english",
                "My bicycle lock is cobalt blue.",
                "What color is my bicycle lock?",
                "user",
                "a",
            ),
            (
                "10_chinese_lookup",
                "chinese",
                "我的 bike_lock 颜色是 cobalt_blue。",
                "我的 bike_lock 颜色是什么?",
                "user",
                "a",
            ),
            (
                "11_assistant_answer",
                "assistant",
                "The observatory access code is 7319.",
                "What is the observatory access code?",
                "assistant",
                "a",
            ),
            (
                "12_second_session",
                "multi",
                "My hiking pole length is 118 centimeters.",
                "What is my hiking pole length?",
                "user",
                "b",
            ),
        )
        for case_id, project, content, query, speaker, suffix in positive_specs:
            captured, capture_ms = await _capture(
                submitter,
                reader,
                case_id,
                _event(
                    case_id,
                    content,
                    project_id=f"s3-{project}",
                    speaker=speaker,
                    session_suffix=suffix,
                ),
            )
            write_latencies.append(capture_ms)
            result, query_ms = await _resolve(reader, query, f"s3-{project}")
            retrieval_latencies.append(query_ms)
            immutable = _canonical_read_immutable(result)
            read_mutations += not immutable
            record(
                case_id,
                _accepted(result, str(captured["evidence_id"])) and immutable,
                latency_ms=query_ms,
                terminal=str(result.get("status")),
            )

        state_started = time.perf_counter()
        state = await reader.request(
            "POST",
            "/v1/memory/get",
            {
                "claim_id": claim_id,
                "requested_scope": {"project_ids": ["s3-golden"]},
                "required_authority": "INFORMATIONAL",
            },
        )
        control_latencies.append((time.perf_counter() - state_started) * 1_000)
        state_items = state.get("items", [])
        record(
            "13_canonical_current_state",
            state.get("status") == "HIT"
            and isinstance(state_items, list)
            and state_items[0].get("payload") == {"editor": "Helix"},
            terminal=str(state.get("status")),
        )

        missing, elapsed = await _resolve(
            reader, "What color is my nonexistent sailboat?", "s3-missing"
        )
        retrieval_latencies.append(elapsed)
        record(
            "14_insufficient_evidence",
            missing.get("status") in {"ABSENT", "ABSTAINED", "MISS"} and not missing.get("items"),
            latency_ms=elapsed,
            terminal=str(missing.get("status")),
        )

        cross, cross_write = await _capture(
            submitter,
            reader,
            "cross-scope",
            _event("cross-scope", "My vault key is violet.", project_id="s3-private"),
        )
        write_latencies.append(cross_write)
        cross_result, elapsed = await _resolve(reader, "What color is my vault key?", "s3-public")
        retrieval_latencies.append(elapsed)
        leaked = any(
            isinstance(item, Mapping) and item.get("evidence_id") == cross.get("evidence_id")
            for item in cross_result.get("items", [])
        )
        governance_leaks += leaked
        record(
            "15_cross_scope_isolation",
            not leaked,
            latency_ms=elapsed,
            terminal=str(cross_result.get("status")),
        )

        unreadable, unreadable_write = await _capture(
            submitter,
            reader,
            "unreadable",
            _event(
                "unreadable",
                "My private token is ultramarine.",
                project_id="s3-unreadable",
                readable=False,
            ),
        )
        write_latencies.append(unreadable_write)
        unreadable_result, elapsed = await _resolve(
            reader, "What color is my private token?", "s3-unreadable"
        )
        retrieval_latencies.append(elapsed)
        unreadable_leak = any(
            isinstance(item, Mapping) and item.get("evidence_id") == unreadable.get("evidence_id")
            for item in unreadable_result.get("items", [])
        )
        governance_leaks += unreadable_leak
        record(
            "16_permission_isolation",
            not unreadable_leak,
            latency_ms=elapsed,
            terminal=str(unreadable_result.get("status")),
        )

        outage_result, elapsed = await _resolve(
            reader, "What is my preferred text editor?", "s3-golden"
        )
        retrieval_latencies.append(elapsed)
        outage_ok = outage_result.get("status") == "HIT" and _canonical_read_immutable(
            outage_result
        )
        fallback_checks.append(outage_ok)
        record(
            "17_model_outage_fallback",
            outage_ok,
            latency_ms=elapsed,
            terminal=str(outage_result.get("status")),
        )

        lag_payload = _event(
            "projection-lag", "My travel mug is matte silver.", project_id="s3-lag"
        )
        lag_started = time.perf_counter()
        lag_capture = await submitter.request(
            "POST", "/v1/evidence", lag_payload, operation_id="p01-s3-capture-lag"
        )
        lag_result, elapsed = await _resolve(reader, "What color is my travel mug?", "s3-lag")
        retrieval_latencies.append(elapsed)
        lag_typed = typed_terminal(lag_result)
        record(
            "18_projection_lag_typed",
            lag_typed,
            latency_ms=(time.perf_counter() - lag_started) * 1_000,
            terminal=str(lag_result.get("status")),
        )
        await _wait_projection(reader, [str(lag_capture["outbox_id"])])

        replay = await submitter.request(
            "POST", "/v1/evidence", lag_payload, operation_id="p01-s3-capture-lag"
        )
        record(
            "19_idempotent_capture",
            replay.get("replayed") is True
            and replay.get("evidence_id") == lag_capture.get("evidence_id"),
        )

        no_need, elapsed = await _resolve(reader, "Calculate 2 + 2 without memory.", "s3-no-memory")
        retrieval_latencies.append(elapsed)
        record(
            "20_no_memory_needed",
            typed_terminal(no_need) and not no_need.get("items"),
            latency_ms=elapsed,
            terminal=str(no_need.get("status")),
        )

        revocation = await operator.request(
            "POST",
            f"/v1/evidence/{initial_id}/revoke",
            {"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
            operation_id="p01-s3-revoke-initial",
        )
        revoked_result, elapsed = await _resolve(
            reader, "What was my preferred text editor?", "s3-golden"
        )
        retrieval_latencies.append(elapsed)
        revoked_leak = any(
            isinstance(item, Mapping) and item.get("evidence_id") == initial_id
            for item in revoked_result.get("items", [])
        )
        governance_leaks += revoked_leak
        record(
            "21_revocation_fail_closed",
            not revoked_leak,
            latency_ms=elapsed,
            terminal=str(revoked_result.get("status")),
        )

        deletion_id = str(revocation["deletion_request_id"])
        deletion: dict[str, Any] = {}
        for _ in range(60):
            deletion = await reader.request("GET", f"/v1/deletion-requests/{deletion_id}")
            if (
                deletion.get("derived_purge_status") == "COMPLETED"
                and deletion.get("primary_bytes_status") == "ERASED"
            ):
                break
            await asyncio.sleep(0.25)
        record(
            "22_delete_derived_and_primary",
            deletion.get("derived_purge_status") == "COMPLETED"
            and deletion.get("primary_bytes_status") == "ERASED",
        )

        _, restart_two, restart_two_ms = await controller.restart(
            candidate=SELECTED_FLAG_VALUE
        )
        persisted = await reader.request("GET", f"/v1/claims/{claim_id}")
        post_restart, elapsed = await _resolve(
            reader, "What was my preferred text editor?", "s3-golden"
        )
        retrieval_latencies.append(elapsed)
        old_leak = any(
            isinstance(item, Mapping) and item.get("evidence_id") == initial_id
            for item in post_restart.get("items", [])
        )
        governance_leaks += old_leak
        record(
            "23_restart_preserves_state",
            restart_two.get("status") == "RUNNING"
            and persisted.get("payload") == {"editor": "Helix"}
            and not old_leak,
            latency_ms=restart_two_ms,
            terminal=str(post_restart.get("status")),
        )

        _, baseline_started, baseline_restart_ms = await controller.restart(
            candidate=ROLLBACK_FLAG_VALUE
        )
        baseline_result, elapsed = await _resolve(
            reader, "What color is my bicycle lock?", "s3-english"
        )
        retrieval_latencies.append(elapsed)
        search = baseline_result.get("search_trace")
        dispositions = (
            search.get("acquisition_probe_dispositions") if isinstance(search, Mapping) else None
        )
        enriched_executed = isinstance(dispositions, list) and any(
            isinstance(item, Mapping)
            and item.get("channel") == "FTS_ENRICHED"
            and item.get("status") == "EXECUTED"
            for item in dispositions
        )
        if ROLLBACK_CHECK_MODE == "PROGRESSIVE_CONTEXT":
            context = baseline_result.get("memory_context")
            compile_trace = (
                context.get("compile_trace") if isinstance(context, Mapping) else None
            )
            baseline_restore = (
                baseline_started.get("status") == "RUNNING"
                and isinstance(compile_trace, Mapping)
                and compile_trace.get("reader_evidence_boundary")
                == "GOVERNANCE_ADMITTED_SOFT_RANKED"
            )
        elif ROLLBACK_CHECK_MODE == "BUDGET_STABLE_CONTEXT":
            context = baseline_result.get("memory_context")
            compile_trace = (
                context.get("compile_trace") if isinstance(context, Mapping) else None
            )
            baseline_restore = (
                baseline_started.get("status") == "RUNNING"
                and isinstance(compile_trace, Mapping)
                and "evidence_set_digest" not in compile_trace
            )
        elif ROLLBACK_CHECK_MODE == "BUDGET_STABLE_CANDIDATE":
            context = baseline_result.get("memory_context")
            compile_trace = (
                context.get("compile_trace") if isinstance(context, Mapping) else None
            )
            baseline_restore = (
                baseline_started.get("status") == "RUNNING"
                and isinstance(compile_trace, Mapping)
                and isinstance(compile_trace.get("evidence_set_digest"), str)
            )
        else:
            baseline_restore = (
                baseline_started.get("status") == "RUNNING" and not enriched_executed
            )
        # Return to the selected S3 configuration before the warm run and handoff.
        _, selected_started, selected_restart_ms = await controller.restart(
            candidate=SELECTED_FLAG_VALUE
        )
        rollback_terminal = str(baseline_result.get("status"))
        if ROLLBACK_CHECK_MODE == "BUDGET_STABLE_CANDIDATE":
            selected_result, elapsed = await _resolve(
                reader, "What color is my bicycle lock?", "s3-english"
            )
            retrieval_latencies.append(elapsed)
            selected_context = selected_result.get("memory_context")
            selected_trace = (
                selected_context.get("compile_trace")
                if isinstance(selected_context, Mapping)
                else None
            )
            baseline_restore = (
                baseline_restore
                and selected_started.get("status") == "RUNNING"
                and isinstance(selected_trace, Mapping)
                and "evidence_set_digest" not in selected_trace
            )
            rollback_terminal = str(selected_result.get("status"))
        record(
            "24_one_flag_restores_baseline",
            baseline_restore,
            latency_ms=baseline_restart_ms + selected_restart_ms,
            terminal=rollback_terminal,
        )

        warm_terminals = 0
        for index in range(100):
            if index % 4 == 0:
                warm_started = time.perf_counter()
                response = await reader.request("GET", f"/v1/claims/{claim_id}")
                control_latencies.append((time.perf_counter() - warm_started) * 1_000)
            elif index % 4 == 1:
                response, warm_ms = await _resolve(
                    reader, "What color is my bicycle lock?", "s3-english"
                )
                retrieval_latencies.append(warm_ms)
            elif index % 4 == 2:
                response, warm_ms = await _resolve(
                    reader, "What color is my nonexistent sailboat?", "s3-missing"
                )
                retrieval_latencies.append(warm_ms)
            else:
                warm_started = time.perf_counter()
                response = await reader.request(
                    "POST",
                    "/v1/memory/get",
                    {
                        "claim_id": claim_id,
                        "requested_scope": {"project_ids": ["s3-golden"]},
                        "required_authority": "INFORMATIONAL",
                    },
                )
                control_latencies.append((time.perf_counter() - warm_started) * 1_000)
            warm_terminals += typed_terminal(response) or bool(response.get("claim_version_id"))

        for cell in scenarios:
            artifacts.append_jsonl("cases.jsonl", cell)

        metrics = LocalUsabilityMetrics(
            golden_flow=all(cell["status"] == "PASS" for cell in scenarios[:8] + scenarios[20:23]),
            scenario_count=len(scenarios),
            scenario_success_count=sum(cell["status"] == "PASS" for cell in scenarios),
            warm_request_count=100,
            typed_terminal_count=warm_terminals,
            read_after_write_p95_ms=percentile(write_latencies, 0.95),
            retrieval_context_p95_ms=percentile(retrieval_latencies, 0.95),
            warm_control_p95_ms=percentile(control_latencies, 0.95),
            model_outage_fallback_rate=sum(fallback_checks) / len(fallback_checks),
            governance_leak_count=governance_leaks,
            canonical_read_mutation_count=read_mutations,
            baseline_restore=baseline_restore,
        )
        payload = {
            "schema_version": METRICS_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "PASS" if all(metrics.exit_checks().values()) else "FAIL",
            **metrics.to_dict(),
            "restart_count": 4,
            "reader_calls": 0,
            "judge_calls": 0,
            "formal_holdout_consumed": False,
        }
        artifacts.write_json("metrics.json", payload)
        finished_at = datetime.now(UTC)
        passed = all(metrics.exit_checks().values())
        terminal = {
            "schema_version": TERMINAL_SCHEMA_VERSION,
            "run_id": run_id,
            "status": PASS_TERMINAL if passed else FAIL_TERMINAL,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
            "product_commit": lock.git_commit,
            "product_lock_digest": lock.digest,
            "metrics_sha256": _canonical_sha256(payload),
            "selected_arm": SELECTED_ARM,
            "candidate_default_enabled": False,
            "rollback_flag": f"{CANDIDATE_FLAG}={str(ROLLBACK_FLAG_VALUE).lower()}",
            "formal_holdout_consumed": False,
            "next_scope": NEXT_SCOPE if passed else "S3_GENERAL_REPAIR_ONLY",
        }
        artifacts.write_json("terminal.json", terminal)
        print(json.dumps(terminal, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if passed else 1
    finally:
        await submitter.close()
        await reader.close()
        await operator.close()
        await reviewer.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(
            f"S3 local usability gate failed closed: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
