"""Opt-in M1 request projection and one-generation state/action commit boundary."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import canonical_json
from milai_lab.methods.milai_m1.decision_basis import DecisionDeltaError, validate_delta
from milai_lab.methods.milai_m1.evidence_view import EvidenceView
from milai_lab.methods.milai_m1.recheck import acknowledgements, refresh_rechecks
from milai_lab.methods.milai_m1.state_store import DecisionBasisStore, ScopeKey

M1_RECIPE_ID = "milai-m1-sparse-decision-json-action-v1"
M1_TRANSPORT_VARIANT = "json_action_decision_delta_v1"

if TYPE_CHECKING:
    from milai_lab.baselines.langmem_agent import FoundationScope


def m1_action_schema(base: dict[str, Any]) -> dict[str, Any]:
    """Keep the v16 answer/calls catalog; add one generation-only delta field."""
    delta = {"oneOf": [
        {"type": "null"},
        {"type": "object", "properties": {"op": {"const": "clear"}},
         "required": ["op"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "set"},
            "decision": {"type": "string"},
            "scope": {"type": "object", "properties": {
                "subject": {"type": "string"},
                "item": {"type": "string"},
                "context": {"type": "string"},
            }, "required": ["subject", "item", "context"],
                "additionalProperties": False},
            "adopted_evidence": {"type": "array", "items": {"type": "string"},
                                 "maxItems": 8},
            "critical_gap": {"type": ["string", "null"]},
            "status": {"enum": ["active", "deferred"]},
        }, "required": ["op", "decision", "scope", "adopted_evidence",
                        "critical_gap", "status"], "additionalProperties": False},
    ]}
    branches = []
    for branch in base["oneOf"]:
        copy = dict(branch)
        copy["properties"] = {
            "decision_delta": delta,
            **branch["properties"],
        }
        copy["required"] = ["decision_delta", *branch["required"]]
        branches.append(copy)
    return {"oneOf": branches}


M1_PROTOCOL = (
    "In the same JSON reply as your normal answer or calls, include decision_delta. "
    "Use null for ordinary turns without a useful action-sensitive ongoing decision. "
    "Use a full set only for a current decision that can change a meaningful next action: "
    '{"op":"set","decision":"...","scope":{"subject":"...","item":"...",'
    '"context":"..."},"adopted_evidence":["e0"],'
    '"critical_gap":null,"status":"active"}. '
    "Use e0/e1/... from this request or c0/c1/... for continued exact evidence. "
    "critical_gap may be a question string; status may be active or deferred. "
    'Use {"op":"clear"} only when that '
    "decision no longer matters. A gap is only a question whose different answers "
    "would change the next meaningful action. Cite only handles listed below or "
    "the continued exact handles in the current basis. A handle being available is not "
    "adoption; include only evidence you actually rely on. A changed memory revision "
    "requires review, not an automatic decision change. Keep normal tool decisions and "
    "answers in this same reply; no extra model call is needed."
)


class M1Controller:
    recipe_id = M1_RECIPE_ID

    def __init__(self, store: DecisionBasisStore, observer: ProvenanceObserver) -> None:
        self.store = store
        self.observer = observer
        self.view = EvidenceView(observer.sidecar)
        self._key: ScopeKey | None = None
        self._thread_id: str | None = None
        self._public_index: int | None = None
        self._planned_short: dict[str, str] = {}
        self._continued_short: dict[str, str] = {}

    def begin_public_message(
        self, scope: FoundationScope, task_id: str, public_index: int,
    ) -> None:
        key: ScopeKey = (scope.run_id, scope.arm_id, scope.user_id, task_id)
        self.store.activate(key)
        self._key = key
        self._thread_id = scope.config()["configurable"]["thread_id"]
        self._public_index = public_index
        refresh_rechecks(self.store, self.observer.sidecar, key)

    def _active(self) -> tuple[ScopeKey, str, int]:
        if self._key is None or self._thread_id is None or self._public_index is None:
            raise ValueError("M1_PUBLIC_MESSAGE_SCOPE_MISSING")
        return self._key, self._thread_id, self._public_index

    def prompt_context(self, planned_messages: list[dict[str, Any]]) -> str:
        key, thread, index = self._active()
        refresh_rechecks(self.store, self.observer.sidecar, key)
        basis = self.store.get(key)
        handles = self.view.handles(planned_messages, thread_id=thread, public_index=index)
        self._planned_short = {f"e{position}": ref for position, ref in enumerate(handles)}
        continued = ([ref for ref in basis["adopted_evidence"] if ref not in handles]
                     if basis is not None else [])
        self._continued_short = {f"c{position}": ref
                                 for position, ref in enumerate(continued)}
        lines = ["Decision context (one optional task-local slot):"]
        if basis is None:
            lines.append("current basis: none")
        else:
            lines.extend([
                "current decision: " + basis["decision"],
                "scope: " + canonical_json(basis["scope"]),
                "adopted handles: " + canonical_json([
                    next((short for short, ref in {
                        **self._planned_short, **self._continued_short,
                    }.items() if ref == adopted), adopted)
                    for adopted in basis["adopted_evidence"]
                ]),
                "critical gap: " + canonical_json(basis["critical_gap"]),
                "host status: " + basis["host_status"],
                "needs recheck: " + str(basis["needs_recheck"]).lower(),
            ])
            for reason in basis["recheck_reasons"]:
                lines.append("recheck reason: " + canonical_json(reason))
        lines.append("available evidence handles in this request (availability is not adoption):")
        lines.extend(f"{short}: {handles[ref]['label']}" for short, ref
                     in self._planned_short.items())
        if not self._planned_short:
            lines.append("none")
        lines.append("new_observation_refs: " + canonical_json([
            short for short, ref in self._planned_short.items()
            if handles[ref]["kind"] == "observation"
            and handles[ref]["new_in_public_message"]
        ]))
        if self._continued_short:
            lines.append("continued exact refs (short label only, body not reread):")
            bindings = {item["ref"]: item for item in basis["adopted_bindings"]} if basis else {}
            lines.extend(f"{short}: {bindings[ref]['label']}" for short, ref
                         in self._continued_short.items())
        return "\n".join(lines)

    def request_id(self, request_index: int) -> str:
        _, thread, public_index = self._active()
        return hashlib.sha256(
            canonical_json([thread, public_index, request_index]).encode()
        ).hexdigest()

    def record_error(
        self, request_index: int, receipt_id: str, raw_delta: Any, code: str,
    ) -> None:
        key, _, _ = self._active()
        self.store.record_error(key, self.request_id(request_index), receipt_id,
                                raw_delta, code)

    def commit(
        self, request_index: int, receipt_id: str, raw_delta: Any,
    ) -> str:
        key, thread, public_index = self._active()
        request_id = self.request_id(request_index)
        prior = self.store.receipt(request_id)
        try:
            delta = validate_delta(raw_delta)
            actual = self.view.request_messages(request_id)
            delivered = self.view.handles(
                actual, thread_id=thread, public_index=public_index,
                request_id=request_id,
            )
            basis = self.store.get(key)
            bound = []
            if delta is not None and delta["op"] == "set":
                exact_refs = []
                for short in delta["adopted_evidence"]:
                    ref = self._planned_short.get(short)
                    if ref is not None:
                        if ref not in delivered:
                            raise DecisionDeltaError("DECISION_EVIDENCE_NOT_DELIVERED")
                    else:
                        ref = self._continued_short.get(short)
                        if ref is None:
                            raise DecisionDeltaError("DECISION_EVIDENCE_NOT_DELIVERED")
                    exact_refs.append(ref)
                if len(set(exact_refs)) != len(exact_refs):
                    raise DecisionDeltaError("DECISION_EVIDENCE_INVALID")
                delta["adopted_evidence"] = exact_refs
                bound = self.view.bind(exact_refs, delivered, basis)
                for item in bound:
                    if item["delivery"] == "continued_exact":
                        item["continuation_request_id"] = request_id
            current_user_ref = next((ref for ref, item in delivered.items()
                                     if item["delivery"] == "current_user"), None)
            ack = acknowledgements(basis, delta, delivered, actual, current_user_ref)
            return self.store.apply(key, request_id, receipt_id, delta, bound, ack)
        except DecisionDeltaError as error:
            if prior is None:
                self.store.record_error(key, request_id, receipt_id, raw_delta,
                                        error.code)
            raise
