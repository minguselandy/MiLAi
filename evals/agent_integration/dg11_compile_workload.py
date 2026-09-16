from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import milai_client
from milai_client.models import RecallEnvelope
from milai_client.optimization import (
    ContextCompileRequest,
    GovernedContextCompiler,
    TokenBudget,
    turn_fingerprint,
)


def _item(case: dict[str, Any]) -> dict[str, Any]:
    memory = case["memory"]
    case_id = str(case["case_id"])
    kind = str(memory["kind"])
    payload: dict[str, Any]
    if kind == "available":
        payload = {"value": memory["value"]}
    elif kind == "conflict":
        payload = {"candidate_values": memory["values"], "resolution": "UNRESOLVED"}
    else:
        raise ValueError(f"{case_id}: item requested for unsupported memory kind")
    return {
        "claim_id": f"claim-{case_id}",
        "claim_version_id": f"claim-version-{case_id}",
        "subject_id": f"subject-{case_id}",
        "predicate": memory["predicate"],
        "claim_type": "PREFERENCE"
        if case["category"] == "preference-constraint"
        else "FACT",
        "payload": payload,
        "scope_predicate": {"project_ids": [memory["scope"]]},
        "valid_time_from": "2026-08-23T00:00:00Z",
        "valid_time_to": None,
        "authority": memory["authority"],
        "epistemic_status": "EFFECTIVE",
        "effective_status": "EFFECTIVE",
        "canonical_commit_seq": 1,
        "open_issue_ids": [f"issue-{case_id}"] if kind == "conflict" else [],
    }


def _issue(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case["case_id"])
    memory = case["memory"]
    return {
        "issue_id": f"issue-{case_id}",
        "target_claim_id": f"claim-{case_id}",
        "issue_type": "CONFLICT",
        "status": "OPEN",
        "revision": 1,
        "scope_predicate": {"project_ids": [memory["scope"]]},
        "discharge_rule": {
            "must_address_branches": True,
            "requires_authority": memory["authority"],
        },
        "required_authority": memory["authority"],
        "branches": [
            {"relation_type": "SUPPORT_BRANCH", "evidence_id": f"evidence-a-{case_id}"},
            {
                "relation_type": "CONTRADICT_BRANCH",
                "evidence_id": f"evidence-b-{case_id}",
            },
        ],
    }


def compile_case(case: dict[str, Any]) -> dict[str, Any]:
    kind = str(case["memory"]["kind"])
    if kind == "none":
        return {
            "case_id": case["case_id"],
            "memory_status": "NO_MEMORY",
            "rendered_context": None,
            "actual_bytes": 0,
            "object_ids": [],
            "representation_policy_version": None,
        }
    issue = _issue(case) if kind == "conflict" else None
    items = [] if kind == "revoked" else [_item(case)]
    issue_ids = [issue["issue_id"]] if issue is not None else []
    body = {
        "results": items,
        "open_issue_ids": issue_ids,
        "retrieval_trace_id": f"trace-{case['case_id']}",
        "consistency": "CANONICAL_REQUIRED",
        "snapshot": {"canonical_outbox_sequence": 1},
        "degraded_components": [],
        "fallback_used": False,
        "fallback_reason": None,
        "abstained": kind == "revoked",
        "abstention_reason": "GROUNDING_BLOCKED" if kind == "revoked" else None,
        "request_id": f"request-{case['case_id']}",
    }
    envelope = RecallEnvelope.from_api(body)
    compiled = GovernedContextCompiler().compile(
        ContextCompileRequest(
            recall_envelope=envelope,
            session_id=f"session-{case['case_id']}",
            query_fingerprint=turn_fingerprint(str(case["query"])),
            constraints=("preserve authority scope and uncertainty",),
            token_budget=TokenBudget(max_bytes=16_384, budget_class="STANDARD"),
            open_issues=((issue,) if issue is not None else ()),
            safety_required=True,
        )
    )
    if compiled.delta.rendered_context is None or compiled.slot is None:
        raise ValueError(f"{case['case_id']}: compiler did not emit required context")
    return {
        "case_id": case["case_id"],
        "memory_status": "UNCERTAIN"
        if kind in {"conflict", "revoked"}
        else "AVAILABLE",
        "rendered_context": compiled.delta.rendered_context,
        "actual_bytes": compiled.metrics.actual_bytes,
        "object_ids": list(compiled.slot.object_ids),
        "representation_policy_version": compiled.slot.representation_policy_version,
        "content_sha256": hashlib.sha256(
            compiled.delta.rendered_context.encode()
        ).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile the DG11 agentic workload")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = dataset.get("cases") if isinstance(dataset, dict) else None
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("DG11 agentic workload must contain exactly 20 cases")
    output = {
        "schema": "milai.dg11.compiled-agentic-workload.v1",
        "compiler_origin": str(Path(milai_client.__file__).resolve()),
        "helper_origin": str(Path(__file__).resolve()),
        "records": [compile_case(case) for case in cases],
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
