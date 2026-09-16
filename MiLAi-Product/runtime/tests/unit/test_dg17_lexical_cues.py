from __future__ import annotations

from milai.application.acquisition import (
    compile_acquisition_plan,
    fuse_acquisition_probe_results,
)
from milai.application.lexical_cues import compile_lexical_cue_set
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import EvidenceRequirementV02


def _plan(query: str):  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(RetrievalRequest(route="L1", query=query))


def test_a4_cues_apply_only_conservative_linguistic_normalization() -> None:
    cues = compile_lexical_cue_set(
        EvidenceRequirementV02(
            slot_id="TARGET_EVENT",
            interpretation_kind="EVENT",
            entity_constraints=["Running", "drones", "购买"],
        )
    )

    assert cues.surface_terms == ["running", "drones", "购买"]
    assert cues.morphological_variants == ["run", "drone"]
    assert cues.entity_aliases == []
    assert cues.relation_cues == []
    assert cues.language_tags == ["zh-Hans", "und-Latn"]
    assert "GENERIC_LATIN_MORPHOLOGY_V1" in cues.provenance
    assert not {"buy", "bought", "purchase", "fly"}.intersection(
        cues.morphological_variants
    )


def test_a4_enriched_lane_is_explicit_and_raw_lane_remains_unchanged() -> None:
    plan = _plan("Which running drones were recorded?")
    baseline = compile_acquisition_plan(
        plan,
        query="Which running drones were recorded?",
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    enriched = compile_acquisition_plan(
        plan,
        query="Which running drones were recorded?",
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
        enable_enriched=True,
    )

    assert all(probe.channel == "FTS_RAW" for probe in baseline.probes)
    enriched_probe = next(probe for probe in enriched.probes if probe.channel == "FTS_ENRICHED")
    assert enriched_probe.requirement_slot == "LOOKUP_ANSWER"
    assert set(enriched_probe.lexical_terms) >= {"running", "drones", "run", "drone"}
    assert enriched.fusion.policy_identity == "RRF_K60_PER_SLOT_RAW_PLUS_ENRICHED_V1"


def test_a4_fusion_retains_raw_and_enriched_channel_provenance() -> None:
    plan = _plan("Which running drones were recorded?")
    acquisition = compile_acquisition_plan(
        plan,
        query="Which running drones were recorded?",
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
        enable_enriched=True,
    )
    candidate = {
        "evidence_id": "candidate-1",
        "source_ref": "memory://session-a/turn-0",
        "subject_id": "session-a",
        "content": "A drone can run a recorded route.",
        "relevance_score": 0.7,
    }
    probe_results = [
        (probe, [candidate] if probe.requirement_slot is not None else [])
        for probe in acquisition.probes
    ]

    fused = fuse_acquisition_probe_results(acquisition, probe_results)

    envelope = fused[0]["acquisition_candidate"]
    assert envelope["channel_ranks"] == {"FTS_RAW": 1, "FTS_ENRICHED": 1}
    assert envelope["matched_fields"] == ["enriched_lexical_query", "lexical_text"]
    assert envelope["matched_slots"] == ["LOOKUP_ANSWER"]
