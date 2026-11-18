"""Prepare, execute and score durable same-before Reader interventions."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import asdict
from typing import Any

import httpx

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_store import connect, dumps, packed, unpack
from milai_lab.harness.contextual_artifacts import BudgetExceeded, http_budget_scope
from milai_lab.methods.dataset_control_states import CONTINUATION, task_annotation
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution
from milai_lab.methods.dataset_reader import (
    ENABLE_THINKING,
    OUTPUT_TOKENS,
    READER_PROTOCOL,
    TEMPERATURE,
    DatasetReader,
    reader_task,
)
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    run_memory_control,
)
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.scorers.memory_control_native import (
    NATIVE_SCORER_SOURCES,
    SCORER_VERSION,
    score_answer,
)

DEFAULT_STATE_QUOTAS = {MUSIQUE: 16_000, QASPER: 5_000, PERSONA: 3_000}
STATE_SUBSAMPLING = (
    ("random", 0.40),
    ("precision", 0.25),
    ("stop_budget", 0.20),
    ("explore", 0.15),
)
METERING = "native_vllm_shared_ledger_v1"
Chooser = Callable[[MemoryControlState, list[MemoryAction]], str]


def comparison_protocol(dataset: MemoryControlDataset) -> dict[str, Any]:
    assert dataset.host is not None and dataset.revision is not None
    return {
        "reader_protocol": READER_PROTOCOL,
        "model_revision": dataset.host.settings["host"]["model"],
        "reader_config": str(dataset.host.config_path),
        "config_version": dataset.host.settings.get("config_version"),
        "tokenizer": dataset.tokenizers["reader"],
        "temperature": TEMPERATURE,
        "enable_thinking": ENABLE_THINKING,
        "output_tokens": OUTPUT_TOKENS,
        "option_seed": dataset.revision["option_seed"],
        "provider_seed": "wire_seed_recorded",
        "continuation": CONTINUATION,
        "delivery": dataset.revision["delivery_protocol"],
        "observation": dataset.observation_protocol,
        "scorer": SCORER_VERSION,
        "native_reference_sources": NATIVE_SCORER_SOURCES,
    }


def group_round_robin(
    rows: list[tuple[int, str, set[str]]],
    rng: random.Random,
) -> Iterator[tuple[int, set[str]]]:
    groups: dict[str, list[tuple[int, set[str]]]] = defaultdict(list)
    for state_id, group, strata in rows:
        groups[group].append((state_id, strata))
    ring = list(groups.values())
    for queue in ring:
        rng.shuffle(queue)
    rng.shuffle(ring)
    rotation = deque(ring)
    while rotation:
        items = rotation.popleft()
        yield items.pop()
        if items:
            rotation.append(items)


def select_states(
    db: sqlite3.Connection,
    used: set[int],
    limit: int,
    seed: int,
) -> list[tuple[int, str]]:
    if limit <= 0:
        raise ValueError("State batch size must be positive")
    prior = Counter(
        row["dataset"]
        for sid in used
        if (
            row := db.execute(
                """
        SELECT t.dataset FROM states s JOIN experiment_tasks t ON t.id=s.task_id WHERE s.id=?
    """,
                (sid,),
            ).fetchone()
        )
        is not None
    )
    pools = defaultdict(list)
    primary = 2048
    for row in db.execute("""
        SELECT s.id, s.recipe, t.dataset, t.native_group, s.actions, v.material_budget,
               v.action_feasibility, w.evidence, v.diagnostics
        FROM experiment_tasks t JOIN states s ON t.id=s.task_id
        JOIN state_variants v ON s.id=v.state_id
        JOIN weak_labels w ON s.id=w.state_id
        WHERE t.experiment_role='train' AND s.sampling<>'policy_reached' ORDER BY s.id
    """):
        if row["id"] in used:
            continue
        menu = unpack(row["actions"])
        fits = unpack(row["action_feasibility"])
        feasible = {a["id"] for a, (f, _) in zip(menu, fits, strict=True) if f is True}
        axes = {"random"}
        if any(
            f"read_{a['parameters'].get('index')}" in feasible
            and a["id"] in feasible
            and a["parameters"].get("expand_context")
            for a in menu
        ):
            axes.add("precision")
        diagnostics = unpack(row["diagnostics"])
        if (
            row["recipe"] != "initial_candidates"
            or row["material_budget"] < primary
            or diagnostics.get("feasibility/material_budget_exhausted", 0)
        ):
            axes.add("stop_budget")
        if not any(x is not None for x in unpack(row["evidence"])) or (
            diagnostics["candidate_complete_set_denominator"]
            and not diagnostics["candidate_complete_sets"]
        ):
            axes.add("explore")
        pools[row["dataset"]].append((row["id"], row["native_group"], axes))
    rng = random.Random(seed + len(used))  # noqa: S311 -- repeatable sampling
    selected: list[tuple[int, str]] = []
    total = sum(DEFAULT_STATE_QUOTAS.values())
    quota = {
        source: min(max(0, target - prior[source]), round(limit * target / total))
        for source, target in DEFAULT_STATE_QUOTAS.items()
    }
    if sum(quota.values()) < limit and (s := max(quota, key=quota.__getitem__)):
        quota[s] = min(DEFAULT_STATE_QUOTAS[s] - prior[s], quota[s] + limit - sum(quota.values()))
    for source, rows in sorted(pools.items()):
        group_order = list(group_round_robin(rows, rng))
        count = max(0, quota[source])
        selected_source: dict[int, str] = {}
        for stratum, fraction in STATE_SUBSAMPLING:
            target = min(count - len(selected_source), round(count * fraction))
            candidates = (
                (sid, labels)
                for sid, labels in group_order
                if sid not in selected_source and stratum in labels
            )
            for _ in range(target):
                entry = next(candidates, None)
                if entry is None:
                    break
                selected_source[entry[0]] = stratum
        for sid, _ in group_order:
            if len(selected_source) >= count:
                break
            selected_source.setdefault(sid, "unfilled_stratum_random")
        selected.extend(selected_source.items())
    rng.shuffle(selected)
    return selected


def choose_actions(
    session: CorpusExecution,
    actions: list[MemoryAction],
    suggestions: list[Chooser],
    rng: random.Random,
) -> list[str]:
    viable = session.feasible_menu(actions)
    bounds = {a.id: a for a in viable}
    reads = [a for a in viable if a.kind == "READ"]
    chosen = dict.fromkeys(["handoff", *(policy(session.state, viable) for policy in suggestions)])
    if reads:
        chosen.setdefault(reads[0].id)
    if len(chosen) < 3 and reads:
        chosen.setdefault(rng.choice(reads).id)
    context_pairs = [
        (a.id, f"read_{a.parameters['index']}")
        for a in reads
        if a.parameters.get("expand_context") and f"read_{a.parameters['index']}" in bounds
    ]
    for expanded, focus in sorted(context_pairs, key=lambda p: not bool(chosen.keys() & set(p))):
        if len(chosen.keys() | {expanded, focus}) <= 5:
            chosen.setdefault(focus)
            chosen.setdefault(expanded)
            break
    unused = [a.id for a in reads if a.id not in chosen]
    if unused and len(chosen) < 5:
        chosen[rng.choice(unused)] = None
    if not chosen.keys() <= bounds.keys():
        raise ValueError("A proposal chose an unavailable action")
    return list(chosen)


def material_difference(
    session: CorpusExecution,
    before: dict[int, int],
    after: dict[int, int],
) -> dict[str, Any]:
    pool = session.pool
    old = [piece for vid in before.values() for piece in pool.views[vid].ranges]
    new = [piece for vid in after.values() for piece in pool.views[vid].ranges]

    def records(ranges: list[tuple[int, int, int]]) -> list[dict[str, Any]]:
        return [
            {"source_ref": pool.ref(oid), "source_revision": 1, "start": a, "end": b}
            for oid, a, b in ranges
        ]

    from milai_lab.memory.reader_projection import merge_source_ranges

    prior = merge_source_ranges(records(old))
    current = merge_source_ranges(records(new))
    added: list[dict[str, Any]] = []
    for span in current:
        remaining = [(span["start"], span["end"])]
        for other in prior:
            if span["source_ref"] != other["source_ref"]:
                continue
            updated = []
            for a, b in remaining:
                if other["end"] <= a or other["start"] >= b:
                    updated.append((a, b))
                else:
                    if a < other["start"]:
                        updated.append((a, other["start"]))
                    if b > other["end"]:
                        updated.append((other["end"], b))
            remaining = updated
        added.extend({**span, "start": a, "end": b} for a, b in remaining)
    return {
        "new_source_ranges": added,
        "replaced_source_ranges": [span for span in prior if span not in current],
    }


def prepare_one(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    state_id: int,
    action_id: str,
    baseline: dict[str, Any],
    original: CorpusExecution,
    seed: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    replay_started = time.perf_counter()
    row, session, actions = dataset.replay(db, state_id, original.pool)
    session.shared_preflight = original.shared_preflight
    feasible = session.feasible_menu(actions)
    if session.online(feasible) != baseline:
        raise ValueError("Before observations differ across paired branches")
    bound = next(a for a in actions if a.id == action_id)
    costs = {"prefix_replay_wall_ms": (time.perf_counter() - replay_started) * 1000}
    if bound not in feasible:
        return (
            "action_failed",
            {"bound": asdict(bound), "reason": session.feasibility(bound)[1]},
            costs,
        )
    opened_before = dict(session.opened)
    start = time.perf_counter()
    decision = run_memory_control(
        session.state,
        FixedContextMemoryPolicy(4),
        session,
        max_steps=row["control_steps"],
        start_step=len(session.prefix),
        intervention=FirstActionIntervention(bound, 2),
    )
    trace = decision["trace"]
    first = trace[0]
    after = trace[1]["before"] if len(trace) > 1 else decision["state"]
    first_pack = controlled_reader_packet(after["visible_evidence"], "policy_handoff")
    final_pack = session.pool.normalized_delivery(session.ops.opened)
    plan = session.plan_packet(final_pack.evidence)
    new_costs: dict[str, Any] = {
        **costs,
        "first_action_wall_ms": first.get("operation_wall_seconds", 0) * 1000,
        "continuation_wall_ms": sum(
            (event.get("operation_wall_seconds", 0) + event["control_wall_seconds"]) * 1000
            for event in trace[1:]
        ),
        "preflight_wall_ms": session.preflight_wall_ms,
        "local_branch_wall_ms": (time.perf_counter() - start) * 1000,
        "reader_material_tokens": plan.material_tokens,
        "navigation_tokens": sum(
            item.get("navigation_excerpt", {}).get("encoder_tokens", 0)
            for item in baseline["observation"]["pending_candidates"]
        ),
        "navigation_wall_ms": 0.0,
        "controller_wall_ms": sum(event["control_wall_seconds"] * 1000 for event in trace),
        "unique_source_chars": final_pack.unique_source_chars,
        "overlap_before_normalization": final_pack.overlap_before_normalization,
    }
    first_ok = first.get("result", {}).get("ok", bound.kind == "HANDOFF")
    wire = {**plan.wire, "seed": seed} if plan.wire else None
    data = {
        "bound": asdict(bound),
        "next_state": after,
        "terminal_state": decision["state"],
        "first_step_material": first_pack,
        "delivered_material": plan.packet,
        "reader_wire": wire,
        "capacity": plan.capacity,
        "source_aliases": final_pack.source_aliases,
        "delta": material_difference(session, opened_before, session.opened),
        "termination": decision["reason"],
        "trace": [
            {k: v for k, v in event.items() if k not in {"before", "actions"}} for event in trace
        ],
        "reason": plan.failure_reason or (first.get("result") or {}).get("status"),
    }
    return ("prepared" if first_ok and plan.feasible is True else "action_failed", data, new_costs)


def prepare_outcomes(
    dataset: MemoryControlDataset,
    run_id: str,
    *,
    limit: int,
    state_ids: list[int],
    explicit_actions: list[str],
    seed: int,
    suggestions: list[tuple[str, Chooser]],
    policy_pool: str | None = None,
) -> dict[str, Any]:
    if dataset.host is None or dataset.revision is None:
        raise ValueError("Use the revised dataset for actual Reader outcomes")
    declaration = {
        "role": "train",
        "comparison_protocol": comparison_protocol(dataset),
        "observation_protocol": dataset.observation_protocol,
        "selection_seed": seed,
        "dataset_run_id": dataset.run_id,
        "sealed": False,
        "recommendations": [name for name, _ in suggestions],
        "sample_kind": "explicit_diagnostic" if state_ids else "policy" if policy_pool else "core",
        "policy_pool": policy_pool,
    }
    with closing(connect(dataset.path, writable=True)) as db:
        with db:
            previous = db.execute(
                "SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if previous is None:
                db.execute("INSERT INTO outcome_runs VALUES (?,?)", (run_id, dumps(declaration)))
            elif json.loads(previous[0]) != declaration:
                raise ValueError(
                    "Outcome selection and Reader protocol are immutable within each run"
                )
        used = {
            sid
            for (sid,) in db.execute(
                "SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=?", (run_id,)
            )
        }
        if policy_pool:
            pool_ids = [
                (sid, source)
                for sid, source in db.execute(
                    """
                SELECT state_id,source_policy FROM policy_state_visits WHERE run_id=? ORDER BY 1
            """,
                    (policy_pool,),
                )
                if sid not in used
            ]
            selected = pool_ids[:limit]
        elif state_ids:
            selected = [
                (sid, "caller_bound") for sid in dict.fromkeys(state_ids) if sid not in used
            ]
        else:
            selected = select_states(db, used, limit, seed)
        rng = random.Random(seed + len(used))  # noqa: S311 -- declared branch order
        repeats = set(rng.sample([sid for sid, _ in selected], round(0.1 * len(selected))))
        statuses: Counter[str] = Counter()
        for sid, stratum in selected:
            with closing(connect(dataset.path)) as db_read:
                state, session, actions = dataset.replay(db_read, sid)
                if state["experiment_role"] != "train":
                    raise ValueError("Core outcome preparation permits only TRAIN groups")
                session.shared_preflight = {}
                baseline = session.online(session.feasible_menu(actions))
                branches = explicit_actions or choose_actions(
                    session, actions, [choose for _, choose in suggestions], rng
                )
                if not set(branches) <= {a.id for a in actions} or len(set(branches)) != len(
                    branches
                ):
                    raise ValueError("Outcome action IDs must be unique actual bindings")
                built = []
                for repeat in range(2 if sid in repeats else 1):
                    ordered = list(branches)
                    rng.shuffle(ordered)
                    repeat_seed = (seed + sid * 31 + repeat) % (2**31 - 1)
                    for action in ordered:
                        status, data, costs = prepare_one(
                            dataset, db_read, sid, action, baseline, session, repeat_seed
                        )
                        stages = {
                            "reader_wire": data.get("reader_wire"),
                            "capacity": data.get("capacity"),
                            "reason": data.get("reason"),
                            "source_aliases": data.get("source_aliases"),
                            "delta": data.get("delta"),
                            "control_trace": data.get("trace"),
                        }
                        built.append(
                            (
                                sid,
                                action,
                                run_id,
                                repeat,
                                packed(data["bound"]),
                                stratum,
                                repeat_seed,
                                READER_PROTOCOL,
                                status,
                                status,
                                packed(data.get("next_state")),
                                packed(data.get("terminal_state")),
                                packed(data.get("first_step_material")),
                                packed(data.get("delivered_material")),
                                packed(stages),
                                packed(costs),
                            )
                        )
                        statuses[status] += 1
            with db:
                db.executemany(
                    """
                    INSERT INTO action_outcomes (
                        state_id,action_id,run_id,repeat_index,bound_action,sampling_origin,
                        branch_seed,reader_protocol,execution_status,action_status,next_state,
                        terminal_state,first_step_material,delivered_material,task_result,costs
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    built,
                )
        return {
            "run_id": run_id,
            "states": len(selected),
            "repeated_states": len(repeats),
            "outcomes_by_status": dict(statuses),
            "reader_requests": 0,
            "comparison_protocol": declaration["comparison_protocol"],
        }


def request_reader(
    client: VLLMClient,
    host: DatasetReader,
    wire: dict[str, Any],
    capacity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    event: dict[str, Any] = {}
    sent = False
    started = time.perf_counter()

    def record(item: dict[str, Any]) -> None:
        nonlocal sent
        if item["event"] == "vllm_request":
            sent |= item.get("request_sent", False)
        if item["event"] in {"vllm_response", "vllm_error"}:
            event.update(
                {
                    k: item[k]
                    for k in (
                        "http_status",
                        "wall_seconds",
                        "usage",
                        "capacity_comparison",
                        "usage_confirmed",
                    )
                    if k in item
                }
            )

    try:
        response = client.native_post("chat/completions", wire, on_event=record)
    except (httpx.HTTPError, CapacityExceeded, ValueError) as exc:
        return (
            {"status": "reader_error", "error_type": type(exc).__name__, "receipt": event},
            {
                "reader_request_attempted": sent,
                "reader_wall_ms": (time.perf_counter() - started) * 1000,
                "reader_client_wall_ms": (time.perf_counter() - started) * 1000,
            },
        )
    usage = response.get("usage") or {}
    first = (response.get("choices") or [{}])[0]
    msg = first.get("message") or {}
    content = msg.get("content")
    result = {"status": "reader_completed", "response": response, "receipt": event}
    if "message" not in first:
        result.update(status="reader_error", error_type="response_missing_choice")
    cost = {
        "reader_request_attempted": sent,
        "reader_wall_ms": event.get("wall_seconds", time.perf_counter() - started) * 1000,
        "reader_client_wall_ms": (time.perf_counter() - started) * 1000,
        "reader_input_tokens": (
            usage["prompt_tokens"] if event.get("usage_confirmed") else capacity["prompt_tokens"]
        ),
        "reader_output_tokens": (
            usage["completion_tokens"]
            if event.get("usage_confirmed")
            else host.capacity.text_tokens(
                str(msg.get("reasoning_content") or "") + (content or "")
            )
            if isinstance(content, str)
            else None
        ),
        "reader_usage_source": "provider" if event.get("usage_confirmed") else "local_tokenizer",
    }
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
        cost["reader_cached_tokens"] = (
            details.get("cached_tokens") if isinstance(details, dict) else None
        )
    return result, cost


def execute_outcomes(
    dataset: MemoryControlDataset,
    run_id: str,
    *,
    limit: int,
) -> dict[str, Any]:
    host = dataset.host
    if host is None or limit < 1:
        raise ValueError("A revised Reader and positive dispatch count are required")
    with (
        closing(connect(dataset.path, writable=True)) as db,
        http_budget_scope(
            host.settings,
            client_configs=ownership_client_configs(host.settings),
        ) as budget,
    ):
        if budget is None:
            raise ValueError("Reader dispatch requires the existing shared HTTP owner")
        row = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Outcome run was not prepared")
        declared = json.loads(row[0])
        if declared["sealed"] or declared["comparison_protocol"] != comparison_protocol(dataset):
            raise ValueError("Outcome run differs from the current bound Reader protocol")
        before = budget.state["generation_requests"]
        outcome_counts: Counter[str] = Counter()
        # A saved in-flight marker with no response is distinct from an unissued branch.
        with db:
            db.execute(
                """
                UPDATE action_outcomes SET execution_status='reader_interrupted',
                    reader_status='unknown_after_interruption' WHERE run_id=?
                    AND execution_status='dispatching'
            """,
                (run_id,),
            )
        with VLLMClient(
            VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity
        ) as client:
            pending = db.execute(
                """
                SELECT state_id,action_id,repeat_index,task_result,costs FROM action_outcomes
                WHERE run_id=? AND execution_status='prepared' ORDER BY rowid LIMIT ?
            """,
                (run_id, limit),
            ).fetchall()
            for branch in pending:
                key = (branch["state_id"], branch["action_id"], run_id, branch["repeat_index"])
                stages, costs = unpack(branch["task_result"]), unpack(branch["costs"])
                with db:
                    db.execute(
                        """UPDATE action_outcomes SET execution_status='dispatching'
                        WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?""",
                        key,
                    )
                try:
                    result, actual = request_reader(
                        client, host, stages["reader_wire"], stages["capacity"]
                    )
                except BudgetExceeded:
                    with db:
                        db.execute(
                            """UPDATE action_outcomes SET execution_status='prepared'
                            WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?""",
                            key,
                        )
                    outcome_counts["budget_rejected_unissued"] += 1
                    break
                status = result["status"]
                with db:
                    db.execute(
                        """UPDATE action_outcomes SET execution_status=?,reader_status=?,
                        task_result=?,costs=?
                        WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?""",
                        (
                            status,
                            status,
                            packed({**stages, "reader_result": result}),
                            packed({**costs, **actual}),
                            *key,
                        ),
                    )
                outcome_counts[status] += 1
        return {
            "run_id": run_id,
            "reader_requests": budget.state["generation_requests"] - before,
            "outcomes_by_status": dict(outcome_counts),
            "metering": METERING,
        }


def score_outcomes(
    dataset: MemoryControlDataset,
    run_id: str,
    *,
    seal: bool,
) -> dict[str, Any]:
    if dataset.revision is None:
        raise ValueError("Use a revised outcome database")
    with closing(connect(dataset.path, writable=True)) as db:
        declared = db.execute(
            "SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if declared is None:
            raise ValueError("No such outcome run")
        declaration = json.loads(declared[0])
        if declaration["comparison_protocol"] != comparison_protocol(dataset):
            raise ValueError("Scoring requires the original Reader task codec")
        rows = db.execute(
            """
            SELECT o.state_id,o.action_id,o.repeat_index,o.task_result,
                   t.id,t.id AS task_id,t.dataset,t.query,t.root_id
            FROM action_outcomes o JOIN states s ON s.id=o.state_id
            JOIN experiment_tasks t ON t.id=s.task_id
            WHERE o.run_id=? AND o.execution_status='reader_completed'
                  AND t.experiment_role='train' ORDER BY t.id,o.rowid
        """,
            (run_id,),
        ).fetchall()
        last_task = None
        for branch in rows:
            if last_task != branch["task_id"]:
                gold = task_annotation(db, branch)
                public, correct = reader_task(
                    branch["dataset"],
                    branch["query"],
                    branch["task_id"],
                    gold,
                    dataset.revision["option_seed"],
                )
                if branch["dataset"] == MUSIQUE:
                    objects = {
                        f"s{pos}": oid
                        for oid, pos in db.execute(
                            "SELECT id,position FROM objects WHERE root_id=?", (branch["root_id"],)
                        )
                    }
                else:
                    objects = {}
                last_task = branch["task_id"]
            stages = unpack(branch["task_result"])
            response = stages["reader_result"]["response"]
            content = response["choices"][0]["message"].get("content")
            aliases = {
                name: objects[value["source_ref"]]
                for name, value in stages["source_aliases"].items()
                if value["source_ref"] in objects
            }
            key = (branch["state_id"], branch["action_id"], run_id, branch["repeat_index"])
            try:
                grade = score_answer(
                    content if isinstance(content, str) else "",
                    public,
                    gold,
                    correct,
                    support_aliases=aliases,
                )
            except (KeyError, TypeError, ValueError) as exc:
                with db:
                    db.execute(
                        """
                        UPDATE action_outcomes SET execution_status='scorer_error',
                            scoring_status=?, task_result=?
                        WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?
                    """,
                        (type(exc).__name__, packed({**stages, "score_error": str(exc)}), *key),
                    )
                continue
            with db:
                db.execute(
                    """
                    UPDATE action_outcomes SET execution_status='ingested',scoring_status=?,
                        native_metrics=?,training_quality=?,success_witness=?
                    WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?
                """,
                    (
                        grade["status"],
                        packed(grade["native_metrics"]),
                        grade["training_quality"],
                        grade["success_witness"],
                        *key,
                    ),
                )
        statuses = dict(
            db.execute(
                """
            SELECT execution_status,count(*) FROM action_outcomes WHERE run_id=? GROUP BY 1
        """,
                (run_id,),
            )
        )
        if seal:
            if any(
                statuses.get(status) for status in ("prepared", "dispatching", "reader_completed")
            ):
                raise ValueError("Outcome run still contains unissued or unscored branches")
            if not statuses.get("ingested"):
                raise ValueError("No actual scored branches in outcome run")
            declaration["sealed"] = True
            with db:
                db.execute(
                    "UPDATE outcome_runs SET config=? WHERE run_id=?", (dumps(declaration), run_id)
                )
        actionable = db.execute(
            """
            SELECT count(DISTINCT state_id),count(DISTINCT dataset || '/' || native_group),
                   count(DISTINCT task_id) FROM action_outcomes
            JOIN states ON states.id=action_outcomes.state_id
            JOIN experiment_tasks ON experiment_tasks.id=states.task_id
            WHERE run_id=? AND execution_status='ingested'
        """,
            (run_id,),
        ).fetchone()
        return {
            "run_id": run_id,
            "sealed": declaration["sealed"],
            "outcomes_by_status": statuses,
            "usable_states": actionable[0],
            "independent_groups": actionable[1],
            "tasks": actionable[2],
            "optimizer_updates": 0,
            "reader_requests_in_scoring": 0,
        }
