"""Shared concurrency ceilings for the paper evaluation harness.

Formal runs choose an explicit worker count before labels are opened. These
lanes provide reusable harness bounds; they do not adapt a running method based
on its score or retry failed logical requests.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParallelismLane:
    name: str
    default_workers: int
    hard_ceiling: int

    def validate(self, workers: int, *, frozen_ceiling: int | None = None) -> int:
        ceiling = self.hard_ceiling if frozen_ceiling is None else frozen_ceiling
        if not 1 <= ceiling <= self.hard_ceiling:
            raise ValueError(f"{self.name} frozen worker ceiling is invalid")
        if not 1 <= workers <= ceiling:
            raise ValueError(
                f"{self.name} workers must be between 1 and {ceiling}, got {workers}"
            )
        return workers


# Eight is the preregistered operating point for this 16-core host. Sixteen is
# an implementation ceiling reserved for a later, pre-label capacity probe.
STATELESS_CONTEXT_LANE = ParallelismLane("stateless context", 8, 16)
STATEFUL_CONTEXT_PROCESS_LANE = ParallelismLane("stateful context process", 4, 8)
DENSE_CONTEXT_PROCESS_LANE = ParallelismLane("dense context process", 2, 2)
ANSWER_PROVIDER_LANE = ParallelismLane("answer provider", 8, 16)
JUDGE_PROVIDER_LANE = ParallelismLane("judge provider", 8, 16)
PROMPT_BUILD_LANE = ParallelismLane("prompt build", 8, 16)


WORKER_CHOICES = tuple(range(1, 17))
