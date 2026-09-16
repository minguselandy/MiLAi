from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return path


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": remediation.sha256_file(path),
    }


def _identity_document(
    root: Path, *, schema: str, candidate: str, evidence_path: Path
) -> dict[str, object]:
    evidence = [_ref(root, evidence_path)]
    return {
        "schema": schema,
        "candidate_id": candidate,
        "identity_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"evidence": evidence})
        ),
        "evidence": evidence,
    }


def _artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, list[Path]]:
    monkeypatch.setattr(authorization, "ROOT", tmp_path)
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    candidate = remediation.CANDIDATE

    policy = _write(
        tmp_path / "docs/contracts/DG-10-ai-audit-policy-override-candidate.4.json",
        {
            "candidate_id": candidate,
            "status": "USER_AUTHORIZED_POLICY_OVERRIDE_FROZEN",
        },
    )
    monkeypatch.setattr(authorization, "POLICY_OVERRIDE", policy)

    source_a = tmp_path / "scripts/a.py"
    source_b = tmp_path / "tests/test_a.py"
    source_a.parent.mkdir(parents=True)
    source_b.parent.mkdir(parents=True)
    source_a.write_text("VALUE = 1\n")
    source_b.write_text("def test_value():\n    assert True\n")
    inventory = remediation.canonical_inventory([source_a, source_b])
    inventory_path = _write(
        tmp_path / "docs/reports/source-inventory.json",
        {
            "schema": "milai.dg10.candidate-source-inventory.v1",
            "candidate_id": candidate,
            **inventory,
        },
    )

    environment_evidence = tmp_path / "evidence/environment.txt"
    model_evidence = tmp_path / "evidence/model.txt"
    environment_evidence.parent.mkdir(parents=True)
    environment_evidence.write_text("locked environment\n")
    model_evidence.write_text("frozen model\n")
    environment_path = _write(
        tmp_path / "docs/reports/environment.json",
        _identity_document(
            tmp_path,
            schema="milai.dg10.environment-identity.v1",
            candidate=candidate,
            evidence_path=environment_evidence,
        ),
    )
    model_path = _write(
        tmp_path / "docs/reports/model.json",
        _identity_document(
            tmp_path,
            schema="milai.dg10.model-identity.v1",
            candidate=candidate,
            evidence_path=model_evidence,
        ),
    )
    identity_path = _write(
        tmp_path / "docs/reports/authorization-identities.json",
        {
            "schema": "milai.dg10.authorization-identities.v1",
            "candidate_id": candidate,
            "source_inventory": _ref(tmp_path, inventory_path),
            "environment_identity": _ref(tmp_path, environment_path),
            "model_identity": _ref(tmp_path, model_path),
            "policy_override": _ref(tmp_path, policy),
        },
    )
    monkeypatch.setattr(authorization, "ACTIVE_IDENTITIES", identity_path)

    identities = authorization._verify_identity_receipt(identity_path)
    audit_evidence = tmp_path / "docs/reviews/ai-audit.json"
    _write(audit_evidence, {"status": "PASS", "open_p0": 0, "open_p1": 0})
    stages: list[Path] = []
    for stage in authorization.REQUIRED_POST_R3_STAGES:
        stages.append(
            _write(
                tmp_path / f"docs/reports/{stage}.json",
                {
                    "schema": "milai.dg10.stage-receipt.v1",
                    "candidate_id": candidate,
                    "stage_id": stage,
                    "stage_state": "ACCEPTED",
                    "evidence_class": "AI_INDEPENDENT",
                    "independent_acceptance": True,
                    "source_inventory_sha256": identities["source_inventory_sha256"],
                    "environment_identity_sha256": identities["environment_identity_sha256"],
                    "model_identity_sha256": identities["model_identity_sha256"],
                    "policy_override_sha256": identities["policy_override"]["sha256"],
                    "open_p0": 0,
                    "open_p1": 0,
                    "evidence": [_ref(tmp_path, audit_evidence)],
                },
            )
        )
    aggregate = _write(tmp_path / "docs/reviews/r0-r2-aggregate.json", {"status": "IMPORTED"})
    monkeypatch.setattr(authorization, "R0_R2_AGGREGATE", aggregate)

    def verify_aggregate(path: Path, bound: dict[str, object]) -> dict[str, object]:
        assert path.resolve() == aggregate.resolve()
        return {
            "receipt": _ref(tmp_path, aggregate),
            "stage_receipts": [
                authorization._verify_stage_receipt(
                    stage,
                    expected_stage=expected,
                    identities=bound,
                )
                for stage, expected in zip(
                    stages[:3], authorization.REQUIRED_BOOTSTRAP_STAGES, strict=True
                )
            ],
            "primary_audits": [],
        }

    monkeypatch.setattr(authorization, "_verify_r0_r2_aggregate", verify_aggregate)
    return aggregate, identity_path, source_a, stages


def test_bootstrap_authorization_is_recomputed_from_bound_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, identity_path, _source, _stages = _artifacts(tmp_path, monkeypatch)
    result = authorization.evaluate_first_model_authorization(
        phase=authorization.BOOTSTRAP_PHASE,
        planned_model_calls=24,
        r0_r2_aggregate_path=aggregate,
        identity_receipt_path=identity_path,
        test_access_requested=False,
    )
    assert result["authorized"] is True
    assert result["required_stages"] == ["DG10-R0", "DG10-R1", "DG10-R2"]
    authorization.require_first_model_authorization(result)


def test_hand_constructed_success_mapping_cannot_authorize() -> None:
    with pytest.raises(authorization.AuthorizationError, match="key set"):
        authorization.require_first_model_authorization(
            {
                "schema": "milai.dg10.model-authorization.v2",
                "candidate_id": remediation.CANDIDATE,
                "authorized": True,
                "reason_codes": [],
            }
        )


def test_tampered_source_after_authorization_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, identity_path, source, _stages = _artifacts(tmp_path, monkeypatch)
    result = authorization.evaluate_first_model_authorization(
        phase=authorization.BOOTSTRAP_PHASE,
        planned_model_calls=24,
        r0_r2_aggregate_path=aggregate,
        identity_receipt_path=identity_path,
        test_access_requested=False,
    )
    source.write_text("VALUE = 2\n")
    with pytest.raises(authorization.AuthorizationError, match="hash drift"):
        authorization.require_first_model_authorization(result)


def test_bootstrap_denominator_test_access_and_post_r3_receipt_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, identity_path, _source, _stages = _artifacts(tmp_path, monkeypatch)
    bootstrap = authorization.evaluate_first_model_authorization(
        phase=authorization.BOOTSTRAP_PHASE,
        planned_model_calls=23,
        r0_r2_aggregate_path=aggregate,
        identity_receipt_path=identity_path,
        test_access_requested=True,
    )
    assert bootstrap["authorized"] is False
    assert set(bootstrap["reason_codes"]) == {
        "BOOTSTRAP_CALL_DENOMINATOR_DRIFT",
        "TEST_ACCESS_FORBIDDEN_DURING_MODEL_AUTHORIZATION",
    }

    post_r3 = authorization.evaluate_first_model_authorization(
        phase=authorization.POST_R3_PHASE,
        planned_model_calls=1,
        r0_r2_aggregate_path=aggregate,
        post_r3_stage_receipt_path=None,
        identity_receipt_path=identity_path,
        test_access_requested=False,
    )
    assert post_r3["authorized"] is False
    assert post_r3["reason_codes"] == ["REQUIRED_R3_STAGE_RECEIPT_ABSENT"]


def test_post_r3_rejects_caller_minted_accepted_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _aggregate, identity_path, _source, stages = _artifacts(tmp_path, monkeypatch)
    identities = authorization._verify_identity_receipt(identity_path)

    with pytest.raises(
        authorization.AuthorizationError,
        match="fixed R3 AI importer output",
    ):
        authorization._verify_stage_receipt(
            stages[3],
            expected_stage="DG10-R3",
            identities=identities,
        )
