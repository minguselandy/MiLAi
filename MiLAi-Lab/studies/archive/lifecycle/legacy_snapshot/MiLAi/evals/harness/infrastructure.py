from __future__ import annotations

import json
import os
import random
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from queue import Queue
from typing import Any, Literal

from evals.harness.contracts import WorkloadHistory, WorkloadQuestion
from evals.harness.lease import EvaluationRuntimeLease


@dataclass(frozen=True, slots=True)
class OneBuildManyQuestionPlan:
    workload: WorkloadHistory
    questions: tuple[WorkloadQuestion, ...]

    @classmethod
    def create(
        cls,
        workload: WorkloadHistory,
        questions: Sequence[WorkloadQuestion],
    ) -> OneBuildManyQuestionPlan:
        values = tuple(questions)
        if any(question.workload_id != workload.workload_id for question in values):
            raise ValueError("all questions must bind to the planned workload")
        return cls(workload=workload, questions=values)


@dataclass(frozen=True, slots=True)
class TemporaryResourceSpec:
    lease_id: str
    database_name: str
    blob_root: Path
    temporary_root: Path

    def __post_init__(self) -> None:
        root = self.temporary_root.resolve()
        blob = self.blob_root.resolve()
        if not self.database_name.startswith("milai_eval_"):
            raise ValueError("evaluation database must use the temporary prefix")
        if blob == root or root not in blob.parents:
            raise ValueError(
                "evaluation blob root must be inside its exact temporary root"
            )


class EvaluationResourceProvisioner:
    """Coordinates exact temporary resources through injected product operations."""

    def __init__(
        self,
        create: Callable[[TemporaryResourceSpec], EvaluationRuntimeLease],
        destroy: Callable[[TemporaryResourceSpec], None],
    ) -> None:
        self._create = create
        self._destroy = destroy

    @contextmanager
    def provision(
        self, spec: TemporaryResourceSpec
    ) -> Iterator[EvaluationRuntimeLease]:
        lease = self._create(spec)
        try:
            yield lease
        finally:
            lease.close()
            self._destroy(spec)


class BoundedLeasePool:
    def __init__(
        self, leases: Sequence[EvaluationRuntimeLease], *, capacity: int
    ) -> None:
        if capacity < 1 or capacity > len(leases):
            raise ValueError("lease pool capacity must fit the supplied leases")
        self._queue: Queue[EvaluationRuntimeLease] = Queue(maxsize=capacity)
        self._leases = tuple(leases[:capacity])
        for lease in self._leases:
            self._queue.put_nowait(lease)

    @contextmanager
    def acquire(self) -> Iterator[EvaluationRuntimeLease]:
        lease = self._queue.get()
        try:
            yield lease
        finally:
            self._queue.put_nowait(lease)

    def close(self) -> None:
        for lease in self._leases:
            lease.close()


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    case_id: str
    method_order: tuple[str, ...]


def seeded_counterbalanced_schedule(
    case_ids: Sequence[str], method_ids: Sequence[str], *, seed: int
) -> tuple[ScheduleRow, ...]:
    methods = list(method_ids)
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("schedule methods must be non-empty and unique")
    random.Random(seed).shuffle(methods)
    return tuple(
        ScheduleRow(
            case_id=case_id,
            method_order=tuple(methods[offset:] + methods[:offset]),
        )
        for offset, case_id in enumerate(case_ids)
        for offset in [offset % len(methods)]
    )


CacheClassification = Literal["PUBLIC", "DEIDENTIFIED"]


class ArtifactCache:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        key: str,
        value: dict[str, Any],
        *,
        classification: CacheClassification,
    ) -> Path:
        encoded = json.dumps(
            {
                "classification": classification,
                "value": value,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        path = self.root / f"{key}.json"
        temporary = self.root / f".{key}.{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        return dict(json.loads(path.read_text(encoding="utf-8"))["value"])


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    key: str
    status: Literal["PASS", "FAIL"]
    result_path: str | None
    failure_code: str | None


class CheckpointLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: CheckpointRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def records(self) -> tuple[CheckpointRecord, ...]:
        if not self.path.exists():
            return ()
        return tuple(
            CheckpointRecord(**json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line
        )

    def terminal_accounting(self, expected_keys: Sequence[str]) -> dict[str, Any]:
        latest = {record.key: record for record in self.records()}
        expected = tuple(expected_keys)
        return {
            "expected": len(expected),
            "passed": sum(
                latest.get(key) is not None and latest[key].status == "PASS"
                for key in expected
            ),
            "failed": sum(
                latest.get(key) is not None and latest[key].status == "FAIL"
                for key in expected
            ),
            "missing": [key for key in expected if key not in latest],
        }
