"""Execute the authors' pure scoring functions with the shared accounted transport.

Official source files remain in their external checkout. Their function bodies
and prompt literals are loaded unchanged; only the HTTP callback is supplied by
the runner. No upstream cloud client, automatic retries or process pool is run.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any


def fixed_native_categories(sessions: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    """Predeclared metadata denominators, supplemental to author's dynamic counts."""
    categories: dict[str, Counter[str]] = {}
    for _, session in sessions:
        if session.get("is_generated_qa_session", False):
            continue
        for memory in session["memory_points"]:
            category = str(memory["memory_type"])
            counts = categories.setdefault(category, Counter())
            counts["all_native_opportunities"] += 1
            is_update = memory["is_update"] == "True"
            counts["updates" if is_update else "formation"] += 1
            counts["interference"] += memory["memory_source"] == "interference"
            counts["updates_missing_original"] += is_update and not memory.get("original_memories")
    return {category: dict(counts) for category, counts in sorted(categories.items())}


def author_functions(path: Path, names: set[str], bindings: dict[str, Any]) -> dict[str, Any]:
    tree = ast.parse(path.read_text(), filename=str(path))
    definitions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if {node.name for node in definitions} != names:
        raise ValueError(f"Official scoring functions missing from {path}")
    constants = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
    ]
    module = ast.Module(body=[*constants, *definitions], type_ignores=[])
    environment = dict(bindings)
    # Execute the selected functions from the explicitly selected author checkout.
    exec(compile(module, str(path), "exec"), environment)  # noqa: S102
    return environment


class HaluMemOfficial:
    def __init__(self, checkout: Path, judge: Callable[[str], dict[str, Any]]) -> None:
        self.functions = author_functions(
            checkout / "eval/eval_tools.py",
            {
                "evaluation_for_memory_integrity",
                "evaluation_for_memory_accuracy",
                "evaluation_for_update_memory",
                "evaluation_for_question",
            },
            {"llm_request_for_json": judge},
        )
        self.aggregate = author_functions(
            checkout / "eval/evaluation.py",
            {
                "compute_f1",
                "aggregate_eval_results",
            },
            {},
        )["aggregate_eval_results"]

    def score(self, name: str, *args: str) -> dict[str, Any]:
        return dict(self.functions["evaluation_for_" + name](*args))

    def aggregate_results(self, records: dict[str, Any]) -> dict[str, Any]:
        kinds = {
            item["memory_type"]
            for key in [
                "memory_integrity_records",
                "memory_update_records",
            ]
            for item in records[key]
        }
        results = {
            **records,
            "overall_score": {
                "memory_integrity": {},
                "memory_accuracy": {},
                "memory_extraction_f1": 0,
                "memory_update": {},
                "question_answering": {},
                "memory_type_accuracy": {
                    kind: {"memory_integrity_acc": 0, "memory_update_acc": 0, "total_num": 0}
                    for kind in kinds
                },
            },
        }
        try:
            self.aggregate(results)
        except ZeroDivisionError:
            # Keep upstream behavior visible for a prefix with missing denominators.
            results["official_aggregation_error"] = "ZeroDivisionError: absent prefix denominator"
        return results


class LongMemEvalOfficial:
    def __init__(self, checkout: Path) -> None:
        self.prompt = author_functions(
            checkout / "src/evaluation/evaluate_qa.py",
            {
                "get_anscheck_prompt",
            },
            {},
        )["get_anscheck_prompt"]

    def make_prompt(self, reference: dict[str, Any], hypothesis: str) -> str:
        return str(
            self.prompt(
                reference["question_type"],
                reference["question"],
                reference["answer"],
                hypothesis,
                abstention="_abs" in reference["question_id"],
            )
        )

    @staticmethod
    def label(response: str) -> bool:
        # This is exactly the official evaluator's label rule, including its limits.
        return "yes" in response.lower()
