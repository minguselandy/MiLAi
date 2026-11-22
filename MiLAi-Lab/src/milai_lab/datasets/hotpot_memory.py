"""Hotpot provided contexts as ordinary Sources; native annotations stay offline.

Data: CC BY-SA 4.0, https://hotpotqa.github.io/ . This memory-control
adaptation does not implement the official fullwiki or predicted-support metric.
"""
from __future__ import annotations

import random
import unicodedata
from collections import Counter
from typing import Any

PROMPT = ("Use the provided reference passages to answer the question with source evidence. "
          "If the available material cannot establish an answer, explain the limitation.\n\n")


def article_id(title: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", title).replace("_", " ").casefold().split())


def allocate_metadata(train: list[dict[str, Any]], validation_order: list[dict[str, Any]],
                      excluded: set[str], counts: dict[str, int], *, seed: int) -> dict[str, Any]:
    """Allocate roots before labels/feedback; every provided article remains disjoint."""
    roles: dict[str, list[dict[str, Any]]] = {name: [] for name in counts}
    used = set(excluded)
    rejected: Counter[str] = Counter()
    for row in validation_order:
        if len(roles["confirm"]) == counts["confirm"]:
            break
        titles = set(row["article_title_ids"])
        if not row["valid_titles"]:
            rejected["validation_invalid_title_identity"] += 1
        elif titles & used:
            rejected["validation_source_overlap"] += 1
        else:
            roles["confirm"].append(row)
            used.update(titles)
    rng = random.Random(seed)  # noqa: S311 -- prospective metadata allocation
    candidates = list(train)
    rng.shuffle(candidates)
    slots = [role for role in ("train", "dev_fit", "dev_select") for _ in range(counts[role])]
    rng.shuffle(slots)
    for row in candidates:
        if not slots:
            break
        titles = set(row["article_title_ids"])
        if not row["valid_titles"]:
            rejected["train_invalid_title_identity"] += 1
        elif titles & excluded:
            rejected["known_local_source_overlap"] += 1
        elif titles & used:
            rejected["reserved_or_selected_source_overlap"] += 1
        else:
            roles[slots.pop()].append(row)
            used.update(titles)
    selected_counts = {role: len(rows) for role, rows in roles.items()}
    complete = selected_counts == counts
    return {"status": "COMPLETE_METADATA_PARTITION" if complete else "INSUFFICIENT_DISJOINT_ROOTS",
        "seed": seed, "target_counts": counts, "selected_counts": selected_counts,
        "roles": roles, "rejected_before_feedback": dict(rejected),
        "excluded_local_article_ids": len(excluded),
        "confirm_status": "RESERVED_METADATA_ONLY_NOT_OPENED",
        "scope": "No question/answer/support text used for allocation; all context article "
                 "identities disjoint within and across roles, not just annotated supports",
        "sha_validation": False}


def export_question(row: dict[str, Any], split: str, *, ordinal: int,
                    seed: int = 20261117) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export literal paragraphs and sentence ranges, without revealing support labels."""
    if split not in {"train", "dev_fit", "dev_select"}:
        raise ValueError("Pilot exporter does not unseal confirmation roles")
    question_id = row["id"]
    titles, paragraphs = row["context"]["title"], row["context"]["sentences"]
    if not isinstance(question_id, str) or not question_id or not row["question"].strip():
        raise ValueError("Native question identity/text is missing")
    if len(titles) != len(paragraphs) or len({article_id(t) for t in titles}) != len(titles):
        raise ValueError("Native context title identities are ambiguous")
    order = list(range(len(titles)))
    random.Random(seed + ordinal * 104729).shuffle(order)  # noqa: S311 -- no label selection
    group = "hotpot-" + question_id
    sources, locations = [], {}
    for local_index, native_index in enumerate(order):
        title, sentences = titles[native_index], paragraphs[native_index]
        if not title or not isinstance(sentences, list) or not all(
                isinstance(sentence, str) for sentence in sentences):
            raise ValueError("Native source text is invalid")
        identifier = f"{group}/document-{local_index}"
        content = title + "\n" + "\n".join(sentences)
        offset = len(title) + 1
        for sentence_index, sentence in enumerate(sentences):
            locations[title, sentence_index] = {
                "original_event_id": identifier, "source_revision": 1,
                "start": offset, "end": offset + len(sentence),
                "native_title": title, "native_sentence_id": sentence_index}
            offset += len(sentence) + 1
        sources.append({"session_id": f"document-{local_index}", "event_key": "paragraph",
            "original_event_id": identifier, "role": "tool", "origin": "reference_document",
            "occurred_at": None, "content": content})
    support = row["supporting_facts"]
    if len(support["title"]) != len(support["sent_id"]):
        raise ValueError("Native support coordinates are inconsistent")
    spans = []
    for title, index in zip(support["title"], support["sent_id"], strict=True):
        span = locations.get((title, index))
        if span is None or span["end"] <= span["start"]:
            raise ValueError("Native support sentence is absent or empty")
        if span not in spans:
            spans.append(span)
    if not spans or not isinstance(row["answer"], str) or not row["answer"].strip():
        raise ValueError("Native answer/support reference is unavailable")
    request = {"id": "question", "query": row["question"],
        "content": PROMPT + row["question"], "source_event_ids": [
            source["original_event_id"] for source in sources],
        "retrieval_request": {"query": row["question"], "read_goal": {
            "purpose": "Answer the supplied question using original reference passages",
            "evidence": ["original_source"]}}}
    history = {"id": group, "source_group": group, "split": split, "dataset": "hotpot",
        "source_version": "HF-hotpotqa-distractor-provided-context-v1",
        "continuous": False, "sources": sources, "requests": [request]}
    # Whole-paragraph witnesses serve the existing structural collector only.
    # Sentence spans define the separately versioned adapted task outcome.
    needed = list(dict.fromkeys(span["original_event_id"] for span in spans))
    controls = {"schema": "source_reference_witness_v1", "source_group": group,
        "split": split, "request_id": "question", "native_question_id": question_id,
        "native_answerable": True, "native_answer": row["answer"],
        "reference_proofs": [[[event] for event in needed]],
        "reference_support_spans": spans,
        "native_type": row.get("type"), "native_level": row.get("level"),
        "metric_version": "native-answer-em-and-delivered-reference-spans-v1",
        "label_scope": "Human benchmark references plus literal delivery; not exhaustive "
                       "semantic sufficiency or official predicted-support jointEM"}
    return history, controls
