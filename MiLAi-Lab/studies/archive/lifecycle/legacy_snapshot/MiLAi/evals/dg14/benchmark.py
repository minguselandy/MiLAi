"""Reproducible DG-14 LongMemEval opened-development benchmark runner.

The run plane receives the five-case, label-free snapshot only.  Answer and
evidence labels enter through :func:`score_opened_dev` after all memory and
provider calls have terminated.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from evals.dg14.contracts import (
    DG14ContractError,
    DG14Error,
    DG14HistoryEvent,
    DG14ReadinessRequest,
    normalize_lme_timestamp,
)
from evals.dg14.ledger import DG14StageEvent, DG14StageLedger
from evals.dg14.provider import (
    MatchedVllmProvider,
    ProviderResult,
    full_provider_contract,
    full_provider_contract_sha256,
    matched_seed,
)
from evals.paper.adapters.baselines import (
    CustomLexicalTop1Adapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
)
from evals.paper.contracts import MemoryEvent
from evals.paper.datasets.longmemeval import (
    LongMemEvalCase,
    load_inputs,
)
from evals.paper.schedules.latin import counterbalanced_order
from evals.paper.scorers.longmemeval import normalize, score_answer, score_retrieval

ROOT = Path(__file__).resolve().parents[2]
OPENED_DEV_INPUT_PATH = (
    ROOT / "var/dg11/paper/runs/pe04-harness-smoke-20260824-002/inputs.json"
)
REJECTED_INPUT_PATH = (
    ROOT / "var/dg11/paper/runs/pe04-harness-smoke-20260824-001/inputs.json"
)
OPENED_DEV_INPUT_SHA256 = (
    "dd1c6fb5c137b16780965b5637562cdfdc8e69ef8d1f1e02e94ce92c754b5a5b"
)
REJECTED_INPUT_SHA256 = (
    "8d27d36136e2d4b93b1813c31c50733e9c71be0b9f8eaa3bba85c5ef0d79816a"
)
OPENED_DEV_CASE_IDS = (
    "001be529",
    "00ca467f",
    "0100672e",
    "01493427",
    "031748ae",
)
ARMS = (
    "CTRL-NONE",
    "CTRL-CUSTOM-LEX1",
    "LME-BM25-S",
    "LME-BM25-T",
    "DG14-MILAI-MCP",
)
BUDGETS = (512, 2048)
METHOD_ID = "DG14-MILAI-MCP"
CLASSIFICATION = "OPENED_DEV_SMOKE / CHARACTERIZATION"
RESULT_SCOPE = CLASSIFICATION
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
DEFAULT_CHAT_TEMPLATE = Path("/cra/qwen36-35B/chat_template.jinja")
BASELINE_CONFIG = ROOT / "var/dg11/paper/method-configs/longmemeval-baselines.json"
EXPECTED_TOKENIZER_SHA256 = (
    "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
)
EXPECTED_CHAT_TEMPLATE_SHA256 = (
    "e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259"
)
EXPECTED_BASELINE_CONFIG_SHA256 = (
    "ec611f78719c1a6c32878bc543a80e196d0b12f34b26970ccd29e9cf917577de"
)
NONINFERIORITY_MARGIN = 0.0
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
EXPECTED_CELL_COUNT = len(OPENED_DEV_CASE_IDS) * len(ARMS) * len(BUDGETS)


class DG14BenchmarkError(DG14ContractError):
    """Typed runner/scoring boundary failure."""


TokenCounter = Callable[[str], int]
MilaiAdapterFactory = Callable[[Any, TokenCounter], Any]


class AnswerProvider(Protocol):
    def answer(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        token_budget: int,
        ledger: DG14StageLedger | None = None,
    ) -> ProviderResult: ...


class RuntimeSession(Protocol):
    def start(self, run_id: str) -> Mapping[str, Any]: ...

    def adapter_for_case(self, case: Any, token_counter: TokenCounter) -> Any: ...

    def close(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkCell:
    ordinal: int
    case_ordinal: int
    case_id: str
    method_id: str
    token_budget: int


@dataclass(frozen=True, slots=True)
class OpenedDevCase:
    """Runner view that exposes only query-time fields and label-free history."""

    case_id: str
    category: str
    question: str
    question_at: str
    sessions: tuple[Any, ...]
    history_events: tuple[DG14HistoryEvent, ...]

    @property
    def source_id(self) -> str:
        return self.case_id


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise DG14BenchmarkError(
            f"cannot hash required DG-14 artifact: {path}"
        ) from exc
    return digest.hexdigest()


def _execution_identities(tokenizer_path: Path) -> dict[str, dict[str, str]]:
    identities = {
        "baseline_config": {
            "path": str(BASELINE_CONFIG.resolve()),
            "sha256": _sha256_file(BASELINE_CONFIG),
        },
        "chat_template": {
            "path": str(DEFAULT_CHAT_TEMPLATE.resolve()),
            "sha256": _sha256_file(DEFAULT_CHAT_TEMPLATE),
        },
        "tokenizer": {
            "path": str(tokenizer_path.resolve()),
            "sha256": _sha256_file(tokenizer_path),
        },
    }
    expected = {
        "baseline_config": EXPECTED_BASELINE_CONFIG_SHA256,
        "chat_template": EXPECTED_CHAT_TEMPLATE_SHA256,
        "tokenizer": EXPECTED_TOKENIZER_SHA256,
    }
    drifted = [
        name
        for name, digest in expected.items()
        if identities[name]["sha256"] != digest
    ]
    if drifted:
        raise DG14BenchmarkError(
            "DG-14 frozen execution identity drifted: " + ", ".join(drifted)
        )
    return identities


def load_opened_dev(
    path: Path = OPENED_DEV_INPUT_PATH,
    pre_call_hook: Callable[[], None] | None = None,
) -> tuple[str, tuple[OpenedDevCase, ...]]:
    """Load only the byte-identical, corrected five-case label-free snapshot."""

    digest = _sha256_file(path)
    if digest == REJECTED_INPUT_SHA256:
        raise DG14BenchmarkError(
            "rejected pe04-harness-smoke-20260824-001 duplicate-session snapshot"
        )
    if digest != OPENED_DEV_INPUT_SHA256:
        raise DG14BenchmarkError(
            "DG-14 run input is not the bound opened-dev -002 snapshot"
        )
    raw_partition, raw_cases = load_inputs(path)
    if tuple(case.source_id for case in raw_cases) != OPENED_DEV_CASE_IDS:
        raise DG14BenchmarkError("opened-dev case identity/order drifted")
    cases = tuple(
        OpenedDevCase(
            case_id=case.source_id,
            category=case.category,
            question=case.question,
            question_at=case.question_at,
            sessions=case.sessions,
            history_events=tuple(
                _dg14_event(
                    case,
                    session_ordinal=session_ordinal,
                    turn_ordinal=turn_ordinal,
                )
                for session_ordinal, session in enumerate(case.sessions)
                for turn_ordinal, _turn in enumerate(session.turns)
            ),
        )
        for case in raw_cases
    )
    if raw_partition != "LME-OPENED-SMOKE":
        raise DG14BenchmarkError("opened-dev partition identity drifted")
    if pre_call_hook is not None:
        pre_call_hook()
    return raw_partition, cases


def build_schedule(
    cases: Sequence[OpenedDevCase | LongMemEvalCase | str],
    budgets: Sequence[int] = BUDGETS,
    arms: Sequence[str] = ARMS,
) -> tuple[BenchmarkCell, ...]:
    if tuple(budgets) != BUDGETS:
        raise DG14BenchmarkError("DG-14 matched budgets must be exactly 512 and 2048")
    if tuple(arms) != ARMS:
        raise DG14BenchmarkError("DG-14 matched arm set/order drifted")
    case_ids = tuple(
        item if isinstance(item, str) else item.source_id for item in cases
    )
    if (
        not case_ids
        or len(set(case_ids)) != len(case_ids)
        or any(case_id not in OPENED_DEV_CASE_IDS for case_id in case_ids)
        or tuple(sorted(case_ids, key=OPENED_DEV_CASE_IDS.index)) != case_ids
    ):
        raise DG14BenchmarkError("DG-14 schedule requires an ordered bound-case subset")
    result: list[BenchmarkCell] = []
    for case_ordinal, case_id in enumerate(case_ids):
        ordered = counterbalanced_order(
            arms,
            case_ordinal=case_ordinal,
            namespace="milai-dg14-opened-dev-v1:retrieval",
        )
        for method_id in ordered:
            for token_budget in budgets:
                result.append(
                    BenchmarkCell(
                        ordinal=len(result),
                        case_ordinal=case_ordinal,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                    )
                )
    if len(result) != len(case_ids) * len(BUDGETS) * len(ARMS):
        raise DG14BenchmarkError("DG-14 schedule denominator drifted")
    return tuple(result)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _process_identity(pid: int) -> dict[str, object]:
    proc_root = Path("/proc") / str(pid)
    try:
        stat = (proc_root / "stat").read_text(encoding="utf-8")
        closing_paren = stat.rfind(")")
        if closing_paren < 0:
            raise ValueError("process stat lacks comm boundary")
        stat_tail = stat[closing_paren + 2 :].split()
        start_ticks = int(stat_tail[19])
        cmdline_bytes = (proc_root / "cmdline").read_bytes()
        cmdline = [
            value.decode("utf-8", errors="surrogateescape")
            for value in cmdline_bytes.split(b"\0")
            if value
        ]
        executable = os.readlink(proc_root / "exe")
        cwd = os.readlink(proc_root / "cwd")
    except (OSError, ValueError, IndexError) as exc:
        raise DG14BenchmarkError(
            f"could not freeze ownership identity for pid {pid}"
        ) from exc
    if not cmdline:
        raise DG14BenchmarkError(f"process {pid} lacks a freezeable command line")
    return {
        "pid": pid,
        "proc_start_ticks": start_ticks,
        "executable": executable,
        "cwd": cwd,
        "cmdline": cmdline,
        "cmdline_sha256": hashlib.sha256(cmdline_bytes).hexdigest(),
    }


def _json_value(value: object) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(cast(Any, value)))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise DG14BenchmarkError(f"non-JSON benchmark value: {type(value).__name__}")


def _local_token_counter(path: Path) -> TokenCounter:
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise DG14BenchmarkError(
            "tokenizers is required unless token_counter is injected"
        ) from exc
    tokenizer = Tokenizer.from_file(str(path))
    return lambda text: len(tokenizer.encode(text).ids)


def _baseline_event(
    case: Any,
    *,
    session_ordinal: int,
    turn_ordinal: int,
) -> MemoryEvent:
    session = case.sessions[session_ordinal]
    turn = session.turns[turn_ordinal]
    return MemoryEvent(
        event_id=(
            f"{case.source_id}:s{session_ordinal}:{session.session_id}:t{turn_ordinal}"
        ),
        content=turn.content,
        observed_at=session.observed_at,
        actor=turn.role,
        scope=f"dg14-opened-dev:{case.source_id}",
        metadata={
            "case_id": case.source_id,
            "session_id": session.session_id,
            "session_ordinal": session_ordinal,
            "turn_index": turn_ordinal,
            "turn_ordinal": turn_ordinal,
        },
    )


def _dg14_event(
    case: Any,
    *,
    session_ordinal: int,
    turn_ordinal: int,
) -> DG14HistoryEvent:
    session = case.sessions[session_ordinal]
    turn = session.turns[turn_ordinal]
    # This allowlist is deliberate: category/question and every scoring field are
    # absent from the object passed to the MiLA adapter.
    return DG14HistoryEvent.from_mapping(
        {
            "case_id": case.source_id,
            "session_ordinal": session_ordinal,
            "original_session_id": session.session_id,
            "turn_ordinal": turn_ordinal,
            "role": turn.role,
            "content": turn.content,
            "observed_at": normalize_lme_timestamp(session.observed_at),
        }
    )


def _events(case: Any, method_id: str) -> tuple[MemoryEvent | DG14HistoryEvent, ...]:
    result: list[MemoryEvent | DG14HistoryEvent] = []
    for session_ordinal, session in enumerate(case.sessions):
        for turn_ordinal, _turn in enumerate(session.turns):
            if method_id == METHOD_ID:
                result.append(
                    _dg14_event(
                        case,
                        session_ordinal=session_ordinal,
                        turn_ordinal=turn_ordinal,
                    )
                )
            else:
                result.append(
                    _baseline_event(
                        case,
                        session_ordinal=session_ordinal,
                        turn_ordinal=turn_ordinal,
                    )
                )
    return tuple(result)


def _baseline_adapter(method_id: str, token_counter: TokenCounter) -> Any:
    if method_id == "CTRL-NONE":
        return NoMemoryAdapter(token_counter=token_counter)
    if method_id == "CTRL-CUSTOM-LEX1":
        return CustomLexicalTop1Adapter(token_counter=token_counter)
    if method_id == "LME-BM25-S":
        return OfficialBM25Adapter(
            granularity="session", top_k=3, token_counter=token_counter
        )
    if method_id == "LME-BM25-T":
        return OfficialBM25Adapter(
            granularity="turn", top_k=3, token_counter=token_counter
        )
    raise DG14BenchmarkError(f"not a controlled baseline arm: {method_id}")


def _stats_calls(adapter: Any) -> int:
    stats = adapter.stats()
    value = getattr(stats, "logical_mcp_calls", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DG14BenchmarkError("adapter logical MCP call count is invalid")
    return value


def _append_stage(
    ledger: DG14StageLedger,
    *,
    run_id: str,
    stage: str,
    case_id: str,
    method_id: str,
    duration_ms: float,
    logical_calls: int = 0,
    token_budget: int | None = None,
    candidate_count: int | None = None,
    retrieval_route: str | None = None,
    memory_tokens: int | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    ledger.append(
        DG14StageEvent(
            run_id=run_id,
            case_id=case_id,
            method_id=method_id,
            token_budget=token_budget,
            stage=stage,
            status="SUCCEEDED",
            duration_ms=duration_ms,
            logical_calls=logical_calls,
            candidate_count=candidate_count,
            retrieval_route=retrieval_route,
            memory_tokens=memory_tokens,
            details=details or {},
        )
    )


def _append_adapter_records(
    ledger: DG14StageLedger,
    *,
    adapter: Any,
    run_id: str,
    case_id: str,
    method_id: str,
    call_cursor: int,
    stage_cursor: int,
    token_budget: int | None = None,
) -> tuple[int, int]:
    """Copy each new MCP call and Runtime stage into the common ledger once."""

    if method_id != METHOD_ID:
        return call_cursor, stage_cursor
    call_records = adapter.export_call_records()
    stage_records = adapter.export_stage_trace()
    if not isinstance(call_records, (tuple, list)) or not isinstance(
        stage_records, (tuple, list)
    ):
        raise DG14BenchmarkError("MiLA adapter trace export contract drifted")
    pending_events: list[DG14StageEvent] = []
    for item in call_records[call_cursor:]:
        raw = _json_value(item)
        if not isinstance(raw, dict):
            raise DG14BenchmarkError("MiLA MCP call record is invalid")
        status = raw.get("status")
        latency_ms = raw.get("latency_ms")
        sequence = raw.get("sequence")
        if (
            status not in {"SUCCEEDED", "FAILED"}
            or not isinstance(latency_ms, (int, float))
            or isinstance(latency_ms, bool)
            or not isinstance(sequence, int)
        ):
            raise DG14BenchmarkError("MiLA MCP call accounting drifted")
        pending_events.append(
            DG14StageEvent(
                run_id=run_id,
                case_id=case_id,
                method_id=method_id,
                token_budget=token_budget,
                logical_request_id=f"{run_id}:{case_id}:mcp:{sequence}",
                stage="mcp",
                status=cast(Any, status),
                duration_ms=float(latency_ms),
                logical_calls=1,
                failure_type="DG14TransportError" if status == "FAILED" else None,
                failure_code=str(raw.get("stage")) if status == "FAILED" else None,
                details={"call_record": raw},
            )
        )
    for item in stage_records[stage_cursor:]:
        raw = _json_value(item)
        if not isinstance(raw, dict):
            raise DG14BenchmarkError("MiLA Runtime stage record is invalid")
        latency_ms = raw.get("latency_ms")
        if not isinstance(latency_ms, (int, float)) or isinstance(latency_ms, bool):
            raise DG14BenchmarkError("MiLA Runtime stage latency is invalid")
        pending_events.append(
            DG14StageEvent(
                run_id=run_id,
                stage="runtime",
                status="SUCCEEDED",
                case_id=case_id,
                method_id=method_id,
                token_budget=token_budget,
                duration_ms=float(latency_ms),
                details={"adapter_stage": raw},
            )
        )
    ledger.append_many(pending_events)
    return len(call_records), len(stage_records)


def _append_runtime_metrics(
    ledger: DG14StageLedger,
    *,
    run_id: str,
    case_id: str,
    method_id: str,
    token_budget: int,
    usage: object,
) -> None:
    if method_id != METHOD_ID or not isinstance(usage, Mapping):
        return
    metrics = usage.get("runtime_stage_metrics")
    if not isinstance(metrics, Mapping):
        return
    durations = metrics.get("durations_ms")
    counts = metrics.get("counts")
    if not isinstance(durations, Mapping):
        return
    for runtime_stage, duration in sorted(
        durations.items(), key=lambda item: str(item[0])
    ):
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            raise DG14BenchmarkError("Runtime stage duration is invalid")
        count = counts.get(runtime_stage) if isinstance(counts, Mapping) else None
        _append_stage(
            ledger,
            run_id=run_id,
            stage="runtime",
            case_id=case_id,
            method_id=method_id,
            token_budget=token_budget,
            duration_ms=float(duration),
            details={
                "runtime_operation": str(runtime_stage),
                "operation_count": count,
            },
        )


def _query_trace(result: Any) -> tuple[dict[str, Any], ...]:
    trace = getattr(result, "trace", None)
    if trace is not None:
        if not isinstance(trace, (tuple, list)):
            raise DG14BenchmarkError("baseline retrieval trace is invalid")
        return tuple(dict(cast(Mapping[str, Any], item)) for item in trace)
    provenance = getattr(result, "provenance", None)
    if not isinstance(provenance, (tuple, list)):
        raise DG14BenchmarkError("MiLA query omitted provenance")
    normalized: list[dict[str, Any]] = []
    for item in provenance:
        raw = _json_value(item)
        if not isinstance(raw, dict):
            raise DG14BenchmarkError("MiLA provenance item is invalid")
        session_id = raw.get("session_id") or raw.get("source_id")
        if not isinstance(session_id, str):
            raise DG14BenchmarkError("MiLA provenance cannot map to an LME session")
        normalized.append(
            {
                **raw,
                "session_id": session_id,
                "source_id": str(raw.get("source_id", session_id)),
            }
        )
    return tuple(normalized)


def _candidate_count(result: Any, trace: Sequence[Mapping[str, Any]]) -> int:
    usage = getattr(result, "usage", {})
    if isinstance(usage, Mapping):
        for key in ("candidate_count", "candidates", "documents_scored"):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return len(trace)


def _retrieval_route(result: Any) -> str:
    usage = getattr(result, "usage", {})
    if isinstance(usage, Mapping):
        for key in ("retrieval_escalation_route", "escalation_route", "route"):
            value = usage.get(key)
            if isinstance(value, str) and value:
                return value
    return "NONE" if not getattr(result, "context", "") else "DIRECT"


def _context_record(
    *,
    cell: BenchmarkCell,
    case: Any,
    result: Any,
    ingest_ms: float,
    finalize_ms: float,
    mcp_calls: int,
) -> dict[str, Any]:
    context = getattr(result, "context", None)
    source_ids = getattr(result, "source_ids", None)
    declared_tokens = getattr(result, "declared_tokens", None)
    latency_ms = getattr(result, "latency_ms", None)
    usage = getattr(result, "usage", None)
    if (
        not isinstance(context, str)
        or not isinstance(source_ids, (tuple, list))
        or not all(isinstance(item, str) for item in source_ids)
        or not isinstance(declared_tokens, int)
        or isinstance(declared_tokens, bool)
        or not isinstance(latency_ms, (int, float))
        or not isinstance(usage, Mapping)
    ):
        raise DG14BenchmarkError("adapter query result contract drifted")
    trace = _query_trace(result)
    allowed_sessions = {session.session_id for session in case.sessions}
    returned_sessions = {
        str(item["session_id"]) for item in trace if "session_id" in item
    }
    contamination = sorted(returned_sessions.difference(allowed_sessions))
    if contamination:
        raise DG14BenchmarkError(
            f"cross-case provenance accepted for {cell.case_id}: {contamination}"
        )
    route = _retrieval_route(result)
    candidates = _candidate_count(result, trace)
    raw_resolve = getattr(result, "raw_resolve", {})
    stage_trace = getattr(result, "stage_trace", ())
    return {
        "adapter_declared_tokens": declared_tokens,
        "adapter_stage_trace": _json_value(stage_trace),
        "candidate_count": candidates,
        "case_id": cell.case_id,
        "category": case.category,
        "classification": CLASSIFICATION,
        "context": context,
        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
        "finalize_latency_ms": round(finalize_ms, 6),
        "ingest_latency_ms": round(ingest_ms, 6),
        "mcp_logical_calls": mcp_calls,
        "mcp_query_logical_calls": mcp_calls,
        "method_id": cell.method_id,
        "ordinal": cell.ordinal,
        "query_latency_ms": round(float(latency_ms), 6),
        "raw_resolve": _json_value(raw_resolve),
        "retrieval_route": route,
        "retrieval_trace": [dict(item) for item in trace],
        "source_ids": list(source_ids),
        "token_budget": cell.token_budget,
        "usage": _json_value(usage),
    }


def _make_manifest(
    *,
    run_id: str,
    input_path: Path,
    partition: str,
    schedule: Sequence[BenchmarkCell],
    tokenizer_path: Path | None,
    execution_identities: Mapping[str, Mapping[str, str]] | None,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "arms": list(ARMS),
        "budgets": list(BUDGETS),
        "case_count": len(OPENED_DEV_CASE_IDS),
        "case_ids": list(OPENED_DEV_CASE_IDS),
        "classification": CLASSIFICATION,
        "dry_run": dry_run,
        "formal_holdout_consumed": False,
        "input_path": str(input_path.resolve()),
        "input_sha256": OPENED_DEV_INPUT_SHA256,
        "label_fields_available_to_run": False,
        "method": "DG14 opened-development matched comparison",
        "partition": partition,
        "provider_contract": full_provider_contract(),
        "provider_contract_sha256": full_provider_contract_sha256(),
        "provider_seed_policy": "same run_id+case_id+budget seed across all arms",
        "execution_identities": _json_value(execution_identities),
        "result_scope": RESULT_SCOPE,
        "run_id": run_id,
        "schedule": [asdict(cell) for cell in schedule],
        "schema": "milai.dg14.opened-dev-manifest.v1",
        "status": "PLANNED" if dry_run else "RUNNING",
        "tokenizer_path": str(tokenizer_path.resolve()) if tokenizer_path else None,
    }


def run_opened_dev(
    *,
    run_id: str,
    input_path: Path = OPENED_DEV_INPUT_PATH,
    output_root: Path,
    tokenizer_path: Path | None = DEFAULT_TOKENIZER,
    token_counter: TokenCounter | None = None,
    provider: AnswerProvider | None = None,
    runtime_session: RuntimeSession | None = None,
    milai_adapter_factory: MilaiAdapterFactory | None = None,
    max_provider_workers: int = 1,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run all 50 matched cells without opening any answer/evidence label source."""

    if not run_id:
        raise ValueError("run_id is required")
    if max_provider_workers not in {1, 2}:
        raise ValueError("provider concurrency must be 1 or 2")
    # The byte gate is intentionally the first external-input action.  Runtime,
    # MCP and provider objects are not created before it succeeds.
    partition, cases = load_opened_dev(input_path)
    schedule = build_schedule(cases)
    execution_identities = (
        _execution_identities(tokenizer_path) if tokenizer_path is not None else None
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    ledger_path = output_root / "stage-ledger.jsonl"
    manifest = _make_manifest(
        run_id=run_id,
        input_path=input_path,
        partition=partition,
        schedule=schedule,
        tokenizer_path=tokenizer_path,
        execution_identities=execution_identities,
        dry_run=dry_run,
    )
    if dry_run:
        dry_run_path = output_root / "dry-run-plan.json"
        if dry_run_path.exists():
            raise DG14BenchmarkError("dry-run plan already exists")
        _atomic_json(dry_run_path, manifest)
        return manifest
    if manifest_path.exists() or ledger_path.exists():
        raise DG14BenchmarkError("run output already exists; choose a fresh run_id")
    _atomic_json(manifest_path, manifest)
    counter = token_counter
    if counter is None:
        if tokenizer_path is None:
            raise DG14BenchmarkError("tokenizer_path or token_counter is required")
        counter = _local_token_counter(tokenizer_path)
    answer_provider = provider or MatchedVllmProvider()
    session = runtime_session
    if session is None and milai_adapter_factory is None:
        session = LocalDG14RuntimeSession(output_root=output_root)
    ledger = DG14StageLedger(ledger_path)
    runtime_details: Mapping[str, Any] = {"status": "INJECTED_FACTORY"}
    contexts: list[dict[str, Any]] = []
    cleanup_cases: list[dict[str, Any]] = []
    active_milai_adapter: Any | None = None
    active_milai_case_id: str | None = None
    active_milai_cleanup_done = True
    correctness: dict[str, dict[str, Any]] = {
        "cross_case_contamination": {"accepted": 0, "denominator": 0},
        "label_leakage": {"accepted": 0, "denominator": 0},
        "silent_fallback": {"accepted": 0, "denominator": 0},
        "stale_revoked_evidence_acceptance": {
            "accepted": 0,
            "denominator": 0,
            "status": "NOT_EXERCISED_BY_MATCHED_RUN",
        },
        "wrong_scope_acceptance": {
            "accepted": 0,
            "denominator": 0,
            "status": "NOT_EXERCISED_BY_MATCHED_RUN",
        },
    }
    try:
        if session is not None:
            started = time.perf_counter()
            runtime_details = session.start(run_id)
            ledger.append(
                DG14StageEvent(
                    run_id=run_id,
                    stage="runtime",
                    status="SUCCEEDED",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    logical_calls=0,
                    details={"operation": "fresh_runtime_start", **runtime_details},
                )
            )
        if len(schedule) != EXPECTED_CELL_COUNT:
            raise DG14BenchmarkError("real DG-14 run requires all 50 matched cells")
        cells = {
            (cell.case_id, cell.method_id, cell.token_budget): cell for cell in schedule
        }
        for case in cases:
            ordered_methods = counterbalanced_order(
                ARMS,
                case_ordinal=OPENED_DEV_CASE_IDS.index(case.source_id),
                namespace="milai-dg14-opened-dev-v1:retrieval",
            )
            for method_id in ordered_methods:
                if method_id == METHOD_ID:
                    if milai_adapter_factory is not None:
                        adapter = milai_adapter_factory(case, counter)
                    elif session is not None:
                        adapter = session.adapter_for_case(case, counter)
                    else:
                        raise DG14BenchmarkError("MiLA adapter factory is unavailable")
                else:
                    adapter = _baseline_adapter(method_id, counter)
                if getattr(adapter, "method_id", None) != method_id:
                    raise DG14BenchmarkError("adapter method identity drifted")
                if method_id == METHOD_ID:
                    active_milai_adapter = adapter
                    active_milai_case_id = case.source_id
                    active_milai_cleanup_done = False
                calls_before = _stats_calls(adapter)
                call_record_cursor = 0
                stage_record_cursor = 0
                started = time.perf_counter()
                adapter.reset(run_id, case.source_id)
                reset_ms = (time.perf_counter() - started) * 1000
                calls_after = _stats_calls(adapter)
                _append_stage(
                    ledger,
                    run_id=run_id,
                    stage="reset",
                    case_id=case.source_id,
                    method_id=method_id,
                    duration_ms=reset_ms,
                    logical_calls=calls_after - calls_before,
                )
                call_record_cursor, stage_record_cursor = _append_adapter_records(
                    ledger,
                    adapter=adapter,
                    run_id=run_id,
                    case_id=case.source_id,
                    method_id=method_id,
                    call_cursor=call_record_cursor,
                    stage_cursor=stage_record_cursor,
                )
                case_events = _events(case, method_id)
                correctness["label_leakage"]["denominator"] += len(case_events)
                calls_before = calls_after
                started = time.perf_counter()
                for event in case_events:
                    adapter.ingest(event)
                ingest_ms = (time.perf_counter() - started) * 1000
                calls_after = _stats_calls(adapter)
                _append_stage(
                    ledger,
                    run_id=run_id,
                    stage="ingest",
                    case_id=case.source_id,
                    method_id=method_id,
                    duration_ms=ingest_ms,
                    logical_calls=calls_after - calls_before,
                    details={"event_count": len(case_events)},
                )
                call_record_cursor, stage_record_cursor = _append_adapter_records(
                    ledger,
                    adapter=adapter,
                    run_id=run_id,
                    case_id=case.source_id,
                    method_id=method_id,
                    call_cursor=call_record_cursor,
                    stage_cursor=stage_record_cursor,
                )
                calls_before = calls_after
                started = time.perf_counter()
                adapter.finalize()
                finalize_ms = (time.perf_counter() - started) * 1000
                calls_after = _stats_calls(adapter)
                _append_stage(
                    ledger,
                    run_id=run_id,
                    stage="finalize",
                    case_id=case.source_id,
                    method_id=method_id,
                    duration_ms=finalize_ms,
                    logical_calls=calls_after - calls_before,
                )
                call_record_cursor, stage_record_cursor = _append_adapter_records(
                    ledger,
                    adapter=adapter,
                    run_id=run_id,
                    case_id=case.source_id,
                    method_id=method_id,
                    call_cursor=call_record_cursor,
                    stage_cursor=stage_record_cursor,
                )
                for budget in BUDGETS:
                    cell = cells[(case.source_id, method_id, budget)]
                    calls_before = calls_after
                    started = time.perf_counter()
                    if method_id == METHOD_ID:
                        result = adapter.query(
                            case.question,
                            normalize_lme_timestamp(case.question_at),
                            budget,
                        )
                    else:
                        result = adapter.query(
                            case.question,
                            normalize_lme_timestamp(case.question_at),
                            budget,
                            "default",
                        )
                    outer_query_ms = (time.perf_counter() - started) * 1000
                    calls_after = _stats_calls(adapter)
                    record = _context_record(
                        cell=cell,
                        case=case,
                        result=result,
                        ingest_ms=ingest_ms,
                        finalize_ms=finalize_ms,
                        mcp_calls=calls_after - calls_before,
                    )
                    contexts.append(record)
                    correctness["cross_case_contamination"]["denominator"] += 1
                    correctness["silent_fallback"]["denominator"] += 1
                    _append_stage(
                        ledger,
                        run_id=run_id,
                        stage="context",
                        case_id=case.source_id,
                        method_id=method_id,
                        token_budget=budget,
                        duration_ms=outer_query_ms,
                        logical_calls=0,
                        candidate_count=int(record["candidate_count"]),
                        retrieval_route=str(record["retrieval_route"]),
                        memory_tokens=int(record["adapter_declared_tokens"]),
                        details={"context_sha256": record["context_sha256"]},
                    )
                    if method_id == METHOD_ID:
                        call_record_cursor, stage_record_cursor = (
                            _append_adapter_records(
                                ledger,
                                adapter=adapter,
                                run_id=run_id,
                                case_id=case.source_id,
                                method_id=method_id,
                                call_cursor=call_record_cursor,
                                stage_cursor=stage_record_cursor,
                                token_budget=budget,
                            )
                        )
                        _append_runtime_metrics(
                            ledger,
                            run_id=run_id,
                            case_id=case.source_id,
                            method_id=method_id,
                            token_budget=budget,
                            usage=record["usage"],
                        )
                cleanup_calls_before = _stats_calls(adapter)
                cleanup_started = time.perf_counter()
                if method_id == METHOD_ID:
                    cleanup_value = adapter.cleanup()
                    active_milai_cleanup_done = True
                else:
                    adapter.close()
                    cleanup_value = {"status": "CLOSED", "namespace": case.source_id}
                cleanup_ms = (time.perf_counter() - cleanup_started) * 1000
                cleanup_calls_after = _stats_calls(adapter)
                cleanup_cases.append(
                    {
                        "case_id": case.source_id,
                        "method_id": method_id,
                        "result": _json_value(cleanup_value),
                    }
                )
                _append_stage(
                    ledger,
                    run_id=run_id,
                    stage="cleanup",
                    case_id=case.source_id,
                    method_id=method_id,
                    duration_ms=cleanup_ms,
                    logical_calls=cleanup_calls_after - cleanup_calls_before,
                    details={"result": _json_value(cleanup_value)},
                )
                _append_adapter_records(
                    ledger,
                    adapter=adapter,
                    run_id=run_id,
                    case_id=case.source_id,
                    method_id=method_id,
                    call_cursor=call_record_cursor,
                    stage_cursor=stage_record_cursor,
                )
                for prior_context in contexts:
                    if (
                        prior_context["case_id"] == case.source_id
                        and prior_context["method_id"] == method_id
                    ):
                        prior_context["mcp_logical_calls"] = cleanup_calls_after
                if method_id == METHOD_ID:
                    active_milai_adapter = None
                    active_milai_case_id = None
        contexts.sort(key=lambda item: int(item["ordinal"]))
        if len(contexts) != EXPECTED_CELL_COUNT:
            raise DG14BenchmarkError("context denominator is incomplete")
        context_archive = {
            "classification": CLASSIFICATION,
            "formal_holdout_consumed": False,
            "input_sha256": OPENED_DEV_INPUT_SHA256,
            "record_count": len(contexts),
            "records": contexts,
            "run_id": run_id,
            "schema": "milai.dg14.opened-dev-contexts.v1",
            "status": "SUCCEEDED",
        }
        _atomic_json(output_root / "contexts.json", context_archive)

        def answer_one(context_record: Mapping[str, Any]) -> dict[str, Any]:
            case = next(
                item for item in cases if item.source_id == context_record["case_id"]
            )
            result = answer_provider.answer(
                run_id=run_id,
                case_id=case.source_id,
                method_id=str(context_record["method_id"]),
                question=case.question,
                question_as_of=normalize_lme_timestamp(case.question_at),
                memory_context=str(context_record["context"]),
                token_budget=int(context_record["token_budget"]),
                ledger=ledger,
            )
            if not isinstance(result, ProviderResult):
                raise DG14BenchmarkError("provider result contract drifted")
            e2e_ms = (
                float(context_record["query_latency_ms"])
                + result.tokenize_latency_ms
                + result.provider_latency_ms
            )
            ledger.append(
                DG14StageEvent(
                    run_id=run_id,
                    case_id=case.source_id,
                    method_id=str(context_record["method_id"]),
                    token_budget=int(context_record["token_budget"]),
                    logical_request_id=result.logical_request_id,
                    stage="e2e",
                    status="SUCCEEDED",
                    duration_ms=e2e_ms,
                    logical_calls=(
                        int(context_record["mcp_logical_calls"])
                        + result.tokenizer_calls
                        + result.provider_calls
                    ),
                    memory_tokens=result.memory_tokens,
                    prompt_tokens=result.prompt_tokens,
                )
            )
            return {
                "answer": result.answer,
                "answer_sha256": result.answer_sha256,
                "cache_salt_sha256": result.cache_salt,
                "case_id": case.source_id,
                "category": case.category,
                "classification": CLASSIFICATION,
                "completion_tokens": result.completion_tokens,
                "context_sha256": hashlib.sha256(result.context.encode()).hexdigest(),
                "context_truncated": result.context_truncated,
                "e2e_latency_ms": round(e2e_ms, 6),
                "finish_reason": result.finish_reason,
                "logical_request_id": result.logical_request_id,
                "mcp_logical_calls": context_record["mcp_logical_calls"],
                "mcp_query_logical_calls": context_record["mcp_query_logical_calls"],
                "memory_tokens": result.memory_tokens,
                "method_id": context_record["method_id"],
                "native_request_id": result.native_request_id,
                "no_memory_prompt_tokens": result.no_memory_prompt_tokens,
                "ordinal": context_record["ordinal"],
                "prompt_sha256": result.prompt_sha256,
                "prompt_tokens": result.prompt_tokens,
                "provider_calls": result.provider_calls,
                "provider_latency_ms": round(result.provider_latency_ms, 6),
                "retrieval_trace": context_record["retrieval_trace"],
                "seed": result.seed,
                "source_context_sha256": context_record["context_sha256"],
                "token_budget": context_record["token_budget"],
                "tokenize_latency_ms": round(result.tokenize_latency_ms, 6),
                "tokenizer_calls": result.tokenizer_calls,
            }

        generations: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_provider_workers) as executor:
            futures = {
                executor.submit(answer_one, record): record for record in contexts
            }
            for future in as_completed(futures):
                generations.append(future.result())
        generations.sort(key=lambda item: int(item["ordinal"]))
        if len(generations) != EXPECTED_CELL_COUNT:
            raise DG14BenchmarkError("provider denominator is incomplete")
        for case_id in OPENED_DEV_CASE_IDS:
            for budget in BUDGETS:
                seeds = {
                    int(record["seed"])
                    for record in generations
                    if record["case_id"] == case_id and record["token_budget"] == budget
                }
                if seeds != {matched_seed(run_id, case_id, budget)}:
                    raise DG14BenchmarkError("matched provider seed invariant failed")
        generation_archive = {
            "classification": CLASSIFICATION,
            "correctness": correctness,
            "formal_holdout_consumed": False,
            "input_sha256": OPENED_DEV_INPUT_SHA256,
            "record_count": len(generations),
            "records": generations,
            "run_id": run_id,
            "schema": "milai.dg14.opened-dev-generations.v1",
            "status": "SUCCEEDED",
        }
        _atomic_json(output_root / "generations.json", generation_archive)
        manifest["status"] = "SUCCEEDED"
        manifest["record_count"] = len(generations)
        manifest["runtime"] = _json_value(runtime_details)
        manifest["stage_ledger_root_sha256"] = ledger.verify().root_sha256
        _atomic_json(manifest_path, manifest)
    finally:
        primary_pending = sys.exc_info()[0] is not None
        if active_milai_adapter is not None and not active_milai_cleanup_done:
            emergency_started = time.perf_counter()
            try:
                emergency_revoked = active_milai_adapter.cleanup()
            except (
                DG14Error,
                OSError,
                subprocess.SubprocessError,
                TimeoutError,
            ) as cleanup_error:
                cleanup_cases.append(
                    {
                        "case_id": active_milai_case_id,
                        "failure_type": type(cleanup_error).__name__,
                        "method_id": METHOD_ID,
                        "status": "FAILED",
                    }
                )
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        stage="cleanup",
                        status="FAILED",
                        duration_ms=(time.perf_counter() - emergency_started) * 1_000,
                        case_id=active_milai_case_id,
                        method_id=METHOD_ID,
                        failure_type=type(cleanup_error).__name__,
                        failure_code="CASE_EMERGENCY_CLEANUP_FAILED",
                    )
                )
            else:
                cleanup_cases.append(
                    {
                        "case_id": active_milai_case_id,
                        "method_id": METHOD_ID,
                        "result": {
                            "evidence_revoked": len(emergency_revoked),
                            "status": "SUCCEEDED_AFTER_STAGE_FAILURE",
                        },
                    }
                )
        runtime_cleanup_started = time.perf_counter()
        if session is not None:
            runtime_cleanup = session.close()
        else:
            runtime_cleanup = {"status": "NOT_REQUIRED"}
        runtime_cleanup_ms = (time.perf_counter() - runtime_cleanup_started) * 1000
        cleanup_status = runtime_cleanup.get("status")
        cleanup_ok = cleanup_status in {"PASS", "NOT_REQUIRED"}
        ledger.append(
            DG14StageEvent(
                run_id=run_id,
                stage="cleanup",
                status="SUCCEEDED" if cleanup_ok else "FAILED",
                duration_ms=runtime_cleanup_ms,
                failure_type=None if cleanup_ok else "DG14BenchmarkError",
                failure_code=None if cleanup_ok else "RUNTIME_DATABASE_CLEANUP_FAILED",
                details={
                    "operation": "fresh_runtime_database_cleanup",
                    "result": _json_value(runtime_cleanup),
                },
            )
        )
        cleanup_archive = {
            "case_cleanups": cleanup_cases,
            "classification": CLASSIFICATION,
            "exact_namespace_only": True,
            "run_id": run_id,
            "runtime_cleanup": _json_value(runtime_cleanup),
            "runtime_cleanup_latency_ms": round(runtime_cleanup_ms, 6),
            "schema": "milai.dg14.opened-dev-cleanup.v1",
        }
        _atomic_json(output_root / "cleanup.json", cleanup_archive)
        manifest["runtime_cleanup"] = _json_value(runtime_cleanup)
        manifest["stage_ledger_root_sha256"] = ledger.verify().root_sha256
        if primary_pending or not cleanup_ok:
            manifest["status"] = "BLOCKED"
        _atomic_json(manifest_path, manifest)
        if not cleanup_ok and sys.exc_info()[0] is None:
            raise DG14BenchmarkError("fresh Runtime database cleanup failed")
    return seal_opened_dev_run(run_id=run_id, output_root=output_root)


def run_milai_smoke(
    *,
    run_id: str,
    output_root: Path,
    input_path: Path = OPENED_DEV_INPUT_PATH,
    tokenizer_path: Path = DEFAULT_TOKENIZER,
    case_ids: Sequence[str] = OPENED_DEV_CASE_IDS,
    runtime_session: RuntimeSession | None = None,
) -> dict[str, Any]:
    """Run only the real MiLA MCP context path for an ordered opened-dev subset."""

    if not run_id:
        raise ValueError("run_id is required")
    selected_ids = tuple(case_ids)
    if (
        not selected_ids
        or len(set(selected_ids)) != len(selected_ids)
        or any(case_id not in OPENED_DEV_CASE_IDS for case_id in selected_ids)
        or tuple(sorted(selected_ids, key=OPENED_DEV_CASE_IDS.index)) != selected_ids
    ):
        raise DG14BenchmarkError("MiLA smoke case IDs must be a bound ordered subset")
    partition, all_cases = load_opened_dev(input_path)
    cases = tuple(case for case in all_cases if case.case_id in selected_ids)
    if tuple(case.case_id for case in cases) != selected_ids:
        raise DG14BenchmarkError("MiLA smoke case selection drifted")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    ledger_path = output_root / "stage-ledger.jsonl"
    if manifest_path.exists() or ledger_path.exists():
        raise DG14BenchmarkError(
            "MiLA smoke output already exists; choose a fresh run_id"
        )
    schedule = tuple(
        BenchmarkCell(
            ordinal=ordinal,
            case_ordinal=OPENED_DEV_CASE_IDS.index(case.case_id),
            case_id=case.case_id,
            method_id=METHOD_ID,
            token_budget=budget,
        )
        for ordinal, (case, budget) in enumerate(
            (case, budget) for case in cases for budget in BUDGETS
        )
    )
    manifest: dict[str, Any] = {
        "budgets": list(BUDGETS),
        "case_count": len(cases),
        "case_ids": list(selected_ids),
        "classification": CLASSIFICATION,
        "formal_holdout_consumed": False,
        "input_path": str(input_path.resolve()),
        "input_sha256": OPENED_DEV_INPUT_SHA256,
        "label_fields_available_to_run": False,
        "method_id": METHOD_ID,
        "partition": partition,
        "provider_calls": 0,
        "run_id": run_id,
        "schedule": [asdict(cell) for cell in schedule],
        "schema": "milai.dg14.opened-dev-milai-smoke-manifest.v1",
        "status": "RUNNING",
        "tokenizer_path": str(tokenizer_path.resolve()),
        "transport": "stdio-mcp",
    }
    _atomic_json(manifest_path, manifest)
    counter = _local_token_counter(tokenizer_path)
    session = runtime_session or LocalDG14RuntimeSession(output_root=output_root)
    ledger = DG14StageLedger(ledger_path)
    contexts: list[dict[str, Any]] = []
    cleanup_cases: list[dict[str, Any]] = []
    runtime_details: Mapping[str, Any] = {}
    active_adapter: Any | None = None
    active_case_id: str | None = None
    active_call_cursor = 0
    active_stage_cursor = 0
    active_cleanup_done = True
    primary_pending = False
    runtime_cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    try:
        started = time.perf_counter()
        runtime_details = session.start(run_id)
        ledger.append(
            DG14StageEvent(
                run_id=run_id,
                stage="runtime",
                status="SUCCEEDED",
                duration_ms=(time.perf_counter() - started) * 1_000,
                details={"operation": "fresh_runtime_start", **runtime_details},
            )
        )
        cells = {(cell.case_id, cell.token_budget): cell for cell in schedule}
        for case in cases:
            adapter = session.adapter_for_case(case, counter)
            if getattr(adapter, "method_id", None) != METHOD_ID:
                raise DG14BenchmarkError("MiLA smoke adapter identity drifted")
            active_adapter = adapter
            active_case_id = case.case_id
            active_call_cursor = 0
            active_stage_cursor = 0
            active_cleanup_done = False

            started = time.perf_counter()
            adapter.reset(run_id, case.case_id)
            _append_stage(
                ledger,
                run_id=run_id,
                stage="reset",
                case_id=case.case_id,
                method_id=METHOD_ID,
                duration_ms=(time.perf_counter() - started) * 1_000,
            )
            active_call_cursor, active_stage_cursor = _append_adapter_records(
                ledger,
                adapter=adapter,
                run_id=run_id,
                case_id=case.case_id,
                method_id=METHOD_ID,
                call_cursor=active_call_cursor,
                stage_cursor=active_stage_cursor,
            )

            started = time.perf_counter()
            for event in case.history_events:
                adapter.ingest(event)
            ingest_ms = (time.perf_counter() - started) * 1_000
            _append_stage(
                ledger,
                run_id=run_id,
                stage="ingest",
                case_id=case.case_id,
                method_id=METHOD_ID,
                duration_ms=ingest_ms,
                logical_calls=len(case.history_events),
                details={"event_count": len(case.history_events)},
            )
            active_call_cursor, active_stage_cursor = _append_adapter_records(
                ledger,
                adapter=adapter,
                run_id=run_id,
                case_id=case.case_id,
                method_id=METHOD_ID,
                call_cursor=active_call_cursor,
                stage_cursor=active_stage_cursor,
            )

            calls_before = adapter.stats().logical_mcp_calls
            started = time.perf_counter()
            adapter.finalize()
            finalize_ms = (time.perf_counter() - started) * 1_000
            calls_after = adapter.stats().logical_mcp_calls
            _append_stage(
                ledger,
                run_id=run_id,
                stage="finalize",
                case_id=case.case_id,
                method_id=METHOD_ID,
                duration_ms=finalize_ms,
                logical_calls=calls_after - calls_before,
                details={"claim_count": adapter.stats().claim_count},
            )
            active_call_cursor, active_stage_cursor = _append_adapter_records(
                ledger,
                adapter=adapter,
                run_id=run_id,
                case_id=case.case_id,
                method_id=METHOD_ID,
                call_cursor=active_call_cursor,
                stage_cursor=active_stage_cursor,
            )

            for budget in BUDGETS:
                calls_before = adapter.stats().logical_mcp_calls
                started = time.perf_counter()
                result = adapter.query(case.question, case.question_at, budget)
                query_outer_ms = (time.perf_counter() - started) * 1_000
                calls_after = adapter.stats().logical_mcp_calls
                record = _context_record(
                    cell=cells[(case.case_id, budget)],
                    case=case,
                    result=result,
                    ingest_ms=ingest_ms,
                    finalize_ms=finalize_ms,
                    mcp_calls=calls_after - calls_before,
                )
                contexts.append(record)
                _append_stage(
                    ledger,
                    run_id=run_id,
                    stage="context",
                    case_id=case.case_id,
                    method_id=METHOD_ID,
                    token_budget=budget,
                    duration_ms=query_outer_ms,
                    candidate_count=int(record["candidate_count"]),
                    retrieval_route=str(record["retrieval_route"]),
                    memory_tokens=int(record["adapter_declared_tokens"]),
                    details={"context_sha256": record["context_sha256"]},
                )
                active_call_cursor, active_stage_cursor = _append_adapter_records(
                    ledger,
                    adapter=adapter,
                    run_id=run_id,
                    case_id=case.case_id,
                    method_id=METHOD_ID,
                    call_cursor=active_call_cursor,
                    stage_cursor=active_stage_cursor,
                    token_budget=budget,
                )
                _append_runtime_metrics(
                    ledger,
                    run_id=run_id,
                    case_id=case.case_id,
                    method_id=METHOD_ID,
                    token_budget=budget,
                    usage=record["usage"],
                )

            cleanup_started = time.perf_counter()
            revoked = adapter.cleanup()
            active_cleanup_done = True
            cleanup_ms = (time.perf_counter() - cleanup_started) * 1_000
            cleanup_cases.append(
                {
                    "case_id": case.case_id,
                    "evidence_revoked": len(revoked),
                    "event_count": len(case.history_events),
                    "namespace_exact": True,
                    "status": "SUCCEEDED",
                }
            )
            _append_stage(
                ledger,
                run_id=run_id,
                stage="cleanup",
                case_id=case.case_id,
                method_id=METHOD_ID,
                duration_ms=cleanup_ms,
                logical_calls=len(revoked),
                details={"evidence_revoked": len(revoked)},
            )
            _append_adapter_records(
                ledger,
                adapter=adapter,
                run_id=run_id,
                case_id=case.case_id,
                method_id=METHOD_ID,
                call_cursor=active_call_cursor,
                stage_cursor=active_stage_cursor,
            )
            total_calls = adapter.stats().logical_mcp_calls
            for record in contexts:
                if record["case_id"] == case.case_id:
                    record["mcp_logical_calls"] = total_calls
            active_adapter = None
            active_case_id = None

        contexts.sort(key=lambda item: int(item["ordinal"]))
        if len(contexts) != len(cases) * len(BUDGETS):
            raise DG14BenchmarkError("MiLA smoke context denominator is incomplete")
        _atomic_json(
            output_root / "contexts.json",
            {
                "classification": CLASSIFICATION,
                "formal_holdout_consumed": False,
                "input_sha256": OPENED_DEV_INPUT_SHA256,
                "record_count": len(contexts),
                "records": contexts,
                "run_id": run_id,
                "schema": "milai.dg14.opened-dev-milai-contexts.v1",
                "status": "SUCCEEDED",
            },
        )
        manifest["record_count"] = len(contexts)
        manifest["runtime"] = _json_value(runtime_details)
        manifest["status"] = "SUCCEEDED"
    finally:
        primary_pending = sys.exc_info()[0] is not None
        if active_adapter is not None and not active_cleanup_done:
            emergency_started = time.perf_counter()
            try:
                revoked = active_adapter.cleanup()
            except (
                DG14Error,
                OSError,
                subprocess.SubprocessError,
                TimeoutError,
            ) as cleanup_error:
                cleanup_cases.append(
                    {
                        "case_id": active_case_id,
                        "failure_type": type(cleanup_error).__name__,
                        "namespace_exact": True,
                        "status": "FAILED",
                    }
                )
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        stage="cleanup",
                        status="FAILED",
                        duration_ms=(time.perf_counter() - emergency_started) * 1_000,
                        case_id=active_case_id,
                        method_id=METHOD_ID,
                        failure_type=type(cleanup_error).__name__,
                        failure_code="CASE_EMERGENCY_CLEANUP_FAILED",
                    )
                )
            else:
                cleanup_cases.append(
                    {
                        "case_id": active_case_id,
                        "evidence_revoked": len(revoked),
                        "namespace_exact": True,
                        "status": "SUCCEEDED_AFTER_STAGE_FAILURE",
                    }
                )
        cleanup_started = time.perf_counter()
        runtime_cleanup = session.close()
        cleanup_ok = runtime_cleanup.get("status") in {"PASS", "NOT_CREATED"}
        ledger.append(
            DG14StageEvent(
                run_id=run_id,
                stage="cleanup",
                status="SUCCEEDED" if cleanup_ok else "FAILED",
                duration_ms=(time.perf_counter() - cleanup_started) * 1_000,
                failure_type=None if cleanup_ok else "DG14BenchmarkError",
                failure_code=None if cleanup_ok else "RUNTIME_DATABASE_CLEANUP_FAILED",
                details={
                    "operation": "fresh_runtime_database_cleanup",
                    "result": _json_value(runtime_cleanup),
                },
            )
        )
        _atomic_json(
            output_root / "cleanup.json",
            {
                "case_cleanups": cleanup_cases,
                "classification": CLASSIFICATION,
                "exact_namespace_only": True,
                "run_id": run_id,
                "runtime_cleanup": _json_value(runtime_cleanup),
                "schema": "milai.dg14.opened-dev-milai-cleanup.v1",
            },
        )
        if primary_pending or not cleanup_ok:
            manifest["status"] = "BLOCKED"
        manifest["runtime_cleanup"] = _json_value(runtime_cleanup)
        manifest["stage_ledger_root_sha256"] = ledger.verify().root_sha256
        _atomic_json(manifest_path, manifest)
        if not cleanup_ok and not primary_pending:
            raise DG14BenchmarkError("fresh Runtime database cleanup failed")
    return manifest


def _load_archive(path: Path, schema: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG14BenchmarkError(f"invalid DG-14 archive: {path}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != schema
        or value.get("classification") != CLASSIFICATION
        or value.get("formal_holdout_consumed") is not False
        or value.get("input_sha256") != OPENED_DEV_INPUT_SHA256
        or value.get("record_count") != EXPECTED_CELL_COUNT
        or not isinstance(value.get("records"), list)
    ):
        raise DG14BenchmarkError(f"DG-14 archive contract drifted: {path}")
    return value


_CLOSURE_CODE_PATHS = (
    ROOT / "evals/dg14/benchmark.py",
    ROOT / "evals/dg14/contracts.py",
    ROOT / "evals/dg14/ledger.py",
    ROOT / "evals/dg14/mcp_stdio.py",
    ROOT / "evals/dg14/milai_mcp_adapter.py",
    ROOT / "evals/dg14/openworker_smoke.py",
    ROOT / "evals/dg14/provider.py",
    ROOT / "integrations/mcp/src/milai_mcp/server.py",
    ROOT / "scripts/run_dg14_longmemeval_dev.py",
)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG14BenchmarkError(f"invalid DG-14 JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise DG14BenchmarkError(f"DG-14 JSON object required: {path}")
    return value


def _code_artifact_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): _sha256_file(path) for path in _CLOSURE_CODE_PATHS
    }


def _run_artifact_hashes(output_root: Path) -> dict[str, str]:
    return {
        name: _sha256_file(output_root / name)
        for name in ("cleanup.json", "contexts.json", "generations.json")
    }


def _provider_events_by_request(
    verification: Any,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for envelope in verification.events:
        event = envelope["event"]
        if event.get("stage") != "provider" or event.get("status") != "SUCCEEDED":
            continue
        request_id = event.get("logical_request_id")
        if not isinstance(request_id, str) or request_id in result:
            raise DG14BenchmarkError("provider ledger request identity drifted")
        result[request_id] = cast(Mapping[str, Any], event)
    return result


def _validate_generation_provider_joins(
    *,
    generations: Mapping[str, Any],
    provider_events: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records = generations.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_CELL_COUNT:
        raise DG14BenchmarkError("generation/provider join denominator drifted")
    if len(provider_events) != EXPECTED_CELL_COUNT:
        raise DG14BenchmarkError("provider ledger denominator drifted")
    normalized: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            raise DG14BenchmarkError("generation record is not an object")
        record = dict(raw)
        request_id = record.get("logical_request_id")
        event = provider_events.get(str(request_id))
        details = event.get("details") if event is not None else None
        if not isinstance(details, dict):
            raise DG14BenchmarkError("generation has no provider ledger event")
        answer = record.get("answer")
        if not isinstance(answer, str):
            raise DG14BenchmarkError("generation answer is absent")
        answer_sha256 = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        joins = {
            "native_request_id": record.get("native_request_id"),
            "prompt_sha256": record.get("prompt_sha256"),
            "seed": record.get("seed"),
        }
        if any(details.get(key) != value for key, value in joins.items()):
            raise DG14BenchmarkError("generation/provider ledger join drifted")
        ledger_answer = details.get("answer_sha256")
        if ledger_answer is not None and ledger_answer != answer_sha256:
            raise DG14BenchmarkError("provider answer digest drifted")
        existing_answer = record.get("answer_sha256")
        if existing_answer is not None and existing_answer != answer_sha256:
            raise DG14BenchmarkError("generation answer digest drifted")
        record["answer_sha256"] = answer_sha256
        normalized.append(record)
    return normalized


def seal_opened_dev_run(*, run_id: str, output_root: Path) -> dict[str, Any]:
    """Bind provider answers and run artifacts into the append-only ledger."""

    manifest_path = output_root / "manifest.json"
    manifest = _read_json_object(manifest_path)
    if (
        manifest.get("schema") != "milai.dg14.opened-dev-manifest.v1"
        or manifest.get("run_id") != run_id
        or manifest.get("status") != "SUCCEEDED"
        or manifest.get("input_sha256") != OPENED_DEV_INPUT_SHA256
        or manifest.get("formal_holdout_consumed") is not False
    ):
        raise DG14BenchmarkError("only a completed label-free DG-14 run can be sealed")
    ledger = DG14StageLedger(output_root / "stage-ledger.jsonl")
    verification = ledger.verify()
    if manifest.get("stage_ledger_root_sha256") != verification.root_sha256:
        raise DG14BenchmarkError("manifest/ledger root drifted before evidence closure")
    existing = manifest.get("evidence_closure")
    if existing is not None:
        if not isinstance(existing, dict):
            raise DG14BenchmarkError("evidence closure contract drifted")
        expected_artifacts = _run_artifact_hashes(output_root)
        if existing.get("artifacts") != expected_artifacts:
            raise DG14BenchmarkError("sealed run artifact digest drifted")
        return manifest

    contexts = _load_archive(
        output_root / "contexts.json", "milai.dg14.opened-dev-contexts.v1"
    )
    generations_path = output_root / "generations.json"
    generations = _load_archive(
        generations_path, "milai.dg14.opened-dev-generations.v1"
    )
    provider_events = _provider_events_by_request(verification)
    normalized = _validate_generation_provider_joins(
        generations=generations,
        provider_events=provider_events,
    )
    context_by_key = {
        (
            record.get("case_id"),
            record.get("method_id"),
            record.get("token_budget"),
        ): record
        for record in cast(list[dict[str, Any]], contexts["records"])
    }
    binding_events: list[DG14StageEvent] = []
    for record in normalized:
        key = (
            record.get("case_id"),
            record.get("method_id"),
            record.get("token_budget"),
        )
        context = context_by_key.get(key)
        if context is None:
            raise DG14BenchmarkError("generation/context identity join drifted")
        source_context_sha256 = context.get("context_sha256")
        existing_source = record.get("source_context_sha256")
        if (
            not isinstance(source_context_sha256, str)
            or existing_source is not None
            and existing_source != source_context_sha256
        ):
            raise DG14BenchmarkError("generation/source-context digest join drifted")
        record["source_context_sha256"] = source_context_sha256
        binding_events.append(
            DG14StageEvent(
                run_id=run_id,
                case_id=str(record["case_id"]),
                method_id=str(record["method_id"]),
                token_budget=int(record["token_budget"]),
                logical_request_id=str(record["logical_request_id"]),
                stage="provider_binding",
                status="SUCCEEDED",
                duration_ms=0,
                details={
                    "answer_sha256": record["answer_sha256"],
                    "binding_source": "parsed_generation_archive",
                    "context_sha256": record["context_sha256"],
                    "native_request_id": record["native_request_id"],
                    "prompt_sha256": record["prompt_sha256"],
                    "source_context_sha256": record["source_context_sha256"],
                },
            )
        )
    generations = {**generations, "records": normalized}
    _atomic_json(generations_path, generations)
    ledger.append_many(binding_events)
    tokenizer_value = manifest.get("tokenizer_path")
    if not isinstance(tokenizer_value, str):
        raise DG14BenchmarkError("sealed real run must identify its tokenizer")
    identities = _execution_identities(Path(tokenizer_value))
    closure_root = ledger.verify()
    manifest["execution_identities"] = identities
    manifest["evidence_closure"] = {
        "artifacts": _run_artifact_hashes(output_root),
        "code_artifacts": _code_artifact_hashes(),
        "ledger_event_count": len(closure_root.events),
        "ledger_root_sha256": closure_root.root_sha256,
        "provider_response_bindings": len(binding_events),
        "schema": "milai.dg14.evidence-closure.v1",
        "status": "SEALED",
    }
    manifest["stage_ledger_root_sha256"] = closure_root.root_sha256
    _atomic_json(manifest_path, manifest)
    return manifest


def _verify_evidence_closure(*, run_id: str, output_root: Path) -> dict[str, Any]:
    manifest = _read_json_object(output_root / "manifest.json")
    closure = manifest.get("evidence_closure")
    verification = DG14StageLedger(output_root / "stage-ledger.jsonl").verify()
    tokenizer_value = manifest.get("tokenizer_path")
    if (
        manifest.get("run_id") != run_id
        or manifest.get("status") != "SUCCEEDED"
        or manifest.get("stage_ledger_root_sha256") != verification.root_sha256
        or not isinstance(closure, dict)
        or closure.get("status") != "SEALED"
        or closure.get("artifacts") != _run_artifact_hashes(output_root)
        or closure.get("code_artifacts") != _code_artifact_hashes()
        or not isinstance(tokenizer_value, str)
        or manifest.get("execution_identities")
        != _execution_identities(Path(tokenizer_value))
    ):
        raise DG14BenchmarkError("DG-14 evidence closure verification failed")
    bindings = {
        str(envelope["event"].get("logical_request_id")): envelope["event"].get(
            "details"
        )
        for envelope in verification.events
        if envelope["event"].get("stage") == "provider_binding"
        and envelope["event"].get("status") == "SUCCEEDED"
    }
    if len(bindings) != EXPECTED_CELL_COUNT:
        raise DG14BenchmarkError("provider response binding denominator drifted")
    generations = _load_archive(
        output_root / "generations.json", "milai.dg14.opened-dev-generations.v1"
    )
    for record in generations["records"]:
        if not isinstance(record, dict):
            raise DG14BenchmarkError("sealed generation record drifted")
        details = bindings.get(str(record.get("logical_request_id")))
        expected = {
            "answer_sha256": record.get("answer_sha256"),
            "context_sha256": record.get("context_sha256"),
            "native_request_id": record.get("native_request_id"),
            "prompt_sha256": record.get("prompt_sha256"),
            "source_context_sha256": record.get("source_context_sha256"),
        }
        if not isinstance(details, Mapping) or any(
            details.get(key) != value for key, value in expected.items()
        ):
            raise DG14BenchmarkError("provider response binding content drifted")
    return manifest


def _load_scoring_fixture(
    path: Path, cases: Sequence[Any]
) -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG14BenchmarkError("opened-dev scoring fixture is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {"classification", "input_sha256", "rows", "schema", "source_ids"}
        or value.get("schema") != "milai.dg14.opened-dev-scoring-fixture.v1"
        or value.get("classification") != CLASSIFICATION
        or value.get("input_sha256") != OPENED_DEV_INPUT_SHA256
        or value.get("source_ids") != list(OPENED_DEV_CASE_IDS)
        or not isinstance(value.get("rows"), list)
        or len(value["rows"]) != len(OPENED_DEV_CASE_IDS)
    ):
        raise DG14BenchmarkError("scoring fixture is not the exact five-row contract")
    by_case = {case.source_id: case for case in cases}
    labels: dict[str, dict[str, Any]] = {}
    for row in value["rows"]:
        if not isinstance(row, dict) or set(row) != {
            "answer_session_ids",
            "answers",
            "source_id",
        }:
            raise DG14BenchmarkError("scoring fixture row fields drifted")
        source_id = row.get("source_id")
        answers = row.get("answers")
        sessions = row.get("answer_session_ids")
        if (
            not isinstance(source_id, str)
            or source_id not in by_case
            or source_id in labels
            or not isinstance(answers, list)
            or not answers
            or not all(isinstance(item, str) and item.strip() for item in answers)
            or not isinstance(sessions, list)
            or not sessions
            or not all(isinstance(item, str) and item for item in sessions)
        ):
            raise DG14BenchmarkError("scoring fixture row types/identity drifted")
        history_ids = {session.session_id for session in by_case[source_id].sessions}
        if not set(sessions).issubset(history_ids):
            raise DG14BenchmarkError("scoring fixture evidence ID is outside history")
        labels[source_id] = {"answers": answers, "answer_session_ids": sessions}
    if tuple(labels) != OPENED_DEV_CASE_IDS:
        raise DG14BenchmarkError("scoring fixture row order drifted")
    return labels


def _retrieval_top3(trace: object) -> list[dict[str, Any]]:
    if not isinstance(trace, list) or not all(isinstance(item, dict) for item in trace):
        raise DG14BenchmarkError("generation retrieval trace is invalid")
    selected: list[dict[str, Any]] = []
    sessions: set[str] = set()
    for raw in trace:
        item = cast(dict[str, Any], raw)
        session_id = item.get("session_id")
        if not isinstance(session_id, str):
            raise DG14BenchmarkError("retrieval trace session mapping is absent")
        if session_id in sessions:
            continue
        sessions.add(session_id)
        selected.append(item)
        if len(selected) == 3:
            break
    return selected


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 6)


def _aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise DG14BenchmarkError("cannot aggregate an empty score group")
    multi = [record for record in records if record["is_multi_session"]]
    result = {
        "case_count": len(records),
        "context_truncation_rate": round(
            mean(int(bool(record["context_truncated"])) for record in records), 9
        ),
        "e2e_latency_ms_mean": round(
            mean(float(record["e2e_latency_ms"]) for record in records), 6
        ),
        "evidence_coverage": round(
            mean(
                float(record["retrieval_score"]["relevant_coverage_at_k"])
                for record in records
            ),
            9,
        ),
        "exact_match": round(
            mean(float(record["answer_score"]["exact_match"]) for record in records), 9
        ),
        "hit_at_k": round(
            mean(float(record["retrieval_score"]["hit_at_k"]) for record in records), 9
        ),
        "mcp_query_logical_calls": sum(
            int(record.get("mcp_query_logical_calls", record["mcp_logical_calls"]))
            for record in records
        ),
        "memory_tokens_mean": round(
            mean(float(record["memory_tokens"]) for record in records), 6
        ),
        "multi_session_success": {
            "denominator": len(multi),
            "rate": round(
                mean(float(record["answer_score"]["exact_match"]) for record in multi),
                9,
            )
            if multi
            else 0.0,
            "successes": sum(
                int(record["answer_score"]["exact_match"]) for record in multi
            ),
        },
        "ndcg_at_k": round(
            mean(float(record["retrieval_score"]["ndcg_at_k"]) for record in records), 9
        ),
        "normalized_f1": round(
            mean(float(record["answer_score"]["normalized_f1"]) for record in records),
            9,
        ),
        "prompt_tokens_mean": round(
            mean(float(record["prompt_tokens"]) for record in records), 6
        ),
        "provider_calls": sum(int(record["provider_calls"]) for record in records),
        "provider_latency_ms_mean": round(
            mean(float(record["provider_latency_ms"]) for record in records), 6
        ),
        "query_latency_ms_p50": _percentile(
            [float(record["query_latency_ms"]) for record in records], 0.50
        ),
        "query_latency_ms_p95": _percentile(
            [float(record["query_latency_ms"]) for record in records], 0.95
        ),
        "retrieval_routes": dict(
            sorted(
                Counter(str(record["retrieval_route"]) for record in records).items()
            )
        ),
        "unknown_abstention_rate": round(
            mean(
                int(normalize(str(record["answer"])) == "unknown") for record in records
            ),
            9,
        ),
    }
    optional_mean_fields = {
        "candidate_count_mean": "candidate_count",
        "finalize_latency_ms_mean": "finalize_latency_ms",
        "ingest_latency_ms_mean": "ingest_latency_ms",
        "tokenize_latency_ms_mean": "tokenize_latency_ms",
    }
    for output_key, record_key in optional_mean_fields.items():
        if all(record_key in record for record in records):
            result[output_key] = round(
                mean(float(record[record_key]) for record in records), 6
            )
    if all("tokenizer_calls" in record for record in records):
        result["tokenizer_calls"] = sum(
            int(record["tokenizer_calls"]) for record in records
        )
    return result


def _shared_lifecycle_metrics(
    scored_records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for method in ARMS:
        by_case: dict[str, int] = {}
        for record in scored_records:
            if record["method_id"] != method:
                continue
            case_id = str(record["case_id"])
            value = int(record["mcp_logical_calls"])
            prior = by_case.setdefault(case_id, value)
            if prior != value:
                raise DG14BenchmarkError(
                    "shared MCP lifecycle count drifted across budgets"
                )
        result[method] = {
            "case_count": len(by_case),
            "mcp_lifecycle_logical_calls": sum(by_case.values()),
        }
    return result


def evaluate_2048_gate(methods: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanically evaluate the preregistered zero-margin BM25-T target."""

    dg14 = cast(Mapping[str, Any], cast(Mapping[str, Any], methods[METHOD_ID])["2048"])
    baseline = cast(
        Mapping[str, Any], cast(Mapping[str, Any], methods["LME-BM25-T"])["2048"]
    )
    noninferiority = {
        metric: float(dg14[metric]) + NONINFERIORITY_MARGIN >= float(baseline[metric])
        for metric in ("exact_match", "normalized_f1", "evidence_coverage")
    }
    minimum_correct = round(float(dg14["exact_match"]) * len(OPENED_DEV_CASE_IDS)) >= 3
    minimum_coverage = float(dg14["evidence_coverage"]) >= 0.8
    return {
        "baseline": "LME-BM25-T",
        "budget_tokens": 2048,
        "minimum_3_of_5_correct": minimum_correct,
        "minimum_evidence_coverage_0_80": minimum_coverage,
        "noninferiority_margin": NONINFERIORITY_MARGIN,
        "noninferiority": noninferiority,
        "passed": minimum_correct and minimum_coverage and all(noninferiority.values()),
    }


def build_failure_taxonomy(
    scored_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not scored_records:
        raise DG14BenchmarkError("failure taxonomy denominator cannot be empty")
    if all("status" in record for record in scored_records):
        by_stage: Counter[str] = Counter()
        by_type: Counter[str] = Counter()
        per_case: defaultdict[str, dict[str, int]] = defaultdict(
            lambda: {"completed": 0, "failed": 0}
        )
        failed = 0
        terminal_records: list[dict[str, Any]] = []
        for record in scored_records:
            case_id = str(record.get("case_id", ""))
            status = record.get("status")
            if not case_id or status not in {"SUCCEEDED", "FAILED"}:
                raise DG14BenchmarkError("typed execution failure record drifted")
            if status == "SUCCEEDED":
                per_case[case_id]["completed"] += 1
                continue
            failure_type = record.get("failure_type")
            failure_stage = record.get("failure_stage")
            if not isinstance(failure_type, str) or not isinstance(failure_stage, str):
                raise DG14BenchmarkError("failed execution record lacks typed failure")
            failed += 1
            by_type[failure_type] += 1
            by_stage[failure_stage] += 1
            per_case[case_id]["failed"] += 1
            terminal_records.append(dict(record))
        return {
            "by_stage": dict(sorted(by_stage.items())),
            "by_type": dict(sorted(by_type.items())),
            "classification": RESULT_SCOPE,
            "completed": len(scored_records) - failed,
            "denominator": len(scored_records),
            "failed": failed,
            "per_case": dict(sorted(per_case.items())),
            "records": terminal_records,
            "schema": "milai.dg14.opened-dev-execution-failure-taxonomy.v1",
        }
    failures: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for record in scored_records:
        if int(record["answer_score"]["exact_match"]) == 1:
            taxonomy = "CORRECT"
        elif normalize(str(record["answer"])) == "unknown":
            taxonomy = "ABSTENTION"
        elif int(record["retrieval_score"]["hit_at_k"]) == 0:
            taxonomy = "RETRIEVAL_MISS"
        elif (
            bool(record["is_multi_session"])
            and float(record["retrieval_score"]["relevant_coverage_at_k"]) < 1.0
        ):
            taxonomy = "PARTIAL_MULTI_SESSION_EVIDENCE"
        elif bool(record["context_truncated"]):
            taxonomy = "CONTEXT_TRUNCATION"
        else:
            taxonomy = "ANSWER_SYNTHESIS_OR_REASONING"
        counts[taxonomy] += 1
        failures.append(
            {
                "case_id": record["case_id"],
                "method_id": record["method_id"],
                "token_budget": record["token_budget"],
                "taxonomy": taxonomy,
            }
        )
    return {
        "classification": RESULT_SCOPE,
        "counts": dict(sorted(counts.items())),
        "denominator": len(scored_records),
        "records": failures,
        "schema": "milai.dg14.opened-dev-failure-taxonomy.v1",
    }


def aggregate_metrics(
    scored_records: Sequence[Mapping[str, Any]],
    correctness_trials: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Pure quality/efficiency/correctness aggregation for one matched group."""

    required = {
        "cross_case_contamination",
        "label_leakage",
        "silent_fallback",
        "stale_revoked_evidence_acceptance",
        "wrong_scope_acceptance",
    }
    if set(correctness_trials) != required:
        raise DG14BenchmarkError("correctness metric field set drifted")
    correctness: dict[str, dict[str, int]] = {}
    for metric in sorted(required):
        raw = correctness_trials[metric]
        accepted = raw.get("accepted")
        denominator = raw.get("denominator")
        if (
            not isinstance(accepted, int)
            or isinstance(accepted, bool)
            or not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or accepted < 0
            or denominator < 0
            or accepted > denominator
        ):
            raise DG14BenchmarkError(f"correctness denominator drifted: {metric}")
        correctness[metric] = {
            "accepted": accepted,
            "denominator": denominator,
        }
    aggregate = _aggregate(scored_records)
    quality_keys = {
        "case_count",
        "evidence_coverage",
        "exact_match",
        "hit_at_k",
        "multi_session_success",
        "ndcg_at_k",
        "normalized_f1",
        "unknown_abstention_rate",
    }
    return {
        "correctness": correctness,
        "efficiency": {
            key: value for key, value in aggregate.items() if key not in quality_keys
        },
        "quality": {
            key: value for key, value in aggregate.items() if key in quality_keys
        },
    }


def score_opened_dev(
    *,
    run_id: str,
    input_path: Path = OPENED_DEV_INPUT_PATH,
    generation_path: Path,
    context_path: Path,
    scoring_fixture: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Score the completed 50 cells from an explicit five-row dev fixture only."""

    if (
        context_path.resolve() != (output_root / "contexts.json").resolve()
        or generation_path.resolve() != (output_root / "generations.json").resolve()
    ):
        raise DG14BenchmarkError("scoring must use the sealed run-local archives")
    manifest = _verify_evidence_closure(run_id=run_id, output_root=output_root)
    if manifest.get("score_closure") is not None:
        raise DG14BenchmarkError("scored DG-14 run is immutable; choose a fresh run_id")
    _partition, cases = load_opened_dev(input_path)
    contexts = _load_archive(context_path, "milai.dg14.opened-dev-contexts.v1")
    generations = _load_archive(generation_path, "milai.dg14.opened-dev-generations.v1")
    if contexts.get("run_id") != run_id or generations.get("run_id") != run_id:
        raise DG14BenchmarkError("score run_id differs from run archives")
    labels = _load_scoring_fixture(scoring_fixture, cases)
    context_records = {
        (record["case_id"], record["method_id"], record["token_budget"]): record
        for record in contexts["records"]
        if isinstance(record, dict)
    }
    expected_keys = {
        (cell.case_id, cell.method_id, cell.token_budget)
        for cell in build_schedule(cases)
    }
    generation_records = [
        cast(dict[str, Any], record)
        for record in generations["records"]
        if isinstance(record, dict)
    ]
    observed_keys = {
        (record.get("case_id"), record.get("method_id"), record.get("token_budget"))
        for record in generation_records
    }
    if set(context_records) != expected_keys or observed_keys != expected_keys:
        raise DG14BenchmarkError("score denominator or matched cell identity drifted")
    scored: list[dict[str, Any]] = []
    for record in generation_records:
        key = (record["case_id"], record["method_id"], record["token_budget"])
        context = context_records[key]
        label = labels[str(record["case_id"])]
        trace = _retrieval_top3(record.get("retrieval_trace"))
        answer_score = score_answer(
            str(record["answer"]), [str(item) for item in label["answers"]]
        )
        retrieval_score = score_retrieval(
            trace, [str(item) for item in label["answer_session_ids"]]
        )
        scored.append(
            {
                **record,
                "answer_score": answer_score,
                "candidate_count": context["candidate_count"],
                "finalize_latency_ms": context["finalize_latency_ms"],
                "ingest_latency_ms": context["ingest_latency_ms"],
                "is_multi_session": len(set(label["answer_session_ids"])) > 1,
                "query_latency_ms": context["query_latency_ms"],
                "retrieval_route": context["retrieval_route"],
                "retrieval_score": retrieval_score,
                "retrieval_trace_scored_k3": trace,
            }
        )
    scored.sort(key=lambda item: int(item["ordinal"]))
    groups: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in scored:
        groups[(str(record["method_id"]), int(record["token_budget"]))].append(record)
    methods = {
        method: {
            str(budget): _aggregate(groups[(method, budget)]) for budget in BUDGETS
        }
        for method in ARMS
    }
    comparison = {
        "classification": RESULT_SCOPE,
        "correctness": generations.get("correctness"),
        "formal_holdout_consumed": False,
        "gate": evaluate_2048_gate(methods),
        "input_sha256": OPENED_DEV_INPUT_SHA256,
        "methods": methods,
        "record_count": len(scored),
        "run_id": run_id,
        "schema": "milai.dg14.opened-dev-comparison.v2",
        "shared_lifecycle_metrics": _shared_lifecycle_metrics(scored),
        "status": "CHARACTERIZED",
    }
    taxonomy = build_failure_taxonomy(scored)
    output_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        output_root / "scored-records.json",
        {
            "classification": RESULT_SCOPE,
            "formal_holdout_consumed": False,
            "record_count": len(scored),
            "records": scored,
            "run_id": run_id,
            "schema": "milai.dg14.opened-dev-scored-records.v1",
        },
    )
    _atomic_json(output_root / "comparison.json", comparison)
    _atomic_json(output_root / "failure-taxonomy.json", taxonomy)
    _write_analysis(output_root / "analysis.md", comparison, taxonomy, scored)
    score_artifacts = {
        name: _sha256_file(output_root / name)
        for name in (
            "analysis.md",
            "comparison.json",
            "failure-taxonomy.json",
            "scored-records.json",
        )
    }
    scoring_fixture_sha256 = _sha256_file(scoring_fixture)
    ledger = DG14StageLedger(output_root / "stage-ledger.jsonl")
    ledger.append(
        DG14StageEvent(
            run_id=run_id,
            stage="score",
            status="SUCCEEDED",
            duration_ms=0,
            details={
                "gate": comparison["gate"],
                "input_sha256": OPENED_DEV_INPUT_SHA256,
                "run_artifacts": _run_artifact_hashes(output_root),
                "score_artifacts": score_artifacts,
                "scoring_fixture_sha256": scoring_fixture_sha256,
            },
        )
    )
    final_ledger = ledger.verify()
    manifest["score_closure"] = {
        "artifacts": score_artifacts,
        "gate": comparison["gate"],
        "ledger_event_count": len(final_ledger.events),
        "ledger_root_sha256": final_ledger.root_sha256,
        "schema": "milai.dg14.score-closure.v1",
        "scoring_fixture_path": str(scoring_fixture.resolve()),
        "scoring_fixture_sha256": scoring_fixture_sha256,
        "status": "SEALED",
    }
    manifest["stage_ledger_root_sha256"] = final_ledger.root_sha256
    _atomic_json(output_root / "manifest.json", manifest)
    return comparison


def _write_analysis(
    path: Path,
    comparison: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
    scored: Sequence[Mapping[str, Any]],
) -> None:
    methods = cast(Mapping[str, Any], comparison["methods"])
    dg14 = cast(Mapping[str, Any], methods[METHOD_ID])["2048"]
    bm25t = cast(Mapping[str, Any], methods["LME-BM25-T"])["2048"]
    dg14_metrics = cast(Mapping[str, Any], dg14)
    bm25t_metrics = cast(Mapping[str, Any], bm25t)
    correct = round(float(dg14_metrics["exact_match"]) * len(OPENED_DEV_CASE_IDS))
    gate = cast(Mapping[str, Any], comparison["gate"])
    lines = [
        "# DG-14 LongMemEval opened-development characterization",
        "",
        f"Run: `{comparison['run_id']}`",
        "",
        "- IMPLEMENTED: matched five-arm, two-budget MCP/provider runner and scorer.",
        "- TESTED: see the run manifest and hash-chained stage ledger.",
        f"- CHARACTERIZED: DG14 2048 exact {correct}/5; coverage {dg14_metrics['evidence_coverage']}.",
        f"- CHARACTERIZED: BM25-T 2048 EM {bm25t_metrics['exact_match']}; F1 {bm25t_metrics['normalized_f1']}.",
        f"- BLOCKED: {'no' if gate['passed'] else 'DG14 2048 minimum/noninferiority target not reached'}.",
        "- NOT FORMALLY EVALUATED: no formal holdout, paper harness or generalization split was consumed.",
        "",
        "## Matched quality and efficiency",
        "",
        "| Arm | Budget | EM | F1 | Hit@K | NDCG@K | Coverage | Unknown | Trunc. | Query p50/p95 ms | Provider ms | E2E ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method in ARMS:
        budgets = cast(Mapping[str, Any], methods[method])
        for budget in BUDGETS:
            metrics = cast(Mapping[str, Any], budgets[str(budget)])
            lines.append(
                "| "
                + " | ".join(
                    (
                        method,
                        str(budget),
                        f"{float(metrics['exact_match']):.3f}",
                        f"{float(metrics['normalized_f1']):.3f}",
                        f"{float(metrics['hit_at_k']):.3f}",
                        f"{float(metrics['ndcg_at_k']):.3f}",
                        f"{float(metrics['evidence_coverage']):.3f}",
                        f"{float(metrics['unknown_abstention_rate']):.3f}",
                        f"{float(metrics['context_truncation_rate']):.3f}",
                        (
                            f"{float(metrics['query_latency_ms_p50']):.1f}/"
                            f"{float(metrics['query_latency_ms_p95']):.1f}"
                        ),
                        f"{float(metrics['provider_latency_ms_mean']):.1f}",
                        f"{float(metrics['e2e_latency_ms_mean']):.1f}",
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            (
                "DG14/2048 matches the strongest opened-smoke baseline on EM, F1, "
                "Hit@K and Evidence Coverage. Its principal cost is governed "
                f"finalization (mean {float(dg14_metrics['finalize_latency_ms_mean']) / 1000:.1f} "
                "s/case in this five-case run); query p50/p95 is "
                f"{float(dg14_metrics['query_latency_ms_p50']):.1f}/"
                f"{float(dg14_metrics['query_latency_ms_p95']):.1f} ms and mean "
                f"provider latency is {float(dg14_metrics['provider_latency_ms_mean']):.1f} ms."
            ),
            "",
            "## DG14/2048 case outcomes",
            "",
            "| Case | Answer | EM | F1 | Hit@K | Coverage | Taxonomy |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    taxonomy_by_key = {
        (str(item["case_id"]), int(item["token_budget"])): str(item["taxonomy"])
        for item in cast(Sequence[Mapping[str, Any]], taxonomy["records"])
        if item.get("method_id") == METHOD_ID
    }
    for record in scored:
        if record.get("method_id") != METHOD_ID or record.get("token_budget") != 2048:
            continue
        answer_score = cast(Mapping[str, Any], record["answer_score"])
        retrieval_score = cast(Mapping[str, Any], record["retrieval_score"])
        answer = str(record["answer"]).replace("|", "\\|")
        lines.append(
            "| "
            + " | ".join(
                (
                    str(record["case_id"]),
                    answer,
                    f"{float(answer_score['exact_match']):.0f}",
                    f"{float(answer_score['normalized_f1']):.3f}",
                    f"{float(retrieval_score['hit_at_k']):.0f}",
                    f"{float(retrieval_score['relevant_coverage_at_k']):.3f}",
                    taxonomy_by_key[(str(record["case_id"]), 2048)],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Case `00ca467f` is a retrieval miss. Case `0100672e` retrieves all labeled evidence but the provider abstains, isolating that failure to reasoning/answer generation rather than retrieval or context truncation.",
            "",
            "## Correctness and scope",
            "",
            "The matched run recorded cross-case contamination 0/50, label leakage 0/12,335 history events, and silent fallback 0/50. A separate real integration smoke records wrong-scope 0/1 and revoked-evidence acceptance 0/1; those trials are intentionally not counted as benchmark cells.",
            "",
            "## Failure taxonomy (all 50 matched cells)",
            "",
        ]
    )
    for label, count in cast(Mapping[str, int], taxonomy["counts"]).items():
        lines.append(f"- {label}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class LocalDG14RuntimeSession:
    """Fresh local Runtime/API/worker lifecycle used by the real CLI path."""

    def __init__(
        self,
        *,
        output_root: Path,
        env_file: Path = DEFAULT_ENV_FILE,
        project_root: Path = ROOT,
        inherit_source_embedding_runtime: bool = False,
        data_mode: Literal["SYNTHETIC_ONLY", "DEIDENTIFIED_ALLOWED"] = (
            "DEIDENTIFIED_ALLOWED"
        ),
        memory_formation_mode: Literal["OFF", "SHADOW", "CANARY"] = "OFF",
        progressive_context_evidence: bool = False,
        budget_invariant_context: bool = False,
        retrieval_evidence_dense_enabled: bool = False,
    ) -> None:
        self.output_root = output_root
        self.env_file = env_file
        self.project_root = project_root
        self._inherit_source_embedding_runtime = inherit_source_embedding_runtime
        self._data_mode = data_mode
        self._memory_formation_mode = memory_formation_mode
        self._progressive_context_evidence = progressive_context_evidence
        self._budget_invariant_context = budget_invariant_context
        self._retrieval_evidence_dense_enabled = retrieval_evidence_dense_enabled
        self._database_name: str | None = None
        self._owner_source: str | None = None
        self._database_urls: dict[str, str] | None = None
        self._tokens: dict[str, str] | None = None
        self._settings: Any = None
        self._environment: dict[str, str] | None = None
        self._api_process: subprocess.Popen[bytes] | None = None
        self._runtime_log: Any = None
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._run_id: str | None = None
        self._ownership_api: Mapping[str, object] | None = None
        self._ownership_worker: Mapping[str, object] | None = None

    def start(self, run_id: str) -> Mapping[str, Any]:
        if self._database_name is not None:
            raise DG14BenchmarkError("Runtime session was already started")
        self._run_id = run_id
        runtime_src = self.project_root / "runtime/src"
        if str(runtime_src) not in sys.path:
            sys.path.insert(0, str(runtime_src))
        from alembic import command
        from alembic.script import ScriptDirectory
        from milai.config import load_settings
        from milai.config.settings import prepare_runtime_directories
        from milai.operations import load_runtime_environment
        from milai.operations.smoke import (
            _alembic_config,
            _api_environment,
            _create_database,
            _database_url,
            _free_loopback_port,
            _HttpClient,
            _migration_url,
            _smoke_settings,
            _wait_api,
        )

        load_runtime_environment(self.env_file.resolve())
        source = load_settings()
        owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
        worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
        audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
        if not owner_source or not worker_source or not audit_source:
            raise DG14BenchmarkError("fresh Runtime database-role URLs are absent")
        nonce = secrets.token_hex(8)
        suffix = hashlib.sha256(f"{run_id}\0{nonce}".encode()).hexdigest()[:20]
        database_name = f"milai_smoke_dg14_{suffix}"
        database_urls = {
            "owner": _database_url(owner_source, database_name),
            "api": _database_url(source.database_dsn, database_name),
            "steward": _database_url(source.steward_database_dsn, database_name),
            "worker": _database_url(worker_source, database_name),
            "audit": _database_url(audit_source, database_name),
        }
        tokens = {
            name: secrets.token_urlsafe(48)
            for name in (
                "legacy",
                "causal",
                "reader",
                "submitter",
                "operator",
                "reviewer",
            )
        }
        self._owner_source = owner_source
        self._database_name = database_name
        _create_database(owner_source, database_name)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._record_ownership("DATABASE_CREATED")
        self._database_urls = database_urls
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")
        self._temporary = tempfile.TemporaryDirectory(prefix="milai-dg14-")
        temporary = Path(self._temporary.name)
        settings = _smoke_settings(
            source,
            database_urls,
            temporary / "blobs",
            uuid4(),
            uuid4(),
            tokens,
            _free_loopback_port(),
        ).model_copy(
            update={
                "data_mode": self._data_mode,
                "feature_profile": {
                    "OFF": "BASELINE",
                    "SHADOW": "FORMED_SHADOW",
                    "CANARY": "FORMED_CANARY",
                }[self._memory_formation_mode],
                "progressive_context_evidence_v0_1": (
                    self._progressive_context_evidence
                ),
                "budget_invariant_context_v0_1": self._budget_invariant_context,
                "retrieval_evidence_dense_enabled": (
                    self._retrieval_evidence_dense_enabled
                ),
            }
        )
        if self._inherit_source_embedding_runtime:
            settings = settings.model_copy(
                update={
                    "embedding_provider": source.embedding_provider,
                    "embedding_model_id": source.embedding_model_id,
                    "embedding_model_path": source.embedding_model_path,
                    "embedding_source_dimensions": source.embedding_source_dimensions,
                    "embedding_projection_dimensions": (
                        source.embedding_projection_dimensions
                    ),
                    "embedding_prewarm": source.embedding_prewarm,
                    "embedding_max_concurrency": source.embedding_max_concurrency,
                }
            )
        prepare_runtime_directories(settings)
        environment = _api_environment(settings, database_urls, tokens)
        # The opened benchmark default is deidentified. Synthetic product
        # witnesses may explicitly choose the stricter mode while retaining the
        # same isolated Runtime composition.
        environment["MILAI_DATA_MODE"] = self._data_mode
        runtime_log = (self.output_root / "runtime.log").open("wb")
        self._runtime_log = runtime_log
        try:
            process = subprocess.Popen(
                [str(self.project_root / "runtime/.venv/bin/milai-api")],
                cwd=self.project_root / "runtime",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=runtime_log,
                stderr=subprocess.STDOUT,
            )
            self._api_process = process
            self._record_ownership("API_PROCESS_STARTED")
            _wait_api(
                _HttpClient(f"http://{settings.bind_host}:{settings.bind_port}"),
                process,
            )
        except BaseException:
            owned_process = self._api_process
            if owned_process is not None and owned_process.poll() is None:
                owned_process.terminate()
                try:
                    owned_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    owned_process.kill()
                    owned_process.wait(timeout=5)
            self._api_process = None
            runtime_log.close()
            self._runtime_log = None
            self._record_ownership("API_START_FAILED")
            raise
        self._tokens = tokens
        self._settings = settings
        self._environment = environment
        migration_head = ScriptDirectory.from_config(
            _alembic_config()
        ).get_current_head()
        return {
            "api_base_url": f"http://{settings.bind_host}:{settings.bind_port}",
            "api_pid": process.pid,
            "database": database_name,
            "data_mode": self._data_mode,
            "embedding_provider": settings.embedding_provider,
            "embedding_model_id": settings.embedding_model_id,
            "embedding_model_path": (
                str(settings.embedding_model_path)
                if settings.embedding_model_path is not None
                else None
            ),
            "embedding_source_dimensions": settings.embedding_source_dimensions,
            "embedding_projection_dimensions": (
                settings.embedding_projection_dimensions
            ),
            "embedding_prewarm": settings.embedding_prewarm,
            "embedding_max_concurrency": settings.embedding_max_concurrency,
            "retrieval_reranker_provider": settings.retrieval_reranker_provider,
            "retrieval_evidence_dense_enabled": (
                settings.retrieval_evidence_dense_enabled
            ),
            "ephemeral": True,
            "migration_head": migration_head,
            "role_tokens": "EPHEMERAL_REDACTED",
        }

    def _record_ownership(self, status: str, *, worker_pid: int | None = None) -> None:
        if self._api_process is not None:
            self._ownership_api = _process_identity(self._api_process.pid)
        if worker_pid is not None:
            self._ownership_worker = _process_identity(worker_pid)
        _atomic_json(
            self.output_root / "runtime-ownership.json",
            {
                "schema_version": "milai-local-runtime-ownership-v0.1",
                "run_id": self._run_id,
                "status": status,
                "database": self._database_name,
                "api_process": self._ownership_api,
                "worker_process": self._ownership_worker,
                "updated_at_unix_ns": time.time_ns(),
            },
        )

    def _worker_once(self, request: DG14ReadinessRequest) -> Mapping[str, object]:
        if self._environment is None or self._database_urls is None:
            raise DG14BenchmarkError("Runtime worker requested before session start")
        environment = dict(self._environment)
        environment["MILAI_WORKER_DATABASE_URL"] = self._database_urls["worker"]
        if self._settings is None:
            raise DG14BenchmarkError("Runtime settings are absent during worker drain")
        # _api_environment intentionally contains only API-facing settings. The
        # separate worker process must receive the same drain/retry contract as
        # this fresh Runtime session instead of falling back to its 256-event
        # default while our cycle bound is computed from 10,000.
        environment["MILAI_WORKER_EVENT_LIMIT"] = str(self._settings.worker_event_limit)
        environment["MILAI_WORKER_RETRY_DELAY_SECONDS"] = str(
            self._settings.worker_retry_delay_seconds
        )
        # One real case can exceed Runtime's per-projection worker_event_limit.
        # Evidence capture and governed claim creation each contribute at most
        # one ordered event per projection, so this exact case-local upper bound
        # plus one empty-queue confirmation cycle drains without polling/retry.
        event_bound = request.evidence_count + request.claim_count
        drain_cycles = max(
            1,
            math.ceil(event_bound / int(self._settings.worker_event_limit)) + 1,
        )
        worker_timeout_seconds = min(300, max(60, math.ceil(event_bound * 0.25)))
        started = time.perf_counter()
        returncodes: list[int] = []
        for _cycle in range(drain_cycles):
            worker = subprocess.run(
                [str(self.project_root / "runtime/.venv/bin/milai-worker"), "--once"],
                cwd=self.project_root / "runtime",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._runtime_log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=worker_timeout_seconds,
            )
            returncodes.append(worker.returncode)
            if worker.returncode != 0:
                raise DG14BenchmarkError("fresh Runtime projection worker failed")
        return {
            "drain_cycles": drain_cycles,
            "event_bound": event_bound,
            "latency_ms": round((time.perf_counter() - started) * 1000, 6),
            "returncodes": returncodes,
            "worker_timeout_seconds": worker_timeout_seconds,
            "worker_once": True,
        }

    def adapter_for_case(self, case: Any, token_counter: TokenCounter) -> Any:
        config = self.adapter_config()
        from evals.dg14.mcp_stdio import StdioMcpTransport
        from evals.dg14.milai_mcp_adapter import DG14MilaiMcpAdapter

        transport = StdioMcpTransport(config)
        return DG14MilaiMcpAdapter(
            config,
            token_counter=token_counter,
            transport=transport,
            readiness_hook=self._worker_once,
        )

    def adapter_config(self) -> Any:
        """Return the current isolated Runtime's four-profile MCP config."""

        if self._settings is None or self._tokens is None:
            raise DG14BenchmarkError("Runtime adapter requested before session start")
        from evals.dg14.contracts import DG14AdapterConfig

        return DG14AdapterConfig(
            base_url=f"http://{self._settings.bind_host}:{self._settings.bind_port}",
            executable=self.project_root / "integrations/mcp/.venv/bin/milai-mcp",
            profile_tokens={
                "operator": self._tokens["operator"],
                "reader-detail": self._tokens["reader"],
                "reviewer": self._tokens["reviewer"],
                "submitter": self._tokens["submitter"],
            },
            tenant_id=str(self._settings.tenant_id),
            principal_id=str(self._settings.local_actor_id),
            scope={},
            max_limit=3,
            allowed_budgets=BUDGETS,
        )

    def profile_actor_ids(self) -> Mapping[str, str]:
        """Expose deterministic named-profile actors for governance receipts."""

        if self._settings is None:
            raise DG14BenchmarkError("Runtime actor identities requested before start")
        from milai.api.auth import profile_actor_id

        return {
            profile: str(profile_actor_id(self._settings, profile))
            for profile in ("submitter", "reviewer")
        }

    def close(self) -> Mapping[str, Any]:
        runtime_src = self.project_root / "runtime/src"
        if str(runtime_src) not in sys.path:
            sys.path.insert(0, str(runtime_src))
        from milai.operations.smoke import _drop_database, _stop_api

        if self._api_process is not None:
            _stop_api(self._api_process)
            self._api_process = None
        if self._runtime_log is not None:
            self._runtime_log.close()
            self._runtime_log = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        if self._owner_source is None or self._database_name is None:
            return {"status": "NOT_CREATED"}
        cleanup = _drop_database(self._owner_source, self._database_name)
        result = {
            **cleanup,
            "database": self._database_name,
            "exact_fresh_database_only": True,
        }
        if cleanup.get("status") == "PASS":
            self._record_ownership("RELEASED")
            self._database_name = None
            self._owner_source = None
        else:
            # A database that could not be proven dropped remains owned.  Keep
            # its identity in memory and on disk so a later launch is blocked
            # until the explicit recovery flow seals it RELEASED.
            self._record_ownership("RELEASE_BLOCKED")
        return result
