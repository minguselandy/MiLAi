"""Freeze capacity-bounded TRAIN interventions before Reader measurement."""

from __future__ import annotations

import random
import sqlite3
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_outcomes import run_protocols
from milai_lab.datasets.memory_control_protocols import BRANCH_PLAN_PROTOCOL
from milai_lab.datasets.memory_control_report import read_json
from milai_lab.datasets.memory_control_store import connect, unpack
from milai_lab.methods.frozen_feature_store import FrozenFeatureStore, batches, prefetch_rows
from milai_lab.methods.memory_control import FixedContextMemoryPolicy, MemoryAction
from milai_lab.methods.memory_control_dataset import MemoryControlDataset, StateIndex
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.methods.small_memory_policy import PolicyScores, best_scored_action
from milai_lab.runners.memory_control_episode import checkpoint_contract
from milai_lab.runners.memory_control_outcome_run import group_round_robin

DELTA_QUOTAS = {MUSIQUE: 600, QASPER: 3600, PERSONA: 1800}
RANKED_PROPOSALS = "matched_frozen_top_and_legal_read_v1"


def online_train_proposals(
    dataset: MemoryControlDataset, core_run: str, checkpoints: list[Path], *,
    seed: int, device: str, states_per_source: int, share_checkpoint_encoder: bool = False,
) -> dict[str, Any]:
    """Rank legal actions on registered TRAIN states before inspecting native evidence."""
    if not dataset.control_release or not checkpoints or states_per_source < 1:
        raise ValueError("Proposals require matched checkpoints and a registered TRAIN sample")
    if share_checkpoint_encoder and len(checkpoints) != 2:
        raise ValueError("Shared encoding requires a matched pair of TRAIN proposal checkpoints")
    started, cpu = time.perf_counter(), time.process_time()
    models = []
    for path in checkpoints:
        contract = checkpoint_contract(path)
        if (contract["observation_protocol"] != dataset.observation_protocol
                or contract["dataset_run_id"] not in {
                    dataset.run_id, dataset.control_release["parent_run_id"],
                }):
            raise ValueError("Proposal checkpoint uses a different before-state contract")
        model = SmallControlModel.load(path, device=device)
        model.configure_base_encoding_cache(32 * 1024**2)
        models.append(model)
    shared = (
        models[0].bind_shared_object_scorer(models[1]) if share_checkpoint_encoder else None
    )
    fixed = FixedContextMemoryPolicy(4)
    rng = random.Random(seed)  # noqa: S311 -- declared TRAIN state sample
    results = []
    with closing(connect(dataset.path)) as db:
        run_protocols(db, (core_run,), dataset.observation_protocol)
        by_source: dict[str, list[tuple[int, str, set[str]]]] = defaultdict(list)
        for sid, source, group in db.execute("""
            SELECT DISTINCT o.state_id,t.dataset,t.native_group FROM action_outcomes o
            JOIN states s ON s.id=o.state_id JOIN experiment_tasks t ON s.task_id=t.id
            WHERE t.experiment_role='train' AND o.run_id=?
            ORDER BY t.dataset,t.native_group,o.state_id
        """, (core_run,)):
            by_source[source].append((sid, group, set()))
        for source, rows in sorted(by_source.items()):
            for sid, _ in list(group_round_robin(rows, rng))[:states_per_source]:
                state, session, raw = dataset.replay(db, sid)
                actions = session.feasible_menu(raw)
                if not any(a.kind == "READ" for a in actions):
                    continue
                online = session.online(actions)
                reference_action = fixed.choose(session.state, actions)
                predictions = shared(online) if shared else tuple(m.score(online) for m in models)
                checkpoint_actions = [best_scored_action(score, actions) for score in predictions]
                results.append({
                    "state_id": sid, "dataset": source, "native_group": state["native_group"],
                    "reference_action": reference_action, "checkpoint_actions": checkpoint_actions,
                    "suggested_actions": list(dict.fromkeys(
                        (reference_action, *checkpoint_actions),
                    )),
                })
    return {
        "role": "train", "dataset_run_id": dataset.run_id,
        "observation_protocol": dataset.observation_protocol, "core_run": core_run,
        "checkpoints": [str(path.resolve()) for path in checkpoints],
        "comparison": "matched_frozen_scores_and_reference_action", "seed": seed,
        "shared_checkpoint_encoder": bool(shared),
        "encoder_work": [model.counters for model in models],
        "states": results, "by_source": dict(Counter(r["dataset"] for r in results)),
        "reader_requests": 0, "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - started, "sha_validation": False,
    }


def _intervention(
    row: sqlite3.Row, measured: set[str],
) -> tuple[list[str], list[str] | None]:
    actions = unpack(row["actions"])
    feasible = unpack(row["action_feasibility"])
    weak = unpack(row["evidence"])
    opened = {
        (a["parameters"]["index"], bool(a["parameters"].get("expand_context"))): (a["id"], y)
        for a, (ok, _), y in zip(actions, feasible, weak, strict=True)
        if a["kind"] == "READ" and ok is True
    }
    if not any(a["id"] == "handoff" and a["kind"] == "HANDOFF" for a in actions):
        return [], None
    pairs: list[tuple[list[str], bool]] = []
    focuses: list[str] = []
    for (idx, expanded), (action, label) in opened.items():
        if expanded:
            continue
        focuses.append(action)
        if (extension := opened.get((idx, True))) is not None:
            pairs.append((
                ["handoff", action, extension[0]], extension[1] is True and label is not True,
            ))
    pairs.sort(key=lambda pair: sum(a in measured for a in pair[0]))
    if pairs:
        return pairs[0][0], next((actions for actions, gold in pairs if gold), None)
    if focuses:
        return ["handoff", min(focuses, key=lambda a: a in measured)], None
    return [], None


def _online_priority_reasons(
    checkpoint_actions: list[str], branches: list[str], measured: set[str],
) -> list[str]:
    """Describe actual model votes represented in this legal intervention."""
    votes = set(checkpoint_actions)
    included = votes.intersection(branches)
    reasons = []
    if len(votes) > 1 and included:
        reasons.append("model_disagreement")
    if included - measured:
        reasons.append("unmeasured_top_action")
    return reasons


def _ranked_vote(score: PolicyScores, menu: list[MemoryAction]) -> dict[str, Any]:
    top = best_scored_action(score, menu)
    read_order = sorted(
        (i for i, action in enumerate(menu) if action.kind == "READ"),
        key=lambda i: (-score.scores[i], i),
    )
    return {
        "top_action": top,
        "best_legal_read": menu[read_order[0]].id if read_order else None,
        "legal_read_ranking": [menu[i].id for i in read_order],
    }


def ranked_train_proposals(
    dataset: MemoryControlDataset, core_run: str, checkpoints: list[Path], *,
    targets: dict[str, int], seed: int, device: str, prior_path: Path | None = None,
    feature_store: Path | None = None, raw_store: Path | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Use the complete legal menu for two frozen W models, before opening sampling labels."""
    import torch

    if (not dataset.control_release or len(checkpoints) != 2 or not targets
            or any(type(n) is not int or n < 1 for n in targets.values())):
        raise ValueError("Ranked proposal acquisition requires two W checkpoints and source targets")
    started, cpu = time.perf_counter(), time.process_time()
    models = []
    for path in checkpoints:
        contract = checkpoint_contract(path)
        if (contract["supervision_mode"] != "weak"
                or contract["observation_protocol"] != dataset.observation_protocol
                or contract["dataset_run_id"] != dataset.run_id):
            raise ValueError("Ranked proposals require the matching, trained W policy")
        model = SmallControlModel.load(path, device=device)
        model.train(False)
        model.configure_base_encoding_cache(32 * 1024**2)
        models.append(model)
    shared = models[0].bind_shared_object_scorer(models[1])
    identity = {
        "role": "train", "dataset_run_id": dataset.run_id,
        "observation_protocol": dataset.observation_protocol, "core_run": core_run,
        "seed": seed, "checkpoints": [str(path.resolve()) for path in checkpoints],
    }
    prior = {}
    if prior_path:
        previous = read_json(prior_path)
        if any(previous.get(k) != v for k, v in identity.items()):
            raise ValueError("Existing W proposals have a different cohort or checkpoint identity")
        prior = {row["state_id"]: row for row in previous["states"]}
        if len(prior) != len(previous["states"]):
            raise ValueError("Existing proposal states are duplicated")
    rng = random.Random(seed)  # noqa: S311 -- predeclared group rotation
    by_source: dict[str, list[tuple[int, str, set[str]]]] = defaultdict(list)
    meta = {}
    with closing(connect(dataset.path)) as db:
        run_protocols(db, (core_run,), dataset.observation_protocol)
        for row in db.execute("""
            SELECT DISTINCT s.id,t.dataset,t.native_group,t.root_id,t.id AS task_id,
                   s.recipe,v.material_budget,s.actions,v.action_feasibility
            FROM action_outcomes o JOIN states s ON s.id=o.state_id
            JOIN experiment_tasks t ON s.task_id=t.id JOIN state_variants v ON v.state_id=s.id
            WHERE t.experiment_role='train' AND o.run_id=?
            ORDER BY t.dataset,t.native_group,s.id
        """, (core_run,)):
            source = row["dataset"]
            if source in targets:
                sid = row["id"]
                meta[sid] = row
                by_source[source].append((sid, row["native_group"], set()))
    # The reservoir is fixed from group/role membership, prior to scoring or opening gold.
    ids = [
        sid for source, states in sorted(by_source.items())
        for sid, _ in list(group_round_robin(states, rng))[:2 * targets[source]]
    ]
    if not ids:
        raise ValueError("The sealed core did not supply any registered TRAIN proposals")
    results = {}
    needs_scores = []
    menus: dict[int, list[dict[str, Any]]] = {}
    counts: Counter[str] = Counter()
    timings: Counter[str] = Counter()
    tick = time.perf_counter()
    for sid in ids:
        item = meta[sid]
        actions = unpack(item["actions"])
        feasible = unpack(item["action_feasibility"])
        menu = [a for a, (ok, _) in zip(actions, feasible, strict=True)
                if a["kind"] != "READ" or ok is True]
        menus[sid] = menu
        reads = {a["id"] for a in menu if a["kind"] == "READ"}
        prior_row = prior.get(sid)
        seen = [] if prior_row is None else prior_row["checkpoint_actions"]
        entry = {"state_id": sid, "dataset": item["dataset"], "native_group": item["native_group"]}
        results[sid] = entry
        if not reads:
            entry.update(votes=[], missing_reason="no_legal_read")
            counts["no_legal_read"] += 1
        elif len(seen) == len(models) and all(a in reads for a in seen):
            entry.update(votes=[{"top_action": a, "best_legal_read": a} for a in seen],
                         score_origin="existing_frozen_W_votes")
            counts["prior_top_read_votes"] += 1
        else:
            needs_scores.append(sid)
    timings["inventory_seconds"] = time.perf_counter() - tick

    cache = None
    if feature_store and needs_scores and all(m.config.prior_policy == "none" for m in models):
        candidate = FrozenFeatureStore(feature_store, dataset, models[0], raw_store=raw_store)
        covered = set(needs_scores)
        for store in (candidate, candidate.raw_store):
            if store is not None:
                with closing(sqlite3.connect(f"{store.index_path.resolve().as_uri()}?mode=ro",
                                             uri=True)) as db:
                    covered.intersection_update(sid for (sid,) in db.execute(
                        "SELECT state_id FROM vectors"
                    ))
        if covered:
            candidate.open([
                StateIndex(sid, meta[sid]["dataset"], meta[sid]["native_group"],
                           meta[sid]["root_id"], meta[sid]["recipe"], (0, 0),
                           meta[sid]["task_id"], meta[sid]["material_budget"], False)
                for sid in sorted(covered)
            ])
            cache = candidate

    def publish() -> None:
        if progress:
            processed = [row for row in results.values() if "votes" in row]
            elapsed = time.perf_counter() - started
            progress({
                "processed": len(processed), "target": len(ids),
                "by_source": dict(Counter(row["dataset"] for row in processed)),
                "states_per_second": len(processed) / max(elapsed, 1e-9),
                "checkpoint_paths": identity["checkpoints"], "phase_counts": dict(counts),
                "timing_seconds": dict(timings), "device": device,
                "encoder_work": [m.counters for m in models], "wall_seconds": elapsed,
                "cuda_peak_bytes": torch.cuda.max_memory_allocated(models[0].device)
                if models[0].device.type == "cuda" else None,
            })

    publish()
    if cache:
        cached = [sid for sid in needs_scores if sid in cache.rows]
        with torch.no_grad():
            for window in batches(cached, 32):
                tick = time.perf_counter()
                rows = [{"actions": menus[sid]} for sid in window]
                states, actions, owners, lengths = cache.batch(window, rows, models[0].device)
                numeric = (cache.numeric_batch(window, models[0].device)
                           if any(m.config.numeric_mode == "real" for m in models) else None)
                timings["cache_load_seconds"] += time.perf_counter() - tick
                tick = time.perf_counter()
                logits = [
                    m.predict(states, actions, owners, rows, numerics=numeric).float().cpu().tolist()
                    for m in models
                ]
                pos = 0
                for sid, n in zip(window, lengths, strict=True):
                    menu = [MemoryAction(**a) for a in menus[sid]]
                    results[sid].update(
                        votes=[_ranked_vote(PolicyScores([a.id for a in menu], v[pos:pos + n]), menu)
                               for v in logits],
                        score_origin="shared_frozen_features",
                    )
                    pos += n
                timings["cached_head_seconds"] += time.perf_counter() - tick
                counts["feature_cache_hit"] += len(window)
                if counts["feature_cache_hit"] % 256 == 0:
                    publish()
    remaining = [sid for sid in needs_scores if "votes" not in results[sid]]
    for window, rows, wall in prefetch_rows(dataset, batches(remaining, 8), 2, features_only=True):
        timings["replay_loader_seconds"] += wall
        for sid, row in zip(window, rows, strict=True):
            menu = [MemoryAction(**a) for a in row["actions"]]
            if [asdict(a) for a in menu] != menus[sid]:
                raise ValueError("Replayed before-state menu differs from its registered binding")
            tick = time.perf_counter()
            results[sid].update(votes=[_ranked_vote(p, menu) for p in shared(row)],
                                score_origin="online_replay")
            timings["uncached_shared_encode_and_head_seconds"] += time.perf_counter() - tick
            counts["feature_cache_miss"] += 1
        if counts["feature_cache_miss"] % 128 == 0:
            publish()
    publish()
    return {
        **identity, "comparison": RANKED_PROPOSALS, "states": list(results.values()),
        "scoring_head": "trained_W_scalar_with_declared_prior",
        "tie_break": "highest_finite_score_then_recorded_legal_menu_order",
        "source_reservoir_targets": {source: 2 * n for source, n in targets.items()},
        "prior_proposals": str(prior_path) if prior_path is not None else None,
        "scoring_counts": dict(counts), "timing_seconds": dict(timings),
        "encoder_work": [model.counters for model in models],
        "reader_requests": 0, "sha_validation": False,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
    }


def _candidate_interventions(
    row: sqlite3.Row, votes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    entries = list(zip(unpack(row["actions"]), unpack(row["action_feasibility"]),
                       unpack(row["evidence"]), strict=True))
    legal = {a["id"]: a for a, (ok, _), _ in entries if a["kind"] == "READ" and ok is True}
    if not any(a["id"] == "handoff" and a["kind"] == "HANDOFF" for a, _, _ in entries):
        raise ValueError("An incremental before state lacks its registered HANDOFF")
    if not legal:
        if votes:
            raise ValueError("A W proposal references a state without legal READ")
        return [{"actions": ["handoff"], "missing": {"R2": "no_legal_read", "R3": "no_legal_read"},
                 "opportunity": False}], False
    if len(votes) != 2 or any(vote["best_legal_read"] not in legal for vote in votes):
        raise ValueError("Both W proposals must bind to a legal READ")
    options = []
    for vote in votes:
        index = legal[vote["best_legal_read"]]["parameters"]["index"]
        precision = {
            "R3" if a["parameters"].get("expand_context") else "R2": (a["id"], ok, reason, label)
            for a, (ok, reason), label in entries
            if a["kind"] == "READ" and a["parameters"]["index"] == index
        }
        actions, missing = ["handoff"], {}
        for kind in ("R2", "R3"):
            entry = precision.get(kind)
            if entry and entry[1] is True:
                actions.append(entry[0])
            else:
                missing[kind] = (entry[2] or "not_feasible") if entry else "not_offered"
        r2, r3 = precision.get("R2"), precision.get("R3")
        options.append({
            "actions": actions, "candidate_index": index, "missing": missing,
            "opportunity": ("R2" not in missing and "R3" not in missing
                            and r3 is not None and r3[3] is True
                            and r2 is not None and r2[3] is not True),
        })
    return options, options[0]["candidate_index"] != options[1]["candidate_index"]


def register_ranked_delta(
    dataset: MemoryControlDataset, core_run: str, proposal_path: Path, *,
    seed: int, quotas: dict[str, int],
) -> dict[str, Any]:
    proposals = read_json(proposal_path)
    if (proposals.get("comparison") != RANKED_PROPOSALS or proposals.get("seed") != seed
            or proposals.get("core_run") != core_run or proposals.get("role") != "train"
            or proposals.get("dataset_run_id") != dataset.run_id
            or proposals.get("observation_protocol") != dataset.observation_protocol
            or proposals.get("sha_validation") is not False
            or not quotas or any(type(n) is not int or n < 1 for n in quotas.values())):
        raise ValueError("Use the registered two-arm TRAIN proposal roster")
    rng = random.Random(seed)  # noqa: S311 -- preregistered allocation and repeat sample
    metadata: dict[int, dict[str, Any]] = {}
    roster: dict[str, list[tuple[int, str, set[str]]]] = defaultdict(list)
    with closing(connect(dataset.path)) as db:
        run_protocols(db, (core_run,), dataset.observation_protocol)
        measured: dict[int, set[str]] = defaultdict(set)
        for sid, action, completed in db.execute("""
            SELECT state_id,action_id,execution_status='ingested' AND training_quality IS NOT NULL
            FROM action_outcomes WHERE run_id=?
        """, (core_run,)):
            seen = measured[sid]
            if completed:
                seen.add(action)
        for item in proposals["states"]:
            sid, source, group = (item[k] for k in ("state_id", "dataset", "native_group"))
            row = db.execute("""
                SELECT s.actions,v.action_feasibility,v.material_budget,w.evidence
                FROM states s JOIN experiment_tasks t ON s.task_id=t.id
                JOIN state_variants v ON v.state_id=s.id JOIN weak_labels w ON w.state_id=s.id
                WHERE s.id=? AND t.dataset=? AND t.native_group=? AND t.experiment_role='train'
            """, (sid, source, group)).fetchone()
            if row is None or sid in metadata or sid not in measured or source not in quotas:
                raise ValueError("D reservoir must contain distinct registered core TRAIN states")
            votes = item["votes"]
            options, disagreement = _candidate_interventions(row, votes)
            for option, vote in zip(options, votes):
                option["priority"] = (disagreement or
                                      vote["best_legal_read"] not in measured[sid])
            metadata[sid] = {
                "state_id": sid, "dataset": source, "native_group": group,
                "material_budget": row["material_budget"], "repeats": 1,
                "votes": votes, "options": options, "candidate_disagreement": disagreement,
            }
            roster[source].append((sid, group, set()))
    selected: dict[int, dict[str, Any]] = {}
    strata, assignments, shortfalls = {}, {}, {}
    for source, target in sorted(quotas.items()):
        order = list(group_round_robin(roster[source], rng))
        first_proposer = rng.randrange(2)
        disagreements = 0
        frequencies: Counter[str] = Counter()
        allocation: Counter[int] = Counter()
        opportunity_size = sum(any(o["opportunity"] for o in metadata[sid]["options"])
                               for sid, _ in order)
        priority_size = sum(any(o.get("priority") for o in metadata[sid]["options"])
                            for sid, _ in order)
        targeted = sorted((("online_priority", priority_size),
                           ("evidence_opportunity", opportunity_size)), key=lambda row: row[1])
        quarter = target // 4
        for stratum, quota in (*((name, quarter) for name, _ in targeted),
                               ("natural", target - 2 * quarter), ("natural_backfill", target)):
            remaining = min(quota, target - sum(frequencies.values()))
            # Prefer actual holes in the C observation menu within each native-group rotation.
            missing_first = sorted(order, key=lambda pair: not any(
                set(o["actions"]) - measured[pair[0]] for o in metadata[pair[0]]["options"]
            ))
            for sid, _ in missing_first:
                if not remaining:
                    break
                if sid in selected:
                    continue
                row = metadata[sid]
                assigned = (first_proposer + disagreements) % 2 if row["candidate_disagreement"] else 0
                option = row["options"][assigned]
                if (stratum == "online_priority" and not option.get("priority")
                        or stratum == "evidence_opportunity" and not option["opportunity"]):
                    continue
                if row["candidate_disagreement"]:
                    allocation[assigned] += 1
                    disagreements += 1
                chosen = {k: v for k, v in row.items() if k != "options"}
                selected[sid] = {
                    **chosen, "stratum": stratum, "actions": option["actions"], "from_core": True,
                    "candidate_index": option.get("candidate_index"),
                    "assigned_proposer": assigned if row["candidate_disagreement"] else None,
                    "unmeasured_candidate_index": row["options"][1 - assigned]["candidate_index"]
                    if row["candidate_disagreement"] else None,
                    "missing_precision_reasons": option["missing"],
                    "planned_missing_actions": sorted(set(option["actions"]) - measured[sid]),
                }
                frequencies[stratum] += 1
                remaining -= 1
        strata[source] = dict(frequencies)
        assignments[source] = {
            "first_proposer": first_proposer, "assigned_checkpoints": [allocation[i] for i in (0, 1)],
        }
        shortfalls[source] = target - sum(frequencies.values())
    if not selected:
        raise ValueError("No TRAIN states could be selected from the core")
    states, repeat_target = _match_repeats(selected, rng, fraction=0.2)
    return {
        "protocol": BRANCH_PLAN_PROTOCOL, "kind": "incremental_pair", "dataset_run_id": dataset.run_id,
        "observation_protocol": dataset.observation_protocol, "seed": seed, "core_run": core_run,
        "source_targets": quotas, "actual_strata_by_source": strata, "states": states,
        "source_shortfalls": shortfalls, "online_proposals": str(proposal_path.resolve()),
        "proposer_checkpoint_paths": proposals["checkpoints"], "disagreement_assignment": assignments,
        "distinct_before_states": len(states), "repeat_states": repeat_target,
        "request_slots": sum(len(r["actions"]) * r["repeats"] for r in states),
        "proposal_protocol": RANKED_PROPOSALS, "registered_before_first_response": True,
        "sha_validation": False,
    }


def _match_repeats(
    selected: dict[int, dict[str, Any]], rng: random.Random, *, fraction: float,
) -> tuple[list[dict[str, Any]], int]:
    repeat_target = round(len(selected) * fraction)
    strata: dict[tuple[str, int, str], list[tuple[int, str, set[str]]]] = defaultdict(list)
    for sid, row in selected.items():
        key = row["dataset"], row["material_budget"], row["stratum"]
        strata[key].append((sid, row["native_group"], set()))
    repeats: Counter[tuple[str, int, str]] = Counter()
    queues = {key: deque(group_round_robin(value, rng)) for key, value in strata.items()}
    for _ in range(repeat_target):
        key = min((k for k, queue in queues.items() if queue),
                  key=lambda k: (repeats[k] / len(strata[k]), k))
        sid, _ = queues[key].popleft()
        selected[sid]["repeats"] = 2
        repeats[key] += 1
    states = list(selected.values())
    rng.shuffle(states)
    return states, repeat_target


def register_branch_plan(
    dataset: MemoryControlDataset, core_run: str, *, seed: int, kind: str,
    quotas: dict[str, int], online_proposals: Path | None = None,
) -> dict[str, Any]:
    """Prefer missing measurements on existing before states with native-group rotation."""
    if not dataset.control_release or kind not in {"incremental_pair", "continuation_audit"}:
        raise ValueError("Branch planning requires a derived TRAIN release and valid purpose")
    if not quotas or any(type(n) is not int or n <= 0 for n in quotas.values()):
        raise ValueError("Declare positive targets per source")
    rng = random.Random(seed)  # noqa: S311 -- frozen native-group allocation
    proposals: dict[int, list[str]] = {}
    if online_proposals:
        source = read_json(online_proposals)
        if (source.get("dataset_run_id") != dataset.run_id
                or source.get("observation_protocol") != dataset.observation_protocol
                or source.get("role") != "train"):
            raise ValueError("Online proposals must use the matching decision-time TRAIN protocol")
        # Historical proposal files combined the reference and model votes.
        # They still support the natural cohort but cannot establish model disagreement.
        proposals = {item["state_id"]: item.get("checkpoint_actions", [])
                     for item in source["states"]}
    roster: dict[str, list[tuple[int, str, set[str]]]] = defaultdict(list)
    metadata: dict[int, dict[str, Any]] = {}
    gold_actions: dict[int, list[str]] = {}
    with closing(connect(dataset.path)) as db:
        run_protocols(db, (core_run,), dataset.observation_protocol)
        measured: dict[int, set[str]] = defaultdict(set)
        for sid, action, completed in db.execute("""
            SELECT state_id,action_id,execution_status='ingested' AND training_quality IS NOT NULL
            FROM action_outcomes WHERE run_id=?
        """, (core_run,)):
            seen = measured[sid]
            if completed:
                seen.add(action)
        for row in db.execute("""
            SELECT s.id,s.actions,t.dataset,t.native_group,v.material_budget,
                   v.action_feasibility,w.evidence
            FROM states s JOIN experiment_tasks t ON t.id=s.task_id
            JOIN state_variants v ON v.state_id=s.id JOIN weak_labels w ON w.state_id=s.id
            WHERE t.experiment_role='train' AND s.sampling<>'policy_reached'
            ORDER BY t.dataset,t.native_group,s.id
        """):
            source_name, sid = row["dataset"], row["id"]
            if source_name not in quotas:
                continue
            observed = measured.get(sid, set())
            branches, gold = _intervention(row, observed)
            if not branches:
                continue
            labels = {"core"} if sid in measured else set()
            if gold:
                labels.add("evidence_opportunity")
                gold_actions[sid] = gold
            reasons = _online_priority_reasons(proposals.get(sid, []), branches, observed)
            if reasons:
                labels.add("online_priority")
            roster[source_name].append((sid, row["native_group"], labels))
            metadata[sid] = {
                "state_id": sid, "dataset": source_name, "native_group": row["native_group"],
                "material_budget": row["material_budget"], "actions": branches,
                "repeats": 1, "from_core": sid in measured,
                "planned_missing_actions": sorted(set(branches) - observed),
            }
    selected: dict[int, dict[str, Any]] = {}
    strata_counts: dict[str, dict[str, int]] = {}
    ordered_by_source: dict[str, list[tuple[int, set[str]]]] = {}
    for source_name, target in sorted(quotas.items()):
        tiers: dict[int, list[tuple[int, str, set[str]]]] = defaultdict(list)
        for row in roster[source_name]:
            sid, _, labels = row
            tier = (0 if metadata[sid]["planned_missing_actions"] else 1) if "core" in labels else 2
            tiers[tier].append(row)
        ordered = [
            item for tier in sorted(tiers) for item in group_round_robin(tiers[tier], rng)
        ]
        ordered_by_source[source_name] = ordered
        quarter = target // 4 if kind == "incremental_pair" else 0
        targeted = sorted(
            ("online_priority", "evidence_opportunity"),
            key=lambda name: (sum(name in labels for _, labels in ordered), name),
        )
        # Reserve the smaller targeted cohort first when eligibility overlaps.
        requests = (*((name, quarter) for name in targeted), ("natural", target - 2 * quarter))
        source_counts: Counter[str] = Counter()

        for slot, requested in (*requests, ("natural_backfill", target)):
            count = min(requested, target - sum(source_counts.values()))
            for sid, labels in ordered:
                if source_counts[slot] >= count:
                    break
                if sid in selected or (slot in {"online_priority", "evidence_opportunity"}
                                       and slot not in labels):
                    continue
                item = {**metadata[sid], "stratum": slot}
                if slot == "evidence_opportunity":
                    item["actions"] = gold_actions[sid]
                    item["planned_missing_actions"] = sorted(set(item["actions"]) - measured[sid])
                if slot == "online_priority":
                    item["online_priority_reasons"] = _online_priority_reasons(
                        proposals[sid], item["actions"], measured.get(sid, set()),
                    )
                selected[sid] = item
                source_counts[slot] += 1
        strata_counts[source_name] = dict(source_counts)
    # Record any original source shortfall before filling on other legal TRAIN groups.
    shortfalls = {
        source: target - sum(strata_counts[source].values()) for source, target in quotas.items()
    }
    needed = sum(shortfalls.values())
    if needed:
        replacements = {
            source: deque(sid for sid, _ in ordered if sid not in selected)
            for source, ordered in ordered_by_source.items()
        }
        while needed and any(replacements.values()):
            for source, queue in replacements.items():
                if not queue or not needed:
                    continue
                sid = queue.popleft()
                label = "cross_source_backfill"
                selected[sid] = {**metadata[sid], "stratum": label}
                strata_counts[source][label] = strata_counts[source].get(label, 0) + 1
                needed -= 1
    if not selected:
        raise ValueError("No registered TRAIN states have a legal intervention")
    states, repeat_target = _match_repeats(
        selected, rng, fraction=0.2 if kind == "incremental_pair" else 0,
    )
    return {
        "protocol": BRANCH_PLAN_PROTOCOL, "kind": kind, "dataset_run_id": dataset.run_id,
        "observation_protocol": dataset.observation_protocol, "seed": seed, "core_run": core_run,
        "source_targets": quotas, "actual_strata_by_source": strata_counts, "states": states,
        "available_train_states_by_source": {s: len(roster[s]) for s in quotas},
        "source_shortfalls_before_backfill": shortfalls,
        "remaining_unfilled_before_states": needed,
        "online_proposals": str(online_proposals.resolve()) if online_proposals else None,
        "distinct_before_states": len(states), "repeat_states": repeat_target,
        "request_slots": sum(len(r["actions"]) * r["repeats"] for r in states),
        "registered_before_first_response": True,
    }
