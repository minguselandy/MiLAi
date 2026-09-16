from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.agent_integration.fast_path_shadow import (
    FastPathShadowError,
    _advance_host_task_state,
    _append_turn_messages,
    _build_history,
    _cache_negative_controls,
    _host_state_observed,
    _initial_host_task_state,
    _summarize,
    _verify_confirmation_commitments,
)


def _cache_control_result(reason: str) -> dict[str, object]:
    return {
        "status": "ABSTAIN",
        "reason": reason,
        "validation_token": None,
        "recall_execution_trace": {
            "result": "MISS",
            "terminal_route": "CACHE",
            "route_trace_complete": True,
            "query_embedding_calls": 0,
            "vector_calls": 0,
            "reranker_calls": 0,
        },
    }


class _CacheControlMcp:
    def __init__(self) -> None:
        self.calls = 0

    def prepare_memory_context(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        responses: dict[int, dict[str, object]] = {
            1: {
                "status": "READY",
                "validation_token": "coverage-token",
                "memory_slot_coverage": {},
            },
            2: {"status": "ABSTAIN", "reason": "CURRENT_STATE_UNCERTAIN"},
            3: {
                "status": "READY",
                "validation_token": "stale-token",
                "memory_slot_coverage": {},
            },
            4: _cache_control_result("CACHE_STATE_KEY_UNCOVERED"),
            5: _cache_control_result("STALE_TASK_SLOT"),
            6: {
                "status": "READY",
                "validation_token": "proof-token",
                "memory_slot_coverage": {},
            },
            7: _cache_control_result("BROKER_BOUND_VALIDATION_PROOF_INVALID"),
        }
        return responses[self.calls]


class _CacheControlRuntime:
    def __init__(self) -> None:
        self.transitions: list[dict[str, object]] = []

    def apply_claim_transition(self, **kwargs: object) -> dict[str, str]:
        self.transitions.append(kwargs)
        return {
            "claim_version_id": "advanced-version",
            "evidence_id": "advanced-evidence",
        }


def test_cache_controls_skip_an_unavailable_fixture_key() -> None:
    database_key = ("orchid", "release.database", "PROJECT_CONFIG")
    mcp = _CacheControlMcp()
    runtime = _CacheControlRuntime()
    receipts = {
        database_key: {
            "claim_id": "config-claim",
            "claim_version_id": "config-version",
            "evidence_id": "config-evidence",
        }
    }
    workload = {
        "workload_id": "FASTPATH_DEV",
        "fixture_state": [
            {
                "state_key": {
                    "subject": "orchid",
                    "predicate": "release.target",
                    "claim_type": "PROJECT_STATE",
                }
            },
            {
                "state_key": {
                    "subject": "orchid",
                    "predicate": "release.deadline",
                    "claim_type": "PROJECT_STATE",
                }
            },
            {
                "state_key": {
                    "subject": database_key[0],
                    "predicate": database_key[1],
                    "claim_type": database_key[2],
                }
            },
        ],
    }

    controls = _cache_negative_controls(
        type("Adapter", (), {"host_mcp": mcp})(),
        runtime,  # type: ignore[arg-type]
        receipts,
        workload,
        {"project_ids": ["synthetic-orchid"]},
    )

    assert mcp.calls == 7
    assert [item["passed"] for item in controls] == [True, True, True]
    assert runtime.transitions[0]["claim_id"] == "config-claim"


def test_build_history_preserves_typed_fixture_as_synthetic_product_input() -> None:
    history = _build_history(
        {
            "workload_id": "FASTPATH_DEV",
            "project_id": "synthetic-orchid",
            "fixture_state": [
                {
                    "state_key": {
                        "subject": "orchid-release",
                        "predicate": "release.target",
                        "claim_type": "PROJECT_STATE",
                    },
                    "value": "rc-7",
                }
            ],
        }
    )

    assert history.dataset_id == "SYNTHETIC_FAST_PATH_SHADOW"
    assert history.metadata["scope_project_ids"] == ["synthetic-orchid"]
    assert history.metadata["claim_projections"] == [
        {
            "subject_id": "orchid-release",
            "predicate": "release.target",
            "claim_type": "PROJECT_STATE",
        }
    ]
    assert history.metadata["claim_payloads"] == [{"value": "rc-7"}]
    assert '"predicate":"release.target"' in history.items[0].content
    assert '"value":"rc-7"' in history.items[0].content


def test_confirmation_labels_must_match_frozen_commitments(tmp_path: Path) -> None:
    workloads = tmp_path / "workloads.yaml"
    workloads.write_text("sealed workload bytes\n", encoding="utf-8")
    label = {
        "schema": "milai.dg12.fast-path-label.v1",
        "workload_id": "FASTPATH_CONFIRMATION",
        "turn_id": "CONF-T01",
        "memory_dependency": "NONE",
        "intent_class": "NONE",
        "state_key": None,
        "fast_eligible": True,
        "required_authority": "INFORMATIONAL",
        "consistency": "CANONICAL_REQUIRED",
        "expected_route_set": ["NONE"],
        "expected_result_set": ["HIT"],
        "independent_from_resolver": True,
    }
    salt = "8" * 64
    canonical = json.dumps(label, sort_keys=True, separators=(",", ":"))
    seal = {
        "schema": "milai.dg12.fast-path-confirmation-seal.v1",
        "workload_id": "FASTPATH_CONFIRMATION",
        "workloads_sha256": hashlib.sha256(workloads.read_bytes()).hexdigest(),
        "commitment_scheme": {"salt_hex": salt},
        "label_schema_fields": list(label),
        "commitments": [
            {
                "turn_id": "CONF-T01",
                "sha256": hashlib.sha256((salt + canonical).encode()).hexdigest(),
            }
        ],
    }
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal), encoding="utf-8")

    verified = _verify_confirmation_commitments(
        {"CONF-T01": label}, seal_path=seal_path, workloads_path=workloads
    )
    assert verified["status"] == "VERIFIED"
    assert verified["labels_verified"] == 1

    with pytest.raises(FastPathShadowError, match="commitment mismatch"):
        _verify_confirmation_commitments(
            {"CONF-T01": {**label, "fast_eligible": False}},
            seal_path=seal_path,
            workloads_path=workloads,
        )


def test_continuous_messages_retain_prior_tool_result_for_characterization() -> None:
    messages: list[dict[str, str]] = []

    _append_turn_messages(
        messages,
        {"host_event": "TOOL_RESULT", "user_text": "What is current?"},
    )
    _append_turn_messages(
        messages,
        {"host_event": "MODEL_RETRY", "user_text": "Retry."},
    )

    assert [item["role"] for item in messages] == ["tool", "user", "user"]


def test_host_task_state_changes_only_on_explicit_directives() -> None:
    state = _initial_host_task_state(
        {
            "task_id": "task-orchid-release",
            "primary_goal_id": "goal-orchid-release",
            "primary_goal_version": 1,
            "primary_goal_summary": "Prepare Orchid.",
            "initial_scope": {"project_ids": ["synthetic-orchid"]},
            "initial_profile": "reader-lite",
        }
    )

    unchanged = _advance_host_task_state(
        state,
        {
            "directive": "CONTINUE",
            "requested_scope": {"project_ids": ["synthetic-cedar"]},
        },
    )
    audit = _advance_host_task_state(
        unchanged,
        {
            "directive": "SWITCH_GOAL",
            "goal_id": "goal-orchid-audit",
            "goal_version": 1,
            "goal_summary": "Audit Orchid.",
        },
    )
    scoped = _advance_host_task_state(
        audit,
        {
            "directive": "SWITCH_SCOPE",
            "requested_scope": {"project_ids": ["synthetic-cedar"]},
        },
    )
    profiled = _advance_host_task_state(
        scoped,
        {"directive": "SWITCH_PROFILE", "profile_id": "submitter"},
    )

    assert unchanged == state
    assert audit["active_goal_id"] == "goal-orchid-audit"
    assert audit["task_id"].endswith("::goal::goal-orchid-audit")
    assert scoped["project_scope"] == {"project_ids": ["synthetic-cedar"]}
    assert scoped["task_generation"] == 2
    assert profiled["profile_identity"] == "submitter"
    assert profiled["task_generation"] == 3


def test_host_state_observation_checks_the_full_binding() -> None:
    state = {
        "task_id": "task-orchid-release",
        "active_goal_id": "goal-orchid-release",
        "active_goal_version": 1,
        "active_goal_summary": "Prepare Orchid.",
        "project_scope": {"project_ids": ["synthetic-orchid"]},
        "profile_id": "reader-lite",
    }
    event = {
        "task_id_sha256": hashlib.sha256(b"task-orchid-release").hexdigest(),
        "active_goal_id_sha256": hashlib.sha256(b"goal-orchid-release").hexdigest(),
        "active_goal_version": 1,
        "active_goal_sha256": hashlib.sha256(b"Prepare Orchid.").hexdigest(),
        "project_scope_sha256": hashlib.sha256(
            b'{"project_ids":["synthetic-orchid"]}'
        ).hexdigest(),
        "profile_id": "reader-lite",
    }

    assert _host_state_observed(state, event) is True
    assert _host_state_observed({**state, "profile_id": "submitter"}, event) is False


def test_shadow_summary_keeps_formal_route_completeness_explicit() -> None:
    summary = _summarize(
        [
            {
                "terminal_route": "NONE",
                "expected_route_set": ["NONE"],
                "route_trace_complete": True,
                "memory_control_ms": None,
                "task_key": None,
                "fast_eligible": True,
                "state_key_present": False,
                "memory_dependency": "NONE",
                "intent_class": "NONE",
                "canonical_state_key_exists_initial": None,
                "canonical_state_key_exists_at_turn": None,
                "required_authority": "INFORMATIONAL",
                "requested_route": "NONE",
                "validated_route": "NONE",
                "policy_override_reason": None,
                "query_embedding_calls": 0,
            },
            {
                "terminal_route": "L1",
                "expected_route_set": ["L0"],
                "route_trace_complete": False,
                "memory_control_ms": 12.0,
                "task_key": "key-1",
                "retained_slot_present": False,
                "fast_eligible": True,
                "state_key_present": True,
                "memory_dependency": "REQUIRED",
                "intent_class": "CURRENT_STATE",
                "canonical_state_key_exists_initial": True,
                "canonical_state_key_exists_at_turn": True,
                "required_authority": "INFORMATIONAL",
                "requested_route": "L1",
                "validated_route": "L1",
                "policy_override_reason": None,
                "query_embedding_calls": 1,
            },
        ]
    )

    assert summary["route_trace_complete_turns"] == 1
    assert summary["provisional_actual_route_in_expected_set_turns"] == 1
    assert summary["route_counts"] == {"L1": 1, "NONE": 1}
    assert summary["independent_fast_eligibility_rate"] == 1.0
    assert summary["independent_state_key_labeled_turns"] == 1
    assert summary["route_execution_fidelity"] == 1.0
    assert summary["execution_calls"]["query_embedding_calls"] == 1
    assert summary["prechange_state_addressability"]["rate"] == 1.0
