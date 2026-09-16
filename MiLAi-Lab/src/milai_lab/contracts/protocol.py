from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricContract:
    metric_id: str
    direction: str
    scorer_id: str


@dataclass(frozen=True, slots=True)
class EvaluationProtocol:
    protocol_id: str
    split_id: str
    schedule_id: str
    seed: int
    metrics: tuple[MetricContract, ...]
    max_answer_calls_per_question: int
    memory_token_budget: int

