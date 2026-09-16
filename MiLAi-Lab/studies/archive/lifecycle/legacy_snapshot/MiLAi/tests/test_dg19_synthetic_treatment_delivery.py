from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from milai.application.semantic_hint import SemanticHintCompletion
from milai.domain.residual_refinding import ResidualCueProposal

from evals.dg19 import synthetic_treatment_delivery as treatment
from scripts import run_dg18_r3_shadow as r3_runner
from scripts import run_dg19_synthetic_treatment_shadow as dg19_runner


class _FakeProvider:
    def __init__(self, mode: str = "fixture") -> None:
        self.mode = mode
        self.calls = 0

    def complete_structured(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        schema_name: str,
        schema: Mapping[str, Any],
        max_completion_tokens: int,
        seed: int,
    ) -> SemanticHintCompletion:
        del schema_name, schema, max_completion_tokens, seed
        self.calls += 1
        observation = json.loads(messages[-1]["content"])
        requirement_id = observation["missing_requirements"][0]["requirement_id"]
        if self.mode == "invalid":
            proposal: dict[str, Any] = {}
        elif self.mode == "unknown-requirement":
            proposal = {
                "requirement_id": "NOT_A_MISSING_REQUIREMENT",
                "action": "NO_ACTION",
                "cues": [],
            }
        else:
            proposal = _fixture_proposal(observation, requirement_id)
        return SemanticHintCompletion(
            content=json.dumps(proposal, separators=(",", ":")),
            provider="fake-structured-provider",
            model="fake-dg19-controller",
            prompt_tokens=100,
            completion_tokens=20,
            tokenizer_latency_ms=0.5,
            queue_ms=1.0,
            ttft_ms=2.0,
            decode_ms=3.0,
            total_ms=6.0,
            provider_calls=1,
            automatic_retry_count=0,
        )


def _fixture_proposal(
    observation: Mapping[str, Any], requirement_id: str
) -> dict[str, Any]:
    question = str(observation["question_excerpt"]).casefold()
    snippets = " ".join(
        str(value["bounded_snippet"]) for value in observation["candidate_summaries"]
    ).casefold()
    if "approved april" in question:
        return {
            "requirement_id": requirement_id,
            "action": "SEARCH_TEMPORAL",
            "cues": [],
        }
    if "immediately following" in snippets:
        return {
            "requirement_id": requirement_id,
            "action": "EXPAND_NEIGHBORS",
            "cues": [],
        }
    if "no additional acquisition clue" in snippets:
        return {
            "requirement_id": requirement_id,
            "action": "NO_ACTION",
            "cues": [],
        }
    for phrase in ("cobalt ledger", "ochre index", "vermilion register"):
        if phrase in snippets:
            return {
                "requirement_id": requirement_id,
                "action": "SEARCH_LEXICAL",
                "cues": [phrase],
            }
    raise AssertionError("fake provider received an unknown fixture observation")


def _product(provider: _FakeProvider | None = None) -> dict[str, Any]:
    return treatment.run_product_shadow(
        run_id="dg19-focused-test",
        provider=provider or _FakeProvider(),
        provider_runtime_identity={
            "verified": True,
            "base_url": "synthetic://fake",
            "configured_model": "fake-dg19-controller",
        },
    )


def _score(tmp_path: Path, product: Mapping[str, Any]) -> dict[str, Any]:
    sealed = tmp_path / "sealed.json"
    treatment.seal_product_shadow(product, sealed)
    return treatment.score_sealed_shadow(sealed)


def test_fixture_freeze_and_product_scorer_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = json.loads(treatment.DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    scorer = json.loads(treatment.DEFAULT_SCORER_FIXTURE.read_text(encoding="utf-8"))
    cases = treatment.load_product_cases()
    actions = {value["expected_action_family"] for value in scorer["cases"]}

    assert fixture["classification"] == (
        "SYNTHETIC_ONLY / NO_REAL_USER_DATA / NO_FORMAL_HOLDOUT"
    )
    assert len(cases) == 6
    assert scorer["classification"] == (
        "SYNTHETIC_SCORER_ONLY / OPEN_AFTER_PRODUCT_SEAL"
    )
    assert actions == {
        "SEARCH_LEXICAL",
        "SEARCH_TEMPORAL",
        "EXPAND_NEIGHBORS",
        "NO_ACTION",
    }
    assert all("scorer" not in case for case in cases)
    assert "expected_answer_bearing_source_refs" not in json.dumps(fixture)

    def forbidden_scorer_loader(
        _path: Path = treatment.DEFAULT_SCORER_FIXTURE,
    ) -> Any:
        raise AssertionError("scorer truth reached product execution")

    monkeypatch.setattr(treatment, "load_scorer_truth", forbidden_scorer_loader)
    product = _product()
    assert product["product_path_scorer_access_count"] == 0
    assert product["labels_loaded"] is False
    assert product["scorer_fields_available"] is False


def test_flat_wire_contract_forbids_provider_control_fields() -> None:
    proposal = ResidualCueProposal.model_validate(
        {
            "requirement_id": "TARGET_EVENT",
            "action": "SEARCH_LEXICAL",
            "cues": ["cobalt ledger"],
        }
    )
    assert set(proposal.model_dump()) == {"requirement_id", "action", "cues"}
    with pytest.raises(ValueError):
        ResidualCueProposal.model_validate(
            {
                **proposal.model_dump(),
                "source_preference": "USER",
            }
        )


def test_real_runtime_chain_executes_one_call_one_pass_and_recomputes_binding(
    tmp_path: Path,
) -> None:
    provider = _FakeProvider()
    product = _product(provider)
    score = _score(tmp_path, product)
    by_case = {row["case_id"]: row for row in product["rows"]}

    assert provider.calls == 6
    assert score["status"] == "PASS_SYNTHETIC_TREATMENT_DELIVERY"
    assert score["summary"]["schema_valid_hint_count"] == 6
    assert score["summary"]["runtime_accepted_hint_count"] == 5
    assert score["summary"]["additional_acquisition_pass_count"] == 5
    assert score["summary"]["new_governed_candidate_count"] == 4
    assert score["summary"]["synthetic_missing_requirement_improved_cases"] == 4
    assert score["summary"]["expected_source_hits_after"] == 4

    lexical = by_case["syn-lexical-bridge-01"]
    receipt = lexical["controller"]["receipt"]
    additional = lexical["additional_acquisition"]
    assert receipt["action"] == "SEARCH_LEXICAL"
    assert receipt["cue_provenance"] == "OBSERVATION"
    assert receipt["rationale_code"] == "ENTITY_BRIDGE"
    assert additional["attempted"] is True
    assert additional["new_governed_candidate_count"] == 1
    assert additional["repeated_candidate_count"] == 1
    assert additional["state_transition"]["outcome"] == "APPLIED"
    assert additional["sufficiency_before"]["missing_slots"] == ["TARGET_EVENT"]
    assert additional["sufficiency_after"]["missing_slots"] == []
    assert additional["binding_after"]["matched_requirement_count"] == 1
    assert additional["action_digest"]
    assert additional["cue_digest"]
    assert additional["candidate_universe_digest"]
    assert additional["eligibility_outcomes"]

    temporal = by_case["syn-temporal-bound-03"]["controller"]["receipt"]
    assert temporal["action"] == "SEARCH_TEMPORAL"
    assert temporal["source_preference"] == "NO_CHANGE"
    assert temporal["lexical_cue_count"] == 0
    assert temporal["temporal_cue"] == {
        "axis": "SOURCE_OBSERVED_TIME",
        "start": "2026-04-01T00:00:00+00:00",
        "end": "2026-04-30T23:59:59+00:00",
    }


def test_no_action_is_safe_and_does_not_execute_an_extra_pass(tmp_path: Path) -> None:
    product = _product()
    score = _score(tmp_path, product)
    row = next(
        value for value in product["rows"] if value["case_id"] == "syn-safe-noop-05"
    )

    assert row["controller"]["schema_valid"] is True
    assert row["controller"]["runtime_status"] == "NO_ACTION"
    assert row["controller"]["runtime_accepted"] is False
    assert row["additional_acquisition"]["attempted"] is False
    assert row["additional_acquisition"]["new_candidate_count"] == 0
    assert score["hard_gate"]["passed"] is True


def test_wrong_scope_revoked_authority_and_model_control_are_rejected(
    tmp_path: Path,
) -> None:
    score = _score(tmp_path, _product())
    safety = score["summary"]["safety_metrics"]

    assert safety["WrongScopeAcceptance"] == {"count": 0, "denominator": 1}
    assert safety["RevokedEvidenceAcceptance"] == {"count": 0, "denominator": 1}
    assert safety["UnauthorizedAuthorityExpansion"] == {
        "count": 0,
        "denominator": 6,
    }
    assert safety["ModelSelectedFinalEvidence"] == {
        "count": 0,
        "denominator": 6,
    }
    assert safety["ModelDeclaredComplete"] == {"count": 0, "denominator": 6}


@pytest.mark.parametrize(
    ("mode", "schema_valid", "expected_status"),
    [
        ("invalid", False, "FAILED_PROVIDER_DELIVERY"),
        ("unknown-requirement", True, "FAILED_RUNTIME_ACCEPTANCE"),
    ],
)
def test_invalid_or_unknown_provider_output_never_executes_or_retries(
    tmp_path: Path,
    mode: str,
    schema_valid: bool,
    expected_status: str,
) -> None:
    provider = _FakeProvider(mode)
    product = _product(provider)
    score = _score(tmp_path, product)

    assert provider.calls == 6
    assert score["status"] == expected_status
    assert score["summary"]["automatic_retry_count"] == 0
    assert all(
        row["controller"]["schema_valid"] is schema_valid for row in product["rows"]
    )
    assert all(
        row["additional_acquisition"]["attempted"] is False for row in product["rows"]
    )
    assert all(row["product_result"]["changed"] is False for row in product["rows"])


def test_product_trace_contains_no_evidence_bodies_and_tamper_breaks_seal(
    tmp_path: Path,
) -> None:
    product = _product()
    serialized = json.dumps(product, ensure_ascii=False)
    assert "append-only storage" not in serialized
    assert "rotating the signing key" not in serialized
    sealed = tmp_path / "sealed.json"
    treatment.seal_product_shadow(product, sealed)
    envelope = json.loads(sealed.read_text(encoding="utf-8"))
    envelope["product_shadow"]["rows"][0]["case_id"] = "tampered"
    sealed.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(treatment.DG19SyntheticError, match="sealed product identity"):
        treatment.score_sealed_shadow(sealed)


def test_pass_receipt_is_accepted_by_existing_dg18_entry_gate(tmp_path: Path) -> None:
    product = _product()
    sealed = tmp_path / "sealed.json"
    treatment.seal_product_shadow(product, sealed)
    score = treatment.score_sealed_shadow(sealed)
    score_path = tmp_path / "score.json"
    score_path.write_text(json.dumps(score), encoding="utf-8")
    receipt = dg19_runner._build_receipt(
        run_id="dg19-receipt-compatibility",
        product=product,
        score=score,
        fixture_path=treatment.DEFAULT_FIXTURE,
        scorer_path=treatment.DEFAULT_SCORER_FIXTURE,
        sealed_path=sealed,
        score_path=score_path,
        failure_path=None,
        provider_gate={"status": "PASS_PROVIDER_CONFORMANCE"},
        provider_receipt_identity={"path": "synthetic", "sha256": "0" * 64},
        provider_runtime_identity={
            "verified": True,
            "base_url": "http://127.0.0.1:7860",
            "configured_model": "Qwen3.6-35B-A3B-FP8",
        },
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    accepted = r3_runner._validated_treatment_delivery(receipt_path)
    assert accepted["status"] == "PASS_SYNTHETIC_TREATMENT_DELIVERY"


def test_runner_binds_exact_conformance_hash_and_refuses_existing_output(
    tmp_path: Path,
) -> None:
    identity = dg19_runner._required_provider_receipt_identity(
        dg19_runner.DEFAULT_PROVIDER_RECEIPT
    )
    assert identity["sha256"] == dg19_runner.EXPECTED_PROVIDER_RECEIPT_SHA256
    altered = tmp_path / "altered.json"
    altered.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="receipt hash drifted"):
        dg19_runner._required_provider_receipt_identity(altered)

    output = tmp_path / "already-exists"
    output.mkdir()
    with pytest.raises(FileExistsError, match="fresh run ID"):
        dg19_runner.run(
            run_id="dg19-existing-output",
            output_root=output,
            fixture_path=treatment.DEFAULT_FIXTURE,
            scorer_path=treatment.DEFAULT_SCORER_FIXTURE,
            base_url="http://127.0.0.1:7860",
            model="Qwen3.6-35B-A3B-FP8",
            provider_conformance_receipt_path=dg19_runner.DEFAULT_PROVIDER_RECEIPT,
        )
