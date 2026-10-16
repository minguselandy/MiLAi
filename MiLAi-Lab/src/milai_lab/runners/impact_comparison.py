"""Impact controls on copies of actual model-formed states and their original arrival.

D0/D1/D2 use the same representation, candidate retrieval, Writer and Reader.
The source seed is reused as observed; no graph or corrected state is supplied.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import ObservedSession
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.edit_benchmarks import READER_PROMPT, BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import _copy_bank, _service, diagnostic_costs

ARMS = ("D0", "D1", "D2-Laya-0", "D2-Laya-CE")


def prepare_comparison(config: dict[str, Any], root: Path) -> dict[str, Any]:
    source = Path(config["source_run"])
    prior = read_json(source / "prepared.json")
    cases = [case for case in prior["cases"] if case["id"] in config["cases"]]
    for case in cases:
        # These are finished source formation/capture artifacts, not old Impact labels.
        read_json(source / case["id"] / "seed/result.json")
        read_json(source / case["id"] / "arrival/complete.json")
    protocol = {"config": config, "cases": cases, "settings": prior["settings"],
        "status": "PREPARED_ZERO_MODEL",
        "scope": "common actual before; previously exposed development histories",
        "state_repair": False, "independent_formation": False,
        "source_seed_cost": "historical cost retained once in source run; no repeated formation"}
    path = root / "prepared.json"
    if path.exists() and read_json(path) != protocol:
        raise ValueError("Comparison inputs changed; use another experiment directory")
    write_json(path, protocol)
    return protocol


def comparison_settings(protocol: dict[str, Any], arm: str, case_id: str) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError(f"Unknown Impact comparison arm: {arm}")
    settings: dict[str, Any] = copy.deepcopy(protocol["settings"])
    name = f"{protocol['config']['name']}-{arm}-{case_id}"
    settings.update(arm="M", experiment_name=name, config_version=name,
                    dependency_reading=False, read_usage_updates=False)
    settings["edit_features"]["dependency_updates"] = arm != "D0"
    if arm.startswith("D2-"):
        settings["laya_impact"] = protocol["config"]["laya"][arm]
    return settings


def state_reader_messages(records: list[dict[str, Any]], question: str,
                          date: str) -> list[dict[str, str]]:
    """A diagnostic from actual current semantics, without original/support text."""
    retained = [{"id": row["id"], "revision": row["value"]["revision"],
                 "content": row["value"]["content"], "scope": row["value"]["scope"]}
                for row in records]
    return [{"role": "system", "content": READER_PROMPT + (
        "\nThis diagnostic supplies only the currently retained semantic state. "
        "Original source text and historical versions are unavailable. "
        "Answer only what this state supports; distinguish missing information."
    )}, {"role": "user", "content": json.dumps({
        "question": question, "observed_date": date, "retained_state": retained,
    }, ensure_ascii=False)}]


def comparison_costs(root: Path) -> dict[str, Any]:
    costs = diagnostic_costs(root)
    stage: dict[str, Any] = {"requests": 0, "questions": 0, "input_tokens": 0,
                             "output_tokens": 0, "wall_seconds": 0.0, "unknown_usage": 0}
    for path in (root / "typed-http").rglob("response.json"):
        receipt = read_json(path)
        stage["requests"] += 1
        stage["questions"] += receipt["unit_count"]
        stage["wall_seconds"] += receipt["latency_seconds"]
        try:
            response = json.loads(receipt["response_text"])
        except json.JSONDecodeError:
            response = {}
        usage = response.get("usage", {})
        if isinstance(usage.get("input_tokens"), int):
            stage["input_tokens"] += usage["input_tokens"]
            stage["output_tokens"] += usage.get("output_tokens", 0)
        else:
            stage["unknown_usage"] += 1
    costs["typed_impact"] = stage
    costs["typed_requests_without_response"] = [
        str(path.relative_to(root)) for path in (root / "typed-http").rglob("request.json")
        if not path.with_name("response.json").exists()]
    timings = list((root / "call-timings").rglob("*.json"))
    costs["call_wall_seconds"] = sum(read_json(p)["wall_seconds"] for p in timings)
    return costs


class TimedBenchmarkRun(BenchmarkRun):
    def call(self, key: str, messages: list[dict[str, str]], **kwargs: Any) -> str:
        cached = (self.root / "http" / key / "response.json").exists()
        started = time.perf_counter()
        try:
            return super().call(key, messages, **kwargs)
        finally:
            if not cached:
                write_json(self.root / "call-timings" / key / "timing.json", {
                    "wall_seconds": time.perf_counter() - started, "key": key})


def run_comparison_arm(protocol: dict[str, Any], root: Path, arm: str, *,
                       run_class: type[BenchmarkRun] = TimedBenchmarkRun) -> dict[str, Any]:
    cases = {}
    for case in protocol["cases"]:
        folder = root / arm / case["id"]
        result_path = folder / "result.json"
        if result_path.exists():
            cases[case["id"]] = read_json(result_path)
            continue
        if (folder / "bank/memory.sqlite").exists():
            raise ValueError(f"Unclosed comparison bank: {folder}; inspect original requests")
        source = Path(protocol["config"]["source_run"]) / case["id"]
        seed = read_json(source / "seed/result.json")
        run = run_class(comparison_settings(protocol, arm, case["id"]), folder, phase="predict")
        started = time.perf_counter()
        try:
            bank = folder / "bank"
            bank.mkdir()
            _copy_bank(source / "arrival/memory.sqlite", bank / "memory.sqlite")
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = _service(run, store, case["owner"], bank)
                before = service.records()
                if {r["id"]: r["value"] for r in before} != {
                        r["id"]: r["value"] for r in seed["actual_state"]}:
                    raise ValueError("The fork differs from the real source seed")
                write_json(folder / "before.json", before)
                observed = ObservedSession(**case["observations"]["update"])
                run.maintain_recipe(service, observed, "update")
                after = service.records()
                write_json(folder / "after.json", after)
                answers = []
                for query in case["queries"]:
                    for mode in ("state_only", "mixed"):
                        key = f"questions/{mode}/{query['id']}"
                        answer = {"query_id": query["id"], "question": query["question"],
                                  "kind": query["kind"], "mode": mode}
                        try:
                            if mode == "state_only":
                                answer["hypothesis"] = run.call(key, state_reader_messages(
                                    after, query["question"], observed.date), structured=False,
                                    enable_thinking=run.stage_thinking("reader"))
                            else:
                                answer["hypothesis"] = run.answer(
                                    service, query["question"], observed.date, key)
                        except ValueError as error:
                            failure = run._known_reader_failure(error, key)
                            if failure is None:
                                raise
                            answer.update(hypothesis=None, reader_failure=failure)
                        answers.append(answer)
                        write_json(folder / "answers.json", answers)
                result = {"status": "CASE_ATTEMPTS_CLOSED", "arm": arm, "case": case["id"],
                    "before": before, "after": after, "answers": answers,
                    "maintenance": read_json(folder / "maintenance/update/complete.json"),
                    "read_values_unchanged": after == service.records(),
                    "state_correct": None, "answer_correct": None,
                    "semantic_review": "pending; execution is not semantic correctness"}
        finally:
            run.close()
        result.update(wall_seconds=time.perf_counter() - started, costs=comparison_costs(folder))
        write_json(result_path, result)
        cases[case["id"]] = result
    summary = {"status": "ARM_ATTEMPTS_CLOSED", "arm": arm, "cases": cases,
               "independent_formation": False, "full_goal_complete": False}
    write_json(root / arm / "summary.json", summary)
    return summary
