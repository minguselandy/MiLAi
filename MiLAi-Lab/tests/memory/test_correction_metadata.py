"""Metadata-only B2/B3 controls on toy sources; sockets and natural data are excluded."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_correction_chains import bound, toy_branch
from test_correction_evidence import (
    CFG,
    CUTOFF,
    TOKENIZER,
    no_network_and_stable_clock,
    opened,
    query,
)

from milai_lab.contracts.correction_relation import (
    FrozenEvidenceCue,
    MetadataChainSnapshot,
    SegmentProfile,
    candidate_identity,
)
from milai_lab.methods.correction_evidence import chain_rag_plan, pack_complete
from milai_lab.methods.correction_metadata import (
    literal_dates,
    query_time_pairs,
    scope_words,
    slot_retrieve_plan,
    temporal_scope_plan,
)
from milai_lab.methods.correction_reader import FrozenBankReader
from milai_lab.runners.correction_evidence_eval import run_query

__all__ = ["no_network_and_stable_clock"]


def cue(
    service: Any, ref: str, quote: str, dimension: str, *, value: str | None = None,
    axis: str | None = None, provenance: str = "frozen_writer",
) -> FrozenEvidenceCue:
    body = service.source(ref)["content"]
    start = body.find(quote)
    spans = []
    while start != -1:
        spans.append(bound(service, ref, start, start + len(quote), "source_text"))
        start = body.find(quote, start + 1)
    return FrozenEvidenceCue(dimension, value or quote, tuple(spans), provenance, axis)


def metadata_bank(
    service: Any, cues: tuple[FrozenEvidenceCue, ...], *, cap: int = 384,
    relations: tuple[Any, ...] = (), emit: Any = None,
) -> FrozenBankReader:
    adapter = FrozenBankReader(service, cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                               tokenizer_identity=TOKENIZER, segmentation=SegmentProfile(cap),
                               source_relations=relations, source_cues=cues, emit=emit)
    adapter.freeze_source_index()
    return adapter


@pytest.mark.parametrize("text,expected", [
    ("2020 2020-02 2020-02-29", ("2020", "2020-02", "2020-02-29")),
    ("2021-02-29 2020-13 0000 2020-01-99", ()),
    ("RFC 2020 version 2021 ver:2022 v 2023", ()),
    ("v2020 1.2020.3 2021.1 a2022 2023_4 2024-001", ()),
    ("March 2020", ("2020",)),
])
def test_literal_date_grammar_and_no_month_normalization(
    text: str, expected: tuple[str, ...],
) -> None:
    assert literal_dates(text) == expected


@pytest.mark.parametrize("question,expected", [
    ("published 2020", (("publication", "2020"),)),
    ("reported 2020-02-29; verified 2021", (("report", "2020-02-29"), ("verification", "2021"))),
    ("reported 2020; reported 2020-03-04", (("report", "2020-03-04"),)),
    ("published and reported 2020", ()),
    ("reported 2020 and 2021", ()),
    ("reported before 2020", ()),
    ("currently published 2020", ()),
    ("reported as of 2020", ()),
    ("reported no later than 2020", ()),
    ("wasn't reported 2020", ()),
    ("wasn\u2019t reported 2020", ()),
    ("reported RFC 2020", ()),
    ("latest effective revision", ()),
])
def test_query_time_pairs_are_local_unambiguous_and_non_comparative(
    question: str, expected: tuple[tuple[str, str], ...],
) -> None:
    assert query_time_pairs(question) == expected


def test_cues_bind_all_matches_project_only_overlaps_and_report_partial_pool(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        body = "scope red blue\n\n" + "unrelated anchor clause\n\n" + "scope red blue\n\n"
        ref = service.capture_user("history", "repeat", body)["source_ref"]
        item = cue(service, ref, "scope red blue", "scope")
        adapter = metadata_bank(service, (item,), cap=26)
        scoped = adapter.retrieve(replace(query(service), question="scope"), limit=1)
        assert isinstance(scoped, MetadataChainSnapshot)
        projected = scoped.cue_projections[0]
        assert len(projected.candidate_ids) == 1 and projected.total_projected_spans == 2
        assert projected.partial_quote_candidate_ids == ()
        assert projected.quote_match_count == 2
        assert set(projected.candidate_ids) == {candidate_identity(scoped.candidates[0])}
        unrelated = adapter.retrieve(replace(query(service), question="unrelated"))
        assert unrelated.cue_projections == ()
        plan, diagnostics = slot_retrieve_plan(unrelated, evidence_budget=4000, token_count=len)
        assert plan.strategy == "chain_rag_v1" and diagnostics["fallback_to_b1"]
        changed = replace(item, quote_spans=item.quote_spans[:1])
        with pytest.raises(ValueError, match="ALL_QUOTE_MATCHES_REQUIRED"):
            metadata_bank(service, (changed,), cap=26)
        changed = replace(item, quote_spans=(replace(item.quote_spans[0], span_sha256="0" * 64),
                                             item.quote_spans[1]))
        with pytest.raises(ValueError, match="CUE_SOURCE_SPAN_CHANGED"):
            metadata_bank(service, (changed,), cap=26)


def test_whole_quote_partial_spans_are_distinct_from_pool_omissions(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        body = "scope alpha\n\nscope beta\n\nscope gamma\n\n"
        ref = service.capture_user("history", "one", body)["source_ref"]
        item = cue(service, ref, body, "scope")
        adapter = metadata_bank(service, (item,), cap=16)
        q = replace(query(service), question="scope")
        snapshot = adapter.retrieve(q)
        view = snapshot.cue_projections[0]
        assert len(view.candidate_ids) == view.total_projected_spans == 3
        assert view.partial_quote_candidate_ids == view.candidate_ids
        assert view.quote_match_count == 1
        result = run_query(adapter, q, lambda *_: {"raw_answer": "toy"},
                           method="slot_retrieve_v1", evidence_budget=4000)
        account = result["selector_metadata_accounting"]
        assert account["pool_projection_omission_cue_ids"] == ()
        assert account["quote_partial_projection"] == {item.cue_id: view.candidate_ids}
        clipped = adapter.retrieve(q, limit=1).cue_projections[0]
        assert clipped.partial_quote_candidate_ids == clipped.candidate_ids
        assert len(clipped.candidate_ids) < clipped.total_projected_spans


def test_time_reorders_only_matching_axis_and_sufficient_cue_precision(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        unknown = service.capture_user("history", "unknown",
                                       "anchor reported 2020 " * 8)["source_ref"]
        dated = service.capture_user("history", "dated", "anchor\nReported: 2020\n")["source_ref"]
        adapter = metadata_bank(service, (cue(service, dated, "Reported: 2020", "time",
                                             axis="report", provenance="native_public"),))
        q = replace(query(service), question="anchor reported 2020")
        snapshot = adapter.retrieve(q)
        assert isinstance(snapshot, MetadataChainSnapshot)
        by_id = {candidate_identity(c): c for c in snapshot.candidates}
        baseline = chain_rag_plan(snapshot, evidence_budget=4000, token_count=len)
        assert by_id[baseline.selected_ids[0]].source_ref == unknown
        plan, diagnostics = temporal_scope_plan(snapshot, evidence_budget=4000, token_count=len)
        assert by_id[plan.selected_ids[0]].source_ref == dated
        assert diagnostics["reordered"] and not diagnostics["fallback_to_b1"]
        assert sorted(row["T"] for row in diagnostics["group_features"]) == [0, 1]
        assert plan.snapshot_sha256 == snapshot.snapshot_sha256
        # Wrong axis and greater query precision cannot invent missing valid dates.
        for question in ("anchor effective 2020", "anchor reported 2020-02"):
            view = adapter.retrieve(replace(q, question=question))
            expected = chain_rag_plan(view, evidence_budget=4000, token_count=len)
            actual, diagnostics = temporal_scope_plan(view, evidence_budget=4000, token_count=len)
            assert actual == expected and diagnostics["fallback_to_b1"]
        with pytest.raises(ValueError, match="GROUP_PRIORITY_INVALID"):
            chain_rag_plan(snapshot, evidence_budget=4000, token_count=len,
                           group_priority=(snapshot.groups[0].group_id,) * 2)


def test_group_time_score_deduplicates_cue_projected_across_many_spans(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        relations, refs = toy_branch(service)
        body = service.source(refs["branch_b"])["content"]
        # Capture a separate synthetic source, keeping public capture hashes valid.
        dated = service.capture_user("history", "dated", "Reported: 2020\n" + body)["source_ref"]
        whole = service.source(dated)["content"]
        relation = replace(relations[0], successor_spans=(bound(service, dated, 0, 14,
                           "correction_text"),), witness_spans=(bound(service, dated, 0,
                           len(whole), "relation_witness"),))
        item = cue(service, dated, whole, "time", axis="report")
        adapter = metadata_bank(service, (item,), cap=32, relations=(relation,))
        snapshot = adapter.retrieve(replace(query(service), question="anchor reported 2020"))
        assert len(snapshot.cue_projections[0].candidate_ids) > 1
        plan, diagnostics = temporal_scope_plan(snapshot, evidence_budget=6000, token_count=len)
        assert [entry["T"] for entry in diagnostics["group_features"]] == [1]
        assert len(plan.complete_group_ids) == 1


@pytest.mark.parametrize("quote,dates", [
    ("Reported 2012; Verified 2019", ()),
    ("Reported and verified 2012", ()),
    ("Reported 2012 and 2019", ()),
    ("2012", ("2012",)),
    ("Reported 2012\nReported 2012", ("2012",)),
])
def test_ambiguous_cue_time_projection_is_empty_but_slot_presence_remains(
    tmp_path: Path, quote: str, dates: tuple[str, ...],
) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user("history", "one", "anchor\n" + quote)["source_ref"]
        item = cue(service, ref, quote, "time", axis="report")
        adapter = metadata_bank(service, (item,))
        snapshot = adapter.retrieve(replace(query(service), question="anchor reported 2012"))
        assert snapshot.cue_projections[0].date_literals == dates
        _, diagnostics = slot_retrieve_plan(snapshot, evidence_budget=4000, token_count=len)
        assert [feature["d"] for feature in diagnostics["candidate_features"]] == [1]
        assert not diagnostics["fallback_to_b1"]


def test_scope_is_max_jaccard_of_scope_values_only(tmp_path: Path) -> None:
    assert scope_words("THE Straße RED of x blue") == {"strasse", "red", "blue"}
    with opened(tmp_path) as service:
        ref = service.capture_user("history", "one", "anchor bound quote")["source_ref"]
        cues = (cue(service, ref, "bound quote", "scope", value="red blue"),
                cue(service, ref, "bound quote", "scope", value="red"),
                cue(service, ref, "bound quote", "relation", value="anchor red blue"))
        adapter = metadata_bank(service, cues)
        snapshot = adapter.retrieve(replace(query(service), question="anchor red blue"))
        _, diagnostics = temporal_scope_plan(snapshot, evidence_budget=4000, token_count=len)
        assert [(f["L_numerator"], f["L_denominator"])
                for f in diagnostics["group_features"]] == [(2, 3)]


def test_slot_counts_distinct_dimensions_once_keeps_zero_tail_and_reader_is_body_only(
    tmp_path: Path,
) -> None:
    events: list[dict[str, Any]] = []
    with opened(tmp_path) as service:
        long = service.capture_user("history", "long", "anchor " + "long " * 30)["source_ref"]
        short = service.capture_user("history", "short", "anchor short")["source_ref"]
        zero = service.capture_user("history", "zero", "anchor zero")["source_ref"]
        cues = tuple(cue(service, long, "anchor", dim, value="selector-only-" + dim)
                     for dim in ("time", "scope", "exception", "relation"))
        cues += (cue(service, long, "anchor", "scope", value="another selector-only scope"),
                 cue(service, short, "anchor", "scope", value="selector-only short"))
        adapter = metadata_bank(service, cues, emit=events.append)
        q = replace(query(service), question="anchor")
        snapshot = adapter.retrieve(q)
        plan, diagnostics = slot_retrieve_plan(snapshot, evidence_budget=6000, token_count=len)
        by_id = {candidate_identity(c): c for c in snapshot.candidates}
        assert [by_id[key].source_ref for key in plan.selected_ids] == [long, short, zero]
        assert not plan.complete_group_ids and plan.group_cost_decisions == ()
        assert sorted(row["d"] for row in diagnostics["candidate_features"]) == [0, 1, 4]
        before = service.sources()

        def reader(q: Any, material: str, receipt: Any) -> dict[str, Any]:
            assert "selector-only" not in material and "cue_id" not in material
            assert len(json.loads(material)["sources"]) == 3
            assert "per-span" in receipt.cost_scope
            return {"raw_answer": "toy"}

        result = run_query(adapter, q, reader, method="slot_retrieve_v1", evidence_budget=6000)
        assert result["requested_method"] == result["effective_method"] == "slot_retrieve_v1"
        assert result["selector_metadata_accounting"]["selector_cue_logical_bytes"] > 0
        assert result["selector_metadata_accounting"]["selector_input_serialized_tokens"] > 0
        index = next(event for event in events if event["event"] == "correction_cue_index")
        assert index["input_logical_bytes"] > 0 and index["quote_validation_logical_body_bytes"] > 0
        assert index["scope_cue_sources"] == 2 and index["date_cue_sources"] == 0
        assert service.sources() == before


def test_all_unknown_b2_b3_are_exact_b1_plan_and_material_and_old_b1_unchanged(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        relations, _ = toy_branch(service)
        common = dict(cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                      tokenizer_identity=TOKENIZER, segmentation=SegmentProfile(32),
                      source_relations=relations)
        old = FrozenBankReader(service, **common)
        old.freeze_source_index()
        adapter = FrozenBankReader(service, **common, source_cues=())
        adapter.freeze_source_index()
        q = replace(query(service), question="anchor")
        snapshot = adapter.retrieve(q)
        old_snapshot = old.retrieve(q)
        assert old_snapshot.candidates == snapshot.candidates
        for budget in (512, 1024, 2048):
            baseline = chain_rag_plan(snapshot, evidence_budget=budget, token_count=len)
            old_plan = chain_rag_plan(old_snapshot, evidence_budget=budget, token_count=len)
            baseline_material, receipt = pack_complete(snapshot, baseline,
                adapter.read_selected(snapshot, baseline.selected_ids), token_count=len)
            old_material, _ = pack_complete(old_snapshot, old_plan,
                old.read_selected(old_snapshot, old_plan.selected_ids), token_count=len)
            assert baseline_material == old_material
            for selector in (temporal_scope_plan, slot_retrieve_plan):
                actual, diagnostics = selector(snapshot, evidence_budget=budget, token_count=len)
                assert actual == baseline and diagnostics["fallback_to_b1"]
                material, actual_receipt = pack_complete(snapshot, actual,
                    adapter.read_selected(snapshot, actual.selected_ids), token_count=len)
                assert material == baseline_material and actual_receipt == receipt
        result = run_query(adapter, q, lambda *_: {"raw_answer": "toy"},
                           method="slot_retrieve_v1")
        assert result["requested_method"] == "slot_retrieve_v1"
        assert result["effective_method"] == "chain_rag_v1"


@pytest.mark.parametrize("damage", ["source", "cutoff", "duplicate", "effective", "dimension"])
def test_cue_contract_and_freeze_fail_closed(tmp_path: Path, damage: str) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user("history", "one", "anchor effective 2020")["source_ref"]
        item = cue(service, ref, "effective 2020", "time", axis="effective")
        with pytest.raises(ValueError, match="CORRECTION_"):
            if damage == "source":
                item = replace(item, quote_spans=(replace(item.quote_spans[0],
                                                          source_sha256="0" * 64),))
            elif damage == "cutoff":
                row = dict(service.source(ref))
                row["observed_at"] = "2026-01-03T00:00:00+00:00"
                service.store.put(service.sources_namespace, ref, row, index=False)
            elif damage == "effective":
                item = replace(item, provenance="native_public")
            elif damage == "dimension":
                item = replace(item, dimension="subjects")
            metadata_bank(service, (item, item) if damage == "duplicate" else (item,))
