"""Deterministic cluster-first admission, independent of experimental answers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OrderContract:
    goal_id: str
    version: str
    benchmark_revision: str
    seed: str

    def digest(self, purpose: str, canonical_id: str) -> str:
        body = json.dumps([self.goal_id, self.version, self.benchmark_revision,
                           purpose, canonical_id, self.seed], ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def order(self, purpose: str, identifiers: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("DUPLICATE_CANONICAL_ID")
        return tuple(sorted(identifiers, key=lambda item: (self.digest(purpose, item), item)))

    def partition(self, clusters: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        ordered = self.order("split", clusters)
        boundary = 2 * len(ordered) // 3
        return self.order("admission", ordered[:boundary]), ordered[boundary:]


@dataclass(frozen=True)
class Qualification:
    status: Literal["ELIGIBLE", "REJECTED", "UNRESOLVED"]
    reasons: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ScreeningRow:
    cluster: str
    status: Literal["ACCEPTED", "REJECTED", "UNRESOLVED", "NOT_SCREENED"]
    reasons: tuple[str, ...]
    evidence: tuple[str, ...]


def admit(order: tuple[str, ...], qualification: dict[str, Qualification], *,
          target: int, screening_cap: int) -> tuple[ScreeningRow, ...]:
    """Seal B from pre-answer status only; no output or gold value enters this function.

    Missing receipts stop screening at the current pointer. Later receipts cannot skip
    an unreviewed earlier cluster. Actual review/time limits determine receipt availability.
    """
    if target < 1 or screening_cap < 0 or len(set(order)) != len(order):
        raise ValueError("INVALID_ADMISSION_BOUNDS_OR_DUPLICATE_CLUSTER")
    rows: list[ScreeningRow] = []
    accepted, screened = 0, 0
    stopped = False
    for cluster in order:
        if stopped or accepted >= target or screened >= screening_cap:
            rows.append(ScreeningRow(cluster, "NOT_SCREENED", ("FROZEN_STOP",), ()))
            continue
        receipt = qualification.get(cluster)
        if receipt is None:
            stopped = True
            rows.append(ScreeningRow(cluster, "NOT_SCREENED", ("REVIEW_NOT_COMPLETED",), ()))
            continue
        screened += 1
        if receipt.status == "ELIGIBLE":
            accepted += 1
            rows.append(ScreeningRow(cluster, "ACCEPTED", receipt.reasons, receipt.evidence))
        else:
            rows.append(ScreeningRow(cluster, receipt.status, receipt.reasons, receipt.evidence))
    return tuple(rows)


def fixed_prefix(rows: tuple[ScreeningRow, ...], count: int) -> tuple[str, ...]:
    """The execution prefix never consults whether a previous answer succeeded."""
    if count < 0:
        raise ValueError("NEGATIVE_PREFIX")
    return tuple(row.cluster for row in rows if row.status == "ACCEPTED")[:count]


def denominators(rows: tuple[ScreeningRow, ...]) -> dict[str, int]:
    counts = {status: sum(row.status == status for row in rows)
              for status in ("ACCEPTED", "REJECTED", "UNRESOLVED", "NOT_SCREENED")}
    return {"discovery_clusters": len(rows), "screened": len(rows) - counts["NOT_SCREENED"],
            **{key.lower(): value for key, value in counts.items()}}
