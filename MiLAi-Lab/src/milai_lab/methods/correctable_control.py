"""V02-10 v0.5 contracts, separate from the frozen v0.4 experiment.

Static request planning does not decide dynamic eligibility. A dynamic failure
must have its own observation, scope and minimal treatment, even if H1 is negative.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from milai_lab.methods.state_control import (
    ARMS,
    Case,
    ControlStop,
    Material,
    canonical,
    digest,
    prepare_request,
)

Condition = Literal["R0", "C0", "C1", "C2", "O"]
Phase = Literal["prepare", "deliver"]


@dataclass(frozen=True)
class Allocation:
    condition: Condition
    phase: Phase

    @property
    def key(self) -> str:
        return f"{self.condition}.{self.phase}"


def static_plan(*, oracle_registered: bool = False) -> tuple[Allocation, ...]:
    phases: tuple[Phase, ...] = ("prepare", "deliver")
    primary = (Allocation("R0", "deliver"), *(
        Allocation(arm, phase) for phase in phases for arm in ARMS
    ))
    return primary + ((Allocation("O", "deliver"),) if oracle_registered else ())


@dataclass(frozen=True)
class StaticRequest:
    allocation: Allocation
    body: bytes
    common_sha256: str


def static_request(
    case: Case, allocation: Allocation, *, scope: str,
    eligible: Callable[[Material], bool], control: str = "", oracle: str | None = None,
    seed: int = 260908,
) -> StaticRequest:
    if allocation not in static_plan(oracle_registered=oracle is not None):
        raise ControlStop("V05_UNREGISTERED_ALLOCATION")
    condition = allocation.condition
    arm = condition if condition in ARMS else "C0"
    item = prepare_request(case, arm, allocation.phase, scope=scope,
                           eligible=eligible, control=control, seed=seed)
    body = json.loads(item.body)
    if condition == "R0":
        if control:
            raise ControlStop("R0_HAS_NO_PREPARATION_ARTIFACT")
        body["messages"][2]["content"] = (
            "Read the complete materials and answer the current task directly in this single turn. "
            "Give the supported conclusion, remaining uncertainty and only necessary next steps."
        )
    elif condition == "O":
        body["messages"][2]["content"] = (
            "Preregistered human focus (diagnostic only):\n" + str(oracle)
            + "\nAnswer the current task using the complete materials."
        )
    return StaticRequest(allocation, canonical(body).encode(), item.common_sha256)


def static_batch_reservation(
    plan: tuple[Allocation, ...], input_counts: Mapping[str, int], *,
    raw_limit: int = 64000, output_cap: int = 1024,
) -> int:
    """Reserve every actual input plus output; eight calls need not fit 64k."""
    if set(input_counts) != {item.key for item in plan}:
        raise ControlStop("V05_INCOMPLETE_ALLOCATION_TOKEN_COUNTS")
    if output_cap != 1024 or any(type(n) is not int or not 0 < n <= 8192
                                 for n in input_counts.values()):
        raise ControlStop("V05_REQUEST_ENVELOPE_INVALID")
    upper = sum(input_counts.values()) + len(plan) * output_cap
    if upper > raw_limit:
        raise ControlStop("V05_COMPLETE_BATCH_OVER_LIMIT")
    return upper


@dataclass(frozen=True)
class DynamicEntry:
    failure_id: str
    source_id: str
    origin: Literal["NORMAL_TRAJECTORY", "CONTROLLED_MECHANISM"]
    layer: Literal["PRESENTED_NOT_USED", "SOURCE_NOT_ACQUIRED", "PERMISSION_OR_TOOL_ERROR"]
    observed_failure: str
    minimal_intervention: str
    contrast: Literal["A/B", "C/D", "A/D"]
    observable_prediction: str

    def check(self) -> None:
        if not all((self.failure_id, self.source_id, self.observed_failure,
                    self.minimal_intervention, self.observable_prediction)):
            raise ControlStop("DYNAMIC_ENTRY_NEEDS_INDEPENDENT_FAILURE")
        if self.layer == "PERMISSION_OR_TOOL_ERROR":
            raise ControlStop("REPAIR_EXECUTION_BOUNDARY_BEFORE_DYNAMIC_EFFECT_RUN")

    @property
    def attribution(self) -> str:
        return "BUNDLE_SCREENING" if self.contrast == "A/D" else "EXPLORATION_PROMPT_CONTRAST"


def request_digest(request: StaticRequest) -> str:
    return digest(request.body)
