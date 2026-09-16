"""External diagnosis gates, independent of State schema or Product implementation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

Judgment = Literal["CORRECT", "INCORRECT", "DISPUTED", "UNSCORED"]


@dataclass(frozen=True)
class Diagnosis:
    run_id: str
    dataset: str
    ability: str
    cluster: str | None
    fit: bool
    support_presented: bool
    judgment: Judgment
    failure_layer: str | None
    relation_failure: bool = False

    @property
    def adjudicated_use_failure(self) -> bool:
        return self.fit and self.support_presented and self.judgment == "INCORRECT"


def next_branch(rows: Sequence[Diagnosis]) -> str:
    if any(r.dataset == "V1" and r.adjudicated_use_failure for r in rows):
        return "EXPAND_FROZEN_V1_PREFIX"
    if any(r.dataset == "V2" and r.ability != "static" and r.adjudicated_use_failure
           for r in rows):
        return "EXPAND_FROZEN_V2_HIT_ABILITIES"
    if any(r.failure_layer in {"INPUT_UNAVAILABLE", "SOURCE_NOT_ACQUIRED", "ASSEMBLY_LOSS"}
           for r in rows):
        return "ROUTE_TO_ACQUISITION"
    if not rows or any(r.judgment in {"DISPUTED", "UNSCORED"} or not r.fit for r in rows):
        return "STOPPED_RESOURCE_OR_PROTOCOL_LIMIT"
    return "KEEP_BASELINE_BOUNDED_EVIDENCE"


def summarize(rows: Sequence[Diagnosis]) -> dict[str, object]:
    failures = [r for r in rows if r.adjudicated_use_failure]
    relation = [r for r in failures if r.relation_failure]
    clusters = {r.cluster for r in relation if r.cluster is not None}
    abilities = {r.ability for r in relation if r.cluster is not None}
    return {"total_observed_questions": len(rows), "support_presented_wrong": len(failures),
            "relation_failures": len(relation), "independent_relation_clusters": len(clusters),
            "relation_abilities": sorted(abilities),
            "candidate_gate": len(clusters) >= 3 and len(abilities) >= 2,
            "core_signal": "NOT_ESTABLISHED_WITHOUT_UNOPENED_CONFIRMATION",
            "failure_layers": dict(Counter(r.failure_layer for r in rows if r.failure_layer))}


def require_ready(qualification: Mapping[str, object], evaluation: Mapping[str, object],
                  backend: Mapping[str, object], contract: Mapping[str, object]) -> None:
    if qualification.get("status") != "CERTIFIED_DISTINCT":
        raise ValueError("EXPOSURE_QUALIFICATION_REQUIRED")
    required = {"official_answer", "official_support_evidence", "required_correctness",
                "counterexamples", "abstention_rule", "dispute_rule", "evaluation_readiness"}
    if (not required <= evaluation.keys()
            or not {"evaluation_mode", "evaluator"} <= contract.keys()
            or contract.get("frozen_before_generation") is not True):
        raise ValueError("PER_QUESTION_EVALUATION_CONTRACT_REQUIRED")
    if backend.get("status") != "FIT":
        raise ValueError("BACKEND_FIT_REQUIRED")
