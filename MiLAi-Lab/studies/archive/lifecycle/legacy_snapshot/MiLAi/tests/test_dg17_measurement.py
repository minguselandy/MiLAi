from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from evals.dg14.provider import ProviderResult
from evals.dg17.measurement import (
    ORACLE_ARMS,
    build_oracle_contexts,
    build_q0_receipt,
    load_answer_bearing_labels,
    run_oracle_ladder,
)

ROOT = Path(__file__).resolve().parents[1]


def test_q0_cli_bootstraps_runtime_source_path() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ""
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_dg17_q0.py"), "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--oracle" in completed.stdout


def test_q0_labels_replay_exact_turn_atom_slot_and_join_boundaries() -> None:
    envelope, cases, labels = load_answer_bearing_labels()

    assert envelope["classification"].endswith("EVALUATION_PLANE")
    assert len(cases) == len(labels) == 10
    assert sum(len(case["atoms"]) for case in labels.values()) == 23
    assert sum(len(case["required_slots"]) for case in labels.values()) == 16
    assert sum(len(case["join_relations"]) for case in labels.values()) == 9
    assert all("answer" not in case for case in labels.values())


def test_q0_renames_session_metric_and_exposes_atom_operator_boundary_metrics() -> None:
    receipt = build_q0_receipt()
    serialized = json.dumps(receipt, sort_keys=True)

    assert "evidence_recall" not in serialized.casefold()
    assert receipt["aggregate"] == {
        "case_count": 10,
        "answer_session_coverage": 0.6,
        "answer_bearing_turn_recall": 0.475,
        "required_evidence_set_coverage": 0.347826087,
        "operator_execution_accuracy": None,
        "context_boundary_loss_rate": 0.333333333,
        "operator_execution_denominator": 0,
        "context_boundary_denominator": 12,
    }
    assert set(receipt["by_query_class"]) == {
        "AGGREGATION",
        "EPISODIC",
        "PREFERENCE",
        "TEMPORAL",
    }


def test_q0_typed_stage_trace_localizes_session_and_boundary_failures() -> None:
    metrics = {item["case_id"]: item for item in build_q0_receipt()["metrics"]}

    missed = metrics["gpt4_8279ba03"]
    assert missed["answer_session_coverage"] == 0.0
    assert missed["primary_failure_stage"] == "ACQUISITION"
    assert [stage["stage"] for stage in missed["stage_trace"]] == [
        "ACQUISITION",
        "QUERY_COMPILER_OPERATOR",
        "CONTEXT_COMPILER",
        "READER",
    ]

    boundary = metrics["4dfccbf7"]
    assert boundary["answer_session_coverage"] == 1.0
    assert boundary["required_evidence_set_coverage"] == 0.5
    assert boundary["context_boundary_loss_rate"] == 0.5
    assert boundary["primary_failure_stage"] == "CONTEXT_BOUNDARY"


def test_q0_oracle_matrix_crosses_evidence_and_ir_without_product_labels() -> None:
    _envelope, cases, labels = load_answer_bearing_labels()
    case = next(item for item in cases if item.case_id == "2a1811e2")
    contexts = build_oracle_contexts(case, labels[case.case_id], "ACTUAL")

    assert tuple(contexts) == ORACLE_ARMS
    assert "Holi celebration" in contexts["A_GOLD_EVIDENCE_GOLD_IR"]
    assert "ACTUAL" in contexts["B_ACTUAL_EVIDENCE_GOLD_IR"]
    assert "TEMPORAL_DISTANCE" in contexts["A_GOLD_EVIDENCE_GOLD_IR"]
    assert '"schema_version":"memory-query-ir-v0.2"' in contexts[
        "C_GOLD_EVIDENCE_PREDICTED_IR"
    ]
    assert '"operator":null' not in contexts["C_GOLD_EVIDENCE_PREDICTED_IR"]
    assert "Holi celebration" not in contexts[
        "D_ACTUAL_EVIDENCE_PREDICTED_IR"
    ]


class _UnknownProvider:
    def __init__(self) -> None:
        self.calls = 0

    def answer(self, **kwargs: Any) -> ProviderResult:
        self.calls += 1
        context = str(kwargs["memory_context"])
        return ProviderResult(
            answer="UNKNOWN",
            answer_sha256="unknown",
            native_request_id=f"native-{self.calls:03d}",
            logical_request_id=f"logical-{self.calls:03d}",
            seed=17,
            cache_salt="salt",
            prompt_sha256="prompt",
            prompt_tokens=100,
            no_memory_prompt_tokens=20,
            memory_tokens=80,
            completion_tokens=1,
            finish_reason="stop",
            context=context,
            context_truncated=False,
            tokenizer_calls=1,
            tokenize_latency_ms=1.0,
            provider_latency_ms=2.0,
        )


def test_q0_oracle_runner_has_fixed_40_cell_denominator_and_typed_diagnosis() -> None:
    provider = _UnknownProvider()
    receipt = run_oracle_ladder(
        build_q0_receipt(),
        provider=provider,
        token_count=lambda _case, _context: 100,
        run_id="dg17-q0-unit",
    )

    assert provider.calls == 40
    assert receipt["status"] == "Q0_CHARACTERIZED"
    assert receipt["oracle_ladder"]["single_run_causal_claim_authorized"] is False
    assert len(receipt["oracle_ladder"]["results"]) == 10
    assert all(
        item["diagnosis"] == "READER_CEILING_OR_TASK_AMBIGUITY"
        for item in receipt["oracle_ladder"]["results"]
    )
