"""Source-native identities and offline annotations for the three official corpora."""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import tarfile
import unicodedata
import zipfile
import zlib
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_acquire import csv_rows, history_file, reference
from milai_lab.datasets.memory_control_store import (
    SCHEMA,
    anomaly,
    connect,
    dumps,
    get_meta,
    packed,
    set_meta,
)

MUSIQUE = "musique_full"
QASPER = "qasper"
PERSONA = "personamem_v2"
PRIMING_PREFIX = "You are an AI assistant helping a user with the following persona:"
FLOAT = "FLOAT SELECTED"
SENT_SPACE = re.compile(r"\s+")


def normalized(text: str) -> str:
    return SENT_SPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def query_message(value: str) -> tuple[str, str]:
    try:
        message, encoding = json.loads(value), "json"
    except json.JSONDecodeError:
        message, encoding = ast.literal_eval(value), "python_literal"
    if (
        not isinstance(message, dict)
        or message.get("role") != "user"
        or not isinstance(message.get("content"), str)
        or not message["content"].strip()
    ):
        raise ValueError("Expected a nonempty user message")
    return message["content"], encoding


def bool_field(value: str) -> bool:
    if value not in {"True", "False"}:
        raise ValueError(f"Unexpected source boolean {value!r}")
    return value == "True"


def is_priming(role: str, content: str) -> bool:
    if role != "system" or not content.lstrip().startswith(PRIMING_PREFIX):
        return False
    suffix = content.lstrip()[len(PRIMING_PREFIX) :].lstrip()
    # The fixed release adds a structured persona object after the generation instruction.
    if suffix.startswith("```json"):
        suffix = suffix[len("```json") :].lstrip()
    try:
        persona, _ = json.JSONDecoder().raw_decode(suffix)
    except json.JSONDecodeError:
        return False
    return isinstance(persona, dict) and (not persona or "short_persona" in persona)


def load_messages(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise ValueError("Expected a message sequence")
    messages = []
    for message in value:
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("role"), str)
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError("Invalid role/content pair")
        messages.append((message["role"], message["content"]))
    return messages


History = list[tuple[str, str | None]]


def snippet_match(
    snippet: list[tuple[str, str]],
    history: History,
    mapping: list[int | None],
    normalized_history: History | None = None,
) -> dict[str, Any]:
    matches: list[list[int]] = []
    status = "unmatched"
    if snippet:
        keys = [(role, normalized(text)) for role, text in snippet]
        for query, source, grade in (
            (snippet, history, "exact"),
            (
                keys,
                normalized_history
                if normalized_history is not None
                else normalize_history(history),
                "normalized",
            ),
        ):
            matches = [
                list(range(i, i + len(query)))
                for i in range(len(source) - len(query) + 1)
                if source[i : i + len(query)] == query
            ]
            if matches:
                status = grade if len(matches) == 1 else "ambiguous"
                break
    return {
        "status": status,
        "raw_indices": matches,
        "processed_indices": [[mapping[i] for i in indices] for indices in matches],
    }


def normalize_history(history: History) -> History:
    return [(role, normalized(body) if body is not None else None) for role, body in history]


def source_history(value: list[Any]) -> History:
    messages = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("role"), str)
            or (item.get("content") is not None and not isinstance(item["content"], str))
        ):
            raise ValueError("Invalid source history role/content")
        messages.append((item["role"], item.get("content")))
    return messages


def root(
    db: sqlite3.Connection,
    source: str,
    group: str,
    raw_path: str,
    location: Any,
    details: Any = None,
) -> int:
    cursor = db.execute(
        "INSERT INTO roots(dataset,native_group,raw_path,location,details) VALUES (?,?,?,?,?)",
        (
            source,
            group,
            raw_path,
            dumps(location),
            packed(details) if details is not None else None,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def task(
    db: sqlite3.Connection,
    root_id: int,
    split: str,
    position: int,
    native: str,
    query: str,
    setting: str = "text_memory_control_v1",
) -> int:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Missing source query")
    cursor = db.execute(
        "INSERT INTO tasks(root_id,split,source_row,native_id,query,setting) VALUES (?,?,?,?,?,?)",
        (root_id, split, position, native, query, setting),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def obj(
    db: sqlite3.Connection,
    root_id: int,
    position: int,
    kind: str,
    location: Any,
    preview: str,
    body: str | None,
    *,
    role: str = "tool",
    block: int | None = None,
) -> int:
    if body is not None and not isinstance(body, str):
        raise ValueError("Source object body must be literal text")
    cursor = db.execute(
        "INSERT INTO objects(root_id,position,kind,role,location,preview,body,characters,block) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            root_id,
            position,
            kind,
            role,
            dumps(location),
            preview.rstrip()[:160],
            zlib.compress(body.encode(), 1) if body is not None else None,
            len(body or ""),
            block,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def annotate(db: sqlite3.Connection, task_id: int, data: Any) -> None:
    db.execute("INSERT INTO annotations VALUES(?,?)", (task_id, packed(data)))


def musique(
    db: sqlite3.Connection, path: Path, cfg: dict[str, Any], counts: dict[str, Any]
) -> None:
    with zipfile.ZipFile(path) as archive:
        for split, name in cfg["members"].items():
            count = counts[MUSIQUE][split]
            with archive.open(name) as records:
                for ordinal, line in enumerate(records):
                    count["raw"] += 1
                    try:
                        row = json.loads(line)
                        flags = row["answerable"]
                        if type(flags) is not bool:
                            raise ValueError("Expected explicit boolean answerable")
                        paragraphs = row["paragraphs"]
                        indices = [p["idx"] for p in paragraphs]
                        if (
                            not paragraphs
                            or len(set(indices)) != len(indices)
                            or any(type(p["is_supporting"]) is not bool for p in paragraphs)
                            or any(
                                not isinstance(p[k], str)
                                for p in paragraphs
                                for k in ("title", "paragraph_text")
                            )
                            or not isinstance(row["question"], str)
                            or not row["question"].strip()
                        ):
                            raise ValueError("Invalid official paragraph or question structure")
                    except (ValueError, KeyError, TypeError) as exc:
                        anomaly(
                            db,
                            MUSIQUE,
                            split,
                            None,
                            "invalid_record",
                            {"ordinal": ordinal, "error": str(exc)},
                        )
                        count["excluded"] += 1
                        continue
                    root_id = root(
                        db,
                        MUSIQUE,
                        row["id"],
                        cfg["archive"],
                        {"member": name, "original_split": split, "original_row_ordinal": ordinal},
                    )
                    tid = task(db, root_id, split, ordinal, row["id"], row["question"])
                    support: list[int] = []
                    for position, p in enumerate(paragraphs):
                        oid = obj(
                            db,
                            root_id,
                            position,
                            "paragraph",
                            {"paragraph_idx": p["idx"]},
                            p["title"],
                            p["paragraph_text"],
                        )
                        if p["is_supporting"]:
                            support.append(oid)
                    annotate(
                        db,
                        tid,
                        {
                            "answerable": flags,
                            "answer": row["answer"],
                            "answer_aliases": row["answer_aliases"],
                            "support_objects": support,
                            "question_decomposition": row["question_decomposition"],
                        },
                    )
                    count["normalized"] += 1
                    if count["raw"] % 512 == 0:
                        db.commit()
            count["source_parsed"] = True
            db.commit()
            print(f"{MUSIQUE}/{split}: {count['raw']} raw tasks", flush=True)


def alignment(
    text: str, bodies: list[tuple[int, str]], *, fragment: bool = False
) -> dict[str, Any]:
    """Text equality wins. Highlighted fragments use literal containment separately."""
    key = normalized(text)
    for grade in ("exact", "normalized"):
        needle = text if grade == "exact" else key
        if not needle.strip():
            continue
        matches = []
        for oid, raw in bodies:
            body = raw if grade == "exact" else normalized(raw)
            if needle == body or (fragment and needle in body):
                matches.append(oid)
        if matches:
            return {"status": grade if len(matches) == 1 else "ambiguous", "objects": matches}
    return {"status": "unmatched", "objects": []}


def align_qasper(
    text: str,
    paragraphs: list[tuple[int, str]],
    captions: list[tuple[int, str]],
    *,
    fragment: bool = False,
) -> dict[str, Any]:
    figure = text.lstrip().startswith(FLOAT)
    if figure:
        needle = text.lstrip()[len(FLOAT) :].lstrip(" :")
        result = alignment(needle, captions, fragment=fragment)
    else:
        result = alignment(text, paragraphs, fragment=fragment)
    return {"evidence_kind": "caption_only" if figure else "text", **result}


def qasper(
    db: sqlite3.Connection, path: Path, cfg: dict[str, Any], counts: dict[str, Any],
    *, groups: set[str] | None = None,
) -> None:
    with tarfile.open(path) as archive:
        for split, name in cfg["members"].items():
            count = counts[QASPER][split]
            stream = archive.extractfile(name)
            if stream is None:
                raise ValueError(f"Missing QASPER member {name}")
            with stream:
                papers = json.load(stream)
            if groups is not None:
                papers = {key: value for key, value in papers.items() if key in groups}
            count["raw_groups"] = len(papers)
            for paper_id, paper in papers.items():
                root_id = root(
                    db,
                    QASPER,
                    paper_id,
                    cfg["archive"],
                    {"member": name, "paper_id": paper_id},
                    {
                        "sections": [s["section_name"] for s in paper["full_text"]],
                        "figures_and_tables": paper["figures_and_tables"],
                    },
                )
                paragraphs, captions = [], []
                position = 0
                for kind in ("title", "abstract"):
                    body = paper.get(kind) or ""
                    oid = obj(db, root_id, position, kind, {"field": kind}, paper["title"], body)
                    paragraphs.append((oid, body))
                    position += 1
                for si, section in enumerate(paper["full_text"]):
                    heading = " / ".join(filter(None, (paper["title"], section["section_name"])))
                    for pi, body in enumerate(section["paragraphs"]):
                        location = {"section_index": si, "paragraph_index": pi}
                        oid = obj(
                            db, root_id, position, "paragraph", location, heading, body, block=si
                        )
                        paragraphs.append((oid, body))
                        position += 1
                for fi, figure in enumerate(paper["figures_and_tables"]):
                    body = figure["caption"] or ""
                    oid = obj(
                        db,
                        root_id,
                        position,
                        "caption_only",
                        {"figure_index": fi, "file": figure["file"], "image_present": False},
                        paper["title"] + " / Figure or table caption",
                        body,
                    )
                    captions.append((oid, body))
                    position += 1
                for qi, qa in enumerate(paper["qas"]):
                    count["raw"] += 1
                    tid = task(db, root_id, split, qi, qa["question_id"], qa["question"])
                    annotations = []
                    for ann in qa["answers"]:
                        answer = ann["answer"]
                        if answer["yes_no"] is not None and type(answer["yes_no"]) is not bool:
                            raise ValueError("QASPER yes/no must be nullable boolean")
                        converted = dict(ann)
                        for field in ("evidence", "highlighted_evidence"):
                            matches = [
                                align_qasper(
                                    line,
                                    paragraphs,
                                    captions,
                                    fragment=field == "highlighted_evidence",
                                )
                                for line in answer.get(field, [])
                            ]
                            converted[field + "_alignment"] = matches
                            for number, match in enumerate(matches):
                                if match["status"] in {"ambiguous", "unmatched"}:
                                    anomaly(
                                        db,
                                        QASPER,
                                        split,
                                        tid,
                                        field + "_" + match["status"],
                                        {
                                            "annotation_id": ann["annotation_id"],
                                            "position": number,
                                            **match,
                                        },
                                    )
                        annotations.append(converted)
                    annotate(db, tid, {"answer_annotations": annotations})
                    count["normalized"] += 1
                db.commit()
            count["source_parsed"] = True
            print(f"{QASPER}/{split}: {count['raw']} raw tasks", flush=True)


def persona_history(
    db: sqlite3.Connection, path: Path, link: str, account: str
) -> tuple[int, History, History, list[int | None], dict[int, int]]:
    data = history_file(path)
    metadata = data["metadata"]
    if str(metadata["persona_id"]) != account:
        raise ValueError("CSV persona_id differs from referenced history metadata")
    history = source_history(data["chat_history"])
    if metadata.get("total_messages") != len(history):
        raise ValueError("Source history metadata message count does not match its body")
    mapping: list[int | None] = []
    filtered: list[dict[str, Any]] = []
    selected: list[tuple[int, str, str]] = []
    for i, (role, body) in enumerate(history):
        if body is None:
            mapping.append(None)
            filtered.append({"raw_message_index": i, "reason": "source_content_absent"})
            anomaly(
                db,
                PERSONA,
                None,
                None,
                "source_content_absent",
                {"history": link, "raw_message_index": i, "role": role},
            )
            continue
        if is_priming(role, body):
            mapping.append(None)
            filtered.append({"raw_message_index": i, "reason": "generation_persona_priming"})
            continue
        if role == "system" and PRIMING_PREFIX in body:
            raise ValueError("Unrecognized persona priming structure")
        mapping.append(len(selected))
        selected.append((i, role, body))
    if not selected:
        raise ValueError("No dialogue remains")
    root_id = root(
        db,
        PERSONA,
        account,
        link,
        {"persona_id": account},
        {"raw_metadata": metadata, "raw_to_processed": mapping, "excluded_messages": filtered},
    )
    blocks: list[list[int]] = []
    ids = {}
    for position, (raw_i, role, body) in enumerate(selected):
        if not blocks or role == "user":
            blocks.append([])
        blocks[-1].append(position)
        ids[raw_i] = obj(
            db,
            root_id,
            position,
            "message",
            {"raw_message_index": raw_i, "processed_message_index": position},
            role + " message",
            body,
            role=role,
            block=len(blocks) - 1,
        )
    for block, members in enumerate(blocks):
        start, end = members[0], members[-1] + 1
        obj(
            db,
            root_id,
            len(selected) + block,
            "message_block",
            {
                "processed_message_range": [start, end],
                "raw_message_indices": [selected[j][0] for j in members],
            },
            "Contiguous conversation block",
            None,
            role="conversation",
            block=block,
        )
    return root_id, history, normalize_history(history), mapping, ids


def persona(
    db: sqlite3.Connection, raw: Path, cfg: dict[str, Any], counts: dict[str, Any],
    *, groups: set[str] | None = None,
) -> None:
    histories: dict[str, tuple[int, History, History, list[int | None], dict[int, int]]] = {}
    rejected: dict[tuple[str, str], str] = {}
    for split, name in cfg["members"].items():
        count = counts[PERSONA][split]
        if not (raw / name).is_file():
            continue
        personas, references = set(), set()
        for ordinal, entry in enumerate(csv_rows(raw / name)):
            account = entry["persona_id"]
            if groups is not None and account not in groups:
                continue
            count["raw"] += 1
            link = entry["chat_history_32k_link"]
            references.add(link)
            personas.add(account)
            try:
                query, parser = query_message(entry["user_query"])
                history_path = raw / reference(link)
                if (link, account) in rejected:
                    raise ValueError(rejected[link, account])
                if link not in histories:
                    try:
                        histories[link] = persona_history(db, history_path, link, account)
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        rejected[link, account] = str(exc)
                        raise
                root_id, history, normalized_history, mapping, ids = histories[link]
                if (
                    str(
                        db.execute(
                            "SELECT native_group FROM roots WHERE id=?", (root_id,)
                        ).fetchone()[0]
                    )
                    != account
                ):
                    raise ValueError("A history was referenced by more than one persona")
            except (OSError, ValueError, SyntaxError, KeyError, TypeError) as exc:
                anomaly(
                    db,
                    PERSONA,
                    split,
                    None,
                    "unusable_task",
                    {"ordinal": ordinal, "history": link, "error": str(exc)},
                )
                count["excluded"] += 1
                continue
            tid = task(
                db, root_id, split, ordinal, f"{name}:{ordinal}", query, cfg["observation_setting"]
            )
            try:
                snippet = load_messages(json.loads(entry["related_conversation_snippet"]))
                match = snippet_match(snippet, history, mapping, normalized_history)
            except (ValueError, KeyError, TypeError) as exc:
                match = {
                    "status": "unmatched",
                    "raw_indices": [],
                    "processed_indices": [],
                    "error": str(exc),
                }
            evidence = (
                [ids[i] for i in match["raw_indices"][0] if i in ids]
                if match["status"] in {"exact", "normalized"}
                else []
            )
            align_ok = bool(evidence) and len(evidence) == len(match["raw_indices"][0])
            if not align_ok:
                anomaly(db, PERSONA, split, tid, "snippet_" + match["status"], match)
            offline: dict[str, Any] = {}
            for field in ("expanded_persona", "incorrect_answers", "updated", "sensitive_info"):
                try:
                    value = (
                        bool_field(entry[field])
                        if field in {"updated", "sensitive_info"}
                        else json.loads(entry[field])
                    )
                    if field == "expanded_persona" and not isinstance(value, dict):
                        raise ValueError("Expanded persona must be an object")
                    if field == "incorrect_answers" and (
                        not isinstance(value, list)
                        or any(x is not None and not isinstance(x, str) for x in value)
                    ):
                        raise ValueError("Incorrect answers must be strings")
                    offline[field] = value
                    if field == "incorrect_answers" and isinstance(value, list) and None in value:
                        anomaly(
                            db,
                            PERSONA,
                            split,
                            tid,
                            "null_incorrect_option",
                            [i for i, option in enumerate(value) if option is None],
                        )
                except (ValueError, KeyError, TypeError) as exc:
                    offline[field] = None
                    anomaly(db, PERSONA, split, tid, "offline_field_" + field, str(exc))
            offline.update(
                {
                    k: (v or None)
                    for k, v in entry.items()
                    if k not in {*offline, "user_query", "related_conversation_snippet"}
                }
            )
            annotate(
                db,
                tid,
                {
                    **offline,
                    "csv_path": name,
                    "query_parser": parser,
                    "snippet_alignment": match,
                    "snippet_objects": evidence,
                    "snippet_fully_visible": align_ok,
                },
            )
            count["normalized"] += 1
            if count["raw"] % 256 == 0:
                db.commit()
        count.update(
            source_parsed=True, raw_groups=len(personas), raw_history_references=len(references)
        )
        db.commit()
        print(f"{PERSONA}/{split}: {count['raw']} raw tasks", flush=True)


def split_groups(db: sqlite3.Connection) -> dict[str, Any]:
    by_split: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in db.execute("SELECT DISTINCT dataset,split,native_group FROM task_index"):
        by_split[row["dataset"]][row["split"]].add(row["native_group"])
    overlap = {
        source: sorted(splits["train"] & (splits["validation"] | splits["dev"]))
        for source, splits in by_split.items()
    }
    db.execute(
        "UPDATE tasks SET clean_role = CASE WHEN split='train' THEN 'train' ELSE 'validation' END"
    )
    db.execute("""
        INSERT INTO exclusions
        SELECT t.id, 'native_group_present_in_official_validation'
        FROM task_index t JOIN
            (SELECT DISTINCT dataset, native_group FROM task_index WHERE split<>'train') v
        ON v.dataset=t.dataset AND v.native_group=t.native_group
        WHERE t.split='train'
    """)
    db.execute(
        "UPDATE tasks SET clean_role='excluded' WHERE id IN (SELECT task_id FROM exclusions)"
    )
    db.commit()
    return overlap


def normalize(db_path: Path, raw: Path, config: dict[str, Any]) -> dict[str, Any]:
    if db_path.exists():
        with closing(connect(db_path)) as previous:
            if get_meta(previous, "configuration") != config:
                raise ValueError("Use a different output path for a changed processing version")
            return dict(get_meta(previous, "raw_counts"))
    part = db_path.with_suffix(".normalizing")
    if part.exists():
        part.unlink()
    counts = {
        source: {
            split: {"raw": 0, "normalized": 0, "excluded": 0, "source_parsed": False}
            for split in cfg["members"]
        }
        for source, cfg in config["sources"].items()
    }
    with closing(connect(part, writable=True)) as db:
        db.executescript(SCHEMA)
        for source, handler in ((MUSIQUE, musique), (QASPER, qasper), (PERSONA, persona)):
            cfg = config["sources"][source]
            path = raw / source
            if "archive" in cfg:
                path /= cfg["archive"]
            if path.exists():
                try:
                    handler(db, path, cfg, counts)
                except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
                    anomaly(db, source, None, None, "source_parse_failure", str(exc))
                    db.commit()
        overlap = split_groups(db)
        for source, splits in counts.items():
            for split, count in splits.items():
                count["anomalies_at_normalize"] = db.execute(
                    "SELECT count(*) FROM anomalies WHERE dataset=? AND split=?", (source, split)
                ).fetchone()[0]
        set_meta(db, "configuration", config)
        set_meta(db, "raw_counts", counts)
        set_meta(db, "official_group_overlap", overlap)
        set_meta(db, "normalization_done", True)
        db.commit()
    part.replace(db_path)
    return counts
