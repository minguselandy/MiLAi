"""Query-free segmentation controls over toy strings only; no RFC or gold access."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from test_correction_evidence import (
    CFG,
    CUTOFF,
    TOKENIZER,
    no_network_and_stable_clock,
    opened,
    query,
)

from milai_lab.contracts.correction_relation import (
    EvidenceSpanCandidate,
    SegmentProfile,
    candidate_identity,
    text_sha256,
)
from milai_lab.methods.correction_reader import FrozenBankReader
from milai_lab.methods.correction_spans import segment_body
from milai_lab.runners.correction_evidence_eval import run_query

__all__ = ["no_network_and_stable_clock"]


@pytest.mark.parametrize("body,cap", [
    ("ab\r\ncd\r\n\r\nef", 10),
    ("aa bb\ncc dd\n\nEEE FFF\nGG HH\n", 14),
    ("   \n\n\t\r\n ", 3),
    ("verylongwordwithoutspaces" * 20, 13),
    ("中文😀e\u0301🙂\u200d↔\n\n" * 30, 11),
    ("archive evidence line\n" * 100, 60),
])
def test_exact_partition_progress_and_token_cap(body: str, cap: int) -> None:
    spans = segment_body(body, token_count=len, profile=SegmentProfile(cap))
    assert "".join(body[start:end] for start, end in spans) == body
    assert all(0 < end - start <= cap for start, end in spans)
    assert spans == segment_body(body, token_count=len, profile=SegmentProfile(cap))
    if body == "ab\r\ncd\r\n\r\nef":
        assert spans == ((0, 10), (10, 12))
    if body.startswith("aa bb"):
        assert body[slice(*spans[0])] == "aa bb\ncc dd\n\n"


def test_prefer_paragraph_then_line_boundaries_before_splitting_long_children() -> None:
    body = "short\n\n" + "a b c d e f g h i j k l m n o p\n" * 2
    spans = segment_body(body, token_count=len, profile=SegmentProfile(10))
    assert spans[0] == (0, len("short\n\n"))
    body = "a\n" + "long_word_without_whitespace" * 3
    spans = segment_body(body, token_count=len, profile=SegmentProfile(10))
    assert spans[0] == (0, len("a\n"))


def test_empty_invalid_and_nonmonotone_token_counts() -> None:
    assert segment_body("", token_count=len, profile=SegmentProfile()) == ()
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        SegmentProfile(0)
    with pytest.raises(ValueError, match="TOKEN_COUNT_INVALID"):
        segment_body("abc", token_count=lambda _: -1, profile=SegmentProfile())
    with pytest.raises(ValueError, match="CAP_CANNOT_FIT_PREFIX"):
        segment_body("😀", token_count=lambda _: 4, profile=SegmentProfile(1))

    def nonmonotone(text: str) -> int:
        return 1 if text == "ab" else len(text) + 2

    spans = segment_body("ababab", token_count=nonmonotone, profile=SegmentProfile(1))
    assert spans == ((0, 2), (2, 4), (4, 6))


def test_span_index_and_selected_exact_unicode_ranges_survive_reopen(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    body = "archive evidence 原文😀\r\n\r\n" * 8
    with opened(tmp_path) as service:
        ref = service.capture_user("history", "long", body)["source_ref"]
        empty = service.capture_user("history", "empty", "")["source_ref"]
        adapter = FrozenBankReader(service, cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                                   tokenizer_identity=TOKENIZER, emit=events.append,
                                   segmentation=SegmentProfile(50))
        frozen = adapter.freeze_source_index()
        assert frozen["excluded_empty_sources"] == [empty]
        assert frozen["eligible_sources"] == 1
        rows = frozen["span_index"]
        assert "".join(body[row["start"]:row["end"]] for row in rows) == body
        assert all("content" not in row for row in rows)
        snapshot = adapter.retrieve(query(service))
        assert len(snapshot.candidates) > 1
        assert all(isinstance(c, EvidenceSpanCandidate) for c in snapshot.candidates)
        ids = [candidate_identity(c) for c in snapshot.candidates]
        assert len(set(ids)) == len(ids) and {c.source_ref for c in snapshot.candidates} == {ref}
        units = adapter.read_selected(snapshot, ids)
        assert all(unit["content"] == body[slice(*unit["range"])] for unit in units)
        with pytest.raises(ValueError, match="UNSELECTED_SOURCE_READ"):
            adapter.read_selected(snapshot, [ref])

        def reader(q: Any, material: str, receipt: Any) -> dict[str, Any]:
            sent = json.loads(material)["sources"]
            assert len(sent) > 1
            for unit, delivered in zip(sent, receipt.delivered, strict=True):
                assert delivered.candidate_id == unit["candidate_id"]
                assert delivered.start == unit["range"][0]
                assert delivered.content_sha256 == text_sha256(unit["content"])
                assert delivered.body_text_sha256 == text_sha256(body)
            return {"raw_answer": "synthetic"}

        result = run_query(adapter, query(service), reader, evidence_budget=4000)
        assert set(result["delivery"]["read_ids"]) == set(ids)
        assert service.sources()[0]["content"] in {body, ""}
        span = snapshot.candidates[0]
        with pytest.raises(ValueError, match="SPAN_IDENTITY_INVALID"):
            replace(span, end=span.end - 1)
    with opened(tmp_path) as service:
        adapter = FrozenBankReader(service, cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                                   tokenizer_identity=TOKENIZER, segmentation=SegmentProfile(50))
        assert adapter.freeze_source_index()["index_sha256"] == frozen["index_sha256"]
        assert adapter.retrieve(query(service)) == snapshot
        assert adapter.read_selected(snapshot, ids) == units


def test_segmentation_profile_changes_identity_but_whole_source_default_stays_exact(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user("history", "one", "archive evidence " * 20)["source_ref"]
        kwargs = dict(cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                      tokenizer_identity=TOKENIZER)
        original = FrozenBankReader(service, **kwargs)
        original.freeze_source_index()
        candidate = original.retrieve(query(service)).candidates[0]
        assert candidate_identity(candidate) == ref
        assert "candidate_id" not in asdict(candidate) and "start" not in asdict(candidate)
        unit = original.read_selected(original.retrieve(query(service)), [ref])[0]
        assert set(unit) == {"source_ref", "role", "observed_at", "range", "content"}
        identities = []
        for cap in (50, 100):
            adapter = FrozenBankReader(service, **kwargs, segmentation=SegmentProfile(cap))
            identities.append(adapter.freeze_source_index()["index_sha256"])
        assert len(set([*identities, original.index_sha256])) == 3
