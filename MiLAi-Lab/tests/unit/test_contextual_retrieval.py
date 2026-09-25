"""Shared ranking, exact source pages, and bounded linked materials."""

from __future__ import annotations

import hashlib
import json

from milai_lab.methods.contextual_memory.material_view import MaterialView
from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_memory.retrieval import IndexEntry, _bm25_scores, index_entries
from milai_lab.methods.contextual_user_memory import ContextualMemory


def memory(*, linked: bool = False) -> ContextualMemory:
    result = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, material_mode="linked" if linked else "plain",
    )
    result.start_task("one", "question")
    return result


def test_chinese_phrase_and_mixed_identifier_have_lexical_recall_without_vectors() -> None:
    entries = [
        IndexEntry("other", "other", "下周开会讨论办公室安排"),
        IndexEntry("target", "target", "项目Alpha的文档必须包含风险说明和验收结果"),
    ]
    for query in ("风险说明", "Alpha风险", "险"):
        scores = _bm25_scores(entries, query)
        assert scores[1] > scores[0] == 0


def test_bm25_term_frequency_and_two_distant_exact_excerpts() -> None:
    mem = memory()
    frequent = mem.publish(Observation("a", "cobalt cobalt cobalt", "user", "file"))
    single = mem.publish(Observation("b", "cobalt", "user", "file"))
    assert mem._rank("cobalt", records=False).refs[0] == frequent
    body = "x" * 1024 + " alphaunique " + "x" * 4500 + " betaunique " + "x" * 1024
    source = mem.publish(Observation("long", body, "user", "file"))
    ranking = mem._rank("alphaunique betaunique", records=False)
    packet = mem._material(source, ranking.spans)
    assert len(packet["excerpts"]) == 2
    assert "content" not in packet and "page" not in packet
    for excerpt in packet["excerpts"]:
        page = excerpt["page"]
        assert excerpt["content"] == body[page["start"] : page["end"]]
        assert page["content_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert packet["excerpts"][0]["page"]["end"] < packet["excerpts"][1]["page"]["start"]
    mem.material_mode = "linked"
    compact = mem._material(source, ranking.spans, max_bytes=500)
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= 500
    assert compact["requires_expansion"]
    assert single in mem._rank("cobalt", records=False).refs


def test_date_filter_pending_and_stable_source_sequence_after_restore() -> None:
    mem = memory()
    first = mem.publish(Observation("a", "first", "user", "file", "session", "2024-01-02"))
    unknown = mem.publish(Observation("b", "unknown", "user", "file", "session"))
    outside = mem.publish(Observation("c", "outside", "user", "file", "session", "2025-01-02"))
    entries, pending = index_entries(
        mem, records=False, date_from="2024-01-01", date_to="2024-12-31",
        session_id="session",
    )
    assert [entry.ref for entry in entries] == [first, unknown]
    assert pending == {unknown}
    for ref in (first, unknown, outside):
        mem.save(source_ref=ref)
    restored = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=mem.embed)
    assert restored.source_sequence == mem.source_sequence
    assert restored.next_source_sequence == mem.next_source_sequence


def test_linked_neighbor_correction_respects_known_prefix_and_budget() -> None:
    mem = memory(linked=True)
    anchor = mem.publish(Observation("a", "Meet at station", "user", "file", "session"))
    neighbor = mem.publish(Observation("b", "The train is at nine", "user", "file", "session"))
    before = mem.last_known_at
    correction = mem.publish(Observation(
        "b2", "Correction: the train is at ten", "user", "file", "session",
        supersedes=neighbor,
    ))
    old = mem.read(anchor, include_sources=False, known_at=before, neighbor_window=1)
    assert {item["ref"] for item in old["associated_materials"]} == {neighbor}
    assert correction not in str(old)
    current = mem.read(anchor, include_sources=False, neighbor_window=1)
    associated = {item["ref"]: item for item in current["associated_materials"]}
    assert associated[correction]["relation"] == "session_neighbor_correction"
    assert associated[neighbor]["relation"] == "session_next"
    compact = mem.read(anchor, include_sources=False, neighbor_window=1, max_bytes=500)
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= 500
    assert correction in (
        {item["ref"] for item in compact["associated_materials"]}
        | set(compact["unexpanded_associated_refs"])
    )
    for item in compact["associated_materials"]:
        if item["ref"] == correction:
            assert item["content"] == "Correction: the train is at ten"
    if correction in compact["required_associated_refs"]:
        assert compact.get("content", "") == ""


def test_plain_ordinary_revision_links_exact_old_and_new_interpretation() -> None:
    mem = memory(linked=True)
    source = mem.publish(Observation("a", "Original wording", "user", "file"))
    old = mem.save(content="Initial interpretation", source_ref=source)["record"]["ref"]
    known_before = mem.last_known_at
    new = mem.save(target_ref=old, content="Corrected interpretation")["record"]["ref"]
    assert new in {item["ref"] for item in mem.read(old)["associated_materials"]}
    assert new in {item["ref"] for item in mem.read(source)["associated_materials"]}
    assert new not in str(mem.read(old, known_at=known_before))
    assert source in {item["ref"] for item in mem.read(new)["associated_materials"]}


def test_plain_old_source_requires_its_current_revision_without_linked_neighbors() -> None:
    mem = memory()
    source = mem.publish(Observation(
        "first", "legacy-marker: use three sections A, B, C", "user", "file", "session",
    ))
    neighbor = mem.publish(Observation(
        "nearby", "unrelated session neighbor", "user", "file", "session",
    ))
    old = mem.save(content="The sections are A, B, C", source_ref=source)["record"]["ref"]
    known_before = mem.last_known_at
    correction = mem.publish(Observation(
        "correction", "Section C is now D", "user", "file", "session",
    ))
    current_text = "The sections are A, B, D; C is no longer required. " * 30
    current = mem.save(
        target_ref=old, content=current_text, source_ref=correction,
    )["record"]["ref"]

    old_packet = mem.read(source, include_sources=False, known_at=known_before)
    assert [(item["ref"], item["relation"]) for item in
            old_packet["associated_materials"]] == [
        (old, "direct_interpretation"),
    ]
    packet = mem.read(source, include_sources=False, neighbor_window=1)
    assert [(item["ref"], item["relation"]) for item in packet["associated_materials"]] == [
        (current, "revised_interpretation"),
    ]
    assert neighbor not in str(packet)
    projected = MaterialView("ordinary", mem).project(packet, max_bytes=8000)
    assert [row.get("content", row.get("text")) for row in projected["materials"]] == [
        "legacy-marker: use three sections A, B, C", current_text,
    ]

    searched = mem.search("legacy-marker", limit=4, max_bytes=8000)
    selected = next(item for item in searched["materials"] if item["ref"] == source)
    assert [(item["ref"], item["relation"]) for item in selected["associated_materials"]] == [
        (current, "revised_interpretation"),
    ]

    compact = mem.read(source, include_sources=False, max_bytes=600)
    reduced = MaterialView("small", mem).project(compact, max_bytes=600)
    assert current in compact["required_associated_refs"]
    assert reduced.get("status") == "INSUFFICIENT_MATERIAL_BUDGET" or all(
        not row.get("content") for row in reduced["materials"] if row.get("kind") == "source"
    )


def test_plain_source_does_not_leak_later_provenance_at_known_cutoff() -> None:
    mem = memory()
    later_source = mem.publish(Observation("later", "second basis", "user", "file"))
    first_source = mem.publish(Observation("first", "first basis", "user", "file"))
    first = mem.save(content="First version", source_ref=first_source)["record"]["ref"]
    known_before = mem.last_known_at
    second = mem.save(
        target_ref=first, content="Second version", source_ref=later_source,
    )["record"]["ref"]
    current = mem.save(
        target_ref=second, content="Third version", source_ref=first_source,
    )["record"]["ref"]
    assert not mem.read(later_source, known_at=known_before).get("associated_materials")
    assert [(item["ref"], item["relation"]) for item in
            mem.read(later_source)["associated_materials"]] == [
        (current, "revised_interpretation"),
    ]


def test_plain_source_delivers_direct_current_interpretation_at_exact_cutoff() -> None:
    mem = memory()
    source = mem.publish(Observation(
        "agreement", "order-unique: agreed refund is 503 cents", "user", "file",
    ))
    before_card = mem.last_known_at
    body = "Customer agreed refund of 503 cents. " * 60
    card_ref = mem.save(content=body, source_ref=source)["record"]["ref"]
    assert not mem.read(source, known_at=before_card).get("associated_materials")
    packet = mem.read(source)
    assert [(item["ref"], item["relation"]) for item in packet["associated_materials"]] == [
        (card_ref, "direct_interpretation"),
    ]
    searched = mem.search("order-unique", limit=3, max_bytes=8000)
    selected = next(item for item in searched["materials"] if item["ref"] == source)
    assert selected["associated_materials"][0]["ref"] == card_ref
    assert selected["associated_materials"][0]["text"] == body

    mem.workspace.cards[mem._handle(card_ref)].retired = True
    projected = MaterialView("plain", mem).project(mem.read(source), max_bytes=8000)
    assert projected["materials"][1]["retired"] is True
    compact = mem.read(source, max_bytes=500)
    reduced = MaterialView("small", mem).project(compact, max_bytes=500)
    assert card_ref in compact["required_associated_refs"]
    assert reduced.get("status") == "INSUFFICIENT_MATERIAL_BUDGET" or all(
        not row.get("content") for row in reduced["materials"] if row.get("kind") == "source"
    )
    separate = mem.save(content="A separate note about the same source", source_ref=source)[
        "record"
    ]["ref"]
    assert {item["ref"] for item in mem.read(source)["associated_materials"]} == {
        card_ref, separate,
    }
