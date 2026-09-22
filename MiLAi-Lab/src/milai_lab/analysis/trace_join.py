"""Validate content-free owner facts and join exposure to supported observations.

This module consumes the Trace Ownership v1 wire contract. It performs no Product
imports, retrieval, model calls, canonical writes, or inference-time label export.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

SCHEMA_VERSION = "milai-trace-join-v1"
_ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$"}
_DIGEST = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_COUNT = {"type": "integer", "minimum": 0}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _object(**fields: Any) -> dict[str, Any]:
    return {"type": "object", "properties": fields, "required": list(fields),
            "additionalProperties": False}


def _array(schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": schema}


_VERSION = _object(memory_ref=_ID, version_id=_ID, content_sha256=_DIGEST)
_INPUT = _object(
    schema_version={"const": SCHEMA_VERSION},
    run_id=_ID,
    product_lock_digest=_DIGEST,
    host=_object(
        host_attempt_trace_id=_ID,
        task_identity_digest=_DIGEST,
        retry_of=_nullable(_ID),
        terminal={"enum": ["SUCCESS", "FAILURE", "ABSTAIN", "NO_MEMORY"]},
    ),
    runtime=_array(_object(
        retrieval_trace_id=_ID,
        decision_snapshot_digest=_nullable(_DIGEST),
        evidence_set_digest=_nullable(_DIGEST),
        missing_reason={"enum": [None, "NOT_EXPORTED", "NO_DECISION", "RUNTIME_UNAVAILABLE"]},
        gate={"enum": ["ADMITTED", "BLOCKED", "ABSTAIN", "ERROR"]},
        acquired_versions=_array(_VERSION),
        selected_versions=_array(_VERSION),
    )),
    mcp=_array(_object(
        invocation_id=_ID,
        host_attempt_trace_id=_ID,
        retrieval_trace_id=_nullable(_ID),
        status={"enum": ["SUCCESS", "FAILURE", "BLOCKED"]},
    )),
    provider=_array(_object(
        request_id=_ID,
        host_attempt_trace_id=_ID,
        provider_native_request_id=_nullable(_ID),
        native_id_missing_reason={"enum": [None, "NOT_ACCEPTED", "RESPONSE_LOST", "NOT_OBSERVED"]},
        status={"enum": ["SUCCESS", "FAILURE", "UNKNOWN"]},
        reader_context_sha256=_nullable(_DIGEST),
        retrieval_trace_ids=_array(_ID),
        exposed_versions=_array(_VERSION),
        usage=_object(input_tokens=_nullable(_COUNT), output_tokens=_nullable(_COUNT)),
    )),
    lab=_object(
        result_ref=_nullable(_ID),
        observable_support=_array(_object(
            request_id=_ID,
            version=_VERSION,
            kind={"enum": ["EVIDENCE_ALIAS", "STRUCTURED_CITATION", "TOOL_REFERENCE",
                           "EXACT_VERSION_REVISION"]},
            support_ref=_ID,
        )),
    ),
)
# Optional for the original offline candidate; live producer assembly always supplies it.
_INPUT["properties"]["provider"]["items"]["properties"]["exposure_status"] = {
    "enum": ["DISPATCHED", "NOT_STARTED", "UNKNOWN"],
}
_VALIDATOR = Draft202012Validator(_INPUT)


def _identity(version: dict[str, Any]) -> tuple[str, str]:
    return version["memory_ref"], version["version_id"]


def _versions(rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for row in rows:
        key = _identity(row)
        if key in result:
            raise ValueError("DUPLICATE_MEMORY_VERSION")
        result[key] = row["content_sha256"]
    return result


def _unique(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("DUPLICATE_TRACE_ID")
    return result


def join_trace(facts: dict[str, Any]) -> dict[str, Any]:
    """Join one Host attempt; missing facts remain explicit and use stays UNKNOWN.

    The input is an external I/O boundary: unknown/body/label fields are rejected.
    An input's provenance must be verified by its runner; structural validation is
    not authentication and cannot turn an invented record into Product evidence.
    """
    if next(_VALIDATOR.iter_errors(facts), None) is not None:
        # Do not echo rejected private payloads or hidden labels in diagnostics.
        raise ValueError("INVALID_TRACE_OWNER_FACTS")
    host = facts["host"]
    attempt = host["host_attempt_trace_id"]
    if host["retry_of"] == attempt:
        raise ValueError("RETRY_REQUIRES_NEW_ATTEMPT")
    runtime = _unique(facts["runtime"], "retrieval_trace_id")
    _unique(facts["mcp"], "invocation_id")
    provider = _unique(facts["provider"], "request_id")
    native_ids: set[str] = set()
    linked_retrievals: set[str] = set()
    delivered_retrievals: set[str] = set()
    selected_by_trace: dict[str, dict[tuple[str, str], str]] = {}
    all_versions: dict[tuple[str, str], str] = {}
    gaps: list[dict[str, str]] = []
    for trace_id, row in runtime.items():
        missing = row["decision_snapshot_digest"] is None or row["evidence_set_digest"] is None
        if missing != (row["missing_reason"] is not None):
            raise ValueError("MISSING_TRACE_REASON_MISMATCH")
        if missing:
            gaps.append({"retrieval_trace_id": trace_id, "reason": row["missing_reason"]})
        acquired = _versions(row["acquired_versions"])
        selected = _versions(row["selected_versions"])
        if any(acquired.get(key) != digest for key, digest in selected.items()):
            raise ValueError("SELECTED_VERSION_NOT_ACQUIRED")
        for key, digest in acquired.items():
            if key in all_versions and all_versions[key] != digest:
                raise ValueError("MEMORY_VERSION_CONTENT_CHANGED")
            all_versions[key] = digest
        selected_by_trace[trace_id] = selected
    for row in facts["mcp"]:
        if row["host_attempt_trace_id"] != attempt:
            raise ValueError("CROSS_ATTEMPT_MCP_JOIN")
        trace_id = row["retrieval_trace_id"]
        if trace_id is not None:
            if trace_id not in runtime or trace_id in linked_retrievals:
                raise ValueError("AMBIGUOUS_OR_MISSING_RUNTIME_JOIN")
            linked_retrievals.add(trace_id)
            if row["status"] == "SUCCESS":
                delivered_retrievals.add(trace_id)
        elif row["status"] == "SUCCESS":
            raise ValueError("SUCCESSFUL_MCP_REQUIRES_RUNTIME_TRACE")
    if linked_retrievals != set(runtime):
        raise ValueError("UNBOUND_RUNTIME_TRACE")
    exposures: dict[str, dict[tuple[str, str], str]] = {}
    for request_id, row in provider.items():
        if row["host_attempt_trace_id"] != attempt:
            raise ValueError("CROSS_ATTEMPT_PROVIDER_JOIN")
        native = row["provider_native_request_id"]
        if (native is None) != (row["native_id_missing_reason"] is not None):
            raise ValueError("MISSING_NATIVE_ID_REASON_MISMATCH")
        if native is not None:
            if native in native_ids:
                raise ValueError("DUPLICATE_NATIVE_REQUEST")
            native_ids.add(native)
        elif row["status"] == "SUCCESS":
            raise ValueError("SUCCESSFUL_PROVIDER_REQUIRES_NATIVE_ID")
        else:
            gaps.append({"request_id": request_id, "reason": row["native_id_missing_reason"]})
        traces = row["retrieval_trace_ids"]
        if len(set(traces)) != len(traces) or not set(traces) <= linked_retrievals:
            raise ValueError("UNBOUND_PROVIDER_RETRIEVAL")
        admitted_selected: dict[tuple[str, str], str] = {}
        for trace_id in traces:
            if runtime[trace_id]["gate"] == "ADMITTED" and trace_id in delivered_retrievals:
                admitted_selected.update(selected_by_trace[trace_id])
        exposed = _versions(row["exposed_versions"])
        exposure_status = row.get("exposure_status")
        if exposure_status in {"NOT_STARTED", "UNKNOWN"} and exposed:
            raise ValueError("EXPOSURE_WITHOUT_KNOWN_DISPATCH")
        if exposure_status == "NOT_STARTED" and row["status"] == "SUCCESS":
            raise ValueError("SUCCESS_WITHOUT_DISPATCH")
        if exposure_status == "UNKNOWN":
            gaps.append({"request_id": request_id, "reason": "EXPOSURE_UNKNOWN"})
        if any(admitted_selected.get(key) != digest for key, digest in exposed.items()):
            raise ValueError("EXPOSURE_NOT_ADMITTED_AND_SELECTED")
        if exposed and row["reader_context_sha256"] is None:
            raise ValueError("EXPOSURE_REQUIRES_CONTEXT_DIGEST")
        if exposed and host["terminal"] == "NO_MEMORY":
            raise ValueError("NO_MEMORY_HAS_EXPOSURE")
        exposures[request_id] = exposed
    support_by_request: dict[str, list[dict[str, Any]]] = {key: [] for key in provider}
    support_ids: set[str] = set()
    for support in facts["lab"]["observable_support"]:
        request_id = support["request_id"]
        key = _identity(support["version"])
        if (request_id not in provider or provider[request_id]["status"] != "SUCCESS"
                or exposures[request_id].get(key) != support["version"]["content_sha256"]):
            raise ValueError("USE_SUPPORT_NOT_BOUND_TO_EXPOSED_VERSION")
        if support["support_ref"] in support_ids:
            raise ValueError("DUPLICATE_USE_SUPPORT")
        support_ids.add(support["support_ref"])
        support_by_request[request_id].append(copy.deepcopy(support))
    requests = []
    for request_id, row in provider.items():
        version_use = []
        for version in row["exposed_versions"]:
            refs = [
                support["support_ref"] for support in support_by_request[request_id]
                if _identity(support["version"]) == _identity(version)
            ]
            version_use.append({
                "version": copy.deepcopy(version),
                "observable_use": "OBSERVABLY_USED" if refs else "UNKNOWN",
                "support_refs": refs,
            })
        requests.append({
            **copy.deepcopy(row),
            "observable_use": "OBSERVABLY_USED" if support_by_request[request_id] else "UNKNOWN",
            "use_support": support_by_request[request_id],
            "version_use": version_use,
            "outcome_association": (
                "ORDERED_EXPOSURE_SEQUENCE" if facts["lab"]["result_ref"] is not None else "NONE"
            ),
            "causal_attribution": "NOT_ESTABLISHED",
            "unknown_usage": any(value is None for value in row["usage"].values()),
        })
    canonical = json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": facts["run_id"],
        "product_lock_digest": facts["product_lock_digest"],
        "host": copy.deepcopy(host),
        "runtime": copy.deepcopy(facts["runtime"]),
        "mcp": copy.deepcopy(facts["mcp"]),
        "requests": requests,
        "result_ref": facts["lab"]["result_ref"],
        "join_status": "PARTIAL" if gaps else "COMPLETE",
        "trace_gaps": gaps,
        "facts_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def join_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join chronological attempts in one pinned run, rejecting replay/retry drift."""
    seen: dict[str, dict[str, Any]] = {}
    requests: set[str] = set()
    natives: set[str] = set()
    retrievals: set[str] = set()
    invocations: set[str] = set()
    versions: dict[tuple[str, str], str] = {}
    joined: list[dict[str, Any]] = []
    for facts in attempts:
        result = join_trace(facts)
        if joined and any(
            joined[0][key] != result[key] for key in ("run_id", "product_lock_digest")
        ):
            raise ValueError("MIXED_RUN_OR_PRODUCT_LOCK")
        host = result["host"]
        identity = host["host_attempt_trace_id"]
        if identity in seen:
            raise ValueError("ATTEMPT_REPLAY")
        previous = host["retry_of"]
        if previous is not None and (
            previous not in seen
            or any(seen[previous][key] != result[key] for key in ("run_id", "product_lock_digest"))
            or seen[previous]["host"]["task_identity_digest"] != host["task_identity_digest"]
        ):
            raise ValueError("UNBOUND_RETRY")
        for trace in result["runtime"]:
            if trace["retrieval_trace_id"] in retrievals:
                raise ValueError("RETRIEVAL_REPLAY")
            retrievals.add(trace["retrieval_trace_id"])
            for version in trace["acquired_versions"]:
                key = _identity(version)
                if key in versions and versions[key] != version["content_sha256"]:
                    raise ValueError("MEMORY_VERSION_CONTENT_CHANGED")
                versions[key] = version["content_sha256"]
        for invocation in result["mcp"]:
            if invocation["invocation_id"] in invocations:
                raise ValueError("INVOCATION_REPLAY")
            invocations.add(invocation["invocation_id"])
        for row in result["requests"]:
            native = row["provider_native_request_id"]
            if row["request_id"] in requests or (native is not None and native in natives):
                raise ValueError("REQUEST_REPLAY")
            requests.add(row["request_id"])
            if native is not None:
                natives.add(native)
        seen[identity] = result
        joined.append(result)
    return joined
