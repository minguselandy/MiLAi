from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from evals.paper.answer_runner import AnswerCompletion, PreparedAnswer
from evals.paper.contracts import ContextRecord, write_context_archive
from evals.paper.dg12_v3.annotations import AnnotationError, build_consensus
from evals.paper.dg12_v3.dg12_contexts import _select_shard
from evals.paper.dg12_v3.freeze import (
    FreezeError,
    require_formal_execution_ready,
    require_paper_v3_ready,
)
from evals.paper.dg12_v3.plan import build_lme_plan
from evals.paper.dg12_v3.runner import (
    FormalRunnerError,
    RetainingAnswerRunner,
    load_complete_context_denominator,
)
from evals.paper.dg12_v3.schedule import (
    EXPECTED_MATRICES,
    FrozenSchedule,
    ScheduleError,
)
from evals.paper.parallelism import STATELESS_CONTEXT_LANE
from evals.paper.runners.contriever_contexts import _select_shard as select_dense_shard
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / "var/dg12/freeze/schedules/latin-square.yaml"
LME_HOLDOUT = ROOT / "var/dg11/paper/freeze/longmemeval-holdout-inputs.json"


def test_frozen_schedule_uses_exact_dg12_rows() -> None:
    schedule = FrozenSchedule.load(SCHEDULE)
    assert schedule.namespace == "milai-dg12-paper-v2"
    for matrix, methods in EXPECTED_MATRICES.items():
        assert len(schedule.matrices[matrix]) == len(methods)
        assert set(schedule.order(matrix, 0)) == set(methods)
        assert schedule.order(matrix, len(methods)) == schedule.order(matrix, 0)


def test_schedule_rejects_namespace_drift(tmp_path: Path) -> None:
    value = json.loads(SCHEDULE.read_text())
    value["generator"]["namespace"] = "milai-dg11-paper-v1"
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ScheduleError, match="namespace"):
        FrozenSchedule.load(path)


def test_lme_plan_has_all_eleven_controlled_methods_for_every_case() -> None:
    plan = build_lme_plan(input_path=LME_HOLDOUT, schedule_path=SCHEDULE)
    assert plan["case_count"] == 100
    assert plan["method_count"] == 11
    assert plan["cell_count"] == 1100
    assert plan["paper_labels_opened"] is False
    assert plan["formal_method_outputs_generated"] is False
    pairs = {(row["case_id"], row["method_id"]) for row in plan["cells"]}
    assert len(pairs) == 1100


def test_native_plan_is_explicit_and_separate() -> None:
    plan = build_lme_plan(
        input_path=LME_HOLDOUT,
        schedule_path=SCHEDULE,
        matrices=("NATIVE_SHARED_CONTEXT",),
    )
    assert plan["method_count"] == 7
    assert plan["cell_count"] == 700
    assert plan["matrices"] == ["NATIVE_SHARED_CONTEXT"]


def _row(case_id: str, status: str) -> dict[str, object]:
    return {
        "benchmark": "LongMemEval",
        "partition": "LME-PAPER-HOLDOUT-100",
        "case_id": case_id,
        "screening_status": status,
        "operator": None,
        "unit": None,
        "required_operands": [],
        "latest_required_operand_id": None,
        "unrelated_numeric_distractor": None,
    }


def test_consensus_never_promotes_one_sided_eligibility() -> None:
    rows_a = tuple(
        _row(f"c-{index}", "ELIGIBLE" if index == 0 else "INELIGIBLE")
        for index in range(500)
    )
    rows_b = tuple(
        _row(f"c-{index}", "AMBIGUOUS" if index == 0 else "INELIGIBLE")
        for index in range(500)
    )
    report, rows = build_consensus(rows_a, rows_b)  # type: ignore[arg-type]
    assert rows[0]["consensus_status"] == "DISAGREEMENT_OR_AMBIGUOUS"
    assert report["prevalence_gate_pass"] is False
    assert report["status"] == "FAIL_PREVALENCE_CLAIM_UNSUPPORTED"


def test_consensus_rejects_wrong_denominator() -> None:
    with pytest.raises(AnnotationError, match="500 by 2"):
        build_consensus((), ())


def test_context_denominator_retains_failure_but_rejects_missing_pair(
    tmp_path: Path,
) -> None:
    plan = {
        "schema": "milai.dg12.paper-lme-plan.v3",
        "status": "LABEL_FREE_PLAN_COMPLETE",
        "cells": [
            {"case_id": "case-1", "method_id": "CTRL-NONE"},
            {"case_id": "case-1", "method_id": "CTRL-FULL"},
        ],
    }
    archive = tmp_path / "contexts.json"
    write_context_archive(
        archive,
        run_id="run",
        benchmark_id="partition",
        records=(
            ContextRecord("case-1", "CTRL-NONE", "CONTROLLED", "", (), (), 0, 0.0, {}),
            ContextRecord(
                "case-1",
                "CTRL-FULL",
                "LONG_CONTEXT_CHARACTERIZATION",
                "",
                (),
                (),
                0,
                0.0,
                {"failure": "CONTEXT_LIMIT_EXCEEDED"},
                terminal_status="CAPABILITY_UNSUPPORTED",
            ),
        ),
    )
    loaded = load_complete_context_denominator(plan=plan, context_archives=(archive,))
    assert loaded[("case-1", "CTRL-FULL")].terminal_status == "CAPABILITY_UNSUPPORTED"
    incomplete = dict(plan)
    incomplete["cells"] = [
        *plan["cells"],
        {"case_id": "case-1", "method_id": "LME-DENSE"},
    ]
    with pytest.raises(FormalRunnerError, match="denominator drifted"):
        load_complete_context_denominator(plan=incomplete, context_archives=(archive,))


def test_answer_runner_retains_provider_failure_without_retry(tmp_path: Path) -> None:
    prepared = (
        PreparedAnswer(0, "req-1", "case-1", "A", "prompt-a", 3, 2),
        PreparedAnswer(1, "req-2", "case-1", "B", "prompt-b", 3, 2),
    )
    calls: list[str] = []

    def answer(item: PreparedAnswer) -> AnswerCompletion:
        calls.append(item.logical_request_id)
        if item.logical_request_id == "req-2":
            raise RuntimeError("retained failure")
        return AnswerCompletion("ok", "native-1", 3, 1, "stop")

    runner = RetainingAnswerRunner(
        UsageLedger(tmp_path / "usage.jsonl"), max_workers=1, max_memory_tokens=512
    )
    first = runner.execute(prepared, answer)
    second = runner.execute(prepared, answer)
    assert [record["status"] for record in first] == ["SUCCEEDED", "FAILED"]
    assert second == first
    assert calls == ["req-1", "req-2"]


def test_answer_runner_executes_eight_provider_calls_concurrently(
    tmp_path: Path,
) -> None:
    prepared = tuple(
        PreparedAnswer(index, f"req-{index}", f"case-{index}", "A", "p", 1, 0)
        for index in range(8)
    )
    barrier = threading.Barrier(8, timeout=5)
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def answer(item: PreparedAnswer) -> AnswerCompletion:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        barrier.wait()
        with lock:
            active -= 1
        return AnswerCompletion("ok", f"native-{item.ordinal}", 1, 1, "stop")

    runner = RetainingAnswerRunner(
        UsageLedger(tmp_path / "usage.jsonl"), max_workers=8, max_memory_tokens=512
    )
    records = runner.execute(prepared, answer)
    assert len(records) == 8
    assert maximum_active == 8


def test_dg12_context_process_shards_are_disjoint_and_complete() -> None:
    cases = tuple(range(17))
    shards = tuple(_select_shard(cases, index=index, count=4) for index in range(4))
    assert sorted(item for shard in shards for item in shard) == list(cases)
    assert not any(
        set(left).intersection(right)
        for left in shards
        for right in shards
        if left is not right
    )


def test_dense_context_process_shards_are_disjoint_and_complete() -> None:
    cases = tuple(range(17))
    shards = tuple(
        select_dense_shard(cases, index=index, count=2) for index in range(2)
    )
    assert sorted(item for shard in shards for item in shard) == list(cases)
    assert not set(shards[0]).intersection(shards[1])


def test_parallelism_lane_rejects_post_freeze_worker_increase() -> None:
    assert STATELESS_CONTEXT_LANE.validate(8, frozen_ceiling=8) == 8
    with pytest.raises(ValueError, match="between 1 and 8"):
        STATELESS_CONTEXT_LANE.validate(9, frozen_ceiling=8)


def test_v3_freeze_verifier_is_one_way_and_hash_bound(tmp_path: Path) -> None:
    bound = tmp_path / "bound.json"
    bound.write_text("{}\n")
    import hashlib

    digest = hashlib.sha256(bound.read_bytes()).hexdigest()
    manifest = {
        "schema": "milai.dg12.paper-freeze-manifest.v3",
        "status": "PAPER_PROTOCOL_V3_FROZEN",
        "paper_labels_opened_at_freeze": False,
        "formal_scores_opened_at_freeze": False,
        "formal_method_outputs_generated_at_freeze": False,
        "candidate_modified": False,
        "training_performed": False,
        "frozen_files": [{"path": "bound.json", "sha256": digest}],
        "execution": {
            "answer_workers_max": 8,
            "answer_tokenizer_sha256": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
            "dense_context_processes_max": 2,
            "judge_workers_max": 8,
            "longmemeval_formal_matrix": "LME_CONTROLLED",
            "longmemeval_method_count": 11,
            "longmemeval_methods": [
                "CTRL-NONE",
                "CTRL-FULL",
                "CTRL-TRUNC-FULL",
                "CTRL-CUSTOM-LEX1",
                "LME-BM25-S",
                "LME-BM25-T",
                "LME-DENSE",
                "DG10-FROZEN",
                "DG11-FULL",
                "DG12-BATCH",
                "LME-ORACLE",
            ],
            "label_dataset_sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
            "method_specific_dynamic_concurrency": False,
            "parallelism_fixed_before_labels": True,
            "prompt_build_workers_max": 8,
            "schedule_namespace": "milai-dg12-paper-v2",
            "stateful_context_processes_max": 4,
            "stateful_context_workers_per_process": 1,
            "stateless_context_workers_max": 8,
            "retain_all_method_case_terminals": True,
        },
        "annotation": {
            "annotator_count": 2,
            "method_outputs_visible": False,
            "formal_labels_visible": False,
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert (
        require_paper_v3_ready(path, workspace_root=tmp_path)["status"]
        == "PAPER_PROTOCOL_V3_FROZEN"
    )
    with pytest.raises(FreezeError, match="authorization is absent"):
        require_formal_execution_ready(path, None, workspace_root=tmp_path)
    terminals = []
    for gate in ("DG12-PE01V3", "DG12-PE02V3"):
        terminal = tmp_path / f"{gate}.json"
        terminal.write_text('{"status":"PASS"}\n')
        terminals.append(
            {
                "gate": gate,
                "path": terminal.name,
                "sha256": hashlib.sha256(terminal.read_bytes()).hexdigest(),
            }
        )
    authorization = tmp_path / "authorization.json"
    authorization.write_text(
        json.dumps(
            {
                "schema": "milai.dg12.formal-execution-authorization.v3",
                "status": "PE01_PE02_NO_LABEL_GATES_PASS",
                "paper_labels_opened_at_authorization": False,
                "formal_method_outputs_generated_at_authorization": False,
                "freeze_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "gate_terminals": terminals,
            }
        )
    )
    assert (
        require_formal_execution_ready(path, authorization, workspace_root=tmp_path)[
            "status"
        ]
        == "PE01_PE02_NO_LABEL_GATES_PASS"
    )
    bound.write_text("drift\n")
    with pytest.raises(FreezeError, match="drifted"):
        require_paper_v3_ready(path, workspace_root=tmp_path)
