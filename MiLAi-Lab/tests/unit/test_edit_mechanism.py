"""Real SQLite historical Reader states and honest diagnostic denominators."""

from __future__ import annotations

import copy
import json
from itertools import pairwise
from pathlib import Path

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.runners.edit_mechanism import (
    blinded_states,
    controlled_events,
    controlled_observations,
    controls,
    full_answer_payload,
    prior_evidence,
    require_completed_external,
    require_completed_suite,
    require_frozen_candidate,
    restore_current,
    snapshots,
    summarize_controlled,
    summarize_drift,
    summarize_native,
    validate_transition,
)


def row(text: str, revision: int = 1, identity: str = "saved-record") -> dict:
    return {
        "ok": True,
        "id": identity,
        "value": {
            "revision": revision,
            "content": text,
            "scope": {},
            "basis": "user_statement",
            "method_arm": "M",
            "method_version": "actual-method",
        },
    }


def test_controls_retain_actual_revisions_without_ideal_initialization(tmp_path: Path) -> None:
    before = [row("Current rule: twice weekly, holidays paused.")]
    after = [row("Current rule: once weekly, holidays paused.", 2)]
    original = copy.deepcopy((before, after))
    assert controls(before, after, "NeverWrite") == before
    retained = controls(before, after, "RetainAll")
    assert len(retained) == 2 and retained[1]["value"] == before[0]["value"]
    assert controls([], after, "NeverWrite") == []
    assert controls(before, before, "RetainAll") == before
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("edit", "diagnostic", "alice"), "alice", tmp_path / "memory.lock"
        )
        restore_current(service, retained)
        found = service.search("weekly", limit=10, include_raw=False)["records"]
        assert {r["value"]["content"] for r in found} == {r["value"]["content"] for r in retained}
        assert service.sources() == []
        restore_current(service, after)
        assert len(service.records()) == 1
        assert service.read("saved-record")["value"] == after[0]["value"]
    assert (before, after) == original


def test_blinding_preserves_same_record_and_changed_revision() -> None:
    before, after = blinded_states(
        [row("Old")], [row("New", 2), row("Additional", identity="next")]
    )
    assert before[0]["record_id"] == after[0]["record_id"]
    assert before[0]["revision"] == 1 and after[0]["revision"] == 2
    assert "method_arm" not in str(before) and "method_version" not in str(after)
    assert after[1]["record_id"] != after[0]["record_id"]


def test_snapshot_availability_does_not_count_no_change_or_unknown_as_committed(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "B1" / "maintenance" / "halumem" / "alice" / "0"
    write_json(folder / "complete.json", {"source_batches": 1})
    write_json(folder / "batch-0000" / "before.json", [row("Old")])
    write_json(folder / "batch-0000" / "after.json", [row("New", 2)])
    write_json(
        folder / "batch-0000" / "complete.json",
        {
            "receipts": [
                {"ok": True, "status": "committed"},
                {"ok": True, "status": "no_change"},
                {
                    "ok": True,
                    "status": "no_change",
                    "replayed": True,
                    "original_status": "committed",
                },
                {"ok": False, "status": "rejected"},
                {"status": "unknown"},
            ],
        },
    )
    before, after, availability = snapshots(tmp_path, "B1", "alice", 0)
    assert before == [row("Old")] and after == [row("New", 2)]
    assert availability["proposals"] == 5
    assert availability["committed_receipts"] == 1
    assert availability["accepted_no_change_receipts"] == 1
    assert availability["original_commits_confirmed_by_replay"] == 1
    assert availability["rejected_receipts"] == 1
    assert availability["other_or_unconfirmed_receipts"] == 1


def test_prior_grounding_fetches_only_actual_old_ranges_without_future_or_arm_labels(
    tmp_path: Path,
) -> None:
    bank = tmp_path / "B0" / "banks" / "alice"
    bank.mkdir(parents=True)
    write_json(tmp_path / "B0" / "actual-config.json", {"arm": "B0"})
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("edit", "B0", "B0", "alice"),
            "alice",
            bank / "memory.lock",
            mutation_contract="event_bound_v1",
        )
        source = service.capture_user(
            "halumem:alice:session:0", "old-message", "Twice weekly; holidays paused."
        )
        service.bind_source_boundary(
            "halumem:alice:session:0", "old-message", [source["source_ref"]]
        )
        method = EditMemory(service, "B0")
        evidence = method.prepare([source["source_ref"]], "weekly")["sources"][0]["evidence_id"]
        saved = method.apply(
            "halumem:alice:session:0",
            "save",
            {
                "action": "create",
                "units": [
                    {
                        "text": "Twice weekly; holidays paused.",
                        "role": "content",
                        "evidence": [evidence],
                    }
                ],
            },
        )
        assert saved["ok"]
        before = service.records()
        write_json(
            tmp_path / "B0/maintenance/halumem/alice/0/batch-0000/delivery.json",
            {"sources": [{"source_ref": source["source_ref"], "timestamp": "2030-01-01"}]},
        )
        service.capture_user("future-session", "future-message", "FUTURE_MUST_NOT_ENTER_DIAGNOSTIC")
    grounded = prior_evidence(tmp_path, "B0", "alice", before)
    assert len(grounded) == 1 and grounded[0]["text"] == "Twice weekly; holidays paused."
    assert grounded[0]["role"] == "user" and grounded[0]["source_revision"] == 1
    assert grounded[0]["original_timestamp"] == "2030-01-01"
    assert "FUTURE_MUST_NOT_ENTER_DIAGNOSTIC" not in str(grounded)
    assert "B0" not in str(grounded) and "evidence_id" not in str(grounded)


def test_unconfirmed_paired_arm_and_incomplete_transition_are_not_scored(tmp_path: Path) -> None:
    write_json(tmp_path / "B0" / "terminal.json", {"status": "COMPLETED_EXPERIMENT_PHASE"})
    with pytest.raises(ValueError, match="paired development arm"):
        require_completed_suite(tmp_path, ["B0", "M"])
    folder = tmp_path / "B0" / "maintenance" / "halumem" / "alice" / "3"
    write_json(folder / "complete.json", {"source_batches": 1})
    write_json(folder / "batch-0000" / "before.json", [row("Old")])
    with pytest.raises(ValueError, match="snapshot missing"):
        snapshots(tmp_path, "B0", "alice", 3)
    write_json(folder / "batch-0000" / "after.json", [row("New", 2)])
    write_json(
        folder / "batch-0000" / "complete.json", {"receipts": [{"ok": False, "status": "rejected"}]}
    )
    first, second, availability = snapshots(tmp_path, "B0", "alice", 3)
    assert first[0]["value"]["revision"] == 1
    assert second[0]["value"]["revision"] == 2
    assert availability["rejected_receipts"] == 1


def test_failed_judgments_stay_in_all_opportunities_and_users_are_paired() -> None:
    records = []
    for arm in ["B1", "M"]:
        for variant in ["Actual", "NeverWrite", "RetainAll"]:
            for owner in ["alice", "bob"]:
                valid = owner == "alice"
                judgment = {
                    "new_requirement_satisfied": arm == "M",
                    "initial_target_present": False,
                    "valid_prior_claims": 1,
                    "damaged_valid_prior_claims": [],
                    "unsupported_additions": [],
                    "prior_grounding_unknown": [],
                    "current_conflicts": ["Two incompatible current values"],
                    "cancellation_succeeded": arm == "M",
                }
                records.append(
                    {
                        "uuid": owner,
                        "arm": arm,
                        "variant": variant,
                        "cancellation_opportunity": True,
                        "transition": {
                            "status": "VALID" if valid else "INVALID_FIRST_ATTEMPT",
                            "judgment": judgment,
                        },
                        "answer_assessment": {"status": "ANSWER_UNAVAILABLE"},
                    }
                )
    report = summarize_native(records, ["B1", "M"])
    m = report["metrics"]["M/Actual"]
    assert m["opportunities"] == 2 and m["valid_transition_judgments"] == 1
    assert m["requirement_satisfied_all"] == 0.5
    assert m["requirement_satisfied_valid"] == 1
    assert m["full_answer_supported_all"] == 0
    assert m["initial_target_present"] == 0
    assert m["valid_prior_grounding_opportunities"] == 1
    assert m["current_conflict_opportunities_valid"] == 1
    assert m["cancellation_opportunities"] == 2
    assert m["scored_cancellation_opportunities"] == 1
    assert m["cancellation_succeeded_all"] == 0.5
    paired = report["paired_requirement_effects"]["B1:M"]
    assert paired["users"] == 2 and paired["difference_second_minus_first"] == 0.5
    collateral = report["paired_mechanism_effects"]["B1:M"]["non_target_damage_valid_grounded"]
    assert collateral["paired_users"] == ["alice"]
    assert collateral["unscored_users"] == ["bob"]
    assert collateral["effect"]["users"] == 1 and collateral["lower_is_better"]
    assert m["non_target_damage_rate_valid_grounded"] == 0
    assert m["unsupported_addition_rate_valid"] == 0


def test_full_answer_audit_keeps_every_original_session_and_exact_answer(tmp_path: Path) -> None:
    original = {
        "question": "What is my current rule?",
        "question_date": "2030/03/03",
        "answer": "Once weekly",
        "haystack_session_ids": ["later", "earlier", "unrelated"],
        "haystack_dates": ["2030/02/01", "2030/01/01", "2030/01/15"],
        "haystack_sessions": [
            [{"role": "user", "content": "Change to once weekly", "has_answer": True}],
            [{"role": "user", "content": "Twice weekly", "has_answer": False}],
            [{"role": "assistant", "content": "Unrelated old discussion", "has_answer": False}],
        ],
        "answer_session_ids": ["later"],
    }
    payload = full_answer_payload(original, "Once weekly. An unsupported cause.")
    assert payload["answer"] == "Once weekly. An unsupported cause."
    assert payload["full_history_sessions"] == 3
    assert [r["session_id"] for r in payload["full_observed_history"]] == [
        "earlier",
        "unrelated",
        "later",
    ]
    assert "has_answer" not in str(payload) and "answer_session_ids" not in payload
    write_json(tmp_path / "M" / "terminal.json", {"status": "COMPLETED_EXPERIMENT_PHASE"})
    with pytest.raises(ValueError, match="external arm"):
        require_completed_external(tmp_path, ["M"])


def test_continuous_damage_reports_invalid_gaps_and_original_chronology() -> None:
    assessment = {
        "status": "VALID",
        "judgment": {
            "damaged_valid_prior_claims": [{"record_id": "record_0", "claim": "Paused holidays"}],
            "unsupported_additions": [],
            "current_conflicts": [],
            "cancellation_succeeded": None,
        },
    }
    assert (
        validate_transition(assessment, [], [{"record_id": "record_0"}], cancellation=False)[
            "status"
        ]
        == "INVALID_FIRST_ATTEMPT"
    )
    records = [
        {
            "arm": "M",
            "uuid": "alice",
            "chronological_step": 1,
            "session": 61,
            "transition": {"status": "INVALID_FIRST_ATTEMPT"},
        },
        {
            "arm": "M",
            "uuid": "alice",
            "chronological_step": 0,
            "session": 62,
            "transition": assessment,
        },
    ]
    result = summarize_drift(records)["trajectories"]["M/alice"]
    assert [r["session"] for r in result] == [62, 61]
    assert result[-1]["cumulative_damage_events"] == 1
    assert result[-1]["cumulative_valid_judgments"] == 1
    assert result[-1]["unscored_steps_to_date"] == 1
    assert result[-1]["current_conflicts"] is None


def test_controlled_formation_inputs_exclude_reviews_questions_and_future_events() -> None:
    manifest = Path(__file__).parents[2] / "data/manifests/milai-edit-controlled-dialogues-v1.json"
    cases = json.loads(manifest.read_text())["cases"]
    for case in cases:
        for variant in case["variants"]:
            observed = controlled_observations(case, variant)
            assert len(observed) == 5
            assert all(s.date < t.date for s, t in pairwise(observed))
            assert "source_supported_requirement" not in str(observed)
            assert "diagnostic_questions" not in str(observed)
            assert len(observed[0].turns) == 1
    independent = cases[2]
    ordinary = controlled_events(independent, "en")
    swapped = controlled_events(independent, "en_independent_swap")
    assert [r["event_id"] for r in swapped] == [
        "formation",
        "cancel_salmon",
        "salary_raise",
        "retirement_uncertain",
        "unconfirmed_assistant",
    ]
    assert {r["event_id"] for r in ordinary} == {r["event_id"] for r in swapped}
    assert controlled_observations(independent, "en")[-1].turns[0]["role"] == "assistant"
    invalid = {**independent, "independent_order_pair": ["formation", "salary_raise"]}
    with pytest.raises(ValueError, match="adjacent independent updates"):
        controlled_events(invalid, "en_independent_swap")


def test_unfrozen_candidate_and_invalid_controlled_answers_are_not_successes(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.json"
    write_json(candidate, {"status": "PREPARED"})
    with pytest.raises(ValueError, match="Fix the final candidate"):
        require_frozen_candidate({"method_version": "v1"}, candidate)
    rows = [
        {
            "source_cluster": "story",
            "variant": "en",
            "arm": "M",
            "chronological_step": 1,
            "classification": "scope_override",
            "cancellation_opportunity": True,
            "transition": {"status": "INVALID_FIRST_ATTEMPT"},
            "answer_assessment": {"status": "ANSWER_UNAVAILABLE"},
        }
    ]
    metrics = summarize_controlled(rows, ["M"])["metrics"]["M"]
    assert metrics["opportunities"] == 1 and metrics["valid_transition_judgments"] == 0
    assert metrics["scope_transition_and_full_answer_correct_all"] == 0
    assert metrics["cancellation_succeeded_all"] == 0
    assert metrics["full_answer_supported_all"] == 0


def test_supported_answer_without_the_required_result_is_not_scope_success() -> None:
    rows = [
        {
            "source_cluster": "story",
            "variant": "en",
            "arm": "M",
            "chronological_step": 1,
            "classification": "scope_override",
            "cancellation_opportunity": False,
            "transition": {
                "status": "VALID",
                "judgment": {
                    "new_requirement_satisfied": True,
                    "damaged_valid_prior_claims": [],
                    "unsupported_additions": [],
                },
            },
            "answer_assessment": {
                "status": "VALID",
                "judgment": {
                    "requirement_correct": False,
                    "complete_and_supported": True,
                },
            },
        }
    ]
    metrics = summarize_controlled(rows, ["M"])["metrics"]["M"]
    assert metrics["full_answer_supported_all"] == 1
    assert metrics["full_answer_correct_and_supported_all"] == 0
    assert metrics["scope_transition_and_full_answer_correct_all"] == 0
