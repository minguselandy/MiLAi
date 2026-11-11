"""Complete released-cohort prediction and separate scoring, with original haystack order."""
from __future__ import annotations

import copy
import os
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import transformers

from milai_lab.datasets.lme_protocol import NativeLmeProtocol
from milai_lab.datasets.longmemeval_v2 import public_question
from milai_lab.harness.artifact_io import entrypoint_settings, read_json, read_jsonl, write_json
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.image_capacity import ImageHostCapacity
from milai_lab.runners.lme_continuation import prediction_roots
from milai_lab.runners.lme_reader import predict_reader, score_reader
from milai_lab.runners.lme_v2 import LmeMemoryBackend


def freeze_native_protocol(upstream: Path, target: Path) -> None:
    """Retain the inspected native implementation itself, with direct byte equality only."""
    (target/"evaluation").mkdir(parents=True, exist_ok=False)
    for name in ("harness.py", "qa_eval_metrics.py"):
        original, saved = upstream/"evaluation"/name, target/"evaluation"/name
        shutil.copyfile(original, saved)
        if original.read_bytes() != saved.read_bytes():
            raise ValueError("Native scoring source changed during its literal copy")


def predict_cohort(
    config: Path, snapshot: Path, upstream: Path, output: Path, *, source_version: str,
    capacity_factory: Callable[[dict[str, Any]], HostCapacity] = ImageHostCapacity,
    transport: httpx.BaseTransport | None = None,
    continue_from: Path | None = None,
) -> dict[str, Any]:
    """Every question once, using only its unchanged public query/image and native haystack."""
    parent = None
    parents: list[Path] = []
    if continue_from is not None:
        parent = read_json(continue_from / "driver.json")
        if (parent["status"] != "FAILED" or parent.get("schema") != "lme_prediction_cohort_v2"
                or parent["source_version"] != source_version
                or Path(parent["snapshot"]).resolve() != snapshot.resolve()
                or read_json(continue_from / "configuration.json") != read_json(config)):
            raise ValueError("Continue a closed failed prediction run with unchanged inputs/method")
        if not any(c["status"] == "NOT_RUN" for c in parent["cases"]):
            raise ValueError("No unattempted prediction positions; failed cases are not retried")
        parents = prediction_roots(continue_from)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    nested_cpu = 0.0
    driver: dict[str, Any] = {"schema": "lme_prediction_cohort_v2",
        "status": "RUNNING", "pid": os.getpid(),
        "source_version": source_version, "snapshot": str(snapshot.resolve()),
        "output": str(output.resolve()), "automatic_retry": False,
        "runtime": {"python": sys.version, "transformers": transformers.__version__,
                    "interpreter": sys.executable},
        "phase": "PREDICTION_ONLY", "cases": [], "planned_positions": None,
        "continued_from": str(continue_from.resolve()) if continue_from is not None else None,
        "inherited_rows": [] if parent is None else
            [c["row"] for c in parent["cases"] if c["status"] != "NOT_RUN"],
        "scope": "Complete supplied Small snapshot cohort, native haystacks, "
                 "unchanged questions/images. "
                 "Textual controller and multimodal fixed Reader; no gold-based filtering. "
                 "Each question has its own Store clone; same loaded controller pool across banks."}
    write_json(output/"driver.json", driver)
    try:
        protocol_source = upstream if continue_from is None else continue_from/"native-protocol"
        freeze_native_protocol(protocol_source, output/"native-protocol")
        protocol = NativeLmeProtocol(output/"native-protocol")
        settings = entrypoint_settings(read_json(config), "functional")
        write_json(output/"configuration.json", read_json(config))
        private = output/"offline-input"
        private.mkdir()
        files = [(snapshot/"questions.jsonl", "questions.jsonl"),
                 (snapshot/"haystacks/lme_v2_small.json", "haystacks.json"),
                 (snapshot/"trajectories.jsonl", "trajectories.jsonl")]
        if continue_from is not None:
            files = [(continue_from/"offline-input"/name, name) for _, name in files]
        for source, name in files:
            shutil.copyfile(source, private/name)
            if source.read_bytes() != (private/name).read_bytes():
                raise ValueError("Evaluation input changed while making its literal snapshot")
        questions = read_jsonl(private/"questions.jsonl")
        haystacks = read_json(private/"haystacks.json")
        ids = [q["id"] for q in questions]
        if not ids or len(set(ids)) != len(ids) or set(haystacks) != set(ids):
            raise ValueError("Retain every declared question and its native haystack")
        driver.update(planned_positions=len(questions),
            original_ledger=settings["budget_path"],
            known_exposure="Disclosed regression;not new holdout",
            reference_access="Raw input snapshot retained offline; answer/eval fields are not read "
                             "by prediction code or passed to memory/Reader.")
        pools: dict[tuple[str, ...], str] = {}
        pool_counts: Counter[str] = Counter()
        for index, row in enumerate(questions):
            pool = tuple(haystacks[row["id"]])
            pools.setdefault(pool, f"pool-{len(pools):04d}")
            case: dict[str, Any] = {"row": index, "question_id": row["id"], "domain": row["domain"],
                "pool": pools[pool], "pool_index": pool_counts[pools[pool]],
                "owner_predictions": str(output.resolve()), "status": "NOT_RUN", "score": None}
            pool_counts[pools[pool]] += 1
            if parent is not None:
                prior = parent["cases"][index]
                if any(prior[k] != case[k] for k in (
                        "row", "question_id", "domain", "pool", "pool_index")):
                    raise ValueError("Continuation changed original question/pool order")
                if prior["status"] != "NOT_RUN":
                    case = copy.deepcopy(prior)
            driver["cases"].append(case)
        write_json(output/"cohort.json", {"cases": driver["cases"],
            "pools": [{"id": name, "trajectory_ids": list(pool)} for pool, name in pools.items()]})
        write_json(output/"driver.json", driver)
        trajectory_rows = read_jsonl(private/"trajectories.jsonl")
        trajectories = {t["id"]: t for t in trajectory_rows}
        if len(trajectories) != len(trajectory_rows) or not {
                identity for pool in pools for identity in pool} <= set(trajectories):
            raise ValueError("Native trajectory identities are duplicated or unavailable")
        capacity = capacity_factory(settings["capacity"])
        backends: dict[tuple[str, ...], LmeMemoryBackend] = {}
        models: dict[tuple[Any, ...], Any] = {}
        for row, case in zip(questions, driver["cases"], strict=True):
            if case["status"] != "NOT_RUN":
                continue
            driver["active_row"] = case["row"]
            case["status"] = "PREPARING_INPUT"
            write_json(output/"driver.json", driver)
            query, query_image = public_question(row, snapshot)
            case["status"] = "RETRIEVING"
            pool = tuple(haystacks[row["id"]])
            child_cpu = time.process_time()
            try:
                if pool not in backends:
                    memory = LmeMemoryBackend(output/"configuration.json", snapshot,
                        output/"memory"/pools[pool], source_version=source_version)
                    memory.models = models
                    previous = next((p/"memory"/pools[pool] for p in parents
                                     if (p/"memory"/pools[pool]/"template").is_dir()), None)
                    if previous is not None:
                        memory.reuse_closed_template(previous)
                    else:
                        for identity in pool:
                            memory.insert(trajectories[identity])
                    backends[pool] = memory
                memory = backends[pool]
                memory.queries = case["pool_index"]
                local_index = memory.queries
                runtime = memory.output/"cases"/f"{local_index:04d}"
                case["runtime"] = str(runtime.resolve())
                context = memory.query(query, query_image)
            finally:
                case["retrieval_cpu_seconds_nested"] = time.process_time()-child_cpu
                nested_cpu += case["retrieval_cpu_seconds_nested"]
            case["status"] = "READING"
            case["prediction_root"] = str((output/"predictions"/f"{case['row']:04d}").resolve())
            write_json(output/"driver.json", driver)
            child_cpu = time.process_time()
            try:
                prediction = predict_reader(
                    runtime, Path(case["prediction_root"]), protocol, capacity,
                    domain=row["domain"], query=query, query_image=query_image, context=context,
                    source_version=source_version, transport=transport)
            finally:
                case["prediction_cpu_seconds_nested"] = time.process_time()-child_cpu
                nested_cpu += case["prediction_cpu_seconds_nested"]
            case.update(status="COMPLETED", is_unknown=prediction["is_unknown"])
            write_json(output/"driver.json", driver)
            print({"completed": sum(c["status"] == "COMPLETED" for c in driver["cases"]),
                   "planned": len(questions)}, flush=True)
        driver["status"] = ("COMPLETED" if all(c["status"] == "COMPLETED" for c in driver["cases"])
                            else "COMPLETED_WITH_RETAINED_FAILURES")
    except BaseException as error:
        if "active_row" in driver:
            case = driver["cases"][driver["active_row"]]
            case.update(status="FAILED_"+case["status"],
                        error_type=type(error).__name__, error=str(error))
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time()-cpu
        torch = sys.modules.get("torch")
        driver["runtime"].update(torch_version=getattr(torch, "__version__", None),
            mha_fastpath_enabled=torch.backends.mha.get_fastpath_enabled() if torch else None)
        driver.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter()-started,
            orchestration_cpu_seconds=elapsed-nested_cpu, cpu_ledger_recorded=False,
            accounting="Whole-process CPU and per-case retrieval/prediction CPU are nested. "
                       "Exclusive orchestration excludes those regions. Backend/Reader components "
                       "retain their own measurements; local controller compute and HTTP usage "
                       "may already be in the original ledger. Never sum nested copies.")
        write_json(output/"driver.json", driver)
    return driver


def score_cohort(predictions: Path, output: Path, *, source_version: str,
                 transport: httpx.BaseTransport | None = None,
                 continue_from: Path | None = None) -> dict[str, Any]:
    """Read references only after the prediction phase is terminal; retain missing denominators."""
    generation = read_json(predictions/"driver.json")
    if generation["status"] not in {"COMPLETED", "COMPLETED_WITH_RETAINED_FAILURES", "FAILED"}:
        raise ValueError("Finish the prediction phase before opening references for scoring")
    parent = None
    if continue_from is not None:
        parent = read_json(continue_from/"driver.json")
        if (parent["status"] != "FAILED" or parent.get("schema") != "lme_scoring_cohort_v2"
                or Path(parent["predictions"]).resolve() != predictions.resolve()
                or parent["source_version"] != source_version
                or [c["question_id"] for c in parent["cases"]] !=
                    [c["question_id"] for c in generation["cases"]]):
            raise ValueError("Continue only failed scoring of the same frozen prediction cohort")
        if not any(c["status"] == "UNSCORED_COMPLETED" for c in parent["cases"]):
            raise ValueError("No unattempted scoring positions; failed Judges are not retried")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    nested_cpu = 0.0
    protocol = NativeLmeProtocol(predictions/"native-protocol")
    settings = entrypoint_settings(read_json(predictions/"configuration.json"), "functional")
    capacity = HostCapacity(settings["capacity"])
    questions = read_jsonl(predictions/"offline-input/questions.jsonl")
    if [q["id"] for q in questions] != [c["question_id"] for c in generation["cases"]]:
        raise ValueError("Prediction cohort and frozen offline references differ")
    cases = ([{"row": c["row"], "question_id": c["question_id"],
        "status": "UNSCORED_"+c["status"], "score": None} for c in generation["cases"]]
        if parent is None else copy.deepcopy(parent["cases"]))
    owners = prediction_roots(predictions)
    driver: dict[str, Any] = {"schema": "lme_scoring_cohort_v2",
        "status": "RUNNING", "pid": os.getpid(),
        "source_version": source_version,
        "predictions": str(predictions.resolve()), "generation_status": generation["status"],
        "runtime": {"python": sys.version, "transformers": transformers.__version__,
                    "interpreter": sys.executable},
        "cases": cases, "automatic_retry": False, "reader_regenerated": False,
        "continued_from": str(continue_from.resolve()) if continue_from is not None else None,
        "inherited_rows": [] if parent is None else
            [c["row"] for c in cases if c["status"] != "UNSCORED_COMPLETED"],
        "metric_scope": "Native answer metrics with local declared Reader/Judge; not official "
                        "model reproduction, source-fidelity certification or independent users."}
    write_json(output/"driver.json", driver)
    try:
        for prior, question, case in zip(generation["cases"], questions, cases, strict=True):
            if prior["status"] != "COMPLETED" or case["status"] != "UNSCORED_COMPLETED":
                continue
            driver["active_row"] = case["row"]
            owner = Path(prior.get("owner_predictions", predictions)).resolve()
            if owner not in owners:
                raise ValueError("Prediction owner is outside the declared continuation ancestry")
            expected = owner/"predictions"/f"{case['row']:04d}"
            if Path(prior["prediction_root"]).resolve() != expected.resolve():
                raise ValueError("A prediction path does not match its declared cohort row")
            child_cpu = time.process_time()
            case["score_root"] = str((output/f"case-{case['row']:04d}").resolve())
            try:
                score = score_reader(expected, output/f"case-{case['row']:04d}",
                    question, protocol, capacity, source_version=source_version,
                    transport=transport)
            finally:
                case["scoring_cpu_seconds_nested"] = time.process_time()-child_cpu
                nested_cpu += case["scoring_cpu_seconds_nested"]
            case.update({k: score[k] for k in ("status", "score", "score_bool", "is_unknown",
                "is_abstention_problem", "category", "eval_name", "response_parsed_boxed")})
            write_json(output/"driver.json", driver)
        driver["status"] = ("COMPLETED" if all(c["score"] is not None for c in cases)
                            else "COMPLETED_WITH_UNSCORED_POSITIONS")
    except BaseException as error:
        if "active_row" in driver:
            case = cases[driver["active_row"]]
            case.update(status="FAILED_SCORING", error_type=type(error).__name__, error=str(error))
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time()-cpu
        driver.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter()-started,
            orchestration_cpu_seconds=elapsed-nested_cpu, cpu_ledger_recorded=False,
            status_counts=dict(Counter(c["status"] for c in cases)),
            accounting="Exclusive orchestration excludes nested scorer stages. Exact rules need "
                       "no Judge; actual Judge requests retain original ledger accounting.")
        write_json(output/"metrics.json", protocol.aggregate(cases))
        write_json(output/"driver.json", driver)
    return driver
