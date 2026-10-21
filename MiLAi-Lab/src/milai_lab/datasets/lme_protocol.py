"""Released LME prompt/scoring functions with an explicit metered Judge transport."""
from __future__ import annotations

import ast
import base64
import importlib.util
import mimetypes
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class NativeLmeProtocol:
    """Reuse inspected upstream function bodies without importing memory backends or retries.

    One instance is used serially. Only the Judge client constructor is replaced;
    reference rubrics, eval-spec parsing, boxed-answer handling and metrics are native.
    The caller fixes the Reader/Judge model and retains all failed/unscored positions.
    """

    def __init__(self, upstream: Path) -> None:
        metrics_path = upstream / "evaluation/qa_eval_metrics.py"
        spec = importlib.util.spec_from_file_location("_milai_lme_native_metrics", metrics_path)
        assert spec is not None and spec.loader is not None
        self.metrics: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.metrics)
        names = {"DOMAIN_SYSTEM_PROMPTS", "CATEGORY_MAP", "NON_ABSTENTION_CATEGORIES",
            "ABSTENTION_CATEGORIES", "COMBINED_ABSTENTION_CATEGORY_PAIRS", "LLM_EVAL_FUNCTIONS",
            "require", "get_system_prompt", "to_data_url", "build_messages",
            "category_from_question_type", "aggregate_metrics", "score_prediction",
            "build_extra_body", "build_reader_request"}
        path = upstream / "evaluation/harness.py"
        parsed = ast.parse(path.read_text())
        nodes = [node for node in parsed.body if (
            isinstance(node, ast.FunctionDef) and node.name in names) or (
            isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names for target in node.targets))]
        namespace: dict[str, Any] = {"__name__": "_milai_lme_native_harness",
            "base64": base64, "mimetypes": mimetypes, "Path": Path,
            "eval_from_spec": self.metrics.eval_from_spec,
            "score_to_bool": self.metrics.score_to_bool}
        # Deferring type annotations avoids importing unrelated optional backend packages.
        module = ast.Module(body=[ast.ImportFrom(module="__future__",
            names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 -- inspected upstream bodies
        self.api = SimpleNamespace(**{name: namespace[name] for name in names})
        self.source_files = [str(metrics_path.resolve()), str(path.resolve())]

    def messages(self, domain: str, query: str, query_image: str | None,
                 context: list[dict[str, str]]) -> tuple[
                     list[dict[str, Any]], list[dict[str, Any]]]:
        wire, logged = self.api.build_messages(self.api.get_system_prompt(domain),
                                               query, query_image, context)
        return wire, logged

    def reader_request(self, messages: list[dict[str, Any]], host: dict[str, Any],
                       thinking: bool) -> dict[str, Any]:
        args = SimpleNamespace(model=host["model"], base_url=host["base_url"],
            timeout_seconds=host["timeout"], max_completion_tokens=host["max_tokens"],
            temperature=host["temperature"], reasoning_effort=None, top_p=None,
            presence_penalty=None, top_k=None, repetition_penalty=None,
            reader_enable_thinking=thinking)
        request: dict[str, Any] = self.api.build_reader_request(args, messages)
        return request

    def score(self, question: dict[str, Any], response: str, *,
              judge_options: dict[str, Any],
              complete: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
        """Called only after the actual Reader output; references never reach retrieval/Reader."""
        def create(**request: Any) -> SimpleNamespace:
            text = complete(request)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.metrics._create_openai_client = lambda **_: client
        parsed = self.metrics.extract_boxed_answer(response)
        name = self.metrics.eval_name(question["eval_function"])
        row = {"question_item": question, "eval_function": question["eval_function"],
            "eval_name": name, "answer_gold": question["answer"], "response_raw": response,
            "response_parsed_boxed": parsed, "is_unknown": self.metrics.is_unknown(parsed)}
        correct, _, unknown = self.api.score_prediction(row, judge_options)
        return {"score": float(correct), "score_bool": correct, "is_unknown": unknown,
            "response_parsed_boxed": parsed, "eval_name": name,
            "is_abstention_problem": name == "llm_abstention_checker",
            "category": self.api.category_from_question_type(question["question_type"])}

    def aggregate(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        """Native metrics only on scored records; unknown failures retain full planned coverage."""
        if not cases:
            raise ValueError("An evaluation needs a nonempty declared question cohort")
        scored = [case for case in cases if case["score"] is not None]
        correct = sum(case["score_bool"] for case in scored)
        native = self.api.aggregate_metrics(scored) if scored else None
        return {"planned": len(cases), "scored": len(scored), "unscored": len(cases)-len(scored),
            "status_counts": dict(Counter(case["status"] for case in cases)),
            "correct_scored": correct,
            "valid_model_UNKNOWN_answers": sum(case["is_unknown"] for case in scored),
            "native_complete_cohort_metrics": native if len(scored) == len(cases) else None,
            "native_scored_subset_metrics": native,
            "all_planned_score_bounds": [correct/len(cases),
                                          (correct+len(cases)-len(scored))/len(cases)],
            "scope": "Unscored program/Judge failures are not negative labels or invented UNKNOWN "
                     "answers. A valid model UNKNOWN is scored by the original benchmark rule. "
                     "Subset metrics are conditional, not a full-cohort score. Shared histories "
                     "and repeated seeds do not create independent source families."}
