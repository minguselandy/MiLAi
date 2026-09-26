"""Opt-in M1 request projection and one-generation state/action commit boundary."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import canonical_json
from milai_lab.methods.milai_m1.decision_basis import (
    DecisionDeltaError,
    generation_delta_schema,
    validate_delta,
)
from milai_lab.methods.milai_m1.evidence_view import EvidenceView
from milai_lab.methods.milai_m1.recheck import completion_proof, refresh_rechecks
from milai_lab.methods.milai_m1.state_store import DecisionBasisStore, ScopeKey

M1_RECIPE_ID = "milai-m1-proposition-recheck-json-action-v18"
M1_TRANSPORT_VARIANT = "json_action_proposition_completion_v18"

if TYPE_CHECKING:
    from milai_lab.baselines.langmem_agent import FoundationScope


def m1_action_schema(base: dict[str, Any]) -> dict[str, Any]:
    """Keep the v16 answer/calls catalog; add the v18 delta branches."""
    delta = generation_delta_schema()
    branches = []
    for branch in base["oneOf"]:
        copy = dict(branch)
        branch_delta = delta
        if "calls" in branch["properties"]:
            branch_delta = {"oneOf": [variant for variant in delta["oneOf"]
                                      if variant.get("properties", {}).get(
                                          "clear_reason", {}).get("const") != "task_ended"]}
        copy["properties"] = {
            "decision_delta": branch_delta,
            **branch["properties"],
        }
        copy["required"] = ["decision_delta", *branch["required"]]
        branches.append(copy)
    return {"oneOf": branches}


M1_PROTOCOL = (
    "In the same JSON reply as your normal answer or calls, include decision_delta. "
    "Use null when no action-sensitive current judgment needs a basis. "
    "A set must state a concrete, testable proposition whose alternative would change "
    "a meaningful action, not a topic label. Give action_scope with subject, item, "
    "action_type, critical_parameters; adopted_evidence entries have ref and "
    "support_role (supports_value, constrains_applicability, records_execution, "
    "or contextual); unresolved_gap may be null or a question; status is active or "
    "deferred. Use only e0/e1/... delivered in this request or continued exact c0/c1/...; "
    "availability is not adoption. Set recheck_outcome to null without pending recheck. "
    "With pending recheck, use retained only if the proposition remains the same, changed "
    "only if it changes, and adopt current/new delivered supporting evidence; unresolved "
    "must be deferred and leaves recheck pending. A revision notice does not contain the "
    "new body and does not prove the old proposition false. Obtain evidence through normal "
    "tools if needed. Pending clear requires task_ended with no calls, or "
    "recheck_completed with retained/changed plus full proposition, action_scope, "
    "adopted_evidence, and unresolved_gap. Otherwise use {\"op\":\"clear\"} only "
    "without pending recheck. Do not add a separate State call."
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
        continued = ([item["ref"] for item in basis["adopted_evidence"]
                      if item["ref"] not in handles]
                     if basis is not None else [])
        self._continued_short = {f"c{position}": ref
                                 for position, ref in enumerate(continued)}
        lines = ["Decision context (one optional task-local slot):"]
        if basis is None:
            lines.append("current basis: none")
        else:
            lines.extend([
                "current proposition: " + basis["proposition"],
                "action scope: " + canonical_json(basis["action_scope"]),
                "adopted handles: " + canonical_json([
                    {"ref": next((short for short, ref in {
                        **self._planned_short, **self._continued_short,
                    }.items() if ref == item["ref"]), item["ref"]),
                     "support_role": item["support_role"]}
                    for item in basis["adopted_evidence"]
                ]),
                "unresolved gap: " + canonical_json(basis["unresolved_gap"]),
                "host status: " + basis["host_status"],
                "needs recheck: " + str(basis["needs_recheck"]).lower(),
            ])
            if basis["recheck_reasons"]:
                lines.append("Recheck required: old proposition is not validated "
                             "against current evidence; complete as retained, changed, "
                             "or unresolved. A version change alone proves no new value.")
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
        calls: list[dict[str, Any]] | None = None,
    ) -> str:
        key, thread, public_index = self._active()
        request_id = self.request_id(request_index)
        prior = self.store.receipt(request_id)
        try:
            actual = self.view.request_messages(request_id)
            basis = self.store.get(key)
            if basis is not None and basis["recheck_reasons"]:
                self.store.record_projection(key, request_id)
            delta = validate_delta(raw_delta)
            if (delta is not None and delta.get("clear_reason") == "task_ended"
                    and calls):
                raise DecisionDeltaError("DECISION_TASK_ENDED_WITH_CALLS")
            delivered = self.view.handles(
                actual, thread_id=thread, public_index=public_index,
                request_id=request_id,
            )
            bound: list[dict[str, Any]] = []
            if delta is not None and "adopted_evidence" in delta:
                exact_refs = []
                for adoption in delta["adopted_evidence"]:
                    short = adoption["ref"]
                    ref = self._planned_short.get(short)
                    if ref is not None:
                        if ref not in delivered:
                            raise DecisionDeltaError("DECISION_EVIDENCE_NOT_DELIVERED")
                    else:
                        ref = self._continued_short.get(short)
                        if ref is None:
                            raise DecisionDeltaError("DECISION_EVIDENCE_NOT_DELIVERED")
                    exact_refs.append({"ref": ref,
                                       "support_role": adoption["support_role"]})
                refs = [item["ref"] for item in exact_refs]
                if len(set(refs)) != len(refs):
                    raise DecisionDeltaError("DECISION_EVIDENCE_INVALID")
                delta["adopted_evidence"] = exact_refs
                bound = self.view.bind(refs, delivered, basis)
                for item, adoption in zip(bound, exact_refs, strict=True):
                    item["support_role"] = adoption["support_role"]
                    if item["delivery"] == "continued_exact":
                        item["continuation_request_id"] = request_id
            ack, proof_refs = completion_proof(
                basis, delta, bound, delivered, actual, self.observer.sidecar, key,
            )
            return self.store.apply(key, request_id, receipt_id, delta, bound,
                                    ack, proof_refs)
        except DecisionDeltaError as error:
            if prior is None:
                self.store.record_error(key, request_id, receipt_id, raw_delta,
                                        error.code)
            raise
