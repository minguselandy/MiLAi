from __future__ import annotations

import json

from evals.gdpm.b0_canary_contract import freeze_canary_manifest
from evals.gdpm.b0_canary_longmemeval import (
    PROTECTED_MANIFESTS,
    QUERY_CAPABILITIES,
    load_runtime_cases,
    load_selection_inputs,
)


def test_real_hierarchy_is_deterministic_nested_and_protected() -> None:
    first = load_selection_inputs()
    second = load_selection_inputs()

    assert first == second
    assert len(first.metadata_pool) == len(first.parent_128_source_ids) == 128
    assert len(first.population_500_source_ids) == 500
    assert set(first.parent_128_source_ids) < set(first.population_500_source_ids)
    protected = {
        source_id
        for receipt in first.parent_128_manifest["protected_partitions"]
        for source_id in json.loads(
            PROTECTED_MANIFESTS[
                0 if str(PROTECTED_MANIFESTS[0]) == receipt["path"] else 1
            ].read_text(encoding="utf-8")
        )["source_ids"]
    }
    assert set(first.parent_128_source_ids).isdisjoint(protected)
    assert first.required_query_capabilities == QUERY_CAPABILITIES

    canary = freeze_canary_manifest(
        cases=first.metadata_pool,
        parent_128_source_ids=first.parent_128_source_ids,
        population_500_source_ids=first.population_500_source_ids,
        parent_128_manifest=first.parent_128_manifest,
        population_500_manifest=first.population_500_manifest,
        required_query_capabilities=first.required_query_capabilities,
    )
    assert canary["case_count"] == 24
    assert set(QUERY_CAPABILITIES) == set(canary["coverage"]["query_capability"])
    assert canary["coverage"]["relation_hard_negative_count"] >= 1


def test_runtime_loader_exposes_only_label_free_case_view() -> None:
    selection = load_selection_inputs()
    canary = freeze_canary_manifest(
        cases=selection.metadata_pool,
        parent_128_source_ids=selection.parent_128_source_ids,
        population_500_source_ids=selection.population_500_source_ids,
        parent_128_manifest=selection.parent_128_manifest,
        population_500_manifest=selection.population_500_manifest,
        required_query_capabilities=selection.required_query_capabilities,
    )
    case_ids = tuple(item["source_id"] for item in canary["cases"])
    cases = load_runtime_cases(case_ids)

    assert set(cases) == set(case_ids)
    assert all(case.history_events for case in cases.values())
    assert all(
        event.case_id == case.case_id
        for case in cases.values()
        for event in case.history_events
    )
    assert not any(
        hasattr(case, field)
        for case in cases.values()
        for field in ("answer", "answers", "answer_session_ids", "gold_session_ids")
    )
