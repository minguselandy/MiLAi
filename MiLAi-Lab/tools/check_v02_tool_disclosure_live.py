"""Finite public governance fixture and Host provenance checks; no model transport."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_e2e_live import metadata
from run_v02_local_vllm import dispatch, manifest, stop_owned
from v02_e2e_state import FileDisclosure, LocalGateError
from v02_low_cost_public import observer


def run(root: Path) -> None:
    config_path = base.LAB / "configs/v02-e2e-generality.json"
    config = base.read_json(config_path)
    assert not config["model_transport_enabled"]
    service = root / (root.name + "-product")
    namespace = service.name + "-pg"
    for cmd in (
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + namespace],
        ["docker", "volume", "ls", "-q", "--filter",
         "label=com.docker.compose.project=" + namespace],
    ):
        if base._command(cmd).stdout.strip():
            raise RuntimeError("SERVICE_NAMESPACE_ALREADY_EXISTS")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.write_json(root / "plan.json", {
        "pin": base.pin(config_path), "config": config,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_count": 1, "synthetic_proposals": 1, "synthetic_reviews": 1,
        "revocations": 1, "maximum_explicit_mcp_calls": 16, "maximum_metadata_gets": 64,
        "scope": "ISOLATED_SYNTHETIC_GOVERNANCE_FIXTURE_PUBLIC_MCP_AND_HOST_ADAPTER",
        "model_calls": 0, "provider_tokenize_calls": 0,
    })
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "independent.txt").write_text("Independent permitted file")
    override = root / "compose-limits.yaml"
    override.write_text("services:\n  postgres:\n    network_mode: bridge\n"
                        "    cpus: 2\n    mem_limit: 1g\n")
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {0, 1})
    calls, reads = [], []
    result = {"status": "RUNNING", "model_calls": 0, "provider_tokenize_calls": 0}
    try:
        base.prepare(service, config_path=config_path, compose_override=override,
                     runtime_overrides={
                         "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
                         "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "16",
                         "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "16",
                         "MILAI_RETRIEVAL_RERANKER_PROVIDER": "none",
                     })
        directory = root / "observer"
        directory.mkdir()
        project = root.name
        canary = "PUBLIC_EXACT_CLAIM_CANARY_e6b4"
        with observer(service, directory, project, project) as (raw_call, env):
            def call(tool, arguments):
                assert len(calls) < 16
                event = {"tool": tool, "arguments": arguments, "start": time.monotonic()}
                calls.append(event)
                try:
                    response = raw_call(tool, arguments)
                    event["response"] = response
                    assert not response.get("mcp_error"), response
                    return response
                finally:
                    event["end"] = time.monotonic()

            def source_metadata(ref):
                assert len(reads) < 64
                event = {"evidence_id": ref, "start": time.monotonic()}
                reads.append(event)
                try:
                    value = metadata(env, ref)
                    event["observed"] = {k: value.get(k) for k in (
                        "evidence_id", "revoked_at", "retention_state", "permission_snapshot",
                    )}
                    return value
                finally:
                    event["end"] = time.monotonic()

            def guarded(tool, arguments, guard):
                return dispatch(workspace, {}, {tool: {}}, call, {
                    "tool": "mcp_call",
                    "arguments_json": json.dumps({"name": tool, "arguments": arguments}),
                }, guard)

            guards = {name: FileDisclosure(project, {"independent.txt": []}, source_metadata)
                      for name in ("capture", "proposal", "list", "claim")}
            evidence = guarded("milai_evidence_capture", {
                "operation_id": "fixture-capture", "source_type": "AGENT_TURN",
                "source_ref": "engineering://" + root.name, "subject_id": "synthetic-service",
                "observed_at": datetime.now(UTC).isoformat(),
                "content": "Synthetic fixture service port is 6432. " + canary,
                "confirmation": "CAPTURE",
            }, guards["capture"])
            ref = evidence["evidence_id"]
            # Static test-fixture governance is outside the normal Agent dispatch allowlist.
            proposal = call("milai_proposal_create", {
                "operation_id": "fixture-proposal", "confirmation": "SUBMIT",
                "proposal": {"operation": "CREATE", "supporting_evidence_refs": [ref],
                    "proposed_patch": {"subject_id": "synthetic-service", "predicate": "port",
                        "claim_type": "FACT", "payload": {"port": 6432, "marker": canary},
                        "confidence": 0.99}},
            })
            guarded("milai_proposal_get", {"proposal_id": proposal["proposal_id"]},
                    guards["proposal"])
            guarded("milai_proposals_list", {}, guards["list"])
            reviewed = call("milai_memory_review", {
                "proposal_id": proposal["proposal_id"], "operation_id": "fixture-review",
                "decision": "APPROVE", "policy_version": "mcp-baseline-v1",
                "reason_code": "SYNTHETIC_BASELINE_VERIFIED", "confirmation": "APPROVE",
            })
            exact = guarded("milai_memory_get", {"claim_id": reviewed["claim_id"]},
                            guards["claim"])
            assert exact["schema_version"] == "memory-state-view-v0.1"
            assert exact["evidence_refs"] == [ref] and canary in json.dumps(exact)
            for name, guard in guards.items():
                assert guard.context_refs == {ref}, (name, guard.context_refs)
                guard.before_request()
                dispatch(workspace, {}, {}, call, {"tool": "write_file", "arguments_json":
                    json.dumps({"path": name + ".md", "content": canary})}, guard)
                assert guard.file_refs[name + ".md"] == [ref]
            call("milai_evidence_revoke", {
                "evidence_id": ref, "operation_id": "fixture-revoke",
                "reason_code": "USER_REQUEST", "confirmation": "REVOKE",
            })
            blocked = []
            for name, guard in guards.items():
                for operation in (guard.before_request, lambda g=guard, n=name: g.read(n + ".md")):
                    try:
                        operation()
                    except LocalGateError as exc:
                        assert str(exc) == "FILE_DISCLOSURE_DENIED"
                    else:
                        raise AssertionError("Revoked source allowed a resend or file read")
                assert guard.visible(manifest(workspace)) == {
                    "independent.txt": manifest(workspace)["independent.txt"],
                }
                permitted = dispatch(workspace, {}, {}, call, {
                    "tool": "read_file", "arguments_json": '{"path":"independent.txt"}',
                }, guard)
                assert permitted["text"] == "Independent permitted file"
                blocked.append(name)
            result.update(status="PUBLIC_TOOL_PROVENANCE_VERIFIED", blocked_paths=blocked,
                          synthetic_claim_id=reviewed["claim_id"], source_id=ref,
                          formal_e2e_passed=False)
    except BaseException as exc:
        result.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        os.sched_setaffinity(0, affinity)
        result.update(explicit_mcp_calls=len(calls), metadata_gets=len(reads))
        base.write_json(root / "public-calls.json", calls)
        base.write_json(root / "metadata-gets.json", reads)
        base.write_json(root / "result.json", result)
        base.write_json(root / "cleanup.json", stop_owned(service))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    run(args.root.resolve())
