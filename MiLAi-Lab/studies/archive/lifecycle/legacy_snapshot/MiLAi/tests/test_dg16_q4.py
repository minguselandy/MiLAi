from __future__ import annotations

import hashlib

from evals.dg14.benchmark import OPENED_DEV_INPUT_PATH, load_opened_dev
from evals.dg14.provider import ProviderResult
from evals.dg16.q4 import UNIT_KINDS, build_units, run_q4_ablation


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def answer(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        token_budget: int,
    ) -> ProviderResult:
        del run_id, question, question_as_of
        self.calls.append((case_id, method_id))
        digest = hashlib.sha256(memory_context.encode()).hexdigest()
        return ProviderResult(
            answer="UNKNOWN",
            answer_sha256=hashlib.sha256(b"UNKNOWN").hexdigest(),
            native_request_id=f"request-{digest[:12]}",
            logical_request_id=f"logical-{digest[:12]}",
            seed=1,
            cache_salt=digest,
            prompt_sha256=digest,
            prompt_tokens=token_budget,
            no_memory_prompt_tokens=100,
            memory_tokens=max(0, token_budget - 100),
            completion_tokens=1,
            finish_reason="stop",
            context=memory_context,
            context_truncated=False,
            tokenizer_calls=1,
            tokenize_latency_ms=0.1,
            provider_latency_ms=0.1,
        )


def test_q4_builds_four_distinct_label_free_evidence_units() -> None:
    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    case = cases[0]

    units = {kind: build_units(case, kind) for kind in UNIT_KINDS}

    assert all(units.values())
    assert all(item.kind == kind for kind, items in units.items() for item in items)
    assert all(item.turn_refs for items in units.values() for item in items)
    assert len(units["TURN_NEIGHBOR"]) == len(units["TURN"])
    assert len(units["EPISODE"]) == len(case.sessions)
    assert all(len(item.content.encode()) <= 1_600 for item in units["CHUNK"])


def test_q4_runs_twenty_matched_cells_and_keeps_controls_fixed() -> None:
    provider = _Provider()
    receipt = run_q4_ablation(
        run_id="q4-test",
        provider=provider,
        token_count=lambda text: len(text.split()),
    )

    assert receipt["status"] == "SUCCEEDED"
    assert receipt["case_count"] == 5
    assert receipt["cell_count"] == 20
    assert len(provider.calls) == 20
    assert set(receipt["summaries"]) == set(UNIT_KINDS)
    assert receipt["fixed_controls"]["candidate_cap"] == 3
    assert receipt["fixed_controls"]["token_budget"] == 2_048
    assert receipt["label_fields_available_to_product_path"] is False
    assert receipt["formal_holdout_consumed"] is False
    assert receipt["selection"]["production_default_frozen"] is False
