from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.gdpm.b0_canary_contract import (
    B0CanaryContractError,
    CanaryAuthorityReceipt,
    CanaryCaseMetadata,
    required_authority_delta,
)
from evals.gdpm.b0_canary_runner import (
    EXPECTED_METRICS,
    B0CanaryRunnerError,
    CanaryBatchResult,
    CanaryContextCell,
    CanarySelectionInputs,
    run_b0_context_only_canary,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
GOAL = ROOT / "MiLAi_GDPM-01_受治理双过程Memory分阶段开发与验证_GOALS.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter(values: dict[str, str]) -> str:
    return "\n".join(
        ["---", *(f"{key}: {value}" for key, value in values.items()), "---", ""]
    )


def _authority(tmp_path: Path) -> tuple[Path, Path]:
    delta = required_authority_delta()
    master = tmp_path / "master.md"
    goal = tmp_path / "goal.md"
    master.write_text(_frontmatter(delta["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(delta["goal"]), encoding="utf-8")
    return master, goal


def _selection() -> CanarySelectionInputs:
    metadata: list[CanaryCaseMetadata] = []
    for index in range(128):
        answerability = "ABSTENTION" if index == 0 else "ANSWERABLE"
        bucket = (
            "NONE"
            if answerability == "ABSTENTION"
            else ("ONE", "TWO", "THREE_TO_SIX")[(index - 1) % 3]
        )
        metadata.append(
            CanaryCaseMetadata(
                source_id=f"case-{index:03d}",
                gold_session_bucket=bucket,
                answerability=answerability,
                query_capability=("LOOKUP", "TEMPORAL", "MULTI_SESSION")[
                    index % 3
                ],
                context_size=("SHORT", "NEAR_BUDGET")[index % 2],
                relation_hard_negative=index in {2, 9},
            )
        )
    parent = tuple(item.source_id for item in metadata)
    population = (*parent, *(f"population-{index:03d}" for index in range(372)))
    parent_manifest = _manifest(parent, "parent")
    population_manifest = _manifest(population, "population")
    return CanarySelectionInputs(
        metadata_pool=tuple(metadata),
        parent_128_source_ids=parent,
        population_500_source_ids=population,
        parent_128_manifest=parent_manifest,
        population_500_manifest=population_manifest,
        required_query_capabilities=("LOOKUP", "TEMPORAL", "MULTI_SESSION"),
    )


def _manifest(source_ids: tuple[str, ...], schema: str) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": schema,
        "case_count": len(source_ids),
        "source_ids": list(source_ids),
    }
    return {
        **material,
        "manifest_digest": hashlib.sha256(
            json.dumps(
                material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }


def _trace() -> dict[str, object]:
    return {
        "raw_retrieval_trace": [],
        "admitted_evidence_trace": {"atomic_unit_truncation_count": 0},
        "reader_visible_trace": {"reader_call_count": 0},
        "reader_context": "synthetic context",
    }


def _run(
    tmp_path: Path,
    *,
    master: Path,
    goal: Path,
    executor=None,
    batch_executor=None,
    metadata_loader=lambda: _selection(),
    case_loader=None,
    **runner_overrides,
):
    tokenizer = tmp_path / "tokenizer.json"
    template = tmp_path / "chat-template.jinja"
    code = tmp_path / "code.py"
    tokenizer.write_text("tokenizer", encoding="utf-8")
    template.write_text("template", encoding="utf-8")
    code.write_text("code", encoding="utf-8")
    loader = case_loader or (lambda case_ids: {item: object() for item in case_ids})
    return run_b0_context_only_canary(
        run_id="synthetic-canary",
        output_root=tmp_path / "run",
        master_path=master,
        goal_path=goal,
        metadata_loader=metadata_loader,
        case_loader=loader,
        context_executor=executor,
        context_batch_executor=batch_executor,
        tokenizer_path=tokenizer,
        tokenizer_sha256=_sha256(tokenizer),
        chat_template_path=template,
        chat_template_sha256=_sha256(template),
        code_paths=(code,),
        **runner_overrides,
    )


def test_current_authority_refuses_before_any_loader_or_output(tmp_path: Path) -> None:
    calls: list[str] = []
    delta = required_authority_delta()
    delta["master"]["authorized_case_count"] = "0"
    master = tmp_path / "unauthorized-master.md"
    goal = tmp_path / "unauthorized-goal.md"
    master.write_text(_frontmatter(delta["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(delta["goal"]), encoding="utf-8")

    with pytest.raises(B0CanaryContractError, match="does not authorize"):
        _run(
            tmp_path,
            master=master,
            goal=goal,
            metadata_loader=lambda: calls.append("metadata"),
            case_loader=lambda _ids: calls.append("cases"),
            executor=lambda *_args: calls.append("execute"),
        )

    assert calls == []
    assert not (tmp_path / "run").exists()


def test_synthetic_24_case_canary_is_exactly_once_and_sealed(tmp_path: Path) -> None:
    master, goal = _authority(tmp_path)
    executed: list[tuple[str, int]] = []

    def executor(case_id: str, _case: object, budget: int) -> CanaryContextCell:
        executed.append((case_id, budget))
        return CanaryContextCell(
            case_id=case_id,
            status="PASS",
            metrics=EXPECTED_METRICS,
            trace=_trace(),
        )

    terminal = _run(tmp_path, master=master, goal=goal, executor=executor)
    results = json.loads((tmp_path / "run/results.json").read_text(encoding="utf-8"))

    assert terminal["status"] == (
        "PASS_B0_24_CONTEXT_ONLY_CANARY_READY_FOR_128"
    )
    assert len(executed) == len({case_id for case_id, _budget in executed}) == 24
    assert {budget for _case_id, budget in executed} == {4096}
    assert results["logical_attempt_count"] == 24
    assert set(results["per_case_attempt_counts"].values()) == {1}
    assert results["reader_calls"] == results["answer_calls"] == 0
    assert results["judge_calls"] == results["canonical_mutation_count"] == 0
    assert results["metrics"] == results["expected"]


def test_batch_executor_is_one_call_with_24_logical_attempts(tmp_path: Path) -> None:
    master, goal = _authority(tmp_path)
    invocations: list[tuple[int, int]] = []

    def batch(items, budget: int) -> CanaryBatchResult:
        invocations.append((len(items), budget))
        return CanaryBatchResult(
            cells=tuple(
                CanaryContextCell(
                    case_id=case_id,
                    status="PASS",
                    metrics=EXPECTED_METRICS,
                    trace=_trace(),
                )
                for case_id, _case in reversed(items)
            ),
            execution_receipt={"status": "PASS", "physical_shards": 4},
        )

    terminal = _run(
        tmp_path,
        master=master,
        goal=goal,
        batch_executor=batch,
    )
    results = json.loads((tmp_path / "run/results.json").read_text(encoding="utf-8"))

    assert terminal["status"] == "PASS_B0_24_CONTEXT_ONLY_CANARY_READY_FOR_128"
    assert invocations == [(24, 4096)]
    assert results["logical_attempt_count"] == 24
    assert results["execution_receipt"] == {"physical_shards": 4, "status": "PASS"}


def test_successor_scope_freezes_8192_budget_and_terminal_names(
    tmp_path: Path,
) -> None:
    master, goal = _authority(tmp_path)
    invocations: list[tuple[int, int]] = []

    def validator(**_paths) -> CanaryAuthorityReceipt:
        return CanaryAuthorityReceipt(
            master_sha256="a" * 64,
            goal_sha256="b" * 64,
            scope="MVP01_U0_24_CASE_CONTEXT_ONLY_CANARY",
        )

    def batch(items, budget: int) -> CanaryBatchResult:
        invocations.append((len(items), budget))
        return CanaryBatchResult(
            cells=tuple(
                CanaryContextCell(
                    case_id=case_id,
                    status="PASS",
                    metrics=EXPECTED_METRICS,
                    trace=_trace(),
                )
                for case_id, _case in items
            ),
            execution_receipt={"status": "PASS"},
        )

    terminal = _run(
        tmp_path,
        master=master,
        goal=goal,
        batch_executor=batch,
        authority_validator=validator,
        evidence_token_budget=8192,
        scope_identity="MVP01_U0_24_CASE_CONTEXT_ONLY_CANARY",
        execution_plan={"mode": "SYNTHETIC", "evidence_token_budget": 8192},
        pass_terminal_status="PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY",
        fail_terminal_status="FAIL_MVP01_U0_24_CONTEXT_ONLY_CANARY",
        pass_next_scope="U0_100_REQUEST_WARM_RELIABILITY_SOAK",
        fail_next_scope="U0_24_CASE_CONTEXT_ONLY_CANARY_REPAIR",
    )
    run_lock = json.loads((tmp_path / "run/run-lock.json").read_text())

    assert invocations == [(24, 8192)]
    assert terminal["status"] == "PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY"
    assert terminal["next_active_scope"] == "U0_100_REQUEST_WARM_RELIABILITY_SOAK"
    assert run_lock["scope"]["identity"] == (
        "MVP01_U0_24_CASE_CONTEXT_ONLY_CANARY"
    )
    assert run_lock["scope"]["evidence_token_budget"] == 8192
    assert run_lock["execution_plan"]["evidence_token_budget"] == 8192


def test_forbidden_reader_call_seals_failure_not_semantic_abstention(
    tmp_path: Path,
) -> None:
    master, goal = _authority(tmp_path)
    count = 0

    def executor(case_id: str, _case: object, _budget: int) -> CanaryContextCell:
        nonlocal count
        count += 1
        return CanaryContextCell(
            case_id=case_id,
            status="FAILED" if count == 1 else "PASS",
            metrics=EXPECTED_METRICS,
            trace=_trace(),
            reader_calls=1 if count == 1 else 0,
            failure_class="PROTOCOL_IMPLEMENTATION" if count == 1 else None,
            semantic_abstention=False,
        )

    terminal = _run(tmp_path, master=master, goal=goal, executor=executor)
    results = json.loads((tmp_path / "run/results.json").read_text(encoding="utf-8"))

    assert terminal["status"] == "FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED"
    assert terminal["reader_answer_judge_calls"] == 1
    assert results["failure_class_counts"] == {"PROTOCOL_IMPLEMENTATION": 1}
    assert any(
        "FORBIDDEN_MODEL_CALL" in violations
        for violations in results["violations"].values()
    )


def test_timeout_is_sealed_as_infrastructure_not_semantic_abstention(
    tmp_path: Path,
) -> None:
    master, goal = _authority(tmp_path)
    count = 0

    def executor(case_id: str, _case: object, _budget: int) -> CanaryContextCell:
        nonlocal count
        count += 1
        if count == 1:
            raise TimeoutError("synthetic context timeout")
        return CanaryContextCell(
            case_id=case_id,
            status="PASS",
            metrics=EXPECTED_METRICS,
            trace=_trace(),
        )

    terminal = _run(tmp_path, master=master, goal=goal, executor=executor)
    results = json.loads((tmp_path / "run/results.json").read_text(encoding="utf-8"))
    traces = json.loads(
        (tmp_path / "run/trace-bundle/contexts.json").read_text(encoding="utf-8")
    )

    assert terminal["status"] == "FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED"
    assert results["logical_attempt_count"] == 24
    assert results["failure_class_counts"] == {"INFRASTRUCTURE": 1}
    assert results["metrics"]["SystemFailureAsSemanticAbstention"] == 0
    failed = next(item for item in traces["cells"] if item["status"] == "FAILED")
    assert failed["failure_class"] == "INFRASTRUCTURE"
    assert failed["semantic_abstention"] is False


def test_case_loader_set_drift_fails_before_output(tmp_path: Path) -> None:
    master, goal = _authority(tmp_path)

    with pytest.raises(B0CanaryRunnerError, match="different 24-case set"):
        _run(
            tmp_path,
            master=master,
            goal=goal,
            executor=lambda *_args: None,
            case_loader=lambda case_ids: {item: object() for item in case_ids[:-1]},
        )

    assert not (tmp_path / "run").exists()
