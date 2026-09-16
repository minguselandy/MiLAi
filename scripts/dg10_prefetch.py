from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from scripts import dg10_memory_quality as quality
from scripts import dg10_remediation as remediation


class PrefetchError(quality.MemoryQualityError):
    pass


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class HostPrefetchHarness:
    """T3a: deterministic host recall followed by exactly one answer call."""

    def __init__(
        self,
        *,
        provider: quality.MemoryProvider,
        answer_client: quality.AnswerClient,
        token_counter: quality.TokenCounter,
        ledger: remediation.AttemptLedger,
    ) -> None:
        self.provider = provider
        self.answer_client = answer_client
        self.token_counter = token_counter
        self.ledger = ledger

    def run(self, *, case_id: str, question: str) -> tuple[dict[str, Any], dict[str, Any]]:
        attempt_id = self.ledger.start_attempt(
            phase="SERVING_T3A_PREFETCH",
            arm="T3a",
            case_id=case_id,
            planned_model_calls=1,
            planned_mcp_calls=1,
        )
        try:
            context = self.provider.retrieve(case_id=case_id, question=question)
        except Exception:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="PROVIDER_REQUEST_FAILED",
                redacted_public_receipt_digest=_sha256(
                    f"{attempt_id}:retrieval-failed"
                ),
            )
            raise
        try:
            if context.retrieval_request_id is not None:
                self.ledger.record_mcp_accepted(
                    attempt_id, context.retrieval_request_id
                )
            quality.validate_memory_context(
                context,
                arm="MILAI_RETRIEVAL",
                question=question,
                token_counter=self.token_counter,
            )
            if context.retrieval_request_id is None:
                raise PrefetchError("T3a prefetch lacks MCP request identity")
            if context.retrieval_receipt_sha256 is None:
                raise PrefetchError("T3a prefetch lacks MCP receipt digest")
            self.ledger.record_mcp_terminal(
                attempt_id,
                raw_sidecar_digest=context.retrieval_receipt_sha256,
            )
        except Exception:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="AGENT_POLICY_REJECTED",
                redacted_public_receipt_digest=_sha256(
                    f"{attempt_id}:retrieval-policy-failed"
                ),
            )
            raise
        messages = quality.render_messages(question, context.text)
        try:
            completion = self.answer_client.complete(
                messages=messages,
                temperature=quality.TEMPERATURE,
                seed=quality.SEED,
                max_output_tokens=quality.MAX_OUTPUT_TOKENS,
                request_key=attempt_id,
            )
        except Exception:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="PROVIDER_REQUEST_FAILED",
                redacted_public_receipt_digest=_sha256(f"{attempt_id}:provider-failed"),
            )
            raise
        try:
            self.ledger.record_provider_accepted(
                attempt_id, completion.native_request_id
            )
            self.ledger.record_provider_terminal(
                attempt_id,
                usage={
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "cached_input_tokens": completion.cached_input_tokens,
                    "reasoning_tokens": completion.reasoning_tokens,
                },
                raw_sidecar_digest=completion.raw_receipt_sha256,
            )
        except Exception:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="PROVIDER_TERMINAL_MISSING",
                redacted_public_receipt_digest=_sha256(
                    f"{attempt_id}:provider-accounting-failed"
                ),
            )
            raise
        try:
            answer = quality.parse_structured_answer(completion.content)
        except quality.MemoryQualityError:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=True,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="OUTPUT_SCHEMA_INVALID",
                redacted_public_receipt_digest=_sha256(f"{attempt_id}:schema-failed"),
            )
            raise
        self.ledger.finalize(
            attempt_id,
            agent_terminal=True,
            parser_terminal=True,
            retention_state="retained",
            failure_reason_code="SUCCESS",
            redacted_public_receipt_digest=_sha256(f"{attempt_id}:{_sha256(answer)}"),
        )
        record = {
            "schema": "milai.dg10.prefetch-execution.v1",
            "candidate_id": remediation.CANDIDATE,
            "attempt_id": attempt_id,
            "case_id": case_id,
            "tier": "T3a",
            "routing": "HOST_DETERMINISTIC_PREFETCH",
            "answer_model_calls": 1,
            "mcp_calls": 1,
            "tool_decision_model_calls": 0,
            "tool_schema_tokens": 0,
            "tool_transcript_tokens": 0,
            "memory_target_tokens": context.target_token_count,
            "compact_renderer_sha256": quality._renderer_sha256(),
            "query_equals_original_question": context.query_equals_original_question,
            "native_request_id_sha256": _sha256(completion.native_request_id),
            "mcp_request_id_sha256": _sha256(context.retrieval_request_id),
            "answer_sha256": _sha256(answer),
        }
        validate_prefetch_record(record)
        sidecar = {
            "schema": "milai.dg10.prefetch-execution-sidecar.v1",
            "attempt_id": attempt_id,
            "question": question,
            "memory_context": context.text,
            "messages": messages,
            "raw_model_output": completion.content,
            "answer": answer,
        }
        return record, sidecar


def validate_prefetch_record(record: Mapping[str, Any]) -> None:
    expected = {
        "schema",
        "candidate_id",
        "attempt_id",
        "case_id",
        "tier",
        "routing",
        "answer_model_calls",
        "mcp_calls",
        "tool_decision_model_calls",
        "tool_schema_tokens",
        "tool_transcript_tokens",
        "memory_target_tokens",
        "compact_renderer_sha256",
        "query_equals_original_question",
        "native_request_id_sha256",
        "mcp_request_id_sha256",
        "answer_sha256",
    }
    if set(record) != expected:
        raise PrefetchError("T3a record key set drift")
    if (
        record.get("schema") != "milai.dg10.prefetch-execution.v1"
        or record.get("candidate_id") != remediation.CANDIDATE
        or record.get("tier") != "T3a"
        or record.get("routing") != "HOST_DETERMINISTIC_PREFETCH"
        or record.get("answer_model_calls") != 1
        or record.get("mcp_calls") != 1
        or record.get("tool_decision_model_calls") != 0
        or record.get("tool_schema_tokens") != 0
        or record.get("tool_transcript_tokens") != 0
        or record.get("query_equals_original_question") is not True
        or not isinstance(record.get("memory_target_tokens"), int)
        or int(record["memory_target_tokens"]) > quality.MAX_MEMORY_TOKENS
        or record.get("compact_renderer_sha256") != quality._renderer_sha256()
    ):
        raise PrefetchError("T3a one-round truth contract failed")
    for key in ("native_request_id_sha256", "mcp_request_id_sha256", "answer_sha256"):
        remediation._require_sha256(record.get(key), key)


def validate_t3b_characterization(record: Mapping[str, Any]) -> None:
    if (
        record.get("tier") != "T3b"
        or record.get("routing") != "MODEL_DECIDES_MCP"
        or record.get("model_calls") != 2
        or record.get("mcp_calls") != 1
        or record.get("tool_decision_model_calls") != 1
        or not isinstance(record.get("tool_schema_tokens"), int)
        or int(record["tool_schema_tokens"]) <= 0
        or not isinstance(record.get("tool_transcript_tokens"), int)
        or int(record["tool_transcript_tokens"]) <= 0
        or record.get("role") != "CHARACTERIZATION_ONLY"
    ):
        raise PrefetchError("T3b two-round characterization contract failed")
