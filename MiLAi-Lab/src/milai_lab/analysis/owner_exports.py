"""Assemble same-execution public producer facts; no Product imports or guessing.

v1 admits fresh Evidence only. Explicit v2 binds current Runtime requests to
observed fresh origins for cache reuse; missing origins never become new retrievals.
"""
from __future__ import annotations

import copy
from typing import Any

from milai_lab.analysis.trace_join import CACHE_SCHEMA_VERSION, SCHEMA_VERSION, join_attempts


def _fresh_versions(
    row: dict[str, Any], owner: dict[str, Any], v2: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence = owner["selected_versions"]
    if row["selected_evidence_refs"] != owner["selected_evidence_refs"]:
        raise ValueError("RUNTIME_SELECTION_VERSION_MISMATCH")
    if not v2:
        if [v["memory_ref"] for v in evidence] != owner["selected_evidence_refs"]:
            raise ValueError("RUNTIME_SELECTION_VERSION_MISMATCH")
        return owner["materialized_evidence_versions"], evidence
    claims = owner["selected_claim_versions"]
    support = owner["selected_support_evidence_refs"]
    evidence_refs = [v["memory_ref"] for v in evidence]
    if (row["selected_claim_version_refs"] != owner["selected_claim_version_refs"]
            or [v["version_id"] for v in claims] != row["selected_claim_version_refs"]
            or (support and not claims)
            or not set(support) <= set(row["selected_evidence_refs"])
            or evidence_refs != [ref for ref in row["selected_evidence_refs"]
                                 if ref not in support or ref in evidence_refs]):
        raise ValueError("RUNTIME_SELECTION_VERSION_MISMATCH")
    return ([*owner["materialized_claim_versions"], *owner["materialized_evidence_versions"]],
            [*claims, *evidence])


def export_owner_attempts(
    cases: list[dict[str, Any]], *, run_id: str, product_lock_digest: str,
    result_refs: list[str],
    schema_version: str = SCHEMA_VERSION,
) -> list[dict[str, Any]]:
    """Return validated join-input facts, preserving owner rather than derived fields."""
    if schema_version not in {SCHEMA_VERSION, CACHE_SCHEMA_VERSION}:
        raise ValueError("UNSUPPORTED_JOIN_VERSION")
    v2 = schema_version == CACHE_SCHEMA_VERSION
    if len(cases) != len(result_refs):
        raise ValueError("OWNER_RESULT_CARDINALITY")
    facts = []
    origins: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for case, result_ref in zip(cases, result_refs, strict=True):
        host = case["host"]
        if host["schema_version"] != "milai-host-owner-trace-v1":
            raise ValueError("UNSUPPORTED_HOST_EXPORT")
        runtime_by_trace: dict[str, dict[str, Any]] = {}
        assembled_by_trace: dict[str, dict[str, Any]] = {}
        runtime = []
        for row in case["runtime"]:
            if row["schema_version"] != "milai-runtime-http-owner-v1":
                raise ValueError("UNSUPPORTED_RUNTIME_EXPORT")
            if row["receipt_reused"] and not v2:
                raise ValueError("CACHE_ORIGIN_JOIN_NOT_YET_SUPPORTED")
            if row["reader_gate"] not in {"ADMITTED", "ABSTAIN", "BLOCKED", "ERROR"}:
                raise ValueError("RUNTIME_READER_GATE_UNKNOWN")
            trace = row["request_ref"] if v2 else row["retrieval_trace_ref"]
            if trace in runtime_by_trace:
                raise ValueError("AMBIGUOUS_RUNTIME_EXPORT")
            runtime_by_trace[trace] = row
            owner = row["owner_trace"]
            if row["receipt_reused"]:
                prior = origins.get(row["context_capsule_ref"])
                if prior is None:
                    raise ValueError("CACHE_ORIGIN_NOT_OBSERVED")
                origin_attempt, origin_row, origin = prior
                validation = row["reuse_validation"]
                if (row["observation_gap"] is not None or owner is not None
                        or not isinstance(validation, dict)
                        or validation["runtime_request_ref"] != trace
                        or validation["origin_retrieval_trace_ref"] != row["retrieval_trace_ref"]
                        or validation["context_capsule_ref"] != row["context_capsule_ref"]
                        or validation["dependency_digest"] != row["dependency_digest"]
                        or validation["requirement_coverage_digest"] != row[
                            "requirement_coverage_digest"]
                        or row["selected_evidence_refs"] != origin_row["selected_evidence_refs"]
                        or row["selected_claim_version_refs"] != origin_row[
                            "selected_claim_version_refs"]):
                    raise ValueError("CACHE_VALIDATION_OWNER_MISMATCH")
                current = {
                    "retrieval_trace_id": row["retrieval_trace_ref"],
                    "decision_snapshot_digest": None, "evidence_set_digest": None,
                    "missing_reason": "NO_NEW_RETRIEVAL", "gate": row["reader_gate"],
                    "acquired_versions": [],
                    "selected_versions": copy.deepcopy(origin["selected_versions"]),
                    "origin_runtime_request_id": origin["runtime_request_id"],
                    "origin_host_attempt_trace_id": origin_attempt,
                    "canonical_position": validation["validation_canonical_position"],
                }
            elif (row["observation_gap"] is not None or not isinstance(owner, dict)
                    or owner["schema_version"] != "milai-runtime-owner-trace-v1"
                    or owner["status"] != "COMPLETE" or owner["trace_gaps"]):
                raise ValueError("INCOMPLETE_RUNTIME_OWNER_EXPORT")
            else:
                if row["retrieval_trace_ref"] != owner["retrieval_trace_ref"]:
                    raise ValueError("AMBIGUOUS_RUNTIME_EXPORT")
                acquired, selected = _fresh_versions(row, owner, v2)
                current = {
                    "retrieval_trace_id": row["retrieval_trace_ref"],
                    "decision_snapshot_digest": owner["decision_snapshot_digest"],
                    "evidence_set_digest": owner["evidence_set_digest"], "missing_reason": None,
                    "gate": row["reader_gate"], "acquired_versions": copy.deepcopy(acquired),
                    "selected_versions": copy.deepcopy(selected),
                }
                if v2:
                    current.update(
                        origin_runtime_request_id=None, origin_host_attempt_trace_id=None,
                        canonical_position=owner["canonical_position"],
                    )
            if v2:
                current.update(
                    runtime_request_id=trace,
                    execution_kind="CACHE_REUSE" if row["receipt_reused"] else "FRESH",
                    context_capsule_ref=row["context_capsule_ref"],
                    reader_context_sha256=row["reader_context_sha256"],
                    requirement_coverage_digest=row["requirement_coverage_digest"],
                    dependency_digest=row["dependency_digest"],
                )
                if not row["receipt_reused"] and row["context_capsule_ref"] is not None:
                    if row["context_capsule_ref"] in origins:
                        raise ValueError("CAPSULE_ORIGIN_REDEFINED")
                    origins[row["context_capsule_ref"]] = (
                        host["host_attempt_trace_id"], row, current,
                    )
            runtime.append(current)
            assembled_by_trace[trace] = current
        mcp = []
        invocations = {}
        for invocation in host["mcp_invocations"]:
            if invocation["receipt_reused"] and not v2:
                raise ValueError("CACHE_ORIGIN_JOIN_NOT_YET_SUPPORTED")
            identity = invocation["invocation_id"]
            if identity in invocations:
                raise ValueError("DUPLICATE_MCP_INVOCATION")
            invocations[identity] = invocation
            mcp.append({
                "invocation_id": identity,
                "host_attempt_trace_id": invocation["host_attempt_trace_id"],
                "retrieval_trace_id": invocation["retrieval_trace_ref"],
                "status": invocation["status"],
            })
            if v2:
                mcp[-1].update(
                    runtime_request_id=invocation["runtime_request_ref"],
                    receipt_reused=invocation["receipt_reused"],
                    context_capsule_ref=invocation["context_capsule_ref"],
                    previous_context_ref=invocation["previous_context_ref"],
                )
        provider = []
        for request in host["provider_requests"]:
            prepared = request["prepared_context_bindings"]
            bindings = request["context_bindings"]
            dispatch = request["exposure_status"]
            if dispatch == "DISPATCHED":
                if request["request_started"] is not True or bindings != prepared:
                    raise ValueError("DISPATCH_BINDING_MISMATCH")
            elif bindings or request["request_started"] is not (
                False if dispatch == "NOT_STARTED" else None
            ):
                raise ValueError("EXPOSURE_WITHOUT_KNOWN_DISPATCH")
            # Verify prepared bindings too, even when no dispatch is established.
            for binding in prepared:
                invocation = invocations.get(binding["mcp_invocation_id"])
                key = "runtime_request_ref" if v2 else "retrieval_trace_ref"
                row = runtime_by_trace.get(binding[key])
                if (invocation is None or invocation["status"] != "SUCCESS" or row is None
                        or invocation["retrieval_trace_ref"] != row["retrieval_trace_ref"]
                        or binding["reader_context_sha256"] != row["reader_context_sha256"]
                        or binding["selected_evidence_refs"] != row["selected_evidence_refs"]
                        or (v2 and (invocation[key] != row["request_ref"]
                            or binding["selected_claim_version_refs"]
                            != row["selected_claim_version_refs"]))):
                    raise ValueError("CONTEXT_NOT_BOUND_TO_RUNTIME_AND_MCP")
            if len(bindings) > 1:
                raise ValueError("MULTI_CONTEXT_COMPOSITION_NOT_YET_SUPPORTED")
            selected = []
            for binding in bindings:
                selected.extend(assembled_by_trace[binding[
                    "runtime_request_ref" if v2 else "retrieval_trace_ref"]]["selected_versions"])
            native = request["native_request_ref"]
            missing = None if native is not None else (
                "NOT_ACCEPTED" if dispatch == "NOT_STARTED" else
                "RESPONSE_LOST" if dispatch == "DISPATCHED" else "NOT_OBSERVED"
            )
            provider.append({
                "request_id": request["request_ref"],
                "host_attempt_trace_id": request["host_attempt_trace_id"],
                "provider_native_request_id": native, "native_id_missing_reason": missing,
                "status": request["status"], "exposure_status": dispatch,
                "reader_context_sha256": bindings[0]["reader_context_sha256"] if bindings else None,
                ("runtime_request_ids" if v2 else "retrieval_trace_ids"): [
                    b["runtime_request_ref" if v2 else "retrieval_trace_ref"] for b in bindings
                ],
                "exposed_versions": copy.deepcopy(selected),
                "usage": {"input_tokens": request["input_tokens"],
                          "output_tokens": request["output_tokens"]},
            })
        if host["terminal"] == "FAILURE":
            terminal = "FAILURE"
        else:
            routes = {"PROVIDER_AVAILABLE": "SUCCESS", "PROVIDER_NO_MEMORY": "NO_MEMORY",
                      "HOST_MEMORY_INSUFFICIENT": "ABSTAIN"}
            if case["route"] not in routes:
                raise ValueError("UNSUPPORTED_HOST_TERMINAL_ROUTE")
            terminal = routes[case["route"]]
        facts.append({
            "schema_version": schema_version, "run_id": run_id,
            "product_lock_digest": product_lock_digest,
            "host": {"host_attempt_trace_id": host["host_attempt_trace_id"],
                     "task_identity_digest": host["task_identity_digest"],
                     "retry_of": host["retry_of"], "terminal": terminal},
            "runtime": runtime, "mcp": mcp, "provider": provider,
            "lab": {"result_ref": result_ref, "observable_support": []},
        })
    join_attempts(facts)
    return facts


def assemble_owner_attempts(
    cases: list[dict[str, Any]], *, run_id: str, product_lock_digest: str,
    result_refs: list[str],
    schema_version: str = SCHEMA_VERSION,
) -> list[dict[str, Any]]:
    """Keep the existing joined-output API; ledger callers use the raw export above."""
    return join_attempts(export_owner_attempts(
        cases, run_id=run_id, product_lock_digest=product_lock_digest,
        result_refs=result_refs, schema_version=schema_version,
    ))
