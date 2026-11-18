"""Dispatch prepared external tasks under the original Reader lease and score EventQA."""

from __future__ import annotations

import argparse
import fcntl
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

from milai_lab.datasets.contextual import EvaluationCase, TaskInput
from milai_lab.datasets.edit_benchmarks import longmemeval_cases
from milai_lab.datasets.memory_control_reader_task import (
    LONGMEMEVAL_S,
    MEMORYAGENTBENCH_EVENTQA,
    ReaderTask,
)
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.harness.contextual_artifacts import BudgetExceeded, http_budget_scope
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.runners.memory_control_outcome_run import remaining_reader_capacity, request_reader
from milai_lab.scorers.contextual import longmemeval_judge_prompt, parse_judge
from milai_lab.scorers.memory_control_native import answer_tokens, parsed_answer
from run_memory_control_external import PROTOCOL

TERMINAL = {"action_failed", "reader_completed", "reader_error", "reader_interrupted"}


def load_prepared(path: Path) -> dict[str, Any]:
    document = read_json(path)
    if (
        not isinstance(document, dict)
        or document["protocol"] != PROTOCOL
        or document["status"] != "PREPARED"
        or document["source"] not in {"eventqa", "longmemeval"}
        or document["reader_requests"] != 0
        or not document["episodes"]
        or len(document["episodes"]) != document["position_count"]
    ):
        raise ValueError("External Reader execution requires a completed preparation receipt")
    ids = {row["native_question_id"] for row in document["episodes"]}
    files = {Path(row["episode"]).name for row in document["episodes"]}
    if len(ids) != document["position_count"] or len(files) != document["position_count"]:
        raise ValueError("Prepared identities and dispositions must be unique")
    return document


def _position(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    record = read_json(path)
    if not isinstance(record, dict) or record["native_question_id"] != entry["native_question_id"]:
        raise ValueError("External question identity changed")
    if record["native_group"] != entry["group"]:
        raise ValueError("External source group changed")
    return record


def _response_content(result: dict[str, Any]) -> Any:
    return result["response"]["choices"][0]["message"].get("content")


def _prediction(record: dict[str, Any], source: str) -> str | None:
    body = _response_content(record["reader_result"])
    parsed = parsed_answer(body, ReaderTask(source, "")) if isinstance(body, str) else None
    return str(parsed["answer"]) if parsed else None


def execute(data: Path, preparation: Path, out: Path, limit: int) -> dict[str, Any]:
    plan = load_prepared(preparation)
    dataset = MemoryControlDataset(data)
    host, revision = dataset.host, dataset.revision
    if (
        host is None
        or revision is None
        or dataset.run_id != plan["reference_run_id"]
        or revision["primary_budget"] != plan["material_budget"]
    ):
        raise ValueError("Prepared external requests must use their bound Reader and budget")
    protocol = {
        "protocol": PROTOCOL,
        "preparation": str(preparation.resolve()),
        "source": plan["source"],
        "arm": plan["arm"],
        "reference_run_id": dataset.run_id,
        "reader_config": str(host.config_path),
    }
    out.mkdir(parents=True, exist_ok=True)
    protocol_path = out / "protocol.json"
    with (
        (out / ".reader.lock").open("a") as lock,
        http_budget_scope(
            host.settings, client_configs=ownership_client_configs(host.settings)
        ) as budget,
    ):
        if budget is None:
            raise ValueError("External Reader execution requires the original shared ledger")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if protocol_path.is_file() and read_json(protocol_path) != protocol:
            raise ValueError("External Reader scope changed on resume")
        existing = read_json(out / "run.json")
        if isinstance(existing, dict) and existing["status"] == "COMPLETED":
            return existing
        write_json(protocol_path, protocol)
        before = budget.state["generation_requests"]
        counts: Counter[str] = Counter()
        with VLLMClient(
            VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity
        ) as client:
            for entry in plan["episodes"]:
                source = Path(entry["episode"])
                destination = out / "episodes" / source.name
                if destination.is_file():
                    record = _position(destination, entry)
                    if record["status"] == "dispatching":
                        record["status"] = "reader_interrupted"
                        write_json(destination, record)
                    if record["status"] in TERMINAL:
                        counts[record["status"]] += 1
                        continue
                    if record["status"] != "not_issued_budget":
                        raise ValueError("Unexpected persisted external episode disposition")
                else:
                    record = _position(source, entry)
                    if record["status"] not in {"ready", "action_failed"} or (
                        record["status"] != entry["status"]
                    ):
                        raise ValueError("Prepared external disposition changed")
                if record["status"] in {"ready", "not_issued_budget"}:
                    if budget.state["generation_requests"] - before >= limit:
                        break
                    record["status"] = "dispatching"
                    write_json(destination, record)
                    try:
                        result, costs = request_reader(
                            client, host, record["reader_wire"], record["capacity"]
                        )
                    except BudgetExceeded:
                        record["status"] = "not_issued_budget"
                        write_json(destination, record)
                        counts[record["status"]] += 1
                        break
                    record.update(status=result["status"], reader_result=result)
                    record["costs"].update(costs)
                write_json(destination, record)
                counts[record["status"]] += 1
        terminal = sum(counts.values()) - counts["not_issued_budget"]
        receipt = {
            **protocol,
            "status": "COMPLETED" if terminal == plan["position_count"] else "PARTIAL",
            "closed_positions": terminal,
            "position_count": plan["position_count"],
            "by_episode_status": dict(counts),
            "reader_requests_this_invocation": budget.state["generation_requests"] - before,
            "ledger_remaining_at_release": remaining_reader_capacity(budget),
            "sha_validation": False,
        }
        write_json(out / "run.json", receipt)
    return receipt


def score_eventqa(out: Path, labels: Path) -> dict[str, Any]:
    receipt = read_json(out / "run.json")
    if receipt["status"] != "COMPLETED" or receipt["source"] != "eventqa":
        raise ValueError("Seal all prepared EventQA Reader positions before loading references")
    preparation = load_prepared(Path(receipt["preparation"]))
    references = read_json(labels)
    if references["source_revision"] != preparation["provenance"]["source_revision"]:
        raise ValueError("EventQA reference release differs from the prepared release")
    cases = []
    by_book: dict[str, list[bool]] = defaultdict(list)
    for entry in preparation["episodes"]:
        path = out / "episodes" / Path(entry["episode"]).name
        record = _position(path, entry)
        refs = references["labels"][record["native_question_id"]]
        if not refs or not all(isinstance(ref, str) and answer_tokens(ref) for ref in refs):
            raise ValueError("Each released EventQA reference must contain text")
        status = record["status"]
        score = False
        if status == "reader_completed":
            answer = _prediction(record, MEMORYAGENTBENCH_EVENTQA)
            status = "scored" if answer is not None else "scored_format_failure"
            if answer is not None:
                normalized = " ".join(answer_tokens(answer))
                score = any(" ".join(answer_tokens(ref)) in normalized for ref in refs)
        by_book[entry["group"]].append(score)
        cases.append(
            {
                "native_question_id": record["native_question_id"],
                "source_group": entry["group"],
                "status": status,
                "substring_exact_match": score,
                "reader_input_tokens": record["costs"].get("reader_input_tokens"),
            }
        )
    return {
        "source": "eventqa_full",
        "protocol": PROTOCOL,
        "reader_run": str((out / "run.json").resolve()),
        "arm": receipt["arm"],
        "position_count": len(cases),
        "source_groups": len(by_book),
        "substring_exact_match_equal_book_mean": fmean(fmean(rows) for rows in by_book.values()),
        "by_source_group": {
            name: {"positions": len(rows), "substring_exact_matches": sum(rows)}
            for name, rows in by_book.items()
        },
        "dispositions": dict(Counter(row["status"] for row in cases)),
        "cases": cases,
        "reader_requests_in_scoring": 0,
        "sha_validation": False,
    }


def judge_longmemeval(data: Path, reader_run: Path, output: Path, limit: int) -> dict[str, Any]:
    receipt = read_json(reader_run / "run.json")
    if receipt["status"] != "COMPLETED" or receipt["source"] != "longmemeval":
        raise ValueError("Seal LongMemEval Reader predictions before opening references")
    plan = load_prepared(Path(receipt["preparation"]))
    if plan["provenance"]["scope"] != "previously_evaluated_external_regression":
        raise ValueError("Use the registered prior-exposure LongMemEval release")
    ids = [entry["native_question_id"] for entry in plan["episodes"]]
    rows = {r["question_id"]: r for r in longmemeval_cases(Path(plan["input"]), ids)}
    dataset = MemoryControlDataset(data)
    host = dataset.host
    if host is None or dataset.run_id != plan["reference_run_id"]:
        raise ValueError("Use the Reader bound to this preparation")
    model = host.settings["host"]["model"]
    declaration = {
        "source": "longmemeval_s_cleaned",
        "scope": plan["provenance"]["scope"],
        "reader_run": str(reader_run.resolve()),
        "judge_protocol": "longmemeval_rubric_with_project_reader",
        "judge_model": model,
    }
    output.mkdir(parents=True, exist_ok=True)
    with http_budget_scope(
        host.settings, client_configs=ownership_client_configs(host.settings)
    ) as budget:
        if budget is None:
            raise ValueError("LongMemEval judging requires the original shared ledger")
        protocol = output / "protocol.json"
        if protocol.is_file() and read_json(protocol) != declaration:
            raise ValueError("LongMemEval judge protocol changed on resume")
        existing = read_json(output / "run.json")
        if isinstance(existing, dict) and existing["status"] == "COMPLETED":
            return existing
        write_json(protocol, declaration)
        before = budget.state["generation_requests"]
        scored = []
        with VLLMClient(
            VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity
        ) as client:
            for entry in plan["episodes"]:
                path = reader_run / "episodes" / Path(entry["episode"]).name
                record = _position(path, entry)
                key = record["native_question_id"]
                destination = output / "judgments" / path.name
                observed = read_json(destination)
                if observed is not None:
                    if observed["native_question_id"] != key:
                        raise ValueError("Saved LongMemEval judgment identity changed")
                    if observed["status"] == "judge_dispatching":
                        observed["status"] = "judge_interrupted"
                        write_json(destination, observed)
                    if observed["status"] != "not_issued_budget":
                        scored.append(observed)
                        continue
                outcome: dict[str, Any] = {
                    "native_question_id": key,
                    "source_group": entry["group"],
                    "status": record["status"],
                    "correct": False,
                }
                if record["status"] == "reader_completed":
                    answer = _prediction(record, LONGMEMEVAL_S)
                    if answer is None:
                        outcome["status"] = "reader_format_failure"
                    else:
                        if budget.state["generation_requests"] - before >= limit:
                            break
                        raw = rows[key]
                        public = TaskInput(
                            "external", key, (), raw["question"], raw["question_date"]
                        )
                        case = EvaluationCase(
                            key,
                            "longmemeval-s-cleaned",
                            "external",
                            public,
                            {"answer": raw["answer"], "question_type": raw["question_type"]},
                            {},
                            {"abstention": "_abs" in key},
                        )
                        wire = {
                            "model": model,
                            "temperature": 0.0,
                            "max_tokens": 32,
                            "seed": record["reader_wire"]["seed"],
                            "chat_template_kwargs": {"enable_thinking": False},
                            "messages": [
                                {"role": "user", "content": longmemeval_judge_prompt(case, answer)}
                            ],
                        }
                        try:
                            capacity = host.capacity.check(
                                wire["messages"], output_tokens=32, enable_thinking=False
                            )
                        except CapacityExceeded as exc:
                            outcome.update(status="judge_capacity_exceeded", capacity=exc.receipt)
                        else:
                            outcome.update(status="judge_dispatching", judge_wire=wire)
                            write_json(destination, outcome)
                            try:
                                reply, costs = request_reader(client, host, wire, capacity)
                            except BudgetExceeded:
                                outcome["status"] = "not_issued_budget"
                                write_json(destination, outcome)
                                break
                            outcome.update(judge_result=reply, judge_costs=costs)
                            if reply["status"] == "reader_completed":
                                grade = parse_judge(_response_content(reply))
                                grade_status = (
                                    "judge_format_failure" if grade["format_error"] else "scored"
                                )
                                outcome.update(status=grade_status, correct=grade["success"])
                            else:
                                outcome["status"] = "judge_error"
                write_json(destination, outcome)
                scored.append(outcome)
        summary = {
            **declaration,
            "status": "COMPLETED" if len(scored) == len(ids) else "PARTIAL",
            "position_count": len(ids),
            "closed_positions": len(scored),
            "observed_correct": sum(x["correct"] for x in scored),
            "dispositions": dict(Counter(x["status"] for x in scored)),
            "reader_requests_this_invocation": budget.state["generation_requests"] - before,
            "sha_validation": False,
        }
        write_json(output / "run.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dispatch = commands.add_parser("execute")
    dispatch.add_argument("--data", type=Path, required=True)
    dispatch.add_argument("--prepared", type=Path, required=True)
    dispatch.add_argument("--out", type=Path, required=True)
    dispatch.add_argument("--limit", type=int, required=True)
    score = commands.add_parser("score-eventqa")
    score.add_argument("--reader-run", type=Path, required=True)
    score.add_argument("--references", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    judge = commands.add_parser("judge-longmemeval")
    judge.add_argument("--data", type=Path, required=True)
    judge.add_argument("--reader-run", type=Path, required=True)
    judge.add_argument("--out", type=Path, required=True)
    judge.add_argument("--limit", type=int, required=True)
    args = parser.parse_args()
    if args.command == "execute":
        if args.limit < 1:
            parser.error("use a positive Reader request limit")
        result = execute(args.data, args.prepared, args.out, args.limit)
        print(result)
    elif args.command == "score-eventqa":
        result = score_eventqa(args.reader_run, args.references)
        write_json(args.output, result)
        print(f"EventQA score receipt at {args.output}")
    else:
        if args.limit < 1:
            parser.error("use a positive Judge request limit")
        print(judge_longmemeval(args.data, args.reader_run, args.out, args.limit))


if __name__ == "__main__":
    main()
