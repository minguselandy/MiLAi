from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from evals.dg24.scorer import (
    _canonical_source_turn_ref,
    _channel_availability,
    _occurrence_source_ref,
    canonical_bytes,
    score_sealed_artifacts,
)

ROOT = Path(__file__).resolve().parents[1]


def _fixtures() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    case_ids = ["case-b", "case-a"]
    product = {
        "records": [
            {
                "case_id": case_id,
                "trace": {
                    "occurrences": [],
                    "candidate_lifecycles": [],
                    "dedup_decisions": [],
                    "channel_decisions": [],
                    "proof_obligations": [
                        {
                            "requirement_id": "req-1",
                            "kind": "ACCESS_SNAPSHOT",
                            "proof_artifact": None,
                            "proof_artifact_digest": None,
                        }
                    ],
                },
            }
            for case_id in case_ids
        ]
    }
    probes = {
        "records": [
            {
                "case_id": case_id,
                "trace": {
                    "requirement_id": "req-1",
                    "channel": "FTS_RAW",
                    "returned_occurrences": [],
                    "disposition": "UNAVAILABLE",
                    "reason_code": "CHANNEL_NOT_AVAILABLE",
                    "mutations": {"canonical": False},
                },
            }
            for case_id in case_ids
        ]
    }
    gold = {
        "queries": [
            {
                "query_id": case_id,
                "requirements": [
                    {
                        "requirement_id": "req-1",
                        "evidence_roles": [
                            {
                                "role": "VALUE",
                                "equivalence_groups": [
                                    {
                                        "equivalence_group_id": f"group-{case_id}",
                                        "source_turn_ref": f"{case_id}:turn-1",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            for case_id in case_ids
        ]
    }
    proof = {
        "queries": [
            {
                "query_id": case_id,
                "requirements": [
                    {
                        "requirement_id": "req-1",
                        "obligations": [
                            {"obligation_id": "access", "kind": "ACCESS_SNAPSHOT"}
                        ],
                    }
                ],
            }
            for case_id in case_ids
        ]
    }
    return product, probes, gold, proof


def _score(
    product: dict[str, Any],
    probes: dict[str, Any],
    gold: dict[str, Any],
    proof: dict[str, Any],
) -> dict[str, Any]:
    return score_sealed_artifacts(
        product=product,
        probes=probes,
        gold_registry=gold,
        proof_registry=proof,
        product_seal_digest="1" * 64,
        probe_seal_digest="2" * 64,
        gold_registry_digest="3" * 64,
        proof_registry_digest="4" * 64,
        rule_sources={},
    )


def test_dg24_scorer_is_deterministic_under_input_order_permutation() -> None:
    product, probes, gold, proof = _fixtures()
    baseline = _score(product, probes, gold, proof)
    shuffled = [deepcopy(value) for value in (product, probes, gold, proof)]
    for value in shuffled:
        value["records" if "records" in value else "queries"].reverse()

    assert canonical_bytes(baseline) == canonical_bytes(_score(*shuffled))


def test_dg24_scorer_does_not_mutate_sealed_inputs() -> None:
    fixtures = _fixtures()
    before = canonical_bytes(fixtures)

    _score(*fixtures)

    assert canonical_bytes(fixtures) == before


def test_scorer_canonicalizes_official_longmem_turn_identity() -> None:
    assert _canonical_source_turn_ref(
        "longmemeval://case/case-a/session/3/session-abc/turn/7?event_id=opaque"
    ) == "case-a:s3:session-abc:t7"
    assert _canonical_source_turn_ref("case-a:s3:session-abc:t7") == (
        "case-a:s3:session-abc:t7"
    )


def test_sealed_probe_and_gold_source_namespaces_have_real_join_coverage() -> None:
    probe_path = ROOT / (
        "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
        "sealed-official-probe-traces.json"
    )
    gold_path = ROOT / (
        "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
        "gold-equivalence-registry-v0.1.json"
    )
    probes = json.loads(probe_path.read_text(encoding="utf-8"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    probe_refs = {
        source_ref
        for record in probes["records"]
        for occurrence in record["trace"]["returned_occurrences"]
        if (source_ref := _occurrence_source_ref(occurrence)) is not None
    }
    gold_refs = {
        group["source_turn_ref"]
        for query in gold["queries"]
        for requirement in query["requirements"]
        for role in requirement["evidence_roles"]
        for group in role["equivalence_groups"]
    }

    assert probe_refs.intersection(gold_refs)


def test_cutoff_above_verified_channel_cap_is_typed_unavailable() -> None:
    report = _channel_availability(
        [
            {
                "discovery_availability": {
                    "EVIDENCE_DENSE": {
                        "rank": 20,
                        "available_at": [],
                        "cutoff_statuses": {
                            "8": "AVAILABLE",
                            "16": "AVAILABLE",
                            "32": "EXCEEDS_VERIFIED_OFFICIAL_AUDIT_CAP",
                            "64": "EXCEEDS_VERIFIED_OFFICIAL_AUDIT_CAP",
                        },
                    }
                }
            }
        ]
    )

    assert report["per_channel_recall"]["EVIDENCE_DENSE"]["32"] == {
        "status": "UNAVAILABLE",
        "found": 0,
        "denominator": 0,
        "unavailable_count": 1,
        "recall": None,
    }
