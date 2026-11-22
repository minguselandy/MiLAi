"""Check the revised delivery and observation semantics on real corpus bindings."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_normalize import QASPER
from milai_lab.datasets.memory_control_store import connect, get_meta, unpack
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.methods.memory_object_policy import object_control_texts


def audit_delivery(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    state_id: int,
) -> dict[str, Any]:
    observation, session, actions = dataset.replay(db, state_id)
    trial = next(
        (
            action
            for action, y, (fits, reason) in zip(
                actions,
                unpack(
                    db.execute(
                        "SELECT evidence FROM weak_labels WHERE state_id=?", (state_id,)
                    ).fetchone()[0]
                ),
                unpack(observation["action_feasibility"]),
                strict=True,
            )
            if y is True and fits is False and reason == "material_budget_exhausted"
        ),
        None,
    )
    if trial is None:
        raise ValueError("The registered real state has no over-budget positive binding")
    measured = session.feasibility(trial)
    before = session.ops.reader_evidence()
    if measured != (False, "material_budget_exhausted") or trial in session.feasible_menu(actions):
        raise ValueError("Precheck admitted a positive action with insufficient material budget")
    result = session.execute(trial, session.state)
    if result["ok"] or session.ops.reader_evidence() != before:
        raise ValueError("An overbudget READ altered the actual Reader material")
    return {
        "state_id": state_id,
        "action_id": trial.id,
        "evidence_gain": True,
        "delivery_feasible": False,
        "actual_execution": result["status"],
        "delivered_material_unchanged": True,
    }


def precision_trace(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    states: list[int],
) -> dict[str, Any]:
    assert dataset.host is not None
    result = {}
    for sid in states:
        row, session, actions = dataset.replay(db, sid)
        focus = next(
            (
                a
                for a in session.feasible_menu(actions)
                if a.kind == "READ"
                and not a.parameters.get("expand_context")
                and f"context_{a.parameters['index']}" in {b.id for b in actions}
            ),
            None,
        )
        if not focus:
            continue
        if not session.take(focus):
            raise ValueError("Actual focus read diverged from its precheck")
        next_actions = session.menu(row["control_steps"])
        expansion = next(
            (
                a
                for a in session.feasible_menu(next_actions)
                if a.id == f"context_{focus.parameters['index']}"
            ),
            None,
        )
        if not expansion:
            continue
        if not session.take(expansion):
            raise ValueError("Actual context read diverged from its precheck")
        measured = session.pool.normalized_delivery(session.ops.opened)
        replayed = session.ops.reader_evidence()
        if (
            replayed != measured.evidence
            or session.used_tokens != session.plan_packet(replayed).material_tokens
        ):
            raise ValueError("Actual Reader packet and union precheck disagree")
        previous = CorpusExecution(
            session.pool, row["query"], session.focus, dataset.reader, row["material_budget"]
        )
        try:
            previous.replay(row["control_steps"], session.prefix)
        except ValueError:
            legacy: dict[str, Any] = {"status": "legacy_trajectory_not_admitted"}
        else:
            legacy = {
                "status": "matched_actions",
                "legacy_tokens": previous.used_tokens,
                "normalized_tokens": session.used_tokens,
            }
        result = {
            "state_id": sid,
            "focus": focus.id,
            "expanded": expansion.id,
            "unique_source_chars": measured.unique_source_chars,
            "delivered_material_tokens": session.used_tokens,
            "fixed_trajectory": legacy,
        }
        break
    if not result:
        raise ValueError("No true same-candidate precision trajectory exercised")
    return result


def overlap_trace(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    states: list[int],
) -> dict[str, Any]:
    for sid in states:
        row, session, menu = dataset.replay(db, sid)
        reads = [a for a in session.feasible_menu(menu) if a.kind == "READ"]
        candidates = []
        for action in reads:
            view = session.pool.bound_view(session.focus, action)
            if view is not None:
                candidates.append((action, session.pool.views[view].ranges))
        for first, ranges in candidates:
            if first.parameters.get("expand_context"):
                continue
            for second, expanded in candidates:
                if (
                    not second.parameters.get("expand_context")
                    or second.parameters["index"] == first.parameters["index"]
                ):
                    continue
                overlap = any(
                    oid == target and max(a, c) < min(b, d)
                    for oid, a, b in ranges
                    for target, c, d in expanded
                )
                if not overlap:
                    continue
                _, actual, _ = dataset.replay(db, sid, session.pool)
                if not actual.take(first):
                    raise ValueError("The first selected Source prefix did not deliver")
                if second not in actual.feasible_menu(actual.menu(row["control_steps"])):
                    continue
                if not actual.take(second):
                    raise ValueError("The second candidate failed its exact precheck")
                merged = actual.pool.normalized_delivery(actual.ops.opened)
                if (
                    merged.overlap_before_normalization <= 0
                    or actual.used_tokens != actual.plan_packet(merged.evidence).material_tokens
                ):
                    raise ValueError("Cross-candidate literal union and Reader token cost diverged")
                return {
                    "state_id": sid,
                    "actions": [first.id, second.id],
                    "duplicate_chars_removed": merged.overlap_before_normalization,
                    "unique_source_chars": merged.unique_source_chars,
                    "delivered_material_tokens": actual.used_tokens,
                }
    raise ValueError("No cross-candidate overlap was exercised")


def validate_revision(path: Path) -> dict[str, Any]:
    dataset = MemoryControlDataset(path)
    metadata = MemoryControlDataset(path, observation_protocol="metadata_v1")
    revision = dataset.revision
    assert revision is not None
    with closing(connect(path)) as db:
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Broken revised Source, task, state or outcome reference")
        counts = dict(
            db.execute("""
            SELECT t.experiment_role,count(*) FROM state_variants v JOIN states s ON s.id=v.state_id
            JOIN experiment_tasks t ON t.id=s.task_id GROUP BY 1
        """)
        )
        if not counts or set(counts) - {"train", "dev"}:
            raise ValueError("Protected or excluded groups entered active states")
        parent_max = get_meta(db, "parent_state_max")
        parent_conflicts = db.execute(
            """
            SELECT count(*) FROM state_variants v JOIN states s ON s.id=v.state_id
            LEFT JOIN states p ON p.id=v.parent_state_id
            WHERE s.id<=? OR (p.id IS NOT NULL AND (p.id>? OR s.task_id<>p.task_id))
        """,
            (parent_max, parent_max),
        ).fetchone()[0]
        if parent_conflicts:
            raise ValueError("Revised state identity collides with the parent snapshot")
        over_budget = None
        qasper_states: list[int] = []
        for row in db.execute(
            """
            SELECT s.id,w.evidence,v.action_feasibility FROM state_variants v
            JOIN states s ON s.id=v.state_id JOIN weak_labels w ON w.state_id=s.id
            JOIN experiment_tasks t ON t.id=s.task_id
            WHERE t.dataset=? AND t.experiment_role='train' ORDER BY v.state_id
        """,
            (QASPER,),
        ):
            fits = unpack(row["action_feasibility"])
            known = unpack(row["evidence"])
            if over_budget is None and any(
                y is True and f is False and why == "material_budget_exhausted"
                for y, (f, why) in zip(known, fits, strict=True)
            ):
                over_budget = row["id"]
            if len(qasper_states) < 64:
                qasper_states.append(row["id"])
            if over_budget is not None and len(qasper_states) == 64:
                break
        if over_budget is None:
            raise ValueError("The data has no budget-separation witness")
        unavailable = audit_delivery(dataset, db, over_budget)
        precision = precision_trace(dataset, db, qasper_states)
        overlap = overlap_trace(dataset, db, qasper_states)
        sid = precision["state_id"]
        row, clean, menu = dataset.replay(db, sid)
        edited = dataset.start_task(
            db,
            row,
            clean.pool,
            clean.focus,
            row["material_budget"],
            annotation={
                "answer_annotations": [],
                "correct_answer": "changed",
                "gold_evidence": ["different offline annotation"],
            },
        )
        altered = edited.replay(row["control_steps"], unpack(row["prefix"]))
        original = object_control_texts(clean.online(clean.feasible_menu(menu)))
        changed = object_control_texts(edited.online(edited.feasible_menu(altered)))
        if original != changed:
            raise ValueError("Offline-only metadata changed actual navigation or encoder input")
        n0 = object_control_texts(metadata.encoder_rows([sid])[0])
        nav_texts = [text for text in original[0] if '"navigation_excerpt"' in text]
        if not nav_texts or n0 == original or any('"navigation_excerpt"' in text for text in n0[0]):
            raise ValueError("The matched N1 protocol failed to change only navigation exposure")
        saved_nav = unpack(
            db.execute(
                "SELECT excerpts FROM task_navigation WHERE task_id=?", (row["task_id"],)
            ).fetchone()[0]
        )
        for location in saved_nav.values():
            source = clean.pool.by_ref[location["source_ref"]]
            if (
                source.body[location["start"] : location["end"]] != location["text"]
                or location["encoder_tokens"] > revision["navigation_tokens_per_candidate"]
            ):
                raise ValueError("Navigation is not its declared bounded original substring")
        parent = db.execute(
            """
            SELECT p.candidates FROM state_variants v JOIN states p ON p.id=v.parent_state_id
            WHERE v.state_id=?
        """,
            (sid,),
        ).fetchone()
        if parent is None or unpack(parent[0]) != clean.focus:
            raise ValueError("Candidate identities or rank diverged from the frozen pool")
    return {
        "status": "DATA_REVISION_COMPLETE",
        "dataset_release": dataset.config["dataset_release"],
        "active_state_counts": counts,
        "parent_state_max": parent_max,
        "over_budget_evidence_witness": unavailable,
        "precision_witness": precision,
        "cross_candidate_overlap_witness": overlap,
        "navigation_check": {
            "state_id": sid,
            "n1_object_texts_with_navigation": len(nav_texts),
            "offline_field_edit_changed_input": False,
            "parent_order_equal": True,
        },
        "reader_requests_in_check": 0,
        "optimizer_updates_in_check": 0,
        "content_verification": "disabled",
    }
