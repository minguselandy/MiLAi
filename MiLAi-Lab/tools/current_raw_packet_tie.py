"""Isolated F1 tie policy; retain the frozen baseline outside an exact raw-packet tie."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, cast

from milai_lab.methods import memory_control
from milai_lab.methods.evidence_selection import coverage, original_terms, request_terms
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState

PROFILE = "rules_current_raw_packet_lexical_tie_v1"
OriginalSelector = Callable[[MemoryControlState, list[MemoryAction], int], str | None]


def packet_for_action(state: MemoryControlState, action: MemoryAction) -> list[dict[str, Any]]:
    if not action.parameters:
        return state.visible_evidence
    observed = {int(m["label"][1:]): m
                for m in [*state.visible_evidence, *(state.observed_evidence or [])]}
    current = [int(m["label"][1:]) for m in state.visible_evidence]
    retrieved = {m["item_index"]: m["evidence"] for m in state.retrieved_scopes or []}
    narrowed = action.parameters.get("retrieved_scope_indices", [])
    return [retrieved[i] if i in narrowed else observed[i]
            for i in action.parameters.get("delivery_indices", current)]


def raw_coverage(state: MemoryControlState, action: MemoryAction) -> float:
    known: set[str] = set()
    for material in state.task.get("known_evidence", []):
        known.update(original_terms(material))
    terms = known.union(*(original_terms(m) for m in packet_for_action(state, action)))
    return coverage(terms, request_terms(state.task))


def current_raw_tie_choice(
    state: MemoryControlState, actions: list[MemoryAction], baseline: str | None,
) -> tuple[str | None, dict[str, Any]]:
    """Only preserve an offered nonempty all-raw current packet on the same lexical score."""
    if any(a.kind != "HANDOFF" for a in actions):
        raise ValueError("Current-raw tie control requires a HANDOFF-only decision menu")
    info: dict[str, Any] = {"baseline": baseline, "selected": baseline, "changed": False,
                            "profile": PROFILE, "scope": "original_route_unchanged"}
    if baseline is None:
        return baseline, info
    current = next((a for a in actions if not a.parameters), None)
    if (current is None or not state.visible_evidence
            or any(m["kind"] != "original_source" for m in state.visible_evidence)):
        return baseline, info
    chosen, = [a for a in actions if a.id == baseline]
    old_score, current_score = raw_coverage(state, chosen), raw_coverage(state, current)
    info.update(baseline_coverage=old_score, current_coverage=current_score,
                current_action=current.id)
    if old_score == current_score:
        info.update(selected=current.id, changed=current.id != baseline,
                    scope="nonempty_all_raw_current_packet_on_exact_lexical_tie")
        return current.id, info
    return baseline, info


@contextmanager
def current_raw_packet_tie(record: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    """Explicit process-local policy variant; restore the frozen function on exit."""
    # This imported binding is the precise frozen RulesMemoryPolicy call site.
    # It is intentionally a process-local extension, not a new runtime export.
    bindings = vars(memory_control)
    original = cast(OriginalSelector, bindings["original_evidence_action"])

    def choose(state: MemoryControlState, actions: list[MemoryAction], reads: int) -> str | None:
        baseline = original(state, actions, reads)
        selected, info = current_raw_tie_choice(state, actions, baseline)
        record({**info, "state": state.project(), "actions": [asdict(a) for a in actions]})
        return selected

    bindings["original_evidence_action"] = choose
    try:
        yield
    finally:
        bindings["original_evidence_action"] = original
