"""Frozen-answer scoring for contextual-memory benchmark cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from milai_lab.datasets.contextual import EvaluationCase
from milai_lab.datasets.stale import PROBE_KEYS
from milai_lab.harness.contextual_artifacts import (
    BudgetExceeded,
    Trace,
    digest,
    read_json,
    write_json,
)
from milai_lab.providers.contextual_vllm import VLLMClient
from milai_lab.scorers import memsyco as memsyco_scoring
from milai_lab.scorers import stale as stale_scoring
from milai_lab.scorers.contextual import longmemeval_judge_prompt, parse_judge, score_mcq


def _judge(
    *,
    folder: Path,
    judge: VLLMClient,
    judge_attempts: int,
    messages: list[dict[str, str]],
    response_format: dict[str, Any] | None,
    parse: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    trace = Trace(folder / "trace.jsonl", "judge")
    judge.emit = trace
    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] = {"status": "JUDGE_UNRESOLVED", "success": None}
    for attempt in range(judge_attempts):
        try:
            raw = judge.chat(messages, response_format=response_format)
            choice = raw["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("Judge output truncated")
            parsed = parse(choice["message"]["content"])
            entry = {"attempt": attempt, "parsed": parsed, "receipt": raw}
            attempts.append(entry)
            write_json(folder / f"attempt-{attempt}.json", entry)
            result.update(parsed)
            if not parsed["format_error"]:
                result["status"] = "SCORED"
                break
        except BudgetExceeded as error:
            result["reason"] = str(error)
            break
        except (httpx.HTTPError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
            entry = {"attempt": attempt, "error": type(error).__name__, "message": str(error)}
            attempts.append(entry)
            write_json(folder / f"attempt-{attempt}.json", entry)
    result.update(attempts=attempts, usage_receipts=trace.usage)
    return result


def score_case(
    case: EvaluationCase,
    answer: dict[str, Any],
    *,
    output: Path,
    judge: VLLMClient,
    judge_attempts: int,
) -> dict[str, Any]:
    """Score one non-STALE answer; retained as the CLI's legacy export."""
    if case.dataset == "stale":
        raise ValueError("STALE requires scenario-level scoring of all three probes")
    frozen = read_json(output / "answer-batch.json")
    entry = next(
        item
        for item in frozen["entries"]
        if item["question_id"] == case.case_id and item["arm"] == answer["arm"]
    )
    if entry.get("answer_sha256") != digest(answer):
        raise ValueError("Scoring requires the exact answer in the frozen batch")
    folder = output / "scores" / answer["arm"] / digest(case.case_id)
    terminal = folder / "score.json"
    if terminal.exists():
        existing: dict[str, Any] = read_json(terminal)
        if existing["answer_sha256"] != digest(answer):
            raise ValueError("Scoring answer changed after freeze")
        return existing
    result: dict[str, Any] = {
        "question_id": case.case_id,
        "arm": answer["arm"],
        "answer_sha256": digest(answer),
        "groups": case.groups,
    }
    if answer["status"] != "complete":
        result.update(status="HOST_INCOMPLETE", success=None)
    elif case.dataset not in {"longmemeval-s-cleaned", "memsyco"}:
        result.update(score_mcq(answer["hypothesis"], case), status="SCORED")
    else:
        if case.dataset == "memsyco":
            messages = memsyco_scoring.judge_messages(case, answer["hypothesis"])
            response_format = memsyco_scoring.judge_response_format(case.groups["track"])

            def parse(content: str) -> dict[str, Any]:
                return memsyco_scoring.parse_judge(case.groups["track"], content)

        else:
            messages = [
                {"role": "user", "content": longmemeval_judge_prompt(case, answer["hypothesis"])}
            ]
            response_format = None

            def parse(content: str) -> dict[str, Any]:
                return parse_judge(content)

        result.update(
            _judge(
                folder=folder,
                judge=judge,
                judge_attempts=judge_attempts,
                messages=messages,
                response_format=response_format,
                parse=parse,
            )
        )
    write_json(terminal, result)
    return result


def score_stale_group(
    cases: Sequence[EvaluationCase],
    answers: Mapping[str, dict[str, Any] | None],
    *,
    arm: str,
    output: Path,
    judge: VLLMClient,
    judge_attempts: int,
) -> dict[str, dict[str, Any]]:
    """Score three frozen probes with exactly one native scenario Judge request."""
    by_key = {case.metadata["probe_key"]: case for case in cases}
    if len(cases) != 3 or set(by_key) != set(PROBE_KEYS):
        raise ValueError("STALE scoring requires three native probes")
    scenario_id = cases[0].metadata["scenario_id"]
    if any(case.metadata["scenario_id"] != scenario_id for case in cases):
        raise ValueError("STALE scoring requires one scenario")
    frozen = read_json(output / "answer-batch.json")
    entries = {
        item["question_id"]: item
        for item in frozen["entries"]
        if item["arm"] == arm and item["question_id"] in {case.case_id for case in cases}
    }
    if len(entries) != 3:
        raise ValueError("STALE scoring requires all probes in the frozen batch")
    answer_hashes: dict[str, str | None] = {}
    for case in cases:
        answer = answers.get(case.case_id)
        expected = entries[case.case_id].get("answer_sha256")
        actual = digest(answer) if answer is not None else None
        if expected != actual or (answer is not None and answer["arm"] != arm):
            raise ValueError("STALE scoring requires exact frozen answers")
        answer_hashes[case.case_id] = actual
    folder = output / "scores" / arm / "_scenarios" / digest(scenario_id)
    terminal = folder / "judge.json"
    group_result: dict[str, Any]
    if terminal.exists():
        group_result = read_json(terminal)
        if group_result["answer_sha256"] != answer_hashes:
            raise ValueError("STALE answers changed after group scoring")
    else:
        complete_answers = {
            case.case_id: answer
            for case in cases
            if (answer := answers.get(case.case_id)) is not None and answer["status"] == "complete"
        }
        group_result = {
            "scenario_id": scenario_id,
            "arm": arm,
            "answer_sha256": answer_hashes,
            "status": "HOST_INCOMPLETE",
            "judge_result": None,
        }
        if len(complete_answers) == 3:
            messages = stale_scoring.judge_messages(
                cases,
                {case.case_id: complete_answers[case.case_id]["hypothesis"] for case in cases},
            )
            judged = _judge(
                folder=folder,
                judge=judge,
                judge_attempts=judge_attempts,
                messages=messages,
                response_format=stale_scoring.judge_response_format(),
                parse=stale_scoring.parse_judge,
            )
            group_result["status"] = judged["status"]
            group_result["judge_result"] = judged
        write_json(terminal, group_result)
    parsed = group_result["judge_result"]
    probe_scores = (
        stale_scoring.probe_judgments(parsed) if group_result["status"] == "SCORED" else {}
    )
    results: dict[str, dict[str, Any]] = {}
    for case in cases:
        answer = answers.get(case.case_id)
        score: dict[str, Any] = {
            "question_id": case.case_id,
            "arm": arm,
            "answer_sha256": answer_hashes[case.case_id],
            "groups": case.groups,
            "shared_judge_path": str(terminal.relative_to(output)),
        }
        if answer is None or answer["status"] != "complete":
            score.update(status="HOST_INCOMPLETE", success=None)
        elif group_result["status"] == "SCORED":
            score.update(probe_scores[case.metadata["probe_key"]], status="SCORED")
        else:
            score.update(
                status="JUDGE_UNRESOLVED",
                success=None,
                format_error=bool(parsed and parsed.get("format_error")),
            )
        path = output / "scores" / arm / digest(case.case_id) / "score.json"
        if path.exists():
            if read_json(path) != score:
                raise ValueError("STALE probe score changed on resume")
        else:
            write_json(path, score)
        results[case.case_id] = score
    return results
