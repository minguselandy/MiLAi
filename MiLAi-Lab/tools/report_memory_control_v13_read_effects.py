"""Offline replay of R2/R3 delivery effects and native MuSiQue bridge completion."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from statistics import mean, median

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.memory.reader_projection import merge_source_ranges, subtract_source_ranges
from milai_lab.methods.dataset_control_states import evidence_for, full_objects, task_annotation
from milai_lab.methods.dataset_corpus_runtime import CorpusPool
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.control_policy_iteration import read_gzip
from milai_lab.runners.qrag_milai_env import MAX_OPERATIONS, cold_root, outcome_label
from milai_lab.scorers.memory_control_episode_metrics import QUALITY_AXES, input_result
from milai_lab.scorers.memory_control_native import musique_pair


def stats(values):
    return dict(
        n=len(values),
        mean=mean(values) if values else None,
        median=median(values) if values else None,
        positive=sum(x > 0 for x in values),
        zero=sum(x == 0 for x in values),
        negative=sum(x < 0 for x in values),
    )


def rate(k, n):
    return dict(numerator=k, denominator=n, rate=k / n if n else None)


def ranges(env):
    """Only the literal source intervals selected for actual Host delivery."""
    result = []
    for opened in env.ops.opened.values():
        if (
            "source_ranges" not in opened
            or opened.get("visibility") != "visible"
            or opened.get("body_delivered") is not True
        ):
            raise ValueError("Expected actual visible literal source intervals")
        spans = subtract_source_ranges(
            opened["source_ranges"], opened.get("unavailable_source_ranges") or []
        )
        for span in spans:
            if span["source_revision"] != 1:
                raise ValueError("Unexpected revision in the static corpus snapshot")
            result.append((env.pool.by_ref[span["source_ref"]].id, span["start"], span["end"]))
    return result


def covered_views(views, pool, relevant):
    return full_objects([span for view in views for span in view.ranges], pool, relevant)


def diff(values):
    return values[1] - values[0] if all(v is not None for v in values) else None


def first_step(dataset, db, task, budget, prefix, pool, aid, expect):
    env, menu, _ = cold_root(dataset, db, task, budget, prefix, pool)
    online = json.loads(json.dumps(env.online(menu)))
    if "action_history" not in expect["observation"]:
        online["observation"].pop("action_history", None)
    if online != expect:
        raise ValueError("Replayed legal TRAIN before differs from its recorded menu")
    a = next(x for x in menu if x.id == aid)
    idx = a.parameters["index"]
    vid = pool.bound_view(env.focus, a)
    before = env.used_tokens
    if not env.take(a) or env.opened[idx] != vid:
        raise ValueError("Registered first READ did not open its bound view")
    norm = pool.normalized_delivery(env.ops.opened)
    packet = env.plan_packet(norm.evidence)
    if packet.material_tokens != env.used_tokens:
        raise ValueError("First-step Host packet and charged material tokens disagree")
    return (
        env.focus[idx],
        pool.views[env.focus[idx]].object_id,
        vid,
        packet.packet,
        merge_source_ranges(pool.source_ranges(ranges(env))),
        env.used_tokens - before,
    )


def paid_measurement(record, directory, allowed):
    origin = record.get("measurement_reused_from")
    paid = record
    if origin:
        path = Path(origin)
        if path.parent.resolve() not in allowed or not path.is_file():
            return None
        paid = read_gzip(path)
        if (
            paid.get("task_id") != record["task_id"]
            or paid.get("reader_wire") != record["reader_wire"]
            or paid.get("reader_result") != record.get("reader_result")
        ):
            raise ValueError(f"Incompatible Reader reuse in {directory}")
    before = paid.get("ledger_before")
    provider = (paid.get("reader_result") or {}).get("response", {}).get("id")
    if (
        paid.get("actual_requests") != 1
        or type(before) is not int
        or paid.get("ledger_after") != before + 1
        or not provider
    ):
        return None
    return before, provider


def quality_cost(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return stats(vals)


def summarize_levels(rows, counts):
    out = {}
    for source, c in counts.items():
        pool = [r for r in rows if r["source"] == source]
        q = [
            r for r in pool if r["quality_delta"] is not None and r["total_cost_delta"] is not None
        ]
        expensive = [r for r in q if r["total_cost_delta"] > 0]
        unhelpful = sum(r["quality_delta"] <= 0 for r in expensive)
        higher_first = [r for r in q if r["immediate_tokens_delta"] > 0]
        wire = [r for r in pool if r["terminal_wire_differs"] is not None]
        out[source] = dict(
            counts=dict(c),
            measured_native_groups=len({r["native_group"] for r in pool}),
            first_packet_difference=rate(sum(r["first_packet_differs"] for r in pool), len(pool)),
            first_interval_difference=rate(sum(r["first_ranges_differ"] for r in pool), len(pool)),
            terminal_wire_difference=rate(sum(r["terminal_wire_differs"] for r in wire), len(wire)),
            same_wire_shared_physical_reply=sum(
                r["terminal_wire_differs"] is False and r["independent_terminal_responses"] is False
                for r in wire
            ),
            missing_quality=len(pool) - sum(r["quality_delta"] is not None for r in pool),
            missing_future_cost=len(pool) - sum(r["future_cost_delta"] is not None for r in pool),
            same_wire_distinct_actual_returns=sum(
                r["terminal_wire_differs"] is False and r["independent_terminal_responses"] is True
                for r in wire
            ),
            different_first_same_terminal=sum(
                r["first_packet_differs"] and not r["terminal_wire_differs"] for r in wire
            ),
            quality_delta=quality_cost(pool, "quality_delta"),
            immediate_tokens_delta=quality_cost(pool, "immediate_tokens_delta"),
            future_cost_delta=quality_cost(pool, "future_cost_delta"),
            total_cost_delta=quality_cost(pool, "total_cost_delta"),
            expensive_without_quality_gain_all=rate(unhelpful, len(q)),
            no_quality_gain_given_higher_total_cost=rate(unhelpful, len(expensive)),
            no_quality_gain_given_higher_first_cost=rate(
                sum(r["quality_delta"] <= 0 for r in higher_first), len(higher_first)
            ),
        )
    return out


def level_effects(dataset, directory):
    cfg = read_json(directory / "round.json")
    done = read_json(directory / "progress.json")
    if (
        done.get("state") != "complete"
        or cfg["dataset_run"] != dataset.run_id
        or cfg["observation"] != dataset.observation_protocol
        or cfg["continuation_mode"] != "full_episode"
    ):
        raise ValueError("Use a closed TRAIN full-continuation package directory")
    origins = {
        (directory / "receipts").resolve(),
        *((Path(x) / "receipts").resolve() for x in cfg.get("reuse_from", [])),
    }
    counts = defaultdict(Counter)
    reports = []
    known = set()
    groups = set()
    with closing(connect(dataset.path)) as db:
        for file in sorted((directory / "packs").glob("*.json.gz")):
            row = read_gzip(file)
            tid = row["task_id"]
            uid = row["root_state_id"]
            source = row["source"]
            group = row["native_group_id"]
            if (
                row["split_role"] != "train"
                or row["continuation_policy_id"] != cfg["continuation_policy_id"]
                or row["collection_round"] != cfg["round"]
                or uid in known
                or not uid.startswith(f"{tid}_")
            ):
                raise ValueError("Mismatched TRAIN root or continuation")
            known.add(uid)
            groups.add((source, group))
            task = db.execute(
                "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='train' "
                "AND clean_role='train'",
                (tid,),
            ).fetchone()
            if task is None or (task["dataset"], task["native_group"]) != (source, group):
                raise ValueError("Native TRAIN identity differs")
            c = counts[source]
            c["roots"] += 1
            prefix = tuple(uid[len(str(tid)) + 1 :].split("-"))
            pool = CorpusPool(db, task["root_id"])
            _, menu, _ = cold_root(dataset, db, task, cfg["material_budget"], prefix, pool)
            if [a.id for a in menu] != [a["id"] for a in row["online"]["actions"]]:
                raise ValueError("Restored full action menu differs")
            levels = defaultdict(dict)
            for a in menu:
                if a.kind == "READ":
                    levels[a.parameters["index"]][bool(a.parameters.get("expand_context"))] = a.id
            measured = {o["first_action_id"]: o for o in row["outcomes"]}
            if not set(measured) <= {a.id for a in menu}:
                raise ValueError("Illegal measured branch")
            offered = {i: v for i, v in levels.items() if set(v) == {False, True}}
            c["roots_offering_both_levels"] += bool(offered)
            c["cooffered_object_slots"] += len(offered)
            c["equivalent_levels_recorded_by_sampler"] += len(row["equivalent_levels"])
            c["paired_measured_object_slots"] += 0
            c["unverified_executed_pairs"] += 0
            root_hits = 0
            for idx, options in offered.items():
                ids = [options[False], options[True]]
                if not all(a in measured for a in ids):
                    continue
                outcomes = [measured[a] for a in ids]
                recs = []
                cps = []
                for a, o in zip(ids, outcomes, strict=True):
                    (key,) = o["reader_receipt_ids"]
                    rec = read_gzip(directory / "receipts" / (key + ".json.gz"))
                    recs.append(rec)
                    cp = o["companion_receipt_id"]
                    cps.append(cp)
                    adjunct = read_gzip(directory / "receipts" / (cp + ".json.gz")) if cp else None
                    if (
                        rec["task_id"] != tid
                        or rec["native_group_id"] != group
                        or (rec["action_trace"] and rec["action_trace"][0] != a)
                    ):
                        raise ValueError("First action and native measurement disagree")
                    if source == MUSIQUE and (
                        not adjunct
                        or adjunct["native_group_id"] != group
                        or adjunct["task_id"] == tid
                    ):
                        raise ValueError("Missing native MuSiQue companion")
                    live = outcome_label(source, rec, adjunct)
                    for k in (
                        "reader_quality",
                        "quality_observed",
                        "future_cost",
                        "future_cost_observed",
                        "immediate_cost",
                    ):
                        if live[k] != o[k]:
                            raise ValueError(
                                "Recorded TRAIN target differs from measured terminal receipt"
                            )
                if any(
                    not r["action_trace"] or r["status"] in {"incomplete", "action_failed"}
                    for r in recs
                ):
                    c["unverified_executed_pairs"] += 1
                    continue
                if cps[0] != cps[1]:
                    raise ValueError("Different native companions within the same root")
                x, y = [
                    first_step(
                        dataset, db, task, cfg["material_budget"], prefix, pool, a, row["online"]
                    )
                    for a in ids
                ]
                if x[:2] != y[:2] or any(
                    o["immediate_cost"] is not None and value != o["immediate_cost"]
                    for o, value in zip(outcomes, (x[5], y[5]), strict=True)
                ):
                    raise ValueError("Different object binding or first-step material cost")
                q = [o["reader_quality"] if o["quality_observed"] else None for o in outcomes]
                future = [o["future_cost"] if o["future_cost_observed"] else None for o in outcomes]
                wa, wb = [r["reader_wire"] for r in recs]
                fixed = [{k: v for k, v in w.items() if k != "messages"} for w in (wa, wb) if w]
                if len(fixed) == 2 and fixed[0] != fixed[1]:
                    raise ValueError("Branches use different decoding")
                delta_c = diff(future)
                actual = [paid_measurement(r, directory, origins) for r in recs]
                if all(actual) and (actual[0][0] == actual[1][0]) != (actual[0][1] == actual[1][1]):
                    raise ValueError("Paired physical Reader and provider identities disagree")

                c["paired_measured_object_slots"] += 1
                root_hits += 1
                reports.append(
                    dict(
                        source=source,
                        native_group=group,
                        root=uid,
                        index=idx,
                        focus_view=x[0],
                        source_object=x[1],
                        view_ids=[x[2], y[2]],
                        action_ids=ids,
                        companion=cps[0],
                        first_packet_differs=x[3] != y[3],
                        first_ranges_differ=bool(
                            subtract_source_ranges(y[4], x[4]) or subtract_source_ranges(x[4], y[4])
                        ),
                        first_source_ranges=[x[4], y[4]],
                        physical_measurements=actual,
                        independent_terminal_responses=(
                            actual[0] != actual[1] if all(actual) else None
                        ),
                        added_ranges=subtract_source_ranges(y[4], x[4]),
                        removed_ranges=subtract_source_ranges(x[4], y[4]),
                        terminal_wire_differs=(wa != wb if wa and wb else None),
                        immediate_tokens_delta=y[5] - x[5],
                        quality_delta=diff(q),
                        future_cost_delta=delta_c,
                        total_cost_delta=delta_c + y[5] - x[5] if delta_c is not None else None,
                        quality=q,
                        future_cost=future,
                        source_receipt_ids=[r["receipt_id"] for r in recs],
                    )
                )
            c["roots_with_measured_pair"] += bool(root_hits)
    for src, _ in groups:
        counts[src]["native_groups"] += 1
    if len(known) != done["complete_packs"]:
        raise ValueError("Incomplete TRAIN pack roster")
    return dict(
        source_directory=str(directory.resolve()),
        data_role="train",
        root_count=len(known),
        native_group_count=len(groups),
        continuation=cfg["continuation_policy_id"],
        by_source=summarize_levels(reports, counts),
        observations=reports,
    )


def bridge_effects(dataset, paths):
    expected = None
    results = []
    for path in paths:
        cfg, pred = input_result(path)
        pop = cfg["population"]
        if (
            read_json(path / "run.json")["status"] != "COMPLETED"
            or pop["role"] != "dev"
            or pop["v13_role"] != "curve"
            or cfg["arm"]["environment"] != "qrag_milai_v13"
            or pop["dataset_run_id"] != dataset.run_id
            or (expected is not None and expected != pop)
        ):
            raise ValueError(
                "Use completed native V13 readouts on exactly the same natural DEV curve roster"
            )
        expected = pop
        groups = defaultdict(list)
        for task in pop["tasks"]:
            if task["dataset"] == MUSIQUE:
                groups[task["native_group"]].append(task["task_id"])
        rows = []
        with closing(connect(dataset.path)) as db:
            for group, tids in groups.items():
                if len(tids) != 2:
                    raise ValueError("Incomplete registered MuSiQue pair")
                pair = [pred.get(i, {}) for i in tids]
                grades = [r.get("grade") for r in pair]
                quality = (
                    musique_pair([g["native_metrics"] for g in grades])[QUALITY_AXES[MUSIQUE]]
                    if all(grades)
                    else None
                )
                answerable = []
                for tid in tids:
                    task = db.execute(
                        "SELECT * FROM experiment_tasks WHERE id=? AND dataset=? "
                        "AND experiment_role='dev'",
                        (tid, MUSIQUE),
                    ).fetchone()
                    if task is None or task["native_group"] != group:
                        raise ValueError("Native DEV identity differs")
                    gold = task_annotation(db, task)
                    grade = pred.get(tid, {}).get("grade")
                    if grade and grade["native_metrics"]["gold_answerable"] != gold["answerable"]:
                        raise ValueError("Saved native grade and actual task answerability differ")
                    if gold["answerable"]:
                        answerable.append((task, gold))
                if len(answerable) != 1:
                    raise ValueError("Need one native answerable member")
                task, gold = answerable[0]
                tid = task["id"]
                packet = pred.get(tid, {})
                pool = CorpusPool(db, task["root_id"])
                focus = pool.rank(task["query"], 32)[:8]
                gold["object_locators"] = [
                    (oid, json.loads(loc))
                    for oid, loc in db.execute(
                        "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],)
                    )
                ]
                e = evidence_for(MUSIQUE, gold, pool)
                bridge = e.first_bridge
                r2 = [pool.views[v] for v in focus]
                r3 = [pool.views[v.context_id] for v in r2 if v.context_id is not None]

                available = covered_views([*r2, *r3], pool, e.positive)
                decomp = gold["question_decomposition"]
                first = next(
                    (
                        i
                        for i, step in enumerate(decomp, 1)
                        if step.get("paragraph_support_idx") is not None
                    ),
                    None,
                )
                ref = (
                    any(
                        re.search(rf"#{first}(?![0-9])", step["question"])
                        for step in decomp[first:]
                    )
                    if first
                    else None
                )
                entry = dict(
                    native_group=group,
                    answerable_task=tid,
                    first_bridge_object=bridge,
                    later_uses_first_subanswer=ref,
                    reachable_top8_r2=(
                        bridge in covered_views(r2, pool, e.positive)
                        if bridge is not None
                        else None
                    ),
                    reachable_top8_any_level=(bridge in available if bridge is not None else None),
                    complete_set_reachable=any(g <= available for g in e.sets) if e.sets else None,
                    native_pair_quality=quality,
                    bridge_completed_by_read=None,
                    full_set_delivered=None,
                )
                if (
                    packet.get("actual_cold_prefix") is not None
                    and packet.get("delivered_material") is not None
                ):
                    env = dataset.start_task(db, task, pool, focus, pop["material_budget"])
                    env.state.action_history = []
                    hit = []
                    initial = False
                    ordinal = 0
                    for aid in packet["actual_cold_prefix"]:
                        options = env.menu(MAX_OPERATIONS)
                        action = next(a for a in options if a.id == aid)
                        before = full_objects(ranges(env), pool, e.positive)
                        if not env.take(action):
                            raise ValueError("Recorded DEV action failed replay")
                        after = full_objects(ranges(env), pool, e.positive)
                        if action.kind == "SEARCH":
                            initial = bridge in after
                            first_trace = (packet.get("control", {}).get("trace") or [{}])[0]
                            actual_menu = first_trace.get("before", {}).get("pending_candidates")
                            if actual_menu is not None:
                                env.menu(MAX_OPERATIONS)
                                if (
                                    json.loads(json.dumps(env.state.pending_candidates))
                                    != actual_menu
                                ):
                                    raise ValueError(
                                        "Top-eight descriptors differ from saved navigation"
                                    )
                            entry["top8_descriptors_verified"] = actual_menu is not None
                        if action.kind == "READ":
                            ordinal += 1
                            if bridge not in before and bridge in after:
                                hit.append(dict(read=ordinal, action=aid))
                    material = pool.normalized_delivery(env.ops.opened)
                    planned = env.plan_packet(material.evidence)
                    if planned.packet != packet["delivered_material"]:
                        raise ValueError("DEV source spans do not reproduce terminal delivery")
                    if (
                        packet.get("reader_wire")
                        and {**planned.wire, "seed": packet["reader_wire"]["seed"]}
                        != packet["reader_wire"]
                    ):
                        raise ValueError("Replayed terminal wire differs")
                    final = full_objects(ranges(env), pool, e.positive)
                    entry.update(
                        bridge_present_after_search=initial if bridge is not None else None,
                        bridge_completed_by_read=bool(hit) if bridge is not None else None,
                        first_bridge_completion=hit[0] if hit else None,
                        delivered_bridge=bridge in final if bridge is not None else None,
                        full_set_delivered=any(g <= final for g in e.sets) if e.sets else None,
                        bridge_source_ref=pool.ref(bridge) if bridge is not None else None,
                        bridge_body_chars=len(pool.objects[bridge].body)
                        if bridge is not None
                        else None,
                        delivered_bridge_ranges=merge_source_ranges(
                            pool.source_ranges([s for s in ranges(env) if s[0] == bridge])
                        ),
                        support_object_ids=sorted(e.positive),
                        completed_support_object_ids=sorted(e.positive & final),
                    )
                rows.append(entry)
        with_bridge = [r for r in rows if r["first_bridge_object"] is not None]
        reachable = [r for r in with_bridge if r["reachable_top8_any_level"]]
        usable = [r for r in reachable if r["bridge_completed_by_read"] is not None]
        arms = defaultdict(list)
        for r in rows:
            arms["all_pairs"].append(r["native_pair_quality"])
            cat = (
                "unknown_delivery"
                if r["full_set_delivered"] is None
                else "complete_evidence"
                if r["full_set_delivered"]
                else "incomplete_evidence"
            )
            arms[cat].append(r["native_pair_quality"])
            key = (
                "unknown_bridge"
                if r.get("delivered_bridge") is None
                else "bridge_delivered"
                if r["delivered_bridge"]
                else "bridge_missing"
            )
            arms[key].append(r["native_pair_quality"])
            arms[key + "__" + cat].append(r["native_pair_quality"])
        results.append(
            dict(
                run=str(path.resolve()),
                arm=cfg["arm"],
                total_registered_tasks=len(pop["tasks"]),
                answerable_native_groups=len(rows),
                annotated_first_bridges=len(with_bridge),
                later_uses_first_subanswer=sum(
                    r["later_uses_first_subanswer"] is True for r in with_bridge
                ),
                verified_top8_descriptors=sum(
                    r.get("top8_descriptors_verified") is True for r in rows
                ),
                reachable_complete_set=rate(
                    sum(r["complete_set_reachable"] is True for r in rows),
                    sum(r["complete_set_reachable"] is not None for r in rows),
                ),
                reachable_bridge=rate(len(reachable), len(with_bridge)),
                bridge_completed_given_reachable=rate(
                    sum(r["bridge_completed_by_read"] for r in usable), len(usable)
                ),
                native_pair_quality_by_evidence={
                    k: dict(
                        groups=len(v),
                        observed=sum(x is not None for x in v),
                        mean=mean(x for x in v if x is not None)
                        if any(x is not None for x in v)
                        else None,
                    )
                    for k, v in arms.items()
                },
                groups=rows,
            )
        )
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--collection", action="append", type=Path, default=[])
    p.add_argument("--arm", action="append", type=Path, default=[])
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not a.collection and not a.arm:
        p.error("Supply at least one closed TRAIN collection or DEV arm")
    ds = MemoryControlDataset(a.data)
    write_json(
        a.output,
        dict(
            dataset_run=ds.run_id,
            new_reader_requests=0,
            collections=[level_effects(ds, d) for d in a.collection],
            dev=bridge_effects(ds, a.arm),
        ),
    )


if __name__ == "__main__":
    main()
