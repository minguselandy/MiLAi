#!/usr/bin/env python3
"""Prepare the non-Formal Product-11 X0 source fixture and human review packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product11 import canonical_sha256, validate_source_fixture

ROOT = Path(__file__).resolve().parents[1]


def _specs() -> list[dict[str, Any]]:
    return [
        _spec(
            "p11-c01",
            "Which distinct clothing items did I buy this season?",
            [
                "ENUMERATION",
                "COUNTING",
                "SAME_TYPE_DIFFERENT_INSTANCE",
                "CROSS_SESSION_AGGREGATION",
                "CONTINUATION",
            ],
            "CONTINUATION",
            [
                ["I bought hiking boots in March.", "They are waterproof."],
                ["I bought a navy blazer in April."],
                ["I bought grey trousers in May."],
            ],
            [[(0, 0)], [(1, 0)], [(2, 0)]],
        ),
        _spec(
            "p11-c02",
            "List the distinct supplements I started taking.",
            [
                "ENUMERATION",
                "SAME_TYPE_DIFFERENT_INSTANCE",
                "REPEATED_MENTION",
                "CROSS_SESSION_AGGREGATION",
                "CONTINUATION",
            ],
            "CONTINUATION",
            [
                ["I started vitamin D.", "Vitamin D has helped my routine."],
                ["I added magnesium at night."],
                ["I began taking iron after the blood test."],
            ],
            [[(0, 0), (0, 1)], [(1, 0)], [(2, 0)]],
        ),
        _spec(
            "p11-c03",
            "Which cities did I visit after changing my travel plan?",
            ["ENUMERATION", "CROSS_SESSION_AGGREGATION", "UPDATE_COLLECTION", "CONTINUATION"],
            "CONTINUATION",
            [
                ["I first planned to visit Rome but cancelled it."],
                ["I visited Lisbon in June."],
                ["I visited Porto after Lisbon."],
                ["I later visited Madrid."],
            ],
            [[(1, 0)], [(2, 0)], [(3, 0)]],
        ),
        _spec(
            "p11-c04",
            "How many different medical appointments did I attend in July?",
            [
                "COUNTING",
                "SAME_TYPE_DIFFERENT_INSTANCE",
                "CROSS_SESSION_AGGREGATION",
                "CONTINUATION",
            ],
            "CONTINUATION",
            [
                ["I attended a dental cleaning on July 3."],
                ["I attended a vision exam on July 12."],
                ["I attended a physiotherapy visit on July 28."],
                ["An August checkup is only planned."],
            ],
            [[(0, 0)], [(1, 0)], [(2, 0)]],
        ),
        _spec(
            "p11-c05",
            "What distinct gifts did I receive for my birthday?",
            [
                "ENUMERATION",
                "SAME_TYPE_DIFFERENT_INSTANCE",
                "CROSS_SESSION_AGGREGATION",
                "CONTINUATION",
            ],
            "CONTINUATION",
            [
                ["Mina gave me a fountain pen."],
                ["Owen gave me a wool scarf."],
                ["Priya gave me a ceramic vase."],
                ["I thanked everyone the next day."],
            ],
            [[(0, 0)], [(1, 0)], [(2, 0)]],
        ),
        _spec(
            "p11-c06",
            "Which different novels did I finish during the break?",
            ["ENUMERATION", "REPEATED_MENTION", "CROSS_SESSION_AGGREGATION", "CONTINUATION"],
            "CONTINUATION",
            [
                ["I finished The Left Hand of Darkness.", "That Le Guin novel was excellent."],
                ["I finished Piranesi."],
                ["I finished Klara and the Sun."],
            ],
            [[(0, 0), (0, 1)], [(1, 0)], [(2, 0)]],
        ),
        _spec(
            "p11-c07",
            "What distinct responsibilities do I have after the role update?",
            ["ENUMERATION", "UPDATE_COLLECTION", "CROSS_SESSION_AGGREGATION", "CONTINUATION"],
            "CONTINUATION",
            [
                ["My old role only covered release notes."],
                ["I now lead sprint planning."],
                ["I now mentor two engineers."],
                ["I also own incident reviews."],
            ],
            [[(1, 0)], [(2, 0)], [(3, 0)]],
        ),
        _spec(
            "p11-c08",
            "How many different restaurants did I try on the trip?",
            [
                "COUNTING",
                "SAME_TYPE_DIFFERENT_INSTANCE",
                "CROSS_SESSION_AGGREGATION",
                "CONTINUATION",
            ],
            "CONTINUATION",
            [
                ["I ate at Cedar Table."],
                ["I tried Blue Lantern the next evening."],
                ["I had lunch at North Pier Cafe."],
                ["I returned to Cedar Table for dessert."],
            ],
            [[(0, 0), (3, 0)], [(1, 0)], [(2, 0)]],
        ),
        _spec(
            "p11-c09",
            "Which power tools did I purchase?",
            ["ENUMERATION", "COUNTING", "SAME_TYPE_DIFFERENT_INSTANCE"],
            "INTRA_SOURCE",
            [
                [
                    "I purchased a cordless drill.",
                    "The receipt was emailed.",
                    "I purchased a circular saw.",
                    "I compared safety glasses.",
                    "I purchased an orbital sander.",
                ]
            ],
            [[(0, 0)], [(0, 2)], [(0, 4)]],
        ),
        _spec(
            "p11-c10",
            "List the distinct pantry staples I restocked.",
            ["ENUMERATION", "SAME_TYPE_DIFFERENT_INSTANCE", "REPEATED_MENTION"],
            "INTRA_SOURCE",
            [
                [
                    "I restocked rice.",
                    "The rice went on the bottom shelf.",
                    "I cleaned the jars.",
                    "I restocked lentils.",
                    "I wrote a shopping list.",
                    "I restocked olive oil.",
                ]
            ],
            [[(0, 0), (0, 1)], [(0, 3)], [(0, 5)]],
        ),
        _spec(
            "p11-c11",
            "Which courses did I enroll in this term?",
            ["ENUMERATION", "COUNTING", "SAME_TYPE_DIFFERENT_INSTANCE"],
            "INTRA_SOURCE",
            [
                [
                    "I enrolled in statistics.",
                    "Classes begin Monday.",
                    "I enrolled in ceramics.",
                    "I bought notebooks.",
                    "I enrolled in Spanish conversation.",
                ]
            ],
            [[(0, 0)], [(0, 2)], [(0, 4)]],
        ),
        _spec(
            "p11-c12",
            "What different plants did I add to the balcony?",
            ["ENUMERATION", "SAME_TYPE_DIFFERENT_INSTANCE"],
            "INTRA_SOURCE",
            [
                [
                    "I added basil to the balcony.",
                    "It needs morning sun.",
                    "I added rosemary.",
                    "I changed the watering can.",
                    "I added a dwarf lemon tree.",
                ]
            ],
            [[(0, 0)], [(0, 2)], [(0, 4)]],
        ),
        _spec(
            "p11-c13",
            "Which repairs did I complete in the apartment?",
            ["ENUMERATION", "SAME_TYPE_DIFFERENT_INSTANCE", "UPDATE_COLLECTION"],
            "INTRA_SOURCE",
            [
                [
                    "I fixed the leaking kitchen tap.",
                    "The plumber visit was cancelled.",
                    "I replaced the hallway light switch.",
                    "I measured the bedroom wall.",
                    "I repaired the balcony latch.",
                ]
            ],
            [[(0, 0)], [(0, 2)], [(0, 4)]],
        ),
        _spec(
            "p11-c14",
            "How many different workouts did I complete this week?",
            ["COUNTING", "SAME_TYPE_DIFFERENT_INSTANCE", "REPEATED_MENTION"],
            "INTRA_SOURCE",
            [
                [
                    "I completed a five-kilometre run.",
                    "The run felt easier than last week.",
                    "I washed my shoes.",
                    "I completed a yoga class.",
                    "I made dinner.",
                    "I completed a swim session.",
                ]
            ],
            [[(0, 0), (0, 1)], [(0, 3)], [(0, 5)]],
        ),
        _spec(
            "p11-c15",
            "Which subscriptions did I renew?",
            ["ENUMERATION", "SAME_TYPE_DIFFERENT_INSTANCE", "UPDATE_COLLECTION"],
            "INTRA_SOURCE",
            [
                [
                    "I renewed the city newspaper.",
                    "The old music trial expired.",
                    "I renewed the cloud backup plan.",
                    "I changed my password.",
                    "I renewed the museum membership.",
                ]
            ],
            [[(0, 0)], [(0, 2)], [(0, 4)]],
        ),
        _spec(
            "p11-c16",
            "What different art supplies did I buy?",
            ["ENUMERATION", "COUNTING", "SAME_TYPE_DIFFERENT_INSTANCE"],
            "INTRA_SOURCE",
            [
                [
                    "I bought watercolour paper.",
                    "The shop was crowded.",
                    "I bought a sable brush.",
                    "I checked a frame size.",
                    "I bought masking fluid.",
                ]
            ],
            [[(0, 0)], [(0, 2)], [(0, 4)]],
        ),
        _spec(
            "p11-c17",
            "Which bicycle did I say I purchased?",
            ["REPEATED_MENTION"],
            "CONTROL",
            [
                [
                    "I purchased a green touring bicycle.",
                    "The green touring bicycle arrived today.",
                    "I adjusted its saddle.",
                ]
            ],
            [[(0, 0), (0, 1)]],
        ),
        _spec(
            "p11-c18",
            "What document did I renew?",
            ["UPDATE_COLLECTION"],
            "CONTROL",
            [["I renewed my passport last Tuesday.", "The new passport arrived by courier."]],
            [[(0, 0), (0, 1)]],
        ),
        _spec(
            "p11-c19",
            "Which phone am I currently using?",
            ["UPDATE_COLLECTION", "REPEATED_MENTION"],
            "CONTROL",
            [
                ["I used to have a silver phone."],
                ["I replaced it with a blue Pixel phone.", "The blue Pixel is now my daily phone."],
            ],
            [[(1, 0), (1, 1)]],
        ),
        _spec(
            "p11-c20",
            "Which two mugs did I buy?",
            ["ENUMERATION", "COUNTING", "SAME_TYPE_DIFFERENT_INSTANCE"],
            "CONTROL",
            [
                [
                    "I bought a red travel mug.",
                    "I also bought a white ceramic mug in the same order.",
                ]
            ],
            [[(0, 0)], [(0, 1)]],
        ),
        _spec(
            "p11-c21",
            "Which appointment was mentioned twice?",
            ["REPEATED_MENTION", "COUNTING"],
            "CONTROL",
            [
                [
                    "My dental cleaning is on September 9.",
                    "I confirmed the September 9 dental cleaning.",
                ]
            ],
            [[(0, 0), (0, 1)]],
        ),
        _spec(
            "p11-c22",
            "Which pet did I adopt?",
            ["REPEATED_MENTION"],
            "CONTROL",
            [
                ["I adopted a tabby cat named Juniper.", "Juniper slept on the sofa."],
                ["I bought cat food."],
            ],
            [[(0, 0), (0, 1)]],
        ),
        _spec(
            "p11-c23",
            "Which travel bookings did I confirm?",
            ["ENUMERATION", "CROSS_SESSION_AGGREGATION"],
            "CONTROL",
            [["I confirmed the train to Kyoto."], ["I confirmed the Riverside Hotel booking."]],
            [[(0, 0)], [(1, 0)]],
        ),
        _spec(
            "p11-c24",
            "Which shoes did I pack?",
            ["ENUMERATION", "COUNTING", "SAME_TYPE_DIFFERENT_INSTANCE"],
            "CONTROL",
            [["I packed running shoes.", "I packed brown boots.", "I packed canvas sandals."]],
            [[(0, 0)], [(0, 1)], [(0, 2)]],
        ),
    ]


def _spec(
    case_id: str,
    question: str,
    capability_shapes: Sequence[str],
    intended_stratum: str,
    session_turns: Sequence[Sequence[str]],
    group_members: Sequence[Sequence[tuple[int, int]]],
    *,
    allow_shared_candidate_turn: bool = False,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "question": question,
        "capability_shapes": list(capability_shapes),
        "intended_stratum": intended_stratum,
        "session_turns": [list(turns) for turns in session_turns],
        "group_members": [[list(member) for member in group] for group in group_members],
        "allow_shared_candidate_turn": allow_shared_candidate_turn,
    }


def _materialize(spec: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = str(spec["case_id"])
    sessions: list[dict[str, Any]] = []
    for session_index, texts in enumerate(spec["session_turns"], start=1):
        source_id = f"p11-source-{case_id}-{session_index:02d}"
        session_id = f"p11-session-{case_id}-{session_index:02d}"
        turns = [
            {
                "turn_id": f"{case_id}-s{session_index:02d}-t{turn_index:02d}",
                "turn_ref": f"p11://{case_id}/s{session_index:02d}/t{turn_index:02d}",
                "observed_at": f"2026-01-{session_index:02d}T{turn_index:02d}:00:00Z",
                "speaker": "user",
                "text": text,
            }
            for turn_index, text in enumerate(texts)
        ]
        sessions.append({"source_id": source_id, "session_id": session_id, "turns": turns})
    source_case = {
        "case_id": case_id,
        "question": spec["question"],
        "capability_shapes": spec["capability_shapes"],
        "intended_stratum": spec["intended_stratum"],
        "sessions": sessions,
    }
    groups: list[dict[str, Any]] = []
    seen_turns: set[str] = set()
    for group_index, members in enumerate(spec["group_members"], start=1):
        refs: list[str] = []
        source_ids: list[str] = []
        session_ids: list[str] = []
        for raw_session_index, raw_turn_index in members:
            session_index = int(raw_session_index)
            turn_index = int(raw_turn_index)
            session = sessions[session_index]
            ref = str(session["turns"][turn_index]["turn_ref"])
            refs.append(ref)
            source_ids.append(str(session["source_id"]))
            session_ids.append(str(session["session_id"]))
        if not spec["allow_shared_candidate_turn"] and seen_turns.intersection(refs):
            raise ValueError(f"candidate groups overlap in {case_id}")
        seen_turns.update(refs)
        groups.append(
            {
                "group_id": f"{case_id}:candidate-g{group_index}",
                "acceptable_evidence_ids": [],
                "acceptable_turn_refs": list(dict.fromkeys(refs)),
                "source_ids": list(dict.fromkeys(source_ids)),
                "session_ids": list(dict.fromkeys(session_ids)),
                "required_for_answer": True,
            }
        )
    proposal = {
        "record_type": "case",
        "case_id": case_id,
        "capability_shapes": spec["capability_shapes"],
        "instance_groups": groups,
        "continuation_opportunity": None,
        "intra_source_opportunity": None,
        "control_or_already_complete": None,
        "model_assisted_proxy": True,
        "human_adjudication_status": "PENDING",
    }
    return source_case, proposal


def _packet(
    *,
    packet_id: str,
    role: str,
    cases: Sequence[Mapping[str, Any]],
    fixture_file_sha256: str,
    fixture_semantic_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "milai-product11-human-review-packet-v0.1",
        "packet_id": packet_id,
        "role": role,
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "instructions": [
            "Review every case independently from the other human reviewer.",
            "Create distinct real-world instance groups and list exact acceptable turn refs.",
            "The same exact turn ref cannot belong to two distinct groups.",
            "Source/session overlap across distinct groups is allowed.",
            "Do not inspect Product treatment output; opportunity booleans are finalized "
            "after A0 trace join.",
            "Record a HUMAN attestation; model-generated proposals are not final labels.",
        ],
        "cases": list(cases),
        "submission_template": {
            "case_id": "copy from packet",
            "capability_shapes": ["copy from packet"],
            "instance_groups": [
                {
                    "group_id": "human-defined stable ID",
                    "acceptable_evidence_ids": [],
                    "acceptable_turn_refs": [],
                    "source_ids": [],
                    "session_ids": [],
                    "required_for_answer": True,
                }
            ],
            "notes": "human rationale",
            "human_adjudication_status": "REVIEWED",
            "attestation": {
                "kind": "HUMAN",
                "id": "human identity",
                "signed_at": "ISO-8601",
                "attestation": "I independently reviewed this case from the source packet.",
            },
        },
    }


def _write_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"refusing to overwrite immutable output: {path}")
        return
    path.write_text(text, encoding="utf-8")


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _jsonl_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def run(run_id: str) -> dict[str, Any]:
    materialized = [_materialize(spec) for spec in _specs()]
    cases = [case for case, _ in materialized]
    proposals = [proposal for _, proposal in materialized]
    fixture = {
        "schema_version": "milai-product11-opened-dev-v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "created_for": "MILA-PRODUCT-11-X0",
        "case_ids": [case["case_id"] for case in cases],
        "cases": cases,
    }
    fixture_summary = validate_source_fixture(fixture)
    fixture_text = _json_text(fixture)
    fixture_semantic_sha256 = canonical_sha256(fixture)
    fixture_file_sha256 = _sha256_text(fixture_text)
    fixture_path = ROOT / "data/fixtures/product11-opened-dev24.v0.1.json"
    _write_immutable(fixture_path, fixture_text)

    manifest = {
        "schema_version": "milai-product11-dataset-manifest-v0.2",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "files": {fixture_path.name: fixture_file_sha256},
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "case_count": 24,
        "case_order_sha256": fixture_summary["case_order_sha256"],
    }
    manifest_text = _json_text(manifest)
    manifest_path = ROOT / "data/manifests/product11-opened-dev24.v0.2.json"
    _write_immutable(manifest_path, manifest_text)

    proposal_header = {
        "record_type": "manifest",
        "schema_version": "milai-product11-instance-group-candidate-v0.2",
        "classification": "MODEL_ASSISTED_PROPOSAL_ONLY",
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "case_count": 24,
        "model_assisted_proxy": True,
        "human_adjudication_status": "PENDING",
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }
    proposal_text = _jsonl_text([proposal_header, *proposals])
    proposal_path = ROOT / "data/labels/product11-instance-groups.candidate.v0.2.jsonl"
    _write_immutable(proposal_path, proposal_text)

    adjudication_header = {
        "record_type": "manifest",
        "schema_version": "milai-product11-human-instance-groups-v0.1",
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "case_count": 24,
        "human_adjudication_status": "PENDING",
        "model_assisted_proxy": True,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }
    adjudication_rows = [
        {
            **proposal,
            "annotator": {
                "kind": "PENDING_HUMAN",
                "id": "",
                "signed_at": "",
                "attestation": "",
            },
            "reviewer": {
                "kind": "PENDING_HUMAN",
                "id": "",
                "signed_at": "",
                "attestation": "",
            },
            "adjudication_notes": (
                "Replace model proposal with independently reviewed human labels."
            ),
        }
        for proposal in proposals
    ]
    adjudication_path = ROOT / "data/labels/product11-human-adjudication.template.v0.2.jsonl"
    _write_immutable(
        adjudication_path,
        _jsonl_text([adjudication_header, *adjudication_rows]),
    )

    annotator_path = ROOT / "data/labels/product11-annotator.packet.v0.2.json"
    reviewer_path = ROOT / "data/labels/product11-reviewer.packet.v0.2.json"
    _write_immutable(
        annotator_path,
        _json_text(
            _packet(
                packet_id="P11-X0-ANNOTATOR-A",
                role="ANNOTATOR",
                cases=cases,
                fixture_file_sha256=fixture_file_sha256,
                fixture_semantic_sha256=fixture_semantic_sha256,
            )
        ),
    )
    _write_immutable(
        reviewer_path,
        _json_text(
            _packet(
                packet_id="P11-X0-REVIEWER-B",
                role="INDEPENDENT_REVIEWER",
                cases=cases,
                fixture_file_sha256=fixture_file_sha256,
                fixture_semantic_sha256=fixture_semantic_sha256,
            )
        ),
    )

    summary = {
        "schema_version": "milai-product11-x0-preparation-summary-v0.1",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "X0_AWAITING_HUMAN_ADJUDICATION",
        "source_fixture": str(fixture_path.relative_to(ROOT)),
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": fixture_semantic_sha256,
        "dataset_manifest": str(manifest_path.relative_to(ROOT)),
        "dataset_manifest_file_sha256": _sha256_text(manifest_text),
        "dataset_manifest_semantic_sha256": canonical_sha256(manifest),
        "candidate_labels": str(proposal_path.relative_to(ROOT)),
        "candidate_labels_file_sha256": _sha256_text(proposal_text),
        "candidate_labels_semantic_sha256": canonical_sha256([proposal_header, *proposals]),
        "human_adjudication_template": str(adjudication_path.relative_to(ROOT)),
        "annotator_packet": str(annotator_path.relative_to(ROOT)),
        "reviewer_packet": str(reviewer_path.relative_to(ROOT)),
        "fixture_summary": fixture_summary,
        "human_adjudication_complete_count": 0,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "product_behavior_written": False,
    }
    summary_path = ROOT / f"var/product11/{run_id}/summary.json"
    _write_immutable(summary_path, _json_text(summary))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(run(args.run_id), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
