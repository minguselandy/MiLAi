"""Pure post-seal DG-24 first-loss scorer.

This module intentionally imports no Runtime package and exposes no retrieval
entrypoint.  It joins only already-sealed JSON artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

SCORER_IDENTITY = "milai-dg24-post-seal-first-loss-scorer-v0.1"
_LONGMEM_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)

LOSS_REASONS = frozenset(
    {
        "CHANNEL_NOT_AVAILABLE",
        "CHANNEL_NOT_ENABLED",
        "CHANNEL_ELIGIBLE_NOT_INVOKED",
        "QUERY_EXPRESSION_MISMATCH",
        "INDEX_REPRESENTATION_MISSING",
        "TEMPORAL_SCOPE_MISROUTED",
        "ENTITY_ALIAS_MISMATCH",
        "NO_CHANNEL_RETRIEVED_GOLD",
        "LEXICAL_ANCHOR_HARD_DROP",
        "ENTITY_ANCHOR_HARD_DROP",
        "SOURCE_ROLE_FILTER_DROP",
        "TIME_FILTER_DROP",
        "SCOPE_FILTER_DROP",
        "REGEX_TYPE_MISCLASSIFICATION",
        "BENCHMARK_RULE_ASSOCIATION",
        "CHANNEL_CUTOFF_DROP",
        "FIXED_PRIORITY_SUPPRESSION",
        "GLOBAL_CUTOFF_DROP",
        "SESSION_AGGREGATION_SUPPRESSION",
        "REDUNDANCY_DISPLACEMENT",
        "DEDUP_WRONG_REPRESENTATIVE",
        "ACCESS_DENIED_EXPECTED",
        "REVOCATION_FILTERED_EXPECTED",
        "POLICY_SCOPE_MISMATCH",
        "HYDRATION_NOT_FOUND",
        "HYDRATION_VERSION_MISMATCH",
        "UNREADABLE_EVIDENCE",
        "SPAN_NOT_GROUNDED",
        "SUBJECT_MISMATCH",
        "PREDICATE_MISMATCH",
        "VALUE_TYPE_MISMATCH",
        "SOURCE_ROLE_MISMATCH",
        "EVENT_TIME_MISMATCH",
        "UNIT_MISMATCH",
        "DUPLICATE_BINDING",
        "CONFLICT_UNRESOLVED",
        "INTERPRETATION_NOT_PRODUCED",
        "PROOF_ACTION_NOT_AVAILABLE",
        "PROOF_ACTION_NOT_SELECTED",
        "BOUNDED_SCAN_INCOMPLETE",
        "MAX_ITEMS_HIT",
        "SOURCE_PARTITION_NOT_CLOSED",
        "PROJECTION_BACKFILL_GAP",
        "AMBIGUOUS_EVENT_TIME",
        "EVENT_IDENTITY_UNRESOLVED",
        "DEDUP_INCOMPLETE",
        "RAW_FALLBACK_INCOMPLETE",
        "ACCESS_SNAPSHOT_INVALID",
        "PROOF_VALIDATION_FAILED",
    }
)


def score_sealed_artifacts(
    *,
    product: Mapping[str, Any],
    probes: Mapping[str, Any],
    gold_registry: Mapping[str, Any],
    proof_registry: Mapping[str, Any],
    product_seal_digest: str,
    probe_seal_digest: str,
    gold_registry_digest: str,
    proof_registry_digest: str,
    rule_sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    product_by_case = {
        str(item["case_id"]): item["trace"] for item in product["records"]
    }
    probes_by_key = {
        (
            str(item["case_id"]),
            str(item["trace"]["requirement_id"]),
            str(item["trace"]["channel"]),
        ): item["trace"]
        for item in probes["records"]
    }
    attributions = []
    for query in sorted(
        gold_registry["queries"], key=lambda item: str(item["query_id"])
    ):
        case_id = str(query["query_id"])
        trace = product_by_case[case_id]
        for requirement in sorted(
            query["requirements"], key=lambda item: str(item["requirement_id"])
        ):
            requirement_id = str(requirement["requirement_id"])
            for role in sorted(
                requirement["evidence_roles"], key=lambda item: str(item["role"])
            ):
                for group in sorted(
                    role["equivalence_groups"],
                    key=lambda item: str(item["equivalence_group_id"]),
                ):
                    attributions.append(
                        _attribute_group(
                            case_id=case_id,
                            requirement_id=requirement_id,
                            role=str(role["role"]),
                            group=group,
                            product_trace=trace,
                            probes_by_key=probes_by_key,
                        )
                    )
    proof_traces = _score_proofs(
        proof_registry=proof_registry,
        product_by_case=product_by_case,
        probes_by_key=probes_by_key,
        attributions=attributions,
    )
    retention = _stage_retention(attributions, product_by_case)
    channel = _channel_availability(attributions)
    distribution = dict(
        sorted(
            Counter(
                item["first_irrecoverable_loss_reason"] or "TERMINAL_SURVIVAL"
                for item in attributions
            ).items()
        )
    )
    authorized = [item for item in attributions if item["authorized_absence"]]
    routing = _successor_routing(distribution, proof_traces)
    rule_report = _rule_report(product_by_case, rule_sources)
    evidence_role = _aggregate(
        attributions, ["query_id", "requirement_id", "evidence_role"]
    )
    requirements = _aggregate(attributions, ["query_id", "requirement_id"])
    queries = _aggregate(attributions, ["query_id"])
    hard_checks = {
        "opened_dev_product_traces_10_of_10": len(product_by_case) == 10,
        "acceptable_equivalence_groups_dispositioned_100": all(
            item["first_irrecoverable_loss_reason"] is not None
            or item["product_terminal_survival"]
            or item["authorized_absence"]
            for item in attributions
        ),
        "label_resolution_complete_100": all(
            item["label_resolution"] != "UNRESOLVED" for item in attributions
        ),
        "proof_obligations_dispositioned_100": all(
            item["disposition"] != "UNRESOLVED" for item in proof_traces
        ),
        "free_text_primary_reasons_zero": all(
            item["first_irrecoverable_loss_reason"] in LOSS_REASONS
            for item in attributions
            if item["first_irrecoverable_loss_reason"] is not None
        ),
        "authorized_absence_separate": all(
            item["first_irrecoverable_loss_reason"]
            in {"ACCESS_DENIED_EXPECTED", "REVOCATION_FILTERED_EXPECTED"}
            for item in authorized
        ),
        "observed_occurrence_lifecycle_100": all(
            len(trace["occurrences"]) == len(trace["candidate_lifecycles"])
            for trace in product_by_case.values()
        ),
        "dedup_lineage_recoverable_100": all(
            decision["preserved_channel_lineage"]
            for trace in product_by_case.values()
            for decision in trace["dedup_decisions"]
        ),
        "leave_one_rule_out_executions_zero": rule_report[
            "leave_one_rule_out_executions"
        ]
        == 0,
    }
    scored = {
        "schema_version": "scored-first-loss-report-v0.1",
        "product_seal_digest": product_seal_digest,
        "probe_seal_digest": probe_seal_digest,
        "gold_registry_digest": gold_registry_digest,
        "proof_registry_digest": proof_registry_digest,
        "scorer_identity": SCORER_IDENTITY,
        "per_equivalence_group": attributions,
        "per_evidence_role": evidence_role,
        "per_requirement": requirements,
        "per_query": queries,
        "proof_obligations": proof_traces,
        "retention_curves": retention,
        "first_loss_distribution": distribution,
        "channel_availability": channel,
        "authorized_absence": {
            "count": len(authorized),
            "records": authorized,
        },
        "successor_routing": routing,
        "hard_gate": {"passed": all(hard_checks.values()), "checks": hard_checks},
    }
    return {
        "scored_report": scored,
        "requirement_loss_attributions": attributions,
        "proof_obligation_traces": proof_traces,
        "stage_retention_report": {
            "schema_version": "stage-retention-report-v0.1",
            **retention,
        },
        "first_loss_distribution": {
            "schema_version": "first-loss-distribution-v0.1",
            "counts": distribution,
        },
        "rule_feature_attribution": rule_report,
        "channel_availability": {
            "schema_version": "channel-availability-report-v0.1",
            **channel,
        },
        "authorized_absence": {
            "schema_version": "authorized-absence-report-v0.1",
            "count": len(authorized),
            "records": authorized,
        },
        "successor_routing": {
            "schema_version": "successor-routing-report-v0.1",
            **routing,
        },
    }


def _attribute_group(
    *,
    case_id: str,
    requirement_id: str,
    role: str,
    group: Mapping[str, Any],
    product_trace: Mapping[str, Any],
    probes_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    source_ref = str(group["source_turn_ref"])
    occurrences = [
        item
        for item in product_trace["occurrences"]
        if item.get("requirement_id") == requirement_id
        and _occurrence_source_ref(item) == source_ref
    ]
    lifecycle_by_occurrence = {
        item["occurrence_id"]: item for item in product_trace["candidate_lifecycles"]
    }
    matching_lifecycles = [
        lifecycle_by_occurrence[item["occurrence_id"]]
        for item in occurrences
        if item["occurrence_id"] in lifecycle_by_occurrence
    ]
    terminal = [item for item in matching_lifecycles if _terminal_survival(item)]
    availability: dict[str, Any] = {}
    for channel in sorted(
        {key[2] for key in probes_by_key if key[:2] == (case_id, requirement_id)}
    ):
        probe = probes_by_key[(case_id, requirement_id, channel)]
        match = next(
            (
                item
                for item in probe["returned_occurrences"]
                if _occurrence_source_ref(item) == source_ref
            ),
            None,
        )
        rank = int(match["raw_rank"]) if match is not None else None
        occurrence_id = str(match["occurrence_id"]) if match is not None else None
        offline_views = {
            int(view["cutoff"]): view for view in probe.get("offline_cut_views", [])
        }
        cutoff_statuses = {
            str(cutoff): str(
                offline_views.get(cutoff, {}).get("status", "UNAVAILABLE_NOT_RECORDED")
            )
            for cutoff in (8, 16, 32, 64)
        }
        availability[channel] = {
            "disposition": probe["disposition"],
            "reason_code": probe["reason_code"],
            "rank": rank,
            "available_at": [
                cutoff
                for cutoff in (8, 16, 32, 64)
                if occurrence_id is not None
                and cutoff_statuses[str(cutoff)] == "AVAILABLE"
                and occurrence_id
                in {
                    str(value)
                    for value in offline_views.get(cutoff, {}).get(
                        "occurrence_ids", []
                    )
                }
            ],
            "cutoff_statuses": cutoff_statuses,
        }
    first_loss: tuple[str, str] | None = None
    first_irrecoverable: tuple[str, str] | None = None
    transient: list[str] = []
    rediscovery: list[str] = []
    if not terminal and matching_lifecycles:
        candidate_losses = []
        for lifecycle in matching_lifecycles:
            loss, irreversible, local_transient, local_rediscovery = _lifecycle_loss(
                lifecycle
            )
            if loss is not None:
                candidate_losses.append((loss, irreversible))
            transient.extend(local_transient)
            rediscovery.extend(local_rediscovery)
        if candidate_losses:
            first_loss = min((item[0] for item in candidate_losses), key=_stage_order)
            irreversible_values = [
                item[1] for item in candidate_losses if item[1] is not None
            ]
            if irreversible_values:
                first_irrecoverable = max(irreversible_values, key=_stage_order)
    if not terminal and first_irrecoverable is None:
        available = [
            (channel, values)
            for channel, values in availability.items()
            if values["rank"] is not None
        ]
        if available:
            invoked = {
                item["channel"]: item for item in product_trace["channel_decisions"]
            }
            eligible_not_invoked = next(
                (
                    channel
                    for channel, _values in available
                    if invoked.get(channel, {}).get("capability_status") == "ENABLED"
                    and invoked.get(channel, {}).get("invocation_disposition")
                    != "INVOKED"
                ),
                None,
            )
            if eligible_not_invoked is not None:
                first_loss = first_irrecoverable = (
                    "S11",
                    "CHANNEL_ELIGIBLE_NOT_INVOKED",
                )
            else:
                first_loss = first_irrecoverable = ("S15", "CHANNEL_CUTOFF_DROP")
        else:
            unavailable_only = all(
                values["disposition"]
                in {"UNAVAILABLE", "NOT_APPLICABLE", "NOT_INVOKED"}
                for values in availability.values()
            )
            first_loss = first_irrecoverable = (
                "S10" if unavailable_only else "S12",
                "CHANNEL_NOT_AVAILABLE"
                if unavailable_only
                else "NO_CHANNEL_RETRIEVED_GOLD",
            )
    authorized = bool(
        first_irrecoverable
        and first_irrecoverable[1]
        in {"ACCESS_DENIED_EXPECTED", "REVOCATION_FILTERED_EXPECTED"}
    )
    return {
        "schema_version": "requirement-loss-attribution-v0.1",
        "query_id": case_id,
        "requirement_id": requirement_id,
        "evidence_role": role,
        "equivalence_group_id": str(group["equivalence_group_id"]),
        "discovery_availability": availability,
        "product_discovery": bool(occurrences),
        "product_terminal_survival": bool(terminal),
        "first_loss_stage": first_loss[0] if first_loss else None,
        "first_loss_reason": first_loss[1] if first_loss else None,
        "first_irrecoverable_loss_stage": (
            first_irrecoverable[0] if first_irrecoverable else None
        ),
        "first_irrecoverable_loss_reason": (
            first_irrecoverable[1] if first_irrecoverable else None
        ),
        "transient_drop_stages": sorted(set(transient), key=_stage_number),
        "rediscovery_stages": sorted(set(rediscovery), key=_stage_number),
        "last_surviving_candidate_identities": sorted(
            {item["candidate_identity"] for item in matching_lifecycles}
        ),
        "authorized_absence": authorized,
        "label_resolution": "EXACT_SPAN",
        "acceptable_source_turn_ref": source_ref,
    }


def _lifecycle_loss(
    lifecycle: Mapping[str, Any],
) -> tuple[
    tuple[str, str] | None,
    tuple[str, str] | None,
    list[str],
    list[str],
]:
    steps = lifecycle["lifecycle"]
    losses = [
        item
        for item in steps
        if item["disposition"] in {"DROPPED", "REJECTED"}
        and item["reason_code"] in LOSS_REASONS
    ]
    first = losses[0] if losses else None
    transient = []
    rediscovery = [
        item["stage_id"] for item in steps if item["disposition"] == "REDISCOVERED"
    ]
    irreversible = first
    if first is not None:
        later = [
            item
            for item in steps
            if item["disposition"] == "REDISCOVERED"
            and int(item["sequence_index"]) > int(first["sequence_index"])
        ]
        if later:
            transient.append(first["stage_id"])
            subsequent = [
                item
                for item in losses
                if int(item["sequence_index"]) > int(later[-1]["sequence_index"])
            ]
            irreversible = subsequent[0] if subsequent else None
    return (
        (str(first["stage_id"]), str(first["reason_code"])) if first else None,
        (
            (str(irreversible["stage_id"]), str(irreversible["reason_code"]))
            if irreversible
            else None
        ),
        transient,
        rediscovery,
    )


def _score_proofs(
    *,
    proof_registry: Mapping[str, Any],
    product_by_case: Mapping[str, Mapping[str, Any]],
    probes_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
    attributions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for query in sorted(
        proof_registry["queries"], key=lambda item: str(item["query_id"])
    ):
        case_id = str(query["query_id"])
        product = product_by_case[case_id]
        product_proofs = {
            (str(item["requirement_id"]), str(item["kind"])): item
            for item in product["proof_obligations"]
        }
        for requirement in sorted(
            query["requirements"], key=lambda item: str(item["requirement_id"])
        ):
            requirement_id = str(requirement["requirement_id"])
            requirement_survival = any(
                item["query_id"] == case_id
                and item["requirement_id"] == requirement_id
                and item["product_terminal_survival"]
                for item in attributions
            )
            for obligation in sorted(
                requirement["obligations"],
                key=lambda item: str(item["obligation_id"]),
            ):
                kind = str(obligation["kind"])
                observed = product_proofs.get((requirement_id, kind))
                artifact = observed.get("proof_artifact") if observed else None
                disposition, reason = _proof_disposition(
                    kind,
                    observed=observed,
                    artifact=artifact if isinstance(artifact, Mapping) else None,
                    requirement_survival=requirement_survival,
                    probe_rows=[
                        value
                        for key, value in probes_by_key.items()
                        if key[:2] == (case_id, requirement_id)
                    ],
                )
                result.append(
                    {
                        "schema_version": "proof-obligation-trace-v0.1",
                        "query_id": case_id,
                        "requirement_id": requirement_id,
                        "obligation_id": str(obligation["obligation_id"]),
                        "obligation_kind": kind,
                        "applicable_actions": [kind],
                        "invoked_actions": [kind] if observed is not None else [],
                        "produced_proof_artifact_ids": (
                            [str(observed["proof_artifact_digest"])]
                            if observed and observed.get("proof_artifact_digest")
                            else []
                        ),
                        "validator_identity": SCORER_IDENTITY,
                        "disposition": disposition,
                        "first_loss_reason": reason,
                    }
                )
    return result


def _proof_disposition(
    kind: str,
    *,
    observed: Mapping[str, Any] | None,
    artifact: Mapping[str, Any] | None,
    requirement_survival: bool,
    probe_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None]:
    if kind == "ACCESS_SNAPSHOT":
        valid = bool(probe_rows) and all(
            not any(item["mutations"].values()) for item in probe_rows
        )
        return (
            ("SATISFIED", None)
            if valid
            else ("VALIDATION_FAILED", "ACCESS_SNAPSHOT_INVALID")
        )
    if kind == "EVENT_TIME_RESOLUTION":
        return (
            ("SATISFIED", None)
            if requirement_survival
            else ("VALIDATION_FAILED", "AMBIGUOUS_EVENT_TIME")
        )
    if observed is None:
        return "ACTION_NOT_SELECTED", "PROOF_ACTION_NOT_SELECTED"
    if artifact is None:
        return "ACTION_NOT_SELECTED", "PROOF_ACTION_NOT_SELECTED"
    if artifact.get("status") != "COMPLETE":
        return "VALIDATION_FAILED", "BOUNDED_SCAN_INCOMPLETE"
    if (
        kind == "SOURCE_PARTITION_CLOSURE"
        and artifact.get("source_partition_closed") is not True
    ):
        return "VALIDATION_FAILED", "SOURCE_PARTITION_NOT_CLOSED"
    if (
        kind == "PROJECTION_CLOSURE"
        and artifact.get("projection_watermark_covered") is not True
    ):
        return "VALIDATION_FAILED", "PROJECTION_BACKFILL_GAP"
    if (
        kind == "DEDUP_COMPLETENESS"
        and artifact.get("source_partition_closed") is not True
    ):
        return "VALIDATION_FAILED", "DEDUP_INCOMPLETE"
    if kind == "RAW_FALLBACK_CLOSURE" and artifact.get("dead_letter_gap") is True:
        return "VALIDATION_FAILED", "RAW_FALLBACK_INCOMPLETE"
    return "SATISFIED", None


def _stage_retention(
    attributions: Sequence[Mapping[str, Any]],
    product_by_case: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    stage_ids = [
        "S12",
        "S13",
        "S14",
        "S15",
        "S20",
        "S21",
        "S22",
        "S23",
        "S30",
        "S31",
        "S32",
        "S40",
        "S41",
        "S42",
        "S43",
        "S44",
        "S45",
    ]
    denominator = len(attributions)
    curves = {}
    for stage in stage_ids:
        alive = 0
        for item in attributions:
            loss = item["first_irrecoverable_loss_stage"]
            if item["product_terminal_survival"] or (
                loss is not None and _stage_number(str(loss)) > _stage_number(stage)
            ):
                alive += 1
        curves[stage] = {
            "alive_equivalence_groups": alive,
            "denominator": denominator,
            "retention": alive / denominator if denominator else 1.0,
        }
    occurrence_count = sum(
        len(item["occurrences"]) for item in product_by_case.values()
    )
    lifecycle_count = sum(
        len(item["candidate_lifecycles"]) for item in product_by_case.values()
    )
    return {
        "equivalence_group_denominator": denominator,
        "curves": curves,
        "observed_occurrence_count": occurrence_count,
        "lifecycle_count": lifecycle_count,
        "lifecycle_coverage": lifecycle_count / occurrence_count
        if occurrence_count
        else 1.0,
    }


def _channel_availability(attributions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    channels = sorted(
        {channel for item in attributions for channel in item["discovery_availability"]}
    )
    denominator = len(attributions)
    recall: dict[str, dict[str, dict[str, int | float | str | None]]] = {}
    for channel in channels:
        recall[channel] = {}
        for cutoff in (8, 16, 32, 64):
            eligible = [
                item
                for item in attributions
                if item["discovery_availability"]
                .get(channel, {})
                .get("cutoff_statuses", {})
                .get(str(cutoff))
                == "AVAILABLE"
            ]
            found = sum(
                1
                for item in eligible
                if cutoff
                in item["discovery_availability"].get(channel, {}).get(
                    "available_at", []
                )
            )
            recall[channel][str(cutoff)] = {
                "status": "AVAILABLE" if eligible else "UNAVAILABLE",
                "found": found,
                "denominator": len(eligible),
                "unavailable_count": denominator - len(eligible),
                "recall": found / len(eligible) if eligible else None,
            }
    union = {}
    for cutoff in (8, 16, 32, 64):
        eligible = [
            item
            for item in attributions
            if any(
                values.get("cutoff_statuses", {}).get(str(cutoff)) == "AVAILABLE"
                for values in item["discovery_availability"].values()
            )
        ]
        found = sum(
            1
            for item in eligible
            if any(
                cutoff in values.get("available_at", [])
                for values in item["discovery_availability"].values()
            )
        )
        union[str(cutoff)] = {
            "status": "AVAILABLE" if eligible else "UNAVAILABLE",
            "found": found,
            "denominator": len(eligible),
            "unavailable_count": denominator - len(eligible),
            "recall": found / len(eligible) if eligible else None,
        }
    return {
        "equivalence_group_denominator": denominator,
        "per_channel_recall": recall,
        "union_oracle_recall": union,
        "claim_boundary": "OFFICIAL_PROBE_AVAILABILITY_NOT_PRODUCT_RECALL_IMPROVEMENT",
    }


def _successor_routing(
    distribution: Mapping[str, int], proof_traces: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    proof_failures = Counter(
        item["first_loss_reason"]
        for item in proof_traces
        if item["disposition"] != "SATISFIED"
    )
    routes = []
    if distribution.get("CHANNEL_ELIGIBLE_NOT_INVOKED", 0):
        routes.append("CHANNEL_ROUTER_OPPORTUNITY_AUDIT")
    if distribution.get("CHANNEL_CUTOFF_DROP", 0) or distribution.get(
        "GLOBAL_CUTOFF_DROP", 0
    ):
        routes.append("RANKING_AND_CUTOFF_TREATMENT_PREREGISTRATION")
    if any(
        distribution.get(reason, 0)
        for reason in (
            "SUBJECT_MISMATCH",
            "PREDICATE_MISMATCH",
            "EVENT_TIME_MISMATCH",
            "INTERPRETATION_NOT_PRODUCED",
        )
    ):
        routes.append("SEMANTIC_INTERPRETATION_BINDING_AUDIT")
    if proof_failures:
        routes.append("PROOF_COMPLETENESS_TREATMENT_PREREGISTRATION")
    if not routes:
        routes.append("NO_RETRIEVAL_TREATMENT_INDICATED_BY_DG24")
    return {
        "routes": routes,
        "proof_failure_counts": dict(sorted(proof_failures.items())),
        "causal_claim": "NOT_ESTIMATED",
        "treatment_executed": False,
    }


def _rule_report(
    product_by_case: Mapping[str, Mapping[str, Any]],
    rule_sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    impacted = defaultdict(list)
    reason_to_rule = {
        "LEXICAL_ANCHOR_HARD_DROP": "LEXICAL_HARD_FILTERS",
        "ENTITY_ANCHOR_HARD_DROP": "LEXICAL_HARD_FILTERS",
        "FIXED_PRIORITY_SUPPRESSION": "FIXED_PRIORITY_FUSION",
        "PREDICATE_MISMATCH": "TYPE_DIRECTED_BINDING_RULES",
        "EVENT_TIME_MISMATCH": "TYPE_DIRECTED_BINDING_RULES",
    }
    for trace in product_by_case.values():
        for lifecycle in trace["candidate_lifecycles"]:
            for step in lifecycle["lifecycle"]:
                rule = reason_to_rule.get(step["reason_code"])
                if rule:
                    impacted[rule].append(lifecycle["occurrence_id"])
    inventory = []
    for rule_id, source in sorted(rule_sources.items()):
        inventory.append(
            {
                "rule_id": rule_id,
                **dict(source),
                "affected_occurrence_ids": sorted(set(impacted.get(rule_id, []))),
                "association_only": True,
            }
        )
    return {
        "schema_version": "rule-feature-attribution-report-v0.1",
        "inventory": inventory,
        "known_rule_inventory_complete": all(
            item.get("source_symbol") and item.get("source_sha256")
            for item in inventory
        ),
        "leave_one_rule_out_executions": 0,
        "correct_answer_dependency": "NOT_MEASURED_DG24",
        "causal_effect": "NOT_ESTIMATED",
    }


def _aggregate(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(str(row[key]) for key in keys)].append(row)
    result = []
    for identity, values in sorted(groups.items()):
        item: dict[str, Any] = {
            key: value for key, value in zip(keys, identity, strict=True)
        }
        item.update(
            {
                "equivalence_group_count": len(values),
                "product_discovery_count": sum(
                    bool(value["product_discovery"]) for value in values
                ),
                "terminal_survival_count": sum(
                    bool(value["product_terminal_survival"]) for value in values
                ),
                "authorized_absence_count": sum(
                    bool(value["authorized_absence"]) for value in values
                ),
            }
        )
        result.append(item)
    return result


def _terminal_survival(lifecycle: Mapping[str, Any]) -> bool:
    return any(
        item["stage_id"] == "S42" and item["disposition"] == "KEPT"
        for item in lifecycle["lifecycle"]
    )


def _occurrence_source_ref(occurrence: Mapping[str, Any]) -> str | None:
    identity = occurrence.get("evidence_record_identity")
    if not isinstance(identity, Mapping) or identity.get("source_ref") is None:
        return None
    return _canonical_source_turn_ref(str(identity["source_ref"]))


def _canonical_source_turn_ref(value: str) -> str:
    """Join equivalent Runtime and scorer-only LongMem turn identities."""

    matched = _LONGMEM_SOURCE_REF.match(value)
    if matched is None:
        return value
    case_id, session_ordinal, session_id, turn_ordinal = matched.groups()
    return (
        f"{unquote(case_id)}:s{session_ordinal}:"
        f"{unquote(session_id)}:t{turn_ordinal}"
    )


def _stage_order(value: tuple[str, str]) -> int:
    return _stage_number(value[0])


def _stage_number(value: str) -> int:
    return int(value.removeprefix("S"))


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "SCORER_IDENTITY",
    "canonical_bytes",
    "score_sealed_artifacts",
    "sha256_file",
]
