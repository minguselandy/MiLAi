"""Read the exact frozen DG-12 schedule; never regenerate it at execution time."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ScheduleError(RuntimeError):
    pass


EXPECTED_NAMESPACE = "milai-dg12-paper-v2"
EXPECTED_MATRICES = {
    "LME_CONTROLLED": (
        "CTRL-NONE",
        "CTRL-FULL",
        "CTRL-TRUNC-FULL",
        "CTRL-CUSTOM-LEX1",
        "LME-BM25-S",
        "LME-BM25-T",
        "LME-DENSE",
        "DG10-FROZEN",
        "DG11-FULL",
        "DG12-BATCH",
        "LME-ORACLE",
    ),
    "NATIVE_SHARED_CONTEXT": (
        "MEM0-OSS",
        "HINDSIGHT-OSS",
        "GRAPHITI-OSS",
        "REME-OSS",
        "OPENVIKING-URI",
        "OPENVIKING-FIND",
        "OPENVIKING-CONTEXT",
    ),
}


@dataclass(frozen=True)
class FrozenSchedule:
    path: Path
    namespace: str
    matrices: dict[str, tuple[tuple[str, ...], ...]]

    @classmethod
    def load(cls, path: Path) -> FrozenSchedule:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleError(f"invalid frozen schedule: {path}") from exc
        if not isinstance(payload, dict):
            raise ScheduleError("frozen schedule must be an object")
        generator = payload.get("generator")
        matrices = payload.get("matrices")
        if (
            payload.get("schema") != "milai.dg12.seeded-latin-schedule.v2"
            or payload.get("status") != "FROZEN"
            or not isinstance(generator, dict)
            or generator.get("namespace") != EXPECTED_NAMESPACE
            or not isinstance(matrices, dict)
        ):
            raise ScheduleError("DG12 schedule identity or namespace drifted")
        parsed: dict[str, tuple[tuple[str, ...], ...]] = {}
        for matrix_name, expected_methods in EXPECTED_MATRICES.items():
            raw = matrices.get(matrix_name)
            if not isinstance(raw, dict):
                raise ScheduleError(f"missing schedule matrix: {matrix_name}")
            methods = raw.get("methods")
            rows = raw.get("rows")
            if methods != list(expected_methods) or not isinstance(rows, list):
                raise ScheduleError(f"method matrix drifted: {matrix_name}")
            periods = int(raw.get("periods", -1))
            if periods != len(expected_methods) or len(rows) != periods:
                raise ScheduleError(f"period count drifted: {matrix_name}")
            ordered_rows: list[tuple[str, ...]] = []
            for expected_index, row in enumerate(rows):
                if not isinstance(row, dict) or row.get("row_index") != expected_index:
                    raise ScheduleError(f"row index drifted: {matrix_name}")
                order = row.get("order")
                if (
                    not isinstance(order, list)
                    or len(order) != periods
                    or set(order) != set(expected_methods)
                ):
                    raise ScheduleError(f"row permutation drifted: {matrix_name}")
                ordered_rows.append(tuple(str(item) for item in order))
            parsed[matrix_name] = tuple(ordered_rows)
        return cls(path.resolve(), EXPECTED_NAMESPACE, parsed)

    def order(self, matrix: str, case_ordinal: int) -> tuple[str, ...]:
        if case_ordinal < 0 or matrix not in self.matrices:
            raise ScheduleError("matrix or case ordinal is invalid")
        rows = self.matrices[matrix]
        return rows[case_ordinal % len(rows)]
