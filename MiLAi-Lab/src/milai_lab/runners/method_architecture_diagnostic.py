"""A common model-formed plain seed, one update, and the existing shared Reader.

The seed is paid for once and reported separately. A candidate clone changes the
representation tag/rendering only; no graph, corrected fact or gold enters its
initial state. Independent-formation experiments remain separate.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from langgraph.store.sqlite import SqliteStore as Store

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import ObservedSession, halumem_session, halumem_users
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.edit_units import render_state
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def promote_plain_version(version: dict[str, Any]) -> dict[str, Any]:
    """Lossless entry into conditioned operators, without inventing any relation."""
    result = copy.deepcopy(version)
    state = result["edit_state"]
    if state["representation"] != "plain_v1" or state["relations"] or state.get("support_groups"):
        raise ValueError("The controlled seed must be an actual plain-proposition state")
    state["representation"] = "conditioned_v1"
    result["content"] = render_state(state)
    return result


def promote_plain_bank(service: MemoryService) -> list[dict[str, Any]]:
    """Transform a diagnostic clone, including its prefix history; never the seed.

    Unit IDs, literal text, attribution, evidence, clocks, revision numbers and
    original formation identities stay exact. The report retains every original
    version alongside its projection; this is not a new observed memory event.
    """
    report = []
    for row in service.records():
        stored = service.store.get(service.namespace, row["id"])
        assert stored is not None
        raw = copy.deepcopy(stored.value)
        metadata = raw["_v13_1"]
        original = copy.deepcopy(metadata["history"])
        metadata["history"] = [promote_plain_version(version) for version in original]
        metadata["current"] = promote_plain_version(metadata["current"])
        raw["content"] = metadata["current"]["content"]
        service.store.put(service.namespace, row["id"], raw, index=False)
        report.append({"record_id": row["id"], "actual_seed_versions": original,
                       "projected_versions": copy.deepcopy(metadata["history"]),
                       "changed_fields": ["edit_state.representation", "content"],
                       "new_relations": 0, "semantic_repair": False})
    return report


def diagnostic_costs(root: Path) -> dict[str, Any]:
    """Summarize original response receipts, not another accounting ledger."""
    stages: dict[str, Any] = {}
    responses = list((root / "http").rglob("response.json"))
    for path in responses:
        parts = path.relative_to(root / "http").parts
        stage = ("embedding" if parts[0] == "embedding" else
                 "policy_selection" if parts[0] == "maintenance-policy" else
                 "impact" if parts[0] == "maintenance" and "impact" in parts else
                 "maintenance" if parts[0] == "maintenance" else
                 "evidence_selection" if parts[0] == "dependency-selection" else "reader")
        group = stages.setdefault(stage, {"responses": 0, "known_tokens": 0,
                                          "unknown_usage_responses": 0})
        usage = read_json(path).get("usage") or {}
        group["responses"] += 1
        if isinstance(usage.get("total_tokens"), int):
            group["known_tokens"] += usage["total_tokens"]
        else:
            group["unknown_usage_responses"] += 1
    return {"stages": stages, "requests_without_response": [
        str(path.relative_to(root)) for path in (root / "http").rglob("request.json")
        if not path.with_name("response.json").exists()],
        "basis": "original receipt inventory; missing responses do not prove dispatch; "
                 "continuous ledger remains authoritative"}


def prepare_diagnostic(config: dict[str, Any], root: Path) -> dict[str, Any]:
    plain = read_json(Path(config["plain_config"]))["entrypoints"]["benchmark"]
    candidate = read_json(Path(config["candidate_config"]))["entrypoints"]["benchmark"]
    user = halumem_users(Path(config["sources"]), [config["owner"]])[0]
    shared_fields = ("budget_path", "model", "context_tokens", "tokenizer_path", "source_tokens",
                     "source_body_tokens", "calendar_context", "maintenance_recipe",
                     "source_top_k", "semantic_top_k", "embedding", "embedding_capacity",
                     "source_access", "source_granularity", "source_tokenization", "reader_target",
                     "evidence_policy", "retrieval_granularity", "memory_profile", "memory_ranking",
                     "reader_projection", "stage_enable_thinking")
    differences = [key for key in shared_fields if plain.get(key) != candidate.get(key)]
    if differences:
        raise ValueError(f"Paired conditions differ: {differences}")
    protocol: dict[str, Any] = {
        "status": "PREPARED_ZERO_MODEL", "config": config,
        "settings": {"plain": plain, "candidate": candidate},
        "observations": {name: asdict(halumem_session(
            config["owner"], ordinal, user["sessions"][ordinal]))
                         for name, ordinal in (("seed", config["seed_session"]),
                                               ("update", config["update_session"]))},
        "queries": config["queries"],
        "before_condition": "common B1 model state; candidate tag-only promotion, no oracle graph",
        "scope": "one controlled update; not an independent-formation system result",
        "read_usage_updates": False,
        "cost_policy": "shared seed actual cost once; each arm's incremental costs separately",
    }
    # Serialize tuples before comparing a previously prepared JSON declaration.
    protocol = json.loads(json.dumps(protocol, ensure_ascii=False))
    path = root / "prepared.json"
    if path.exists() and read_json(path) != protocol:
        raise ValueError("Prepared diagnostic changed; use a new output root")
    write_json(path, protocol)
    return protocol


def _settings(protocol: dict[str, Any], role: str) -> dict[str, Any]:
    settings: dict[str, Any] = copy.deepcopy(
        protocol["settings"]["plain" if role == "seed" else role])
    identity = protocol["config"]["name"] + "-" + role
    settings.update(experiment_name=identity, config_version=identity, read_usage_updates=False)
    return settings


def _service(run: BenchmarkRun, store: Store, owner: str, bank: Path) -> MemoryService:
    return MemoryService(
        store, ("edit", "method-architecture-diagnostic", owner), owner, bank / "memory.lock",
        functional_contract="functional_v1", memory_profile=run.settings["memory_profile"],
        memory_ranking=run.settings.get("memory_ranking", "dense"),
        semantic_retriever=run._semantic_retriever())


def _copy_bank(source: Path, destination: Path) -> None:
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as copied:
            original.backup(copied)


def _prepare_arrival(protocol: dict[str, Any], root: Path) -> Path:
    """Capture the common update once so both arms get identical Source identities/clocks."""
    bank = root / "arrival"
    if (bank / "complete.json").exists():
        return bank / "memory.sqlite"
    bank.mkdir(exist_ok=True)
    started = time.perf_counter()
    if not (bank / "memory.sqlite").exists():
        _copy_bank(root / "seed/bank/memory.sqlite", bank / "memory.sqlite")
    owner = protocol["config"]["owner"]
    settings = protocol["settings"]["plain"]
    observed = ObservedSession(**protocol["observations"]["update"])
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("edit", "method-architecture-diagnostic", owner), owner, bank / "memory.lock",
            functional_contract="functional_v1", memory_profile=settings["memory_profile"])
        sources = []
        for index, turn in enumerate(observed.turns):
            capture = service.capture_user if turn["role"] == "user" else service.capture_assistant
            receipt = capture(observed.session_id, f"turn:{index}", turn["content"],
                              occurred_at=turn["timestamp"],
                              calendar_context=settings.get("calendar_context"))
            if not receipt["ok"]:
                raise ValueError("Common source capture did not complete")
            sources.append(service.source(receipt["source_ref"]))
    write_json(bank / "complete.json", {"sources": sources, "model_calls": 0,
                                        "wall_seconds": time.perf_counter() - started})
    return bank / "memory.sqlite"


def run_seed(
    protocol: dict[str, Any], root: Path, *, run_class: type[BenchmarkRun] = BenchmarkRun,
) -> dict[str, Any]:
    folder = root / "seed"
    result_path = folder / "result.json"
    if result_path.exists():
        return cast(dict[str, Any], read_json(result_path))
    if (folder / "bank/memory.sqlite").exists():
        raise ValueError("Unclosed seed bank; inspect original requests before continuing")
    started = time.perf_counter()
    run = run_class(_settings(protocol, "seed"), folder, phase="predict")
    try:
        bank = folder / "bank"
        bank.mkdir()
        observed = ObservedSession(**protocol["observations"]["seed"])
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = _service(run, store, protocol["config"]["owner"], bank)
            run.maintain_recipe(service, observed, "seed")
            records = service.records()
            result = {"status": "SEED_ATTEMPT_CLOSED", "actual_state": records,
                      "initial_state_empty": not records,
                      "maintenance": read_json(folder / "maintenance/seed/complete.json"),
                      "semantic_correctness": "unreviewed"}
    finally:
        run.close()
    result.update(wall_seconds=time.perf_counter() - started, costs=diagnostic_costs(folder))
    write_json(result_path, result)
    return result


def run_pair(
    protocol: dict[str, Any], root: Path, *, run_class: type[BenchmarkRun] = BenchmarkRun,
) -> dict[str, Any]:
    seed = read_json(root / "seed/result.json")
    arrival_bank = _prepare_arrival(protocol, root)
    results = {}
    for role in ("plain", "candidate"):
        folder = root / role
        path = folder / "result.json"
        if path.exists():
            results[role] = read_json(path)
            continue
        if (folder / "bank/memory.sqlite").exists():
            raise ValueError(f"Unclosed {role} bank; inspect original outcomes before continuing")
        started = time.perf_counter()
        run = run_class(_settings(protocol, role), folder, phase="predict")
        try:
            bank = folder / "bank"
            bank.mkdir()
            _copy_bank(arrival_bank, bank / "memory.sqlite")
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = _service(run, store, protocol["config"]["owner"], bank)
                original = service.records()
                if {row["id"]: row["value"] for row in original} != {
                    row["id"]: row["value"] for row in seed["actual_state"]
                }:
                    raise ValueError("The diagnostic clone differs from its actual model seed")
                projection = promote_plain_bank(service) if role == "candidate" else []
                before = service.records()
                write_json(folder / "before.json", {"records": before, "projection": projection})
                observed = ObservedSession(**protocol["observations"]["update"])
                run.maintain_recipe(service, observed, "update")
                after = service.records()
                write_json(folder / "after.json", after)
                answers = []
                for query in protocol["queries"]:
                    key = "questions/" + query["id"]
                    answer: dict[str, Any] = {"id": query["id"], "kind": query["kind"],
                                              "question": query["question"]}
                    try:
                        answer["hypothesis"] = run.answer(
                            service, query["question"], observed.date, key)
                    except ValueError as error:
                        failure = run._known_reader_failure(error, key)
                        if failure is None:
                            raise
                        answer.update(hypothesis=None, reader_failure=failure)
                    answers.append(answer)
                    write_json(folder / "answers.json", answers)
                maintenance = read_json(folder / "maintenance/update/complete.json")
                result = {"status": "DIAGNOSTIC_ATTEMPTS_CLOSED", "before": before, "after": after,
                          "answers": answers, "initial_state_empty": seed["initial_state_empty"],
                          "maintenance": maintenance,
                          "engineered_ok": (maintenance["status"] == "completed"
                                            and all(a["hypothesis"] is not None for a in answers)),
                          "state_correct": None,
                          "answer_correct": None, "source_faithful": None,
                          "assessment": "unreviewed; CLI completion is not semantic success"}
        finally:
            run.close()
        result.update(wall_seconds=time.perf_counter() - started, costs=diagnostic_costs(folder))
        write_json(path, result)
        results[role] = result
    summary = {"status": "PAIRED_DIAGNOSTIC_CLOSED", "arms": results,
               "shared_seed_costs": seed["costs"],
               "common_arrival": read_json(root / "arrival/complete.json"),
               "full_goal_complete": False, "independent_system_result": False}
    write_json(root / "summary.json", summary)
    return summary
