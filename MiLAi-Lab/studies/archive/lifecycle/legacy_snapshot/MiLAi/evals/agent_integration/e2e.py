from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command
from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.config import load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations import load_runtime_environment
from milai.operations.smoke import (
    _alembic_config,
    _api_environment,
    _body,
    _create_database,
    _database_url,
    _drop_database,
    _free_loopback_port,
    _headers,
    _HttpClient,
    _migration_url,
    _smoke_settings,
    _stop_api,
    _wait_api,
)
from milai.persistence import Database
from milai.persistence.projection_repository import ProjectionRepository
from milai.workers.main import FoundationWorker

_ROOT = Path(__file__).resolve().parents[2]
_PROBE = Path(__file__).with_name("adapter_probe.py")
_MCP_HOST = Path(__file__).with_name("mcp_host.py")
_MCP_WIRE_HOST = Path(__file__).with_name("mcp_wire_host.py")


class E2EFailure(RuntimeError):
    pass


def _require(value: object, code: str) -> None:
    if not value:
        raise E2EFailure(code)


def _child_environment(
    base_url: str,
    token: str,
    *,
    scope: dict[str, Any] | None = None,
    agent_as_of: datetime | None = None,
    max_limit: int | None = None,
) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("MILAI_")
    }
    environment.update({"MILAI_BASE_URL": base_url, "MILAI_AGENT_TOKEN": token})
    environment.update(
        {
            "MILAI_AGENT_SCOPE_JSON": json.dumps(
                scope or {"project_ids": ["milai-agent-e2e"]},
                separators=(",", ":"),
            ),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
        }
    )
    if agent_as_of is not None:
        if agent_as_of.utcoffset() is None:
            raise ValueError("agent_as_of must include a timezone offset")
        environment["MILAI_AGENT_AS_OF"] = agent_as_of.isoformat()
    if max_limit is not None:
        if not 1 <= max_limit <= 50:
            raise ValueError("max_limit must be between 1 and 50")
        environment["MILAI_AGENT_MAX_LIMIT"] = str(max_limit)
    return environment


def _run_json(
    command_line: list[str],
    payload: dict[str, Any],
    *,
    base_url: str,
    token: str,
    scope: dict[str, Any] | None = None,
    agent_as_of: datetime | None = None,
    max_limit: int | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        command_line,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
        env=_child_environment(
            base_url,
            token,
            scope=scope,
            agent_as_of=agent_as_of,
            max_limit=max_limit,
        ),
        cwd=_ROOT,
    )
    if completed.returncode != 0:
        lines = [line for line in completed.stderr.splitlines() if line.strip()]
        detail = " | ".join(lines[-12:])[:1_200] if lines else "NO_DIAGNOSTIC"
        raise E2EFailure(f"ADAPTER_EXIT_{completed.returncode}:{detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise E2EFailure("ADAPTER_INVALID_JSON") from exc
    if not isinstance(result, dict):
        raise E2EFailure("ADAPTER_NON_OBJECT")
    return result


def _adapter(
    name: str,
    action: str,
    payload: dict[str, Any],
    *,
    base_url: str,
    token: str,
) -> dict[str, Any]:
    interpreter = {
        "generic": _ROOT / "integrations/python-client/.venv/bin/python",
        "langgraph": _ROOT / "integrations/langgraph/.venv/bin/python",
        "autogen": _ROOT / "integrations/autogen/.venv/bin/python",
    }[name]
    return _run_json(
        [str(interpreter), str(_PROBE), "--adapter", name, "--action", action],
        payload,
        base_url=base_url,
        token=token,
    )


def _mcp(
    profile: str,
    tool: str | None,
    payload: dict[str, Any],
    *,
    base_url: str,
    token: str,
    mode: str = "2026-07-28",
    scope: dict[str, Any] | None = None,
    agent_as_of: datetime | None = None,
    max_limit: int | None = None,
) -> dict[str, Any]:
    configured_python = os.environ.get("DG10_MCP_HOST_PYTHON")
    interpreter = (
        Path(configured_python)
        if configured_python
        else _ROOT / "integrations/mcp/.venv/bin/python"
    )
    if not interpreter.is_absolute() or not interpreter.is_file():
        raise E2EFailure("MCP_HOST_PYTHON_NOT_FOUND")
    command_line = [
        str(interpreter),
        str(_MCP_HOST),
        "--profile",
        profile,
        "--mode",
        mode,
    ]
    if tool is not None:
        command_line.extend(["--tool", tool])
    return _run_json(
        command_line,
        payload,
        base_url=base_url,
        token=token,
        scope=scope,
        agent_as_of=agent_as_of,
        max_limit=max_limit,
    )


def _mcp_wire(
    tool: str,
    payload: dict[str, Any],
    *,
    base_url: str,
    token: str,
) -> dict[str, Any]:
    return _run_json(
        [
            str(_ROOT / "integrations/mcp/.venv/bin/python"),
            str(_MCP_WIRE_HOST),
            "--profile",
            "reader",
            "--tool",
            tool,
        ],
        payload,
        base_url=base_url,
        token=token,
    )


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("structured")
    if not isinstance(value, dict):
        raise E2EFailure("MCP_STRUCTURED_RESULT_MISSING")
    return value


def _wire_structured(result: dict[str, Any]) -> dict[str, Any]:
    call = result.get("call")
    value = call.get("structuredContent") if isinstance(call, dict) else None
    if not isinstance(value, dict):
        raise E2EFailure("MCP_WIRE_STRUCTURED_RESULT_MISSING")
    return value


def _review(
    client: _HttpClient,
    token: str,
    proposal_id: str,
    operation_id: str,
    reason_code: str,
) -> dict[str, Any]:
    return _body(
        client.post(
            f"/v1/proposals/{proposal_id}/review",
            headers=_headers(token, operation_id),
            json={
                "decision": "APPROVE",
                "policy_version": "agent-e2e-human-steward-v1",
                "reason_code": reason_code,
            },
        ),
        200,
        "review",
    )


def _accepted_version(result: dict[str, Any]) -> str | None:
    items = result.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    value = items[0].get("claim_version_id")
    return str(value) if value else None


def _start_api(
    settings: Any,
    database_urls: dict[str, str],
    tokens: dict[str, str],
) -> subprocess.Popen[bytes]:
    executable = Path(sys.executable).with_name("milai-api")
    if not executable.is_file():
        raise E2EFailure("API_ENTRYPOINT_NOT_INSTALLED")
    return subprocess.Popen(
        [str(executable)],
        cwd=_ROOT / "runtime",
        env=_api_environment(settings, database_urls, tokens),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _trace_reasons(result: dict[str, Any]) -> set[str]:
    trace = result.get("trace")
    rejected = trace.get("rejected_candidates", []) if isinstance(trace, dict) else []
    return {
        str(item.get("reject_reason"))
        for item in rejected
        if isinstance(item, dict) and item.get("reject_reason")
    }


def _run_fixture(
    settings: Any,
    database_urls: dict[str, str],
    tokens: dict[str, str],
    run_id: str,
    phase_hook: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    api_process = _start_api(settings, database_urls, tokens)
    base_url = f"http://{settings.bind_host}:{settings.bind_port}"
    client = _HttpClient(base_url)
    worker_database = Database(
        settings, dsn=database_urls["worker"], expected_role="milai_worker"
    )
    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(
            settings.blob_root,
            kek=settings.blob_kek,
            key_reference=settings.blob_key_reference,
            allow_plaintext_read=True,
        ),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"agent-e2e-{run_id[:12]}",
    )
    marker = f"milaie2e{run_id[:12]}"
    observed_at = datetime.now(UTC).isoformat()
    query = marker
    evidence_base = {
        "source_type": "TOOL_OBSERVATION",
        "subject_id": marker,
        "observed_at": observed_at,
        "permission_snapshot": {"readable": True, "scope": "synthetic-agent-e2e"},
        "retention_state": "READABLE",
    }
    phases: list[dict[str, Any]] = []
    try:
        _wait_api(client, api_process)
        initial = _adapter(
            "generic",
            "recall",
            {"query": query},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(initial["status"] == "ABSTAINED", "S1_INITIAL_NOT_ABSTAINED")
        if phase_hook is not None:
            phase_hook(
                "initial",
                {
                    "base_url": base_url,
                    "reader_token": tokens["reader"],
                    "marker": marker,
                },
            )

        evidence_v1 = _mcp(
            "submitter",
            "milai_evidence_capture",
            {
                "operation_id": f"e2e-s1-evidence-{run_id}",
                **evidence_base,
                "source_ref": f"agent-e2e://{run_id}/session-1/tool",
                "content": f"{marker} tool reports project runtime Python 3.11",
                "confirmation": "CAPTURE",
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        evidence_v1_body = _structured(evidence_v1)
        evidence_v1_id = str(evidence_v1_body["evidence_id"])
        proposal_v1 = _mcp(
            "submitter",
            "milai_proposal_create",
            {
                "operation_id": f"e2e-s1-proposal-{run_id}",
                "proposal": {
                    "operation": "CREATE",
                    "proposed_patch": {
                        "subject_id": marker,
                        "predicate": "runtime.python.version",
                        "claim_type": "RUNTIME_VERSION",
                        "payload": {"python": "3.11", "marker": marker},
                        "authority": "ACTION_SAFE",
                        "confidence": 0.99,
                    },
                    "supporting_evidence_refs": [evidence_v1_id],
                    "scope_predicate": {"project_ids": ["milai-agent-e2e"]},
                    "requested_authority": "ACTION_SAFE",
                    "derivation_policy_id": "agent-e2e-v1",
                    "model_id": "agent-e2e-extractor",
                    "template_version": "v1",
                    "input_snapshot_hash": hashlib.sha256(
                        f"{run_id}:session-1".encode()
                    ).hexdigest(),
                },
                "confirmation": "SUBMIT",
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        pre_review = _adapter(
            "generic",
            "recall",
            {"query": query},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(pre_review["status"] == "ABSTAINED", "S1_PRE_REVIEW_VISIBLE")
        reviewed_v1 = _review(
            client,
            tokens["reviewer"],
            str(_structured(proposal_v1)["proposal_id"]),
            f"e2e-s1-review-{run_id}",
            "SYNTHETIC_TOOL_OBSERVATION_VERIFIED",
        )
        claim_id = str(reviewed_v1["claim_id"])
        version_v1 = str(reviewed_v1["claim_version_id"])
        _require(worker.run_once() > 0, "S1_WORKER_DID_NOT_PROJECT")
        causal = _adapter(
            "generic",
            "causal",
            {"outbox_ids": [str(reviewed_v1["outbox_id"])]},
            base_url=base_url,
            token=tokens["reader"],
        )
        generic_v1 = _adapter(
            "generic",
            "recall",
            {
                "query": query,
                "consistency": "READ_YOUR_WRITES",
                "causal_token": causal["causal_token"],
            },
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(_accepted_version(generic_v1) == version_v1, "S1_GENERIC_V1_MISMATCH")
        mcp_v1 = _mcp(
            "reader",
            "milai_recall",
            {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(not mcp_v1["is_error"], "S1_MCP_RECALL_ERROR")
        _require(
            _accepted_version(_structured(mcp_v1)) == version_v1,
            "S1_MCP_V1_MISMATCH",
        )
        langgraph_v1 = _adapter(
            "langgraph",
            "recall",
            {"query": query, "turn": 1},
            base_url=base_url,
            token=tokens["reader"],
        )
        accepted_native = langgraph_v1["trace"]["accepted_candidates"]
        _require(
            accepted_native and accepted_native[0]["claim_version_id"] == version_v1,
            "S1_NATIVE_V1_MISMATCH",
        )
        _require(langgraph_v1["checkpoint_preserved"], "S1_CHECKPOINT_MIXED")
        phases.append(
            {
                "session": 1,
                "status": "PASS",
                "pre_review": "ABSTAINED",
                "claim_id": claim_id,
                "claim_version_id": version_v1,
                "causal_minimum_sequence": causal["minimum_outbox_sequence"],
                "adapter_traces": {
                    "generic": generic_v1["trace_id"],
                    "mcp": _structured(mcp_v1)["trace_id"],
                    "langgraph": langgraph_v1["trace_id"],
                },
            }
        )
        if phase_hook is not None:
            phase_hook(
                "current",
                {
                    "base_url": base_url,
                    "reader_token": tokens["reader"],
                    "marker": marker,
                    "claim_id": claim_id,
                    "claim_version_id": version_v1,
                    "trace_id": _structured(mcp_v1)["trace_id"],
                },
            )

        _stop_api(api_process)
        if api_process.stderr is not None:
            api_process.stderr.close()
        api_process = _start_api(settings, database_urls, tokens)
        _wait_api(client, api_process)
        restarted_mcp = _mcp(
            "reader",
            "milai_recall",
            {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(not restarted_mcp["is_error"], "S1_RESTART_MCP_RECALL_ERROR")
        _require(
            _accepted_version(_structured(restarted_mcp)) == version_v1,
            "S1_RESTART_PERSISTENCE_MISMATCH",
        )
        phases.append(
            {
                "session": "1-restart",
                "status": "PASS",
                "claim_id": claim_id,
                "claim_version_id": version_v1,
                "trace_id": _structured(restarted_mcp)["trace_id"],
                "runtime_restarted": True,
                "mcp_session_restarted": True,
            }
        )

        wrong_tenant = _body(
            client.post(
                "/v1/evidence",
                headers=_headers(
                    tokens["submitter"], f"e2e-wrong-tenant-{run_id}"
                ),
                json={
                    **evidence_base,
                    "tenant_id": str(uuid4()),
                    "source_ref": f"agent-e2e://{run_id}/wrong-tenant",
                    "content": f"{marker} must not cross tenant boundaries",
                },
            ),
            403,
            "wrong_tenant",
        )
        _require(
            (wrong_tenant.get("error") or {}).get("code") == "TENANT_MISMATCH",
            "ISOLATION_TENANT_NOT_REJECTED",
        )
        wrong_scope = _mcp(
            "reader",
            "milai_recall",
            {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
            base_url=base_url,
            token=tokens["reader"],
            scope={"project_ids": ["not-milai-agent-e2e"]},
        )
        wrong_scope_body = _structured(wrong_scope)
        _require(
            wrong_scope_body["status"] == "ABSTAINED"
            and not wrong_scope_body["items"],
            "ISOLATION_SCOPE_NOT_REJECTED",
        )
        wrong_profile = _mcp(
            "reader-lite",
            "milai_evidence_capture",
            {
                "operation_id": f"e2e-wrong-profile-{run_id}",
                **evidence_base,
                "source_ref": f"agent-e2e://{run_id}/wrong-profile",
                "content": f"{marker} must not be writable from reader-lite",
                "confirmation": "CAPTURE",
            },
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(wrong_profile["is_error"] is True, "ISOLATION_PROFILE_NOT_REJECTED")
        phases.append(
            {
                "session": "isolation-negative",
                "status": "PASS",
                "wrong_tenant": "TENANT_MISMATCH",
                "wrong_scope": "ABSTAINED_EMPTY",
                "wrong_profile": "MCP_TOOL_REJECTED",
            }
        )

        conflict_evidence = _mcp(
            "submitter",
            "milai_evidence_capture",
            {
                "operation_id": f"e2e-s2-evidence-{run_id}",
                "source_type": "TOOL_OBSERVATION",
                "source_ref": f"agent-e2e://{run_id}/session-2/pyproject",
                "subject_id": marker,
                "observed_at": observed_at,
                "content": f"{marker} pyproject requires Python >=3.12",
                "permission_snapshot": {
                    "readable": True,
                    "scope": "synthetic-agent-e2e",
                },
                "retention_state": "READABLE",
                "confirmation": "CAPTURE",
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        conflict_evidence_body = _structured(conflict_evidence)
        conflict_proposal = _mcp(
            "submitter",
            "milai_proposal_create",
            {
                "operation_id": f"e2e-s2-proposal-{run_id}",
                "proposal": {
                    "target_claim_id": claim_id,
                    "operation": "CONTRADICT",
                    "expected_version_id": version_v1,
                    "proposed_patch": {},
                    "contradicting_evidence_refs": [
                        conflict_evidence_body["evidence_id"]
                    ],
                    "scope_predicate": {"project_ids": ["milai-agent-e2e"]},
                    "requested_authority": "ACTION_SAFE",
                    "derivation_policy_id": "agent-e2e-v1",
                    "model_id": "agent-e2e-extractor",
                    "template_version": "v1",
                    "input_snapshot_hash": hashlib.sha256(
                        f"{run_id}:session-2".encode()
                    ).hexdigest(),
                },
                "confirmation": "SUBMIT",
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        reviewed_conflict = _review(
            client,
            tokens["reviewer"],
            str(_structured(conflict_proposal)["proposal_id"]),
            f"e2e-s2-review-{run_id}",
            "CONFLICT_CONFIRMED",
        )
        issue_id = str(reviewed_conflict["open_issue_id"])
        issue = _body(
            client.get(
                f"/v1/open-issues/{issue_id}", headers=_headers(tokens["reader"])
            ),
            200,
            "issue",
        )
        head = _body(
            client.get(f"/v1/claims/{claim_id}", headers=_headers(tokens["reader"])),
            200,
            "head",
        )
        _require(head["claim_version_id"] == version_v1, "S2_HEAD_MOVED")
        generic_conflict = _adapter(
            "generic",
            "recall",
            {
                "query": query,
                "build_context": True,
                "active_goal": "select Python runtime",
            },
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(generic_conflict["status"] == "ABSTAINED", "S2_GENERIC_NOT_ABSTAINED")
        _require(
            issue_id in generic_conflict["open_issue_ids"], "S2_GENERIC_ISSUE_OMITTED"
        )
        sections = generic_conflict["context"]["protected_sections"]
        open_issues = sections["OPEN ISSUES"]
        _require(
            open_issues and open_issues[0]["issue_id"] == issue_id,
            "S2_CAPSULE_ISSUE_MISSING",
        )
        _require(open_issues[0]["branches"], "S2_CAPSULE_BRANCHES_MISSING")
        _require(open_issues[0]["discharge_rule"], "S2_CAPSULE_DISCHARGE_MISSING")
        mcp_conflict = _mcp(
            "reader",
            "milai_recall",
            {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
            base_url=base_url,
            token=tokens["reader"],
        )
        mcp_conflict_body = _structured(mcp_conflict)
        _require(mcp_conflict_body["status"] == "ABSTAINED", "S2_MCP_NOT_ABSTAINED")
        _require(
            issue_id in mcp_conflict_body["open_issue_ids"], "S2_MCP_ISSUE_OMITTED"
        )
        langgraph_conflict = _adapter(
            "langgraph",
            "recall",
            {
                "query": query,
                "turn": 2,
                "active_goal": "select Python runtime",
                "constraints": [
                    "preserve both Evidence branches",
                    "do not infer certainty",
                ],
            },
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(langgraph_conflict["status"] == "ABSTAINED", "S2_NATIVE_NOT_ABSTAINED")
        _require(
            issue_id in langgraph_conflict["open_issue_ids"], "S2_NATIVE_ISSUE_OMITTED"
        )
        autogen_conflict = _adapter(
            "autogen",
            "recall",
            {"query": query},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(autogen_conflict["data_only"], "S2_AUTOGEN_NOT_DATA_ONLY")
        _require(
            issue_id in autogen_conflict["metadata"]["open_issue_ids"],
            "S2_AUTOGEN_ISSUE_OMITTED",
        )
        wire_conflict = _mcp_wire(
            "milai_recall",
            {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
            base_url=base_url,
            token=tokens["reader"],
        )
        wire_body = _wire_structured(wire_conflict)
        _require(wire_body["status"] == "ABSTAINED", "S2_WIRE_HOST_NOT_ABSTAINED")
        _require(issue_id in wire_body["open_issue_ids"], "S2_WIRE_HOST_ISSUE_OMITTED")
        phases.append(
            {
                "session": 2,
                "status": "PASS",
                "head_unchanged": True,
                "open_issue_id": issue_id,
                "issue_status": issue["status"],
                "branches": sorted(item["relation_type"] for item in issue["branches"]),
                "discharge_rule_preserved": True,
                "adapter_traces": {
                    "generic": generic_conflict["trace_id"],
                    "mcp": mcp_conflict_body["trace_id"],
                    "langgraph": langgraph_conflict["trace_id"],
                    "autogen": autogen_conflict["metadata"]["trace_id"],
                    "independent_mcp_wire": wire_body["trace_id"],
                },
            }
        )
        if phase_hook is not None:
            phase_hook(
                "conflict",
                {
                    "base_url": base_url,
                    "reader_token": tokens["reader"],
                    "marker": marker,
                    "claim_id": claim_id,
                    "open_issue_id": issue_id,
                    "trace_id": mcp_conflict_body["trace_id"],
                },
            )

        ci_capture = _adapter(
            "langgraph",
            "capture",
            {
                "session_id": f"session-3-{run_id}",
                "turn_id": "ci",
                "tool_name": "ci",
                "subject_id": marker,
                "observed_at": observed_at,
                "content": f"{marker} CI matrix passes Python 3.12",
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        ci_evidence = ci_capture["milai_capture"]["evidence"]
        _require(isinstance(ci_evidence, dict), "S3_NATIVE_CAPTURE_FAILED")
        runtime_capture = _adapter(
            "langgraph",
            "capture",
            {
                "session_id": f"session-3-{run_id}",
                "turn_id": "runtime",
                "tool_name": "runtime",
                "subject_id": marker,
                "observed_at": observed_at,
                "content": f"{marker} runtime probe reports Python 3.12",
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        runtime_evidence = runtime_capture["milai_capture"]["evidence"]
        _require(isinstance(runtime_evidence, dict), "S3_NATIVE_RUNTIME_CAPTURE_FAILED")
        resolution_proposal = _adapter(
            "generic",
            "proposal",
            {
                "operation_id": f"e2e-s3-proposal-{run_id}",
                "proposal": {
                    "target_claim_id": claim_id,
                    "operation": "SUPERSEDE",
                    "expected_version_id": version_v1,
                    "proposed_patch": {
                        "payload": {"python": "3.12", "marker": marker},
                        "authority": "ACTION_SAFE",
                        "confidence": 0.99,
                        "resolve_issue_id": issue_id,
                        "expected_issue_revision": issue["revision"],
                        "addressed_branches": ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"],
                    },
                    "supporting_evidence_refs": [
                        ci_evidence["evidence_id"],
                        runtime_evidence["evidence_id"],
                    ],
                    "scope_predicate": {"project_ids": ["milai-agent-e2e"]},
                    "requested_authority": "ACTION_SAFE",
                    "derivation_policy_id": "agent-e2e-v1",
                    "model_id": "agent-e2e-extractor",
                    "template_version": "v1",
                    "input_snapshot_hash": hashlib.sha256(
                        f"{run_id}:session-3".encode()
                    ).hexdigest(),
                },
            },
            base_url=base_url,
            token=tokens["submitter"],
        )
        resolved = _review(
            client,
            tokens["reviewer"],
            str(resolution_proposal["proposal_id"]),
            f"e2e-s3-review-{run_id}",
            "DISCHARGE_RULE_VERIFIED",
        )
        version_v2 = str(resolved["claim_version_id"])
        _require(version_v2 != version_v1, "S3_VERSION_NOT_SUPERSEDED")
        _require(worker.run_once() > 0, "S3_WORKER_DID_NOT_PROJECT")
        generic_v2 = _adapter(
            "generic",
            "recall",
            {"query": query},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(_accepted_version(generic_v2) == version_v2, "S3_V2_NOT_RECALLED")
        revoked = _mcp(
            "operator",
            "milai_evidence_revoke",
            {
                "evidence_id": runtime_evidence["evidence_id"],
                "operation_id": f"e2e-s3-revoke-{run_id}",
                "reason_code": "USER_REQUEST",
                "confirmation": "REVOKE",
            },
            base_url=base_url,
            token=tokens["operator"],
        )
        revoke_body = _structured(revoked)
        _require(
            revoke_body["canonical_block_status"] == "APPLIED", "S3_REVOKE_NOT_BLOCKED"
        )
        deletion_request_id = str(revoke_body["deletion_request_id"])
        stale_generic = _adapter(
            "generic",
            "recall",
            {"query": query, "consistency": "EVENTUAL"},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(stale_generic["status"] == "ABSTAINED", "S3_GENERIC_STALE_VISIBLE")
        _require(
            "GROUNDING_BLOCKED" in _trace_reasons(stale_generic),
            "S3_GENERIC_BLOCK_MISSING",
        )
        stale_mcp = _mcp(
            "reader",
            "milai_recall",
            {"query": query, "consistency": "EVENTUAL", "limit": 5},
            base_url=base_url,
            token=tokens["reader"],
        )
        stale_mcp_body = _structured(stale_mcp)
        _require(stale_mcp_body["status"] == "ABSTAINED", "S3_MCP_STALE_VISIBLE")
        stale_mcp_trace = _mcp(
            "reader",
            "milai_trace_get",
            {"trace_id": stale_mcp_body["trace_id"]},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(
            "GROUNDING_BLOCKED"
            in {
                item["reject_reason"]
                for item in _structured(stale_mcp_trace)["rejected_candidates"]
            },
            "S3_MCP_BLOCK_MISSING",
        )
        stale_native = _adapter(
            "langgraph",
            "recall",
            {"query": query, "turn": 3, "consistency": "EVENTUAL"},
            base_url=base_url,
            token=tokens["reader"],
        )
        _require(stale_native["status"] == "ABSTAINED", "S3_NATIVE_STALE_VISIBLE")
        _require(
            "GROUNDING_BLOCKED"
            in {
                item["reject_reason"]
                for item in stale_native["trace"]["rejected_candidates"]
            },
            "S3_NATIVE_BLOCK_MISSING",
        )
        reopened = _body(
            client.get(
                f"/v1/open-issues/{issue_id}", headers=_headers(tokens["reader"])
            ),
            200,
            "reopened_issue",
        )
        _require(reopened["status"] == "WAITING_EVIDENCE", "S3_ISSUE_NOT_REOPENED")
        _require(
            issue_id in stale_generic["open_issue_ids"], "S3_REOPENED_ISSUE_OMITTED"
        )
        deletion_status = _mcp(
            "operator",
            "milai_deletion_status_get",
            {"evidence_id": runtime_evidence["evidence_id"]},
            base_url=base_url,
            token=tokens["operator"],
        )
        _require(
            _structured(deletion_status)["canonical_block_status"] == "APPLIED",
            "S3_DELETION_STATUS_NOT_FAIL_CLOSED",
        )
        _require(worker.run_once() > 0, "S3_WORKER_DID_NOT_PURGE")
        final_deletion = _body(
            client.get(
                f"/v1/deletion-requests/{deletion_request_id}",
                headers=_headers(tokens["reader"]),
            ),
            200,
            "final_deletion",
        )
        _require(
            final_deletion["derived_purge_status"] == "COMPLETED", "S3_PURGE_INCOMPLETE"
        )
        phases.append(
            {
                "session": 3,
                "status": "PASS",
                "claim_version_id": version_v2,
                "revoked_evidence_id": runtime_evidence["evidence_id"],
                "deletion_request_id": deletion_request_id,
                "issue_status_after_revoke": reopened["status"],
                "stale_projection_reject_reason": "GROUNDING_BLOCKED",
                "adapter_traces": {
                    "generic": stale_generic["trace_id"],
                    "mcp": stale_mcp_body["trace_id"],
                    "langgraph": stale_native["trace_id"],
                },
                "physical_reconciliation": {
                    "derived_purge_status": final_deletion["derived_purge_status"],
                    "primary_bytes_status": final_deletion["primary_bytes_status"],
                },
            }
        )
        if phase_hook is not None:
            phase_hook(
                "revoked",
                {
                    "base_url": base_url,
                    "reader_token": tokens["reader"],
                    "marker": marker,
                    "claim_id": claim_id,
                    "open_issue_id": issue_id,
                    "trace_id": stale_mcp_body["trace_id"],
                },
            )
        _stop_api(api_process)
        disconnected_started = time.monotonic()
        disconnected_terminal: dict[str, Any]
        try:
            disconnected = _mcp(
                "reader",
                "milai_recall",
                {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
                base_url=base_url,
                token=tokens["reader"],
            )
        except E2EFailure as exc:
            disconnected_terminal = {
                "terminal": "HOST_FAILED_CLOSED",
                "error_type": type(exc).__name__,
            }
        else:
            _require(
                disconnected.get("is_error") is True,
                "DISCONNECTED_RUNTIME_DID_NOT_FAIL_CLOSED",
            )
            disconnected_terminal = {"terminal": "MCP_ERROR_RESULT"}
        disconnected_seconds = time.monotonic() - disconnected_started
        _require(disconnected_seconds < 20, "DISCONNECTED_RUNTIME_NOT_BOUNDED")
        phases.append(
            {
                "session": "runtime-disconnected",
                "status": "PASS",
                **disconnected_terminal,
                "duration_seconds": round(disconnected_seconds, 6),
                "stale_memory_used": False,
            }
        )
        if phase_hook is not None:
            phase_hook(
                "canonical_down",
                {
                    "base_url": base_url,
                    "reader_token": tokens["reader"],
                    "marker": marker,
                },
            )
        return {
            "marker": marker,
            "phases": phases,
            "mcp_hosts": [
                {
                    "host": "official-python-client-stdio",
                    "protocol": mcp_v1["protocol_version"],
                },
                {
                    "host": wire_conflict["host"],
                    "protocol": wire_conflict["protocol_version"],
                },
            ],
            "adapters": ["generic-sdk", "mcp-stdio", "langgraph", "autogen-read"],
            "functional_cases": {
                "F0-03": "PASS",
                "F0-04": "PASS",
                "F0-05": "PASS",
                "F0-06": "PASS",
                "F0-07": "PASS",
                "F0-08": "PASS",
                "F0-09": "PASS",
            },
            "hard_failures": [],
        }
    finally:
        active_error = sys.exc_info()[1]
        _stop_api(api_process)
        worker_database.close()
        if active_error is not None and api_process.stderr is not None:
            safe_log = api_process.stderr.read().decode("utf-8", errors="replace")[
                -4_000:
            ]
            raise E2EFailure(
                f"{active_error}:API_LOG_TAIL:{safe_log}"
            ) from active_error


def _write_report(path: Path, report: dict[str, Any]) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Isolated three-session Agent integration E2E"
    )
    parser.add_argument("--env-file", type=Path, default=_ROOT / "runtime/.env")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    load_runtime_environment(args.env_file)
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise SystemExit("owner, worker and audit database URLs are required")

    run_id = uuid4().hex
    database_name = f"milai_smoke_{run_id[:20]}"
    database_urls = {
        "owner": _database_url(owner_source, database_name),
        "api": _database_url(source.database_dsn, database_name),
        "steward": _database_url(source.steward_database_dsn, database_name),
        "worker": _database_url(worker_source, database_name),
        "audit": _database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    report: dict[str, Any] = {
        "schema": "milai.agent-integration-three-session-e2e.v1",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "data_mode": "SYNTHETIC_ONLY",
        "status": "BLOCKED",
        "database": database_name,
    }
    created = False
    try:
        _create_database(owner_source, database_name)
        created = True
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")
        with tempfile.TemporaryDirectory(
            prefix="milai-agent-e2e-blobs-"
        ) as blob_directory:
            settings = _smoke_settings(
                source,
                database_urls,
                Path(blob_directory),
                uuid4(),
                uuid4(),
                tokens,
                _free_loopback_port(),
            )
            prepare_runtime_directories(settings)
            report.update(_run_fixture(settings, database_urls, tokens, run_id))
        report["status"] = "PASS"
    except Exception as exc:
        report["failure"] = type(exc).__name__
        report["failure_code"] = str(exc)
        raise
    finally:
        report["cleanup"] = (
            _drop_database(owner_source, database_name)
            if created
            else {"status": "NOT_CREATED"}
        )
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        secrets_absent = all(token not in serialized for token in tokens.values())
        functional_cases = report.setdefault("functional_cases", {})
        functional_cases["F0-10"] = (
            "PASS"
            if report["cleanup"].get("status") == "PASS" and secrets_absent
            else "FAILED"
        )
        report["cleanup"]["secret_artifacts_absent"] = secrets_absent
        report["finished_at"] = datetime.now(UTC).isoformat()
        _write_report(args.report, report)
    if report["functional_cases"]["F0-10"] != "PASS":
        raise E2EFailure("F0_CLEANUP_INCOMPLETE")


if __name__ == "__main__":
    main()
