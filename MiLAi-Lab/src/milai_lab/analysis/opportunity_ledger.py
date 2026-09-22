"""Lab-only opportunity accounting over validated, content-free owner facts.

Structural validation is not producer authentication. The runner must actually
persist each opportunity snapshot before observing the corresponding outcome.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.analysis.trace_join import join_attempts

SCHEMA_VERSION = "milai-memory-opportunity-ledger-v1"
_ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$"}
_SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_COUNT = {"type": "integer", "minimum": 0}


def _object(**fields: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def _array(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


def _nullable(item: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [item, {"type": "null"}]}


_VERSION = _object(memory_ref=_ID, version_id=_ID, content_sha256=_SHA)
_SNAPSHOT = _object(
    sequence=_COUNT,
    task_input_sha256=_SHA,
    available_versions=_array(_VERSION),
    meaningful_alternatives=_array(_array(_VERSION)),
    baseline_attempt_id=_nullable(_ID),
)
_SEALED = _object(**_SNAPSHOT["properties"], snapshot_sha256=_SHA)
_DECISION = _object(sequence=_COUNT, version=_VERSION, support_ref=_ID)
_OBSERVATIONS = _object(
    schema_version={"const": SCHEMA_VERSION},
    method_version=_ID,
    method_sha256=_SHA,
    arm_kind={"enum": ["PRODUCT_TESTKIT", "PRODUCT_BLACK_BOX", "SIMULATION"]},
    usage_kind={"enum": ["MODEL", "CONTROLLED_FIXTURE", "NONE"]},
    attempts=_array(
        _object(
            host_attempt_trace_id=_ID,
            arm_id=_ID,
            task_id=_ID,
            policy_version=_ID,
            opportunity=_SEALED,
            outcome=_object(
                sequence=_COUNT,
                result_ref=_nullable(_ID),
                task_outcome={"enum": ["SUCCESS", "FAILURE", "ABSTAIN", "UNKNOWN"]},
            ),
            explicit_adoption=_array(_DECISION),
            explicit_rejection=_array(_DECISION),
            revision_opportunity={"type": "boolean"},
            revision_opportunity_ref=_nullable(_ID),
            costs=_object(
                retrieval_calls=_nullable(_COUNT),
                embedding_calls=_nullable(_COUNT),
                model_generations=_nullable(_COUNT),
                maintenance_input_tokens=_nullable(_COUNT),
                maintenance_output_tokens=_nullable(_COUNT),
                latency_ms=_nullable({"type": "number", "minimum": 0}),
                unknown_reasons=_array(_ID),
            ),
        )
    ),
    revisions=_array(
        _object(
            revision_id=_ID,
            source_attempt_id=_ID,
            created_sequence=_COUNT,
            predecessor=_VERSION,
            version=_VERSION,
            policy_version=_ID,
            kind={
                "enum": [
                    "CORRECTION",
                    "SCOPE_NARROWING",
                    "SCOPE_EXPANSION",
                    "EXAMPLE_REFRESH",
                    "RETIRE",
                ]
            },
            evidence_refs=_array(_ID),
        )
    ),
)
_VALIDATOR = Draft202012Validator(_OBSERVATIONS)
_SNAPSHOT_VALIDATOR = Draft202012Validator(_SNAPSHOT)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def freeze_opportunity(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Seal declared alternatives; caller persists this before outcome collection."""
    if next(_SNAPSHOT_VALIDATOR.iter_errors(snapshot), None) is not None:
        raise ValueError("INVALID_OPPORTUNITY_SNAPSHOT")
    return {**copy.deepcopy(snapshot), "snapshot_sha256": _digest(snapshot)}


def _key(version: dict[str, Any]) -> tuple[str, str, str]:
    return version["memory_ref"], version["version_id"], version["content_sha256"]


def _distinct(versions: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    values = {_key(version) for version in versions}
    if len(values) != len(versions):
        raise ValueError("DUPLICATE_OPPORTUNITY_VERSION")
    return values


def _accessed(joined: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {
        _key(version)
        for runtime in joined["runtime"]
        for version in (
            runtime["selected_versions"]
            if runtime.get("execution_kind") == "CACHE_REUSE"
            else runtime["acquired_versions"]
        )
    }


def _token_cost(requests: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [request["usage"][field] for request in requests]
    unknown = sum(value is None for value in values)
    known = sum(value for value in values if value is not None)
    return {
        field: None if unknown else known,
        "known_" + field: known,
        "unknown_" + field + "_requests": unknown,
    }


def build_opportunity_ledger(
    owner_facts: list[dict[str, Any]],
    observations: dict[str, Any],
) -> dict[str, Any]:
    """Validate one chronological pinned run; never manufacture use or causal credit."""
    if next(_VALIDATOR.iter_errors(observations), None) is not None:
        raise ValueError("INVALID_OPPORTUNITY_OBSERVATIONS")
    joined = join_attempts(owner_facts)
    metadata = observations["attempts"]
    if not joined or len(joined) != len(metadata):
        raise ValueError("OPPORTUNITY_ATTEMPT_CARDINALITY")
    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    sequences: set[int] = set()
    last_outcome = -1
    for facts, meta in zip(joined, metadata, strict=True):
        attempt_id = facts["host"]["host_attempt_trace_id"]
        if meta["host_attempt_trace_id"] != attempt_id:
            raise ValueError("OPPORTUNITY_ATTEMPT_ORDER_MISMATCH")
        pre, outcome = meta["opportunity"], meta["outcome"]
        snapshot = {key: value for key, value in pre.items() if key != "snapshot_sha256"}
        if _digest(snapshot) != pre["snapshot_sha256"]:
            raise ValueError("OPPORTUNITY_SNAPSHOT_CHANGED")
        if not last_outcome < pre["sequence"] < outcome["sequence"]:
            raise ValueError("OPPORTUNITY_NOT_FROZEN_BEFORE_OUTCOME")
        sequences.update((pre["sequence"], outcome["sequence"]))
        last_outcome = outcome["sequence"]
        if outcome["result_ref"] != facts["result_ref"] or (
            outcome["task_outcome"] != "UNKNOWN" and outcome["result_ref"] is None
        ):
            raise ValueError("UNBOUND_TASK_OUTCOME")
        available = _distinct(pre["available_versions"])
        if available != _accessed(facts):
            raise ValueError("OPPORTUNITY_POOL_NOT_OWNER_OBSERVED")
        alternatives: set[str] = set()
        for alternative in pre["meaningful_alternatives"]:
            if not alternative or not _distinct(alternative) <= available:
                raise ValueError("ALTERNATIVE_NOT_IN_FROZEN_POOL")
            alternative_digest = _digest(alternative)
            if alternative_digest in alternatives:
                raise ValueError("DUPLICATE_MEANINGFUL_ALTERNATIVE")
            alternatives.add(alternative_digest)
        if len(alternatives) >= 2 and len(available) < 2:
            raise ValueError("INSUFFICIENT_CANDIDATES_FOR_SELECTION_OPPORTUNITY")
        selected = [
            version for runtime in facts["runtime"] for version in runtime["selected_versions"]
        ]
        selected_set = {_key(version) for version in selected}
        decision_keys: dict[str, set[tuple[str, str, str]]] = {}
        for field, allowed in (
            ("explicit_adoption", selected_set),
            ("explicit_rejection", available),
        ):
            decision_keys[field] = set()
            for decision in meta[field]:
                key = _key(decision["version"])
                if key not in allowed or key in decision_keys[field]:
                    raise ValueError("UNBOUND_EXPLICIT_MEMORY_DECISION")
                if not pre["sequence"] < decision["sequence"] < outcome["sequence"]:
                    raise ValueError("MEMORY_DECISION_OUTSIDE_ATTEMPT")
                if decision["sequence"] in sequences:
                    raise ValueError("OPPORTUNITY_EVENT_REPLAY")
                sequences.add(decision["sequence"])
                decision_keys[field].add(key)
        if decision_keys["explicit_adoption"] & decision_keys["explicit_rejection"]:
            raise ValueError("CONTRADICTORY_EXPLICIT_MEMORY_DECISION")
        if meta["revision_opportunity"] != (meta["revision_opportunity_ref"] is not None):
            raise ValueError("REVISION_OPPORTUNITY_REQUIRES_SUPPORT")
        costs = meta["costs"]
        unknown_costs = [
            key for key, value in costs.items() if key != "unknown_reasons" and value is None
        ]
        if bool(unknown_costs) != bool(costs["unknown_reasons"]):
            raise ValueError("UNKNOWN_COST_REQUIRES_REASON")
        fresh = [
            runtime
            for runtime in facts["runtime"]
            if runtime.get("execution_kind") != "CACHE_REUSE"
        ]
        if costs["retrieval_calls"] is not None and costs["retrieval_calls"] < len(fresh):
            raise ValueError("RETRIEVAL_COST_OMITS_OBSERVED_EXECUTIONS")
        if observations["usage_kind"] != "MODEL" and costs["model_generations"] != 0:
            raise ValueError("FIXTURE_IS_NOT_MODEL_GENERATION")
        requests = facts["requests"]
        baseline_id = pre["baseline_attempt_id"]
        changed: bool | None = None
        if baseline_id is not None:
            baseline = by_id.get(baseline_id)
            if (
                baseline is None
                or baseline["task_id"] != meta["task_id"]
                or (
                    baseline["arm_id"] == meta["arm_id"]
                    or baseline["task_input_sha256"] != pre["task_input_sha256"]
                    or baseline["available_versions"] != pre["available_versions"]
                    or baseline["meaningful_alternatives"] != pre["meaningful_alternatives"]
                )
            ):
                raise ValueError("UNMATCHED_SELECTION_COMPARISON")
            changed = baseline["selected_versions"] != selected
        exposures = [
            {
                "request_id": request["request_id"],
                "exposure_status": request.get("exposure_status", "DISPATCHED"),
                "reader_context_sha256": request["reader_context_sha256"],
                "versions": request["exposed_versions"],
                "version_use": request["version_use"],
            }
            for request in requests
        ]
        failures = [
            {"owner": "PROVIDER", "ref": request["request_id"], "status": request["status"]}
            for request in requests
            if request["status"] != "SUCCESS"
        ]
        if facts["host"]["terminal"] == "FAILURE":
            failures.append({"owner": "HOST", "ref": attempt_id, "status": "FAILURE"})
        row = {
            "run_id": facts["run_id"],
            "arm_id": meta["arm_id"],
            "task_id": meta["task_id"],
            "attempt_id": attempt_id,
            "retry_of": facts["host"]["retry_of"],
            "product_lock_digest": facts["product_lock_digest"],
            "method_version": observations["method_version"],
            "method_sha256": observations["method_sha256"],
            "policy_version": meta["policy_version"],
            "arm_kind": observations["arm_kind"],
            "usage_kind": observations["usage_kind"],
            "opportunity_sequence": pre["sequence"],
            "outcome_sequence": outcome["sequence"],
            "task_input_sha256": pre["task_input_sha256"],
            "opportunity_snapshot_sha256": pre["snapshot_sha256"],
            "memory_available": bool(available),
            "available_versions": pre["available_versions"],
            "retrieved_candidate_count": len(
                {_key(v) for r in fresh for v in r["acquired_versions"]}
            ),
            "meaningful_alternatives": pre["meaningful_alternatives"],
            "meaningful_alternative_count": len(alternatives),
            "mechanism_opportunity": len(available) >= 2 and len(alternatives) >= 2,
            "selection_comparison_ref": baseline_id,
            "selection_changed": changed,
            "selected_versions": selected,
            "exposure_sequence": exposures,
            "exposed_versions": [v for request in requests for v in request["exposed_versions"]],
            "explicit_adoption": meta["explicit_adoption"],
            "explicit_rejection": meta["explicit_rejection"],
            "observable_use": "OBSERVABLY_USED"
            if any(request["observable_use"] == "OBSERVABLY_USED" for request in requests)
            else "UNKNOWN",
            "task_outcome": outcome["task_outcome"],
            "result_ref": outcome["result_ref"],
            "revision_opportunity": meta["revision_opportunity"],
            "revision_opportunity_ref": meta["revision_opportunity_ref"],
            "revision_created": [],
            "later_retrieval": [],
            "later_exposure": [],
            "later_use": [],
            **costs,
            **_token_cost(requests, "input_tokens"),
            **_token_cost(requests, "output_tokens"),
            "maintenance_tokens": None
            if any(
                costs[key] is None
                for key in (
                    "maintenance_input_tokens",
                    "maintenance_output_tokens",
                )
            )
            else costs["maintenance_input_tokens"] + costs["maintenance_output_tokens"],
            "failures": failures,
            "unknown_usage": bool(unknown_costs)
            or any(request["unknown_usage"] for request in requests),
            "unknown_cost_fields": unknown_costs,
            "trace_gaps": facts["trace_gaps"],
            "owner_facts_sha256": facts["facts_sha256"],
            "owner_trace_schema_version": facts["schema_version"],
            "causal_attribution": "NOT_ESTABLISHED",
        }
        rows.append(row)
        by_id[attempt_id] = row
    _bind_revisions(observations["revisions"], rows, by_id, sequences, joined)
    return copy.deepcopy(
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": joined[0]["run_id"],
            "product_lock_digest": joined[0]["product_lock_digest"],
            "observations_sha256": _digest(observations),
            "rows": rows,
            "funnel": _funnel(rows),
            "claim_ceiling": "ACCOUNTING_NOT_MECHANISM_BENEFIT",
        }
    )


def _bind_revisions(
    revisions: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    sequences: set[int],
    joined: list[dict[str, Any]],
) -> None:
    revision_ids: set[str] = set()
    versions: set[tuple[str, str]] = set()
    for revision in revisions:
        source = by_id.get(revision["source_attempt_id"])
        old, new = revision["predecessor"], revision["version"]
        created = revision["created_sequence"]
        if source is None or not source["revision_opportunity"] or not revision["evidence_refs"]:
            raise ValueError("REVISION_WITHOUT_SUPPORTED_OPPORTUNITY")
        if created <= source["outcome_sequence"] or created in sequences:
            raise ValueError("INVALID_REVISION_CHRONOLOGY")
        if (
            _key(old) not in {_key(v) for v in source["available_versions"]}
            or old["memory_ref"] != new["memory_ref"]
            or old["version_id"] == new["version_id"]
        ):
            raise ValueError("INVALID_REVISION_LINEAGE")
        version_id = (new["memory_ref"], new["version_id"])
        if revision["revision_id"] in revision_ids or version_id in versions:
            raise ValueError("REVISION_REPLAY")
        revision_ids.add(revision["revision_id"])
        versions.add(version_id)
        sequences.add(created)
        source["revision_created"].append(copy.deepcopy(revision))
        for row, facts in zip(rows, joined, strict=True):
            accessed = _accessed(facts)
            if any(key[:2] == version_id and key != _key(new) for key in accessed):
                raise ValueError("REVISION_VERSION_CONTENT_CHANGED")
            if _key(new) not in accessed:
                continue
            if row["opportunity_sequence"] <= created:
                raise ValueError("REVISION_REUSE_PRECEDES_CREATION")
            ref = {
                "revision_id": revision["revision_id"],
                "attempt_id": row["attempt_id"],
                "task_id": row["task_id"],
                "independent_task": row["task_id"] != source["task_id"],
                "version": new,
            }
            fresh = {
                _key(v)
                for r in facts["runtime"]
                if r.get("execution_kind") != "CACHE_REUSE"
                for v in r["acquired_versions"]
            }
            if _key(new) in fresh:
                source["later_retrieval"].append(copy.deepcopy(ref))
            if _key(new) in {_key(v) for v in row["exposed_versions"]}:
                source["later_exposure"].append(copy.deepcopy(ref))
            if any(
                _key(v["version"]) == _key(new) and v["observable_use"] == "OBSERVABLY_USED"
                for request in row["exposure_sequence"]
                for v in request["version_use"]
            ):
                source["later_use"].append(copy.deepcopy(ref))


def _funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stages: dict[str, Callable[[dict[str, Any]], bool]] = {
        "memory_available": lambda r: r["memory_available"],
        "meaningful_alternatives": lambda r: r["mechanism_opportunity"],
        "selection_changed": lambda r: (
            r["mechanism_opportunity"] and r["selection_changed"] is True
        ),
        "exposed": lambda r: bool(r["exposed_versions"]),
        "observable_use": lambda r: r["observable_use"] == "OBSERVABLY_USED",
        "outcome": lambda r: r["task_outcome"] != "UNKNOWN",
        "revision_opportunity": lambda r: r["revision_opportunity"],
        "revision": lambda r: bool(r["revision_created"]),
        "later_retrieved": lambda r: any(x["independent_task"] for x in r["later_retrieval"]),
        "later_exposed": lambda r: any(x["independent_task"] for x in r["later_exposure"]),
        "later_used": lambda r: any(x["independent_task"] for x in r["later_use"]),
    }
    counts = {name: sum(bool(predicate(row)) for row in rows) for name, predicate in stages.items()}
    return {
        "tasks": len({row["task_id"] for row in rows}),
        "attempts": len(rows),
        "stage_attempt_counts": counts,
        "selection_comparison_unknown": sum(row["selection_changed"] is None for row in rows),
        "mechanism_effect_denominator": sum(row["mechanism_opportunity"] for row in rows),
        "denominator_unit": "eligible attempts; matched effects must compare arms separately",
        "mechanism_opportunities_by_arm": {
            arm: sum(row["mechanism_opportunity"] for row in rows if row["arm_id"] == arm)
            for arm in sorted({row["arm_id"] for row in rows})
        },
        "without_opportunity_retained": sum(not row["mechanism_opportunity"] for row in rows),
        "causal_attribution": "NOT_ESTABLISHED",
        "note": "Stage counts are independently observed, not a forced monotone conversion funnel.",
    }
