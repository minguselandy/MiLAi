from __future__ import annotations

from evals.dg16.q6 import evaluate_release_gate, score_product_records
from scripts.run_dg16_q6 import _wait_all_lane_cleanup


class _ReadinessTransport:
    def __init__(self, timeout_status: str = "TIMEOUT") -> None:
        self.calls: list[dict[str, object]] = []
        self.timeout_status = timeout_status

    def call(
        self, profile: str, tool: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert profile == "reader-detail"
        assert tool == "milai_projection_readiness_wait"
        self.calls.append(arguments)
        return {
            "status": self.timeout_status if len(self.calls) == 1 else "READY",
            "projections": [],
        }


def _product_records() -> list[dict[str, object]]:
    return [
        {
            "case_id": case_id,
            "token_budget": budget,
            "answer": answer,
            "selected_source_refs": [f"{case_id}:source"],
            "derived_source_turn_refs": [],
        }
        for case_id, answer in (
            ("a", "one"),
            ("b", "two"),
            ("c", "three"),
            ("d", "four"),
            ("e", "five"),
        )
        for budget in (512, 2048)
    ]


def test_score_product_records_and_release_gate() -> None:
    fixture = {
        "cases": [
            {
                "case_id": case_id,
                "answers": [answer],
                "required_atoms": [{"source_turn_ref": f"{case_id}:source"}],
            }
            for case_id, answer in (
                ("a", "one"),
                ("b", "two"),
                ("c", "three"),
                ("d", "four"),
                ("e", "five"),
            )
        ]
    }
    baseline = [
        {
            "case_id": case_id,
            "token_budget": budget,
            "method_id": "DG14-MILAI-MCP",
            "answer_score": {"exact_match": int(case_id in {"a", "b", "c"})},
        }
        for case_id in ("a", "b", "c", "d", "e")
        for budget in (512, 2048)
    ]
    scored = score_product_records(_product_records(), fixture, baseline)
    assert scored["summaries"]["2048"]["exact_match_count"] == 5
    assert scored["summaries"]["2048"]["exact_match_delta_count"] == 2
    assert scored["summaries"]["2048"]["evidence_atom_recall"] == 1.0

    names = {
        "canonical_promotion",
        "cross_case_contamination",
        "label_leakage",
        "permission_denied_bypass",
        "silent_fallback",
        "stale_revoked_evidence_acceptance",
        "wrong_scope_acceptance",
    }
    safety = {name: {"accepted": 0, "denominator": 1} for name in names}
    assert evaluate_release_gate(scored["summaries"], safety)["status"] == "PASS"


def test_cleanup_readiness_uses_bounded_api_calls_without_query_retry() -> None:
    transport = _ReadinessTransport()

    result = _wait_all_lane_cleanup(  # type: ignore[arg-type]
        transport,
        target_outbox_id="purge-target",
        total_timeout_ms=60_000,
    )

    assert result["status"] == "READY"
    assert [call["timeout_ms"] for call in transport.calls] == [15_000, 15_000]
    assert result["bounded_wait"] == {
        "total_timeout_ms": 60_000,
        "per_call_timeout_max_ms": 15_000,
        "calls": [
            {"call": 1, "timeout_ms": 15_000, "status": "TIMEOUT"},
            {"call": 2, "timeout_ms": 15_000, "status": "READY"},
        ],
    }


def test_cleanup_readiness_continues_on_runtime_timeout_status() -> None:
    transport = _ReadinessTransport("PROJECTION_READINESS_TIMEOUT")

    result = _wait_all_lane_cleanup(  # type: ignore[arg-type]
        transport,
        target_outbox_id="purge-target",
        total_timeout_ms=60_000,
    )

    assert result["status"] == "READY"
    assert [call["timeout_ms"] for call in transport.calls] == [15_000, 15_000]
