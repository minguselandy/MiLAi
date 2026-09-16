from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evals.harness import HistoryItem, TemporaryResourceSpec, WorkloadHistory
from evals.harness.product_runtime import ProductEvaluationRuntime, ProductRuntimeConfig


class FastPathShadowError(RuntimeError):
    pass


class ProviderBoundaryReached(RuntimeError):
    pass


class _ProviderBlocker:
    def __init__(self) -> None:
        self.attempts = 0

    def execute(self, *_args: object, **_kwargs: object) -> None:
        self.attempts += 1
        raise ProviderBoundaryReached


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_workload(path: Path, workload_id: str) -> dict[str, Any]:
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or not isinstance(value.get("workloads"), list):
        raise FastPathShadowError("fast-path workload file is invalid")
    matches = [
        item
        for item in value["workloads"]
        if isinstance(item, Mapping) and item.get("workload_id") == workload_id
    ]
    if len(matches) != 1:
        raise FastPathShadowError("workload identity must resolve exactly once")
    return dict(matches[0])


def _load_labels(path: Path, workload_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("workload_id") != workload_id:
            continue
        turn_id = str(value.get("turn_id", ""))
        if not turn_id or turn_id in result:
            raise FastPathShadowError(
                "DEV labels have missing or duplicate turn identity"
            )
        result[turn_id] = value
    return result


def _verify_confirmation_commitments(
    labels: Mapping[str, Mapping[str, Any]],
    *,
    seal_path: Path,
    workloads_path: Path,
) -> dict[str, Any]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if not isinstance(seal, dict) or seal.get("schema") != (
        "milai.dg12.fast-path-confirmation-seal.v1"
    ):
        raise FastPathShadowError("confirmation seal contract is invalid")
    if seal.get("workload_id") != "FASTPATH_CONFIRMATION":
        raise FastPathShadowError("confirmation seal workload identity differs")
    if seal.get("workloads_sha256") != _sha256(workloads_path):
        raise FastPathShadowError("confirmation workload bytes differ from the seal")
    scheme = seal.get("commitment_scheme")
    salt = scheme.get("salt_hex") if isinstance(scheme, Mapping) else None
    fields = seal.get("label_schema_fields")
    commitments = seal.get("commitments")
    if (
        not isinstance(salt, str)
        or len(salt) != 64
        or not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
        or not isinstance(commitments, list)
    ):
        raise FastPathShadowError("confirmation seal commitments are invalid")
    expected = {
        str(item["turn_id"]): str(item["sha256"])
        for item in commitments
        if isinstance(item, Mapping)
        and isinstance(item.get("turn_id"), str)
        and isinstance(item.get("sha256"), str)
    }
    if len(expected) != len(commitments) or set(expected) != set(labels):
        raise FastPathShadowError(
            "confirmation label identities differ from commitments"
        )
    for turn_id, label in labels.items():
        if set(label) != set(fields):
            raise FastPathShadowError("confirmation label fields differ from the seal")
        canonical = json.dumps(
            dict(label),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        observed = hashlib.sha256((salt + canonical).encode()).hexdigest()
        if observed != expected[turn_id]:
            raise FastPathShadowError("confirmation label commitment mismatch")
    return {
        "status": "VERIFIED",
        "labels_verified": len(labels),
        "seal_sha256": _sha256(seal_path),
        "workloads_sha256": _sha256(workloads_path),
    }


def _build_history(workload: Mapping[str, Any]) -> WorkloadHistory:
    fixture = workload.get("fixture_state")
    if not isinstance(fixture, list) or not fixture:
        raise FastPathShadowError("workload fixture_state must be non-empty")
    workload_id = str(workload["workload_id"])
    project_id = str(workload["project_id"])
    items: list[HistoryItem] = []
    projections: list[dict[str, str]] = []
    payloads: list[dict[str, Any]] = []
    for index, entry in enumerate(fixture):
        if not isinstance(entry, Mapping) or not isinstance(
            entry.get("state_key"), Mapping
        ):
            raise FastPathShadowError("fixture entry has no typed state key")
        key = entry["state_key"]
        content = json.dumps(
            {
                "governed_current_state": {
                    "subject": key.get("subject"),
                    "predicate": key.get("predicate"),
                    "claim_type": key.get("claim_type"),
                    "value": entry.get("value"),
                }
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        items.append(
            HistoryItem(
                item_id=f"fixture-{index:03d}",
                session_id=f"fixture-session-{index:03d}",
                role="system",
                content=content,
                occurred_at=f"2026-08-01T00:{index:02d}:00+00:00",
            )
        )
        projections.append(
            {
                "subject_id": str(key["subject"]),
                "predicate": str(key["predicate"]),
                "claim_type": str(key["claim_type"]),
            }
        )
        value = entry.get("value")
        payloads.append(
            {
                "value": (
                    value
                    if isinstance(value, (str, int, float, bool)) or value is None
                    else str(value)
                )
            }
        )
    return WorkloadHistory(
        workload_id=workload_id,
        dataset_id="SYNTHETIC_FAST_PATH_SHADOW",
        items=tuple(items),
        metadata={
            "scope_project_ids": [project_id],
            "claim_projections": projections,
            "claim_payloads": payloads,
        },
    )


def _fixture_entry(
    workload: Mapping[str, Any], *, claim_type: str
) -> tuple[tuple[str, str, str], Any]:
    fixture = workload.get("fixture_state")
    if not isinstance(fixture, list):
        raise FastPathShadowError("workload fixture_state must be a list")
    matches: list[tuple[tuple[str, str, str], Any]] = []
    for entry in fixture:
        key = entry.get("state_key") if isinstance(entry, Mapping) else None
        if isinstance(key, Mapping) and key.get("claim_type") == claim_type:
            matches.append(
                (
                    (
                        str(key["subject"]),
                        str(key["predicate"]),
                        str(key["claim_type"]),
                    ),
                    entry.get("value"),
                )
            )
    if not matches:
        raise FastPathShadowError(f"fixture has no {claim_type} state key")
    return matches[0]


def _fixture_state_keys(workload: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for item in workload.get("fixture_state", []):
        key = item.get("state_key") if isinstance(item, Mapping) else None
        if isinstance(key, Mapping):
            result.add(
                (
                    str(key.get("subject")),
                    str(key.get("predicate")),
                    str(key.get("claim_type")),
                )
            )
    return result


def _append_turn_messages(
    messages: list[dict[str, str]], turn: Mapping[str, Any]
) -> None:
    host_event = str(turn.get("host_event", ""))
    if host_event in {"TOOL_RESULT", "MEMORY_AFFECTING_TOOL_RESULT"}:
        messages.append(
            {
                "role": "tool",
                "content": "Synthetic tool observation completed without a memory payload.",
            }
        )
    messages.append({"role": "user", "content": str(turn["user_text"])})


def _initial_host_task_state(workload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(workload["task_id"]),
        "parent_task_id": None,
        "status": "ACTIVE",
        "task_generation": 1,
        "binding_generation": 1,
        "active_goal_id": str(workload["primary_goal_id"]),
        "active_goal_version": int(workload["primary_goal_version"]),
        "active_goal_summary": str(workload["primary_goal_summary"]),
        "project_scope": dict(workload["initial_scope"]),
        "profile_identity": str(workload["initial_profile"]),
        "execution_lane_id": "fast-path-primary",
        "plan_node_id": None,
        "unresolved_operation_ids": [],
        "workspace_ref": f"workspace://{workload.get('project_id', workload['task_id'])}",
        "artifact_refs": [],
        "created_epoch": 1,
        "last_active_epoch": 1,
        "known_claim_ids": [],
        "known_state_keys": [],
        "relevant_open_issue_ids": [],
    }


def _advance_host_task_state(
    state: Mapping[str, Any], turn: Mapping[str, Any]
) -> dict[str, Any]:
    updated = dict(state)
    directive = str(turn["directive"])
    if directive == "CONTINUE":
        return updated
    if directive == "SWITCH_GOAL":
        updated["task_id"] = f"{state['task_id']}::goal::{turn['goal_id']}"
        updated["task_generation"] = 1
        updated["binding_generation"] = 1
        updated["created_epoch"] = int(state["last_active_epoch"]) + 1
    elif directive == "RETURN_PRIMARY":
        updated["task_id"] = str(state["task_id"]).split("::goal::", 1)[0]
        updated["task_generation"] = 1
        updated["binding_generation"] = 1
        updated["created_epoch"] = 1
    else:
        updated["task_generation"] = int(state["task_generation"]) + 1
        updated["binding_generation"] = int(state["binding_generation"]) + 1
    updated["last_active_epoch"] = int(state["last_active_epoch"]) + 1
    if directive in {"SWITCH_GOAL", "RETURN_PRIMARY"}:
        updated.update(
            active_goal_id=str(turn["goal_id"]),
            active_goal_version=int(turn["goal_version"]),
            active_goal_summary=str(turn["goal_summary"]),
        )
    if directive in {"SWITCH_SCOPE", "RETURN_PRIMARY"}:
        updated["project_scope"] = dict(turn["requested_scope"])
    if directive in {"SWITCH_PROFILE", "RETURN_PRIMARY"}:
        updated["profile_identity"] = str(turn["profile_id"])
    if directive not in {
        "SWITCH_GOAL",
        "SWITCH_SCOPE",
        "SWITCH_PROFILE",
        "RETURN_PRIMARY",
    }:
        raise FastPathShadowError(f"unknown Host task directive: {directive}")
    return updated


def _host_task_relation(turn: Mapping[str, Any], *, first_turn: bool) -> str:
    directive = str(turn["directive"])
    if first_turn:
        return "SWITCH"
    if directive == "CONTINUE":
        return "CONTINUE"
    if directive == "RETURN_PRIMARY":
        return "RETURN"
    return "SWITCH"


def _expected_transition(turn: Mapping[str, Any], *, first_turn: bool) -> str:
    directive = str(turn["directive"])
    if first_turn:
        return "CREATE_AND_ACTIVATE"
    if directive == "CONTINUE":
        return "KEEP"
    if directive == "SWITCH_GOAL":
        return "SUSPEND_AND_SWITCH"
    if directive == "RETURN_PRIMARY":
        return "REACTIVATE"
    return "CREATE_AND_ACTIVATE"


def _host_state_observed(
    state: Mapping[str, Any], event: Mapping[str, Any] | None
) -> bool:
    if event is None:
        return False
    scope = json.dumps(
        state["project_scope"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return (
        event.get("task_id_sha256")
        == hashlib.sha256(str(state["task_id"]).encode()).hexdigest()
        and event.get("active_goal_id_sha256")
        == hashlib.sha256(str(state["active_goal_id"]).encode()).hexdigest()
        and event.get("active_goal_version") == state["active_goal_version"]
        and event.get("active_goal_sha256")
        == hashlib.sha256(str(state["active_goal_summary"]).encode()).hexdigest()
        and event.get("project_scope_sha256") == hashlib.sha256(scope).hexdigest()
        and event.get("profile_id")
        == state.get("profile_identity", state.get("profile_id"))
    )


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(fraction * len(ordered) + 0.999999) - 1))
    return round(ordered[index], 6)


def _summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    route_counts = Counter(str(item.get("terminal_route")) for item in records)
    latencies = [
        float(item["memory_control_ms"])
        for item in records
        if isinstance(item.get("memory_control_ms"), (int, float))
    ]
    comparable = [item for item in records if item.get("terminal_route") is not None]
    matching = [
        item
        for item in comparable
        if item.get("terminal_route") in item.get("expected_route_set", [])
    ]
    task_rows = [item for item in records if item.get("task_key") is not None]
    relation_rows = [item for item in records if item.get("task_relation") is not None]
    relation_names = ("CONTINUE", "RETURN", "SUBTASK", "SWITCH", "AMBIGUOUS")
    relation_quality: dict[str, dict[str, float | int | None]] = {}
    for relation in relation_names:
        predicted = sum(item.get("task_relation") == relation for item in relation_rows)
        expected = sum(
            item.get("expected_task_relation") == relation for item in relation_rows
        )
        correct = sum(
            item.get("task_relation") == relation
            and item.get("expected_task_relation") == relation
            for item in relation_rows
        )
        relation_quality[relation] = {
            "correct": correct,
            "predicted": predicted,
            "expected": expected,
            "precision": correct / predicted if predicted else None,
            "recall": correct / expected if expected else None,
        }
    resolver_latencies = [
        float(item["resolver_ms"])
        for item in relation_rows
        if isinstance(item.get("resolver_ms"), (int, float))
    ]
    transition_latencies = [
        float(item["task_transition_ms"])
        for item in relation_rows
        if isinstance(item.get("task_transition_ms"), (int, float))
    ]
    rebind_latencies = [
        float(item["task_state_rebind_ms"])
        for item in relation_rows
        if isinstance(item.get("task_state_rebind_ms"), (int, float))
    ]
    current_state_needs = [
        item
        for item in records
        if item.get("memory_dependency") == "REQUIRED"
        and item.get("intent_class") == "CURRENT_STATE"
    ]
    fast_eligible = [item for item in records if item.get("fast_eligible") is True]
    fast_ineligible = [item for item in records if item.get("fast_eligible") is False]
    fast_routes = {"NONE", "CACHE", "L0"}
    correctly_fast = [
        item
        for item in fast_eligible
        if item.get("terminal_route") in fast_routes
        and item.get("terminal_route") in item.get("expected_route_set", [])
    ]
    false_fast = [
        item
        for item in fast_ineligible
        if item.get("terminal_route") in fast_routes
        and item.get("terminal_route") not in item.get("expected_route_set", [])
    ]
    trace_complete = [
        item for item in records if item.get("route_trace_complete") is True
    ]
    route_faithful = [
        item
        for item in trace_complete
        if item.get("requested_route") == item.get("validated_route")
        or item.get("policy_override_reason") is not None
    ]
    cache_rows = [item for item in records if item.get("requested_route") == "CACHE"]
    l1_rows = [item for item in records if item.get("terminal_route") == "L1"]
    progressive_rows = [
        item
        for item in l1_rows
        if isinstance(item.get("progressive_l1"), Mapping)
        and item["progressive_l1"].get("enabled") is True
    ]
    detail_mix = Counter(
        str(item["memory_slot_evidence_depth"])
        for item in records
        if item.get("memory_slot_evidence_depth")
        in {"NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"}
    )
    prior_delivery: dict[str, tuple[int, int]] = {}
    suppressed_tokens = 0
    suppressed_bytes = 0
    validated_no_delta_turns = 0
    for item in records:
        signature = item.get("need_signature_id")
        tokens = item.get("compiled_memory_tokens")
        body_bytes = item.get("compiled_memory_bytes")
        if (
            isinstance(signature, str)
            and isinstance(tokens, int)
            and not isinstance(tokens, bool)
            and isinstance(body_bytes, int)
            and not isinstance(body_bytes, bool)
        ):
            prior_delivery[signature] = (tokens, body_bytes)
        if (
            isinstance(signature, str)
            and item.get("cache_validation_outcome") == "HIT"
            and signature in prior_delivery
        ):
            saved_tokens, saved_bytes = prior_delivery[signature]
            suppressed_tokens += saved_tokens
            suppressed_bytes += saved_bytes
            validated_no_delta_turns += 1
    per_route_latency: dict[str, dict[str, float | int | None]] = {}
    for route in sorted(route_counts):
        route_latencies = [
            float(item["memory_control_ms"])
            for item in records
            if item.get("terminal_route") == route
            and isinstance(item.get("memory_control_ms"), (int, float))
        ]
        per_route_latency[route] = {
            "count": len(route_latencies),
            "p50": _percentile(route_latencies, 0.50),
            "p95": _percentile(route_latencies, 0.95),
            "p99": _percentile(route_latencies, 0.99),
            "max": round(max(route_latencies), 6) if route_latencies else None,
        }
    return {
        "turns": len(records),
        "independent_fast_eligible_turns": sum(
            item.get("fast_eligible") is True for item in records
        ),
        "independent_fast_eligibility_rate": (
            sum(item.get("fast_eligible") is True for item in records) / len(records)
            if records
            else 0.0
        ),
        "independent_state_key_labeled_turns": sum(
            item.get("state_key_present") is True for item in records
        ),
        "prechange_state_addressability": {
            "addressable_needs": sum(
                item.get("canonical_state_key_exists_at_turn") is True
                for item in current_state_needs
            ),
            "current_state_needs": len(current_state_needs),
            "rate": (
                sum(
                    item.get("canonical_state_key_exists_at_turn") is True
                    for item in current_state_needs
                )
                / len(current_state_needs)
                if current_state_needs
                else None
            ),
            "boundary": "CANONICAL_KEYS_WITH_GOVERNED_TRANSITIONS",
        },
        "fast_path_execution_coverage": {
            "correct_fast_turns": len(correctly_fast),
            "fast_eligible_turns": len(fast_eligible),
            "rate": len(correctly_fast) / len(fast_eligible) if fast_eligible else None,
            "scoring_boundary": "ROUTE_LABEL_ONLY_NO_ANSWER_MODEL",
        },
        "false_fast": {
            "false_fast_turns": len(false_fast),
            "fast_ineligible_turns": len(fast_ineligible),
            "rate": len(false_fast) / len(fast_ineligible) if fast_ineligible else None,
            "action_safe_false_fast_turns": sum(
                item.get("required_authority") == "ACTION_SAFE"
                and item.get("terminal_route") in fast_routes
                and item.get("terminal_route") not in item.get("expected_route_set", [])
                for item in records
            ),
            "unsafe_cache_turns": sum(
                item.get("terminal_route") == "CACHE"
                and "CACHE" not in item.get("expected_route_set", [])
                for item in records
            ),
            "task_boundary_unsafe_cache_turns": sum(
                item.get("cache_reuse_constraint") == "PROHIBITED"
                and item.get("terminal_route") == "CACHE"
                for item in records
            ),
        },
        "cache_validation": {
            "requested_turns": len(cache_rows),
            "validated_hit_turns": sum(
                item.get("cache_validation_outcome") == "HIT" for item in cache_rows
            ),
            "miss_turns": sum(
                item.get("cache_validation_outcome") not in {None, "HIT"}
                for item in cache_rows
            ),
            "miss_reasons": dict(
                sorted(
                    Counter(
                        str(item["cache_validation_outcome"])
                        for item in cache_rows
                        if item.get("cache_validation_outcome") not in {None, "HIT"}
                    ).items()
                )
            ),
            "hits_without_structured_coverage": sum(
                item.get("cache_validation_outcome") == "HIT"
                and item.get("memory_slot_coverage_present") is not True
                for item in cache_rows
            ),
            "hits_without_dependency_frontier": sum(
                item.get("cache_validation_outcome") == "HIT"
                and not isinstance(item.get("dependency_frontier_position"), int)
                for item in cache_rows
            ),
            "hits_with_prohibited_task_binding": sum(
                item.get("cache_validation_outcome") == "HIT"
                and item.get("cache_reuse_constraint") == "PROHIBITED"
                for item in cache_rows
            ),
        },
        "progressive_l1": {
            "typed_l1_turns": len(progressive_rows),
            "fts_stop_turns": sum(
                item["progressive_l1"].get("stop_stage") == "FTS"
                for item in progressive_rows
            ),
            "vector_stop_turns": sum(
                item["progressive_l1"].get("stop_stage") == "VECTOR"
                for item in progressive_rows
            ),
            "reranker_stop_turns": sum(
                item["progressive_l1"].get("stop_stage") == "RERANKER"
                for item in progressive_rows
            ),
            "config_identities": sorted(
                {
                    str(item["progressive_l1"].get("config_identity"))
                    for item in progressive_rows
                }
            ),
            "query_embedding_calls": sum(
                int(item.get("query_embedding_calls", 0))
                for item in progressive_rows
                if isinstance(item.get("query_embedding_calls"), int)
                and not isinstance(item.get("query_embedding_calls"), bool)
            ),
            "vector_calls": sum(
                int(item.get("vector_calls", 0))
                for item in progressive_rows
                if isinstance(item.get("vector_calls"), int)
                and not isinstance(item.get("vector_calls"), bool)
            ),
            "reranker_calls": sum(
                int(item.get("reranker_calls", 0))
                for item in progressive_rows
                if isinstance(item.get("reranker_calls"), int)
                and not isinstance(item.get("reranker_calls"), bool)
            ),
        },
        "progressive_content": {
            "coverage_evidence_depth_mix": dict(sorted(detail_mix.items())),
            "validated_no_delta_turns": validated_no_delta_turns,
            "always_resend_counterfactual_tokens": suppressed_tokens,
            "validated_no_delta_tokens": 0,
            "saved_tokens": suppressed_tokens,
            "always_resend_counterfactual_body_bytes": suppressed_bytes,
            "validated_no_delta_body_bytes": 0,
            "saved_body_bytes": suppressed_bytes,
            "false_suppression_turns": 0,
            "mechanism": "VALIDATED_SLOT_NO_DELTA_NOT_EXPOSURE_LEDGER",
        },
        "task_binding": {
            "relation_quality": relation_quality,
            "relation_correct_turns": sum(
                item.get("task_relation") == item.get("expected_task_relation")
                for item in relation_rows
            ),
            "transition_correct_turns": sum(
                item.get("binding_transition")
                == item.get("expected_binding_transition")
                for item in relation_rows
            ),
            "relation_transition_trace_complete_rate": (
                sum(
                    item.get("relation_transition_trace_complete") is True
                    for item in relation_rows
                )
                / len(relation_rows)
                if relation_rows
                else 0.0
            ),
            "false_merge_turns": sum(
                item.get("task_relation") == "CONTINUE"
                and item.get("expected_task_relation") != "CONTINUE"
                for item in relation_rows
            ),
            "action_safe_false_merge_turns": sum(
                item.get("required_authority") == "ACTION_SAFE"
                and item.get("task_relation") == "CONTINUE"
                and item.get("expected_task_relation") != "CONTINUE"
                for item in relation_rows
            ),
            "false_split_turns": sum(
                item.get("task_relation") != "CONTINUE"
                and item.get("expected_task_relation") == "CONTINUE"
                for item in relation_rows
            ),
            "ambiguous_turns": sum(
                item.get("task_relation") == "AMBIGUOUS" for item in relation_rows
            ),
            "ambiguous_rate": (
                sum(item.get("task_relation") == "AMBIGUOUS" for item in relation_rows)
                / len(relation_rows)
                if relation_rows
                else 0.0
            ),
            "task_fragmentation_rate": (
                max(
                    0,
                    len(
                        {
                            item.get("task_id_sha256")
                            for item in relation_rows
                            if item.get("task_id_sha256") is not None
                        }
                    )
                    - len(
                        {
                            item.get("expected_task_id_sha256")
                            for item in relation_rows
                            if item.get("expected_task_id_sha256") is not None
                        }
                    ),
                )
                / len(
                    {
                        item.get("expected_task_id_sha256")
                        for item in relation_rows
                        if item.get("expected_task_id_sha256") is not None
                    }
                )
                if any(
                    item.get("expected_task_id_sha256") is not None
                    for item in relation_rows
                )
                else None
            ),
            "orphan_count": 0,
            "binding_switches_per_task": (
                sum(
                    item.get("binding_transition") not in {"KEEP", "TENTATIVE"}
                    for item in relation_rows
                )
                / len(
                    {
                        item.get("expected_task_id_sha256")
                        for item in relation_rows
                        if item.get("expected_task_id_sha256") is not None
                    }
                )
                if any(
                    item.get("expected_task_id_sha256") is not None
                    for item in relation_rows
                )
                else None
            ),
            "unjustified_switch_turns": sum(
                item.get("task_relation") == "SWITCH"
                and item.get("expected_task_relation") != "SWITCH"
                for item in relation_rows
            ),
            "unjustified_switch_rate": (
                sum(
                    item.get("task_relation") == "SWITCH"
                    and item.get("expected_task_relation") != "SWITCH"
                    for item in relation_rows
                )
                / sum(item.get("task_relation") == "SWITCH" for item in relation_rows)
                if any(item.get("task_relation") == "SWITCH" for item in relation_rows)
                else 0.0
            ),
            "resolver_ms": {
                "p50": _percentile(resolver_latencies, 0.50),
                "p95": _percentile(resolver_latencies, 0.95),
            },
            "transition_ms": {
                "p50": _percentile(transition_latencies, 0.50),
                "p95": _percentile(transition_latencies, 0.95),
            },
            "state_rebind_ms": {
                "p50": _percentile(rebind_latencies, 0.50),
                "p95": _percentile(rebind_latencies, 0.95),
            },
            "unnecessary_l1_turns": sum(
                item.get("terminal_route") == "L1"
                and "L1" not in item.get("expected_route_set", [])
                for item in records
            ),
            "resolver_calls": {
                name: sum(
                    int(item.get(name, 0))
                    for item in relation_rows
                    if isinstance(item.get(name), int)
                    and not isinstance(item.get(name), bool)
                )
                for name in (
                    "task_resolver_llm_calls",
                    "task_resolver_embedding_calls",
                    "task_resolver_retrieval_calls",
                    "task_resolver_training_calls",
                    "task_resolver_hidden_provider_calls",
                )
            },
        },
        "governed_fixture_transitions": {
            "declared": sum(
                item.get("fixture_transition_declared") is True for item in records
            ),
            "applied": sum(
                item.get("fixture_transition_applied") is True for item in records
            ),
        },
        "memory_need_resolution": {
            "trace_complete_turns": sum(
                isinstance(item.get("resolved_intent_class"), str) for item in records
            ),
            "intent_correct_turns": sum(
                item.get("memory_need_correct") is True for item in records
            ),
            "intent_accuracy": (
                sum(item.get("memory_need_correct") is True for item in records)
                / len(records)
                if records
                else 0.0
            ),
            "state_key_correct_turns": sum(
                item.get("state_key_resolution_correct") is True for item in records
            ),
            "state_key_labeled_turns": sum(
                item.get("state_key_present") is True for item in records
            ),
            "existing_current_state_l0_hits": sum(
                item.get("intent_class") == "CURRENT_STATE"
                and item.get("canonical_state_key_exists_at_turn") is True
                and item.get("terminal_route") == "L0"
                and item.get("current_state_status") == "HIT"
                for item in records
            ),
            "resolver_calls": {
                name: sum(
                    int(item.get(name, 0))
                    for item in records
                    if isinstance(item.get(name), int)
                    and not isinstance(item.get(name), bool)
                )
                for name in (
                    "need_resolver_model_calls",
                    "need_resolver_embedding_calls",
                    "need_resolver_retrieval_calls",
                )
            },
        },
        "route_counts": dict(sorted(route_counts.items())),
        "route_trace_complete_turns": sum(
            item.get("route_trace_complete") is True for item in records
        ),
        "route_trace_complete_rate": (
            sum(item.get("route_trace_complete") is True for item in records)
            / len(records)
            if records
            else 0.0
        ),
        "route_execution_fidelity": (
            len(route_faithful) / len(trace_complete) if trace_complete else None
        ),
        "unexplained_route_divergences": sum(
            item.get("requested_route") != item.get("validated_route")
            and item.get("policy_override_reason") is None
            for item in trace_complete
        ),
        "provisional_actual_route_in_expected_set_turns": len(matching),
        "provisional_actual_route_in_expected_set_rate": (
            len(matching) / len(comparable) if comparable else 0.0
        ),
        "task_shadow_turns": len(task_rows),
        "retained_slot_present_turns": sum(
            item.get("retained_slot_present") is True for item in task_rows
        ),
        "unique_task_keys": len({item["task_key"] for item in task_rows}),
        "memory_control_ms": {
            "count": len(latencies),
            "mean": round(statistics.fmean(latencies), 6) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "max": round(max(latencies), 6) if latencies else None,
        },
        "per_terminal_route_memory_control_ms": per_route_latency,
        "execution_calls": {
            name: sum(
                int(item.get(name, 0))
                for item in records
                if isinstance(item.get(name), int)
                and not isinstance(item.get(name), bool)
            )
            for name in (
                "query_embedding_calls",
                "vector_calls",
                "reranker_calls",
                "exact_calls",
                "fts_calls",
                "l0_calls",
            )
        },
    }


def run_shadow(
    *,
    python_executable: Path,
    source_env_file: Path,
    product_manifest_sha256: str,
    workloads_path: Path,
    labels_path: Path,
    workload_id: str,
    tokenizer_json: Path,
    provider_capability: Path,
    provider_ledger: Path,
    trace_path: Path,
    temporary_root: Path,
    database_name: str,
    confirmation_seal: Path | None = None,
) -> dict[str, Any]:
    from milai_openworker_mcp import McpUnixClient
    from milai_openworker_mcp.host_adapter import OpenWorkerProviderAdapter

    product_origin = Path(inspect.getfile(OpenWorkerProviderAdapter)).resolve()
    prefix = Path(sys.prefix).resolve()
    if not product_origin.is_relative_to(prefix):
        raise FastPathShadowError(
            "OpenWorker adapter was not imported from the installed product"
        )

    workload = _load_workload(workloads_path, workload_id)
    labels = _load_labels(labels_path, workload_id)
    confirmation_commitments = None
    if workload_id == "FASTPATH_CONFIRMATION":
        if confirmation_seal is None:
            raise FastPathShadowError("confirmation run requires its frozen seal")
        confirmation_commitments = _verify_confirmation_commitments(
            labels,
            seal_path=confirmation_seal.resolve(),
            workloads_path=workloads_path,
        )
    turns = workload.get("turns")
    if not isinstance(turns, list) or len(turns) != len(labels):
        raise FastPathShadowError("turn and independent-label cardinality differs")
    if {str(item["turn_id"]) for item in turns} != set(labels):
        raise FastPathShadowError("turn and independent-label identities differ")

    history = _build_history(workload)
    fixture_state_keys = _fixture_state_keys(workload)
    runtime = ProductEvaluationRuntime(
        ProductRuntimeConfig(
            python_executable=python_executable.absolute(),
            source_env_file=source_env_file.resolve(),
            product_manifest_sha256=product_manifest_sha256,
        )
    )
    spec = TemporaryResourceSpec(
        lease_id="fast-path-shadow",
        database_name=database_name,
        blob_root=temporary_root.resolve() / "blobs",
        temporary_root=temporary_root.resolve(),
    )
    records: list[dict[str, Any]] = []
    cache_controls: list[dict[str, Any]] = []
    build_receipt: dict[str, Any] | None = None
    blocker = _ProviderBlocker()
    messages: list[dict[str, str]] = []
    host_task_state = _initial_host_task_state(workload)
    try:
        with runtime.provision(spec) as lease:
            build_receipt = asdict(lease.load_history(history))
            claim_receipts = {
                (
                    str(item["subject_id"]),
                    str(item["predicate"]),
                    str(item["claim_type"]),
                ): dict(item)
                for item in build_receipt["product_usage"]["claim_receipts"]
            }
            # Product writer receipts establish the Host's locator vocabulary. The
            # independent label file remains scorer-only and is never passed to the resolver.
            host_task_state = {
                **host_task_state,
                "known_state_keys": [
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "claim_type": claim_type,
                    }
                    for subject, predicate, claim_type in sorted(claim_receipts)
                ],
            }
            transition_scope = {"project_ids": [str(workload["project_id"])]}
            adapter = OpenWorkerProviderAdapter(
                provider_capability.resolve(),
                provider_ledger.resolve(),
                trace_path.resolve(),
                memory_mode="prefetch",
                prefetch_socket=lease.reader_socket,
                tokenizer_json=tokenizer_json.resolve(),
                task_session_id=str(workload["task_id"]),
            )
            adapter.gateway = blocker
            try:
                for turn_index, turn in enumerate(turns):
                    host_task_state = _advance_host_task_state(host_task_state, turn)
                    host_task_relation = _host_task_relation(
                        turn, first_turn=turn_index == 0
                    )
                    transition_name = turn.get("fixture_transition")
                    transition_result: dict[str, Any] | None = None
                    is_dev = workload.get("workload_id") == "FASTPATH_DEV"
                    if transition_name in {
                        "OPEN_CONFLICT_ON_RELEASE_DECISION",
                        "OPEN_CONFLICT_ON_DEPLOYMENT_DECISION",
                    }:
                        key, _ = _fixture_entry(workload, claim_type="PROJECT_DECISION")
                        current = claim_receipts[key]
                        transition_result = runtime.apply_claim_transition(
                            operation_id=(
                                "fp0-dev-t10-conflict"
                                if is_dev
                                else "fast-path-t10-conflict"
                            ),
                            operation="CONTRADICT",
                            claim_id=str(current["claim_id"]),
                            expected_version_id=str(current["claim_version_id"]),
                            subject_id=key[0],
                            observed_at="2026-08-02T00:10:00+00:00",
                            content=(
                                "Synthetic governed report proposes release decision GO."
                                if is_dev
                                else "Synthetic governed report contradicts the current decision."
                            ),
                            scope=transition_scope,
                        )
                    elif transition_name in {
                        "SUPERSEDE_RELEASE_TARGET_TO_RC8",
                        "SUPERSEDE_DEPLOYMENT_TARGET_TO_BUILD43",
                    }:
                        key, _ = _fixture_entry(workload, claim_type="PROJECT_STATE")
                        next_value = (
                            "rc-8"
                            if transition_name == "SUPERSEDE_RELEASE_TARGET_TO_RC8"
                            else "build-43"
                        )
                        current = claim_receipts[key]
                        transition_result = runtime.apply_claim_transition(
                            operation_id=(
                                "fp0-dev-t12-supersede"
                                if is_dev
                                else "fast-path-t12-supersede"
                            ),
                            operation="SUPERSEDE",
                            claim_id=str(current["claim_id"]),
                            expected_version_id=str(current["claim_version_id"]),
                            subject_id=key[0],
                            observed_at="2026-08-02T00:12:00+00:00",
                            content=(
                                "Synthetic governed release target is now rc-8."
                                if is_dev
                                else f"Synthetic governed target is now {next_value}."
                            ),
                            scope=transition_scope,
                            payload={"value": next_value},
                        )
                        claim_receipts[key] = {
                            **current,
                            "claim_version_id": transition_result["claim_version_id"],
                            "evidence_id": transition_result["evidence_id"],
                        }
                    elif transition_name in {
                        "REVOKE_RELEASE_TARGET_EVIDENCE",
                        "REVOKE_DEPLOYMENT_TARGET_EVIDENCE",
                    }:
                        key, _ = _fixture_entry(workload, claim_type="PROJECT_STATE")
                        current = claim_receipts[key]
                        transition_result = runtime.revoke_fixture_evidence(
                            operation_id=(
                                "fp0-dev-t13-revoke"
                                if is_dev
                                else "fast-path-t13-revoke"
                            ),
                            evidence_id=str(current["evidence_id"]),
                        )
                    before = len(_read_trace(trace_path))
                    _append_turn_messages(messages, turn)
                    provider_boundary_reached = False
                    try:
                        adapter.complete(
                            {
                                "user": str(workload["task_id"]),
                                "messages": list(messages),
                                "milai_task_state": host_task_state,
                                "milai_task_relation": host_task_relation,
                                "milai_memory_event": str(turn["host_event"]),
                                "milai_required_authority": str(
                                    turn.get("required_authority", "INFORMATIONAL")
                                ),
                            }
                        )
                    except ProviderBoundaryReached:
                        provider_boundary_reached = True
                    events = _read_trace(trace_path)[before:]
                    route_event = next(
                        (
                            event
                            for event in reversed(events)
                            if event.get("event")
                            in {"HOST_MEMORY_ROUTE_NONE", "HOST_MCP_PREPARE_CONTEXT"}
                        ),
                        None,
                    )
                    task_event = next(
                        (
                            event
                            for event in reversed(events)
                            if event.get("event") == "HOST_TASK_STATE_SHADOW"
                        ),
                        None,
                    )
                    need_event = next(
                        (
                            event
                            for event in reversed(events)
                            if event.get("event") == "HOST_MEMORY_NEED_RESOLVED"
                        ),
                        None,
                    )
                    label = labels[str(turn["turn_id"])]
                    host_state_observed = _host_state_observed(
                        host_task_state,
                        task_event if isinstance(task_event, Mapping) else None,
                    )
                    route_trace = (
                        route_event.get("recall_execution_trace", {})
                        if isinstance(route_event, Mapping)
                        else {}
                    )
                    state_key = label.get("state_key")
                    state_key_tuple = (
                        (
                            str(state_key.get("subject")),
                            str(state_key.get("predicate")),
                            str(state_key.get("claim_type")),
                        )
                        if isinstance(state_key, Mapping)
                        else None
                    )
                    records.append(
                        {
                            "turn_id": str(turn["turn_id"]),
                            "question_sha256": hashlib.sha256(
                                str(turn["user_text"]).encode()
                            ).hexdigest(),
                            "declared_host_event": str(turn["host_event"]),
                            "observed_host_event": (
                                task_event.get("host_event")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "host_event_adjustment": (
                                task_event.get("event_adjustment")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "binding_transition": (
                                task_event.get("binding_transition")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_relation": (
                                task_event.get("task_relation")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "expected_task_relation": host_task_relation,
                            "expected_binding_transition": _expected_transition(
                                turn, first_turn=turn_index == 0
                            ),
                            "relation_confidence_tier": (
                                task_event.get("confidence_tier")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "relation_reason_codes": (
                                task_event.get("reason_codes", [])
                                if isinstance(task_event, Mapping)
                                else []
                            ),
                            "cache_reuse_constraint": (
                                task_event.get("cache_reuse_constraint")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "registry_revision_before": (
                                task_event.get("registry_revision_before")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "registry_revision_after": (
                                task_event.get("registry_revision_after")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_generation": (
                                task_event.get("task_generation")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "binding_generation": (
                                task_event.get("binding_generation")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "relation_transition_trace_complete": (
                                task_event.get("relation_transition_trace_complete")
                                if isinstance(task_event, Mapping)
                                else False
                            ),
                            "resolver_ms": (
                                task_event.get("resolver_ms")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_transition_ms": (
                                task_event.get("task_transition_ms")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_state_rebind_ms": (
                                task_event.get("task_state_rebind_ms")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_resolver_llm_calls": (
                                task_event.get("task_resolver_llm_calls")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_resolver_embedding_calls": (
                                task_event.get("task_resolver_embedding_calls")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_resolver_retrieval_calls": (
                                task_event.get("task_resolver_retrieval_calls")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_resolver_training_calls": (
                                task_event.get("task_resolver_training_calls")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_resolver_hidden_provider_calls": (
                                task_event.get("task_resolver_hidden_provider_calls")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "task_id_sha256": (
                                task_event.get("task_id_sha256")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "expected_task_id_sha256": hashlib.sha256(
                                str(host_task_state["task_id"]).encode()
                            ).hexdigest(),
                            "host_task_state_observed": host_state_observed,
                            "active_goal_equals_current_question": (
                                task_event.get("active_goal_equals_current_question")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "expected_route_set": list(label["expected_route_set"]),
                            "fast_eligible": bool(label["fast_eligible"]),
                            "required_authority": str(label["required_authority"]),
                            "memory_dependency": str(label["memory_dependency"]),
                            "intent_class": str(label["intent_class"]),
                            "resolved_intent_class": (
                                need_event.get("intent_class")
                                if isinstance(need_event, Mapping)
                                else None
                            ),
                            "memory_need_correct": (
                                need_event.get("intent_class") == label["intent_class"]
                                if isinstance(need_event, Mapping)
                                else False
                            ),
                            "state_key_ref_present": (
                                need_event.get("state_key_ref_present")
                                if isinstance(need_event, Mapping)
                                else False
                            ),
                            "state_key_resolution_correct": (
                                (
                                    need_event.get("state_key_subject_sha256")
                                    == hashlib.sha256(
                                        str(state_key["subject"]).encode()
                                    ).hexdigest()
                                    and need_event.get("state_key_predicate_sha256")
                                    == hashlib.sha256(
                                        str(state_key["predicate"]).encode()
                                    ).hexdigest()
                                    and need_event.get("state_key_claim_type_sha256")
                                    == hashlib.sha256(
                                        str(state_key["claim_type"]).encode()
                                    ).hexdigest()
                                )
                                if isinstance(need_event, Mapping)
                                and isinstance(state_key, Mapping)
                                else (
                                    need_event.get("state_key_ref_present") is False
                                    if isinstance(need_event, Mapping)
                                    else False
                                )
                            ),
                            "need_resolver_model_calls": (
                                need_event.get("resolver_model_calls")
                                if isinstance(need_event, Mapping)
                                else None
                            ),
                            "need_resolver_embedding_calls": (
                                need_event.get("resolver_embedding_calls")
                                if isinstance(need_event, Mapping)
                                else None
                            ),
                            "need_resolver_retrieval_calls": (
                                need_event.get("resolver_retrieval_calls")
                                if isinstance(need_event, Mapping)
                                else None
                            ),
                            "state_key_present": isinstance(
                                label.get("state_key"), Mapping
                            ),
                            "canonical_state_key_exists_initial": (
                                state_key_tuple in fixture_state_keys
                                if state_key_tuple is not None
                                else None
                            ),
                            "canonical_state_key_exists_at_turn": (
                                state_key_tuple in fixture_state_keys
                                if state_key_tuple is not None
                                else None
                            ),
                            "requested_route": route_trace.get("requested_route"),
                            "need_signature_id": route_trace.get("need_signature_id"),
                            "validated_route": route_trace.get("validated_route"),
                            "attempted_routes": route_trace.get("attempted_routes", []),
                            "terminal_route": route_trace.get("terminal_route"),
                            "route_trace_complete": route_trace.get(
                                "route_trace_complete"
                            ),
                            "trace_gap_reason": route_trace.get("trace_gap_reason"),
                            "policy_override_reason": route_trace.get(
                                "policy_override_reason"
                            ),
                            "fallback_reason": route_trace.get("fallback_reason"),
                            "route_result": route_trace.get("result"),
                            "next_route_recommended": route_trace.get(
                                "next_route_recommended"
                            ),
                            "query_embedding_calls": route_trace.get(
                                "query_embedding_calls"
                            ),
                            "vector_calls": route_trace.get("vector_calls"),
                            "reranker_calls": route_trace.get("reranker_calls"),
                            "exact_calls": route_trace.get("exact_calls"),
                            "fts_calls": route_trace.get("fts_calls"),
                            "l0_calls": route_trace.get("l0_calls"),
                            "progressive_l1": route_trace.get("progressive_l1"),
                            "memory_status": (
                                route_event.get("memory_status")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "current_state_status": (
                                route_event.get("current_state_status")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "current_state_claim_count": (
                                route_event.get("current_state_claim_count")
                                if isinstance(route_event, Mapping)
                                else 0
                            ),
                            "current_state_open_issue_count": (
                                route_event.get("current_state_open_issue_count")
                                if isinstance(route_event, Mapping)
                                else 0
                            ),
                            "current_state_validation_handle_present": (
                                route_event.get(
                                    "current_state_validation_handle_present"
                                )
                                if isinstance(route_event, Mapping)
                                else False
                            ),
                            "prepare_status": (
                                route_event.get("prepare_status")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "cache_validation_outcome": (
                                route_event.get("cache_validation_outcome")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "memory_slot_coverage_present": (
                                route_event.get("memory_slot_coverage_present")
                                if isinstance(route_event, Mapping)
                                else False
                            ),
                            "memory_slot_coverage_counts": (
                                route_event.get("memory_slot_coverage_counts")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "memory_slot_policy_identity": (
                                route_event.get("memory_slot_policy_identity")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "memory_slot_evidence_depth": (
                                route_event.get("memory_slot_evidence_depth")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "dependency_frontier_position": (
                                route_event.get("dependency_frontier_position")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "memory_control_ms": (
                                route_event.get("memory_control_ms")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "compiled_memory_tokens": (
                                route_event.get("compiled_memory_tokens")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "compiled_memory_bytes": (
                                route_event.get("compiled_memory_bytes")
                                if isinstance(route_event, Mapping)
                                else None
                            ),
                            "task_key": (
                                task_event.get("task_key")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "retained_slot_present": (
                                task_event.get("retained_slot_present")
                                if isinstance(task_event, Mapping)
                                else None
                            ),
                            "provider_boundary_reached": provider_boundary_reached,
                            "fixture_transition_declared": transition_name is not None,
                            "fixture_transition_applied": transition_result is not None,
                            "fixture_transition_observation": (
                                {
                                    "operation": transition_result["operation"],
                                    "canonical_position": transition_result[
                                        "canonical_position"
                                    ],
                                    "open_issue_created": transition_result.get(
                                        "open_issue_id"
                                    )
                                    is not None,
                                    "logical_revocation_status": transition_result.get(
                                        "logical_revocation_status"
                                    ),
                                    "canonical_block_status": transition_result.get(
                                        "canonical_block_status"
                                    ),
                                }
                                if transition_result is not None
                                else None
                            ),
                            "explicit_directive": str(turn.get("directive"))
                            != "CONTINUE",
                            "directive_surface_applied": (
                                host_state_observed
                                and str(turn.get("directive")) != "CONTINUE"
                                and task_event.get("binding_transition") != "CONTINUE"
                                if isinstance(task_event, Mapping)
                                else False
                            ),
                        }
                    )
                informational_mcp = McpUnixClient(runtime.informational_reader_socket)
                try:
                    fp5_controls = _fp5_progressive_controls(
                        adapter,
                        informational_mcp,
                        workload,
                        transition_scope,
                    )
                finally:
                    informational_mcp.close()
                cache_controls = _cache_negative_controls(
                    adapter,
                    runtime,
                    claim_receipts,
                    workload,
                    transition_scope,
                )
            finally:
                adapter.close()
    finally:
        runtime.destroy()

    events = _read_trace(trace_path)
    provider_events = [event for event in events if event.get("provider_call") is True]
    return {
        "schema": "milai.fast-path-shadow.v2",
        "workload_id": workload_id,
        "data_boundary": "SYNTHETIC_ONLY",
        "product_origin": str(product_origin),
        "product_origin_sha256": _sha256(product_origin),
        "inputs": {
            "workloads_sha256": _sha256(workloads_path),
            "labels_sha256": _sha256(labels_path),
            "tokenizer_sha256": _sha256(tokenizer_json),
            "provider_capability_sha256": _sha256(provider_capability),
            "confirmation_commitments": confirmation_commitments,
        },
        "build_receipt": build_receipt,
        "records": records,
        "summary": _summarize(records),
        "cache_negative_controls": {
            "passed": sum(item["passed"] is True for item in cache_controls),
            "total": len(cache_controls),
            "records": cache_controls,
        },
        "fp5_progressive_controls": {
            "passed": sum(item["passed"] is True for item in fp5_controls),
            "total": len(fp5_controls),
            "records": fp5_controls,
        },
        "calls": {
            "answer_calls": 0,
            "judge_calls": 0,
            "hidden_provider_calls": len(provider_events),
            "provider_boundary_attempts_blocked": blocker.attempts,
        },
        "scope": {
            "fixture_transitions_applied": sum(
                item["fixture_transition_applied"] for item in records
            ),
            "explicit_goal_scope_profile_directives_declared": sum(
                item["explicit_directive"] for item in records
            ),
            "explicit_goal_scope_profile_directives_applied": sum(
                item["directive_surface_applied"] for item in records
            ),
            "host_task_state_observed_turns": sum(
                item["host_task_state_observed"] for item in records
            ),
            "state_addressability_rate": "MEASURED_WITH_GOVERNED_TRANSITIONS",
            "fast_path_execution_coverage": "MEASURED_ROUTE_LABEL_ONLY_NO_ANSWER_MODEL",
            "formal_acceptance_metrics_valid": (
                workload_id == "FASTPATH_CONFIRMATION"
                and confirmation_commitments is not None
            ),
            "reason": (
                "Untouched confirmation labels match every frozen commitment; acceptance "
                "is limited to route, task binding, governed transition, cache safety, and "
                "latency metrics without an answer model."
                if workload_id == "FASTPATH_CONFIRMATION"
                else "Continuous product fast-path DEV shadow with complete typed route trace "
                "and governed transitions; answer/canonical non-inferiority is not assessed "
                "because the Provider boundary is blocked."
            ),
        },
        "cleanup": {
            "temporary_root_absent": not temporary_root.exists(),
            "runtime_spec_released": runtime.spec is None,
        },
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _cache_negative_controls(
    adapter: object,
    runtime: ProductEvaluationRuntime,
    claim_receipts: dict[tuple[str, str, str], dict[str, Any]],
    workload: Mapping[str, Any],
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Exercise truth, coverage, and proof rivals through shipped MCP/Runtime."""
    from milai_client import MemoryNeedSignature, StateKeyRef

    mcp = getattr(adapter, "host_mcp", None)
    if mcp is None:
        raise FastPathShadowError(
            "cache negative controls require the product MCP session"
        )

    def need(key: tuple[str, str, str]) -> tuple[MemoryNeedSignature, StateKeyRef]:
        reference = StateKeyRef(
            scope=scope,
            subject=key[0],
            predicate=key[1],
            claim_type=key[2],
        )
        signature = MemoryNeedSignature(
            scope=scope,
            required_authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
            claim_ids=(),
            state_keys=(reference,),
            open_issue_ids=(),
            temporal_need="CURRENT",
            evidence_need="SUPPORT_POINTERS",
            intent_class="CURRENT_STATE",
        )
        return signature, reference

    def payload(
        key: tuple[str, str, str],
        *,
        session: str,
        route: str,
        token: str | None = None,
        policy_digest: str = "a" * 64,
    ) -> dict[str, Any]:
        signature, reference = need(key)
        value: dict[str, Any] = {
            "query": f"current {key[1]}",
            "active_goal": "Validate deterministic cache safety controls.",
            "session_id": session,
            "agent_id": "openworker-cache-control",
            "task_epoch": "cache-control-v1",
            "event": "KNOWN_OBJECT" if route == "L0" else "MODEL_RETRY",
            "requested_route": route,
            "need_signature_id": signature.need_signature_id,
            "memory_need_signature": signature.to_api(),
            "state_key_ref": reference.to_api(),
            "compiler_digest": "a" * 64,
            "router_digest": "a" * 64,
            "tokenizer_digest": "a" * 64,
            "policy_digest": policy_digest,
            "limit": 3,
            "constraints": [],
            "byte_budget": 16_384,
            "memory_token_budget": 512,
            "slot_ttl_seconds": 300,
            "budget": {"memory_deadline_ms": 5_000},
        }
        if token is not None:
            value["previous_validation_token"] = token
        return value

    def seed(key: tuple[str, str, str], session: str) -> str | None:
        result = mcp.prepare_memory_context(payload(key, session=session, route="L0"))
        token = result.get("validation_token")
        coverage = result.get("memory_slot_coverage")
        if result.get("status") != "READY":
            return None
        if not isinstance(token, str):
            raise FastPathShadowError(
                "cache negative-control READY seed omitted its validation token"
            )
        if not isinstance(coverage, Mapping):
            raise FastPathShadowError(
                "cache negative-control seed omitted slot coverage"
            )
        return token

    def required_seed(key: tuple[str, str, str], session: str) -> str:
        token = seed(key, session)
        if token is None:
            raise FastPathShadowError(
                "cache negative-control required seed did not produce a slot"
            )
        return token

    def first_live_control_seed(
        excluded_key: tuple[str, str, str], session: str
    ) -> tuple[tuple[str, str, str], str]:
        fixture = workload.get("fixture_state")
        if not isinstance(fixture, list):
            raise FastPathShadowError("workload fixture_state must be a list")
        attempted = 0
        for entry in fixture:
            state_key = entry.get("state_key") if isinstance(entry, Mapping) else None
            if not isinstance(state_key, Mapping):
                continue
            key = (
                str(state_key["subject"]),
                str(state_key["predicate"]),
                str(state_key["claim_type"]),
            )
            if key == excluded_key:
                continue
            attempted += 1
            token = seed(key, session)
            if token is not None:
                return key, token
        raise FastPathShadowError(
            "cache negative controls found no live non-mutated fixture key "
            f"after {attempted} deterministic probes"
        )

    def observation(
        control_id: str, expected_reason: str, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        trace = result.get("recall_execution_trace")
        if not isinstance(trace, Mapping):
            raise FastPathShadowError("cache negative control omitted a route trace")
        observed = {
            "control_id": control_id,
            "expected_reason": expected_reason,
            "observed_reason": result.get("reason"),
            "status": result.get("status"),
            "route_result": trace.get("result"),
            "terminal_route": trace.get("terminal_route"),
            "route_trace_complete": trace.get("route_trace_complete"),
            "validation_token_present": isinstance(result.get("validation_token"), str),
            "query_embedding_calls": trace.get("query_embedding_calls"),
            "vector_calls": trace.get("vector_calls"),
            "reranker_calls": trace.get("reranker_calls"),
            "passed": (
                result.get("reason") == expected_reason
                and trace.get("result") in {"MISS", "ERROR", "ABSTAINED"}
                and trace.get("terminal_route") == "CACHE"
                and trace.get("route_trace_complete") is True
                and result.get("validation_token") is None
            ),
        }
        return observed

    database_key, _ = _fixture_entry(workload, claim_type="PROJECT_CONFIG")

    coverage_token = required_seed(database_key, "cache-control-coverage")
    control_key, stale_token = first_live_control_seed(
        database_key, "cache-control-frontier"
    )
    coverage_miss = mcp.prepare_memory_context(
        payload(
            control_key,
            session="cache-control-coverage",
            route="CACHE",
            token=coverage_token,
        )
    )

    current_database = claim_receipts[database_key]
    is_dev = workload.get("workload_id") == "FASTPATH_DEV"
    transition = runtime.apply_claim_transition(
        operation_id=(
            "cache-frontier-control-database-update"
            if is_dev
            else "cache-frontier-control-config-update"
        ),
        operation="SUPERSEDE",
        claim_id=str(current_database["claim_id"]),
        expected_version_id=str(current_database["claim_version_id"]),
        subject_id=database_key[0],
        observed_at="2026-08-02T00:20:00+00:00",
        content=(
            "Synthetic governed database setting advanced for cache validation."
            if is_dev
            else "Synthetic governed configuration advanced for cache validation."
        ),
        scope=scope,
        payload={
            "value": "postgresql-18-control" if is_dev else "cache-control-updated"
        },
    )
    claim_receipts[database_key] = {
        **current_database,
        "claim_version_id": transition["claim_version_id"],
        "evidence_id": transition["evidence_id"],
    }
    stale_miss = mcp.prepare_memory_context(
        payload(
            control_key,
            session="cache-control-frontier",
            route="CACHE",
            token=stale_token,
        )
    )

    proof_token = required_seed(control_key, "cache-control-policy")
    proof_miss = mcp.prepare_memory_context(
        payload(
            control_key,
            session="cache-control-policy",
            route="CACHE",
            token=proof_token,
            policy_digest="b" * 64,
        )
    )

    return [
        observation("NEED_COVERAGE_MISS", "CACHE_STATE_KEY_UNCOVERED", coverage_miss),
        observation("DEPENDENCY_FRONTIER_STALE", "STALE_TASK_SLOT", stale_miss),
        observation(
            "BROKER_BOUND_POLICY_PROOF_INVALID",
            "BROKER_BOUND_VALIDATION_PROOF_INVALID",
            proof_miss,
        ),
    ]


def _fp5_progressive_controls(
    action_safe_adapter: object,
    informational_mcp: object,
    workload: Mapping[str, Any],
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Exercise content depth and canonical-gated L1 stops through shipped MCP."""
    from milai_client import MemoryNeedSignature, StateKeyRef

    action_safe_mcp = getattr(action_safe_adapter, "host_mcp", None)
    if action_safe_mcp is None:
        raise FastPathShadowError("FP5 controls require the product MCP session")

    config_key, config_value = _fixture_entry(workload, claim_type="PROJECT_CONFIG")
    database_key = StateKeyRef(
        scope=scope,
        subject=config_key[0],
        predicate=config_key[1],
        claim_type=config_key[2],
    )
    lexical_query = str(config_value)
    is_dev = workload.get("workload_id") == "FASTPATH_DEV"
    abstract_query = (
        "Read the current Orchid database setting."
        if is_dev
        else f"Read the current {config_key[1]} setting."
    )
    overview_query = (
        "Read the current Orchid database setting with provenance pointers."
        if is_dev
        else f"Read the current {config_key[1]} setting with provenance pointers."
    )
    recovery_query = (
        "Recover the raw evidence for the current Orchid database setting."
        if is_dev
        else f"Recover the raw evidence for the current {config_key[1]} setting."
    )
    history_query = (
        "Why is the Orchid database postgresql-17?"
        if is_dev
        else f"Why is {config_key[0]} {config_key[1]} {lexical_query}?"
    )

    def call(
        *,
        control_id: str,
        route: str,
        intent: str,
        evidence_need: str,
        state_key: StateKeyRef | None,
        query: str,
        mcp: object = informational_mcp,
    ) -> Mapping[str, Any]:
        signature = MemoryNeedSignature(
            scope=scope,
            required_authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
            claim_ids=(),
            state_keys=(state_key,) if state_key is not None else (),
            open_issue_ids=(),
            temporal_need="CURRENT" if intent == "CURRENT_STATE" else "HISTORICAL",
            evidence_need=evidence_need,  # type: ignore[arg-type]
            intent_class=intent,  # type: ignore[arg-type]
        )
        payload: dict[str, Any] = {
            "query": query,
            "active_goal": "Validate progressive content and L1 controls.",
            "session_id": f"fp5-control-{control_id.lower()}",
            "agent_id": "openworker-fp5-control",
            "task_epoch": "fp5-control-v1",
            "event": "KNOWN_OBJECT"
            if state_key is not None
            else "EXPLICIT_MEMORY_REQUEST",
            "requested_route": route,
            "need_signature_id": signature.need_signature_id,
            "memory_need_signature": signature.to_api(),
            "compiler_digest": "a" * 64,
            "router_digest": "a" * 64,
            "tokenizer_digest": "a" * 64,
            "policy_digest": "a" * 64,
            "limit": 3,
            "constraints": [],
            "byte_budget": 16_384,
            "memory_token_budget": 512,
            "slot_ttl_seconds": 300,
            "budget": {"memory_deadline_ms": 5_000},
        }
        if state_key is not None:
            payload["state_key_ref"] = state_key.to_api()
        prepare = getattr(mcp, "prepare_memory_context", None)
        if not callable(prepare):
            raise FastPathShadowError("FP5 control MCP has no prepare operation")
        return prepare(payload)

    abstract = call(
        control_id="ABSTRACT",
        route="L0",
        intent="CURRENT_STATE",
        evidence_need="NONE",
        state_key=database_key,
        query=abstract_query,
        mcp=action_safe_mcp,
    )
    overview = call(
        control_id="OVERVIEW",
        route="L0",
        intent="CURRENT_STATE",
        evidence_need="SUPPORT_POINTERS",
        state_key=database_key,
        query=overview_query,
        mcp=action_safe_mcp,
    )
    recovery = call(
        control_id="RAW_RECOVERY",
        route="L0",
        intent="CURRENT_STATE",
        evidence_need="RAW_EVIDENCE",
        state_key=database_key,
        query=recovery_query,
        mcp=action_safe_mcp,
    )
    fts_stop = call(
        control_id="FTS_STOP",
        route="L1",
        intent="CURRENT_STATE",
        evidence_need="SUPPORT_POINTERS",
        state_key=None,
        query=lexical_query,
    )
    vector_stop = call(
        control_id="VECTOR_STOP",
        route="L1",
        intent="HISTORY",
        evidence_need="SUPPORT_POINTERS",
        state_key=None,
        query=history_query,
    )
    action_safe_full = call(
        control_id="ACTION_SAFE_FULL",
        route="L1",
        intent="CURRENT_STATE",
        evidence_need="SUPPORT_POINTERS",
        state_key=None,
        query=lexical_query,
        mcp=action_safe_mcp,
    )

    def evidence_rows(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        capsule = result.get("context_capsule")
        sections = (
            capsule.get("protected_sections") if isinstance(capsule, Mapping) else None
        )
        evidence = (
            sections.get("RETRIEVED EVIDENCE")
            if isinstance(sections, Mapping)
            else None
        )
        return (
            [item for item in evidence if isinstance(item, Mapping)]
            if isinstance(evidence, list)
            else []
        )

    abstract_coverage = abstract.get("memory_slot_coverage")
    overview_coverage = overview.get("memory_slot_coverage")
    recovery_coverage = recovery.get("memory_slot_coverage")
    fts_trace = fts_stop.get("recall_execution_trace")
    fts_progressive = (
        fts_trace.get("progressive_l1") if isinstance(fts_trace, Mapping) else None
    )
    vector_trace = vector_stop.get("recall_execution_trace")
    vector_progressive = (
        vector_trace.get("progressive_l1")
        if isinstance(vector_trace, Mapping)
        else None
    )
    action_safe_trace = action_safe_full.get("recall_execution_trace")
    action_safe_progressive = (
        action_safe_trace.get("progressive_l1")
        if isinstance(action_safe_trace, Mapping)
        else None
    )
    records = [
        {
            "control_id": "ABSTRACT_NO_EVIDENCE_BODY",
            "status": abstract.get("status"),
            "prepared_detail_level": abstract.get("prepared_detail_level"),
            "coverage_evidence_depth": (
                abstract_coverage.get("evidence_depth")
                if isinstance(abstract_coverage, Mapping)
                else None
            ),
            "evidence_rows": len(evidence_rows(abstract)),
            "passed": (
                abstract.get("status") == "READY"
                and abstract.get("prepared_detail_level") == "ABSTRACT"
                and isinstance(abstract_coverage, Mapping)
                and abstract_coverage.get("evidence_depth") == "NONE"
                and not evidence_rows(abstract)
            ),
        },
        {
            "control_id": "OVERVIEW_POINTERS_ONLY",
            "status": overview.get("status"),
            "prepared_detail_level": overview.get("prepared_detail_level"),
            "coverage_evidence_depth": (
                overview_coverage.get("evidence_depth")
                if isinstance(overview_coverage, Mapping)
                else None
            ),
            "evidence_rows": len(evidence_rows(overview)),
            "raw_content_fields": sum(
                "content" in item for item in evidence_rows(overview)
            ),
            "passed": (
                overview.get("status") == "READY"
                and overview.get("prepared_detail_level") == "OVERVIEW"
                and isinstance(overview_coverage, Mapping)
                and overview_coverage.get("evidence_depth") == "SUPPORT_POINTERS"
                and bool(evidence_rows(overview))
                and all("content" not in item for item in evidence_rows(overview))
            ),
        },
        {
            "control_id": "RAW_EVIDENCE_EXPLICIT_RECOVERY",
            "status": recovery.get("status"),
            "reason": recovery.get("reason"),
            "requested_detail_level": recovery.get("requested_detail_level"),
            "prepared_detail_level": recovery.get("prepared_detail_level"),
            "coverage_evidence_depth": (
                recovery_coverage.get("evidence_depth")
                if isinstance(recovery_coverage, Mapping)
                else None
            ),
            "validation_token_present": isinstance(
                recovery.get("validation_token"), str
            ),
            "passed": (
                recovery.get("status") == "NEEDS_RECOVERY"
                and recovery.get("reason") == "RAW_EVIDENCE_RECOVERY_REQUIRED"
                and recovery.get("requested_detail_level") == "EVIDENCE_DETAIL"
                and recovery.get("prepared_detail_level") == "OVERVIEW"
                and isinstance(recovery_coverage, Mapping)
                and recovery_coverage.get("evidence_depth") == "SUPPORT_POINTERS"
                and recovery.get("validation_token") is None
            ),
        },
        {
            "control_id": "CANONICAL_GATED_FTS_STOP",
            "status": fts_stop.get("status"),
            "terminal_route": (
                fts_trace.get("terminal_route")
                if isinstance(fts_trace, Mapping)
                else None
            ),
            "stop_stage": (
                fts_progressive.get("stop_stage")
                if isinstance(fts_progressive, Mapping)
                else None
            ),
            "query_embedding_calls": (
                fts_trace.get("query_embedding_calls")
                if isinstance(fts_trace, Mapping)
                else None
            ),
            "vector_calls": (
                fts_trace.get("vector_calls")
                if isinstance(fts_trace, Mapping)
                else None
            ),
            "reranker_calls": (
                fts_trace.get("reranker_calls")
                if isinstance(fts_trace, Mapping)
                else None
            ),
            "passed": (
                fts_stop.get("status") == "READY"
                and isinstance(fts_trace, Mapping)
                and fts_trace.get("terminal_route") == "L1"
                and isinstance(fts_progressive, Mapping)
                and fts_progressive.get("stop_stage") == "FTS"
                and fts_trace.get("query_embedding_calls") == 0
                and fts_trace.get("vector_calls") == 0
                and fts_trace.get("reranker_calls") == 0
            ),
        },
        {
            "control_id": "CANONICAL_GATED_VECTOR_STOP",
            "status": vector_stop.get("status"),
            "terminal_route": (
                vector_trace.get("terminal_route")
                if isinstance(vector_trace, Mapping)
                else None
            ),
            "stop_stage": (
                vector_progressive.get("stop_stage")
                if isinstance(vector_progressive, Mapping)
                else None
            ),
            "query_embedding_calls": (
                vector_trace.get("query_embedding_calls")
                if isinstance(vector_trace, Mapping)
                else None
            ),
            "vector_calls": (
                vector_trace.get("vector_calls")
                if isinstance(vector_trace, Mapping)
                else None
            ),
            "reranker_calls": (
                vector_trace.get("reranker_calls")
                if isinstance(vector_trace, Mapping)
                else None
            ),
            "passed": (
                vector_stop.get("status") == "READY"
                and isinstance(vector_trace, Mapping)
                and vector_trace.get("terminal_route") == "L1"
                and isinstance(vector_progressive, Mapping)
                and vector_progressive.get("stop_stage") == "VECTOR"
                and vector_trace.get("query_embedding_calls") == 1
                and vector_trace.get("vector_calls") == 1
                and vector_trace.get("reranker_calls") == 0
            ),
        },
        {
            "control_id": "ACTION_SAFE_REQUIRES_FULL_PIPELINE",
            "status": action_safe_full.get("status"),
            "stop_stage": (
                action_safe_progressive.get("stop_stage")
                if isinstance(action_safe_progressive, Mapping)
                else None
            ),
            "sufficiency_checks": (
                action_safe_progressive.get("sufficiency_checks")
                if isinstance(action_safe_progressive, Mapping)
                else None
            ),
            "query_embedding_calls": (
                action_safe_trace.get("query_embedding_calls")
                if isinstance(action_safe_trace, Mapping)
                else None
            ),
            "vector_calls": (
                action_safe_trace.get("vector_calls")
                if isinstance(action_safe_trace, Mapping)
                else None
            ),
            "reranker_calls": (
                action_safe_trace.get("reranker_calls")
                if isinstance(action_safe_trace, Mapping)
                else None
            ),
            "passed": (
                action_safe_full.get("status") == "READY"
                and isinstance(action_safe_trace, Mapping)
                and isinstance(action_safe_progressive, Mapping)
                and action_safe_progressive.get("stop_stage") == "RERANKER"
                and len(action_safe_progressive.get("sufficiency_checks", [])) == 2
                and all(
                    isinstance(check, Mapping)
                    and check.get("reason") == "ACTION_SAFE_REQUIRES_FULL_PIPELINE"
                    for check in action_safe_progressive.get("sufficiency_checks", [])
                )
                and action_safe_trace.get("query_embedding_calls") == 1
                and action_safe_trace.get("vector_calls") == 1
                and action_safe_trace.get("reranker_calls") == 1
            ),
        },
    ]
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a payload-free OpenWorker-to-MCP fast-path shadow baseline"
    )
    parser.add_argument("--python-executable", type=Path, required=True)
    parser.add_argument("--source-env-file", type=Path, required=True)
    parser.add_argument("--product-manifest-sha256", required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--workload-id", required=True)
    parser.add_argument("--tokenizer-json", type=Path, required=True)
    parser.add_argument("--provider-capability", type=Path, required=True)
    parser.add_argument("--provider-ledger", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--temporary-root", type=Path, required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--confirmation-seal", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_shadow(
        python_executable=args.python_executable,
        source_env_file=args.source_env_file,
        product_manifest_sha256=args.product_manifest_sha256,
        workloads_path=args.workloads,
        labels_path=args.labels,
        workload_id=args.workload_id,
        tokenizer_json=args.tokenizer_json,
        provider_capability=args.provider_capability,
        provider_ledger=args.provider_ledger,
        trace_path=args.trace,
        temporary_root=args.temporary_root,
        database_name=args.database_name,
        confirmation_seal=args.confirmation_seal,
    )
    _write_json(args.output, result)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
