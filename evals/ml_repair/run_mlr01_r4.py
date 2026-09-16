"""Stage runner for the bounded ML-R01 R4 characterization."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from evals.ml_repair.mlr01_r4_contexts import run_contexts
from evals.ml_repair.mlr01_r4_freeze import build_capability_seal
from evals.ml_repair.mlr01_r4_providers import run_answers, run_judges
from evals.ml_repair.mlr01_r4_score import score


def _run_target(stage: str, target: int) -> dict[str, Any]:
    functions: dict[str, Callable[[int], dict[str, Any]]] = {
        "contexts": run_contexts,
        "answers": run_answers,
        "judges": run_judges,
        "score": score,
    }
    return functions[stage](target)


def run_pilot_8() -> dict[str, Any]:
    capability = build_capability_seal()
    context = run_contexts(8)
    answer = run_answers(8)
    judge = run_judges(8)
    scored = score(8)
    return {
        "execution_scope": "USER_LIMITED_8_CASES_X_4_ARMS_THEN_STOP",
        "capability_seal_digest": capability["seal_digest"],
        "context": context,
        "answer": answer,
        "judge": judge,
        "score": scored,
        "stopped_before_128": True,
        "stopped_before_500": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        required=True,
        choices=(
            "seal",
            "contexts-8",
            "answers-8",
            "judges-8",
            "score-8",
            "pilot-8",
        ),
    )
    args = parser.parse_args()
    if args.stage == "seal":
        value = build_capability_seal()
    elif args.stage == "pilot-8":
        value = run_pilot_8()
    else:
        lane, target_text = args.stage.split("-", 1)
        value = _run_target(lane, int(target_text))
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
