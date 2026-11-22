"""Audit source coverage, native identities, view ranges and action/supervision joins."""

from __future__ import annotations

import json
import sqlite3
import tarfile
import zipfile
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_acquire import csv_rows, history_file
from milai_lab.datasets.memory_control_normalize import (
    MUSIQUE,
    PERSONA,
    QASPER,
    is_priming,
    query_message,
)
from milai_lab.datasets.memory_control_store import body_text, get_meta, unpack
from milai_lab.datasets.memory_control_views import Span
from milai_lab.methods.memory_object_policy import object_control_texts


class Audit:
    def __init__(self) -> None:
        self.errors: Counter[str] = Counter()
        self.examples: dict[str, list[Any]] = defaultdict(list)
        self.measured: Counter[str] = Counter()

    def check(self, condition: bool, code: str, example: Any) -> None:
        if not condition:
            self.errors[code] += 1
            if len(self.examples[code]) < 8:
                self.examples[code].append(example)

    def tally(self, key: str, count: int = 1) -> None:
        self.measured[key] += count


def audit_musique(db: sqlite3.Connection, raw: Path, cfg: dict[str, Any], audit: Audit) -> None:
    if not (raw / cfg["archive"]).is_file():
        return
    with zipfile.ZipFile(raw / cfg["archive"]) as archive:
        for split, member in cfg["members"].items():
            saved = iter(
                db.execute(
                    """
                SELECT t.*,a.data FROM task_index t JOIN annotations a ON a.task_id=t.id
                WHERE t.dataset=? AND t.split=? ORDER BY t.source_row
            """,
                    (MUSIQUE, split),
                )
            )
            pairs: dict[str, tuple[bool, dict[int, tuple[str, str]]]] = {}
            closed = set()
            record = next(saved, None)
            with archive.open(member) as stream:
                for ordinal, line in enumerate(stream):
                    raw_row = json.loads(line)
                    audit.tally(f"{MUSIQUE}/{split}/raw")
                    audit.check(
                        record is not None and record["source_row"] == ordinal,
                        "music_original_row_missing",
                        (split, ordinal),
                    )
                    if record is None or record["source_row"] != ordinal:
                        continue
                    saved_annotation = unpack(record["data"])
                    audit.check(
                        raw_row["id"] == record["native_id"] == record["native_group"]
                        and raw_row["question"] == record["query"]
                        and saved_annotation["answerable"] is raw_row["answerable"]
                        and all(
                            saved_annotation[key] == raw_row[key]
                            for key in ("answer", "answer_aliases", "question_decomposition")
                        ),
                        "music_original_annotation_mismatch",
                        (split, ordinal),
                    )
                    audit.tally("weak_answerability/MuSiQue/known")
                    if raw_row["answer"] and not raw_row["answerable"]:
                        audit.tally("music_unanswerable_with_nonempty_answer")
                    body_by_idx, support, n_paragraphs = {}, [], 0
                    for index, (obj, src) in enumerate(
                        zip(
                            db.execute(
                                "SELECT * FROM objects WHERE root_id=? ORDER BY position",
                                (record["root_id"],),
                            ),
                            raw_row["paragraphs"],
                            strict=False,
                        )
                    ):
                        key = json.loads(obj["location"])["paragraph_idx"]
                        expected_body = src["paragraph_text"]
                        audit.check(
                            key == src["idx"]
                            and obj["position"] == index
                            and body_text(obj["body"]) == expected_body,
                            "music_paragraph_mismatch",
                            (split, ordinal, index),
                        )
                        n_paragraphs += 1
                        body_by_idx[src["idx"]] = (src["title"], expected_body)
                        if src["is_supporting"]:
                            support.append(obj["id"])
                    saved_count = db.execute(
                        "SELECT count(*) FROM objects WHERE root_id=?", (record["root_id"],)
                    ).fetchone()[0]
                    audit.check(
                        n_paragraphs == saved_count == len(raw_row["paragraphs"])
                        and support == saved_annotation["support_objects"],
                        "music_support_or_paragraph_count",
                        (split, ordinal),
                    )
                    identity = raw_row["id"]
                    audit.check(identity not in closed, "music_more_than_two_versions", identity)
                    first = pairs.pop(identity, None)
                    if first is None:
                        pairs[identity] = (raw_row["answerable"], body_by_idx)
                    else:
                        closed.add(identity)
                        audit.check(
                            first[0] is not raw_row["answerable"],
                            "music_pair_missing_variant",
                            identity,
                        )
                        if first[1] != body_by_idx:
                            audit.tally("music_pairs_with_different_material")
                    record = next(saved, None)
            audit.tally(f"{MUSIQUE}/{split}/verified_pairs", len(closed))
            audit.check(
                not pairs and record is None, "music_unpaired_or_extra_tasks", (split, len(pairs))
            )


def audit_qasper(db: sqlite3.Connection, raw: Path, cfg: dict[str, Any], audit: Audit) -> None:
    if not (raw / cfg["archive"]).is_file():
        return
    with tarfile.open(raw / cfg["archive"]) as archive:
        for split, member in cfg["members"].items():
            file = archive.extractfile(member)
            assert file is not None
            with file:
                papers = json.load(file)
            for paper_id, raw_paper in papers.items():
                roots = db.execute(
                    "SELECT id,details FROM roots WHERE dataset=? AND native_group=?",
                    (QASPER, paper_id),
                ).fetchall()
                if len(roots) > 1:
                    roots = [
                        row
                        for row in roots
                        if db.execute(
                            "SELECT 1 FROM tasks WHERE root_id=? AND split=? LIMIT 1",
                            (row["id"], split),
                        ).fetchone()
                    ]
                audit.check(len(roots) == 1, "qasper_paper_identity", paper_id)
                if len(roots) != 1:
                    continue
                root = roots[0]
                details = unpack(root["details"])
                audit.check(
                    details["figures_and_tables"] == raw_paper["figures_and_tables"]
                    and details["sections"] == [s["section_name"] for s in raw_paper["full_text"]],
                    "qasper_document_boundaries",
                    paper_id,
                )
                literal_objects: dict[tuple[Any, ...], tuple[int, str]] = {}
                for obj in db.execute("SELECT * FROM objects WHERE root_id=?", (root["id"],)):
                    location = json.loads(obj["location"])
                    key: tuple[Any, ...]
                    if "section_index" in location:
                        key = ("paragraph", location["section_index"], location["paragraph_index"])
                    elif "figure_index" in location:
                        key = ("caption", location["figure_index"])
                        figure = raw_paper["figures_and_tables"][location["figure_index"]]
                        audit.check(
                            not location["image_present"] and location["file"] == figure["file"],
                            "qasper_caption_reference",
                            obj["id"],
                        )
                    else:
                        key = (obj["kind"],)
                    literal_objects[key] = (obj["id"], body_text(obj["body"]))
                originals: dict[tuple[Any, ...], str] = {
                    (kind,): raw_paper[kind] or "" for kind in ("title", "abstract")
                }
                originals.update(
                    {
                        ("paragraph", si, pi): text
                        for si, section in enumerate(raw_paper["full_text"])
                        for pi, text in enumerate(section["paragraphs"])
                    }
                )
                originals.update(
                    {
                        ("caption", fi): figure["caption"] or ""
                        for fi, figure in enumerate(raw_paper["figures_and_tables"])
                    }
                )
                audit.check(
                    {key: body for key, (_, body) in literal_objects.items()} == originals,
                    "qasper_paragraph_or_caption_changed",
                    paper_id,
                )
                text_objects = {
                    oid for key, (oid, _) in literal_objects.items() if key[0] != "caption"
                }
                caption_objects = {
                    oid for key, (oid, _) in literal_objects.items() if key[0] == "caption"
                }
                grouped = {
                    task["native_id"]: task
                    for task in db.execute(
                        """
                    SELECT t.*,a.data FROM tasks t JOIN annotations a ON a.task_id=t.id
                    WHERE t.root_id=? AND t.split=?
                """,
                        (root["id"], split),
                    )
                }
                audit.check(
                    len(grouped) == len(raw_paper["qas"]), "qasper_question_count", paper_id
                )
                for question in raw_paper["qas"]:
                    audit.tally(f"{QASPER}/{split}/raw")
                    task = grouped.get(question["question_id"])
                    if task is None:
                        audit.check(False, "qasper_missing_question", question["question_id"])
                        continue
                    saved = unpack(task["data"])["answer_annotations"]
                    answers = [
                        {k: v for k, v in item.items() if not k.endswith("_alignment")}
                        for item in saved
                    ]
                    audit.check(
                        answers == question["answers"] and task["query"] == question["question"],
                        "qasper_annotation_changed",
                        task["id"],
                    )
                    flags = {item["answer"]["unanswerable"] for item in saved}
                    if len(flags) > 1:
                        audit.tally("qasper_mixed_answerability_tasks")
                    if len(saved) > 1:
                        audit.tally("qasper_multi_annotation_tasks")
                    kinds = set()
                    for item in saved:
                        audit.tally("weak_answerability/QASPER/known")
                        value = item["answer"]["yes_no"]
                        if value is False:
                            audit.tally("qasper_no_answers")
                        if item["answer"]["unanswerable"]:
                            audit.tally("qasper_unanswerable_annotations")
                        for field in ("evidence", "highlighted_evidence"):
                            aligned = item[field + "_alignment"]
                            audit.check(
                                len(aligned) == len(item["answer"].get(field, [])),
                                "qasper_evidence_position_missing",
                                task["id"],
                            )
                            for match in aligned:
                                audit.tally(f"{QASPER}/{split}/{field}/{match['status']}")
                                if field == "evidence" and not item["answer"]["unanswerable"]:
                                    kinds.add(match["evidence_kind"])
                                if match["evidence_kind"] == "caption_only":
                                    audit.tally(f"qasper_caption_only_{field}")
                                candidates = (
                                    caption_objects
                                    if match["evidence_kind"] == "caption_only"
                                    else text_objects
                                )
                                audit.check(
                                    set(match["objects"]) <= candidates,
                                    "qasper_evidence_object_boundary",
                                    task["id"],
                                )
                                if match["status"] == "ambiguous":
                                    audit.check(
                                        len(match["objects"]) > 1,
                                        "qasper_ambiguous_hidden_matches",
                                        task["id"],
                                    )
                    if kinds == {"caption_only"}:
                        audit.tally("qasper_figure_only_tasks")


def audit_persona(db: sqlite3.Connection, raw: Path, cfg: dict[str, Any], audit: Audit) -> None:
    roots = {}
    for root in db.execute("SELECT * FROM roots WHERE dataset=?", (PERSONA,)):
        entry = history_file(raw / root["raw_path"])
        details = unpack(root["details"])
        messages = entry["chat_history"]
        audit.check(
            str(entry["metadata"]["persona_id"]) == root["native_group"]
            and details["raw_metadata"] == entry["metadata"],
            "persona_history_identity",
            root["raw_path"],
        )
        mapping = details["raw_to_processed"]
        expected_indices = list(range(len([x for x in mapping if x is not None])))
        audit.check(
            len(mapping) == len(messages)
            and [x for x in mapping if x is not None] == expected_indices,
            "persona_index_map",
            root["raw_path"],
        )
        reason = {r["raw_message_index"]: r["reason"] for r in details["excluded_messages"]}
        objects = {
            json.loads(row["location"])["raw_message_index"]: row
            for row in db.execute(
                "SELECT * FROM objects WHERE root_id=? AND kind='message'", (root["id"],)
            )
        }
        for i, message in enumerate(messages):
            literal = message.get("content")
            if literal is None:
                expected_reason = "source_content_absent"
            elif is_priming(message["role"], literal):
                expected_reason = "generation_persona_priming"
            else:
                expected_reason = None
            if expected_reason:
                audit.tally("persona_messages_" + expected_reason)
                audit.check(
                    mapping[i] is None and reason.get(i) == expected_reason and i not in objects,
                    "persona_priming_or_missing_leak",
                    (root["id"], i),
                )
            else:
                saved = objects.get(i)
                audit.check(
                    saved is not None
                    and saved["position"] == mapping[i]
                    and saved["role"] == message["role"]
                    and body_text(saved["body"]) == literal,
                    "persona_message_content_or_order",
                    (root["id"], i),
                )
                if message["role"] == "system":
                    audit.tally("persona_nonpriming_system_retained")
        roots[root["raw_path"]] = (root["native_group"], mapping)
    audit.tally("persona_unique_histories", len(roots))
    for split, member in cfg["members"].items():
        if not (raw / member).is_file():
            continue
        saved_tasks = {
            r["source_row"]: r
            for r in db.execute(
                """
            SELECT t.*,a.data FROM task_index t JOIN annotations a ON a.task_id=t.id
            WHERE t.dataset=? AND t.split=?
        """,
                (PERSONA, split),
            )
        }
        for ordinal, entry in enumerate(csv_rows(raw / member)):
            audit.tally(f"{PERSONA}/{split}/raw")
            task = saved_tasks.get(ordinal)
            if task is None:
                audit.check(False, "persona_task_unavailable", (split, ordinal))
                continue
            query, parser = query_message(entry["user_query"])
            saved = unpack(task["data"])
            reference = entry["chat_history_32k_link"]
            group, mapping = roots[reference]
            audit.check(
                task["query"] == query
                and saved["query_parser"] == parser
                and task["raw_path"] == reference
                and group == task["native_group"] == entry["persona_id"],
                "persona_query_or_history_reference",
                task["id"],
            )
            audit.tally(f"{PERSONA}/{split}/query/{parser}")
            for key in ("updated", "sensitive_info"):
                expected = entry[key] == "True"
                audit.check(
                    saved[key] is expected, "persona_native_bool_changed", (task["id"], key)
                )
                audit.tally(f"{PERSONA}/{split}/{key}/{saved[key]}")
            audit.tally(f"{PERSONA}/{split}/who/{saved['who']}")
            for key in ("preference", "prev_pref", "who", "updated", "sensitive_info"):
                grade = "unknown" if saved[key] is None else "known"
                audit.tally(f"weak_preference/PersonaMem/{key}/{grade}")
            match = saved["snippet_alignment"]
            audit.tally(f"{PERSONA}/{split}/snippet/{match['status']}")
            audit.check(
                [[mapping[i] for i in indices] for indices in match["raw_indices"]]
                == match["processed_indices"],
                "persona_snippet_index_map",
                task["id"],
            )
            if match["status"] not in {"exact", "normalized"}:
                audit.check(
                    not saved["snippet_objects"], "persona_unknown_mapped_to_positive", task["id"]
                )


def additional_ranges(wanted: list[Span], admitted: dict[int, list[tuple[int, int]]]) -> bool:
    for oid, left, right in wanted:
        position = left
        for start, end in sorted(admitted.get(oid, [])):
            if start > position:
                break
            position = max(position, end)
        if position < right:
            return True
    return False


def audit_views_states(
    db: sqlite3.Connection, config: dict[str, Any], audit: Audit
) -> dict[tuple[str, str], Counter[str]]:
    stats: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    maximum_objects = get_meta(db, "tokenizers")["encoder"]["maximum_memory_objects"]
    for root in db.execute("SELECT id,dataset FROM roots ORDER BY id"):
        rid, source = root
        objects = {
            r["id"]: r
            for r in db.execute(
                "SELECT id,position,characters,kind FROM objects WHERE root_id=?", (rid,)
            )
        }
        view_ranges: dict[int, list[Span]] = {}
        base: dict[int, int | None] = {}
        body_pages: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for view in db.execute(
            """
            SELECT v.*,c.focus_id,c.context_id,c.equivalence
            FROM views v JOIN objects o ON o.id=v.object_id
            LEFT JOIN candidates c ON c.focus_id=v.id WHERE o.root_id=?
        """,
            (rid,),
        ):
            vid = view["id"]
            ranges = [tuple(span) for span in unpack(view["ranges"])]
            view_ranges[vid] = ranges
            audit.tally(f"views_{view['tier']}")
            audit.check(
                view["reader_tokens"] >= 0 and view["encoder_tokens"] >= 0, "view_token_count", vid
            )
            if view["tier"] != "preview":
                audit.check(
                    bool(ranges)
                    and all(
                        oid in objects and 0 <= start < end <= objects[oid]["characters"]
                        for oid, start, end in ranges
                    ),
                    "view_object_range_mismatch",
                    vid,
                )
            if view["tier"] == "R2":
                oid, start, end = ranges[0]
                body_pages[oid].append((start, end))
                base[vid] = view["context_id"]
                if view["context_id"] is None:
                    audit.tally("view_equivalence_" + (view["equivalence"] or "missing_reason"))
                if view["method"] == "literal_page":
                    audit.tally("literal_read_pages")
            if view["tier"] == "R3":
                audit.tally("real_context_pages")
        for oid, parts in body_pages.items():
            ordered = sorted(parts)
            audit.check(
                ordered[0][0] == 0
                and ordered[-1][1] == objects[oid]["characters"]
                and all(a[1] == b[0] for a, b in pairwise(ordered)),
                "object_body_pagination_gap",
                oid,
            )
        for fid, cid in base.items():
            if cid is None:
                continue
            coverage: dict[int, list[tuple[int, int]]] = defaultdict(list)
            for oid, start, end in view_ranges.get(cid, []):
                coverage[oid].append((start, end))
            focus = view_ranges[fid][0]
            audit.check(
                not additional_ranges([focus], coverage)
                and additional_ranges(view_ranges.get(cid, []), {focus[0]: [focus[1:]]}),
                "context_repeats_or_loses_focus",
                (fid, cid),
            )
            audit.tally("real_context_bindings")
        for row in db.execute(
            """
            SELECT s.*,t.split,t.clean_role,w.evidence,w.corpus_coverage,j.protocol
            FROM tasks t JOIN states s ON s.task_id=t.id
            LEFT JOIN weak_labels w ON w.state_id=s.id
            LEFT JOIN rollout_jobs j ON j.state_id=s.id WHERE t.root_id=?
        """,
            (rid,),
        ):
            sid = row["id"]
            counter = stats[source, row["split"]]
            counter["states"] += 1
            counter["clean_states"] += row["clean_role"] != "excluded"
            counter["sampling_" + row["sampling"]] += 1
            counter["coverage_" + row["corpus_coverage"]] += 1
            audit.check(row["protocol"] is not None, "state_missing_rollout_job", sid)
            focus = unpack(row["candidates"])
            if (
                not focus
                or len(focus) != len(set(focus))
                or len(focus) > config["states"]["candidate_limit"]
                or not all(vid in base for vid in focus)
            ):
                audit.check(False, "state_candidate_view_mismatch", sid)
                continue
            prefix = unpack(row["prefix"])
            actions = unpack(row["actions"])
            evidence = unpack(row["evidence"])
            delivered = dict(unpack(row["delivered"]))
            prefix_bindings = {
                name: (i, vid)
                for i, fid in enumerate(focus)
                for name, vid in ((f"read_{i}", fid), (f"context_{i}", base[fid]))
                if vid is not None
            }
            expected_delivered = dict(
                prefix_bindings[name] for name in prefix[1:] if name in prefix_bindings
            )
            audit.check(
                prefix[:1] == ["search"]
                and len(prefix) == len(set(prefix)) < row["control_steps"]
                and all(name in prefix_bindings for name in prefix[1:])
                and expected_delivered == delivered,
                "state_prefix_or_delivered_mismatch",
                sid,
            )
            covered: dict[int, list[tuple[int, int]]] = defaultdict(list)
            for vid in delivered.values():
                for oid, start, end in view_ranges.get(vid, []):
                    covered[oid].append((start, end))
            expected = []
            for identifier, (i, view) in prefix_bindings.items():
                expanded = identifier.startswith("context")
                if identifier not in prefix and additional_ranges(view_ranges[view], covered):
                    expected.append(
                        {
                            "id": identifier,
                            "kind": "READ",
                            "target": f"candidate {i}" + (" context" if expanded else ""),
                            "parameters": {
                                "index": i,
                                **({"expand_context": True} if expanded else {}),
                            },
                        }
                    )
            expected.append(
                {
                    "id": "handoff",
                    "kind": "HANDOFF",
                    "target": "Reader with opened evidence",
                    "parameters": {},
                }
            )
            audit.check(actions == expected, "state_action_binding_mismatch", sid)
            audit.check(
                len(evidence) == len(actions)
                and all(
                    v is None or (type(v) is bool and a["kind"] == "READ")
                    for a, v in zip(actions, evidence, strict=False)
                ),
                "state_unknown_mask_mismatch",
                sid,
            )
            audit.check(
                row["object_count"] <= maximum_objects
                and 0 < row["material_tokens"] <= config["views"]["reader_material_tokens"],
                "state_capacity",
                sid,
            )
            counter["weak_rows"] += any(v is not None for v in evidence)
            counter["weak_evidence_known"] += sum(v is not None for v in evidence)
            counter["weak_evidence_positive"] += sum(v is True for v in evidence)
            counter["weak_evidence_unknown"] += sum(v is None for v in evidence)
            counter["legal_actions"] += len(actions)
    return stats


def sampled_projection(rows: list[dict[str, Any]], audit: Audit) -> None:
    forbidden = {
        "answerable",
        "answer",
        "answers",
        "correct_answer",
        "weak_evidence",
        "provenance",
        "group_id",
        "original_split",
        "source_row",
        "expanded_persona",
        "short_persona",
        "who",
        "updated",
        "sensitive_info",
        "snippet_alignment",
        "future_history",
        "paragraph_support_idx",
        "question_decomposition",
    }

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    for row in rows:
        online = {k: row[k] for k in ("observation", "actions")}
        audit.check(not (keys(online) & forbidden), "online_supervision_fields", row["sample_id"])
        audit.check(
            object_control_texts(row) == object_control_texts(online),
            "encoder_observes_offline_metadata",
            row["sample_id"],
        )
        audit.tally("native_online_sample_checks")
