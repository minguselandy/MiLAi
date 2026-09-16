"""HiAgent's subgoal/summary/retrieval algorithm, transplanted to a text Host.

Independent implementation, not vendored upstream code or a paper-score reproduction.
Source: HiAgent2024/HiAgent@cebdd8e4eacec1a532ce2c0041db8902217b90ba,
agentboard/agents/{cme_final,summarize}.py. See the accompanying fidelity note.

Like that source, every input assembly summarizes each non-expanded past segment
again; there is deliberately no summary cache. Retrieval stays active until a new
subgoal. Actor and summarizer share one explicit call budget. Network, model choice,
token counting, authorization and actual tool execution belong to the caller.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

UPSTREAM_COMMIT = "cebdd8e4eacec1a532ce2c0041db8902217b90ba"
METHOD_VERSION = "hiagent-terminal-v0.1"


class HiAgentError(ValueError):
    """A local contract failure, not a business correctness judgment."""


@dataclass(frozen=True)
class Pair:
    action: str
    observation: str


@dataclass
class Segment:
    number: int
    subgoal: str
    pairs: list[Pair] = field(default_factory=list)
    summary: str | None = None


@dataclass(frozen=True)
class ModelCall:
    kind: Literal["actor", "summary", "maintenance", "observer", "reflector"]
    messages: tuple[dict[str, str], ...]
    segment: int | None = None
    json_output: bool = False


class HiAgentHost:
    """Single-task, in-process research Host. No optional note-writing channel.

    A model-declared new subgoal closes the previous segment, but does not certify
    that it succeeded. Actual observations remain archived. ``step`` makes any
    required summary calls, then one actor call. A retrieve decision does not run
    a shell command; the next step uses the expanded historical segment.
    """

    def __init__(
        self,
        *,
        goal: str,
        actor_policy: str,
        summary_policy: str,
        generate: Callable[[ModelCall], str],
        validate_action: Callable[[dict[str, Any]], None],
        dispatch: Callable[[dict[str, Any]], str],
        max_calls: int = 64,
        initial_observations: tuple[str, ...] = (),
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if type(max_calls) is not int or max_calls < 1:
            raise HiAgentError("INVALID_CALL_BUDGET")
        self.goal = goal
        self.actor_policy, self.summary_policy = actor_policy, summary_policy
        self.generate, self.validate_action, self.dispatch = generate, validate_action, dispatch
        self.max_calls = max_calls
        self.initial_observations = initial_observations
        self.emit = emit
        self.segments: list[Segment] = []
        self.expanded: set[int] = set()
        self.calls = {"actor": 0, "summary": 0}
        self.finished = self.halted = False

    def _event(self, event: str, **data: Any) -> None:
        if self.emit:
            self.emit({"event": event, **data})

    def _call(self, request: ModelCall) -> str:
        if sum(self.calls.values()) >= self.max_calls:
            raise HiAgentError("TOTAL_MODEL_CALL_LIMIT")
        self.calls[request.kind] += 1
        call = sum(self.calls.values())
        self._event("MODEL_CALL_ATTEMPT", call=call, request=asdict(request))
        # Exceptions, including unknown Provider usage, propagate. Never retry or
        # turn a transport failure into a supposedly successful summary.
        output = self.generate(request)
        self._event("MODEL_RETURN", call=call, kind=request.kind, output=output)
        if not isinstance(output, str):
            raise HiAgentError("NON_TEXT_MODEL_OUTPUT")
        return output

    def _summarize(self) -> None:
        for segment in self.segments[:-1]:
            if segment.number in self.expanded:
                continue
            body = {"subgoal": segment.subgoal,
                    "trajectory": [asdict(pair) for pair in segment.pairs]}
            summary = self._call(ModelCall("summary", (
                {"role": "system", "content": self.summary_policy},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ), segment.number)).strip()
            # A settled but blank completion is visibly degraded, not certified
            # completion. Do not catch unknown/failed HTTP calls here.
            fallback = not summary
            if fallback:
                summary = segment.pairs[-1].observation
            segment.summary = summary
            self._event("SUMMARY_REPLACED", segment=segment.number, summary=summary,
                        fallback_last_observation=fallback)

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        """Mechanical assembly; no old bodies duplicated beside summaries."""
        history = []
        for segment in self.segments:
            current = segment is self.segments[-1]
            details = current or segment.number in self.expanded
            if not details and segment.summary is None:
                raise HiAgentError("PAST_SEGMENT_NOT_SUMMARIZED")
            entry: dict[str, Any] = {
                "segment": segment.number, "subgoal": segment.subgoal,
                "view": "current" if current else "expanded" if details else "summary",
            }
            if details:
                entry["trajectory"] = [asdict(pair) for pair in segment.pairs]
            else:
                entry["summary"] = segment.summary
            history.append(entry)
        body = {"initial_observations": self.initial_observations, "history": history}
        return (
            {"role": "system", "content": self.actor_policy},
            {"role": "user", "content": self.goal},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        )

    def _parse(self, raw: str) -> tuple[str | None, dict[str, Any]]:
        value = json.loads(raw)
        if (not isinstance(value, dict) or not {"action", "arguments"} <= value.keys()
                or value.keys() - {"action", "arguments", "subgoal"}
                or not isinstance(value["action"], str)
                or not isinstance(value["arguments"], dict)):
            raise HiAgentError("INVALID_ACTOR_ENVELOPE")
        subgoal = value.get("subgoal")
        if subgoal is not None and (
            not isinstance(subgoal, str) or not subgoal.strip()
            or "\n" in subgoal or "\r" in subgoal
        ):
            raise HiAgentError("INVALID_SUBGOAL")
        action: dict[str, Any] = {"action": value["action"], "arguments": value["arguments"]}
        if action["action"] == "retrieve":
            ids = action["arguments"].get("segments")
            if (subgoal is not None or set(action["arguments"]) != {"segments"}
                    or not isinstance(ids, list) or not ids
                    or any(type(i) is not int or not 1 <= i < len(self.segments) for i in ids)):
                raise HiAgentError("INVALID_RETRIEVAL")
        else:
            self.validate_action(action)
        if not self.segments and subgoal is None:
            raise HiAgentError("INITIAL_SUBGOAL_REQUIRED")
        if subgoal is not None and self.segments and not self.segments[-1].pairs:
            raise HiAgentError("EMPTY_PREVIOUS_SEGMENT")
        return subgoal, action

    def step(self) -> None:
        if self.halted or self.finished:
            raise HiAgentError("HOST_HALTED_OR_FINISHED")
        try:
            self._summarize()
            raw = self._call(ModelCall("actor", self.actor_messages()))
            subgoal, action = self._parse(raw)
            if subgoal is not None:
                self.segments.append(Segment(len(self.segments) + 1, subgoal))
                self.expanded.clear()
                self._event("SUBGOAL_STARTED", segment=len(self.segments), subgoal=subgoal)
            if action["action"] == "retrieve":
                self.expanded.update(action["arguments"]["segments"])
                self._event("RETRIEVAL_SELECTED", expanded=sorted(self.expanded))
                return
            # Raw actor output is logged separately; archive only its actual
            # action, followed by the observation returned by that action.
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

    def snapshot(self) -> dict[str, Any]:
        """Evidence only; not a public persistent-Memory checkpoint contract."""
        return {"method": METHOD_VERSION, "upstream_commit": UPSTREAM_COMMIT,
                "segments": [asdict(segment) for segment in self.segments],
                "expanded": sorted(self.expanded), "call_attempts": dict(self.calls),
                "finished": self.finished, "halted": self.halted}
