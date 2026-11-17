"""Freeze isolated source/schema/visibility calibration fixtures, without model calls."""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import open_evidence_packs, project_packs
from milai_lab.runners.given_host_readout import SEPARATE_ANSWER_SCHEMA
from run_collected_handoff_readouts import parse_readout

KINDS = (
    "supported",
    "missing",
    "wrong",
    "format",
    "revoked",
    "unknown_execution",
    "question_role",
    "temporal",
    "interval_unknown",
)


def parsed_fixture(fields: dict[str, Any]) -> dict[str, Any]:
    return parse_readout(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(fields, ensure_ascii=False)},
                }
            ]
        },
        SEPARATE_ANSWER_SCHEMA,
    )


def response(
    answer: str, explanation: str, *, citations: list[str] | None = None
) -> dict[str, Any]:
    return parsed_fixture(
        {
            "answer": answer,
            "explanation": explanation,
            "evidence": ["e0"] if citations is None else citations,
        }
    )


def material(service: MemoryService, session: str, event: str, text: str) -> dict[str, Any]:
    ref = service.capture_user(session, event, text)["source_ref"]
    return {
        "kind": "original_source",
        "id": ref,
        "session_id": session,
        "turn_range": [0, 1],
        "source_ranges": [{"source_ref": ref, "source_revision": 1, "start": 0, "end": len(text)}],
    }


def packet(service: MemoryService, materials: list[dict[str, Any]]) -> dict[str, Any]:
    opened = open_evidence_packs(service, materials)
    return {
        "ok": True,
        "schema": "question_evidence_v1",
        "evidence": project_packs(opened, list(range(len(opened)))),
        "control_handoff": "policy",
        "instructions": "Answer only from delivered evidence. "
        "Handoff does not certify sufficiency. Report missing conditions explicitly.",
    }


def build_calibration(output: Path, *, worlds: int = 20, seed: int = 20261118) -> dict[str, Any]:
    if worlds < 2:
        raise ValueError("At least two worlds are needed for the fixed pilot")
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    rng = random.Random(seed)  # noqa: S311 -- fixed experimental world assignment
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    captures = opens = forgets = 0
    for world in range(worlds):
        root = output / f"world-{world:03d}"
        root.mkdir()
        with SqliteStore.from_conn_string(str(root / "bank.sqlite")) as store:
            service = MemoryService(
                store,
                ("review-calibration", str(world)),
                str(world),
                root / "lock",
                functional_contract="functional_v1",
                clock=lambda: datetime(2033, 1, 1, tzinfo=UTC),
            )
            name, owner, wrong_owner = f"Project-{world}", f"Aster-{world}", f"Birch-{world}"
            low, high = rng.randint(3, 40), rng.randint(60, 99)
            text = f"The delivered assignment report names {owner} as owner of {name}."
            original = material(service, "s", "assignment", text)
            captures += 1
            complete = packet(service, [original])
            opens += 1
            assert complete["evidence"][0]["evidence"][0]["content"] == text
            question = f"Whom does the assignment report name as owner of {name}?"

            def add(
                kind: str,
                query: str,
                delivered: dict[str, Any],
                first: dict[str, Any],
                material_status: str,
                resolution: bool | None,
                grounding: bool | None,
                proof: dict[str, Any],
                *,
                world_index: int = world,
            ) -> None:
                public = {
                    "question": query,
                    "query_time": "2033-05-31",
                    "packet": copy.deepcopy(delivered),
                    "first_observation": copy.deepcopy(first),
                    "observation_origin": "scripted_protocol_fixture_not_model_first",
                }
                private = {
                    "world": world_index,
                    "kind": kind,
                    "expected": {
                        "material_status": material_status,
                        "task_resolution": resolution,
                        "answer_grounding": grounding,
                    },
                    "proof": proof,
                    "grade": "A_scoped_executable_fixture_not_natural_semantic_truth",
                    "pilot": world_index == 0 or (world_index == 1 and kind == "supported"),
                }
                pending.append((public, private))

            if world % 2:
                comparison = material(
                    service,
                    "s",
                    "comparison",
                    f"Entry A has a reported limit of {low}; "
                    f"entry B has a reported limit of {high}.",
                )
                captures += 1
                compared = packet(service, [comparison])
                opens += 1
                assert high > low
                add(
                    "supported",
                    "Which entry has the larger reported numeric limit?",
                    compared,
                    response("B", f"The reported limits are {low} and {high}."),
                    "SUFFICIENT",
                    True,
                    True,
                    {"operator": "integer_greater_than", "A": low, "B": high},
                )
            else:
                add(
                    "supported",
                    question,
                    complete,
                    response(owner, "The report explicitly names it."),
                    "SUFFICIENT",
                    True,
                    True,
                    {"literal_reported_owner": owner, "source_body_matched_common_open": True},
                )
            empty = packet(service, [])
            opens += 1
            add(
                "missing",
                question,
                empty,
                response(
                    "Cannot establish from supplied evidence.",
                    "No original passage was delivered.",
                    citations=[],
                ),
                "INSUFFICIENT",
                False,
                True,
                {
                    "actual_delivered_original_bodies": 0,
                    "stored_source_not_counted_as_delivered": True,
                },
            )
            add(
                "wrong",
                question,
                complete,
                response(wrong_owner, "The report names this owner."),
                "SUFFICIENT",
                False,
                False,
                {
                    "literal_reported_owner": owner,
                    "asserted_different_owner": wrong_owner,
                    "same_available_packet_as_supported": world % 2 == 0,
                },
            )
            invalid = parsed_fixture({"answer": owner})
            assert invalid["status"] == "FAILED" and invalid["reason"] == "ValidationError"
            add(
                "format",
                question,
                complete,
                invalid,
                "SUFFICIENT",
                False,
                None,
                {
                    "actual_common_schema_rejection": invalid["reason"],
                    "semantic_material_still_present": True,
                },
            )
            add(
                "unknown_execution",
                question,
                complete,
                {
                    "status": "UNKNOWN",
                    "answer": None,
                    "reason": "scripted_missing_transport_observation",
                },
                "SUFFICIENT",
                None,
                None,
                {
                    "scope": "Supplied UNKNOWN boundary; not an observed service failure",
                    "actual_Model_or_HTTP_calls": 0,
                },
            )
            requested = material(
                service,
                "s",
                "request",
                f"Could you confirm whether the transfer for {name} completed?",
            )
            captures += 1
            request_packet = packet(service, [requested])
            opens += 1
            add(
                "question_role",
                f"Does the delivered record confirm completion for {name}?",
                request_packet,
                response("Yes", "The user confirmed that the transfer completed."),
                "SUFFICIENT",
                False,
                False,
                {
                    "actual_source_role": "user",
                    "source_is_question_not_assertion_or_tool_effect": True,
                    "scope": "Source question means no confirmation in record; not world truth.",
                },
            )
            boundary = date(2033, 6, 1)
            as_of = date(2033, 5, 31)
            temporal = material(
                service,
                "s",
                "schedule",
                f"Before {boundary}, the reported allowance is {low}. "
                f"From {boundary}, it is {high}.",
            )
            captures += 1
            temporal_packet = packet(service, [temporal])
            opens += 1
            assert as_of < boundary
            add(
                "temporal",
                f"According to the schedule, what allowance applies on {as_of}?",
                temporal_packet,
                response(str(high), "Use the later announced allowance."),
                "SUFFICIENT",
                False,
                False,
                {
                    "as_of": str(as_of),
                    "boundary": str(boundary),
                    "applicable_value": low,
                    "incorrect_future_value": high,
                    "capture_time_not_used_as_effective_date": True,
                },
            )
            interval = material(
                service,
                "s",
                "interval",
                f"The exact reported count for {name} is unresolved. "
                f"It can be any integer from {low} to {high}.",
            )
            captures += 1
            interval_packet = packet(service, [interval])
            opens += 1
            candidate = (low + high) // 2
            possible = {value == candidate for value in range(low, high + 1)}
            assert possible == {True, False}
            add(
                "interval_unknown",
                f"Is the exact reported count for {name} equal to {candidate}?",
                interval_packet,
                response("Yes", "That exact count is established."),
                "UNKNOWN",
                None,
                False,
                {
                    "allowed_interval": [low, high],
                    "queried_value": candidate,
                    "possible_query_truths": [False, True],
                    "scope": "Partial-world truth unresolved; assertion not entailed",
                },
            )
            handles = [f["fragment_handle"] for f in service.source_fragments(original["id"])]
            assert service.forget("s", "revoke-assignment", fragment_handles=handles)["ok"]
            forgets += 1
            assert service.source(original["id"]) is None
            revoked = packet(service, [original])
            opens += 1
            assert all(not p.get("evidence") for p in revoked["evidence"])
            assert owner not in json.dumps(revoked)
            add(
                "revoked",
                question,
                revoked,
                response(owner, "The delivered passage names this owner."),
                "INSUFFICIENT",
                False,
                False,
                {
                    "actual_common_source_revocation": True,
                    "common_reopen_delivered_bodies": 0,
                    "not_physical_erasure_claim": True,
                },
            )
    rng.shuffle(pending)
    cases, truths = [], []
    for i, (public, private) in enumerate(pending):
        code = f"J{i:03d}"
        cases.append({"case_code": code, **public})
        truths.append({"case_code": code, **private})
    assert len(cases) == worlds * len(KINDS)
    counts = Counter(row["kind"] for row in truths)
    assert set(counts) == set(KINDS) and set(counts.values()) == {worlds}
    assert len([r for r in truths if r["pilot"]]) == 10
    write_json(output / "judge-cases.json", cases)
    write_json(output / "private-truth.json", truths)
    write_json(output / "pilot-case-codes.json", [r["case_code"] for r in truths if r["pilot"]])
    report = {
        "status": "FROZEN_BEFORE_ANY_JUDGE_CALL",
        "fixture_protocol": "review-contract-fixtures-v2",
        "source_worlds": worlds,
        "cases": len(cases),
        "kind_counts": dict(counts),
        "prospective_pilot_cases": 10,
        "seed": seed,
        "actual_source_captures": captures,
        "actual_common_open_calls": opens,
        "actual_source_revocations": forgets,
        "scripted_observations_not_model_firsts": True,
        "truth_scope": "Executable source/schema/visibility/constraint properties only; "
        "not independent natural semantic truth or final confirmation.",
        "pilot_and_model_calls_admitted": False,
        "Reader_calls": 0,
        "judge_calls": 0,
        "GPU_job_requested": False,
        "existing_banks_changed": False,
        "sha_validation": False,
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
        "compute_ledger_status": "pending_idle_settlement",
    }
    write_json(output / "run.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--worlds", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    print(json.dumps(build_calibration(args.output, worlds=args.worlds, seed=args.seed)))


if __name__ == "__main__":
    main()
