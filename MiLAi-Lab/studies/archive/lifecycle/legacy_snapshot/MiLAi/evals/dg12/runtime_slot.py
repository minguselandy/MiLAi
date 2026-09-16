"""Unified DG12 RuntimeSlot contract and label-free loader normalization."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from evals.paper.contracts import ContextRecord
from evals.paper.datasets.extended import ExtendedCase, load_extended_inputs
from evals.paper.datasets.memora import (
    MemoraCase,
    MemoraCohort,
)
from evals.paper.datasets.memora import (
    load_inputs as load_memora_inputs,
)


class RuntimeSlotError(RuntimeError):
    pass


class LoaderKind(StrEnum):
    CUPID = "CUPID"
    HORIZON = "HORIZON"
    BEAM = "BEAM"
    MEMORA = "MEMORA"


class SlotState(StrEnum):
    NEW = "NEW"
    MIGRATED = "MIGRATED"
    READY_AND_WARM = "READY_AND_WARM"
    EMPTY = "EMPTY"
    LOADING_COHORT = "LOADING_COHORT"
    INDEXED = "INDEXED"
    QUERYING = "QUERYING"
    DRAINING = "DRAINING"
    RESETTING = "RESETTING"
    QUARANTINED = "QUARANTINED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class RuntimeTurn:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class RuntimeSession:
    session_id: str
    observed_at: str
    turns: tuple[RuntimeTurn, ...]


@dataclass(frozen=True, slots=True)
class RuntimeHistory:
    history_id: str
    loader_kind: LoaderKind
    source_history_id: str
    sessions: tuple[RuntimeSession, ...]


@dataclass(frozen=True, slots=True)
class RuntimeQuestion:
    case_id: str
    history_id: str
    question: str
    question_at: str
    category: str


@dataclass(frozen=True, slots=True)
class SlotWork:
    history: RuntimeHistory
    questions: tuple[RuntimeQuestion, ...]


@runtime_checkable
class RuntimeSlot(Protocol):
    """Execution contract shared by reference, fast, and online-latency slots."""

    @property
    def slot_id(self) -> str: ...

    @property
    def state(self) -> SlotState: ...

    def start(self) -> None: ...

    def load(self, history: RuntimeHistory) -> None: ...

    def query(self, question: RuntimeQuestion) -> ContextRecord: ...

    def stats(self, *, question_count: int) -> dict[str, Any]: ...

    def drain(self) -> None: ...

    def reset(self) -> None: ...

    def quarantine(self, reason_code: str) -> None: ...

    def close(self) -> None: ...


_ALLOWED_TRANSITIONS: dict[SlotState, frozenset[SlotState]] = {
    SlotState.NEW: frozenset(
        {SlotState.MIGRATED, SlotState.QUARANTINED, SlotState.CLOSED}
    ),
    SlotState.MIGRATED: frozenset({SlotState.READY_AND_WARM, SlotState.QUARANTINED}),
    SlotState.READY_AND_WARM: frozenset({SlotState.EMPTY, SlotState.QUARANTINED}),
    SlotState.EMPTY: frozenset(
        {SlotState.LOADING_COHORT, SlotState.CLOSED, SlotState.QUARANTINED}
    ),
    SlotState.LOADING_COHORT: frozenset({SlotState.INDEXED, SlotState.QUARANTINED}),
    SlotState.INDEXED: frozenset(
        {SlotState.QUERYING, SlotState.DRAINING, SlotState.QUARANTINED}
    ),
    SlotState.QUERYING: frozenset(
        {SlotState.INDEXED, SlotState.DRAINING, SlotState.QUARANTINED}
    ),
    SlotState.DRAINING: frozenset({SlotState.RESETTING, SlotState.QUARANTINED}),
    SlotState.RESETTING: frozenset({SlotState.EMPTY, SlotState.QUARANTINED}),
    SlotState.QUARANTINED: frozenset({SlotState.CLOSED}),
    SlotState.CLOSED: frozenset(),
}


@dataclass(slots=True)
class SlotLifecycle:
    state: SlotState = SlotState.NEW
    reason_code: str | None = None

    def transition(self, target: SlotState) -> None:
        if target not in _ALLOWED_TRANSITIONS[self.state]:
            raise RuntimeSlotError(
                f"illegal RuntimeSlot transition: {self.state}->{target}"
            )
        self.state = target

    def quarantine(self, reason_code: str) -> None:
        if not reason_code or self.state in {SlotState.QUARANTINED, SlotState.CLOSED}:
            raise RuntimeSlotError("RuntimeSlot quarantine request is invalid")
        self.reason_code = reason_code
        self.transition(SlotState.QUARANTINED)


class CohortRuntimeSlot:
    """Adapter from the DG11 cohort runtime to the unified DG12 Slot contract.

    The legacy backend still creates infrastructure while loading a history.  The
    adapter records that combined boundary explicitly; BHE02 replaces it with a
    genuinely persistent start/reset implementation without changing callers.
    """

    def __init__(self, *, slot_id: str, env_file: Path, tokenizer_path: Path) -> None:
        if not slot_id:
            raise RuntimeSlotError("RuntimeSlot ID is empty")
        self._slot_id = slot_id
        self._env_file = env_file
        self._tokenizer_path = tokenizer_path
        self._lifecycle = SlotLifecycle()
        self._start_requested = False
        self._history: RuntimeHistory | None = None
        self._backend: Any = None
        self._tokenizer: Any = None

    @property
    def slot_id(self) -> str:
        return self._slot_id

    @property
    def state(self) -> SlotState:
        return self._lifecycle.state

    def start(self) -> None:
        if self.state not in {SlotState.NEW, SlotState.EMPTY} or self._start_requested:
            raise RuntimeSlotError("RuntimeSlot start is invalid in the current state")
        self._start_requested = True

    def load(self, history: RuntimeHistory) -> None:
        if not self._start_requested or self.state not in {
            SlotState.NEW,
            SlotState.EMPTY,
        }:
            raise RuntimeSlotError("RuntimeSlot load requires a fresh start request")
        from tokenizers import Tokenizer

        from evals.paper.datasets.memora import MemoraCohort, MemoraSession, MemoraTurn
        from evals.paper.runners.memora_milai_contexts import _CohortRuntime

        cohort = MemoraCohort(
            cohort_id=history.history_id,
            period=history.loader_kind.value.casefold(),
            persona="public-deidentified",
            sessions=tuple(
                MemoraSession(
                    observed_at=session.observed_at,
                    session_id=session.session_id,
                    turns=tuple(
                        MemoraTurn(actor=turn.role, content=turn.content)
                        for turn in session.turns
                    ),
                )
                for session in history.sessions
            ),
        )
        backend = _CohortRuntime(cohort=cohort, env_file=self._env_file)
        try:
            backend.__enter__()
            self._tokenizer = Tokenizer.from_file(str(self._tokenizer_path))
        except Exception:
            backend.close()
            self._lifecycle.quarantine("COMBINED_START_LOAD_FAILED")
            raise
        self._backend = backend
        self._history = history
        self._start_requested = False
        if self.state is SlotState.NEW:
            self._lifecycle.transition(SlotState.MIGRATED)
            self._lifecycle.transition(SlotState.READY_AND_WARM)
            self._lifecycle.transition(SlotState.EMPTY)
        self._lifecycle.transition(SlotState.LOADING_COHORT)
        self._lifecycle.transition(SlotState.INDEXED)

    def query(self, question: RuntimeQuestion) -> ContextRecord:
        if (
            self.state is not SlotState.INDEXED
            or self._backend is None
            or self._history is None
            or self._tokenizer is None
            or question.history_id != self._history.history_id
        ):
            raise RuntimeSlotError(
                "RuntimeSlot query is not bound to the indexed history"
            )
        from evals.paper.datasets.memora import MemoraCase

        self._lifecycle.transition(SlotState.QUERYING)
        try:
            record = self._backend.query(
                MemoraCase(
                    case_id=question.case_id,
                    cohort_id=question.history_id,
                    question=question.question,
                    question_at=question.question_at,
                    source_question_id=question.case_id,
                    task=question.category,
                ),
                self._tokenizer,
            )
        except Exception:
            self.quarantine("QUERY_FAILED")
            raise
        self._lifecycle.transition(SlotState.INDEXED)
        return record

    def stats(self, *, question_count: int) -> dict[str, Any]:
        if self._backend is None or self.state not in {
            SlotState.INDEXED,
            SlotState.DRAINING,
        }:
            raise RuntimeSlotError("RuntimeSlot statistics are unavailable")
        return {
            **self._backend.stats(question_count=question_count),
            "combined_start_load": True,
            "persistent_infrastructure": False,
            "slot_id": self.slot_id,
            "slot_state": self.state.value,
        }

    def drain(self) -> None:
        if self.state is not SlotState.INDEXED:
            raise RuntimeSlotError("RuntimeSlot drain requires INDEXED")
        self._lifecycle.transition(SlotState.DRAINING)

    def reset(self) -> None:
        if self.state is SlotState.INDEXED:
            self.drain()
        if self.state is not SlotState.DRAINING or self._backend is None:
            raise RuntimeSlotError("RuntimeSlot reset requires a drained backend")
        self._lifecycle.transition(SlotState.RESETTING)
        try:
            self._backend.close()
        except Exception:
            self._lifecycle.quarantine("REFERENCE_CLEANUP_FAILED")
            raise
        self._backend = None
        self._history = None
        self._tokenizer = None
        self._lifecycle.transition(SlotState.EMPTY)

    def quarantine(self, reason_code: str) -> None:
        if self._backend is not None:
            try:
                self._backend.close()
            finally:
                self._backend = None
                self._history = None
                self._tokenizer = None
        self._lifecycle.quarantine(reason_code)

    def close(self) -> None:
        if self.state is SlotState.CLOSED:
            return
        if self.state is SlotState.INDEXED or self.state is SlotState.DRAINING:
            self.reset()
        elif self._backend is not None:
            self._backend.close()
            self._backend = None
        if self.state is SlotState.QUARANTINED or self.state in {
            SlotState.NEW,
            SlotState.EMPTY,
        }:
            self._lifecycle.transition(SlotState.CLOSED)
        else:
            raise RuntimeSlotError("RuntimeSlot close is invalid in the current state")


def _canonical_history(sessions: tuple[RuntimeSession, ...]) -> bytes:
    return json.dumps(
        [
            {
                "observed_at": session.observed_at,
                "session_id": session.session_id,
                "turns": [
                    {"content": turn.content, "role": turn.role}
                    for turn in session.turns
                ],
            }
            for session in sessions
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _history_id(loader_kind: LoaderKind, sessions: tuple[RuntimeSession, ...]) -> str:
    return (
        f"{loader_kind.value.casefold()}-history-"
        + hashlib.sha256(_canonical_history(sessions)).hexdigest()[:24]
    )


def bounded_representative_work(work: SlotWork) -> SlotWork:
    """Create a one-session/one-question lifecycle smoke without scorer labels."""

    if not work.history.sessions or not work.questions:
        raise RuntimeSlotError("representative Slot smoke requires history and question")
    sessions = work.history.sessions[:1]
    history_id = _history_id(work.history.loader_kind, sessions)
    history = RuntimeHistory(
        history_id=history_id,
        loader_kind=work.history.loader_kind,
        source_history_id=work.history.source_history_id + ":bounded-smoke",
        sessions=sessions,
    )
    source_question = work.questions[0]
    question = RuntimeQuestion(
        case_id=source_question.case_id,
        history_id=history_id,
        question=source_question.question,
        question_at=source_question.question_at,
        category=source_question.category,
    )
    return SlotWork(history=history, questions=(question,))


def _extended_work(
    partition: str, cases: tuple[ExtendedCase, ...]
) -> tuple[SlotWork, ...]:
    if partition.startswith("CUPID-"):
        loader_kind = LoaderKind.CUPID
    elif partition.startswith("HORIZON-"):
        loader_kind = LoaderKind.HORIZON
    elif partition.startswith("BEAM-"):
        loader_kind = LoaderKind.BEAM
    else:
        raise RuntimeSlotError("extended loader partition is unsupported")
    histories: dict[str, RuntimeHistory] = {}
    questions: dict[str, list[RuntimeQuestion]] = defaultdict(list)
    for case in cases:
        sessions = tuple(
            RuntimeSession(
                session_id=session.session_id,
                observed_at=session.observed_at,
                turns=tuple(
                    RuntimeTurn(role=turn.role, content=turn.content)
                    for turn in session.turns
                ),
            )
            for session in case.sessions
        )
        history_id = _history_id(loader_kind, sessions)
        source_history_id = ",".join(session.session_id for session in sessions)
        candidate = RuntimeHistory(
            history_id=history_id,
            loader_kind=loader_kind,
            source_history_id=source_history_id,
            sessions=sessions,
        )
        existing = histories.setdefault(history_id, candidate)
        if existing != candidate:
            raise RuntimeSlotError("history digest collision or content drift")
        questions[history_id].append(
            RuntimeQuestion(
                case_id=case.case_id,
                history_id=history_id,
                question=case.question,
                question_at=case.question_at,
                category=case.category,
            )
        )
    return tuple(
        SlotWork(history=history, questions=tuple(questions[history.history_id]))
        for history in histories.values()
    )


def _memora_history(cohort: MemoraCohort) -> RuntimeHistory:
    sessions = tuple(
        RuntimeSession(
            session_id=session.session_id,
            observed_at=session.observed_at,
            turns=tuple(
                RuntimeTurn(role=turn.actor, content=turn.content)
                for turn in session.turns
            ),
        )
        for session in cohort.sessions
    )
    return RuntimeHistory(
        history_id=_history_id(LoaderKind.MEMORA, sessions),
        loader_kind=LoaderKind.MEMORA,
        source_history_id=cohort.cohort_id,
        sessions=sessions,
    )


def _memora_question(case: MemoraCase, history_id: str) -> RuntimeQuestion:
    return RuntimeQuestion(
        case_id=case.case_id,
        history_id=history_id,
        question=case.question,
        question_at=case.question_at,
        category=case.task,
    )


def _memora_work(
    cohorts: tuple[MemoraCohort, ...], cases: tuple[MemoraCase, ...]
) -> tuple[SlotWork, ...]:
    cases_by_cohort: dict[str, list[MemoraCase]] = defaultdict(list)
    for case in cases:
        cases_by_cohort[case.cohort_id].append(case)
    work: list[SlotWork] = []
    for cohort in cohorts:
        history = _memora_history(cohort)
        cohort_cases = cases_by_cohort.pop(cohort.cohort_id, [])
        if not cohort_cases:
            raise RuntimeSlotError("Memora cohort has no questions")
        work.append(
            SlotWork(
                history=history,
                questions=tuple(
                    _memora_question(case, history.history_id) for case in cohort_cases
                ),
            )
        )
    if cases_by_cohort:
        raise RuntimeSlotError("Memora question references an unknown cohort")
    return tuple(work)


def load_slot_work(path: Path) -> tuple[str, tuple[SlotWork, ...]]:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeSlotError("RuntimeSlot input archive is invalid") from exc
    schema = envelope.get("schema") if isinstance(envelope, dict) else None
    if schema == "milai.dg11.paper-memora-inputs.v1":
        cohorts, cases = load_memora_inputs(path)
        return "MEMORA", _memora_work(cohorts, cases)
    partition, cases = load_extended_inputs(path)
    return partition, _extended_work(partition, cases)
