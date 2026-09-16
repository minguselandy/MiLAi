"""Local controlled LongMemEval context producers for protocol v3."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from evals.paper.adapters import (
    CustomLexicalTop1Adapter,
    FullHistoryAdapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
    OracleAdapter,
)
from evals.paper.contracts import (
    ContextRecord,
    MemoryAdapter,
    MemoryEvent,
    write_context_archive,
)
from evals.paper.datasets.longmemeval import labels_from_dataset, load_inputs
from evals.paper.parallelism import STATELESS_CONTEXT_LANE

from .freeze import (
    ANSWER_TOKENIZER_SHA256,
    require_formal_holdout_authorized,
    require_paper_v3_ready,
    sha256_file,
)
from .plan import build_lme_plan
from .runner import consume_holdout_labels

LOCAL_METHODS = (
    "CTRL-NONE",
    "CTRL-FULL",
    "CTRL-TRUNC-FULL",
    "CTRL-CUSTOM-LEX1",
    "LME-BM25-S",
    "LME-BM25-T",
    "LME-ORACLE",
)
TRACKS = {
    "CTRL-NONE": "CONTROLLED",
    "CTRL-FULL": "LONG_CONTEXT_CHARACTERIZATION",
    "CTRL-TRUNC-FULL": "LONG_CONTEXT_CHARACTERIZATION",
    "CTRL-CUSTOM-LEX1": "CONTROLLED",
    "LME-BM25-S": "CONTROLLED",
    "LME-BM25-T": "CONTROLLED",
    "LME-ORACLE": "UPPER_BOUND",
}


class ControlledContextError(RuntimeError):
    pass


def _adapter(method_id: str, token_counter: Callable[[str], int]) -> MemoryAdapter:
    if method_id == "CTRL-NONE":
        return NoMemoryAdapter(token_counter=token_counter)
    if method_id == "CTRL-FULL":
        return FullHistoryAdapter(truncate=False, token_counter=token_counter)
    if method_id == "CTRL-TRUNC-FULL":
        return FullHistoryAdapter(truncate=True, token_counter=token_counter)
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
    if method_id == "LME-ORACLE":
        return OracleAdapter(token_counter=token_counter)
    raise ControlledContextError(f"not a local controlled method: {method_id}")


def _events(case: Any) -> tuple[MemoryEvent, ...]:
    return tuple(
        MemoryEvent(
            event_id=f"{session.session_id}:{turn_index}",
            content=turn.content,
            observed_at=session.observed_at,
            actor=turn.role,
            scope="dg12-paper-public-benchmark",
            metadata={"session_id": session.session_id, "turn_index": turn_index},
        )
        for session in case.sessions
        for turn_index, turn in enumerate(session.turns)
    )


def prepare_contexts(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    methods: tuple[str, ...],
    token_budget: int,
    tokenizer_path: Path,
    schedule_path: Path,
    freeze_manifest: Path,
    label_dataset: Path | None = None,
    workers: int = STATELESS_CONTEXT_LANE.default_workers,
    execution_authorization: Path | None = None,
) -> dict[str, Any]:
    freeze = require_paper_v3_ready(freeze_manifest)
    require_formal_holdout_authorized(
        input_path=input_path,
        manifest_path=freeze_manifest,
        authorization_path=execution_authorization,
    )
    STATELESS_CONTEXT_LANE.validate(
        workers,
        frozen_ceiling=int(freeze["execution"]["stateless_context_workers_max"]),
    )
    if (
        not methods
        or len(set(methods)) != len(methods)
        or any(method not in LOCAL_METHODS for method in methods)
    ):
        raise ControlledContextError("local method selection is invalid")
    if ("LME-ORACLE" in methods) != (label_dataset is not None):
        raise ControlledContextError(
            "oracle labels must be supplied exactly when LME-ORACLE is requested"
        )
    from tokenizers import Tokenizer

    if sha256_file(tokenizer_path) != ANSWER_TOKENIZER_SHA256:
        raise ControlledContextError("answer tokenizer drifted from the freeze")
    partition, cases = load_inputs(input_path)
    case_by_id = {case.source_id: case for case in cases}
    labels: Mapping[str, Mapping[str, Any]] | None = None
    if label_dataset is not None:
        consume_holdout_labels(
            run_id=run_id,
            input_path=input_path,
            label_dataset=label_dataset,
            expected_label_sha256=str(freeze["execution"]["label_dataset_sha256"]),
            first_purpose="ORACLE_UPPER_BOUND_CONTEXT",
        )
        labels = labels_from_dataset(label_dataset, tuple(case_by_id))
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    token_counter = lambda text: len(tokenizer.encode(text).ids)
    plan = build_lme_plan(input_path=input_path, schedule_path=schedule_path)
    selected_cells = [
        cell for cell in plan["cells"] if str(cell["method_id"]) in methods
    ]
    records: list[ContextRecord | None] = [None] * len(selected_cells)

    def prepare(index: int, cell: Mapping[str, Any]) -> tuple[int, ContextRecord]:
        method_id = str(cell["method_id"])
        case = case_by_id[str(cell["case_id"])]
        adapter = _adapter(method_id, token_counter)
        adapter.reset(run_id, case.source_id)
        if isinstance(adapter, OracleAdapter):
            assert labels is not None
            raw_ids = labels[case.source_id].get("answer_session_ids")
            if not isinstance(raw_ids, list):
                raise ControlledContextError("oracle evidence labels are invalid")
            adapter.set_oracle_source_ids(str(item) for item in raw_ids)
        for event in _events(case):
            adapter.ingest(event)
        adapter.finalize()
        try:
            result = adapter.query(
                case.question,
                case.question_at,
                token_budget,
                "ORACLE_UPPER_BOUND"
                if method_id == "LME-ORACLE"
                else TRACKS[method_id],
            )
            record = ContextRecord(
                case_id=case.source_id,
                method_id=method_id,
                track=TRACKS[method_id],
                context=result.context,
                source_ids=result.source_ids,
                trace=result.trace,
                declared_tokens=result.declared_tokens,
                latency_ms=result.latency_ms,
                usage={
                    **dict(result.usage),
                    "adapter_storage_bytes": adapter.stats().storage_bytes,
                },
            )
        except ValueError as exc:
            if method_id != "CTRL-FULL" or "exceeds" not in str(exc):
                raise
            record = ContextRecord(
                case_id=case.source_id,
                method_id=method_id,
                track=TRACKS[method_id],
                context="",
                source_ids=(),
                trace=(),
                declared_tokens=0,
                latency_ms=0.0,
                usage={"failure": "CONTEXT_LIMIT_EXCEEDED"},
                terminal_status="CAPABILITY_UNSUPPORTED",
            )
        finally:
            adapter.close()
        return index, record

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="paper-controlled"
    ) as pool:
        futures = {
            pool.submit(prepare, index, cell): index
            for index, cell in enumerate(selected_cells)
        }
        for future in as_completed(futures):
            index, record = future.result()
            records[index] = record

    expected = len(cases) * len(methods)
    if len(records) != expected or any(record is None for record in records):
        raise ControlledContextError("local context denominator is incomplete")
    finalized = tuple(record for record in records if record is not None)
    return write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=finalized,
        metadata={
            "labels_accessed": "ORACLE_UPPER_BOUND_ONLY" if labels else False,
            "maximum_concurrent_requests": workers,
            "paper_labels_opened": labels is not None,
            "parallelism_lane": STATELESS_CONTEXT_LANE.name,
            "schedule_namespace": plan["schedule_namespace"],
            "worker_count": workers,
        },
    )
