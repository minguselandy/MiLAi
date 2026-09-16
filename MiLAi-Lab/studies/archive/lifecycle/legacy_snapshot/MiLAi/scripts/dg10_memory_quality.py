from __future__ import annotations

import hashlib
import inspect
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts import dg10_remediation as remediation

ARMS = ("NO_MEMORY", "NAIVE_RAG", "MILAI_RETRIEVAL")
SYSTEM_PROMPT = (
    "Answer the question using only the supplied memory when relevant. "
    "If evidence is insufficient, say so. Return one JSON object with exactly "
    "one string field named answer."
)
MAX_MEMORY_TOKENS = 512
MAX_OUTPUT_TOKENS = 256
SEED = 20260822
TEMPERATURE = 0
TOPOLOGY_CONTRACT = remediation.ROOT / (
    "docs/contracts/DG-10-memory-quality-topology-candidate.4.json"
)


class MemoryQualityError(remediation.RemediationError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryContext:
    arm: str
    text: str
    target_token_count: int
    evidence_ids: tuple[str, ...]
    retrieval_request_id: str | None
    retrieval_receipt_sha256: str | None
    query_sha256: str
    query_equals_original_question: bool
    ranking_source: str
    governed_ingest: bool
    canonical_gate: bool
    full_session_corpus: bool
    artificial_marker: bool
    shared_naive_ranking: bool


@dataclass(frozen=True, slots=True)
class Completion:
    native_request_id: str
    content: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    finish_reason: str
    raw_receipt_sha256: str


class MemoryProvider(Protocol):
    def retrieve(self, *, case_id: str, question: str) -> MemoryContext: ...


class AnswerClient(Protocol):
    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: int,
        seed: int,
        max_output_tokens: int,
        request_key: str,
    ) -> Completion: ...


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _renderer_sha256() -> str:
    return hashlib.sha256(inspect.getsource(render_messages).encode()).hexdigest()


def render_messages(question: str, memory: str) -> list[dict[str, str]]:
    memory_value = memory if memory else "(none)"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "<memory>\n"
                + memory_value
                + "\n</memory>\n<question>\n"
                + question
                + "\n</question>"
            ),
        },
    ]


def parse_structured_answer(content: str) -> str:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise MemoryQualityError("answer output is not JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"answer"}
        or not isinstance(value["answer"], str)
    ):
        raise MemoryQualityError("answer output schema is invalid")
    return value["answer"]


def validate_memory_context(
    context: MemoryContext,
    *,
    arm: str,
    question: str,
    token_counter: TokenCounter,
) -> None:
    if context.arm != arm or arm not in ARMS:
        raise MemoryQualityError("memory arm identity mismatch")
    observed_tokens = token_counter.count(context.text)
    if observed_tokens != context.target_token_count or observed_tokens > MAX_MEMORY_TOKENS:
        raise MemoryQualityError("memory target-tokenizer ceiling or recount failed")
    if context.query_sha256 != _sha256_text(question):
        raise MemoryQualityError("retrieval query hash differs from original question")
    if not context.query_equals_original_question or context.artificial_marker:
        raise MemoryQualityError("memory query substitution or artificial marker detected")
    if arm == "NO_MEMORY":
        if (
            context.text
            or context.evidence_ids
            or context.retrieval_request_id is not None
            or context.retrieval_receipt_sha256 is not None
            or context.ranking_source != "NONE"
            or context.governed_ingest
            or context.canonical_gate
            or context.full_session_corpus
        ):
            raise MemoryQualityError("NO_MEMORY arm contains retrieval data")
    elif arm == "NAIVE_RAG":
        if (
            context.ranking_source != "NAIVE_RAG_FROZEN_BASELINE"
            or not context.text
            or not context.evidence_ids
            or context.retrieval_request_id is not None
            or context.retrieval_receipt_sha256 is not None
            or context.governed_ingest
            or context.canonical_gate
            or context.full_session_corpus
        ):
            raise MemoryQualityError("NAIVE_RAG ranking source drift")
    else:
        if (
            context.ranking_source != "MILAI_RUNTIME_CANONICAL_GATE"
            or not context.governed_ingest
            or not context.canonical_gate
            or not context.full_session_corpus
            or not context.query_equals_original_question
            or context.artificial_marker
            or context.shared_naive_ranking
            or context.retrieval_request_id is None
            or context.retrieval_receipt_sha256 is None
        ):
            raise MemoryQualityError("MiLAi retrieval governance/topology contract failed")


class TrackAHarness:
    def __init__(
        self,
        *,
        answer_client: AnswerClient,
        token_counter: TokenCounter,
        providers: Mapping[str, MemoryProvider],
        ledger: remediation.AttemptLedger,
    ) -> None:
        if set(providers) != set(ARMS):
            raise MemoryQualityError("Track A provider arm set is incomplete")
        self.answer_client = answer_client
        self.token_counter = token_counter
        self.providers = providers
        self.ledger = ledger

    def run_arm(self, *, case_id: str, question: str, arm: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if arm not in ARMS:
            raise MemoryQualityError("unknown Track A arm")
        planned_mcp_calls = int(arm == "MILAI_RETRIEVAL")
        attempt_id = self.ledger.start_attempt(
            phase="TRACK_A_MEMORY_QUALITY",
            case_id=case_id,
            arm=arm,
            planned_model_calls=1,
            planned_mcp_calls=planned_mcp_calls,
        )
        try:
            context = self.providers[arm].retrieve(
                case_id=case_id, question=question
            )
        except Exception:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="PROVIDER_REQUEST_FAILED",
                redacted_public_receipt_digest=_sha256_text(
                    f"{attempt_id}:retrieval-failed"
                ),
            )
            raise
        try:
            if context.retrieval_request_id is not None:
                self.ledger.record_mcp_accepted(
                    attempt_id, context.retrieval_request_id
                )
            validate_memory_context(
                context,
                arm=arm,
                question=question,
                token_counter=self.token_counter,
            )
            if context.retrieval_request_id is not None:
                if context.retrieval_receipt_sha256 is None:
                    raise MemoryQualityError("MCP retrieval receipt digest is absent")
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
                redacted_public_receipt_digest=_sha256_text(
                    f"{attempt_id}:retrieval-policy-failed"
                ),
            )
            raise
        messages = render_messages(question, context.text)
        try:
            completion = self.answer_client.complete(
                messages=messages,
                temperature=TEMPERATURE,
                seed=SEED,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                request_key=attempt_id,
            )
        except Exception:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="PROVIDER_REQUEST_FAILED",
                redacted_public_receipt_digest=_sha256_text(f"{attempt_id}:provider-failed"),
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
                redacted_public_receipt_digest=_sha256_text(
                    f"{attempt_id}:provider-accounting-failed"
                ),
            )
            raise
        try:
            answer = parse_structured_answer(completion.content)
        except MemoryQualityError:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=True,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="OUTPUT_SCHEMA_INVALID",
                redacted_public_receipt_digest=_sha256_text(f"{attempt_id}:schema-failed"),
            )
            raise
        public_receipt_digest = _sha256_text(f"{attempt_id}:{_sha256_text(answer)}")
        self.ledger.finalize(
            attempt_id,
            agent_terminal=True,
            parser_terminal=True,
            retention_state="retained",
            failure_reason_code="SUCCESS",
            redacted_public_receipt_digest=public_receipt_digest,
        )
        record = {
            "schema": "milai.dg10.memory-quality-arm-record.v1",
            "candidate_id": remediation.CANDIDATE,
            "attempt_id": attempt_id,
            "case_id": case_id,
            "arm": arm,
            "host_runner": type(self).__name__,
            "renderer_sha256": _renderer_sha256(),
            "system_prompt_sha256": _sha256_text(SYSTEM_PROMPT),
            "generation": {
                "temperature": TEMPERATURE,
                "seed": SEED,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
            "answer_model_calls": 1,
            "mcp_calls": planned_mcp_calls,
            "native_request_id_sha256": _sha256_text(completion.native_request_id),
            "finish_reason": completion.finish_reason,
            "usage": {
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
            },
            "memory_target_tokens": context.target_token_count,
            "memory_context_sha256": _sha256_text(context.text),
            "answer_sha256": _sha256_text(answer),
            "score_field": "answer",
            "retrieval": {
                "query_sha256": context.query_sha256,
                "query_equals_original_question": context.query_equals_original_question,
                "ranking_source": context.ranking_source,
                "governed_ingest": context.governed_ingest,
                "canonical_gate": context.canonical_gate,
                "full_session_corpus": context.full_session_corpus,
                "artificial_marker": context.artificial_marker,
                "shared_naive_ranking": context.shared_naive_ranking,
                "evidence_ids_sha256": hashlib.sha256(
                    json.dumps(sorted(context.evidence_ids)).encode()
                ).hexdigest(),
            },
        }
        sidecar = {
            "schema": "milai.dg10.memory-quality-arm-sidecar.v1",
            "attempt_id": attempt_id,
            "case_id": case_id,
            "arm": arm,
            "question": question,
            "memory_context": context.text,
            "evidence_ids": list(context.evidence_ids),
            "messages": messages,
            "raw_model_output": completion.content,
            "answer": answer,
        }
        return record, sidecar


def validate_topology(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise MemoryQualityError("Track A records are empty")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get("case_id")), []).append(record)
    native_hashes: list[str] = []
    attempt_ids: list[str] = []
    record_keys = {
        "schema",
        "candidate_id",
        "attempt_id",
        "case_id",
        "arm",
        "host_runner",
        "renderer_sha256",
        "system_prompt_sha256",
        "generation",
        "answer_model_calls",
        "mcp_calls",
        "native_request_id_sha256",
        "finish_reason",
        "usage",
        "memory_target_tokens",
        "memory_context_sha256",
        "answer_sha256",
        "score_field",
        "retrieval",
    }
    retrieval_keys = {
        "query_sha256",
        "query_equals_original_question",
        "ranking_source",
        "governed_ingest",
        "canonical_gate",
        "full_session_corpus",
        "artificial_marker",
        "shared_naive_ranking",
        "evidence_ids_sha256",
    }
    for case_id, rows in grouped.items():
        if not case_id or case_id == "None":
            raise MemoryQualityError("Track A case identity is absent")
        if {row.get("arm") for row in rows} != set(ARMS) or len(rows) != 3:
            raise MemoryQualityError(f"three-arm case coverage mismatch: {case_id}")
        invariant_keys = ("host_runner", "renderer_sha256", "system_prompt_sha256", "generation")
        for key in invariant_keys:
            if len({_canonical_record_value(row.get(key)) for row in rows}) != 1:
                raise MemoryQualityError(f"Track A invariant differs: {key}")
        for row in rows:
            if (
                set(row) != record_keys
                or row.get("schema") != "milai.dg10.memory-quality-arm-record.v1"
                or row.get("candidate_id") != remediation.CANDIDATE
                or row.get("case_id") != case_id
                or not isinstance(row.get("attempt_id"), str)
                or not row.get("attempt_id")
                or row.get("answer_model_calls") != 1
                or row.get("score_field") != "answer"
                or row.get("host_runner") != "TrackAHarness"
                or row.get("renderer_sha256") != _renderer_sha256()
                or row.get("system_prompt_sha256") != _sha256_text(SYSTEM_PROMPT)
                or not isinstance(row.get("finish_reason"), str)
                or not row.get("finish_reason")
            ):
                raise MemoryQualityError("Track A answer-call or score-field drift")
            memory_tokens = row.get("memory_target_tokens")
            if (
                not isinstance(memory_tokens, int)
                or isinstance(memory_tokens, bool)
                or not 0 <= memory_tokens <= MAX_MEMORY_TOKENS
            ):
                raise MemoryQualityError("Track A memory ceiling exceeded")
            generation = row.get("generation")
            if generation != {
                "temperature": TEMPERATURE,
                "seed": SEED,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            }:
                raise MemoryQualityError("Track A generation policy drift")
            usage = row.get("usage")
            if (
                not isinstance(usage, Mapping)
                or set(usage) != {"input_tokens", "output_tokens"}
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in usage.values()
                )
            ):
                raise MemoryQualityError("Track A usage record drift")
            for key in (
                "native_request_id_sha256",
                "memory_context_sha256",
                "answer_sha256",
            ):
                remediation._require_sha256(row.get(key), f"Track A {key}")
            retrieval = row.get("retrieval")
            if not isinstance(retrieval, Mapping) or set(retrieval) != retrieval_keys:
                raise MemoryQualityError("Track A retrieval record drift")
            remediation._require_sha256(
                retrieval.get("query_sha256"), "Track A retrieval query"
            )
            remediation._require_sha256(
                retrieval.get("evidence_ids_sha256"),
                "Track A retrieval evidence IDs",
            )
            expected_mcp_calls = int(row.get("arm") == "MILAI_RETRIEVAL")
            if row.get("mcp_calls") != expected_mcp_calls:
                raise MemoryQualityError("Track A MCP-call topology drift")
            arm = row.get("arm")
            common_retrieval = (
                retrieval.get("query_equals_original_question") is True
                and retrieval.get("artificial_marker") is False
                and retrieval.get("shared_naive_ranking") is False
            )
            if arm == "NO_MEMORY" and not (
                memory_tokens == 0
                and row.get("memory_context_sha256") == _sha256_text("")
                and retrieval.get("ranking_source") == "NONE"
                and retrieval.get("governed_ingest") is False
                and retrieval.get("canonical_gate") is False
                and retrieval.get("full_session_corpus") is False
                and retrieval.get("evidence_ids_sha256")
                == hashlib.sha256(json.dumps([]).encode()).hexdigest()
                and common_retrieval
            ):
                raise MemoryQualityError("NO_MEMORY topology record drift")
            if arm == "NAIVE_RAG" and not (
                memory_tokens > 0
                and retrieval.get("ranking_source") == "NAIVE_RAG_FROZEN_BASELINE"
                and retrieval.get("governed_ingest") is False
                and retrieval.get("canonical_gate") is False
                and retrieval.get("full_session_corpus") is False
                and common_retrieval
            ):
                raise MemoryQualityError("NAIVE_RAG topology record drift")
            attempt_ids.append(str(row["attempt_id"]))
            native_hashes.append(str(row["native_request_id_sha256"]))
        milai = next(row for row in rows if row.get("arm") == "MILAI_RETRIEVAL")
        retrieval = milai.get("retrieval")
        if not isinstance(retrieval, Mapping) or (
            retrieval.get("artificial_marker") is not False
            or retrieval.get("shared_naive_ranking") is not False
            or retrieval.get("query_equals_original_question") is not True
            or retrieval.get("canonical_gate") is not True
            or retrieval.get("governed_ingest") is not True
            or retrieval.get("full_session_corpus") is not True
        ):
            raise MemoryQualityError("MiLAi record bypasses real retrieval topology")
    if len(native_hashes) != len(set(native_hashes)):
        raise MemoryQualityError("native request mapping is not one-to-one")
    if len(attempt_ids) != len(set(attempt_ids)):
        raise MemoryQualityError("Track A attempt IDs repeat")
    arm_counts = Counter(str(record["arm"]) for record in records)
    return {
        "schema": "milai.dg10.memory-quality-topology-validation.v1",
        "candidate_id": remediation.CANDIDATE,
        "case_count": len(grouped),
        "record_count": len(records),
        "arm_counts": dict(sorted(arm_counts.items())),
        "answer_calls_per_arm_case": 1,
        "hidden_or_extra_model_calls": 0,
        "native_request_mapping_unique": True,
        "status": "PASS",
    }


def _canonical_record_value(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def validate_frozen_topology_contract(path: Path = TOPOLOGY_CONTRACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema") != "milai.dg10.memory-quality-topology.v1"
        or value.get("candidate_id") != remediation.CANDIDATE
        or value.get("arms") != list(ARMS)
        or set(value.get("answer_model_calls_per_case", {}).values()) != {1}
        or value.get("memory_target_tokenizer_tokens_max") != MAX_MEMORY_TOKENS
        or value.get("milai_retrieval", {}).get("artificial_marker_allowed") is not False
        or value.get("milai_retrieval", {}).get("shared_naive_ranking_allowed") is not False
        or value.get("test_access_authorized") is not False
    ):
        raise MemoryQualityError("frozen Track A topology contract drifted")
    return {
        "path": path.relative_to(remediation.ROOT).as_posix(),
        "sha256": remediation.sha256_file(path),
        "status": "PASS",
    }
