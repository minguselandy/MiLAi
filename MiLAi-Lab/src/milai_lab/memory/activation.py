"""Transparent retrieval aids backed by the existing owner Store.

Activation measures contact and use, never truth. Utility measures explicit
feedback under a declared protocol, never factual probability or permission.
The ordinary dense comparison does not call the optional ranking function.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from milai_lab.memory.service import MemoryService


@dataclass(frozen=True, slots=True)
class ActivationParameters:
    """Engineering parameters; one time unit is one second, not a fitted constant."""

    tau_seconds: float = 86400.0
    decay: float = 0.5
    epsilon: float = 1e-6

    def __post_init__(self) -> None:
        if self.tau_seconds <= 0 or self.decay <= 0 or self.epsilon <= 0:
            raise ValueError("ACTIVATION_PARAMETERS_MUST_BE_POSITIVE")


DEFAULT_ACTIVATION_PARAMETERS = ActivationParameters()


def activation_score(
    timestamps: Sequence[datetime],
    now: datetime,
    *,
    parameters: ActivationParameters = DEFAULT_ACTIVATION_PARAMETERS,
) -> float:
    """log(epsilon + sum((1 + age_seconds / tau_seconds) ** -decay)).

    The caller supplies deduplicated actual observations/uses. Future times are
    not contacts yet, and are excluded. Equal times from independent sources
    remain separate contacts; no content hashes or byte comparisons are used.
    """
    strength = sum(
        (1 + (now - timestamp).total_seconds() / parameters.tau_seconds) ** -parameters.decay
        for timestamp in timestamps
        if timestamp <= now
    )
    return math.log(parameters.epsilon + strength)


def utility_estimate(
    positive: int,
    negative: int,
    *,
    alpha: float = 1.0,
    beta: float = 1.0,
) -> dict[str, Any]:
    """Beta-Bernoulli mean for explicit usefulness feedback, with sample count."""
    if positive < 0 or negative < 0 or alpha <= 0 or beta <= 0:
        raise ValueError("UTILITY_COUNTS_OR_PRIOR_INVALID")
    count = positive + negative
    return {
        "mean": (alpha + positive) / (alpha + beta + count),
        "positive": positive,
        "negative": negative,
        "n": count,
        "alpha": alpha,
        "beta": beta,
        "interpretation": "usefulness under explicit feedback protocol",
        "calibration": "uncalibrated",
        "factual_probability": None,
    }


def cold_storage_advice(
    timestamps: Sequence[datetime],
    now: datetime,
    *,
    pinned: bool = False,
    pending: bool = False,
    after: timedelta = timedelta(days=90),
) -> dict[str, Any]:
    """A rebuildable indexing suggestion; explicit recall stays available."""
    past = [timestamp for timestamp in timestamps if timestamp <= now]
    protected = pinned or pending
    return {
        "cold_suggested": bool(past) and now - max(past) >= after and not protected,
        "protected": protected,
        "last_contact_or_use": max(past).isoformat() if past else None,
        "after_seconds": after.total_seconds(),
        "explicit_recall_available": True,
        "deletion_authorized": False,
    }


def rank_candidates(
    candidates: Sequence[dict[str, Any]],
    *,
    activation_weight: float = 0.1,
    utility_weight: float = 0.0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Explicit optional ranking over already owner-scoped candidates.

    Inputs have id, actual cosine dense_score, activation, and optional utility
    mean, visible/allowed/pinned/pending. Total is (cosine + 1) / 2 plus
    activation_weight * sigmoid(activation) plus utility_weight * utility_mean.
    No dense score is inferred from list position. Visibility and current
    permission filter before ranking; pin/pending only prevent budget omission.
    Protected candidates can make the result longer than limit. They never
    bypass visibility, permissions, or an application's independent controls.
    """
    if activation_weight < 0 or utility_weight < 0 or (limit is not None and limit < 1):
        raise ValueError("ACTIVATION_RANKING_PARAMETERS_INVALID")
    ranked = []
    for candidate in candidates:
        if not candidate.get("visible", True) or not candidate.get("allowed", True):
            continue
        dense_score = float(candidate["dense_score"])
        activation = float(candidate["activation"])
        semantic_component = (dense_score + 1) / 2
        activation_component = (
            1 / (1 + math.exp(-activation))
            if activation >= 0
            else math.exp(activation) / (1 + math.exp(activation))
        )
        utility = candidate.get("utility", {})
        utility_component = float(utility.get("mean", 0.5))
        total = (
            semantic_component
            + activation_weight * activation_component
            + utility_weight * utility_component
        )
        ranked.append(
            {
                **candidate,
                "ranking": {
                    "method": "dense_activation_v1",
                    "dense_score": dense_score,
                    "semantic_component": semantic_component,
                    "activation": activation,
                    "activation_component": activation_component,
                    "utility_component": utility_component,
                    "activation_weight": activation_weight,
                    "utility_weight": utility_weight,
                    "total": total,
                    "factual_probability": None,
                },
            }
        )
    ranked.sort(key=lambda candidate: (-candidate["ranking"]["total"], candidate["id"]))
    if limit is None:
        return ranked
    return [
        candidate
        for position, candidate in enumerate(ranked)
        if position < limit or candidate.get("pinned", False) or candidate.get("pending", False)
    ]


class ActivationIndex:
    """Use/feedback metadata in the same Store, separate from ordinary facts.

    Source contacts come from actual visible record support. Assistant summaries
    are not independent contacts. A read counts at most once per record/request,
    regardless of versions, pages or cursors. Replays/cache reads add no use.
    Feedback labels are explicit caller interpretations with actual provenance;
    the module does not claim to verify their natural-language entailment.
    """

    def __init__(
        self,
        service: MemoryService,
        *,
        parameters: ActivationParameters = DEFAULT_ACTIVATION_PARAMETERS,
    ) -> None:
        self.service = service
        self.parameters = parameters
        self.namespace = (*service.namespace, "activation")

    def _state(self, record_id: str) -> dict[str, Any]:
        item = self.service.store.get(self.namespace, record_id)
        return dict(item.value) if item is not None else {"uses": {}, "feedback": {}}

    @staticmethod
    def _support_refs(value: dict[str, Any]) -> list[str]:
        """Legacy source-unknown reads remain unknown, with no invented contacts."""
        if "source_refs" in value:
            return list(value["source_refs"])
        return [value["source_ref"]] if value.get("source_ref") else []

    def record_use(
        self,
        record_id: str,
        *,
        request_id: str,
        cached: bool = False,
        replay: bool = False,
    ) -> dict[str, Any]:
        if not request_id:
            raise ValueError("ACTIVATION_REQUEST_ID_REQUIRED")
        record = self.service.read(record_id)
        if not record.get("ok"):
            return {"recorded": False, "reason": "record_unavailable"}
        if cached or replay:
            return {"recorded": False, "reason": "cache_or_internal_replay"}
        with self.service._locked():
            state = self._state(record_id)
            if request_id in state["uses"]:
                return {"recorded": False, "reason": "same_request", "request_id": request_id}
            state["uses"][request_id] = {
                "request_id": request_id,
                "used_at": self.service.clock().isoformat(),
                "revision": record["value"].get("revision"),
                "source_refs": self._support_refs(record["value"]),
            }
            self.service.store.put(self.namespace, record_id, state, index=False)
        return {"recorded": True, "request_id": request_id}

    def record_feedback(
        self,
        record_id: str,
        *,
        request_id: str,
        source_ref: str,
        useful: bool | None,
        protocol: str = "explicit_usefulness_v1",
        replay: bool = False,
    ) -> dict[str, Any]:
        if not request_id or not protocol or (useful is not None and type(useful) is not bool):
            raise ValueError("UTILITY_FEEDBACK_ARGUMENTS_INVALID")
        record = self.service.read(record_id)
        if not record.get("ok"):
            return {"recorded": False, "reason": "record_unavailable"}
        source = self.service.source(source_ref)
        if source is None:
            return {"recorded": False, "reason": "feedback_source_unavailable"}
        if replay or source["role"] == "assistant":
            return {"recorded": False, "reason": "replay_or_assistant_is_not_explicit_feedback"}
        if useful is None:
            return {"recorded": False, "reason": "unknown_feedback_not_a_label"}
        with self.service._locked():
            state = self._state(record_id)
            prior = state["feedback"].get(source_ref)
            if prior is not None:
                if prior["useful"] != useful or prior["protocol"] != protocol:
                    raise ValueError("UTILITY_EXISTING_FEEDBACK_INTERPRETATION_CHANGED")
                return {"recorded": False, "reason": "same_feedback_source"}
            state["feedback"][source_ref] = {
                "source_ref": source_ref,
                "role": source["role"],
                "request_id": request_id,
                "observed_at": source["observed_at"],
                "record_revision": record["value"].get("revision"),
                "useful": useful,
                "protocol": protocol,
                "caller_interpretation": "unchecked",
            }
            self.service.store.put(self.namespace, record_id, state, index=False)
        return {"recorded": True, "source_ref": source_ref, "caller_interpretation": "unchecked"}

    def describe(
        self,
        record_id: str,
        *,
        now: datetime | None = None,
        pinned: bool = False,
        pending: bool = False,
    ) -> dict[str, Any] | None:
        """Current visible registry plus actual components; forgotten records return None."""
        record = self.service.read(record_id)
        if not record.get("ok"):
            return None
        state = self._state(record_id)
        contact_refs = [
            *self._support_refs(record["value"]),
            *(ref for use in state["uses"].values() for ref in use["source_refs"]),
        ]
        sources = [
            source
            for source_ref in dict.fromkeys(contact_refs)
            if (source := self.service.source(source_ref)) is not None
            and source["role"] != "assistant"
        ]
        contacts = [
            {"source_ref": source["event_id"], "observed_at": source["observed_at"]}
            for source in sources
        ]
        uses = list(state["uses"].values())
        feedback = [
            value
            for source_ref, value in state["feedback"].items()
            if self.service.source(source_ref) is not None
        ]
        time = now or self.service.clock()
        timestamps = [
            datetime.fromisoformat(value).astimezone(UTC)
            for value in [
                *(contact["observed_at"] for contact in contacts),
                *(use["used_at"] for use in uses),
            ]
        ]
        positive = sum(entry["useful"] for entry in feedback)
        return {
            "id": record_id,
            "revision": record["value"].get("revision"),
            "as_of": time.isoformat(),
            "activation": activation_score(timestamps, time, parameters=self.parameters),
            "parameters": {
                "tau_seconds": self.parameters.tau_seconds,
                "decay": self.parameters.decay,
                "epsilon": self.parameters.epsilon,
            },
            "utility": utility_estimate(positive, len(feedback) - positive),
            "source_contacts": contacts,
            "uses": uses,
            "feedback": feedback,
            "pinned": pinned,
            "pending": pending,
            "cold_storage": cold_storage_advice(timestamps, time, pinned=pinned, pending=pending),
        }
