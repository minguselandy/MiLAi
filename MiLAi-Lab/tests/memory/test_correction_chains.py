"""B1 branch/closure/packing controls over synthetic sources; all sockets denied."""

from __future__ import annotations

import json
from dataclasses import replace
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
    BoundSourceSpan,
    ChainResearchSnapshot,
    SegmentProfile,
    SourceRelation,
    candidate_identity,
    text_sha256,
)
from milai_lab.methods.correction_evidence import chain_rag_plan, pack_complete, render_material
from milai_lab.methods.correction_reader import FrozenBankReader
from milai_lab.runners.correction_evidence_eval import run_query

__all__ = ["no_network_and_stable_clock"]


def bound(service: Any, ref: str, start: int, end: int, role: str) -> BoundSourceSpan:
    row = service.source(ref)
    body = row["content"]
    return BoundSourceSpan(ref, row["content_sha256"], text_sha256(body), start, end,
                           text_sha256(body[start:end]), role)


def toy_branch(service: Any) -> tuple[tuple[SourceRelation, ...], dict[str, str]]:
    bodies = {
        "original": "anchor setting A.\n\nUnrelated independent clause.\n",
        "branch_b": "quoted predecessor A.\n\nReplacement B.\n\nWitness detailed note B.\n",
        "branch_c": "Replacement C and witness.\n",
    }
    refs = {key: service.capture_user("history", key, body)["source_ref"]
            for key, body in bodies.items()}
    original = bound(service, refs["original"], 0, len("anchor setting A."), "source_text")
    quoted = bound(service, refs["branch_b"], 0, len("quoted predecessor A."),
                   "quoted_predecessor")
    relations = []
    for key in ("branch_b", "branch_c"):
        body, ref = bodies[key], refs[key]
        start = body.index("Replacement")
        relations.append(SourceRelation(
            (original, quoted) if key == "branch_b" else (original,),
            (bound(service, ref, start, body.index("\n", start), "correction_text"),),
            (bound(service, ref, 0, len(body), "relation_witness"),)))
    return tuple(relations), refs


def reader_bank(
    service: Any, relations: tuple[SourceRelation, ...], **kwargs: Any,
) -> FrozenBankReader:
    return FrozenBankReader(service, cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                            tokenizer_identity=TOKENIZER, segmentation=SegmentProfile(32),
                            source_relations=relations, **kwargs)


def test_top_branch_closure_and_exact_group_budget_deliver_all_same_source_spans(
    tmp_path: Path,
) -> None:
    events: list[dict[str, Any]] = []
    with opened(tmp_path) as service:
        relations, refs = toy_branch(service)
        adapter = reader_bank(service, relations, emit=events.append)
        frozen = adapter.freeze_source_index()
        initial = service.sources()
        q = replace(query(service), question="anchor")
        snapshot = adapter.retrieve(q)
        assert isinstance(snapshot, ChainResearchSnapshot)
        assert len(snapshot.groups) == 1 and len(snapshot.candidates) == 5
        assert snapshot.candidates[0].source_ref == refs["original"]
        assert snapshot.candidates[0].start == 0
        assert sum(c.source_ref == refs["branch_b"] for c in snapshot.candidates) == 3
        assert len(snapshot.ordinary_seed_ids) == 1
        assert not snapshot.pool_omitted_ids and not snapshot.unclosed_relation_ids
        assert all(c.start == 0 for c in snapshot.candidates if c.source_ref == refs["original"])
        group = snapshot.groups[0]
        assert set(group.relation_ids) == {relation.relation_id for relation in relations}
        # Summing individual wrappers is one codepoint too conservative at this boundary.
        assert len(render_material([])) + sum(c.unit_tokens for c in snapshot.candidates) > (
            group.material_tokens)
        plan = chain_rag_plan(snapshot, evidence_budget=group.material_tokens, token_count=len)
        assert plan.complete_group_ids == (group.group_id,)
        assert set(plan.selected_ids) == {candidate_identity(c) for c in snapshot.candidates}
        calls = []

        def reader(q: Any, material: str, receipt: Any) -> dict[str, Any]:
            calls.append(material)
            sent = json.loads(material)["sources"]
            assert len(sent) == 5 and len({unit["candidate_id"] for unit in sent}) == 5
            assert receipt.complete_group_ids == (group.group_id,)
            assert not receipt.incomplete_group_ids and not receipt.packing_omitted_ids
            assert receipt.material_tokens == group.material_tokens == len(material)
            assert receipt.planning_minus_material_tokens == 0
            assert receipt.group_cost_decisions[0].selected_as_complete
            return {"raw_answer": "synthetic only"}

        result = run_query(adapter, q, reader, method="chain_rag_v1",
                           evidence_budget=group.material_tokens)
        assert len(calls) == 1 and service.sources() == initial
        assert result["scientific_status"] == "B1_MECHANICAL_ONLY_NOT_T0_RESULT"
        assert "semantics unchecked" in frozen["relation_validation"]
        assert events[-2]["event"] == "correction_readonly_assertion"
        assert events[-2]["unchanged"]
        assert adapter.retrieve(q) == snapshot  # shared retrieval does not depend on the arm


def test_shared_k_truncation_and_budget_shortfall_remain_explicit(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        relations, _ = toy_branch(service)
        adapter = reader_bank(service, relations)
        adapter.freeze_source_index()
        q = replace(query(service), question="anchor")
        snapshot = adapter.retrieve(q, limit=2)
        assert isinstance(snapshot, ChainResearchSnapshot)
        assert len(snapshot.candidates) == 2
        assert len(snapshot.pool_omitted_ids) == 3 and snapshot.unclosed_relation_ids
        plan = chain_rag_plan(snapshot, evidence_budget=4000, token_count=len)
        material, receipt = pack_complete(snapshot, plan,
            adapter.read_selected(snapshot, plan.selected_ids), token_count=len)
        assert len(json.loads(material)["sources"]) == 2
        assert not receipt.complete_group_ids and receipt.incomplete_group_ids
        assert receipt.unclosed_relation_ids == snapshot.unclosed_relation_ids
        assert receipt.group_cost_decisions[0].available_in_pool is False
        whole = adapter.retrieve(q)
        plan = chain_rag_plan(whole, evidence_budget=whole.groups[0].material_tokens - 1,
                              token_count=len)
        assert not plan.complete_group_ids and plan.incomplete_group_ids
        assert plan.group_cost_decisions[0].available_in_pool
        assert not plan.group_cost_decisions[0].selected_as_complete


@pytest.mark.parametrize("damage", ["source", "body", "span", "range", "cutoff", "duplicate"])
def test_relation_binding_fails_closed_before_query(tmp_path: Path, damage: str) -> None:
    with opened(tmp_path) as service:
        relations, refs = toy_branch(service)
        old = relations[0].predecessor_spans[0]
        if damage == "cutoff":
            row = dict(service.source(refs["original"]))
            row["observed_at"] = "2026-01-03T00:00:00+00:00"
            service.store.put(service.sources_namespace, refs["original"], row, index=False)
        elif damage == "duplicate":
            relations = (*relations, relations[0])
        else:
            changed = {"source": {"source_sha256": "0" * 64},
                       "body": {"body_text_sha256": "0" * 64},
                       "span": {"span_sha256": "0" * 64},
                       "range": {"start": 1}}[damage]
            relations = (replace(relations[0], predecessor_spans=(replace(old, **changed),)),
                         relations[1])
        with pytest.raises(ValueError, match=r"CORRECTION_(RELATION|DUPLICATE_RELATION)"):
            reader_bank(service, relations).freeze_source_index()


def test_ambiguous_original_matches_remain_bound_and_quoted_only_does_not_invent_edge(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        repeated = "anchor A.\n\n"
        original = service.capture_user("history", "original", repeated * 4)["source_ref"]
        page = service.capture_user("history", "page", "old A.\n\nnew B.\n")["source_ref"]
        quoted = bound(service, page, 0, len("old A."), "quoted_predecessor")
        relation = SourceRelation(
            (quoted, *(bound(service, original, i * len(repeated),
                             i * len(repeated) + len("anchor A."), "source_text")
                        for i in range(4))),
            (bound(service, page, len("old A.\n\n"), len("old A.\n\nnew B."),
                   "correction_text"),),
            (bound(service, page, 0, len("old A.\n\nnew B.\n"), "relation_witness"),),
            location_status="ambiguous")
        adapter = reader_bank(service, (relation,))
        adapter.freeze_source_index()
        q = replace(query(service), question="anchor")
        snapshot = adapter.retrieve(q)
        assert len(snapshot.groups) == 1
        assert {c.source_ref for c in snapshot.candidates} == {original, page}
        assert sum(c.source_ref == original for c in snapshot.candidates) == 2
        only_quote = replace(relation, predecessor_spans=(quoted,), location_status="quoted_only")
        adapter = reader_bank(service, (only_quote,))
        adapter.freeze_source_index()
        assert {c.source_ref for c in adapter.retrieve(q).candidates} == {original}


def test_packer_drops_whole_planned_group_and_continues_later_units(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        relations, refs = toy_branch(service)
        service.capture_user("history", "later", "anchor short.")
        adapter = reader_bank(service, relations)
        adapter.freeze_source_index()
        snapshot = adapter.retrieve(replace(query(service), question="anchor setting"))
        assert isinstance(snapshot, ChainResearchSnapshot) and len(snapshot.groups) == 2
        plan = chain_rag_plan(snapshot, evidence_budget=6000, token_count=len)
        branch = next(group for group in snapshot.groups if len(group.candidate_ids) > 1)
        later = next(group for group in snapshot.groups if len(group.candidate_ids) == 1)
        assert plan.selected_ids == (*branch.candidate_ids, *later.candidate_ids)
        units = adapter.read_selected(snapshot, plan.selected_ids)
        attempts: list[tuple[str, ...]] = []

        def boundary_spike(material: str) -> int:
            values = json.loads(material)["sources"]
            attempts.append(tuple(value["candidate_id"] for value in values))
            return len(material) + (10000 if any(
                value["source_ref"] == refs["original"] for value in values) else 0)

        material, receipt = pack_complete(snapshot, plan, units, token_count=boundary_spike)
        assert attempts[:2] == [branch.candidate_ids, later.candidate_ids]
        sent = json.loads(material)["sources"]
        assert len(sent) == 1 and sent[0]["content"] == "anchor short."
        assert len(receipt.packing_omitted_ids) == 5
        assert len(receipt.complete_group_ids) == len(receipt.incomplete_group_ids) == 1
        assert receipt.planning_minus_material_tokens == plan.estimated_tokens - len(material)


def test_chain_runner_requires_explicit_span_relation_index(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        service.capture_user("history", "one", "archive evidence")
        adapter = FrozenBankReader(service, cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                                   tokenizer_identity=TOKENIZER)
        adapter.freeze_source_index()
        with pytest.raises(ValueError, match="CHAIN_SNAPSHOT_REQUIRED"):
            run_query(adapter, query(service), lambda *_: pytest.fail("reader must not run"),
                      method="chain_rag_v1")
