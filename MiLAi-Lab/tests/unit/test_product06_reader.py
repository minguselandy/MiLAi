from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]


def _runner_module():
    path = LAB / "tools/run_product05_openworker_lme.py"
    spec = importlib.util.spec_from_file_location("product06_openworker_lme", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_product06_selection_is_fixed_disjoint_and_outcome_blind() -> None:
    selection = json.loads(
        (LAB / "data/labels/product06-reader-selection.v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    product05 = json.loads(
        (LAB / "data/labels/product05-openworker-lme-selection.v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    labels = json.loads(
        (
            LAB
            / "data/labels/product02-longmemeval-answer-turns-qwen36-v4.json"
        ).read_text(encoding="utf-8")
    )

    validation = selection["tiers"]["V0"]
    confirmation = selection["tiers"]["R3"]
    cases = {row["case_id"]: row for row in selection["cases"]}
    product05_ids = {row["case_id"] for row in product05["cases"]}
    labels_by_id = {row["case_id"]: row for row in labels["cases"]}

    assert len(validation) == len(set(validation)) == 12
    assert len(confirmation) == len(set(confirmation)) == 24
    assert not set(validation) & set(confirmation)
    assert set(validation + confirmation) == set(cases)
    assert not set(cases) & product05_ids
    assert selection["formal_holdout_consumed"] is False
    assert "reference answer value" in selection["selection_excludes"]
    assert "Product-06 score or outcome" in selection["selection_excludes"]
    assert {cases[item]["capability_family"] for item in validation} == {
        "ORDINARY_USER_LOOKUP",
        "ASSISTANT_SOURCE_RECALL",
        "MULTI_SESSION_SET_COUNT",
        "COMPARISON_PERCENT_UNIT",
        "TEMPORAL_STATE_UPDATE",
        "INSUFFICIENT_ABSTENTION",
    }
    for case_id, metadata in cases.items():
        if "answer_turn_speakers" not in metadata:
            continue
        observed = sorted(
            {row["speaker"] for row in labels_by_id[case_id]["selections"]}
        )
        assert metadata["answer_turn_speakers"] == observed


def test_product06_reader_comparison_counts_safety_and_gain_metrics() -> None:
    module = _runner_module()

    def row(
        case_id: str,
        *,
        direct: bool,
        reader: bool,
        family: str,
        lookup: bool = False,
        abstention: bool = False,
        invalid_citations: int = 0,
        fallback: bool = False,
        tool: bool = False,
    ):
        return {
            "case_id": case_id,
            "metadata": {
                "capability_family": family,
                "ordinary_lookup": lookup,
                "abstention": abstention,
            },
            "arms": {
                "direct": {"correct": direct},
                "model-native": {
                    "correct": reader,
                    "trace": {
                        "reader_session_result": {
                            "fallback": fallback,
                            "invalid_citation_count": invalid_citations,
                            "tool_calls": ([{"tool": "calculator"}] if tool else []),
                            "provider_rounds": 2 if tool else 1,
                        }
                    },
                },
            },
        }

    rows = [
        row("gain-a", direct=False, reader=True, family="SET", tool=True),
        row("gain-b", direct=False, reader=True, family="TEMPORAL"),
        row("stable", direct=True, reader=True, family="LOOKUP", lookup=True),
        row(
            "unsupported",
            direct=False,
            reader=False,
            family="INSUFFICIENT",
            abstention=True,
            invalid_citations=1,
            fallback=True,
        ),
    ]

    comparison = module._comparison(rows, "model-native")

    assert comparison["additional_correct"] == 2
    assert comparison["net_correct_gain"] == 2
    assert comparison["gain_family_count"] == 2
    assert comparison["ordinary_lookup_correct_case_regressions"] == 0
    assert comparison["new_unsupported_answers"] == 1
    assert comparison["invalid_visible_citations"] == 1
    assert comparison["reader_fallbacks"] == 1
    assert comparison["calculator_answer_count"] == 1
    assert comparison["calculator_correct_answer_count"] == 1


def test_arm_cardinality_does_not_conflate_direct_passes_and_provider_calls() -> None:
    module = _runner_module()

    assert module._expected_arm_cardinality("direct", None) == (0, 1)
    assert module._expected_arm_cardinality("inventory", None) == (1, 1)
    assert module._expected_arm_cardinality("grounded", None) == (1, 1)
    assert module._expected_arm_cardinality("ledger", None) == (2, 2)
    assert module._expected_arm_cardinality(
        "model-native", {"provider_rounds": 1}
    ) == (1, 1)
    assert module._expected_arm_cardinality(
        "model-native", {"provider_rounds": 2}
    ) == (2, 2)
