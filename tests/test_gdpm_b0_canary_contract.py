from __future__ import annotations

from pathlib import Path

import pytest

from evals.gdpm.b0_canary_contract import (
    B0CanaryContractError,
    CanaryCaseMetadata,
    authorize_then_load,
    freeze_canary_manifest,
    required_authority_delta,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
GOAL = ROOT / "MiLAi_GDPM-01_受治理双过程Memory分阶段开发与验证_GOALS.md"


def _frontmatter(values: dict[str, str]) -> str:
    lines = ["---", *(f"{key}: {value}" for key, value in values.items()), "---", ""]
    return "\n".join(lines)


def _authorized_documents(tmp_path: Path) -> tuple[Path, Path]:
    delta = required_authority_delta()
    master = tmp_path / "master.md"
    goal = tmp_path / "goal.md"
    master.write_text(_frontmatter(delta["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(delta["goal"]), encoding="utf-8")
    return master, goal


def _synthetic_pool() -> tuple[CanaryCaseMetadata, ...]:
    rows: list[CanaryCaseMetadata] = []
    for index in range(128):
        answerability = "ABSTENTION" if index == 0 else "ANSWERABLE"
        bucket = (
            "NONE"
            if answerability == "ABSTENTION"
            else ("ONE", "TWO", "THREE_TO_SIX")[(index - 1) % 3]
        )
        rows.append(
            CanaryCaseMetadata.from_mapping(
                {
                    "source_id": f"opaque-{index:02d}",
                    "gold_session_bucket": bucket,
                    "answerability": answerability,
                    "query_capability": ("LOOKUP", "TEMPORAL", "MULTI_SESSION")[
                        index % 3
                    ],
                    "context_size": ("SHORT", "NEAR_BUDGET")[index % 2],
                    "relation_hard_negative": index in {3, 11},
                }
            )
        )
    return tuple(rows)


def _manifest(source_ids: tuple[str, ...], schema: str) -> dict[str, object]:
    import hashlib
    import json

    material: dict[str, object] = {
        "schema_version": schema,
        "case_count": len(source_ids),
        "source_ids": list(source_ids),
    }
    digest = hashlib.sha256(
        json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return {**material, "manifest_digest": digest}


def test_handed_off_current_authority_refuses_before_loader() -> None:
    called = False

    def loader() -> object:
        nonlocal called
        called = True
        return object()

    with pytest.raises(B0CanaryContractError, match="does not authorize"):
        authorize_then_load(master_path=MASTER, goal_path=GOAL, loader=loader)

    assert called is False


def test_exact_future_authority_allows_loader_and_preserves_zero_call_scope(
    tmp_path: Path,
) -> None:
    master, goal = _authorized_documents(tmp_path)
    calls = 0

    def loader() -> str:
        nonlocal calls
        calls += 1
        return "metadata"

    receipt, value = authorize_then_load(
        master_path=master,
        goal_path=goal,
        loader=loader,
    )

    assert value == "metadata"
    assert calls == 1
    assert receipt.case_count == 24
    assert receipt.reader_answer_judge_calls == 0
    assert receipt.formal_holdout_consumed is False


def test_near_miss_authority_cannot_enable_reader_or_128_cases(tmp_path: Path) -> None:
    delta = required_authority_delta()
    delta["master"]["authorized_case_count"] = "128"
    delta["goal"]["reader_answer_judge_calls_authorized"] = "true"
    master = tmp_path / "master.md"
    goal = tmp_path / "goal.md"
    master.write_text(_frontmatter(delta["master"]), encoding="utf-8")
    goal.write_text(_frontmatter(delta["goal"]), encoding="utf-8")

    with pytest.raises(B0CanaryContractError, match="does not authorize"):
        authorize_then_load(
            master_path=master,
            goal_path=goal,
            loader=lambda: None,
        )


def test_selection_metadata_rejects_outcome_and_gold_content_fields() -> None:
    row = {
        "source_id": "opaque",
        "gold_session_bucket": "ONE",
        "answerability": "ANSWERABLE",
        "query_capability": "LOOKUP",
        "context_size": "SHORT",
        "relation_hard_negative": False,
        "system_correct": True,
        "gold_session_ids": ["forbidden"],
    }

    with pytest.raises(B0CanaryContractError, match="forbidden"):
        CanaryCaseMetadata.from_mapping(row)


def test_manifest_is_24_in_128_in_500_and_permutation_invariant() -> None:
    cases = _synthetic_pool()
    parent = tuple(item.source_id for item in cases)
    population = (*parent, *(f"population-{i}" for i in range(372)))
    first = freeze_canary_manifest(
        cases=cases,
        parent_128_source_ids=parent,
        population_500_source_ids=population,
        parent_128_manifest=_manifest(parent, "parent"),
        population_500_manifest=_manifest(population, "population"),
        required_query_capabilities=("LOOKUP", "TEMPORAL", "MULTI_SESSION"),
    )
    reversed_input = freeze_canary_manifest(
        cases=tuple(reversed(cases)),
        parent_128_source_ids=tuple(reversed(parent)),
        population_500_source_ids=tuple(reversed(population)),
        parent_128_manifest=_manifest(parent, "parent"),
        population_500_manifest=_manifest(population, "population"),
        required_query_capabilities=("LOOKUP", "TEMPORAL", "MULTI_SESSION"),
    )

    assert first == reversed_input
    assert first["case_count"] == 24
    assert first["nesting"]["parent_128_case_count"] == 128
    assert first["nesting"]["population_500_case_count"] == 500
    assert first["coverage"]["relation_hard_negative_count"] >= 1
    assert first["reader_answer_judge_calls_authorized"] is False


def test_manifest_rejects_missing_structural_stratum() -> None:
    cases = tuple(
        CanaryCaseMetadata(
            source_id=f"opaque-{index:02d}",
            gold_session_bucket="ONE",
            answerability="ANSWERABLE",
            query_capability=("LOOKUP", "TEMPORAL")[index % 2],
            context_size=("SHORT", "NEAR_BUDGET")[index % 2],
            relation_hard_negative=index == 0,
        )
        for index in range(128)
    )
    parent = tuple(item.source_id for item in cases)
    population = (*parent, *(f"population-{i}" for i in range(372)))

    with pytest.raises(B0CanaryContractError, match="cannot cover required strata"):
        freeze_canary_manifest(
            cases=cases,
            parent_128_source_ids=parent,
            population_500_source_ids=population,
            parent_128_manifest=_manifest(parent, "parent"),
            population_500_manifest=_manifest(population, "population"),
            required_query_capabilities=("LOOKUP", "TEMPORAL"),
        )
