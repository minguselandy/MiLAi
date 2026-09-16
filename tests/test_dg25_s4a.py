from __future__ import annotations

import ast
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    InterpretationEventTime,
    NormalizedTemporalConstraint,
    RequirementCardinalityV02,
)
from milai.domain.temporal_proof import (
    EventTimeIntervalV02,
    build_event_time_interval_v02,
    classify_range_membership,
    read_legacy_bounded_range_scan_proof_v01,
)

from evals.dg25.arm_sealing import (
    COMBINED_SEAL_READINESS_BINDING_FIELDS,
    COST_LEDGER_FIELDS,
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    build_block_all_arm_seal,
    build_combined_all_arm_seal,
    build_label_free_arm_output,
    validate_combined_all_arm_seal,
)
from evals.dg25.effect_scorer import _canonical_source_ref, scorer_contract
from evals.dg25.routing_ablation import E2ArmConfigV01, build_e2_arm_config
from evals.dg25.s4a_generator import (
    _CaseAnalysis,
    _event_interval,
    _point_membership,
    _project_arm_record,
    _TemporalCandidate,
    validate_s4a_authorization,
)
from evals.dg25.s4a_readiness import (
    S4A_OFFICIAL_RUN_ID,
    build_s4a_source_manifest,
    derive_combined_seal_readiness_bindings,
    read_json,
)
from scripts.run_dg25_s4a import (
    resolve_combined_seal_readiness_bindings,
    validate_independent_review,
    validate_official_run_id_binding,
    validate_top_level_paths,
)

ROOT = Path(__file__).resolve().parents[1]
PROOF_KINDS = (
    "BOUNDED_RANGE_SCAN",
    "SOURCE_PARTITION_CLOSURE",
    "EVENT_TIME_RESOLUTION",
    "DEDUP_COMPLETENESS",
    "PROJECTION_CLOSURE",
    "RAW_FALLBACK_CLOSURE",
    "ACCESS_SNAPSHOT",
)


def test_effect_scorer_joins_runtime_and_registry_turn_identities() -> None:
    runtime_ref = (
        "longmemeval://case/case%20a/session/3/session%2Fabc/turn/7?event_id=opaque"
    )

    assert _canonical_source_ref(runtime_ref) == "case a:s3:session/abc:t7"
    assert _canonical_source_ref("case a:s3:session/abc:t7") == (
        "case a:s3:session/abc:t7"
    )
    assert _canonical_source_ref("case a:s3:session/abc:t7?opaque=1") == (
        "case a:s3:session/abc:t7"
    )


@pytest.mark.parametrize(
    "source_ref",
    [
        "",
        "?event_id=missing-identity",
        "longmemeval://case/case-a/session/not-an-ordinal/session-a/turn/1",
        "longmemeval://case/case-a/session/1/session-a/turn/not-an-ordinal",
    ],
)
def test_effect_scorer_rejects_malformed_source_refs(source_ref: str) -> None:
    with pytest.raises(ValueError, match="DG25_SOURCE_REF_INVALID"):
        _canonical_source_ref(source_ref)


def test_s4a_interval_arm_is_conservative_at_closed_open_boundary() -> None:
    query_interval = _query_interval()
    span = _span(
        evidence_id="e-boundary",
        source_ref="synthetic:session-boundary:t0",
        session_id="session-boundary",
        text="user: Baby Alex was born on January 9.",
    )
    interpretation = _interpretation(
        identifier="i-boundary",
        span=span,
        event_identity="alex",
        event_time=InterpretationEventTime(
            start=datetime(2023, 1, 9, 12, tzinfo=UTC),
            end=datetime(2023, 1, 9, 12, tzinfo=UTC),
            normalized_from="January 9",
            anchor_provenance={"precision": "DAY"},
        ),
        time_basis="EXPLICIT_EVENT_TIME",
    )
    interval = _event_interval(interpretation, span)

    assert _point_membership(interpretation, query_interval) == "IN_RANGE"
    assert interval.interval_start == datetime(2023, 1, 9, 12, tzinfo=UTC)
    assert interval.interval_end_exclusive == datetime(2023, 1, 10, 12, tzinfo=UTC)
    assert interval.precision == "DAY"
    assert (
        classify_range_membership(interval, query_interval)
        == "AMBIGUOUS_RANGE_MEMBERSHIP"
    )


def test_s4a_t2_noop_dedup_multi_entity_and_v02_fail_closed() -> None:
    analysis = _analysis()
    configs = {item.arm_id: item for item in _configs()}

    t1 = _project_arm_record(analysis=analysis, config=configs["T1"])
    t2 = _project_arm_record(analysis=analysis, config=configs["T2"])
    t3 = _project_arm_record(analysis=analysis, config=configs["T3"])
    t4 = _project_arm_record(analysis=analysis, config=configs["T4"])

    assert t1 == t2
    t3_requirement = t3["requirements"][0]
    selected = t3_requirement["selected_occurrences"]
    assert len(selected) == 4
    assert (
        len(
            {
                item["event_identity_digest"]
                for item in selected
                if item["event_identity_digest"] is not None
            }
        )
        == 3
    )
    assert len(selected[0]["discovery_lineage"]) == 2
    assert t3_requirement["temporal_metrics"]["duplicate_candidate_count"] == 1
    assert t3_requirement["temporal_metrics"]["unresolved_event_count"] == 1

    t4_requirement = t4["requirements"][0]
    assert t4_requirement["sufficiency"] == "PARTIAL"
    assert t4_requirement["bounded_range_scan_proof_v02"]["status"] == "PARTIAL"
    statuses = {
        item["obligation_id"]: item["status"]
        for item in t4_requirement["proof_obligations"]
    }
    assert statuses["req:EVENT_TIME_RESOLUTION"] == "NOT_SATISFIED"
    assert statuses["req:DEDUP_COMPLETENESS"] == "NOT_SATISFIED"
    assert statuses["req:BOUNDED_RANGE_SCAN"] == "NOT_SATISFIED"


def test_s4a_authorization_is_exact_and_denies_scoring() -> None:
    expected = {"readiness_receipt_sha256": "a" * 64, "expected_arm_count": 5}
    material = {
        "schema": "milai.dg25.s4a-independent-authorization.v0.1",
        "authorized": True,
        "scope": "S4A_E2_LABEL_FREE_ALL_5_ARMS_E2_AND_COMBINED_SEALS",
        "readiness_bindings": expected,
        "readiness_bindings_digest": canonical_sha256(expected),
        "authorized_attempts": 1,
        "labels_authorized": False,
        "registry_content_authorized": False,
        "scoring_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
        "automatic_retries": 0,
    }
    authorization = {**material, "authorization_digest": canonical_sha256(material)}

    validate_s4a_authorization(
        authorization=authorization,
        expected_bindings=expected,
    )
    invalid = dict(authorization)
    invalid["scoring_authorized"] = True
    invalid_material = dict(invalid)
    invalid_material.pop("authorization_digest")
    invalid["authorization_digest"] = canonical_sha256(invalid_material)
    with pytest.raises(ValueError, match="DG25_S4A_AUTHORIZATION_BOUNDARY_INVALID"):
        validate_s4a_authorization(
            authorization=invalid,
            expected_bindings=expected,
        )


def test_combined_seal_recomputation_and_boundary_rejection() -> None:
    outputs = {}
    seals = {}
    for block, order, marker in (
        ("E1", E1_ARM_ORDER, "1"),
        ("E2", E2_ARM_ORDER, "2"),
    ):
        common = _common_execution_bindings(marker)
        block_inputs = {
            arm_id: {"input_digest": canonical_sha256([block, arm_id])}
            for arm_id in order
        }
        config_digests = {
            arm_id: canonical_sha256(["config", block, arm_id]) for arm_id in order
        }
        block_outputs = {
            arm_id: build_label_free_arm_output(
                block=block,
                arm_id=arm_id,
                arm_config_digest=config_digests[arm_id],
                common_execution_bindings=common,
                block_input_identity=block_inputs[arm_id],
                records=[],
                cost_ledger=_zero_cost_ledger(),
            )
            for arm_id in order
        }
        outputs.update(block_outputs)
        seals[block] = build_block_all_arm_seal(
            block=block,
            arm_outputs=block_outputs,
            arm_order=order,
            config_digests=config_digests,
            common_execution_bindings=common,
            block_input_identities=block_inputs,
            generator_source_sha256=marker * 64,
            sealer_source_sha256="3" * 64,
            runner_source_sha256="4" * 64,
            independent_authorization_digest="5" * 64,
        )
    readiness = {field: "6" * 64 for field in COMBINED_SEAL_READINESS_BINDING_FIELDS}
    readiness["final_k"] = 8
    combined = build_combined_all_arm_seal(
        e1_seal=seals["E1"],
        e2_seal=seals["E2"],
        arm_outputs=outputs,
        readiness_bindings=readiness,
    )

    validate_combined_all_arm_seal(
        seal=combined,
        e1_seal=seals["E1"],
        e2_seal=seals["E2"],
        arm_outputs=outputs,
        readiness_bindings=readiness,
    )
    tampered = dict(combined)
    tampered["scoring_executed_during_generation"] = True
    with pytest.raises(ValueError, match="DG25_COMBINED_SEAL_BOUNDARY_VIOLATION"):
        validate_combined_all_arm_seal(
            seal=tampered,
            e1_seal=seals["E1"],
            e2_seal=seals["E2"],
            arm_outputs=outputs,
            readiness_bindings=readiness,
        )

    with pytest.raises(
        ValueError, match="DG25_COMBINED_READINESS_BINDING_SCHEMA_MISMATCH"
    ):
        build_combined_all_arm_seal(
            e1_seal=seals["E1"],
            e2_seal=seals["E2"],
            arm_outputs=outputs,
            readiness_bindings={"s4a_readiness_receipt_sha256": "6" * 64},
        )


def test_combined_seal_bindings_match_frozen_scorer_contract() -> None:
    historical_root = ROOT / "var/dg25/readiness/dg25-s3-readiness-20260830-011"
    protocol = read_json(historical_root / "all-arm-seal-protocol.json")
    sealed_scorer_contract = read_json(historical_root / "effect-scorer-contract.json")
    stop_evaluation = read_json(historical_root / "stop-evaluation-contract.json")
    bindings, fields = derive_combined_seal_readiness_bindings(
        protocol=protocol,
        scorer_contract=sealed_scorer_contract,
    )

    assert tuple(fields) == COMBINED_SEAL_READINESS_BINDING_FIELDS
    assert fields == scorer_contract()["required_execution_bindings"]
    assert fields == sealed_scorer_contract["contract"]["required_execution_bindings"]
    assert bindings == stop_evaluation["readiness_bindings"]
    digest = canonical_sha256(bindings)
    execution_manifest = {
        "combined_seal_readiness_binding_fields": fields,
        "combined_seal_readiness_bindings": bindings,
        "combined_seal_readiness_bindings_digest": digest,
    }
    stop_contract = {
        "combined_seal_readiness_binding_fields": fields,
        "expected_combined_seal_readiness_bindings": bindings,
        "expected_combined_seal_readiness_bindings_digest": digest,
    }
    authorization_bindings = {
        "combined_seal_readiness_bindings_digest": digest,
    }

    assert (
        resolve_combined_seal_readiness_bindings(
            execution_manifest=execution_manifest,
            stop_contract=stop_contract,
            expected_authorization_bindings=authorization_bindings,
        )
        == bindings
    )


def test_s4a_review_and_runner_paths_fail_closed() -> None:
    expected = {"readiness_run_id": "ready", "expected_e2_arm_count": 5}
    receipt_identity = {
        "path": "var/dg25/s4a-readiness/ready/receipt.json",
        "sha256": "a" * 64,
        "size": 1,
    }
    authorization_material = {
        "schema": "milai.dg25.s4a-independent-authorization.v0.1",
        "authorized": True,
        "scope": "S4A_E2_LABEL_FREE_ALL_5_ARMS_E2_AND_COMBINED_SEALS",
        "readiness_bindings": expected,
        "readiness_bindings_digest": canonical_sha256(expected),
        "authorized_attempts": 1,
        "labels_authorized": False,
        "registry_content_authorized": False,
        "scoring_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
        "automatic_retries": 0,
    }
    authorization = {
        **authorization_material,
        "authorization_digest": canonical_sha256(authorization_material),
    }
    review_material = {
        "schema": "milai.dg25.s4a-independent-review.v0.1",
        "verdict": "AUTHORIZE_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEAL",
        "reviewed_readiness_receipt": receipt_identity,
        "readiness_bindings": expected,
        "readiness_bindings_digest": canonical_sha256(expected),
        "authorization": authorization,
    }
    review = {**review_material, "review_digest": canonical_sha256(review_material)}

    assert (
        validate_independent_review(
            review=review,
            readiness_receipt_identity=receipt_identity,
            expected_bindings=expected,
        )
        == authorization
    )
    invalid = dict(review)
    invalid["review_digest"] = "0" * 64
    with pytest.raises(ValueError, match="DG25_S4A_INDEPENDENT_REVIEW_DIGEST_MISMATCH"):
        validate_independent_review(
            review=invalid,
            readiness_receipt_identity=receipt_identity,
            expected_bindings=expected,
        )

    with pytest.raises(ValueError, match="DG25_S4A_RUN_ID_NOT_SAFE"):
        validate_top_level_paths(
            args=Namespace(
                run_id="../escape",
                readiness_run_id="ready",
                authorization_review=Path("var/dg25/reviews/review.json"),
            ),
            root=ROOT,
        )


def test_s4a_authorization_is_bound_to_one_official_output_run_id() -> None:
    expected = {"official_s4a_run_id": S4A_OFFICIAL_RUN_ID}
    execution_manifest = {"official_s4a_run_id": S4A_OFFICIAL_RUN_ID}
    stop_contract = {"official_s4a_run_id": S4A_OFFICIAL_RUN_ID}

    validate_official_run_id_binding(
        run_id=S4A_OFFICIAL_RUN_ID,
        expected_bindings=expected,
        execution_manifest=execution_manifest,
        stop_contract=stop_contract,
    )
    with pytest.raises(ValueError, match="DG25_S4A_OFFICIAL_RUN_ID_BINDING_MISMATCH"):
        validate_official_run_id_binding(
            run_id="dg25-s4a-e2-label-free-20260830-replay",
            expected_bindings=expected,
            execution_manifest=execution_manifest,
            stop_contract=stop_contract,
        )

    runner_source = (ROOT / "scripts/run_dg25_s4a.py").read_text(encoding="utf-8")
    assert runner_source.index("DG25_S4A_OFFICIAL_RUN_ID_BINDING_PRECHECK") < (
        runner_source.index("DG25_S4A_LABEL_FREE_INPUT_LOAD")
    )


def test_s4a_source_manifest_proves_generator_and_runner_isolation() -> None:
    manifest = build_s4a_source_manifest(ROOT)

    assert manifest["source_scan"]["generator_isolated"] is True
    assert manifest["source_scan"]["runner_isolated"] is True
    assert manifest["source_scan"]["scorer_registry_import_count"] == 0
    assert len(manifest["files"]) == 15


def test_s4a_generator_has_no_filesystem_scorer_or_label_entrypoint() -> None:
    path = ROOT / "evals/dg25/s4a_generator.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "evals.dg25.effect_scorer" not in imported_modules
    assert "evals.dg24.gold_registry" not in imported_modules
    assert "evals.dg24.proof_registry" not in imported_modules
    assert "pathlib" not in imported_modules
    assert not {"open", "eval", "exec", "__import__"}.intersection(call_names)


def _common_execution_bindings(marker: str) -> dict[str, object]:
    return {
        "execution_delta_manifest_digest": marker * 64,
        "all_arm_seal_protocol_digest": marker * 64,
        "readiness_source_manifest_digest": marker * 64,
        "case_order_digest": marker * 64,
        "config_set_digest": marker * 64,
        "input_binding_digest": marker * 64,
        "caps_digest": marker * 64,
        "cost_ledger_schema_digest": marker * 64,
        "final_k": 8,
    }


def _zero_cost_ledger() -> dict[str, object]:
    return {field: None if field == "latency_ms" else 0 for field in COST_LEDGER_FIELDS}


def _analysis() -> _CaseAnalysis:
    query_interval = _query_interval()
    requirement = EvidenceRequirementV02(
        slot_id="req",
        interpretation_kind="EVENT",
        entity_constraints=["born"],
        predicate_constraints=["matches_range", "deduplicate"],
        temporal_constraints=NormalizedTemporalConstraint(
            reference_time=datetime(2023, 1, 10, tzinfo=UTC),
            start=datetime(2023, 1, 1, tzinfo=UTC),
            end=datetime(2023, 1, 10, tzinfo=UTC),
            boundary="CLOSED_OPEN",
        ),
        cardinality=RequirementCardinalityV02(
            minimum=1,
            maximum=None,
            distinct=True,
        ),
    )
    candidates = [
        _candidate(
            rank=1,
            identity="alex",
            evidence_id="e-alex-1",
            session_id="session-family",
            event_time=datetime(2023, 1, 5, tzinfo=UTC),
            query_interval=query_interval,
        ),
        _candidate(
            rank=2,
            identity="alex",
            evidence_id="e-alex-2",
            session_id="session-family",
            event_time=datetime(2023, 1, 5, tzinfo=UTC),
            query_interval=query_interval,
        ),
        _candidate(
            rank=3,
            identity="blair",
            evidence_id="e-blair",
            session_id="session-family",
            event_time=datetime(2023, 1, 5, tzinfo=UTC),
            query_interval=query_interval,
        ),
        _candidate(
            rank=4,
            identity="alex",
            evidence_id="e-alex-later",
            session_id="session-family",
            event_time=datetime(2023, 1, 6, tzinfo=UTC),
            query_interval=query_interval,
        ),
        _candidate(
            rank=5,
            identity=None,
            evidence_id="e-unresolved",
            session_id="session-unresolved",
            event_time=None,
            query_interval=query_interval,
        ),
    ]
    legacy = read_legacy_bounded_range_scan_proof_v01(
        {
            "status": "COMPLETE",
            "scan_axis": "EVENT_OCCURRENCE_TIME",
            "source_partition_closed": True,
            "projection_watermark_covered": True,
            "projection_watermark": 5,
            "target_watermark": 5,
            "source_count": 5,
            "projected_count": 5,
            "returned_count": 5,
            "max_items": 2000,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
        }
    )
    return _CaseAnalysis(
        query_id="synthetic-query",
        query_identity="1" * 64,
        frozen_query_ir_digest="2" * 64,
        compiled_query_semantics_digest="3" * 64,
        requirement_id="req",
        requirement=requirement,
        query_interval=query_interval,
        common_requirement={
            "source_snapshot_identity": "4" * 64,
            "permission_snapshot_digest": "5" * 64,
            "retention_snapshot_digest": "6" * 64,
            "t2_applicability": {
                "disposition": "NOT_APPLICABLE",
                "reason_code": (
                    "NO_GROUNDED_UNIQUE_ANCHOR_RELATION_IN_SEALED_ROW_CONTRACT"
                ),
                "decided_before_labels": True,
            },
        },
        proof_obligations=tuple(
            {
                "kind": kind,
                "obligation_id": f"req:{kind}",
                "requirement_id": "req",
            }
            for kind in PROOF_KINDS
        ),
        legacy_proof=legacy,
        candidates=tuple(candidates),
        evidence_row_count=5,
    )


def _candidate(
    *,
    rank: int,
    identity: str | None,
    evidence_id: str,
    session_id: str,
    event_time: datetime | None,
    query_interval: EventTimeIntervalV02,
) -> _TemporalCandidate:
    span = _span(
        evidence_id=evidence_id,
        source_ref=f"synthetic:{session_id}:t{rank}",
        session_id=session_id,
        text="user: A baby was born.",
    )
    interpretation_time = (
        InterpretationEventTime(
            start=event_time,
            end=event_time,
            normalized_from="January 5",
            anchor_provenance={"precision": "DAY"},
        )
        if event_time is not None
        else None
    )
    interpretation = _interpretation(
        identifier=f"i-{rank}",
        span=span,
        event_identity=identity,
        event_time=interpretation_time,
        time_basis=(
            "EXPLICIT_EVENT_TIME" if event_time is not None else "SOURCE_OBSERVED_TIME"
        ),
    )
    interval = _event_interval(interpretation, span)
    return _TemporalCandidate(
        raw_rank=rank,
        raw_occurrence_id=f"raw-{rank}",
        evidence_id=evidence_id,
        source_turn_ref=span.source_turn_ref,
        span=span,
        interpretation=interpretation,
        applicability_status="MATCH",
        point_membership=_point_membership(interpretation, query_interval),
        interval=interval,
        interval_membership=classify_range_membership(interval, query_interval),
    )


def _span(
    *,
    evidence_id: str,
    source_ref: str,
    session_id: str,
    text: str,
) -> EvidenceSpan:
    return EvidenceSpan(
        span_id=f"span-{evidence_id}",
        source_evidence_id=evidence_id,
        source_turn_ref=source_ref,
        subject_id=session_id,
        session_id=session_id,
        turn_id=source_ref,
        identity_source="STRUCTURED_TURN_METADATA",
        speaker="user",
        start=0,
        end=len(text),
        text=text,
        source_timestamp=datetime(2023, 1, 5, 12, tzinfo=UTC),
        provenance={"source_span_verified": True},
    )


def _interpretation(
    *,
    identifier: str,
    span: EvidenceSpan,
    event_identity: str | None,
    event_time: InterpretationEventTime | None,
    time_basis: str,
) -> EvidenceInterpretationCandidate:
    return EvidenceInterpretationCandidate.model_validate(
        {
            "interpretation_id": identifier,
            "span_id": span.span_id,
            "kind": "EVENT",
            "value": {
                "text": span.text,
                "event_status": "OCCURRED",
                "event_identity": event_identity,
            },
            "entities": ["baby", "born"],
            "predicate": "event_observation",
            "event_time": event_time,
            "time_basis": time_basis,
            "extractor_identity": "synthetic-test",
        }
    )


def _query_interval() -> EventTimeIntervalV02:
    return build_event_time_interval_v02(
        interval_start=datetime(2023, 1, 1, tzinfo=UTC),
        interval_end_exclusive=datetime(2023, 1, 10, tzinfo=UTC),
        timezone="UTC",
        precision="RELATIVE_RANGE",
        basis="SOURCE_RELATIVE",
    )


def _configs() -> list[E2ArmConfigV01]:
    vectors = [
        (
            "T0",
            None,
            None,
            None,
            None,
            "bounded-range-scan-proof-v0.1",
            "dg24-proof-disposition-v0.1",
        ),
        (
            "T1",
            "T0",
            "event-time-interval-v0.2",
            None,
            None,
            "bounded-range-scan-proof-v0.1",
            "dg24-proof-disposition-v0.1",
        ),
        (
            "T2",
            "T1",
            "event-time-interval-v0.2",
            "unique-anchor-relative-v0.1",
            None,
            "bounded-range-scan-proof-v0.1",
            "dg24-proof-disposition-v0.1",
        ),
        (
            "T3",
            "T2",
            "event-time-interval-v0.2",
            "unique-anchor-relative-v0.1",
            "event-identity-dedup-v0.1",
            "bounded-range-scan-proof-v0.1",
            "dg24-proof-disposition-v0.1",
        ),
        (
            "T4",
            "T3",
            "event-time-interval-v0.2",
            "unique-anchor-relative-v0.1",
            "event-identity-dedup-v0.1",
            "bounded-range-scan-proof-v0.2",
            "bounded-range-scan-proof-validator-v0.2",
        ),
    ]
    return [
        build_e2_arm_config(
            arm_id=arm_id,
            ordered_predecessor=predecessor,
            interval_normalization_version=interval,
            unique_anchor_resolution_version=anchor,
            event_identity_dedup_version=identity,
            proof_writer_version=proof_writer,
            proof_validator_version=proof_validator,
            t2_applicability_source="PRELABEL_COMMON_INPUT",
            common_input_digest="f" * 64,
            component_source_identities={},
        )
        for (
            arm_id,
            predecessor,
            interval,
            anchor,
            identity,
            proof_writer,
            proof_validator,
        ) in vectors
    ]
