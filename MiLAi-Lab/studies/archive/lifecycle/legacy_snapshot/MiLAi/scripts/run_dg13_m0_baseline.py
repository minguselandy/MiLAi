from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from milai_client import (
    DeterministicMemoryNeedResolver,
    DeterministicQueryOnlyIntentShadow,
)

TaskCondition = Literal["OMITTED", "UNKNOWN", "AVAILABLE"]


@dataclass(frozen=True, slots=True)
class _Case:
    case_id: str
    language: str
    query: str
    task_condition: TaskCondition


_CASES = (
    _Case("M0-EN-TASK-OMITTED", "EN", "What is the current release status?", "OMITTED"),
    _Case("M0-CN-TASK-UNKNOWN", "CN", "当前项目进行到哪里?", "UNKNOWN"),
    _Case("M0-MIXED-TASK-AVAILABLE", "MIXED", "Recall 当前 database setting", "AVAILABLE"),
    _Case("M0-BOUND-PROBE", "EN", "Could this affect the release?", "AVAILABLE"),
    _Case("M0-NOT-NEEDED", "EN", "What is 17 plus 25?", "AVAILABLE"),
)


def _fingerprint(query: str, version: str) -> str:
    return hashlib.sha256((version + "\0" + query).encode()).hexdigest()


def build_report() -> dict[str, object]:
    shadow_interpreter = DeterministicQueryOnlyIntentShadow()
    current_resolver = DeterministicMemoryNeedResolver()
    cases: list[dict[str, object]] = []
    for case in _CASES:
        shadow = shadow_interpreter.interpret(case.query, invocation_mode="PREFETCH_AUTO")
        current = current_resolver.resolve(
            case.query,
            scope={"project_ids": ["milai"]},
            required_authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
        )
        current_route = "NONE" if case.task_condition == "OMITTED" else current.requested_route
        disagreement = shadow.intent in {"POSSIBLE", "REQUIRED"} and current_route == "NONE"
        first_boundary = None
        if disagreement:
            first_boundary = (
                "HOST_TASK_GATE"
                if case.task_condition == "OMITTED"
                else "HOST_TYPED_NEED_FILTER"
            )
        cases.append(
            {
                "case_id": case.case_id,
                "language": case.language,
                "task_condition": case.task_condition,
                "query_fingerprint": _fingerprint(case.query, shadow.interpreter_version),
                "query_only": asdict(shadow),
                "current_task_gated": {
                    "intent": (
                        current.signature.intent_class if current_route != "NONE" else "NONE"
                    ),
                    "route": current_route,
                    "reason_code": (
                        "TASK_IDENTITY_OMITTED"
                        if case.task_condition == "OMITTED"
                        else current.reason_code
                    ),
                },
                "intent_route_disagreement": disagreement,
                "first_blocking_boundary": first_boundary,
                "shadow_changed_production_result": False,
            }
        )
    disagreements = [case for case in cases if case["intent_route_disagreement"] is True]
    return {
        "schema": "milai.dg13.m0-baseline.v1",
        "status": "BASELINE_REPLAYED",
        "case_count": len(cases),
        "query_only_possible_or_required_count": sum(
            case["query_only"]["intent"] in {"POSSIBLE", "REQUIRED"}  # type: ignore[index]
            for case in cases
        ),
        "task_gated_none_count": sum(
            case["current_task_gated"]["route"] == "NONE"  # type: ignore[index]
            for case in cases
        ),
        "intent_route_disagreement_count": len(disagreements),
        "first_blocking_boundaries": sorted(
            {
                str(case["first_blocking_boundary"])
                for case in disagreements
                if case["first_blocking_boundary"] is not None
            }
        ),
        "cases": cases,
        "privacy": {
            "query_plaintext_persisted": False,
            "fingerprint": "sha256(interpreter_version + NUL + query)",
        },
        "limitations": [
            "M0 shadow is observational and does not alter the current Host route.",
            "The fixed development cases are reachability diagnostics, not quality evidence.",
            "Runtime/MCP latency evidence is owned by RetrievalTrace-backed AccessTrace tests.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the bounded DG-13 M0 reachability baseline")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "case_count": report["case_count"],
                "intent_route_disagreement_count": report[
                    "intent_route_disagreement_count"
                ],
                "output": str(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
