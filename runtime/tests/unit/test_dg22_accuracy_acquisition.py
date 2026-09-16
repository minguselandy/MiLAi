from __future__ import annotations

from datetime import UTC, datetime

from evals.dg22.acquisition_correctness import run_acquisition_correctness

from milai.application.accuracy_acquisition import (
    accuracy_bundle_query_text,
    compile_accuracy_action_decision,
    compile_requirement_complete_bundle,
    execute_requirement_complete_bundle,
)
from milai.application.query_planner import QueryPlanner
from milai.domain import RetrievalRequest

REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)


def _query_ir(query: str):  # type: ignore[no-untyped-def]
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    assert plan.memory_query_ir is not None
    return plan.memory_query_ir


def _evidence(evidence_id: str, content: str) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "canonical_mutation": False,
        "evidence_id": evidence_id,
        "source_ref": f"memory://synthetic/turn/{evidence_id}",
        "subject_id": "synthetic",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": REFERENCE.isoformat(),
        "content": content,
        "content_hash": f"hash-{evidence_id}",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }


def test_dg22_policy_bundle_and_official_executor_contract() -> None:
    result = run_acquisition_correctness()

    assert result["status"] == "PASS_REQUIREMENT_COMPLETE_ACQUISITION_FUSION"
    assert result["hard_gate"]["passed"]
    assert result["policy"]["default_enabled"] is False
    assert result["metrics"]["extra_passes_per_query"] == 1
    assert result["metrics"]["repository_probe_calls"] == 1
    assert result["metrics"]["provider_controller_calls"] == 0
    assert result["metrics"]["automatic_retries"] == 0


def test_dg22_fast_stops_stale_guards_and_target_cap() -> None:
    result = run_acquisition_correctness()

    assert all(item["passed"] for item in result["fast_stop_matrix"])
    assert all(result["stale_identity_probe"].values())
    assert result["target_cap_probe"]["passed"]
    assert result["metrics"]["case_id_or_gold_function_parameters"] == 0


def test_dg22_precision_fusion_is_attributed_and_region_unique() -> None:
    result = run_acquisition_correctness()
    execution = result["execution"]

    assert execution["global_probe_count"] == 0
    assert execution["repeated_accepted_region_count"] == 0
    assert set(execution["first_reserve_requirement_ids"]) == {"TOTAL_PRICE", "ITEM_COUNT"}
    assert execution["probe_attribution"] != execution["binding_attribution"]
    assert execution["useful_candidate_rate"] >= 0.30


def test_accuracy_query_expands_lexical_equivalents_without_labels() -> None:
    query_ir = _query_ir("When did I buy my new game?")
    targets = [item.slot_id for item in query_ir.requirements if item.required]
    bundle = compile_requirement_complete_bundle(
        query_ir,
        targets,
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )

    text = accuracy_bundle_query_text(query_ir, bundle).split()

    assert {"buy", "bought", "got", "game", "gaming"}.issubset(text)
    assert all("case" not in term and "gold" not in term for term in text)


def test_accuracy_binding_allows_one_context_modifier_but_requires_action_anchor() -> None:
    query_ir = _query_ir("When did I take my acoustic guitar for service?")
    targets = [item.slot_id for item in query_ir.requirements if item.required]
    bundle = compile_requirement_complete_bundle(
        query_ir,
        targets,
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )
    execution = execute_requirement_complete_bundle(
        query_ir,
        bundle,
        [
            _evidence(
                "target",
                "I decided to take my guitar to the tech for service on June 4.",
            ),
            _evidence(
                "distractor",
                "I stored my acoustic guitar by the window on June 4.",
            ),
        ],
        current_requirement_state_digest="1" * 64,
        current_acquisition_capability_digest="2" * 64,
    )

    assert "target" in execution["selected_evidence_ids"]
    assert "distractor" not in execution["selected_evidence_ids"]


def test_accuracy_recovery_defers_exhaustive_sets_to_a_proof_capable_channel() -> None:
    query_ir = _query_ir("How many workshops did I attend in March?")
    missing = [item.slot_id for item in query_ir.requirements if item.required]

    decision = compile_accuracy_action_decision(
        query_ir,
        missing,
        executable_channels=["FTS_ENRICHED"],
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )

    assert decision["status"] == "SKIPPED"
    assert decision["reason_code"] == "SKIP_PROOF_CHANNEL_REQUIRED"


def test_planned_event_signal_separates_target_from_incidental_category_mention() -> None:
    query_ir = _query_ir(
        "How many days before the team meeting I was preparing for did I attend "
        "the workshop on Effective Communication in the Workplace?"
    )
    targets = [item.slot_id for item in query_ir.requirements if item.required]
    bundle = compile_requirement_complete_bundle(
        query_ir,
        targets,
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )
    execution = execute_requirement_complete_bundle(
        query_ir,
        bundle,
        [
            _evidence(
                "meeting",
                "I was preparing for the team meeting scheduled for January 17.",
            ),
            _evidence(
                "workshop",
                "I attended a workshop about communication in team meetings on January 10.",
            ),
        ],
        current_requirement_state_digest="1" * 64,
        current_acquisition_capability_digest="2" * 64,
    )

    attributed = execution["binding_attribution"]
    assert any("meeting" in evidence_ids for evidence_ids in attributed.values())


def test_temporal_slot_reserves_a_dated_operand_over_an_undated_lexical_match() -> None:
    query_ir = _query_ir(
        "How many days before the team meeting I was preparing for did I attend "
        "the workshop on Effective Communication in the Workplace?"
    )
    targets = [item.slot_id for item in query_ir.requirements if item.required]
    bundle = compile_requirement_complete_bundle(
        query_ir,
        targets,
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )
    execution = execute_requirement_complete_bundle(
        query_ir,
        bundle,
        [
            _evidence(
                "workshop-with-undated-meeting",
                (
                    "I am preparing for an upcoming meeting with my team. "
                    "I attended the Effective Communication in the Workplace workshop "
                    "on January 10th."
                ),
            ),
            _evidence(
                "dated-meeting",
                "I was preparing for the team meeting on January 17th.",
            ),
        ],
        current_requirement_state_digest="1" * 64,
        current_acquisition_capability_digest="2" * 64,
    )

    assert execution["binding_attribution"]["EVENT_2"][0] == "dated-meeting"
    assert set(execution["selected_evidence_ids"]) == {
        "workshop-with-undated-meeting",
        "dated-meeting",
    }
