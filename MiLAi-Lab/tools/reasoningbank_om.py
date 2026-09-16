"""Native-agent scope adapter reusing the existing synchronous OM implementation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from milai_lab.methods.observational_capacity import (
    CapacityObservationalMemoryHost,
    CapacityOMConfig,
)
from milai_lab.methods.observational_memory import ObservationalMemoryHost, OMConfig
from milai_lab.methods.reasoning_bank import MemoryCall, MemoryOutputError

OM_ACTOR_POLICY = (
    "Use the observation log and uncompressed prior interaction pages when relevant. "
    "Continuation hints may be outdated; follow the current native task. "
    "Source event references support range readback. Keep the native action and delivery format."
)
COMPACT_SOURCE_POLICY = (
    " An observation's source_ref points to paged provenance JSON, containing original "
    "event references and character ranges. Read that source, then the original event "
    "range when needed. These are coarse source unions, not proof of every summary claim."
)


class CompactProvenanceHost(ObservationalMemoryHost):
    """Keep full provenance in state and expose it by stable, paged references."""

    def __init__(self, *, source_index, **kwargs):
        self.source_index = source_index
        super().__init__(**kwargs)

    def _observation_view(self):
        result = []
        for group in self.observation_groups:
            source = json.dumps(
                {key: value for key, value in group.items() if key != "text"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ref = "om-source:" + hashlib.sha256(source.encode()).hexdigest()
            self.source_index[ref] = source
            result.append({"text": group["text"], "source_ref": ref, "source_chars": len(source)})
        return result


class NativeOMSession:
    method_version = "native-om-compact-v0.2"
    config_class = OMConfig

    def __init__(
        self,
        *,
        state,
        scope,
        provider,
        task_id,
        policy_root: Path,
        emit,
        config=None,
        compact_provenance=False,
    ):
        self.state, self.scope = state, scope
        self.provider, self.task_id, self.emit = provider, task_id, emit
        self.config = self.config_class(**(config or {}))
        self.policy_root = policy_root
        self.native_messages = []
        self.native_tools = None
        self.pending_seen = []
        self.maintenance_failures = []
        self.compact_provenance = compact_provenance
        self.projection_contract = "compact_source_v1" if compact_provenance else "full_source_v1"
        self.actor_policy = OM_ACTOR_POLICY + (COMPACT_SOURCE_POLICY if compact_provenance else "")
        self.source_index = copy.deepcopy(state.get("source_index", {}))

    def _host_class(self):
        return CompactProvenanceHost if self.compact_provenance else ObservationalMemoryHost

    def start(self, task_id, query):
        host_class = self._host_class()
        self.host = host_class(
            goal=query,
            actor_policy=self.actor_policy,
            summary_policy=(self.policy_root / "observer.txt").read_text(),
            reflector_policy=(self.policy_root / "reflector.txt").read_text(),
            generate=lambda call: self.provider.memory_call(
                task_id,
                MemoryCall(
                    call.kind,
                    call.messages,
                    getattr(self.config, f"{call.kind}_output_tokens"),
                    0.0,
                    True,
                ),
            ),
            validate_action=lambda action: None,
            dispatch=lambda action: "",
            source_entries=lambda: [],
            read_source=lambda *args: {},
            count_text=self.provider.count_text,
            count_messages=self.provider.count_messages,
            config=self.config,
            model_profile="Qwen3.6-35B-A3B-FP8",
            max_calls=4096,
            emit=self.emit,
            **({"source_index": self.source_index} if self.compact_provenance else {}),
        )
        if self.state:
            if self.state.get("projection_contract", "full_source_v1") != self.projection_contract:
                raise ValueError("OM_PROJECTION_CONTRACT_MISMATCH")
            if any(
                self.state["scope"].get(key) != self.scope.get(key)
                for key in ("experiment", "method", "model", "domain", "method_version")
            ):
                raise ValueError("CROSS_METHOD_OM_BANK")
            self.host.restore(self.state["checkpoint"])
        self.current_boundary = len(self.host.events)
        self.host.observe("Current native task: " + query)

    def observe(self, kind, text):
        self.host.observe(kind + ":\n" + text)

    def memory_context(self):
        self._maintenance()
        prior = [
            index
            for index in self.host.raw_tail
            if self.host.pages[index]["event"] < self.current_boundary
        ]
        body = {
            "observations": self.host._observation_view(),
            "continuationHints": self.host.continuation_hints,
            "raw_prior_pages": [],
            "omitted_pages": [],
        }
        included = []
        for index in reversed(prior):
            candidate = {
                **body,
                "raw_prior_pages": [self.host.pages[i] for i in sorted([*included, index])],
            }
            if self._fits(candidate):
                included.append(index)
                body = candidate
        omitted = [index for index in prior if index not in included]
        body["omitted_pages"] = self.host._omissions(omitted)
        while not self._fits(body) and included:
            omitted.append(included.pop())
            body["raw_prior_pages"] = [self.host.pages[i] for i in sorted(included)]
            body["omitted_pages"] = self.host._omissions(omitted)
        if not self._fits(body):
            raise ValueError("OM_NATIVE_CONTEXT_CAPACITY")
        # Current-task native history remains complete for every method. OM raw
        # pages of that same history are not duplicated in its memory projection.
        current = [
            i for i in self.host.raw_tail if self.host.pages[i]["event"] >= self.current_boundary
        ]
        self.pending_seen = included + current
        return self.actor_policy + "\n\n" + json.dumps(body, ensure_ascii=False)

    def _fits(self, body):
        text = self.actor_policy + "\n\n" + json.dumps(body, ensure_ascii=False)
        messages = copy.deepcopy(self.native_messages)
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += "\n\n" + text
        else:
            messages.insert(0, {"role": "system", "content": text})
        return (
            self.provider.count_messages(messages, self.native_tools)
            + self.config.actor_output_tokens
            <= self.config.context_tokens
        )

    def mark_seen(self):
        self.host.actor_seen_pages.update(self.pending_seen)

    def _maintenance(self):
        for operation in (self.host._observe_pending, self.host._reflect):
            try:
                operation()
            except MemoryOutputError as error:
                self.maintenance_failures.append(str(error))
                self.emit({"event": "OM_MAINTENANCE_UNAVAILABLE", "reason": str(error)})

    def read(self, ref, start=0, length=None):
        if isinstance(ref, str) and ref.startswith("om-source:"):
            if ref not in self.source_index:
                raise ValueError("UNPUBLISHED_OM_REFERENCE")
            length = self.config.page_chars if length is None else length
            if type(start) is not int or start < 0 or type(length) is not int or length < 1:
                raise ValueError("INVALID_OM_SOURCE_RANGE")
            source = self.source_index[ref]
            end = min(len(source), start + min(length, 16000))
            return {
                "ref": ref,
                "start": start,
                "end": end,
                "total_chars": len(source),
                "text": source[start:end],
                "has_more": end < len(source),
            }
        if not isinstance(ref, str) or not ref.startswith("event:"):
            raise ValueError("UNPUBLISHED_OM_REFERENCE")
        index = int(ref.split(":", 1)[1])
        if not 0 <= index < len(self.host.events):
            raise ValueError("UNPUBLISHED_OM_REFERENCE")
        return json.loads(
            self.host._retrieve(
                {"ref": ref, "start": start, "length": length or self.config.page_chars}
            )
        )

    def finish(self, trajectory, *, commit):
        # Native actions/feedback were appended incrementally. Final delivery was
        # produced by the Actor; the evaluator's score is never passed here.
        self._maintenance()
        value = {
            "scope": self.scope,
            "checkpoint": self.host.checkpoint(),
            "projection_contract": self.projection_contract,
            "source_index": self.source_index,
        }
        if commit:
            self.state.clear()
            self.state.update(copy.deepcopy(value))
        return {
            "status": "OM_TASK_BOUNDARY",
            "committed": commit,
            "maintenance_failures": self.maintenance_failures,
        }

    def checkpoint(self):
        return copy.deepcopy(self.state)


class CapacityProvenanceHost(CapacityObservationalMemoryHost, CompactProvenanceHost):
    """Capacity algorithms with the existing immutable, paged source index."""


class NativeCapacityOMSession(NativeOMSession):
    method_version = "native-om-capacity-v0.3.1"
    config_class = CapacityOMConfig

    def __init__(self, **kwargs):
        if not kwargs.get("compact_provenance"):
            raise ValueError("CAPACITY_OM_REQUIRES_COMPACT_PROVENANCE")
        super().__init__(**kwargs)
        self.projection_contract = "bounded_catalog_v2"
        self.actor_policy += (
            " Omitted prior pages are listed in a paged source catalog; read its source_ref "
            "for original event ranges. In text-only environments, read a source by replying "
            'ONLY <memory_request>{"kind":"read","ref":"PUBLISHED_REFERENCE",'
            '"start":0,"length":4000}</memory_request>.'
        )
        if self.config.actor_output_tokens != 4096:
            raise ValueError("NATIVE_ACTOR_OUTPUT_RESERVE_MISMATCH")
        if self.config.context_tokens > getattr(self.provider, "context", 65536):
            raise ValueError("OM_WINDOW_EXCEEDS_PROVIDER")

    def _host_class(self):
        return CapacityProvenanceHost

    def start(self, task_id, query):
        super().start(task_id, query)
        self.host.validate_capacity()

    def _catalog(self, ids, *, publish=False):
        if not ids:
            return []
        # Exact ranges: after subdivision page IDs need not follow source order.
        rows = [{"page_id": i, "source": self.host.pages[i]["source"]} for i in ids]
        source = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ref = "om-source:" + hashlib.sha256(source.encode()).hexdigest()
        if publish:
            self.source_index[ref] = source
        return [{"source_ref": ref, "source_chars": len(source), "page_count": len(ids)}]

    def _body(self, prior, included=(), *, publish=False):
        selected = set(included)
        return {
            "observations": self.host._observation_view(),
            "continuationHints": self.host.continuation_hints,
            "raw_prior_pages": [self.host.pages[i] for i in prior if i in selected],
            "omitted_pages": self._catalog(
                [i for i in prior if i not in selected], publish=publish
            ),
        }

    def _minimum_projection_tokens(self):
        prior = [
            i for i in self.host.raw_tail if self.host.pages[i]["event"] < self.current_boundary
        ]
        return self._input_tokens(self._body(prior))

    def _input_tokens(self, body):
        text = self.actor_policy + "\n\n" + json.dumps(body, ensure_ascii=False)
        messages = copy.deepcopy(self.native_messages)
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += "\n\n" + text
        else:
            messages.insert(0, {"role": "system", "content": text})
        return self.provider.count_messages(messages, self.native_tools)

    def _fits(self, body):
        return (
            self._input_tokens(body)
            + self.config.actor_output_tokens
            + self.config.measurement_margin_tokens
            <= self.config.context_tokens
        )

    def check_actor_request(self, messages, tools=None):
        count = self.provider.count_messages(messages, tools)
        if (
            count + self.config.actor_output_tokens + self.config.measurement_margin_tokens
            > self.config.context_tokens
        ):
            raise ValueError("OM_FINAL_SERIALIZED_REQUEST_CAPACITY")
        self.emit(
            {
                "event": "OM_ACTOR_CAPACITY",
                "input_tokens": count,
                "output_reserve": self.config.actor_output_tokens,
                "measurement_margin": self.config.measurement_margin_tokens,
            }
        )

    def _maintenance(self):
        self.maintenance_remaining = self.config.maintenance_max_calls
        pressure = (
            self._minimum_projection_tokens()
            + self.config.actor_output_tokens
            + self.config.measurement_margin_tokens
            > self.config.context_tokens
        )
        self._run_maintenance(pressure=pressure)

    def _run_maintenance(self, *, pressure=False):
        while self.maintenance_remaining > 0:
            before_calls = sum(self.host.calls.values())
            before_pages = len(self.host.raw_tail)
            before_tokens = self._minimum_projection_tokens()
            progress = False
            try:
                # Under Actor pressure, reduce the log before admitting new pages.
                progress = self.host.reflect_batch(force=pressure)
                if sum(self.host.calls.values()) == before_calls and not pressure:
                    progress = self.host.observe_batch()
                    # A full previous log can prevent even one Observer page fitting.
                    if (
                        sum(self.host.calls.values()) == before_calls
                        and not progress
                        and self.host.observer_capacity_blocked
                    ):
                        progress = self.host.reflect_batch(force=True)
            except MemoryOutputError as error:
                self.maintenance_failures.append(str(error))
                self.emit({"event": "OM_MAINTENANCE_UNAVAILABLE", "reason": str(error)})
            calls = sum(self.host.calls.values()) - before_calls
            self.maintenance_remaining -= calls
            after_tokens = self._minimum_projection_tokens()
            self.emit(
                {
                    "event": "OM_CAPACITY_PROGRESS",
                    "calls": calls,
                    "pending_pages_before": before_pages,
                    "pending_pages_after": len(self.host.raw_tail),
                    "actor_input_before": before_tokens,
                    "actor_input_after": after_tokens,
                    "actor_target_tokens": self.config.context_tokens
                    - self.config.actor_output_tokens
                    - self.config.measurement_margin_tokens,
                    "remaining_calls": self.maintenance_remaining,
                    "status": "PROGRESS" if progress else "NO_PROGRESS",
                }
            )
            if not progress or not calls:
                break
            if pressure and (
                after_tokens
                + self.config.actor_output_tokens
                + self.config.measurement_margin_tokens
                <= self.config.context_tokens
            ):
                break

    def memory_context(self):
        # Required native facts/tool schema alone must fit; do not compress them.
        native_tokens = self.provider.count_messages(self.native_messages, self.native_tools)
        if (
            native_tokens + self.config.actor_output_tokens + self.config.measurement_margin_tokens
            > self.config.context_tokens
        ):
            raise ValueError("OM_REQUIRED_NATIVE_CONTEXT_CAPACITY")
        self._maintenance()
        prior = [
            i for i in self.host.raw_tail if self.host.pages[i]["event"] < self.current_boundary
        ]
        body = self._body(prior)
        if not self._fits(body):
            self._run_maintenance(pressure=True)
            body = self._body(prior)
        if not self._fits(body):
            raise ValueError("OM_NATIVE_CONTEXT_CAPACITY_AFTER_BOUNDED_MAINTENANCE")
        included = []
        # Prefer the most recent prior pages; the catalog always stays bounded.
        for index in reversed(prior):
            candidate = self._body(prior, [*included, index])
            if not self._fits(candidate):
                break
            included.append(index)
            body = candidate
        current = [
            i for i in self.host.raw_tail if self.host.pages[i]["event"] >= self.current_boundary
        ]
        self.pending_seen = included + current
        body = self._body(prior, included, publish=True)
        return self.actor_policy + "\n\n" + json.dumps(body, ensure_ascii=False)


def om_session_class(config):
    return (
        NativeCapacityOMSession
        if config.get("om_capacity_policy") == "bounded_v1"
        else NativeOMSession
    )


def om_method_version(config):
    policy = config.get("om_capacity_policy", "legacy")
    if policy not in {"legacy", "bounded_v1"}:
        raise ValueError("UNKNOWN_OM_CAPACITY_POLICY")
    if policy == "bounded_v1":
        return NativeCapacityOMSession.method_version
    return (
        NativeOMSession.method_version
        if config.get("om_compact_provenance", False)
        else "OM_SYNC_PORT"
    )
