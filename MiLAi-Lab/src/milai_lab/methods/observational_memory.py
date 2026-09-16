"""Synchronous text OM mechanism port; independent of RWC scheduling.

Reference: mastra-ai/mastra@b611980c1a3fe3f74bd3c6538ce6a34f510954d0
(Apache-2.0). Independently written policies and mechanics; see the Host guide
for differences. No async buffering, extractor calls, automatic retries or search.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from milai_lab.methods.hiagent import HiAgentError, ModelCall

METHOD_VERSION = "om-sync-port-v0.1"


OM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "observations": {"type": "string", "minLength": 1, "maxLength": 3000},
        "continuationHints": {
            "type": "object",
            "properties": {
                "currentTask": {"type": "string", "maxLength": 512},
                "suggestedResponse": {"type": "string", "maxLength": 512},
            },
            "required": ["currentTask", "suggestedResponse"],
            "additionalProperties": False,
        },
    },
    "required": ["observations", "continuationHints"],
    "additionalProperties": False,
}


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class OMConfig:
    observation_tokens: int = 12000
    reflection_tokens: int = 16000
    recent_events: int = 2
    page_chars: int = 4000
    context_tokens: int = 65536
    actor_output_tokens: int = 4096
    observer_output_tokens: int = 2048
    reflector_output_tokens: int = 2048

    def __post_init__(self) -> None:
        if any(type(v) is not int or v < 1 for v in asdict(self).values()):
            raise HiAgentError("INVALID_OM_CAPACITY")
        if (
            self.page_chars > 16000
            or max(
                self.actor_output_tokens, self.observer_output_tokens, self.reflector_output_tokens
            )
            >= self.context_tokens
        ):
            raise HiAgentError("INVALID_OM_CAPACITY")


class ObservationalMemoryHost:
    """Page-exact coverage and Actor receipt positions, with one maintenance attempt.

    All original events remain archived. Only accepted observation pages leave the
    default raw tail. Source ranges are provenance, never a truth certification.
    """

    def __init__(
        self,
        *,
        goal: str,
        actor_policy: str,
        summary_policy: str,
        reflector_policy: str,
        generate: Callable[[ModelCall], str],
        validate_action: Callable[[dict[str, Any]], None],
        dispatch: Callable[[dict[str, Any]], str],
        source_entries: Callable[[], list[dict[str, Any]]],
        read_source: Callable[[str, int, int], dict[str, Any]],
        count_text: Callable[[str], int],
        count_messages: Callable[[tuple[dict[str, str], ...]], int],
        config: OMConfig | None = None,
        model_profile: str = "caller-bound",
        max_calls: int = 64,
        initial_observations: tuple[str, ...] = (),
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if type(max_calls) is not int or max_calls < 1:
            raise HiAgentError("INVALID_CALL_BUDGET")
        self.goal, self.goal_revision = goal, 1
        self.actor_policy, self.summary_policy = actor_policy, summary_policy
        self.reflector_policy, self.model_profile = reflector_policy, model_profile
        self.generate, self.validate_action, self.dispatch = generate, validate_action, dispatch
        self.source_entries, self.read_source = source_entries, read_source
        self.count_text, self.count_messages = count_text, count_messages
        self.config, self.max_calls, self.emit = config or OMConfig(), max_calls, emit
        self.calls = {"actor": 0, "observer": 0, "reflector": 0}
        self.phase, self.finished, self.halted, self.initialized = "IDLE", False, False, False
        self.events: list[dict[str, Any]] = []
        self.pages: list[dict[str, Any]] = []
        self.raw_tail: list[int] = []
        self.covered_ranges: list[int] = []
        self.actor_seen_pages: set[int] = set()
        self.observation_groups: list[dict[str, Any]] = []
        self.continuation_hints = {"currentTask": "", "suggestedResponse": ""}
        self.observer_attempt: list[int] = []
        self.reflector_attempt = ""
        self.feedback = ""
        self._append("goal", goal)
        for text in initial_observations:
            self._append("message", text)

    def _event(self, event: str, **fields: Any) -> None:
        if self.emit:
            self.emit({"event": event, **fields})

    def _append(self, kind: str, text: str, action: dict[str, Any] | None = None) -> None:
        event_id = len(self.events)
        source = None
        if kind == "tool":
            value = json.loads(text)
            ref = value.get("ref")
            entry = next((e for e in self.source_entries() if e["ref"] == ref), None)
            if entry is not None:
                source = entry
        self.events.append({"id": event_id, "kind": kind, "text": text, "action": action})
        total = source["total_chars"] if source else len(text)
        for start in range(0, max(total, 1), self.config.page_chars):
            if source:
                page = self.read_source(source["ref"], start, self.config.page_chars)
                body = page["text"]
                ref, revision = source["ref"], page["revision"]
            else:
                body = text[start : start + self.config.page_chars]
                ref, revision = f"event:{event_id}", hashlib.sha256(text.encode()).hexdigest()
            page_id = len(self.pages)
            self.pages.append(
                {
                    "id": page_id,
                    "event": event_id,
                    "kind": kind,
                    "action": action,
                    "text": body,
                    "source": {
                        "ref": ref,
                        "revision": revision,
                        "start": start,
                        "length": len(body),
                        "total_chars": total,
                    },
                }
            )
            self.raw_tail.append(page_id)
        self._event("OM_EVENT_APPENDED", event_id=event_id, kind=kind, total_chars=total)

    def observe(self, observation: str) -> None:
        if self.phase != "IDLE" or self.halted or self.finished:
            raise HiAgentError("OBSERVATION_REQUIRES_ACTIVE_QUIESCENT_HOST")
        if not isinstance(observation, str):
            raise HiAgentError("INVALID_OBSERVATION")
        self._append("message", observation)

    def _assert_sources(self) -> None:
        available = {e["ref"]: e["revision"] for e in self.source_entries()}
        for page in self.pages:
            source = page["source"]
            if (
                not source["ref"].startswith("event:")
                and available.get(source["ref"]) != source["revision"]
            ):
                raise HiAgentError("OM_SOURCE_DEPENDENCY_NOT_READABLE")

    def _messages(self, policy: str, body: dict[str, Any]) -> tuple[dict[str, str], ...]:
        return (
            {"role": "system", "content": policy},
            {"role": "user", "content": self.goal},
            {"role": "user", "content": encoded(body)},
        )

    def _fits(self, messages: tuple[dict[str, str], ...], role: str) -> bool:
        return (
            self.count_messages(messages) + int(getattr(self.config, f"{role}_output_tokens"))
            <= self.config.context_tokens
        )

    def _call(
        self, role: Literal["actor", "observer", "reflector"], messages: tuple[dict[str, str], ...]
    ) -> str:
        self._assert_sources()
        if not self._fits(messages, role):
            raise HiAgentError("OM_INPUT_CAPACITY")
        if sum(self.calls.values()) >= self.max_calls:
            raise HiAgentError("TOTAL_MODEL_CALL_LIMIT")
        self.calls[role] += 1
        call = sum(self.calls.values())
        request = ModelCall(role, messages, json_output=True)
        self._event("MODEL_CALL_ATTEMPT", call=call, request=asdict(request))
        output = self.generate(request)  # Unknown usage propagates; never retry.
        self._event("MODEL_RETURN", call=call, kind=role, output=output)
        if not isinstance(output, str):
            raise HiAgentError("NON_TEXT_MODEL_OUTPUT")
        return output

    @staticmethod
    def _parse_maintenance(raw: str) -> tuple[str, dict[str, str]]:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise HiAgentError("UNUSABLE_OM_OUTPUT")
        observations = value.get("observations")
        if isinstance(observations, list) and all(isinstance(item, str) for item in observations):
            observations = "\n".join(observations)
        if not isinstance(observations, str):
            raise HiAgentError("UNUSABLE_OM_OUTPUT")
        value["observations"] = observations
        hints = value.get("continuationHints", {})
        if (
            not value["observations"].strip()
            or not isinstance(hints, dict)
            or any(
                not isinstance(hints.get(k, ""), str) for k in ("currentTask", "suggestedResponse")
            )
        ):
            raise HiAgentError("UNUSABLE_OM_OUTPUT")
        return value["observations"].strip(), {
            k: hints.get(k, "") for k in ("currentTask", "suggestedResponse")
        }

    def _observation_view(self) -> list[dict[str, Any]]:
        """The native adapter may expose provenance through stable source reads."""
        return self.observation_groups

    def _observe_pending(self) -> None:
        pending_tokens = self.count_text(encoded([self.pages[i] for i in self.raw_tail]))
        if pending_tokens < self.config.observation_tokens:
            return
        cutoff = len(self.events) - self.config.recent_events
        eligible = [
            i
            for i in self.raw_tail
            if self.pages[i]["event"] < cutoff and i in self.actor_seen_pages
        ]
        batch: list[int] = []
        body: dict[str, Any] = {
            "previous_observations": self._observation_view(),
            "raw_pages": [],
            "continuationHints": self.continuation_hints,
        }
        for page_id in eligible:
            trial = {**body, "raw_pages": [self.pages[i] for i in [*batch, page_id]]}
            if not self._fits(self._messages(self.summary_policy, trial), "observer"):
                break
            body, batch = trial, [*batch, page_id]
        if not batch or batch == self.observer_attempt:
            return
        self.observer_attempt = batch
        raw = self._call("observer", self._messages(self.summary_policy, body))
        try:
            text, hints = self._parse_maintenance(raw)
        except ValueError:
            self.feedback = "Observer output unusable; original unobserved pages retained."
            self._event("OM_OBSERVER_REJECTED", pages=batch)
            return
        self.observation_groups.append(
            {
                "text": text,
                "pages": batch,
                "source_ranges": [self.pages[i]["source"] for i in batch],
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
            raw_tail=list(self.raw_tail),
        )

    def _reflect(self) -> None:
        if (
            self.count_text("\n".join(g["text"] for g in self.observation_groups))
            < self.config.reflection_tokens
        ):
            return
        identity = hashlib.sha256(encoded(self.observation_groups).encode()).hexdigest()
        if identity == self.reflector_attempt:
            return
        body = {
            "observations": self.observation_groups,
            "continuationHints": self.continuation_hints,
        }
        # Groups already fit at admission. A compact text-only reflection input
        # avoids serializing the often larger provenance union into model context.
        body["observations"] = [{"text": g["text"]} for g in self.observation_groups]
        self.reflector_attempt = identity
        raw = self._call("reflector", self._messages(self.reflector_policy, body))
        try:
            text, hints = self._parse_maintenance(raw)
        except ValueError:
            self.feedback = "Reflector output unusable; previous observations retained."
            self._event("OM_REFLECTOR_REJECTED")
            return
        pages = [i for g in self.observation_groups for i in g["pages"]]
        self.observation_groups = [
            {
                "text": text,
                "pages": pages,
                "source_ranges": [self.pages[i]["source"] for i in pages],
                "mapping": "coarse_reflection_union",
            }
        ]
        self.continuation_hints = hints
        # A non-shrinking response must not cause repeated reflection on assembly.
        self.reflector_attempt = hashlib.sha256(
            encoded(self.observation_groups).encode()
        ).hexdigest()
        self._event(
            "OM_REFLECTION_ACCEPTED", observations=text, pages=pages, continuationHints=hints
        )

    def _omissions(self, ids: list[int]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for i in sorted(ids):
            source = self.pages[i]["source"]
            if (
                rows
                and rows[-1]["page_end"] + 1 == i
                and rows[-1]["source"]["ref"] == source["ref"]
            ):
                rows[-1]["page_end"] = i
                rows[-1]["source"]["length"] += source["length"]
            else:
                rows.append({"page_start": i, "page_end": i, "source": dict(source)})
        return rows

    def _actor_input(self) -> tuple[tuple[dict[str, str], ...], list[int]]:
        body: dict[str, Any] = {
            "observations": self.observation_groups,
            "continuationHints": self.continuation_hints,
            "raw_tail": [],
            "omitted_pages": [],
            "feedback": self.feedback,
            "source_catalog": self.source_entries(),
            "goal_revision": self.goal_revision,
        }
        # Prefer fresh feedback, then unseen pages, then the remaining raw tail.
        unseen = [i for i in self.raw_tail if i not in self.actor_seen_pages]
        order = list(dict.fromkeys([*reversed(unseen), *reversed(self.raw_tail)]))
        included: list[int] = []
        for i in order:
            trial = {**body, "raw_tail": [self.pages[j] for j in sorted([*included, i])]}
            if self._fits(self._messages(self.actor_policy, trial), "actor"):
                included.append(i)
                body = trial
        omitted = [i for i in self.raw_tail if i not in included]
        body["omitted_pages"] = self._omissions(omitted)
        messages = self._messages(self.actor_policy, body)
        # Make room for explicit omission metadata; never mark omitted pages seen.
        while not self._fits(messages, "actor") and included:
            omitted.append(included.pop())
            body["raw_tail"] = [self.pages[j] for j in sorted(included)]
            body["omitted_pages"] = self._omissions(omitted)
            messages = self._messages(self.actor_policy, body)
        if self.raw_tail and not included:
            raise HiAgentError("OM_PROTECTED_INPUT_CAPACITY")
        return messages, included

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        return self._actor_input()[0]

    def _retrieve(self, args: dict[str, Any]) -> str:
        ref, start, length = (
            args.get("ref"),
            args.get("start", 0),
            args.get("length", self.config.page_chars),
        )
        if (
            not isinstance(ref, str)
            or type(start) is not int
            or start < 0
            or type(length) is not int
            or not 1 <= length <= 16000
        ):
            raise HiAgentError("INVALID_OM_READ")
        if ref.startswith("event:"):
            matches = [e for e in self.events if f"event:{e['id']}" == ref]
            if not matches:
                raise HiAgentError("UNPUBLISHED_OM_REFERENCE")
            text = matches[0]["text"]
            return encoded(
                {
                    "ref": ref,
                    "start": start,
                    "text": text[start : start + length],
                    "total_chars": len(text),
                }
            )
        if ref not in {e["ref"] for e in self.source_entries()}:
            raise HiAgentError("UNPUBLISHED_OM_REFERENCE")
        return encoded(self.read_source(ref, start, length))

    def step(self) -> None:
        if self.halted or self.finished or self.phase != "IDLE":
            raise HiAgentError("HOST_NOT_ACTIVE")
        try:
            self.phase = "MAINTENANCE"
            self._assert_sources()
            self._reflect()
            self._observe_pending()
            self._reflect()
            self.phase = "ACTOR"
            messages, included = self._actor_input()
            value = json.loads(self._call("actor", messages))
            if not isinstance(value, dict):
                raise HiAgentError("INVALID_ACTION_ENVELOPE")
            name = value.get("action")
            if not isinstance(name, str):
                raise HiAgentError("INVALID_ACTION_ENVELOPE")
            if "arguments" not in value:
                fields = {
                    "exec": ("command", "timeout_sec"),
                    "read": ("ref", "start", "length"),
                    "retrieve": ("ref", "start", "length"),
                    "final": ("text",),
                }
                value["arguments"] = {k: value[k] for k in fields.get(name, ()) if k in value}
                self._event("OM_ACTOR_NORMALIZED", reason="flat_tool_arguments")
            if not isinstance(value["arguments"], dict):
                raise HiAgentError("INVALID_ACTION_ENVELOPE")
            action: dict[str, Any] = {"action": name, "arguments": value["arguments"]}
            self.actor_seen_pages.update(included)
            self.feedback, self.initialized = "", True
            if action["action"] == "retrieve":
                self._append("recall", self._retrieve(action["arguments"]), action)
            else:
                self.validate_action(action)
                self.phase = "DISPATCH"
                self._event("REAL_DISPATCH_ATTEMPT", action=action)
                observation = self.dispatch(action)
                self._append("tool", observation, action)
                self.finished = action["action"] == "final"
                self._event("REAL_OBSERVATION", action=action, observation=observation)
        except BaseException as exc:
            self.halted = True
            self._event("HOST_STOPPED", error=str(exc), phase=self.phase)
            raise
        finally:
            self.phase = "FAILED" if self.halted else "IDLE"

    def _contract(self) -> dict[str, Any]:
        return {
            "method": METHOD_VERSION,
            "config": asdict(self.config),
            "model_profile": self.model_profile,
            "max_calls": self.max_calls,
            "policy_hash": hashlib.sha256(
                encoded([self.actor_policy, self.summary_policy, self.reflector_policy]).encode()
            ).hexdigest(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "method": METHOD_VERSION,
            "phase": self.phase,
            "halted": self.halted,
            "finished": self.finished,
            "initialized": self.initialized,
            "calls": dict(self.calls),
            "events": self.events,
            "pages": self.pages,
            "raw_tail": self.raw_tail,
            "covered_ranges": self.covered_ranges,
            "actor_seen_pages": sorted(self.actor_seen_pages),
            "observation_groups": self.observation_groups,
            "continuation_hints": self.continuation_hints,
            "observer_attempt": self.observer_attempt,
            "reflector_attempt": self.reflector_attempt,
            "feedback": self.feedback,
            "goal_revision": self.goal_revision,
        }

    def checkpoint(self) -> dict[str, Any]:
        if self.phase != "IDLE" or self.halted:
            raise HiAgentError("CHECKPOINT_REQUIRES_KNOWN_QUIESCENT_BOUNDARY")
        self._assert_sources()
        return copy.deepcopy(
            {"contract": self._contract(), "goal": self.goal, "state": self.snapshot()}
        )

    def restore(self, checkpoint: dict[str, Any]) -> None:
        if self.initialized or any(self.calls.values()):
            raise HiAgentError("RESTORE_REQUIRES_FRESH_HOST")
        if checkpoint.get("contract") != self._contract():
            raise HiAgentError("CHECKPOINT_CONTRACT_MISMATCH")
        state = copy.deepcopy(checkpoint["state"])
        if state.get("phase") != "IDLE" or state.get("halted") is not False:
            raise HiAgentError("CHECKPOINT_HAS_UNRESOLVED_OPERATIONS")
        candidate = copy.copy(self)
        for key in self.snapshot():
            if key != "method":
                setattr(candidate, key, state[key])
        candidate.actor_seen_pages = set(state["actor_seen_pages"])
        ids = set(range(len(candidate.pages)))
        if (
            list(p["id"] for p in candidate.pages) != list(range(len(candidate.pages)))
            or set(candidate.raw_tail) & set(candidate.covered_ranges)
            or set(candidate.raw_tail) | set(candidate.covered_ranges) != ids
            or not candidate.actor_seen_pages <= ids
            or set(candidate.calls) != set(self.calls)
            or any(type(n) is not int or n < 0 for n in candidate.calls.values())
            or sum(candidate.calls.values()) > self.max_calls
        ):
            raise HiAgentError("INVALID_OM_CHECKPOINT")
        candidate._assert_sources()
        if self.goal != checkpoint["goal"]:
            candidate.goal_revision += 1
            candidate.finished = False
            candidate.continuation_hints = {"currentTask": "", "suggestedResponse": ""}
            candidate._append("goal", self.goal)
        self.__dict__.update(candidate.__dict__)
        self._event("CHECKPOINT_RESTORED", method=METHOD_VERSION, goal_revision=self.goal_revision)
