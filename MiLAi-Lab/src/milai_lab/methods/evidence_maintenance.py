"""Trial-local HiAgent controls and an opt-in feedback-maintained evidence record.

These are separate research methods. The original HiAgent assembly is unchanged.
The Host owns lifecycle and input construction; the model interprets the evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from milai_lab.methods.hiagent import HiAgentHost, ModelCall

H_ONCE_VERSION = "hiagent-once-v0.1"
EVIDENCE_VERSION = "evidence-maintenance-v0.1"


class HiAgentOnceHost(HiAgentHost):
    """Reuse only the same closed source and policy in this Host instance."""

    def __init__(self, *, summary_policy_version: str = "hiagent-summary-v0.1",
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.summary_policy_version = summary_policy_version
        self.summary_sources: dict[int, str] = {}
        self.summary_degraded: dict[int, bool] = {}

    def _summarize(self) -> None:
        for segment in self.segments[:-1]:
            if segment.number in self.expanded:
                continue
            body = {"subgoal": segment.subgoal,
                    "trajectory": [asdict(pair) for pair in segment.pairs]}
            identity = hashlib.sha256(json.dumps({
                "source": body, "policy": self.summary_policy,
                "policy_version": self.summary_policy_version,
            }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if segment.summary is not None and self.summary_sources.get(segment.number) == identity:
                self._event("SUMMARY_REUSED", segment=segment.number, source_identity=identity,
                            degraded=self.summary_degraded[segment.number])
                continue
            summary = self._call(ModelCall("summary", (
                {"role": "system", "content": self.summary_policy},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ), segment.number)).strip()
            degraded = not summary
            segment.summary = summary if summary else segment.pairs[-1].observation
            self.summary_sources[segment.number] = identity
            self.summary_degraded[segment.number] = degraded
            self._event("SUMMARY_REPLACED", segment=segment.number, summary=segment.summary,
                        fallback_last_observation=degraded, source_identity=identity)

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        messages = super().actor_messages()
        body = json.loads(messages[-1]["content"])
        for entry in body["history"]:
            if entry["view"] == "summary":
                entry["summary_status"] = (
                    "DEGRADED_LAST_OBSERVATION" if self.summary_degraded[entry["segment"]]
                    else "MODEL_SUMMARY")
        return (*messages[:-1], {"role": "user", "content": json.dumps(body, ensure_ascii=False)})

    def snapshot(self) -> dict[str, Any]:
        return {**super().snapshot(), "method": H_ONCE_VERSION,
                "summary_policy_version": self.summary_policy_version,
                "summary_sources": dict(self.summary_sources),
                "summary_degraded": dict(self.summary_degraded)}


class EvidenceHost(HiAgentHost):
    """Consume each completed pair once before the next Actor, never after final.

    Past trajectories are archived, not automatically duplicated next to the record.
    The current segment and explicitly expanded past segments retain actual detail.
    New observations therefore reach the Actor directly as well as the maintainer.
    """

    def __init__(self, *, source_entries: Callable[[], list[dict[str, Any]]] | None = None,
                 policy_version: str = "EVIDENCE_0", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls["maintenance"] = 0
        self.source_entries = source_entries or (lambda: [])
        self.policy_version = policy_version
        self.record = ""
        self.maintained_pairs = 0
        self.record_revision = 0
        self.maintenance_status = "NO_OBSERVATION_YET"

    def _summarize(self) -> None:
        pairs = [{"segment": segment.number, "subgoal": segment.subgoal, **asdict(pair)}
                 for segment in self.segments for pair in segment.pairs]
        pending = pairs[self.maintained_pairs:]
        if not pending:
            return
        body = {"previous_record": self.record, "new_observations": pending,
                "source_entries": self.source_entries()}
        updated = self._call(ModelCall("maintenance", (
            {"role": "system", "content": self.summary_policy},
            {"role": "user", "content": self.goal},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ))).strip()
        previous = self.record
        # A settled blank output consumes the observation batch once and remains
        # visibly degraded. Transport/unknown-usage exceptions never reach here.
        if updated:
            self.record = updated
            self.record_revision += 1
            self.maintenance_status = "MODEL_RECORD"
        else:
            self.maintenance_status = "DEGRADED_EMPTY_OUTPUT_PREVIOUS_RECORD_RETAINED"
        self.maintained_pairs = len(pairs)
        self._event("EVIDENCE_REPLACED", record=self.record, previous_record=previous,
                    changed=self.record != previous, status=self.maintenance_status,
                    maintained_pairs=self.maintained_pairs, new_pairs=len(pending),
                    revision=self.record_revision)

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        history = []
        for segment in self.segments:
            current = segment is self.segments[-1]
            details = current or segment.number in self.expanded
            entry: dict[str, Any] = {
                "segment": segment.number, "subgoal": segment.subgoal,
                "view": "current" if current else "expanded" if details else "archived",
            }
            if details:
                entry["trajectory"] = [asdict(pair) for pair in segment.pairs]
            history.append(entry)
        body = {"initial_observations": self.initial_observations,
                "evidence_record": self.record, "maintenance_status": self.maintenance_status,
                "history": history, "source_entries": self.source_entries()}
        return (
            {"role": "system", "content": self.actor_policy},
            {"role": "user", "content": self.goal},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        )

    def snapshot(self) -> dict[str, Any]:
        return {**super().snapshot(), "method": EVIDENCE_VERSION,
                "policy_version": self.policy_version, "evidence_record": self.record,
                "maintenance_status": self.maintenance_status,
                "record_revision": self.record_revision, "maintained_pairs": self.maintained_pairs}
