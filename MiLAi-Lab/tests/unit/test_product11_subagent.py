from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from milai_lab.product11 import CAPABILITY_SHAPES, canonical_sha256, validate_human_seal
from milai_lab.product11_subagent import (
    ANNOTATOR_ROLE,
    ORCHESTRATION_SCHEMA,
    PROPOSAL_SCHEMA,
    REVIEWER_ROLE,
    build_subagent_review_packet,
    merge_independent_subagent_proposals,
    validate_subagent_merge_chain,
    validate_subagent_orchestration_manifest,
    validate_subagent_proposal,
    validate_subagent_review_packet,
    validate_subagent_seal,
)


def _load_tool_module(name: str) -> object:
    path = Path(__file__).resolve().parents[2] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load test tool module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge_tool = _load_tool_module("merge_product11_subagent_reviews")
seal_tool = _load_tool_module("seal_product11_subagent_labels")
prepare_tool = _load_tool_module("prepare_product11_subagent_workflow")


def _fixture() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for index in range(24):
        case_id = f"case-{index:02d}"
        cases.append(
            {
                "case_id": case_id,
                "question": f"What happened in {case_id}?",
                "capability_shapes": list(CAPABILITY_SHAPES),
                "intended_stratum": ("CONTINUATION", "INTRA_SOURCE", "CONTROL")[
                    index % 3
                ],
                "sessions": [
                    {
                        "source_id": f"source-{case_id}",
                        "session_id": f"session-{case_id}",
                        "turns": [
                            {
                                "turn_ref": f"p11://{case_id}/t0",
                                "text": f"Evidence for {case_id}",
                            },
                            {
                                "turn_ref": f"p11://{case_id}/t1",
                                "text": f"Other evidence for {case_id}",
                            },
                        ],
                    }
                ],
            }
        )
    return {
        "schema_version": "milai-product11-opened-dev-v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "cases": cases,
    }


def _proposal(*, role: str, identity: str, group_suffix: str) -> dict[str, object]:
    return {
        "schema_version": PROPOSAL_SCHEMA,
        "role": role,
        "identity": identity,
        "review_status": "COMPLETE",
        "source_packet_sha256": f"packet-{role}",
        "cases": [
            {
                "case_id": f"case-{index:02d}",
                "instance_groups": [
                    {
                        "group_id": f"case-{index:02d}:{group_suffix}",
                        "acceptable_turn_refs": [f"p11://case-{index:02d}/t0"],
                        "required_for_answer": True,
                    }
                ],
            }
            for index in range(24)
        ],
    }


def _traces() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(24):
        case_id = f"case-{index:02d}"
        if index < 8:
            rendered: list[str] = []
            direct: list[str] = []
            raw = [f"p11://{case_id}/t0"]
        elif index < 16:
            rendered = [f"p11://{case_id}/t1"]
            direct = list(rendered)
            raw = list(rendered)
        else:
            rendered = [f"p11://{case_id}/t0"]
            direct = list(rendered)
            raw = list(rendered)
        rows.append(
            {
                "schema_version": "milai-product11-x0-a0-case-trace-v0.1",
                "case_id": case_id,
                "status": "TRACE_COMPLETE",
                "source_snapshot_as_of": "2026-09-05T00:00:00Z",
                "invariants": {
                    "labels_loaded": False,
                    "label_fields_present": False,
                    "canonical_mutation": False,
                    "cross_namespace_source_count": 0,
                },
                "identity_sets": {
                    "rendered_evidence_ids": [],
                    "rendered_turn_refs": rendered,
                    "post_identity_evidence_ids": [],
                    "post_identity_turn_refs": direct,
                    "raw_evidence_ids": [],
                    "raw_turn_refs": raw,
                },
            }
        )
    return rows


def _envelope(*, identity: str, invocation: str, role: str) -> dict[str, object]:
    return {
        "kind": "SUBAGENT",
        "orchestrator_assigned_agent_id": identity,
        "invocation_id": invocation,
        "model_id": "test-model",
        "role": role,
        "input_bundle_sha256": f"packet-{role}",
        "output_sha256": f"output-{role}",
        "peer_output_supplied": False,
        "proposal_output_supplied": False,
        "a0_trace_supplied": False,
        "treatment_output_supplied": False,
    }


def _merge(
    annotator: dict[str, object], reviewer: dict[str, object]
) -> dict[str, object]:
    return merge_independent_subagent_proposals(
        _fixture(),
        _traces(),
        annotator,
        reviewer,
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
        annotator_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
        reviewer_packet_sha256=f"packet-{REVIEWER_ROLE}",
        annotator_proposal_sha256=f"output-{ANNOTATOR_ROLE}",
        reviewer_proposal_sha256=f"output-{REVIEWER_ROLE}",
        orchestration_manifest_sha256="manifest-sha",
        annotator_envelope=_envelope(
            identity="agent-a", invocation="invocation-a", role=ANNOTATOR_ROLE
        ),
        reviewer_envelope=_envelope(
            identity="agent-b", invocation="invocation-b", role=REVIEWER_ROLE
        ),
    )


def test_subagent_merge_ignores_local_group_ids_and_derives_opportunities() -> None:
    result = _merge(
        _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left"),
        _proposal(role=REVIEWER_ROLE, identity="agent-b", group_suffix="right"),
    )
    assert result["status"] == "READY_FOR_X0_SUBAGENT_SEAL"
    assert result["exact_semantic_agreement"] is True
    assert result["continuation_opportunity_count"] == 8
    assert result["intra_source_opportunity_count"] == 8
    assert result["control_or_already_complete_count"] == 8
    rows = result["adjudicated_rows"]
    assert isinstance(rows, list)
    assert validate_subagent_seal(_fixture(), rows)["status"] == (
        "PASS_PRODUCT11_X0_SUBAGENT_SEAL"
    )
    with pytest.raises(ValueError, match="human seal manifest is invalid"):
        validate_human_seal(_fixture(), rows)


def test_subagent_merge_conflict_is_hash_only_and_fail_closed() -> None:
    annotator = _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left")
    reviewer = _proposal(role=REVIEWER_ROLE, identity="agent-b", group_suffix="right")
    reviewer["cases"][0]["instance_groups"][0]["acceptable_turn_refs"] = [
        "p11://case-00/t1"
    ]
    result = _merge(annotator, reviewer)
    assert result["status"] == "BLOCKED_PRODUCT11_SUBAGENT_SEMANTIC_DISAGREEMENT"
    assert result["adjudicated_rows"] is None
    assert result["conflict_case_count"] == 1
    conflict = result["conflicts"][0]
    assert set(conflict) == {
        "case_id",
        "reason",
        "annotator_semantic_sha256",
        "reviewer_semantic_sha256",
    }


def test_subagent_proposal_rejects_human_and_opportunity_fields() -> None:
    proposal = _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left")
    proposal["human_attestation"] = {"kind": "HUMAN"}
    with pytest.raises(ValueError, match="fields are invalid"):
        validate_subagent_proposal(
            _fixture(),
            proposal,
            expected_role=ANNOTATOR_ROLE,
            expected_identity="agent-a",
            expected_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
        )

    proposal = _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left")
    proposal["cases"][0]["continuation_opportunity"] = True
    with pytest.raises(ValueError, match="adjudication-only"):
        validate_subagent_proposal(
            _fixture(),
            proposal,
            expected_role=ANNOTATOR_ROLE,
            expected_identity="agent-a",
            expected_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
        )


def test_subagent_merge_rejects_same_identity_or_invocation() -> None:
    annotator = _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left")
    reviewer = _proposal(role=REVIEWER_ROLE, identity="agent-a", group_suffix="right")
    left = _envelope(identity="agent-a", invocation="same", role=ANNOTATOR_ROLE)
    right = _envelope(identity="agent-a", invocation="same", role=REVIEWER_ROLE)
    with pytest.raises(ValueError, match="identities are not distinct"):
        merge_independent_subagent_proposals(
            _fixture(),
            _traces(),
            annotator,
            reviewer,
            fixture_file_sha256="fixture-sha",
            a0_trace_sha256="trace-sha",
            annotator_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
            reviewer_packet_sha256=f"packet-{REVIEWER_ROLE}",
            annotator_proposal_sha256=f"output-{ANNOTATOR_ROLE}",
            reviewer_proposal_sha256=f"output-{REVIEWER_ROLE}",
            orchestration_manifest_sha256="manifest-sha",
            annotator_envelope=left,
            reviewer_envelope=right,
        )


def test_subagent_merge_rejects_same_invocation_with_distinct_identities() -> None:
    annotator = _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left")
    reviewer = _proposal(role=REVIEWER_ROLE, identity="agent-b", group_suffix="right")
    left = _envelope(identity="agent-a", invocation="same", role=ANNOTATOR_ROLE)
    right = _envelope(identity="agent-b", invocation="same", role=REVIEWER_ROLE)
    with pytest.raises(ValueError, match="invocation identities are not distinct"):
        merge_independent_subagent_proposals(
            _fixture(),
            _traces(),
            annotator,
            reviewer,
            fixture_file_sha256="fixture-sha",
            a0_trace_sha256="trace-sha",
            annotator_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
            reviewer_packet_sha256=f"packet-{REVIEWER_ROLE}",
            annotator_proposal_sha256=f"output-{ANNOTATOR_ROLE}",
            reviewer_proposal_sha256=f"output-{REVIEWER_ROLE}",
            orchestration_manifest_sha256="manifest-sha",
            annotator_envelope=left,
            reviewer_envelope=right,
        )


def test_subagent_proposal_identity_is_bound_by_expected_envelope() -> None:
    proposal = _proposal(role=ANNOTATOR_ROLE, identity="self-asserted", group_suffix="left")
    with pytest.raises(ValueError, match="provenance is invalid"):
        validate_subagent_proposal(
            _fixture(),
            proposal,
            expected_role=ANNOTATOR_ROLE,
            expected_identity="orchestrator-assigned",
            expected_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
        )


def test_subagent_label_requires_model_provenance_not_human_completion() -> None:
    result = _merge(
        _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left"),
        _proposal(role=REVIEWER_ROLE, identity="agent-b", group_suffix="right"),
    )
    rows = result["adjudicated_rows"]
    assert isinstance(rows, list)
    invalid = deepcopy(rows)
    invalid[0]["human_adjudication_status"] = "COMPLETE"
    with pytest.raises(ValueError, match="manifest is invalid"):
        validate_subagent_seal(_fixture(), invalid)


def test_subagent_source_packet_is_role_bound_and_proposal_free() -> None:
    fixture = _fixture()
    packet = build_subagent_review_packet(
        fixture,
        role=ANNOTATOR_ROLE,
        packet_id="packet-a",
        fixture_file_sha256="fixture-sha",
    )
    result = validate_subagent_review_packet(
        fixture,
        packet,
        expected_role=ANNOTATOR_ROLE,
        expected_fixture_file_sha256="fixture-sha",
    )
    assert result["status"] == "VALID_SOURCE_ONLY_SUBAGENT_PACKET"
    assert "intended_stratum" not in packet["cases"][0]
    assert "instance_groups" not in packet["cases"][0]

    invalid = deepcopy(packet)
    invalid["role"] = REVIEWER_ROLE
    with pytest.raises(ValueError, match="provenance is invalid"):
        validate_subagent_review_packet(
            fixture,
            invalid,
            expected_role=ANNOTATOR_ROLE,
            expected_fixture_file_sha256="fixture-sha",
        )

    invalid = deepcopy(packet)
    invalid["cases"][0]["instance_groups"] = []
    with pytest.raises(ValueError, match="forbidden result fields"):
        validate_subagent_review_packet(
            fixture,
            invalid,
            expected_role=ANNOTATOR_ROLE,
            expected_fixture_file_sha256="fixture-sha",
        )


def test_subagent_proposal_rejects_ungrounded_evidence_id() -> None:
    proposal = _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left")
    proposal["cases"][0]["instance_groups"][0]["acceptable_evidence_ids"] = [
        "invented-evidence-id"
    ]
    with pytest.raises(ValueError, match="cannot assert Evidence IDs"):
        validate_subagent_proposal(
            _fixture(),
            proposal,
            expected_role=ANNOTATOR_ROLE,
            expected_identity="agent-a",
            expected_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
        )


def _orchestration_manifest() -> dict[str, object]:
    return {
        "schema_version": ORCHESTRATION_SCHEMA,
        "run_id": "run-b",
        "created_at": "2026-09-05T00:00:00Z",
        "created_before_execution": True,
        "status": "SEALED_BEFORE_SUBAGENT_EXECUTION",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "source_fixture": "fixture.json",
        "source_fixture_file_sha256": "fixture-sha",
        "source_fixture_semantic_sha256": canonical_sha256(_fixture()),
        "a0_trace": "trace.jsonl",
        "a0_trace_sha256": "trace-sha",
        "producers": {
            "annotator": {
                "role": ANNOTATOR_ROLE,
                "orchestrator_assigned_agent_id": "agent-a",
                "invocation_id": "invocation-a",
                "model_id": "test-model",
                "packet": "packet-a.json",
                "packet_sha256": f"packet-{ANNOTATOR_ROLE}",
                "expected_proposal": "proposal-a.json",
            },
            "reviewer": {
                "role": REVIEWER_ROLE,
                "orchestrator_assigned_agent_id": "agent-b",
                "invocation_id": "invocation-b",
                "model_id": "test-model",
                "packet": "packet-b.json",
                "packet_sha256": f"packet-{REVIEWER_ROLE}",
                "expected_proposal": "proposal-b.json",
            },
        },
        "isolation": {
            "peer_output_supplied": False,
            "proposal_output_supplied": False,
            "a0_trace_supplied": False,
            "treatment_output_supplied": False,
        },
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }


def test_subagent_orchestration_requires_preexecution_isolation() -> None:
    manifest = _orchestration_manifest()
    result = validate_subagent_orchestration_manifest(
        _fixture(),
        manifest,
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
        packet_sha256_by_role={
            ANNOTATOR_ROLE: f"packet-{ANNOTATOR_ROLE}",
            REVIEWER_ROLE: f"packet-{REVIEWER_ROLE}",
        },
    )
    assert result["status"] == "VALID_PREEXECUTION_SUBAGENT_ORCHESTRATION"

    invalid = deepcopy(manifest)
    invalid["isolation"]["peer_output_supplied"] = True
    with pytest.raises(ValueError, match="did not preserve isolation"):
        validate_subagent_orchestration_manifest(
            _fixture(),
            invalid,
            fixture_file_sha256="fixture-sha",
            a0_trace_sha256="trace-sha",
            packet_sha256_by_role={
                ANNOTATOR_ROLE: f"packet-{ANNOTATOR_ROLE}",
                REVIEWER_ROLE: f"packet-{REVIEWER_ROLE}",
            },
        )


def _chain_inputs() -> tuple[list[dict[str, object]], dict[str, object]]:
    result = _merge(
        _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left"),
        _proposal(role=REVIEWER_ROLE, identity="agent-b", group_suffix="right"),
    )
    rows = result.pop("adjudicated_rows")
    assert isinstance(rows, list)
    summary = {
        **result,
        "adjudicated_output": "var/product11/run-b/subagent-adjudicated.jsonl",
        "adjudicated_output_sha256": "adjudicated-sha",
        "annotator_packet_sha256": f"packet-{ANNOTATOR_ROLE}",
        "reviewer_packet_sha256": f"packet-{REVIEWER_ROLE}",
        "annotator_proposal_sha256": f"output-{ANNOTATOR_ROLE}",
        "reviewer_proposal_sha256": f"output-{REVIEWER_ROLE}",
    }
    return rows, summary


def _validate_chain(
    rows: list[dict[str, object]], summary: dict[str, object]
) -> dict[str, object]:
    return validate_subagent_merge_chain(
        _fixture(),
        rows,
        _traces(),
        summary,
        _proposal(role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left"),
        _proposal(role=REVIEWER_ROLE, identity="agent-b", group_suffix="right"),
        fixture_file_sha256="fixture-sha",
        a0_trace_sha256="trace-sha",
        adjudicated_sha256="adjudicated-sha",
        orchestration_manifest_sha256="manifest-sha",
        annotator_packet_sha256=f"packet-{ANNOTATOR_ROLE}",
        reviewer_packet_sha256=f"packet-{REVIEWER_ROLE}",
        annotator_proposal_sha256=f"output-{ANNOTATOR_ROLE}",
        reviewer_proposal_sha256=f"output-{REVIEWER_ROLE}",
    )


def test_subagent_seal_chain_rejects_bypass_and_tampering() -> None:
    rows, summary = _chain_inputs()
    assert _validate_chain(rows, summary)["status"] == "VALID_SUBAGENT_MERGE_CHAIN"

    wrong_hash = deepcopy(summary)
    wrong_hash["adjudicated_output_sha256"] = "wrong"
    with pytest.raises(ValueError, match="summary chain is invalid"):
        _validate_chain(rows, wrong_hash)

    conflict = deepcopy(summary)
    conflict["conflict_case_count"] = 1
    with pytest.raises(ValueError, match="summary chain is invalid"):
        _validate_chain(rows, conflict)

    altered_rows = deepcopy(rows)
    altered_rows[0]["producer_a"]["output_sha256"] = "tampered"
    with pytest.raises(ValueError, match="producer envelope drifted"):
        _validate_chain(altered_rows, summary)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_subagent_merge_and_seal_cli_enforce_artifact_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(merge_tool, "ROOT", tmp_path)
    monkeypatch.setattr(seal_tool, "ROOT", tmp_path)
    monkeypatch.setattr(
        seal_tool,
        "OUTPUT",
        tmp_path / "data/labels/product11-subagent-instance-groups-v0.2.jsonl",
    )
    fixture_path = tmp_path / "data/fixture.json"
    trace_path = tmp_path / "artifacts/a0-trace.jsonl"
    annotator_packet_path = tmp_path / "data/annotator-packet.json"
    reviewer_packet_path = tmp_path / "data/reviewer-packet.json"
    run_dir = tmp_path / "var/product11/run-cli"
    annotator_proposal_path = run_dir / "annotator-proposal.json"
    reviewer_proposal_path = run_dir / "reviewer-proposal.json"
    manifest_path = run_dir / "subagent-orchestration-manifest.json"
    fixture = _fixture()
    _write_json(fixture_path, fixture)
    _write_jsonl(trace_path, _traces())
    fixture_sha = _sha256(fixture_path)
    annotator_packet = build_subagent_review_packet(
        fixture,
        role=ANNOTATOR_ROLE,
        packet_id="packet-cli-a",
        fixture_file_sha256=fixture_sha,
    )
    reviewer_packet = build_subagent_review_packet(
        fixture,
        role=REVIEWER_ROLE,
        packet_id="packet-cli-b",
        fixture_file_sha256=fixture_sha,
    )
    _write_json(annotator_packet_path, annotator_packet)
    _write_json(reviewer_packet_path, reviewer_packet)
    annotator_proposal = _proposal(
        role=ANNOTATOR_ROLE, identity="agent-a", group_suffix="left"
    )
    reviewer_proposal = _proposal(
        role=REVIEWER_ROLE, identity="agent-b", group_suffix="right"
    )
    annotator_proposal["source_packet_sha256"] = _sha256(annotator_packet_path)
    reviewer_proposal["source_packet_sha256"] = _sha256(reviewer_packet_path)
    _write_json(annotator_proposal_path, annotator_proposal)
    _write_json(reviewer_proposal_path, reviewer_proposal)
    manifest = _orchestration_manifest()
    manifest["run_id"] = "run-cli"
    manifest["source_fixture"] = str(fixture_path.relative_to(tmp_path))
    manifest["source_fixture_file_sha256"] = fixture_sha
    manifest["a0_trace"] = str(trace_path.relative_to(tmp_path))
    manifest["a0_trace_sha256"] = _sha256(trace_path)
    manifest["producers"]["annotator"].update(
        {
            "packet": str(annotator_packet_path.relative_to(tmp_path)),
            "packet_sha256": _sha256(annotator_packet_path),
            "expected_proposal": str(annotator_proposal_path.relative_to(tmp_path)),
        }
    )
    manifest["producers"]["reviewer"].update(
        {
            "packet": str(reviewer_packet_path.relative_to(tmp_path)),
            "packet_sha256": _sha256(reviewer_packet_path),
            "expected_proposal": str(reviewer_proposal_path.relative_to(tmp_path)),
        }
    )
    _write_json(manifest_path, manifest)
    merged = merge_tool.run(orchestration_manifest=manifest_path)
    summary_path = run_dir / "subagent-merge-summary.json"

    for name, mutation, match in (
        (
            "wrong-hash",
            lambda value: value.update(adjudicated_output_sha256="wrong"),
            "summary chain is invalid",
        ),
        (
            "conflict",
            lambda value: value.update(conflict_case_count=1),
            "summary chain is invalid",
        ),
        (
            "altered-envelope",
            lambda value: value["producer_a"].update(output_sha256="wrong"),
            "producer envelope is invalid",
        ),
    ):
        invalid = deepcopy(merged)
        mutation(invalid)
        invalid_path = run_dir / f"{name}-summary.json"
        _write_json(invalid_path, invalid)
        with pytest.raises(ValueError, match=match):
            seal_tool.run(merge_summary=invalid_path, run_id=f"seal-{name}")

    handcrafted = deepcopy(merged)
    handcrafted_path = run_dir / "handcrafted.jsonl"
    handcrafted_rows = _load_jsonl_for_test(
        tmp_path / str(merged["adjudicated_output"])
    )
    handcrafted_rows[1]["instance_groups"][0]["acceptable_turn_refs"] = [
        "p11://case-00/t1"
    ]
    _write_jsonl(handcrafted_path, handcrafted_rows)
    handcrafted["adjudicated_output"] = str(handcrafted_path.relative_to(tmp_path))
    handcrafted["adjudicated_output_sha256"] = _sha256(handcrafted_path)
    handcrafted_summary_path = run_dir / "handcrafted-summary.json"
    _write_json(handcrafted_summary_path, handcrafted)
    with pytest.raises(ValueError, match="not produced by proposals"):
        seal_tool.run(
            merge_summary=handcrafted_summary_path, run_id="seal-handcrafted"
        )

    receipt = seal_tool.run(merge_summary=summary_path, run_id="seal-valid")
    assert receipt["artifact_chain_verified"] is True
    assert receipt["status"] == "PASS_PRODUCT11_X0_SUBAGENT_SEAL"


def _load_jsonl_for_test(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_prepare_subagent_workflow_seals_manifest_before_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_path = tmp_path / "data/fixture.json"
    trace_path = tmp_path / "artifacts/a0-trace.jsonl"
    annotator_packet_path = tmp_path / "data/annotator-packet.json"
    reviewer_packet_path = tmp_path / "data/reviewer-packet.json"
    _write_json(fixture_path, _fixture())
    _write_jsonl(trace_path, _traces())
    monkeypatch.setattr(prepare_tool, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_tool, "FIXTURE", fixture_path)
    monkeypatch.setattr(prepare_tool, "A0_TRACE", trace_path)
    monkeypatch.setattr(prepare_tool, "ANNOTATOR_PACKET", annotator_packet_path)
    monkeypatch.setattr(prepare_tool, "REVIEWER_PACKET", reviewer_packet_path)
    arguments = {
        "run_id": "prepare-run",
        "annotator_identity": "agent-a",
        "reviewer_identity": "agent-b",
        "annotator_invocation_id": "invocation-a",
        "reviewer_invocation_id": "invocation-b",
        "model_id": "test-model",
    }
    result = prepare_tool.run(**arguments)
    assert result["status"] == "SEALED_BEFORE_SUBAGENT_EXECUTION"
    with pytest.raises(RuntimeError, match="refusing to reuse a subagent run manifest"):
        prepare_tool.run(**arguments)
