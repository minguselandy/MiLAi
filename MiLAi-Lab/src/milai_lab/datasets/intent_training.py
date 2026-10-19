"""Source-only adapters for the registered Host-intent collection.

Answers, support flags and old judgments remain outside the public histories.
These adapters do not label operations or manufacture generated memory views.
"""
from __future__ import annotations

import copy
from typing import Any

SOURCE_FIELDS = ("session_id", "event_key", "original_event_id", "role", "origin", "content",
                 "occurred_at", "calendar_context")


def memops_intent_history(history: dict[str, Any]) -> dict[str, Any]:
    """Keep first/last arrival cuts, including every intervening literal source."""
    arrivals = [i for i, step in enumerate(history["steps"]) if step["incoming_sources"]]
    selected = [arrivals[0], arrivals[-1]]
    previous = -1
    requests = []
    for index in selected:
        step = history["steps"][index]
        incoming = [copy.deepcopy({key: source[key] for key in SOURCE_FIELDS if key in source})
                    for event in history["steps"][previous + 1:index + 1]
                    for source in event["incoming_sources"]]
        requests.append({"id": step["id"], "content": step["content"],
            "incoming_sources": incoming,
            **{key: step[key] for key in ("occurred_at", "query_time", "calendar_context")
               if key in step}})
        previous = index
    return {"id": history["id"], "source_group": history["source_family"],
            "split": history["split"], "continuous": True, "sources": [], "requests": requests}


def musique_intent_request(row: dict[str, Any], row_index: int) -> dict[str, Any]:
    """All actual paragraphs are visible inputs; reference answers/support are not."""
    sources = [{"session_id": f"document-{i}", "event_key": "document",
                "original_event_id": f"document-{i}", "role": "tool",
                "origin": "reference_document", "occurred_at": None,
                "content": paragraph["title"] + "\n" + paragraph["paragraph_text"]}
               for i, paragraph in enumerate(row["paragraphs"])]
    return {"id": f"corpus-{row_index}", "content": (
        "Use the available reference documents to answer this question, retrieving evidence "
        "first. If needed evidence is absent, state what cannot be established.\n\n"
        + row["question"]), "sources": sources}


def add_storage_requests(history: dict[str, Any]) -> dict[str, Any]:
    """Controlled literal-record contrasts within an already allocated source group.

    The record is an explicit fixture artifact, not an ideal semantic summary.
    Original arrival queries stay unchanged; each storage query gets its own bank.
    """
    result = copy.deepcopy(history)
    sources = [copy.deepcopy(source) for request in history["requests"]
               for source in request["incoming_sources"]]
    for source in sources:
        source["original_event_id"] = source["session_id"] + "/" + source["event_key"]
    user = [source for source in sources if source["role"] == "user"]
    revisions = [{"record": "conversation", "source_event_id": source["original_event_id"],
                  "text": source["content"], "scope": {"artifact": "retained conversation record"}}
                 for source in (user[0], user[-1])]
    for kind, question in (
        ("current", "What exactly is currently stored in the retained conversation record? "
                    "Report its stored content rather than reconstruct a better summary."),
        ("first", "What exactly was stored in the first saved version of the retained "
                  "conversation record? Retrieve the actual stored version, rather than "
                  "infer what was saved from the conversation alone."),
    ):
        result["requests"].append({"id": "record-" + kind, "content": question,
            "independent": True, "sources": sources, "stored_revisions": revisions})
    return result
