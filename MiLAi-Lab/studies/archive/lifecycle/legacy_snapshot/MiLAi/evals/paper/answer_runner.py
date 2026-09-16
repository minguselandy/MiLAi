"""Common answer runner; memory methods cannot alter this call path."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from evals.paper.archive import ArchiveError, scan_archive
from evals.paper.parallelism import ANSWER_PROVIDER_LANE
from evals.paper.usage_ledger import UsageLedger


class AnswerRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedAnswer:
    ordinal: int
    logical_request_id: str
    case_id: str
    method_id: str
    prompt: str
    prompt_tokens: int
    memory_tokens: int


@dataclass(frozen=True)
class AnswerCompletion:
    answer: str
    native_request_id: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str


AnswerCall = Callable[[PreparedAnswer], AnswerCompletion]


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


class PaperAnswerRunner:
    def __init__(
        self,
        ledger: UsageLedger,
        *,
        max_workers: int = ANSWER_PROVIDER_LANE.default_workers,
        max_memory_tokens: int,
    ) -> None:
        ANSWER_PROVIDER_LANE.validate(max_workers)
        if max_memory_tokens <= 0:
            raise ValueError("memory token ceiling must be positive")
        self._ledger = ledger
        self._max_workers = max_workers
        self._max_memory_tokens = max_memory_tokens

    def execute(
        self,
        prepared: Sequence[PreparedAnswer],
        answer_call: AnswerCall,
    ) -> tuple[Mapping[str, Any], ...]:
        request_ids = tuple(item.logical_request_id for item in prepared)
        if len(set(request_ids)) != len(request_ids):
            raise AnswerRunnerError("logical request IDs are not unique")
        if any(item.memory_tokens > self._max_memory_tokens for item in prepared):
            raise AnswerRunnerError("prepared answer exceeds the frozen memory ceiling")
        summary = scan_archive(self._ledger.path, request_ids)
        if summary.failed or summary.manual_reconciliation:
            raise ArchiveError(
                "archive contains terminal failures or an ambiguous provider start"
            )
        prior_terminals = _successful_terminals(self._ledger)
        initially_missing = set(summary.missing)
        runnable = [
            item
            for item in prepared
            if item.logical_request_id in set(summary.safe_to_resume + summary.missing)
        ]
        results: dict[str, Mapping[str, Any]] = dict(prior_terminals)

        def run_one(item: PreparedAnswer) -> Mapping[str, Any]:
            if item.logical_request_id in initially_missing:
                self._ledger.append(
                    {
                        "case_id": item.case_id,
                        "logical_request_id": item.logical_request_id,
                        "method_id": item.method_id,
                        "prompt_sha256": prompt_sha256(item.prompt),
                        "type": "RESERVED",
                    }
                )
            self._ledger.append(
                {
                    "logical_request_id": item.logical_request_id,
                    "type": "PROVIDER_STARTED",
                }
            )
            try:
                completion = answer_call(item)
            except Exception as exc:
                self._ledger.append(
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                        "logical_request_id": item.logical_request_id,
                        "status": "FAILED",
                        "type": "TERMINAL",
                    }
                )
                raise
            if completion.prompt_tokens != item.prompt_tokens:
                raise AnswerRunnerError(
                    "native prompt usage differs from tokenizer preflight"
                )
            record = {
                "answer": completion.answer,
                "case_id": item.case_id,
                "completion_tokens": completion.completion_tokens,
                "finish_reason": completion.finish_reason,
                "logical_request_id": item.logical_request_id,
                "memory_tokens": item.memory_tokens,
                "method_id": item.method_id,
                "native_request_id": completion.native_request_id,
                "ordinal": item.ordinal,
                "prompt_sha256": prompt_sha256(item.prompt),
                "prompt_tokens": completion.prompt_tokens,
            }
            self._ledger.append(
                {
                    **record,
                    "status": "SUCCEEDED",
                    "type": "TERMINAL",
                }
            )
            return record

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(run_one, item): item.logical_request_id
                for item in runnable
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        if set(results) != set(request_ids):
            raise AnswerRunnerError("answer denominator is incomplete")
        return tuple(sorted(results.values(), key=lambda item: int(item["ordinal"])))


def _successful_terminals(ledger: UsageLedger) -> dict[str, Mapping[str, Any]]:
    terminals: dict[str, Mapping[str, Any]] = {}
    for envelope in ledger.verify().events:
        event = envelope["event"]
        if not isinstance(event, dict) or event.get("type") != "TERMINAL":
            continue
        if event.get("status") != "SUCCEEDED":
            continue
        request_id = str(event["logical_request_id"])
        terminals[request_id] = {
            key: value for key, value in event.items() if key not in {"status", "type"}
        }
    return terminals
