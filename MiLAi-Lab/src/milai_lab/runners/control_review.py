"""Finite single-candidate four-axis review using existing transport and budget."""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.methods.control_outcomes import (
    parse_outcome,
    review_contract,
    review_input,
    review_schema,
    unavailable_outcome,
)
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


def review_cases(cases: list[dict[str, Any]], settings: dict[str, Any], output: Path,
                 *, protocol: str) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "cases.json", cases)
    config = VLLMConfig(**settings["host"])
    rubric, _, _ = review_contract(protocol)
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(), "protocol": protocol,
        "planned": len(cases), "closed": 0, "judge_calls": 0, "judge_failures": 0,
        "input_unavailable": 0, "automatic_retry": False, "sha_validation": False,
        "generation_contract": asdict(config), "budget_path": settings["budget_path"],
        "independent_human_review": False,
        "scope": "Single-candidate independent axes; no old response/label replacement"}
    write_json(output / "run.json", run)
    trace = Trace(output / "trace.jsonl", "small_control_four_axis_review")
    results = []
    started, cpu = time.perf_counter(), time.process_time()
    with http_budget_scope(settings) as budget:
        assert budget is not None
        before = dict(budget.state["generation"])
        try:
            with VLLMClient(config, budget=budget, capacity=HostCapacity(settings["capacity"]),
                            emit=trace) as client:
                for case in cases:
                    destination = output / case["sample_id"]
                    destination.mkdir(exist_ok=False)
                    record = {key: case[key] for key in ("sample_id", "stratum", "expected")
                              if key in case}
                    if case["review_input_status"] != "complete":
                        outcome = unavailable_outcome(case, "input_unavailable_not_judged")
                        run["input_unavailable"] += 1
                    else:
                        request: dict[str, Any] = {
                            "messages": [{"role": "system", "content": rubric},
                            {"role": "user", "content": json.dumps(review_input(case,
                                protocol=protocol),
                                                                   ensure_ascii=False)}],
                            "response_format": {"type": "json_schema", "json_schema": {
                                "name": "memory_outcome_axes", "schema": review_schema(
                                    case, protocol)}}}
                        write_json(destination / "request.json", request)
                        run["judge_calls"] += 1
                        try:
                            response = client.chat(request["messages"],
                                response_format=request["response_format"],
                                enable_thinking=config.enable_thinking)
                            write_json(destination / "response.json", response)
                            if response["choices"][0]["finish_reason"] != "stop":
                                raise ValueError("First review response incomplete")
                            outcome = parse_outcome(response["choices"][0]["message"]["content"],
                                                    case, protocol=protocol)
                        except Exception as error:
                            outcome = unavailable_outcome(case, "judge_failed")
                            record["error"] = f"{type(error).__name__}: {error}"
                            run["judge_failures"] += 1
                            if (budget.state["generation"]["unknown_usage"]
                                    > before["unknown_usage"]):
                                write_json(destination / "result.json",
                                           {**record, "outcome": outcome})
                                raise
                    record["outcome"] = outcome
                    write_json(destination / "result.json", record)
                    results.append(record)
                    run["closed"] += 1
                    write_json(output / "run.json", run)
                    if run["closed"] % 20 == 0:
                        print(json.dumps({k: run[k] for k in (
                            "closed", "judge_calls", "judge_failures", "input_unavailable")}),
                            flush=True)
            run["status"] = "COMPLETED_WITH_FAILURES" if run["judge_failures"] else "COMPLETED"
        except Exception as error:
            run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            run.update(wall_seconds=time.perf_counter() - started,
                cpu_seconds=time.process_time() - cpu,
                generation_delta={key: value - before[key]
                                  for key, value in budget.state["generation"].items()},
                compute_ledger_status="pending_idle_settlement")
            write_json(output / "run.json", run)
            write_json(output / "results.json", results)
            summary = {}
            for stratum in sorted({r.get("stratum", "unlabelled") for r in results}):
                subset = [r for r in results if r.get("stratum", "unlabelled") == stratum]
                summary[stratum] = {"closed": len(subset), "primary": dict(Counter(
                    str(r["outcome"]["primary_outcome"]) for r in subset)),
                    "axes": {axis: dict(Counter(r["outcome"][axis] for r in subset))
                             for axis in ("execution_status", "material_sufficiency",
                                          "answer_support", "answer_completeness")}}
            write_json(output / "summary.json", summary)
    return run
