from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_quality_gates(
    *,
    current_v1: Mapping[str, Any],
    legacy_v1: Mapping[str, Any],
    current_categories: Mapping[str, Mapping[str, Any]],
    legacy_categories: Mapping[str, Mapping[str, Any]],
    lexical_categories: Mapping[str, Mapping[str, Any]],
    mean_memory_tokens: float,
    safety_pass: bool,
) -> dict[str, bool]:
    f1_delta = round(
        float(current_v1["normalized_f1_mean"])
        - float(legacy_v1["normalized_f1_mean"]),
        6,
    )
    em_delta = round(
        float(current_v1["exact_match_mean"]) - float(legacy_v1["exact_match_mean"]),
        6,
    )
    multi_delta = round(
        float(current_categories["multi-session"]["normalized_f1_mean"])
        - float(legacy_categories["multi-session"]["normalized_f1_mean"]),
        6,
    )
    assistant_delta = round(
        float(current_categories["single-session-assistant"]["normalized_f1_mean"])
        - float(lexical_categories["single-session-assistant"]["normalized_f1_mean"]),
        6,
    )
    knowledge_delta = round(
        float(current_categories["knowledge-update"]["normalized_f1_mean"])
        - float(legacy_categories["knowledge-update"]["normalized_f1_mean"]),
        6,
    )
    return {
        "f1_vs_legacy_gte_plus_0_05": f1_delta >= 0.05,
        "em_vs_legacy_gte_zero": em_delta >= 0,
        "multi_session_vs_legacy_gte_zero": multi_delta >= 0,
        "single_assistant_vs_custom_lexical_gte_zero": assistant_delta >= 0,
        "knowledge_update_regression_gte_minus_0_02": knowledge_delta >= -0.02,
        "mean_memory_tokens_lte_320": mean_memory_tokens <= 320,
        "safety_regressions_zero": safety_pass,
    }
