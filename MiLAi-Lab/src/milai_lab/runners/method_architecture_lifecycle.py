"""Measured maintenance allocation over one arrived stream and reusable actual states."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import ObservedSession, halumem_session, halumem_users
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import maintain_event, parse_object
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import _copy_bank, _service, diagnostic_costs

POLICIES = ("event", "explicit_change", "query_rebuild")
CHANGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"maintain": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["maintain", "reason"],
}


def prepare_lifecycle(config: dict[str, Any], root: Path) -> dict[str, Any]:
    settings = read_json(Path(config["base_config"]))["entrypoints"]["benchmark"]
    user = halumem_users(Path(config["sources"]), [config["owner"]])[0]
    protocol: dict[str, Any] = json.loads(json.dumps({
        "status": "PREPARED_ZERO_MODEL", "config": config, "settings": settings,
        "observations": [asdict(halumem_session(config["owner"], i, session))
                         for i, session in enumerate(user["sessions"])],
        "policies": list(POLICIES), "read_usage_updates": False,
        "arrival_policy": "capture every actual Source immediately, before scheduling maintenance",
        "explicit_change": "maintain the first arrival, then one metered decision per arrival",
        "query_rebuild": "fresh semantic state from the arrived prefix at the first query; "
                         "reuse that state for further queries until the next arrival",
        "query_reuse": "first k of the actual reads at each checkpoint; shared maintenance "
                       "charged once, not independent repeated formation",
        "policy_information": "arrived Sources and past actual state only; no future query or gold",
        "source_identity": "independent policy banks; same original bodies/report clocks, "
                           "actual capture clocks and Source IDs remain native",
        "unknown_retry": False,
    }, ensure_ascii=False))
    path = root / "prepared.json"
    if path.exists() and read_json(path) != protocol:
        raise ValueError("Prepared lifecycle changed; use another output root")
    write_json(path, protocol)
    return protocol


def capture_arrival(
    service: MemoryService, observed: ObservedSession, settings: dict[str, Any],
) -> list[str]:
    refs = []
    for i, turn in enumerate(observed.turns):
        capture = service.capture_user if turn["role"] == "user" else service.capture_assistant
        receipt = capture(observed.session_id, f"turn:{i}", turn["content"],
                          occurred_at=turn["timestamp"],
                          calendar_context=settings.get("calendar_context"))
        if not receipt["ok"]:
            raise ValueError("Original arrival capture did not complete")
        ref = receipt["source_ref"]
        refs.append(ref)
        if turn["role"] == "user":
            service.bind_public_turn(observed.session_id, f"turn:{i}", ref,
                                     config_version=settings["config_version"], phase="start")
    return refs


def change_request(
    observed: ObservedSession, records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    state = [{"record_id": row["id"], "revision": row["value"]["revision"],
              "scope": row["value"]["scope"], "edit_state": row["value"].get("edit_state")}
             for row in records]
    return [{"role": "system", "content": (
        "Decide whether this newly arrived event explicitly adds, changes, corrects or "
        "withdraws a durable assertion, rule or intention relative to the saved state. "
        "New uncertain plans remain uncertain but may need storage. Mere acknowledgments "
        "or conversational filler need no semantic maintenance. This decision only schedules "
        "the ordinary editor; it neither edits memory nor certifies facts. Use arrived "
        "content and the actual saved state, without anticipating future questions. "
        "Return the supplied schema with a short reason.")},
        {"role": "user", "content": json.dumps({"arrival": asdict(observed),
            "saved_state": state, "response_schema": CHANGE_SCHEMA}, ensure_ascii=False)}]


def rebuild_prefix(
    run: BenchmarkRun, service: MemoryService, refs: list[str], date: str, key: str,
) -> dict[str, Any]:
    """Use the existing editor on the actual arrived prefix in a source-only clone."""
    method = EditMemory(service, "M", interface_version="I2",
        features=EditFeatures.from_settings(run.settings["edit_features"]),
        maintenance_mode=run.settings["maintenance_mode"])
    sources = [service.source(ref) for ref in refs]
    anchor = next(source for source in reversed(sources) if source and source["role"] == "user")
    session = anchor["session"]
    service.bind_public_turn(session, anchor["capture_key"], anchor["event_id"],
                             config_version=run.settings["config_version"], phase="start")
    current = [source["event_id"] for source in sources if source and source["session"] == session]
    previous = [ref for ref in refs if ref not in current]
    service.bind_source_boundary(session, key, current)
    delivery = method.prepare(current, "", selected_records=[], redelivered_ranges=[])
    history = method.prepare(previous, "", selected_records=[], redelivered_ranges=[])

    def deliver_history(located: dict[str, Any]) -> dict[str, Any]:
        # Historical originals were read from this actual source-only prefix.
        # They are redelivered evidence, not new events or synthetic records.
        return {**located, "redelivered_sources": history["sources"],
                "source_attributes": [*delivery.get("source_attributes", []),
                                      *history.get("source_attributes", [])]}

    def reconstruction_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        messages = copy.deepcopy(messages)
        messages[0]["content"] = (
            "For this call, reconstruct the current semantic state from the whole arrived "
            "Source prefix. There is no prior semantic state. Both current evidence and "
            "redelivered_support are formation input; interpret their original report clocks "
            "and corrections in chronology. Earlier reports have not happened again. "
            "The latest event may only acknowledge an earlier statement; that does not "
            "remove the need to reconstruct the earlier supported state. No question or "
            "reference answer is available. Retain the following editor's source, unit and "
            "output contracts.\n" + messages[0]["content"])
        return messages

    calls = 0

    def call(stage: str, messages: list[dict[str, str]], schema: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls > run.client.config.max_calls:
            raise ValueError("Reconstruction exceeded the existing maintenance call allowance")
        messages = reconstruction_messages(messages)
        stage_name, _, work = stage.partition(":")
        suffix = stage_name + ("/work-" + work.rsplit(":", 1)[-1] if work else "")
        raw = run.call(f"maintenance/{key}/{suffix}", messages, structured=True,
            response_format={"type": "json_schema", "json_schema": {
                "name": "milai_" + stage_name, "schema": schema}},
            enable_thinking=run.stage_thinking(stage_name))
        return parse_object(raw, reject_duplicate_keys=True)

    result = maintain_event(method, delivery, session=session, request_id=key, date=date,
        recipe="single_pass", memory_view_mode="staged", model_call=call,
        selected_record_ids=[], retrieval_limit=run.settings["retrieval_limit"], fit=run._fits,
        stage_fit=lambda stage, messages: run._fits(
            reconstruction_messages(messages), enable_thinking=run.stage_thinking(stage)),
        prepare_delivery=deliver_history)
    write_json(run.root / "maintenance" / key / "complete.json", result)
    return result


def _totals(root: Path) -> dict[str, int]:
    stages = diagnostic_costs(root)["stages"]
    return {"generation_known_tokens": sum(row["known_tokens"] for key, row in stages.items()
                                     if key != "embedding"),
            "generation_requests": sum(row["responses"] for key, row in stages.items()
                                       if key != "embedding"),
            "embedding_known_tokens": stages.get("embedding", {}).get("known_tokens", 0),
            "unknown_usage_responses": sum(row["unknown_usage_responses"]
                                           for row in stages.values())}


def _read_checkpoint(
    run: BenchmarkRun, service: MemoryService, protocol: dict[str, Any], ordinal: int,
    observed: ObservedSession,
) -> dict[str, Any]:
    before = service.records()
    reads = []
    for index, query in enumerate(protocol["config"]["queries"][:max(
            protocol["config"]["reuse_counts"])]):
        start = _totals(run.root)
        started = time.perf_counter()
        key = f"questions/prefix-{ordinal}/reuse-{index}"
        result = {"index": index, "id": query["id"], "question": query["question"]}
        try:
            result["hypothesis"] = run.answer(service, query["question"], observed.date, key)
        except ValueError as error:
            failure = run._known_reader_failure(error, key)
            if failure is None:
                raise
            result.update(hypothesis=None, reader_failure=failure)
        end = _totals(run.root)
        result.update(costs={k: end[k] - start[k] for k in start},
                      wall_seconds=time.perf_counter() - started)
        reads.append(result)
        write_json(run.root / f"queries/prefix-{ordinal}.json", reads)
    return {"session": ordinal, "state": before, "reads": reads,
            "record_values_unchanged": before == service.records()}


def lifecycle_curves(result: dict[str, Any], reuse_counts: list[int]) -> dict[str, Any]:
    all_reads = [read for checkpoint in result["checkpoints"] for read in checkpoint["reads"]]
    total = result["total_costs"]
    maintenance = {key: total[key] - sum(row["costs"][key] for row in all_reads) for key in total}
    curves = {}
    for count in reuse_counts:
        selected = [read for checkpoint in result["checkpoints"]
                    for read in checkpoint["reads"][:count]]
        read_cost = {key: sum(row["costs"][key] for row in selected) for key in total}
        curves[str(count)] = {"queries_per_checkpoint": count, "query_opportunities": len(selected),
            "complete_answers": sum(row["hypothesis"] is not None for row in selected),
            "maintenance": maintenance, "reading": read_cost,
            "lifecycle": {key: maintenance[key] + read_cost[key] for key in total},
            "quality": None}
    return curves


def run_policy(
    protocol: dict[str, Any], root: Path, policy: str, *,
    run_class: type[BenchmarkRun] = BenchmarkRun,
) -> dict[str, Any]:
    if policy not in POLICIES:
        raise ValueError("Unknown declared maintenance policy")
    folder = root / policy
    result_path = folder / "result.json"
    if result_path.exists():
        return dict(read_json(result_path))
    if (folder / "bank/memory.sqlite").exists():
        raise ValueError("Unclosed lifecycle policy; inspect original attempts before continuing")
    settings = copy.deepcopy(protocol["settings"])
    identity = protocol["config"]["name"] + "-" + policy
    settings.update(arm="M", experiment_name=identity, config_version=identity,
                    read_usage_updates=False)
    run = run_class(settings, folder, phase="predict")
    started = time.perf_counter()
    owner = protocol["config"]["owner"]
    bank = folder / "bank"
    bank.mkdir()
    arrivals, checkpoints, refs = [], [], []
    try:
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = _service(run, store, owner, bank)
            for ordinal, raw in enumerate(protocol["observations"]):
                observed = ObservedSession(**raw)
                arrived = capture_arrival(service, observed, settings)
                refs.extend(arrived)
                decision: dict[str, Any] = {"maintain": policy == "event",
                    "reason": "per-event allocation" if policy == "event" else "deferred to query"}
                if policy == "explicit_change":
                    if ordinal == 0:
                        decision = {"maintain": True, "reason": "initial arrival formation"}
                    else:
                        messages = change_request(observed, service.records())
                        decision = parse_object(run.call(f"maintenance-policy/event-{ordinal}",
                            messages, structured=True, response_format={"type": "json_schema",
                            "json_schema": {"name": "maintenance_allocation",
                                            "schema": CHANGE_SCHEMA}}))
                        Draft202012Validator(CHANGE_SCHEMA).validate(decision)
                if decision["maintain"]:
                    run.maintain_recipe(service, observed, f"event-{ordinal}")
                arrivals.append({"session": ordinal, "source_refs": arrived,
                    "decision": decision, "state": service.records()})
                write_json(folder / "arrivals.json", arrivals)
                if ordinal not in protocol["config"]["query_after_sessions"]:
                    continue
                if policy == "query_rebuild":
                    rebuilt = folder / "rebuilds" / f"prefix-{ordinal}"
                    rebuilt.mkdir(parents=True)
                    _copy_bank(bank / "memory.sqlite", rebuilt / "memory.sqlite")
                    with SqliteStore.from_conn_string(str(rebuilt / "memory.sqlite")) as copied:
                        active = _service(run, copied, owner, rebuilt)
                        before = active.records()
                        receipt = rebuild_prefix(run, active, refs, observed.date,
                                                 f"rebuild-prefix-{ordinal}")
                        checkpoint = _read_checkpoint(run, active, protocol, ordinal, observed)
                        checkpoint.update(rebuild_before=before, rebuild_receipt=receipt)
                else:
                    checkpoint = _read_checkpoint(run, service, protocol, ordinal, observed)
                checkpoints.append(checkpoint)
                write_json(folder / "checkpoints.json", checkpoints)
            final_source_count = len(service.sources())
    finally:
        run.close()
    result = {"status": "POLICY_ATTEMPTS_CLOSED", "policy": policy,
        "arrivals": arrivals, "checkpoints": checkpoints, "captured_sources": final_source_count,
        "wall_seconds": time.perf_counter() - started, "costs": diagnostic_costs(folder),
        "total_costs": _totals(folder), "semantic_correctness": None}
    result["reuse_curves"] = lifecycle_curves(result, protocol["config"]["reuse_counts"])
    write_json(result_path, result)
    return result


def run_lifecycle(
    protocol: dict[str, Any], root: Path, *, run_class: type[BenchmarkRun] = BenchmarkRun,
) -> dict[str, Any]:
    result = {"status": "LIFECYCLE_ATTEMPTS_CLOSED", "policies": {
        policy: run_policy(protocol, root, policy, run_class=run_class) for policy in POLICIES},
        "assessment": "unreviewed; reuse curves allocate actual work, not a deployment claim"}
    write_json(root / "summary.json", result)
    return result
