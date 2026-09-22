"""Assemble same-execution public producer facts; no Product imports or guessing.

Only the fresh informational Evidence path is admitted in this first assembler.
Cache reuse, missing owner versions and unsupported shapes fail explicitly instead
of fabricating a new retrieval, an empty candidate pool or a model-use claim.
"""
from __future__ import annotations

import copy
from typing import Any

from milai_lab.analysis.trace_join import SCHEMA_VERSION, join_attempts


def assemble_owner_attempts(
    cases: list[dict[str, Any]], *, run_id: str, product_lock_digest: str,
    result_refs: list[str],
) -> list[dict[str, Any]]:
    if len(cases) != len(result_refs):
        raise ValueError("OWNER_RESULT_CARDINALITY")
    facts = []
    for case, result_ref in zip(cases, result_refs, strict=True):
        host = case["host"]
        if host["schema_version"] != "milai-host-owner-trace-v1":
            raise ValueError("UNSUPPORTED_HOST_EXPORT")
        runtime_by_trace: dict[str, dict[str, Any]] = {}
        runtime = []
        for row in case["runtime"]:
            if row["schema_version"] != "milai-runtime-http-owner-v1":
                raise ValueError("UNSUPPORTED_RUNTIME_EXPORT")
            if row["receipt_reused"]:
                raise ValueError("CACHE_ORIGIN_JOIN_NOT_YET_SUPPORTED")
            owner = row["owner_trace"]
            if (row["observation_gap"] is not None or not isinstance(owner, dict)
                    or owner["schema_version"] != "milai-runtime-owner-trace-v1"
                    or owner["status"] != "COMPLETE" or owner["trace_gaps"]):
                raise ValueError("INCOMPLETE_RUNTIME_OWNER_EXPORT")
            trace = row["retrieval_trace_ref"]
            if trace != owner["retrieval_trace_ref"] or trace in runtime_by_trace:
                raise ValueError("AMBIGUOUS_RUNTIME_EXPORT")
            if (row["selected_evidence_refs"] != owner["selected_evidence_refs"]
                    or [v["memory_ref"] for v in owner["selected_versions"]]
                    != owner["selected_evidence_refs"]):
                raise ValueError("RUNTIME_SELECTION_VERSION_MISMATCH")
            if row["reader_gate"] not in {"ADMITTED", "ABSTAIN", "BLOCKED", "ERROR"}:
                raise ValueError("RUNTIME_READER_GATE_UNKNOWN")
            runtime_by_trace[trace] = row
            runtime.append({
                "retrieval_trace_id": trace,
                "decision_snapshot_digest": owner["decision_snapshot_digest"],
                "evidence_set_digest": owner["evidence_set_digest"], "missing_reason": None,
                "gate": row["reader_gate"],
                "acquired_versions": copy.deepcopy(owner["materialized_evidence_versions"]),
                "selected_versions": copy.deepcopy(owner["selected_versions"]),
            })
        mcp = []
        invocations = {}
        for invocation in host["mcp_invocations"]:
            if invocation["receipt_reused"]:
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
                row = runtime_by_trace.get(binding["retrieval_trace_ref"])
                if (invocation is None or invocation["status"] != "SUCCESS" or row is None
                        or invocation["retrieval_trace_ref"] != row["retrieval_trace_ref"]
                        or binding["reader_context_sha256"] != row["reader_context_sha256"]
                        or binding["selected_evidence_refs"] != row["selected_evidence_refs"]):
                    raise ValueError("CONTEXT_NOT_BOUND_TO_RUNTIME_AND_MCP")
            if len(bindings) > 1:
                raise ValueError("MULTI_CONTEXT_COMPOSITION_NOT_YET_SUPPORTED")
            selected = []
            for binding in bindings:
                selected.extend(runtime_by_trace[binding["retrieval_trace_ref"]][
                    "owner_trace"]["selected_versions"])
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
                "retrieval_trace_ids": [b["retrieval_trace_ref"] for b in bindings],
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
            "schema_version": SCHEMA_VERSION, "run_id": run_id,
            "product_lock_digest": product_lock_digest,
            "host": {"host_attempt_trace_id": host["host_attempt_trace_id"],
                     "task_identity_digest": host["task_identity_digest"],
                     "retry_of": host["retry_of"], "terminal": terminal},
            "runtime": runtime, "mcp": mcp, "provider": provider,
            "lab": {"result_ref": result_ref, "observable_support": []},
        })
    return join_attempts(facts)
