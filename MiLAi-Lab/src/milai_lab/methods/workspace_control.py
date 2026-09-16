"""Opt-in Host control loop built on the feedback-maintained HiAgent archive.

The model chooses the content, branches and next working set. Code only resolves
published identities, schedules maintenance, and preserves execution boundaries.
This is a research method, not canonical Memory or a world rollback facility.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from milai_lab.methods.evidence_maintenance import EvidenceHost
from milai_lab.methods.hiagent import HiAgentError, ModelCall, Pair, Segment

CONTROL_VERSION = "workspace-control-v0.1"


@dataclass
class WorkingControl:
    # The technical identity is the existing segment number. Everything describing
    # why to keep, leave or revisit a route remains model-authored, fallible text.
    record: str = ""
    question: str = ""
    intent: str = ""
    focus_segments: list[int] = field(default_factory=list)
    focus_refs: list[str] = field(default_factory=list)
    branches: list[dict[str, Any]] = field(default_factory=list)


class WorkspaceControlHost(EvidenceHost):
    """Maintain -> assemble -> Actor -> real feedback, with quiescent handoff.

    Final is first a proposal. An optional, bounded maintenance pass feeds advice
    back to the Actor, which still chooses whether to act or submit. Maintenance
    never dispatches actions and never certifies that the task succeeded.
    """

    def __init__(self, *, resolve_source: Callable[[str], str],
                 manage_workset: bool = True, max_delivery_reviews: int = 2,
                 policy_version: str = "CONTROL_0", **kwargs: Any) -> None:
        super().__init__(policy_version=policy_version, **kwargs)
        if (type(manage_workset) is not bool or type(max_delivery_reviews) is not int
                or max_delivery_reviews < 0):
            raise HiAgentError("INVALID_CONTROL_CONFIGURATION")
        self.resolve_source = resolve_source
        self.manage_workset = manage_workset
        self.max_delivery_reviews = max_delivery_reviews
        self.control = WorkingControl()
        self.initialized = False
        self.control_feedback = ""
        self.actor_seen_pairs = 0
        self.external_observations: list[str] = []
        self.maintained_external = self.actor_seen_external = 0
        self.delivery_proposal: dict[str, Any] | None = None
        self.delivery_reviews = 0
        self.reviewed_boundary: tuple[int, int] | None = None
        self.phase = "IDLE"

    def _pairs(self) -> list[dict[str, Any]]:
        return [{"segment": segment.number, "subgoal": segment.subgoal, **asdict(pair)}
                for segment in self.segments for pair in segment.pairs]

    def observe(self, observation: str) -> None:
        """Trusted caller supplies new feedback, including after a handoff.

        Do not use this API to turn an evaluator answer into an online observation.
        New feedback is protected from old focus selections in both model inputs.
        """
        if self.phase != "IDLE" or self.halted or self.finished:
            raise HiAgentError("OBSERVATION_REQUIRES_ACTIVE_QUIESCENT_HOST")
        if not isinstance(observation, str):
            raise HiAgentError("INVALID_OBSERVATION")
        self.external_observations.append(observation)
        self._event("EXTERNAL_OBSERVATION", observation=observation)

    def _decode_control(self, value: Any) -> WorkingControl:
        expected = {"record", "question", "intent", "focus_segments", "focus_refs", "branches"}
        if not isinstance(value, dict) or set(value) != expected:
            raise HiAgentError("INVALID_CONTROL_ENVELOPE")
        if any(not isinstance(value[name], str) for name in ("record", "question", "intent")):
            raise HiAgentError("INVALID_CONTROL_TEXT")
        known_refs = {entry["ref"] for entry in self.source_entries()}

        def refs_valid(refs: Any) -> bool:
            return (isinstance(refs, list) and all(isinstance(ref, str) for ref in refs)
                    and len(refs) == len(set(refs)) and set(refs) <= known_refs)

        ids = value["focus_segments"]
        if (not isinstance(ids, list)
                or any(type(i) is not int or not 1 <= i <= len(self.segments) for i in ids)
                or len(ids) != len(set(ids)) or not refs_valid(value["focus_refs"])):
            raise HiAgentError("UNPUBLISHED_CONTROL_REFERENCE")
        branches = value["branches"]
        if not isinstance(branches, list):
            raise HiAgentError("INVALID_BRANCH_ENTRIES")
        seen: set[int] = set()
        for branch in branches:
            if (not isinstance(branch, dict) or set(branch) != {"segment", "text", "refs"}
                    or type(branch["segment"]) is not int
                    or not 1 <= branch["segment"] <= len(self.segments)
                    or branch["segment"] in seen or not isinstance(branch["text"], str)
                    or not refs_valid(branch["refs"])):
                raise HiAgentError("INVALID_BRANCH_REFERENCE")
            seen.add(branch["segment"])
        return WorkingControl(**value)

    def _maintain(self, reason: str) -> None:
        pairs = self._pairs()
        body = {
            "reason": reason, "previous_control": asdict(self.control),
            "new_observations": pairs[self.maintained_pairs:],
            "external_observations": self.external_observations[self.maintained_external:],
            "initial_observations": self.initial_observations,
            "history_entries": [{"segment": s.number, "subgoal": s.subgoal}
                                for s in self.segments],
            "source_entries": self.source_entries(),
            "delivery_proposal": self.delivery_proposal,
        }
        # A final proposal can follow retrieval with no new environment feedback.
        # Give this pass the same expanded evidence the Actor just consulted.
        if reason == "delivery":
            body["working_context"] = json.loads(self.actor_messages()[-1]["content"])
        raw = self._call(ModelCall("maintenance", (
            {"role": "system", "content": self.summary_policy},
            {"role": "user", "content": self.goal},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ), json_output=True))
        try:
            updated = self._decode_control(json.loads(raw))
        except (json.JSONDecodeError, HiAgentError) as exc:
            # Settled formatting misses are not transport failures. Preserve the
            # last record, disclose the rejection, and let Actor see raw feedback.
            self.control_feedback = str(exc)
            self.maintenance_status = "REJECTED_PREVIOUS_CONTROL_RETAINED"
            self._event("CONTROL_REJECTED", reason=reason, detail=self.control_feedback)
        else:
            previous = asdict(self.control)
            self.control = updated
            self.record = updated.record
            self.expanded = set(updated.focus_segments)
            self.record_revision += 1
            self.control_feedback = ""
            self.maintenance_status = "MODEL_CONTROL_NOT_AUTHORITY"
            self._event("CONTROL_REPLACED", reason=reason, previous=previous,
                        control=asdict(updated), revision=self.record_revision)
        self.maintained_pairs = len(pairs)
        self.maintained_external = len(self.external_observations)
        self.initialized = True

    def _summarize(self) -> None:
        if (not self.initialized or len(self._pairs()) > self.maintained_pairs
                or len(self.external_observations) > self.maintained_external):
            self._maintain("feedback" if self.initialized else "initial")

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        history = []
        for segment in self.segments:
            current = segment is self.segments[-1]
            details = current or not self.manage_workset or segment.number in self.expanded
            entry: dict[str, Any] = {"segment": segment.number, "subgoal": segment.subgoal,
                                     "view": "current" if current else
                                     "expanded" if details else "archived"}
            if details:
                entry["trajectory"] = [asdict(pair) for pair in segment.pairs]
            history.append(entry)
        body = {
            "initial_observations": self.initial_observations,
            "control": asdict(self.control), "control_status": self.maintenance_status,
            "control_feedback": self.control_feedback,
            "history": history, "source_entries": self.source_entries(),
            "selected_sources": [{"ref": ref, "content": self.resolve_source(ref)}
                                 for ref in self.control.focus_refs],
            "new_observations": self._pairs()[self.actor_seen_pairs:],
            "external_observations": self.external_observations[self.actor_seen_external:],
            "delivery_proposal": self.delivery_proposal,
            "delivery_reviews_remaining": self.max_delivery_reviews - self.delivery_reviews,
        }
        return (
            {"role": "system", "content": self.actor_policy},
            {"role": "user", "content": self.goal},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        )

    def step(self) -> None:
        if self.halted or self.finished or self.phase != "IDLE":
            raise HiAgentError("HOST_HALTED_OR_FINISHED")
        try:
            self.phase = "MAINTENANCE"
            if self.delivery_proposal is not None:
                self._maintain("delivery")
                self.delivery_reviews += 1
                self.reviewed_boundary = (len(self._pairs()), len(self.external_observations))
            else:
                self._summarize()
            self.phase = "ACTOR"
            subgoal, action = self._parse(self._call(ModelCall("actor", self.actor_messages())))
            self.actor_seen_pairs = len(self._pairs())
            self.actor_seen_external = len(self.external_observations)
            self.delivery_proposal = None
            if action["action"] == "retrieve":
                self.expanded.update(action["arguments"]["segments"])
                self._event("RETRIEVAL_SELECTED", expanded=sorted(self.expanded))
                return
            boundary = (len(self._pairs()), len(self.external_observations))
            if (action["action"] == "final" and self.reviewed_boundary != boundary
                    and self.delivery_reviews < self.max_delivery_reviews):
                self.delivery_proposal = action
                self._event("DELIVERY_PROPOSED", action=action,
                            remaining_reviews=self.max_delivery_reviews - self.delivery_reviews)
                return  # No submission and no fabricated environment receipt.
            if subgoal is not None:
                self.segments.append(Segment(len(self.segments) + 1, subgoal))
                # Selection belongs to the control loop; changing a subgoal does
                # not silently erase its selected historical evidence.
                self._event("SUBGOAL_STARTED", segment=len(self.segments), subgoal=subgoal)
            self.phase = "DISPATCH"
            self._event("BEFORE_DISPATCH", segment=len(self.segments), action=action)
            observation = self.dispatch(action)
            self.segments[-1].pairs.append(Pair(
                json.dumps(action, ensure_ascii=False), observation))
            self._event("OBSERVATION_RECEIVED", segment=len(self.segments),
                        action=action, observation=observation)
            self.finished = action["action"] == "final"
        except BaseException as exc:
            self.halted = True
            self._event("HOST_STOPPED", error_type=type(exc).__name__, reason=str(exc))
            raise
        finally:
            # Failed/unknown operations remain non-resumable even though this
            # Python call has unwound. There is no silent action replay path.
            self.phase = "FAILED" if self.halted else "IDLE"

    def snapshot(self) -> dict[str, Any]:
        return {**super().snapshot(), "method": CONTROL_VERSION,
                "control": asdict(self.control), "phase": self.phase,
                "control_feedback": self.control_feedback, "initialized": self.initialized,
                "actor_seen_pairs": self.actor_seen_pairs,
                "external_observations": list(self.external_observations),
                "maintained_external": self.maintained_external,
                "actor_seen_external": self.actor_seen_external,
                "delivery_proposal": self.delivery_proposal,
                "delivery_reviews": self.delivery_reviews,
                "reviewed_boundary": self.reviewed_boundary}

    def _contract(self) -> dict[str, Any]:
        policy = json.dumps([self.actor_policy, self.summary_policy], ensure_ascii=False)
        return {"method": CONTROL_VERSION, "policy_version": self.policy_version,
                "policy_hash": hashlib.sha256(policy.encode()).hexdigest(),
                "max_calls": self.max_calls, "manage_workset": self.manage_workset,
                "max_delivery_reviews": self.max_delivery_reviews}

    def checkpoint(self) -> dict[str, Any]:
        if self.phase != "IDLE" or self.halted:
            raise HiAgentError("CHECKPOINT_REQUIRES_KNOWN_QUIESCENT_BOUNDARY")
        return {"contract": self._contract(), "goal": self.goal,
                "initial_observations": list(self.initial_observations), "state": self.snapshot()}

    def restore(self, checkpoint: dict[str, Any]) -> None:
        """Restore trusted local Host data only, into a fresh matching instance.

        Caller binds the source registry and the still-existing environment first.
        The constructor's goal is authoritative, so a revised user goal is not
        overwritten by an older record. No Provider or tool call occurs here.
        """
        if self.segments or sum(self.calls.values()) or self.initialized:
            raise HiAgentError("RESTORE_REQUIRES_FRESH_HOST")
        if checkpoint.get("contract") != self._contract():
            raise HiAgentError("CHECKPOINT_CONTRACT_MISMATCH")
        state = checkpoint["state"]
        if state.get("phase") != "IDLE" or state.get("halted") is not False:
            raise HiAgentError("CHECKPOINT_HAS_UNRESOLVED_OPERATIONS")
        if (any(type(state[key]) is not bool for key in ("initialized", "finished"))
                or type(state["record_revision"]) is not int or state["record_revision"] < 0
                or any(not isinstance(state[key], str)
                       for key in ("control_feedback", "maintenance_status"))):
            raise HiAgentError("INVALID_CHECKPOINT_STATUS")
        segments = []
        for i, segment in enumerate(state["segments"], 1):
            if (segment["number"] != i or not isinstance(segment["subgoal"], str)
                    or not segment["subgoal"].strip()):
                raise HiAgentError("INVALID_CHECKPOINT_SEGMENT")
            pairs = [Pair(**pair) for pair in segment["pairs"]]
            if any(not isinstance(p.action, str) or not isinstance(p.observation, str)
                   for p in pairs):
                raise HiAgentError("INVALID_CHECKPOINT_PAIR")
            segments.append(Segment(i, segment["subgoal"], pairs))
        pair_count = sum(len(s.pairs) for s in segments)
        external = state["external_observations"]
        if not isinstance(external, list) or any(not isinstance(item, str) for item in external):
            raise HiAgentError("INVALID_CHECKPOINT_OBSERVATION")
        for key, upper in (("maintained_pairs", pair_count), ("actor_seen_pairs", pair_count),
                           ("maintained_external", len(external)),
                           ("actor_seen_external", len(external)),
                           ("delivery_reviews", self.max_delivery_reviews)):
            if type(state[key]) is not int or not 0 <= state[key] <= upper:
                raise HiAgentError("INVALID_CHECKPOINT_CURSOR")
        calls = state["call_attempts"]
        if (not isinstance(calls, dict) or calls.keys() != self.calls.keys()
                or any(type(n) is not int or n < 0 for n in calls.values())
                or sum(calls.values()) > self.max_calls):
            raise HiAgentError("INVALID_CHECKPOINT_CALL_ACCOUNTING")
        expanded = state["expanded"]
        if (not isinstance(expanded, list)
                or any(type(i) is not int or not 1 <= i <= len(segments) for i in expanded)):
            raise HiAgentError("INVALID_CHECKPOINT_EXPANSION")
        initial = checkpoint["initial_observations"]
        if not isinstance(initial, list) or any(not isinstance(item, str) for item in initial):
            raise HiAgentError("INVALID_CHECKPOINT_INITIAL_OBSERVATIONS")
        review = state["reviewed_boundary"]
        if review is not None and (not isinstance(review, (list, tuple)) or len(review) != 2
                                  or any(type(n) is not int for n in review)
                                  or not 0 <= review[0] <= pair_count
                                  or not 0 <= review[1] <= len(external)):
            raise HiAgentError("INVALID_CHECKPOINT_DELIVERY_BOUNDARY")
        proposal = state["delivery_proposal"]
        if proposal is not None:
            self.validate_action(proposal)
            if proposal["action"] != "final":
                raise HiAgentError("INVALID_CHECKPOINT_DELIVERY_PROPOSAL")
        # Validate the record against recovered segment IDs, without leaving a
        # partially restored Host on a malformed record.
        self.segments = segments
        try:
            control = self._decode_control(state["control"])
        except BaseException:
            self.segments = []
            raise
        self.control, self.record = control, control.record
        self.expanded = set(expanded)
        self.calls = dict(calls)
        self.initial_observations = tuple(initial)
        self.external_observations = list(external)
        self.finished = state["finished"]
        self.initialized = state["initialized"]
        self.maintenance_status = state["maintenance_status"]
        self.record_revision = state["record_revision"]
        self.control_feedback = state["control_feedback"]
        self.delivery_proposal = proposal
        self.reviewed_boundary = tuple(review) if review is not None else None
        for key in ("maintained_pairs", "actor_seen_pairs", "maintained_external",
                    "actor_seen_external", "delivery_reviews"):
            setattr(self, key, state[key])
        if self.goal != checkpoint["goal"]:
            self.initialized = False
            self.reviewed_boundary = None
        self._event("HOST_RESTORED", call_attempts=dict(self.calls),
                    pending_pairs=pair_count - self.maintained_pairs,
                    goal_updated=self.goal != checkpoint["goal"])
