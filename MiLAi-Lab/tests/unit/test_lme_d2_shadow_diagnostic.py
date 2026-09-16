from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

LAB = Path(__file__).resolve().parents[2]
TOOLS = LAB / "tools"


def _module() -> ModuleType:
    path = TOOLS / "run_lme_d2_shadow_diagnostic.py"
    spec = importlib.util.spec_from_file_location("lme_d2_shadow_diagnostic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(TOOLS))
    return module


def test_score_shadow_counts_only_exact_required_turn_refs() -> None:
    module = _module()
    raw = {
        "memory_context": {"selected_source_turn_refs": ["turn-a", "distractor"]},
        "intra_source_acquisition_shadow": {
            "mode": "SHADOW",
            "status": "COMPLETE",
            "candidates": [
                {
                    "source_ref": "turn-a",
                    "global_rank": 1,
                    "channel_ranks": {"FTS_INTRA_SOURCE": 1},
                    "already_in_coarse_pool": True,
                },
                {
                    "source_ref": "turn-b",
                    "source_type": "RUNTIME_OBSERVATION",
                    "session_id": "session-b",
                    "global_rank": 2,
                    "channel_ranks": {"FTS_INTRA_SOURCE": 1},
                    "already_in_coarse_pool": False,
                },
                {"source_ref": "other"},
            ],
        },
    }
    required = {
        "turn-a": {"session_ordinal": 1},
        "turn-b": {"session_ordinal": 2},
        "turn-c": {"session_ordinal": 3},
    }

    result = module._score_shadow(raw, required)

    assert result["public_required_turn_count"] == 1
    assert result["missing_required_turn_count"] == 2
    assert result["fine_required_turn_count"] == 2
    assert result["recovered_missing_required_turn_count"] == 1
    assert result["all_missing_required_turns_fine_acquired"] is False
    recovered = next(
        row
        for row in result["required_turn_visibility"]
        if row["turn_ref"] == "turn-b"
    )
    assert recovered["d2_global_rank"] == 2
    assert recovered["d2_channel_rank"] == 1
    assert recovered["already_in_coarse_pool"] is False
    assert recovered["d2_novel_source_rank"] == 1
    assert recovered["d2_position_among_per_source_first_novel"] == 1
    assert recovered["simulated_policy_selected"] is True
    assert recovered["simulated_policy_cumulative_visible"] is True
    assert result["selection_diagnostics"] == {
        "source_with_novel_candidate_count": 1,
        "per_source_first_novel_candidate_count": 1,
        "missing_turns_covered_by_per_source_novel_cap_1": 1,
        "all_missing_turns_covered_by_per_source_novel_cap_1": False,
        "simulated_policy": {
            "name": "FIRST_NOVEL_PER_SOURCE_THEN_GLOBAL_CAP",
            "cap": 20,
            "selected_candidate_count": 1,
            "selected_required_turn_count": 1,
            "cumulative_required_turn_count": 2,
            "recovered_missing_required_turn_count": 1,
            "lost_public_required_turn_count": 0,
            "all_missing_required_turns_recovered": False,
        },
    }


def test_simulated_policy_is_non_destructive_and_globally_capped() -> None:
    module = _module()
    candidates = [
        {
            "source_ref": f"turn-{index}",
            "source_type": "RUNTIME_OBSERVATION",
            "session_id": f"session-{index}",
            "global_rank": index,
            "already_in_coarse_pool": False,
        }
        for index in range(1, 23)
    ]
    raw = {
        "memory_context": {"selected_source_turn_refs": ["already-public"]},
        "intra_source_acquisition_shadow": {
            "mode": "SHADOW",
            "status": "COMPLETE",
            "candidates": candidates,
        },
    }
    required = {
        "already-public": {},
        "turn-20": {},
        "turn-21": {},
    }

    result = module._score_shadow(raw, required)
    policy = result["selection_diagnostics"]["simulated_policy"]

    assert policy["selected_candidate_count"] == 20
    assert policy["cumulative_required_turn_count"] == 2
    assert policy["recovered_missing_required_turn_count"] == 1
    assert policy["lost_public_required_turn_count"] == 0


def test_wait_projection_batches_large_lme_sessions() -> None:
    module = _module()
    observed: list[list[str]] = []
    module.p09._wait_projection = lambda _environment, ids: observed.append(ids)

    module._wait_projection_batched({}, [str(index) for index in range(1025)])

    assert [len(batch) for batch in observed] == [512, 512, 1]


def test_aggregate_excludes_zero_required_abstention_from_macro_denominator() -> None:
    module = _module()
    policy = {
        "cumulative_required_turn_count": 0,
        "recovered_missing_required_turn_count": 0,
        "lost_public_required_turn_count": 0,
        "all_missing_required_turns_recovered": True,
    }
    aggregate = module._aggregate_results(
        [
            {
                "required_turn_count": 1,
                "public_required_turn_count": 1,
                "fine_required_turn_count": 1,
                "missing_required_turn_count": 0,
                "selection_diagnostics": {
                    "simulated_policy": {**policy, "cumulative_required_turn_count": 1}
                },
            },
            {
                "required_turn_count": 0,
                "public_required_turn_count": 0,
                "fine_required_turn_count": 0,
                "missing_required_turn_count": 0,
                "selection_diagnostics": {"simulated_policy": policy},
            },
        ]
    )

    assert aggregate["case_count"] == 2
    assert aggregate["exact_turn_scorable_case_count"] == 1
    assert aggregate["zero_required_turn_case_count"] == 1
    assert aggregate["public_macro_coverage"] == 1.0
