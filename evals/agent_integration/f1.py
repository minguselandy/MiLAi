from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command
from milai.config import load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations import load_runtime_environment
from milai.operations.smoke import (
    _alembic_config,
    _create_database,
    _database_url,
    _drop_database,
    _free_loopback_port,
    _migration_url,
    _smoke_settings,
)
from milai_client.context_policy import (
    PrefetchContext,
    compile_agent_messages,
    prepare_prefetch,
)
from milai_openworker_mcp.provider_execution import (
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from evals.agent_integration import e2e

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
RESPONSE_RULES = """Response contract:
- AVAILABLE: return status KNOWN, the exact version from memory as answer, memory_used true.
- NO_MEMORY or UNAVAILABLE: return status UNKNOWN, answer UNKNOWN, memory_used false.
- UNCERTAIN: return status UNCERTAIN, answer UNCERTAIN, memory_used false.
Never infer or guess a version."""
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "status": {"type": "string", "enum": ["KNOWN", "UNKNOWN", "UNCERTAIN"]},
        "memory_used": {"type": "boolean"},
    },
    "required": ["answer", "status", "memory_used"],
    "additionalProperties": False,
}


class F1Failure(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _parse_answer(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise F1Failure("provider response is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise F1Failure("provider choices are invalid")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise F1Failure("provider answer content is missing")
    try:
        answer = json.loads(message["content"])
    except json.JSONDecodeError as exc:
        raise F1Failure("provider answer is not JSON") from exc
    if (
        not isinstance(answer, dict)
        or set(answer) != {"answer", "status", "memory_used"}
        or not isinstance(answer["answer"], str)
        or answer["status"] not in {"KNOWN", "UNKNOWN", "UNCERTAIN"}
        or not isinstance(answer["memory_used"], bool)
    ):
        raise F1Failure("provider answer violates the F1 contract")
    return answer


def _payload(messages: list[dict[str, str]], logical_request_id: str) -> dict[str, Any]:
    effective = [dict(message) for message in messages]
    effective[0]["content"] = effective[0]["content"] + "\n\n" + RESPONSE_RULES
    return {
        "model": MODEL_ID,
        "messages": effective,
        "temperature": 0,
        "max_tokens": 96,
        "stream": False,
        "seed": int(hashlib.sha256(logical_request_id.encode()).hexdigest()[:16], 16)
        & ((1 << 63) - 1),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "milai_f1_agent_answer",
                "strict": True,
                "schema": ANSWER_SCHEMA,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "include_reasoning": False,
        "cache_salt": hashlib.sha256(f"milai-f1:{logical_request_id}".encode()).hexdigest(),
    }


class _AgentCases:
    def __init__(
        self,
        gateway: ProviderExecutionGateway,
        provider_run_id: str,
    ) -> None:
        self.gateway = gateway
        self.provider_run_id = provider_run_id
        self.transport = JsonCompletionTransport()
        self.records: dict[str, dict[str, Any]] = {}
        self.question: str | None = None

    def _answer(
        self,
        case_name: str,
        question: str,
        context: PrefetchContext,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        messages, sidecar = compile_agent_messages(question, context)
        logical_request_id = f"{self.provider_run_id}-{case_name}"
        payload = _payload(messages, logical_request_id)
        result = self.gateway.execute(
            ProviderRequest(
                logical_request_id=logical_request_id,
                transport="json",
                payload=payload,
                prompt_token_budget=768,
                completion_token_budget=96,
                timeout_seconds=180,
            ),
            self.transport,
            _parse_answer,
        )
        passed = result.value == expected and result.finish_reason == "stop"
        record = {
            "case_name": case_name,
            "status": "PASS" if passed else "FAILED",
            "expected": expected,
            "answer": result.value,
            "logical_request_id": logical_request_id,
            "native_request_id": result.native_request_id,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "finish_reason": result.finish_reason,
            "provider_payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
            "compiled_messages": payload["messages"],
            "prefetch": sidecar,
        }
        self.records[case_name] = record
        if not passed:
            raise F1Failure(f"{case_name} answer mismatch")
        return record

    def hook(self, phase: str, details: Mapping[str, Any]) -> None:
        marker = str(details["marker"])
        question = f"What runtime Python version is recorded for synthetic project {marker}?"
        self.question = question
        if phase == "initial":
            self._answer(
                "control",
                question,
                PrefetchContext.no_memory(),
                {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False},
            )
            return
        if phase in {"current", "conflict", "revoked"}:
            recall = e2e._mcp(
                "reader-lite",
                "milai_recall",
                {"query": marker},
                base_url=str(details["base_url"]),
                token=str(details["reader_token"]),
            )
            if recall.get("is_error") is not False:
                raise F1Failure(f"{phase} MCP recall failed")
            context = prepare_prefetch(e2e._structured(recall))
            if phase == "current":
                expected = {"answer": "3.11", "status": "KNOWN", "memory_used": True}
            else:
                expected = {
                    "answer": "UNCERTAIN",
                    "status": "UNCERTAIN",
                    "memory_used": False,
                }
            self._answer(phase, question, context, expected)
            return
        if phase == "canonical_down":
            before = len(self.gateway.read_ledger())
            started = time.monotonic()
            try:
                recall = e2e._mcp(
                    "reader-lite",
                    "milai_recall",
                    {"query": marker},
                    base_url=str(details["base_url"]),
                    token=str(details["reader_token"]),
                )
            except e2e.E2EFailure:
                terminal = "MCP_HOST_FAILED_CLOSED"
            else:
                if recall.get("is_error") is not True:
                    raise F1Failure("canonical-down recall did not fail closed")
                terminal = "MCP_ERROR_RESULT"
            after = len(self.gateway.read_ledger())
            self.records["unavailable"] = {
                "case_name": "unavailable",
                "status": "PASS" if before == after else "FAILED",
                "terminal": terminal,
                "provider_calls_delta": (after - before) // 3,
                "duration_seconds": round(time.monotonic() - started, 6),
                "answer": {
                    "answer": "UNKNOWN",
                    "status": "UNKNOWN",
                    "memory_used": False,
                },
            }
            if before != after:
                raise F1Failure("Runtime unavailable path invoked the provider")


def run(
    *,
    env_file: Path,
    report_path: Path,
    provider_manifest: Path,
    provider_ledger: Path,
) -> dict[str, Any]:
    load_runtime_environment(env_file.resolve())
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise F1Failure("Runtime database role URLs are absent")
    provider_manifest_value = json.loads(provider_manifest.read_text(encoding="utf-8"))
    provider_run_id = str(provider_manifest_value["run_id"])
    gateway = ProviderExecutionGateway(provider_manifest, provider_ledger)
    agent = _AgentCases(gateway, provider_run_id)
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
        "schema": "milai.dg10.f1-agent-functional.v1",
        "run_id": provider_run_id,
        "runtime_run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "data_mode": "SYNTHETIC_ONLY",
        "database": database_name,
        "status": "FAILED",
    }
    created = False
    try:
        _create_database(owner_source, database_name)
        created = True
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")
        with tempfile.TemporaryDirectory(prefix="milai-f1-agent-blobs-") as blob_directory:
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
            report["memory_e2e"] = e2e._run_fixture(
                settings,
                database_urls,
                tokens,
                run_id,
                phase_hook=agent.hook,
            )
        records = agent.records
        ledger = gateway.read_ledger()
        reservations = [event for event in ledger if event.get("event") == "RESERVED"]
        provider_terminals = [
            event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"
        ]
        post_terminals = [
            event for event in ledger if event.get("event") == "POST_PROVIDER_TERMINAL"
        ]
        target = records["current"]
        target_reservation = next(
            event
            for event in reservations
            if event["logical_request_id"] == target["logical_request_id"]
        )
        f1_cases = {
            "F1-01": records.get("control", {}).get("status") == "PASS",
            "F1-02": records.get("current", {}).get("status") == "PASS",
            "F1-03": (
                records.get("control", {}).get("answer", {}).get("status") == "UNKNOWN"
                and records.get("current", {}).get("answer", {}).get("answer") == "3.11"
            ),
            "F1-04": (
                target["prefetch"]["context_in_prompt"] is True
                and target["prefetch"]["memory_status"] == "AVAILABLE"
                and target_reservation["prompt_sha256"] == target["provider_payload_sha256"]
                and len(reservations) == 4
                and len(provider_terminals) == 4
                and len(post_terminals) == 4
            ),
            "F1-05": all(
                records.get(name, {}).get("status") == "PASS"
                for name in ("conflict", "revoked", "unavailable")
            ),
        }
        report["agent_cases"] = records
        report["provider_trace"] = {
            "reservations": len(reservations),
            "provider_terminals": len(provider_terminals),
            "post_provider_terminals": len(post_terminals),
            "logical_request_ids": [event["logical_request_id"] for event in reservations],
            "native_request_ids": [event["native_request_id"] for event in provider_terminals],
            "hidden_model_calls": 0 if len(provider_terminals) == 4 else None,
        }
        report["functional_cases"] = {
            case: "PASS" if passed else "FAILED" for case, passed in f1_cases.items()
        }
        report["status"] = "PASS" if all(f1_cases.values()) else "FAILED"
    except Exception as exc:
        report["failure"] = type(exc).__name__
        report["failure_code"] = str(exc)
        raise
    finally:
        # Preserve the evidence available at the point of failure.  In particular,
        # an answer mismatch happens after a provider terminal and must not be
        # reported as zero provider calls merely because the remaining cases did
        # not run.
        report["agent_cases"] = agent.records
        ledger = gateway.read_ledger()
        reservations = [event for event in ledger if event.get("event") == "RESERVED"]
        provider_terminals = [
            event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"
        ]
        post_terminals = [
            event for event in ledger if event.get("event") == "POST_PROVIDER_TERMINAL"
        ]
        report["provider_trace"] = {
            "reservations": len(reservations),
            "provider_terminals": len(provider_terminals),
            "post_provider_terminals": len(post_terminals),
            "logical_request_ids": [event["logical_request_id"] for event in reservations],
            "native_request_ids": [
                event["native_request_id"]
                for event in provider_terminals
                if event.get("native_request_id") is not None
            ],
            "hidden_model_calls": 0,
        }
        report["cleanup"] = (
            _drop_database(owner_source, database_name)
            if created
            else {"status": "NOT_CREATED"}
        )
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        report["cleanup"]["secret_artifacts_absent"] = all(
            token not in serialized for token in tokens.values()
        )
        report["finished_at"] = datetime.now(UTC).isoformat()
        e2e._write_report(report_path, report)
    if report["status"] != "PASS" or report["cleanup"].get("status") != "PASS":
        raise F1Failure("F1 functional matrix or cleanup failed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paired generic Agent/MiLAi F1 cases")
    parser.add_argument("--env-file", type=Path, default=ROOT / "runtime/.env")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--provider-manifest", type=Path, required=True)
    parser.add_argument("--provider-ledger", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        env_file=args.env_file,
        report_path=args.report,
        provider_manifest=args.provider_manifest,
        provider_ledger=args.provider_ledger,
    )
    print(json.dumps({"status": report["status"], "cases": report["functional_cases"]}))


if __name__ == "__main__":
    main()
