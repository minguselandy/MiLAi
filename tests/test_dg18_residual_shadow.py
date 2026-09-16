from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from milai.application.semantic_hint import SemanticHintCompletion, SemanticHintError

from evals.dg18 import residual_shadow as shadow
from scripts import run_dg18_r3_shadow as r3_runner


class _FakeResidualProvider:
    def __init__(self, mode: str) -> None:
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
        if self.mode == "sse-error":
            raise SemanticHintError(
                "SEMANTIC_HINT_PROVIDER_SSE_ERROR",
                transport_mode="streaming",
                http_status=200,
                stream_finish_state="done",
                sse_error_type="InternalServerError",
                sse_error_code=500,
                completion_tokens=0,
                latency_ms=7.5,
            )
        if self.mode == "invalid":
            content = "{}"
        elif self.mode == "no-action":
            content = json.dumps(
                {
                    "requirement_id": requirement_id,
                    "action": "NO_ACTION",
                    "cues": [],
                }
            )
        else:
            content = json.dumps(
                {
                    "requirement_id": requirement_id,
                    "action": "SEARCH_LEXICAL",
                    "cues": [_observation_cue(observation)],
                }
            )
        return SemanticHintCompletion(
            content=content,
            provider="fake-structured-provider",
            model="fake-r3-controller",
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


def _observation_cue(observation: Mapping[str, Any]) -> str:
    for requirement in observation["missing_requirements"]:
        entities = requirement.get("known_entities", [])
        if entities:
            return str(entities[0])
    for candidate in observation["candidate_summaries"]:
        words = re.findall(r"[^\W_]+", str(candidate["bounded_snippet"]), re.UNICODE)
        uncommon = [value for value in words if len(value) >= 7]
        if uncommon:
            return str(uncommon[0])
    return "memory"


def _run(provider: _FakeResidualProvider, *, candidate_cap: int = 3) -> dict[str, Any]:
    return shadow.run_product_shadow(
        run_id=f"dg18-r3-test-{provider.mode}",
        q1r_archive_path=shadow.DEFAULT_Q1R_ARCHIVE,
        questions=shadow.opened_dev_questions(),
        provider=provider,
        candidate_cap=candidate_cap,
    )


def test_r3_product_phase_is_label_free_then_scorer_opens_labels_after_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_loader = shadow._load_scoring_labels

    def forbidden_loader(_path: Path) -> Any:
        raise AssertionError("evaluation labels reached the product phase")

    monkeypatch.setattr(shadow, "_load_scoring_labels", forbidden_loader)
    provider = _FakeResidualProvider("no-action")
    product = _run(provider)

    assert product["labels_loaded"] is False
    assert product["label_boundary"]["product_path_label_access_count"] == 0
    eligible = [row for row in product["rows"] if row["activation"]["eligible"]]
    assert provider.calls == len(eligible)
    assert provider.calls > 0

    complete = [
        row
        for row in product["rows"]
        if row["deterministic"]["sufficiency_status"] == "COMPLETE"
    ]
    assert complete
    assert all(row["controller"]["model_call_count"] == 0 for row in complete)

    sealed_path = tmp_path / "sealed.json"
    shadow.seal_product_shadow(product, sealed_path)
    monkeypatch.setattr(shadow, "_load_scoring_labels", original_loader)
    scored = shadow.score_sealed_shadow(sealed_path)

    assert scored["label_boundary"] == {
        "product_path_label_access_count": 0,
        "scorer_label_access_count": 1,
        "scoring_started_after_product_seal": True,
        "formal_holdout_consumed": False,
    }
    aggregate = scored["aggregate"]
    assert {
        "activation",
        "schema",
        "cue_provenance",
        "gold_turn_rank",
        "required_slot_candidate_recall",
        "required_evidence_coverage",
        "candidates",
        "binding",
        "operator_ready",
        "controller_latency_ms",
        "controller_tokens",
    }.issubset(aggregate)
    governance = scored["hard_gate"]["governance_negative_metrics"]
    assert set(governance) == {
        "WrongComplete",
        "WrongScopeAcceptance",
        "UnauthorizedAuthorityExpansion",
        "RevokedEvidenceAcceptance",
        "PermissionUnknownAcceptance",
        "CrossTenantCandidateAcceptance",
        "HiddenFallback",
        "ModelSelectedFinalEvidence",
        "ModelDeclaredComplete",
    }
    assert all(metric["denominator"] > 0 for metric in governance.values())
    assert all(metric["count"] == 0 for metric in governance.values())
    assert scored["treatment_delivery_outcome"] == "TREATMENT_NOT_DELIVERED"
    assert scored["residual_effect_outcome"] == "RESIDUAL_EFFECT_NOT_EVALUATED"
    assert scored["disposition"] == "PARKED_PROVIDER_CONTRACT_INCOMPATIBLE"
    manipulation = aggregate["manipulation_check"]
    assert manipulation["ProviderCallAttempted"]["count"] == provider.calls
    assert manipulation["ProviderSchemaAccepted"]["count"] == provider.calls
    assert manipulation["RuntimeAcceptedHintRate"]["numerator"] == 0
    assert manipulation["AdditionalAcquisitionPassExecuted"]["count"] == 0
    assert manipulation["TreatmentDelivered"] is False


def test_r3_product_phase_rejects_any_label_field(tmp_path: Path) -> None:
    archive = json.loads(shadow.DEFAULT_Q1R_ARCHIVE.read_text(encoding="utf-8"))
    archive["gold"] = {"forbidden": True}
    contaminated = tmp_path / "contaminated.json"
    contaminated.write_text(json.dumps(archive), encoding="utf-8")

    with pytest.raises(shadow.R3ShadowError, match="label field reached"):
        shadow.run_product_shadow(
            run_id="dg18-r3-label-boundary",
            q1r_archive_path=contaminated,
            questions=shadow.opened_dev_questions(),
            provider=_FakeResidualProvider("no-action"),
        )


def test_full_r3_lme_requires_conformance_and_synthetic_treatment_gate(
    tmp_path: Path,
) -> None:
    provider_receipt = (
        shadow.ROOT
        / "var/dg18/provider-conformance/dg18-provider-conformance-20260828-002/receipt.json"
    )
    validated = r3_runner._validated_provider_conformance(
        provider_receipt,
        base_url="http://127.0.0.1:7860",
        model="Qwen3.6-35B-A3B-FP8",
    )
    assert validated["status"] == "PASS_PROVIDER_CONFORMANCE"

    missing_treatment = tmp_path / "missing-treatment.json"
    missing_treatment.write_text(
        json.dumps(
            {
                "schema": "milai.dg18.synthetic-treatment-delivery-receipt.v0.1",
                "status": "TREATMENT_NOT_DELIVERED",
                "formal_holdout_consumed": False,
                "summary": {
                    "schema_valid_hint_count": 0,
                    "runtime_accepted_hint_count": 0,
                    "additional_acquisition_pass_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="treatment-delivery entry gate"):
        r3_runner._validated_treatment_delivery(missing_treatment)


def test_r3_invalid_schema_has_zero_retry_and_cannot_change_product_result() -> None:
    provider = _FakeResidualProvider("invalid")
    product = _run(provider)
    eligible = [row for row in product["rows"] if row["activation"]["eligible"]]

    assert provider.calls == len(eligible)
    assert all(row["controller"]["schema_valid"] is False for row in eligible)
    assert all(row["controller"]["automatic_retry_count"] == 0 for row in eligible)
    assert all(
        re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", row["controller"]["error"])
        for row in eligible
    )
    assert all(row["product_result"]["changed"] is False for row in product["rows"])
    assert all(
        row["offline_simulation"]["attempted"] is False for row in eligible
    )


def test_r3_scorer_separates_valid_treatment_without_mediator_gain(
    tmp_path: Path,
) -> None:
    product = _run(_FakeResidualProvider("lexical"))
    sealed_path = tmp_path / "valid-treatment.json"
    shadow.seal_product_shadow(product, sealed_path)

    scored = shadow.score_sealed_shadow(sealed_path)

    manipulation = scored["aggregate"]["manipulation_check"]
    assert manipulation["SchemaValidHintRate"]["rate"] == 1.0
    assert manipulation["RuntimeAcceptedHintRate"]["rate"] == 1.0
    assert manipulation["AdditionalAcquisitionPassExecuted"]["count"] > 0
    assert manipulation["NewGovernedCandidateCount"] > 0
    assert manipulation["TreatmentDelivered"] is True
    assert scored["treatment_delivery_outcome"] == "VALID_TREATMENT_DELIVERED"
    assert (
        scored["residual_effect_outcome"]
        == "MEDIATOR_GAIN_NOT_OBSERVED_AFTER_VALID_TREATMENT"
    )
    assert scored["disposition"] == "PARKED_NO_MEDIATOR_GAIN"


def test_r3_scorer_records_typed_sse_error_as_treatment_not_delivered(
    tmp_path: Path,
) -> None:
    product = _run(_FakeResidualProvider("sse-error"))
    sealed_path = tmp_path / "sse-error.json"
    shadow.seal_product_shadow(product, sealed_path)

    scored = shadow.score_sealed_shadow(sealed_path)

    manipulation = scored["aggregate"]["manipulation_check"]
    assert manipulation["ProviderTransportMode"] == {"streaming": 3}
    assert manipulation["ProviderSSEErrorObserved"] == {"count": 3, "denominator": 3}
    assert manipulation["ProviderErrorClassificationCorrect"] == {
        "count": 3,
        "denominator": 3,
    }
    assert manipulation["SchemaValidHintRate"]["numerator"] == 0
    assert manipulation["TreatmentDelivered"] is False
    assert scored["disposition"] == "PARKED_PROVIDER_CONTRACT_INCOMPATIBLE"


def test_r3_offline_candidate_simulation_is_capped_and_deduplicated() -> None:
    cap = 2
    provider = _FakeResidualProvider("lexical")
    product = _run(provider, candidate_cap=cap)
    simulated = [
        row["offline_simulation"]
        for row in product["rows"]
        if row["offline_simulation"]["attempted"]
    ]

    assert simulated
    for result in simulated:
        new_refs = result["new_candidate_refs"]
        baseline_refs = result["combined_candidate_refs"][: -len(new_refs) or None]
        assert len(new_refs) <= cap
        assert len(new_refs) == len(set(new_refs))
        assert set(new_refs).isdisjoint(baseline_refs)
        assert result["combined_candidate_count"] == len(
            set(result["combined_candidate_refs"])
        )
        assert result["wrong_scope_candidate_count"] == 0
        assert result["product_result_changed"] is False
        assert result["state_transition"]["outcome"] == "APPLIED"

    for row in product["rows"]:
        receipt = row["controller"]["receipt"]
        if receipt is not None:
            serialized = json.dumps(receipt, sort_keys=True)
            assert "hint" not in receipt
            assert "lexical_cues" not in serialized
            assert "bounded_snippet" not in serialized
