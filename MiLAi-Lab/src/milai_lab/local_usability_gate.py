from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return float(ordered[rank])


@dataclass(frozen=True, slots=True)
class LocalUsabilityMetrics:
    golden_flow: bool
    scenario_count: int
    scenario_success_count: int
    warm_request_count: int
    typed_terminal_count: int
    read_after_write_p95_ms: float
    retrieval_context_p95_ms: float
    warm_control_p95_ms: float
    model_outage_fallback_rate: float
    governance_leak_count: int
    canonical_read_mutation_count: int
    baseline_restore: bool

    @property
    def task_success_rate(self) -> float:
        return self.scenario_success_count / self.scenario_count

    @property
    def typed_terminal_rate(self) -> float:
        return self.typed_terminal_count / self.warm_request_count

    def exit_checks(self) -> dict[str, bool]:
        return {
            "GoldenFlow": self.golden_flow,
            "ProductTaskSuccess": self.scenario_count == 24 and self.task_success_rate >= 0.90,
            "WarmTypedTerminalRate": self.warm_request_count == 100
            and self.typed_terminal_rate == 1.0,
            "ReadAfterWriteSearchableP95": self.read_after_write_p95_ms <= 5_000,
            "RetrievalContextP95": self.retrieval_context_p95_ms <= 2_000,
            "WarmMemoryControlP95": self.warm_control_p95_ms <= 500,
            "ModelOutageDeterministicFallback": self.model_outage_fallback_rate == 1.0,
            "GovernanceLeak": self.governance_leak_count == 0,
            "CanonicalReadMutation": self.canonical_read_mutation_count == 0,
            "OneFlagRestoresBaseline": self.baseline_restore,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "golden_flow": self.golden_flow,
            "scenario_count": self.scenario_count,
            "scenario_success_count": self.scenario_success_count,
            "product_task_success_rate": self.task_success_rate,
            "warm_request_count": self.warm_request_count,
            "typed_terminal_count": self.typed_terminal_count,
            "typed_terminal_rate": self.typed_terminal_rate,
            "read_after_write_searchable_p95_ms": self.read_after_write_p95_ms,
            "retrieval_context_p95_ms": self.retrieval_context_p95_ms,
            "warm_memory_control_p95_ms": self.warm_control_p95_ms,
            "model_outage_deterministic_fallback_rate": self.model_outage_fallback_rate,
            "governance_leak_count": self.governance_leak_count,
            "canonical_read_mutation_count": self.canonical_read_mutation_count,
            "one_flag_restores_baseline": self.baseline_restore,
            "exit_checks": self.exit_checks(),
        }


def typed_terminal(response: Mapping[str, Any]) -> bool:
    status = response.get("status")
    if isinstance(status, str) and status:
        return True
    abstained = response.get("abstained")
    return isinstance(abstained, bool)
