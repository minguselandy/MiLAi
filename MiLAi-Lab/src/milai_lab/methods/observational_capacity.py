"""Bounded capacity maintenance for the native OM adapter, independently versioned.

Original event text remains immutable. Only accepted, actually supplied pages are
covered; reflection replaces a supplied prefix, retaining the unprocessed suffix.
This module has no provider, benchmark or product dependencies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from milai_lab.methods.hiagent import HiAgentError
from milai_lab.methods.observational_memory import ObservationalMemoryHost, OMConfig, encoded


@dataclass(frozen=True)
class CapacityOMConfig(OMConfig):
    measurement_margin_tokens: int = 256
    maintenance_max_calls: int = 4
    minimum_page_chars: int = 128


class CapacityObservationalMemoryHost(ObservationalMemoryHost):
    config: CapacityOMConfig
    observer_input_attempt = ""

    def _contract(self) -> dict[str, Any]:
        return {**super()._contract(), "capacity_method": "bounded-om-v0.3.1"}

    def snapshot(self) -> dict[str, Any]:
        return {**super().snapshot(), "observer_input_attempt": self.observer_input_attempt}

    def _fits(self, messages: tuple[dict[str, str], ...], role: str) -> bool:
        return (
            self.count_messages(messages)
            + int(getattr(self.config, f"{role}_output_tokens"))
            + self.config.measurement_margin_tokens
            <= self.config.context_tokens
        )

    def _split_uncovered_page(self, page_id: int) -> bool:
        """Split a not-yet-covered range; preserve old IDs and immutable events."""
        page = self.pages[page_id]
        size = len(page["text"])
        if size <= self.config.minimum_page_chars or page_id not in self.raw_tail:
            return False
        middle = size // 2
        later = {
            **page,
            "id": len(self.pages),
            "text": page["text"][middle:],
            "source": {
                **page["source"],
                "start": page["source"]["start"] + middle,
                "length": size - middle,
            },
        }
        self.pages[page_id] = {
            **page,
            "text": page["text"][:middle],
            "source": {**page["source"], "length": middle},
        }
        self.pages.append(later)
        position = self.raw_tail.index(page_id)
        self.raw_tail.insert(position + 1, later["id"])
        if page_id in self.actor_seen_pages:
            self.actor_seen_pages.add(later["id"])
        self._event("OM_PAGE_SUBDIVIDED", original_page=page_id, added_page=later["id"])
        return True

    def observe_batch(self) -> bool:
        self.observer_capacity_blocked = False
        pending = self.count_text(encoded([self.pages[i] for i in self.raw_tail]))
        if pending < self.config.observation_tokens:
            return False
        cutoff = len(self.events) - self.config.recent_events
        body: dict[str, Any] = {
            "previous_observations": self._observation_view(),
            "raw_pages": [],
            "continuationHints": self.continuation_hints,
        }
        if not self._fits(self._messages(self.summary_policy, body), "observer"):
            self.observer_capacity_blocked = True
            self._event("OM_OBSERVER_CAPACITY", reason="PREVIOUS_LOG_OR_REQUIRED_GOAL")
            return False
        batch: list[int] = []
        # Iterate the evolving queue so a subdivided range is handled in order.
        for page_id in self.raw_tail:
            if self.pages[page_id]["event"] >= cutoff or page_id not in self.actor_seen_pages:
                continue
            while True:
                trial = {**body, "raw_pages": [self.pages[i] for i in [*batch, page_id]]}
                messages = self._messages(self.summary_policy, trial)
                if self._fits(messages, "observer"):
                    body, batch = trial, [*batch, page_id]
                    break
                if batch or not self._split_uncovered_page(page_id):
                    break
            if page_id not in batch:
                self.observer_capacity_blocked = not batch
                break
        if not batch:
            return False
        messages = self._messages(self.summary_policy, body)
        identity = hashlib.sha256(encoded(messages).encode()).hexdigest()
        if identity == self.observer_input_attempt:
            return False
        self.observer_attempt = list(batch)
        self.observer_input_attempt = identity
        self._event(
            "OM_MAINTENANCE_BATCH",
            role="observer",
            pending_tokens=pending,
            input_tokens=self.count_messages(messages),
            pages=batch,
            output_reserve=self.config.observer_output_tokens,
            measurement_margin=self.config.measurement_margin_tokens,
        )
        raw = self._call("observer", messages)
        try:
            text, hints = self._parse_maintenance(raw)
        except ValueError:
            self.feedback = "Observer output unusable; supplied pages remain uncovered."
            self._event("OM_OBSERVER_REJECTED", pages=batch)
            return False
        self.observation_groups.append(
            {
                "text": text,
                "pages": batch,
                "source_ranges": [dict(self.pages[i]["source"]) for i in batch],
                "mapping": "coarse_batch_union",
            }
        )
        covered = set(batch)
        self.raw_tail = [i for i in self.raw_tail if i not in covered]
        self.covered_ranges.extend(batch)
        self.continuation_hints = hints
        self._event(
            "OM_OBSERVATIONS_ACCEPTED",
            pages=batch,
            observations=text,
            continuationHints=hints,
            pending_pages=len(self.raw_tail),
        )
        return True

    def reflect_batch(self, *, force: bool = False) -> bool:
        if not self.observation_groups:
            return False
        if (
            not force
            and self.count_text("\n".join(g["text"] for g in self.observation_groups))
            < self.config.reflection_tokens
        ):
            return False
        selected: list[dict[str, Any]] = []
        body: dict[str, Any] = {"observations": [], "continuationHints": self.continuation_hints}
        for group in self.observation_groups:
            trial = {**body, "observations": [{"text": g["text"]} for g in [*selected, group]]}
            if not self._fits(self._messages(self.reflector_policy, trial), "reflector"):
                break
            selected.append(group)
            body = trial
        if not selected:
            self._event("OM_REFLECTOR_CAPACITY", reason="FIRST_GROUP_OR_REQUIRED_GOAL")
            return False
        messages = self._messages(self.reflector_policy, body)
        identity = hashlib.sha256(encoded(messages).encode()).hexdigest()
        if identity == self.reflector_attempt:
            return False
        self.reflector_attempt = identity
        self._event(
            "OM_MAINTENANCE_BATCH",
            role="reflector",
            groups=len(selected),
            input_tokens=self.count_messages(messages),
            output_reserve=self.config.reflector_output_tokens,
            measurement_margin=self.config.measurement_margin_tokens,
        )
        raw = self._call("reflector", messages)
        try:
            text, hints = self._parse_maintenance(raw)
        except ValueError:
            self.feedback = "Reflector output unusable; original log retained."
            self._event("OM_REFLECTOR_REJECTED")
            return False
        before = self.count_text(encoded(body))
        after = self.count_text(
            encoded({"observations": [{"text": text}], "continuationHints": hints})
        )
        if after >= before:
            self.feedback = "Reflection did not shrink supplied material; original log retained."
            self._event("OM_REFLECTION_NO_PROGRESS", before_tokens=before, after_tokens=after)
            return False
        pages = list(dict.fromkeys(i for g in selected for i in g["pages"]))
        replacement = {
            "text": text,
            "pages": pages,
            "source_ranges": [dict(self.pages[i]["source"]) for i in pages],
            "mapping": "coarse_reflection_union",
        }
        self.observation_groups = [replacement, *self.observation_groups[len(selected) :]]
        self.continuation_hints = hints
        self._event(
            "OM_REFLECTION_ACCEPTED",
            observations=text,
            pages=pages,
            replaced_groups=len(selected),
            remaining_groups=len(self.observation_groups),
            before_tokens=before,
            after_tokens=after,
        )
        return True

    def _observe_pending(self) -> None:
        self.observe_batch()

    def _reflect(self) -> None:
        self.reflect_batch()

    def validate_capacity(self) -> None:
        if (
            self.config.measurement_margin_tokens
            + max(
                self.config.actor_output_tokens,
                self.config.observer_output_tokens,
                self.config.reflector_output_tokens,
            )
            >= self.config.context_tokens
        ):
            raise HiAgentError("INVALID_OM_CAPACITY_MARGIN")
