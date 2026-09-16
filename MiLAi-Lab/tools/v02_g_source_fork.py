"""Carry G's confirmed public captures into independent continuation projects."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx

import run_v02_memory_flow as base
from v02_local_provider import LocalGateError, read_events, write_json
from v02_low_cost_public import observer
from v02_post_g_sources import completed_g_files
from v02_variant_plan import branches

SOURCE_FIELDS = ("source_type", "source_ref", "subject_id", "observed_at", "content",
                 "speaker", "source_context")


def captures(root: Path) -> dict[str, dict]:
    confirmed = {}
    for event in read_events(root / "G/tool-events.jsonl"):
        action = event.get("action", {})
        if action.get("tool") != "mcp_call":
            continue
        args = json.loads(action["arguments_json"])
        if args.get("name") != "milai_evidence_capture":
            continue
        receipt = event.get("acquired", {})
        if (receipt.get("mcp_error") or not receipt.get("evidence_id")
                or not receipt.get("outbox_id")):
            raise LocalGateError("G_CAPTURE_UNCONFIRMED_NO_BRANCH_FORK")
        ref = str(UUID(receipt["evidence_id"]))
        request = args["arguments"]
        if ref in confirmed and confirmed[ref]["request"] != request:
            raise LocalGateError("G_CAPTURE_RECEIPT_IDENTITY_CONFLICT")
        confirmed[ref] = {"request": request, "receipt": receipt}
    return confirmed


def declared_refs(value) -> set[str]:
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_refs":
                result.update(child)
            elif key == "evidence_id":
                result.add(child)
            else:
                result.update(declared_refs(child))
    elif isinstance(value, list):
        for child in value:
            result.update(declared_refs(child))
    return result


def require_eligible(record: dict, ref: str, project: str) -> None:
    permission = record.get("permission_snapshot", {})
    if (record.get("evidence_id") != ref or record.get("revoked_at")
            or record.get("retention_state") != "READABLE"
            or permission.get("readable") is not True
            or permission.get("project_ids") != [project]):
        raise LocalGateError("G_SOURCE_NOT_CURRENTLY_ELIGIBLE")


def require_same_observation(record: dict, request: dict) -> None:
    for key in SOURCE_FIELDS:
        if key == "observed_at":
            equal = datetime.fromisoformat(record[key]) == datetime.fromisoformat(request[key])
        elif key == "source_context":
            # The public typed context can make omitted null defaults explicit.
            expected, actual = request.get(key) or {}, record.get(key) or {}
            equal = all(actual.get(k) == v for k, v in expected.items()) and all(
                k in expected or v is None for k, v in actual.items())
        else:
            equal = record.get(key) == request.get(key)
        if not equal:
            raise LocalGateError("G_CAPTURE_SOURCE_DIFFERS_FROM_RECEIPTED_REQUEST:" + key)


def capture_classification(receipt: dict, request: dict, project: str) -> str:
    # This pinned public GET omits classification; use the correlated capture receipt.
    summary = receipt.get("confirmation_summary", {})
    expected = {key: request[key] for key in ("source_type", "source_ref", "subject_id")}
    expected.update(project_id=project, canonical_changed=False,
        content_sha256=hashlib.sha256(request["content"].encode()).hexdigest(),
        content_chars=len(request["content"]))
    classification = summary.get("data_classification")
    if (any(summary.get(key) != value for key, value in expected.items())
            or classification not in {"SYNTHETIC", "DEIDENTIFIED", "PERSONAL"}):
        raise LocalGateError("G_CAPTURE_CONFIRMATION_SUMMARY_NOT_BOUND")
    return classification


def input_fingerprint(root: Path) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
        "config.json", "G/tool-events.jsonl", "G/file-evidence-refs.json",
        "checkpoint-result.json", "G/result.json", "G/worker-exit.json",
        "frozen-g-files.json", "allocations.jsonl",
    )}


def complete_g_sources(root: Path) -> dict:
    """One public fork attempt, never re-create G or clear an unknown capture outcome."""
    confirmed = captures(root)
    snapshot = base.read_json(root / "prepared-bindings.json")
    config = base.read_json(root / "config.json")
    arms = branches(config)
    if (snapshot.get("status") != "PUBLIC_SOURCES_VERIFIED"
            or set(snapshot["branches"]) != set(arms)
            or len({b["project"] for b in snapshot["branches"].values()}) != len(arms)):
        raise LocalGateError("G_SOURCE_BRANCHES_NOT_ISOLATED")
    known = set(snapshot["branches"]["G"]["reference_mapping_from_g"])
    required = declared_refs(base.read_json(root / "checkpoint-result.json")["payload"])
    required.update(ref for refs in base.read_json(root / "G/file-evidence-refs.json").values()
                    for ref in refs)
    if required - known - set(confirmed):
        raise LocalGateError("G_REFERENCES_WITHOUT_CAPTURE_RECEIPTS")
    confirmed = {ref: value for ref, value in confirmed.items() if ref not in known}
    if not confirmed:
        return {"status": "NO_NEW_G_CAPTURES", "new_source_count": 0, "model_calls": 0}
    completed_g_files(root)
    fingerprint = input_fingerprint(root)
    output = root / "g-source-preparation"
    output.mkdir()  # Preserve partial writes; do not blindly replay an earlier attempt.
    started = time.monotonic()
    initial_bytes = (root / "prepared-bindings.json").read_bytes()
    write_json(output / "initial-bindings.json", snapshot)
    result = {"status": "PREPARING", "new_source_count": len(confirmed), "branches": {},
              "model_calls": 0, "input_sha256": fingerprint,
              "initial_bindings_sha256": hashlib.sha256(initial_bytes).hexdigest()}
    try:
        service = root / (root.name + "-product")
        env = base._load_environment(service / "runtime.env")
        with httpx.Client(base_url=env["MILAI_BASE_URL"], trust_env=False, follow_redirects=False,
                          timeout=10, headers={"Authorization": "Bearer " + env["MILAI_API_TOKEN"]}
                          ) as client:
            def get(ref):
                response = client.get("/v1/evidence/" + str(UUID(ref)))
                response.raise_for_status()
                return response.json()

            originals, classifications = {}, {}
            for ref, value in confirmed.items():
                record = get(ref)
                require_eligible(record, ref, snapshot["branches"]["G"]["project"])
                require_same_observation(record, value["request"])
                classifications[ref] = capture_classification(
                    value["receipt"], value["request"], snapshot["branches"]["G"]["project"])
                originals[ref] = record
            write_json(output / "original-metadata.json", originals)
            revised = copy.deepcopy(snapshot)
            all_ids = set(confirmed) | known | {
                target for branch in snapshot["branches"].values()
                for target in branch["reference_mapping_from_g"].values()}
            for arm in arms[1:]:
                binding = snapshot["branches"][arm]
                directory = output / arm
                directory.mkdir()
                outcomes, mapping, outbox_ids = [], {}, []
                result["branches"][arm] = {"project": binding["project"], "operations": outcomes}
                with observer(service, directory, binding["project"], binding["task_ref"]) as (
                    call, _,
                ):
                    for ref, original in originals.items():
                        require_eligible(get(ref), ref, snapshot["branches"]["G"]["project"])
                        request = {key: original.get(key) for key in SOURCE_FIELDS}
                        request.update(operation_id="fork-g-source-" + ref, confirmation="CAPTURE")
                        operation = {"original_evidence_id": ref, "request": request,
                                     "outcome": "UNKNOWN"}
                        outcomes.append(operation)
                        write_json(directory / "operations.json", outcomes)
                        receipt = call("milai_evidence_capture", request)
                        operation["receipt"] = receipt
                        target = receipt.get("evidence_id")
                        if receipt.get("mcp_error") or not target or not receipt.get("outbox_id"):
                            raise LocalGateError("BRANCH_G_CAPTURE_UNCONFIRMED")
                        operation["outcome"] = "RECEIPTED"
                        write_json(directory / "operations.json", outcomes)
                        if target in all_ids:
                            raise LocalGateError("G_SOURCE_FORK_IDENTITY_REUSED")
                        record = get(target)
                        require_eligible(record, target, binding["project"])
                        require_same_observation(record, original)
                        if capture_classification(receipt, request, binding["project"]) != (
                            classifications[ref]
                        ):
                            raise LocalGateError("G_SOURCE_CLASSIFICATION_CHANGED")
                        operation.update(outcome="CONFIRMED_AND_READABLE", metadata=record)
                        mapping[ref] = target
                        all_ids.add(target)
                        outbox_ids.append(receipt["outbox_id"])
                        write_json(directory / "operations.json", outcomes)
                readiness = []
                for start in range(0, len(outbox_ids), 512):
                    response = client.post("/v1/system/projection-readiness", timeout=35,
                        headers={"Authorization": "Bearer " + env["MILAI_AGENT_READER_TOKEN"]},
                        json={"target_outbox_ids": outbox_ids[start:start + 512],
                              "required_projections": ["evidence"],
                              "expected_versions": {"evidence": "evidence-search-v1"},
                              "timeout_ms": 30000, "poll_interval_ms": 50})
                    response.raise_for_status()
                    value = response.json()
                    readiness.append(value)
                    write_json(directory / "readiness.json", readiness)
                    if value.get("status") != "READY":
                        raise LocalGateError("G_SOURCE_FORK_INDEX_NOT_READY")
                revised["branches"][arm]["reference_mapping_from_g"].update(mapping)
                result["branches"][arm]["reference_mapping_from_g"] = mapping
                write_json(output / "progress.json", result)
            for ref in originals:
                require_eligible(get(ref), ref, snapshot["branches"]["G"]["project"])
        completed_g_files(root)
        if input_fingerprint(root) != fingerprint:
            raise LocalGateError("G_SOURCE_INPUT_CHANGED_DURING_PREPARATION")
        if (root / "prepared-bindings.json").read_bytes() != initial_bytes:
            raise LocalGateError("G_SOURCE_BINDINGS_CHANGED_DURING_PREPARATION")
        revised["G_new_evidence"] = "PUBLIC_G_CAPTURES_VERIFIED"
        revised["branches"]["G"]["reference_mapping_from_g"].update(
            {ref: ref for ref in confirmed})
        result["status"] = "PUBLIC_G_CAPTURES_FORKED"
        write_json(output / "ready-bindings.json", revised)
        # Publish only the all-branches result. A crash/partial JSON never permits a cold launch.
        write_json(root / "prepared-bindings.json", revised)
    except BaseException as exc:
        result.update(status="UNCONFIRMED_STOP_NO_RETRY", error_type=type(exc).__name__)
        raise
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        write_json(output / "result.json", result)
    return result
