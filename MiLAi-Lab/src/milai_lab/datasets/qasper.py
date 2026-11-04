"""Native QASPER papers as ordinary sources; answer/evidence annotations stay offline."""
from __future__ import annotations

import copy
import random
from collections import defaultdict
from typing import Any

QUESTION_PROMPT_PREFIX = (
    "Use the available paper to answer the question with source evidence. "
    "If the available material cannot establish an answer, explain the limitation.\n\n"
)


def given_question_request(question: str) -> dict[str, Any]:
    """Keep dataset task instructions outside a supplied retrieval query."""
    return {"query": question, "read_goal": {
        "purpose": "Answer the supplied paper question with original evidence",
        "evidence": ["original_source"],
    }}


def native_evidence_text(text: str) -> str:
    """The official QASPER reader's evidence normalization; source bodies stay literal."""
    return text.replace("\n", " ").strip()


def allocate_papers(train: dict[str, Any], dev: dict[str, Any], *, train_count: int,
                    dev_count: int, seed: int) -> list[dict[str, str]]:
    """Fix paper families before question/evidence selection; retain the native partitions."""
    if train.keys() & dev.keys():
        raise ValueError("A native paper identity appears in both train and dev")
    groups = []
    rng = random.Random(seed)  # noqa: S311 -- declared source allocation, not outcome selection
    for native_split, papers, count in (("train", train, train_count), ("dev", dev, dev_count)):
        order = sorted(papers)
        rng.shuffle(order)
        for index, paper_id in enumerate(order):
            groups.append({"paper_id": paper_id, "source_group": "qasper-paper-" + paper_id,
                "native_split": native_split, "split": native_split if index < count else "unused"})
    return groups


def paper_sources(paper_id: str, paper: dict[str, Any]) -> tuple[
        list[dict[str, Any]], dict[str, list[str]]]:
    sources = []
    text_locations: dict[str, list[str]] = defaultdict(list)

    def add(key: str, heading: str | None, body: str, *, textual: bool) -> None:
        event_id = paper_id + "/" + key
        lines = [paper["title"], *([heading] if heading is not None else []), body]
        sources.append({"session_id": paper_id, "event_key": key,
            "original_event_id": event_id, "role": "tool", "origin": "reference_document",
            "occurred_at": None, "content": "\n".join(lines)})
        if textual:
            text_locations[body].append(event_id)

    add("abstract", "Abstract", paper["abstract"], textual=True)
    for section_index, section in enumerate(paper["full_text"]):
        if section["section_name"] is not None:
            add(f"section-{section_index}-heading", "Section heading",
                section["section_name"], textual=True)
        for paragraph_index, text in enumerate(section["paragraphs"]):
            add(f"section-{section_index}-paragraph-{paragraph_index}",
                section["section_name"], text, textual=True)
    for index, figure in enumerate(paper["figures_and_tables"]):
        add(f"caption-{index}", "Figure/table caption (caption text only)",
            figure["caption"], textual=False)
    return sources, dict(text_locations)


def export_paper(paper_id: str, paper: dict[str, Any], split: str, *, max_questions: int = 2,
                 given_requests: bool = False,
                 ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Use native question order, not answerability or evidence position, to cap questions."""
    sources, locations = paper_sources(paper_id, paper)
    normalized: dict[str, list[str]] = defaultdict(list)
    for text, identifiers in locations.items():
        normalized[native_evidence_text(text)].extend(identifiers)
    family = "qasper-paper-" + paper_id
    requests, controls = [], []
    for index, qa in enumerate(paper["qas"][:max_questions]):
        request_id = f"question-{index}"
        request = {"id": request_id, "content": QUESTION_PROMPT_PREFIX + qa["question"]}
        if given_requests:
            request["retrieval_request"] = given_question_request(qa["question"])
        requests.append(request)
        annotations = []
        for annotation in qa["answers"]:
            answer = annotation["answer"]
            evidence = []
            for text in answer["evidence"]:
                normalized_text = native_evidence_text(text)
                nontext = normalized_text.startswith("FLOAT SELECTED")
                literal = locations.get(text, [])
                matches = ([] if nontext or not normalized_text else
                           literal or normalized.get(normalized_text, []))
                evidence.append({"native_evidence": text, "source_event_ids": list(matches),
                    "match_basis": ("literal" if literal else "native_newline_strip")
                                   if matches else None,
                    "status": "non_text_evidence" if nontext else
                              "matched_text" if matches else "unmatched_text"})
            annotations.append({"annotation_id": annotation["annotation_id"],
                "answer": copy.deepcopy(answer), "evidence": evidence})
        controls.append({"source_group": family, "split": split, "paper_id": paper_id,
            "request_id": request_id, "native_question_id": qa["question_id"],
            "annotations": annotations, "operation_labels": [],
            "scope": "Alternative human annotations kept separately. Text evidence locates "
                "positive support only; headers support header text, not entire sections. "
                "Unmarked paragraphs and unmatched/figure evidence remain "
                "unjudged. Unanswerable is not an operation label or an instruction to HANDOFF. "
                "Actual READ receipts and delivered materials must precede operation feedback."})
    # The existing Host runner uses history.id in a Store namespace (no periods).
    # Escape the runtime label reversibly; the native source identity stays unchanged.
    bank_id = family.replace("%", "%25").replace(".", "%2E")
    return {"id": bank_id, "source_group": family, "split": split,
            "continuous": False, "sources": sources, "requests": requests}, controls
