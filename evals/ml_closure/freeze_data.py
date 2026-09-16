"""Create and seal the unified lifecycle repair and validation data.

This module is deliberately limited to fixture construction, split/coverage
validation, and hashing.  It does not import a Formation implementation or a
scorer, and it writes Raw/query inputs separately from semantic labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = "milai.memory-lifecycle-data.v0.1"
QUERY_STRATA = (
    "CURRENT_STATE_EXACT_LOOKUP",
    "UPDATE_CORRECTION_CONFLICT_REVOKE",
    "ENTITY_IDENTITY_MULTI_SESSION",
    "EVENT_TIME_ORDER_COUNT",
    "PREFERENCE_INTENT_TEMPORARY",
    "ABSTENTION_MISSING_HARD_NEGATIVE",
)
TRANSITIONS = (
    "ESTABLISHES",
    "UPDATES",
    "CORRECTS",
    "REVOKES",
    "TEMPORARILY_CONSTRAINS",
)


class DataFreezeError(RuntimeError):
    """The pre-treatment lifecycle data contract is invalid."""


@dataclass
class ConversationBuilder:
    split: str
    ordinal: int
    stratum: str
    base_time: datetime
    conversation_id: str = field(init=False)
    scope_id: str = field(init=False)
    turns: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    event_pairs: list[dict[str, Any]] = field(default_factory=list)
    alias_pairs: list[dict[str, Any]] = field(default_factory=list)
    negative_controls: list[dict[str, Any]] = field(default_factory=list)
    replay_steps: list[dict[str, Any]] = field(default_factory=list)
    query: dict[str, Any] | None = None
    query_label: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        prefix = "repair" if self.split == "repair-dev" else "sealed"
        self.conversation_id = f"mlc-{prefix}-{self.ordinal:03d}"
        self.scope_id = f"scope:{self.conversation_id}"

    def turn(self, role: str, content: str) -> str:
        index = len(self.turns)
        evidence_id = f"{self.conversation_id}:e{index}"
        session = 0 if index < 2 else 1
        observed_at = self.base_time + timedelta(hours=index * 6)
        self.turns.append(
            {
                "evidence_id": evidence_id,
                "source_ref": (
                    f"memory://mlc/{self.conversation_id}/session-{session}:t{index}"
                ),
                "session_id": f"{self.conversation_id}:session-{session}",
                "scope_id": self.scope_id,
                "role": role,
                "speaker": role,
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "observed_at": observed_at.isoformat(),
                "content": content,
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "access_decision": "ALLOWED",
                "revoked_at": None,
            }
        )
        if role == "user":
            self._label_first_person(evidence_id, content)
        return evidence_id

    def entity(
        self, evidence_id: str, phrase: str, identity_key: str, *, nth: int = 0
    ) -> str:
        start, end = _span(self._content(evidence_id), phrase, nth=nth)
        entity_id = f"{self.conversation_id}:entity:{len(self.entities)}"
        self.entities.append(
            {
                "entity_id": entity_id,
                "evidence_id": evidence_id,
                "span_start": start,
                "span_end": end,
                "span_text": phrase,
                "identity_key": identity_key,
            }
        )
        return entity_id

    def event(
        self,
        evidence_id: str,
        phrase: str,
        event_type: str,
        event_identity: str,
        *,
        start: str | None,
        end: str | None,
        time_basis: str,
        time_category: str,
        negated: bool = False,
        nth: int = 0,
    ) -> str:
        left, right = _span(self._content(evidence_id), phrase, nth=nth)
        event_id = f"{self.conversation_id}:event:{len(self.events)}"
        self.events.append(
            {
                "event_id": event_id,
                "evidence_id": evidence_id,
                "span_start": left,
                "span_end": right,
                "span_text": phrase,
                "event_type": event_type,
                "event_identity": f"{self.scope_id}:{event_identity}",
                "occurrence_time": {"start": start, "end": end},
                "time_basis": time_basis,
                "time_category": time_category,
                "negated": negated,
            }
        )
        return event_id

    def state(
        self,
        evidence_id: str,
        phrase: str,
        predicate: str,
        value: Any,
        modality: str,
        disposition: str = "GOVERNED_REVIEW_REQUIRED",
        *,
        nth: int = 0,
    ) -> str:
        left, right = _span(self._content(evidence_id), phrase, nth=nth)
        state_id = f"{self.conversation_id}:state:{len(self.states)}"
        self.states.append(
            {
                "state_id": state_id,
                "evidence_id": evidence_id,
                "span_start": left,
                "span_end": right,
                "span_text": phrase,
                "subject_identity": f"{self.scope_id}:self",
                "predicate": predicate,
                "value": value,
                "modality": modality,
                "promotion_disposition": disposition,
            }
        )
        return state_id

    def transition(
        self,
        evidence_id: str,
        phrase: str,
        predicate: str,
        relation: str,
        previous_value: Any,
        new_value: Any,
        resulting_state_id: str,
        *,
        nth: int = 0,
    ) -> str:
        left, right = _span(self._content(evidence_id), phrase, nth=nth)
        transition_id = f"{self.conversation_id}:transition:{len(self.transitions)}"
        self.transitions.append(
            {
                "transition_id": transition_id,
                "evidence_id": evidence_id,
                "span_start": left,
                "span_end": right,
                "span_text": phrase,
                "subject_identity": f"{self.scope_id}:self",
                "predicate": predicate,
                "relation": relation,
                "previous_value": previous_value,
                "new_value": new_value,
                "resulting_state_id": resulting_state_id,
            }
        )
        self.replay_steps.append(
            {
                "transition_id": transition_id,
                "expected_relation": relation,
                "expected_current": new_value,
            }
        )
        return transition_id

    def ask(
        self,
        question: str,
        *,
        expected_answer: str,
        proof_evidence_ids: list[str],
        operator: str,
        current_state: Any,
        history: list[Any],
        expected_complete: bool = True,
    ) -> None:
        query_id = f"{self.conversation_id}:q0"
        self.query = {
            "query_id": query_id,
            "stratum": self.stratum,
            "question": question,
        }
        self.query_label = {
            "query_id": query_id,
            "expected_answer": expected_answer,
            "proof_obligations": proof_evidence_ids,
            "expected_bindings": proof_evidence_ids,
            "expected_operator": operator,
            "expected_complete": expected_complete,
            "expected_current_state": current_state,
            "expected_history": history,
            "expected_review_disposition": "USER_REVIEW",
        }

    def build(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if len(self.turns) != 4 or self.query is None or self.query_label is None:
            raise DataFreezeError(f"INCOMPLETE_CONVERSATION:{self.conversation_id}")
        return (
            {
                "conversation_id": self.conversation_id,
                "scope_id": self.scope_id,
                "turns": self.turns,
                "queries": [self.query],
            },
            {
                "conversation_id": self.conversation_id,
                "scope_id": self.scope_id,
                "entity_mentions": self.entities,
                "entity_identity_pairs": list(self.alias_pairs),
                "events": self.events,
                "event_identity_pairs": self.event_pairs,
                "state_assertions": self.states,
                "state_transitions": self.transitions,
                "lifecycle_replay": self.replay_steps,
                "negative_controls": self.negative_controls,
                "queries": [self.query_label],
            },
        )

    def _label_first_person(self, evidence_id: str, content: str) -> None:
        for matched in list(
            re.finditer(r"\b(?:I|me|my|myself)\b", content, re.IGNORECASE)
        )[:4]:
            entity_id = f"{self.conversation_id}:entity:{len(self.entities)}"
            self.entities.append(
                {
                    "entity_id": entity_id,
                    "evidence_id": evidence_id,
                    "span_start": matched.start(),
                    "span_end": matched.end(),
                    "span_text": matched.group(0),
                    "identity_key": f"{self.scope_id}:self",
                }
            )

    def _content(self, evidence_id: str) -> str:
        return next(
            turn["content"] for turn in self.turns if turn["evidence_id"] == evidence_id
        )


def build_split(
    split: str, count_per_stratum: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_conversations: list[dict[str, Any]] = []
    label_conversations: list[dict[str, Any]] = []
    base = datetime(2026, 4 if split == "repair-dev" else 6, 1, 9, tzinfo=UTC)
    ordinal = 0
    factories = (
        _current_state,
        _updates,
        _identity,
        _event_time,
        _preference,
        _abstention,
    )
    for stratum, factory in zip(QUERY_STRATA, factories, strict=True):
        for local_index in range(count_per_stratum):
            builder = ConversationBuilder(
                split, ordinal, stratum, base + timedelta(days=ordinal)
            )
            factory(builder, local_index, split)
            raw, labels = builder.build()
            raw_conversations.append(raw)
            label_conversations.append(labels)
            ordinal += 1
    _finish_identity_pairs(label_conversations)
    return (
        {"schema": SCHEMA, "split": split, "conversations": raw_conversations},
        {"schema": SCHEMA, "split": split, "conversations": label_conversations},
    )


def _current_state(b: ConversationBuilder, i: int, split: str) -> None:
    cities = _values(
        split,
        [
            "Lisbon",
            "Kyoto",
            "Nairobi",
            "Tallinn",
            "Quito",
            "Osaka",
            "Dublin",
            "Taipei",
            "Lima",
            "Prague",
        ],
        ["Bristol", "Turin", "Busan"],
    )
    jobs = _values(
        split,
        [
            "architect",
            "librarian",
            "chemist",
            "designer",
            "teacher",
            "editor",
            "analyst",
            "nurse",
            "engineer",
            "curator",
        ],
        ["planner", "baker", "translator"],
    )
    city, job = cities[i], jobs[i]
    e0 = b.turn("user", f"I currently live in {city}.")
    b.turn("assistant", "Thanks, I will treat that as user-provided information.")
    e2 = b.turn("user", f"My occupation is {job}, and I still call {city} home.")
    b.turn("assistant", "Understood.")
    s0 = b.state(e0, f"live in {city}", "residence", {"location": city}, "ASSERTED")
    b.transition(
        e0, f"live in {city}", "residence", "ESTABLISHES", None, {"location": city}, s0
    )
    s1 = b.state(e2, f"occupation is {job}", "occupation", {"title": job}, "ASSERTED")
    b.transition(
        e2,
        f"occupation is {job}",
        "occupation",
        "ESTABLISHES",
        None,
        {"title": job},
        s1,
    )
    b.state(e2, f"call {city} home", "residence", {"location": city}, "ASSERTED")
    b.ask(
        "Where do I currently live?",
        expected_answer=city,
        proof_evidence_ids=[e0, e2],
        operator="LOOKUP_CURRENT",
        current_state={"residence": city},
        history=[city],
    )


def _updates(b: ConversationBuilder, i: int, split: str) -> None:
    old_cities = _values(
        split,
        [
            "Riga",
            "Bern",
            "Perth",
            "Seoul",
            "Accra",
            "Ghent",
            "Oslo",
            "Lyon",
            "Pune",
            "Graz",
        ],
        ["Leeds", "Bonn", "Kobe"],
    )
    new_cities = _values(
        split,
        [
            "Vilnius",
            "Basel",
            "Darwin",
            "Incheon",
            "Kumasi",
            "Bruges",
            "Bergen",
            "Nice",
            "Surat",
            "Salzburg",
        ],
        ["York", "Mainz", "Nara"],
    )
    old, new = old_cities[i], new_cities[i]
    mode = i if split != "repair-dev" else (0, 3, 6)[i]
    if mode % 10 < 3:
        e0 = b.turn("user", f"I live in {old}.")
        b.turn("assistant", "I noted the location you supplied.")
        day = 10 + i
        phrase = f"moved from {old} to {new}"
        e2 = b.turn("user", f"On January {day}, 2026, I moved from {old} to {new}.")
        b.turn("assistant", "I understand that this updates the earlier location.")
        s0 = b.state(e0, f"live in {old}", "residence", {"location": old}, "ASSERTED")
        b.transition(
            e0,
            f"live in {old}",
            "residence",
            "ESTABLISHES",
            None,
            {"location": old},
            s0,
        )
        s1 = b.state(e2, new, "residence", {"location": new}, "ASSERTED")
        b.transition(
            e2, phrase, "residence", "UPDATES", {"location": old}, {"location": new}, s1
        )
        b.event(
            e2,
            phrase,
            "move",
            "move-residence",
            start=f"2026-01-{day:02d}T00:00:00+00:00",
            end=f"2026-01-{day:02d}T00:00:00+00:00",
            time_basis="EXPLICIT_EVENT_TIME",
            time_category="EXPLICIT",
        )
        answer, history = new, [old, new]
    elif mode % 10 < 6:
        e0 = b.turn("user", f"I said I lived in {new}.")
        b.turn("assistant", "I recorded what you said.")
        phrase = f"Correction: I do not live in {new}; I live in {old}"
        e2 = b.turn("user", phrase + ".")
        b.turn("assistant", "I will preserve the correction and its provenance.")
        s0 = b.state(e0, f"lived in {new}", "residence", {"location": new}, "ASSERTED")
        b.transition(
            e0,
            f"lived in {new}",
            "residence",
            "ESTABLISHES",
            None,
            {"location": new},
            s0,
        )
        s1 = b.state(e2, f"live in {old}", "residence", {"location": old}, "ASSERTED")
        b.transition(
            e2,
            phrase,
            "residence",
            "CORRECTS",
            {"location": new},
            {"location": old},
            s1,
        )
        b.event(
            e2,
            f"do not live in {new}",
            "move",
            "negated-move",
            start=None,
            end=None,
            time_basis="UNRESOLVED",
            time_category="AMBIGUOUS",
            negated=True,
        )
        answer, history = old, [new, old]
    elif mode % 10 < 9:
        items = _values(
            split,
            [
                "peanuts",
                "latex",
                "shellfish",
                "sesame",
                "pollen",
                "nickel",
                "almonds",
                "wool",
                "soy",
                "dust",
            ],
            ["mango", "cobalt", "oats"],
        )
        item = items[i]
        e0 = b.turn("user", f"I am allergic to {item}.")
        b.turn("assistant", "I noted the asserted allergy.")
        phrase = f"That {item} allergy was incorrect; I revoke it"
        e2 = b.turn("user", phrase + ".")
        b.turn("assistant", "I will no longer treat it as current.")
        s0 = b.state(e0, f"allergic to {item}", "allergy", {"item": item}, "ASSERTED")
        b.transition(
            e0,
            f"allergic to {item}",
            "allergy",
            "ESTABLISHES",
            None,
            {"item": item},
            s0,
        )
        s1 = b.state(e2, phrase, "allergy", None, "ASSERTED")
        b.transition(e2, phrase, "allergy", "REVOKES", {"item": item}, None, s1)
        answer, history = "no current allergy on record", [{"item": item}, None]
    else:
        e0 = b.turn("user", f"I live in {old}.")
        b.turn("assistant", "I noted your usual residence.")
        phrase = f"Until September 18, 2026, I am staying in {new}"
        e2 = b.turn("user", phrase + " for a project.")
        b.turn(
            "assistant",
            "I will keep the temporary interval distinct from your usual home.",
        )
        s0 = b.state(e0, f"live in {old}", "residence", {"location": old}, "ASSERTED")
        b.transition(
            e0,
            f"live in {old}",
            "residence",
            "ESTABLISHES",
            None,
            {"location": old},
            s0,
        )
        s1 = b.state(
            e2,
            f"staying in {new}",
            "temporary_location",
            {"location": new},
            "TEMPORARY",
        )
        b.transition(
            e2,
            phrase,
            "temporary_location",
            "TEMPORARILY_CONSTRAINS",
            None,
            {"location": new},
            s1,
        )
        answer, history = new, [old, {"temporary": new}]
    b.ask(
        "What location or allergy state is current after my latest change?",
        expected_answer=answer,
        proof_evidence_ids=[e0, e2],
        operator="LOOKUP_CURRENT_WITH_HISTORY",
        current_state=answer,
        history=history,
    )


def _identity(b: ConversationBuilder, i: int, split: str) -> None:
    first = _values(
        split,
        [
            "Alex",
            "Jordan",
            "Taylor",
            "Casey",
            "Morgan",
            "Robin",
            "Jamie",
            "Avery",
            "Riley",
            "Cameron",
        ],
        ["Devon", "Skyler", "Quinn"],
    )[i]
    surname = _values(
        split,
        [
            "Morgan",
            "Lee",
            "Patel",
            "Ng",
            "Silva",
            "Khan",
            "Chen",
            "Brown",
            "Kim",
            "Garcia",
        ],
        ["Stone", "Meyer", "Ito"],
    )[i]
    other_surname = _values(
        split,
        [
            "Rivera",
            "Park",
            "Shah",
            "Wu",
            "Costa",
            "Ali",
            "Lin",
            "Green",
            "Choi",
            "Lopez",
        ],
        ["Reed", "Klein", "Sato"],
    )[i]
    full, other = f"{first} {surname}", f"{first} {other_surname}"
    day, other_day = 3 + i, 18 + i
    phrase0 = f"{full} and I attended the Atlas workshop on February {day}, 2026"
    e0 = b.turn("user", f"My colleague {phrase0}.")
    b.turn("assistant", "Thanks for distinguishing the person and event.")
    phrase1 = (
        f"{surname} and I attended that same Atlas workshop on February {day}, 2026"
    )
    phrase2 = f"my dentist {other} attended a different Atlas workshop on February {other_day}, 2026"
    e2 = b.turn("user", f"{phrase1}; {phrase2}.")
    b.turn("assistant", "I will not merge the two people or the two workshops.")
    full_id = b.entity(e0, full, f"{b.scope_id}:person:{full.casefold()}")
    alias_id = b.entity(e2, surname, f"{b.scope_id}:person:{full.casefold()}")
    other_id = b.entity(e2, other, f"{b.scope_id}:person:{other.casefold()}")
    b.alias_pairs.extend(
        (
            {"left": full_id, "right": alias_id, "same": True, "kind": "ALIAS"},
            {
                "left": full_id,
                "right": other_id,
                "same": False,
                "kind": "SAME_FIRST_NAME_HARD_NEGATIVE",
            },
        )
    )
    t0 = f"2026-02-{day:02d}T00:00:00+00:00"
    t1 = f"2026-02-{other_day:02d}T00:00:00+00:00"
    event0 = b.event(
        e0,
        phrase0,
        "attend",
        f"atlas-workshop:{day}",
        start=t0,
        end=t0,
        time_basis="EXPLICIT_EVENT_TIME",
        time_category="EXPLICIT",
    )
    event1 = b.event(
        e2,
        phrase1,
        "attend",
        f"atlas-workshop:{day}",
        start=t0,
        end=t0,
        time_basis="EXPLICIT_EVENT_TIME",
        time_category="EXPLICIT",
    )
    event2 = b.event(
        e2,
        phrase2,
        "attend",
        f"atlas-workshop:{other_day}",
        start=t1,
        end=t1,
        time_basis="EXPLICIT_EVENT_TIME",
        time_category="EXPLICIT",
    )
    b.event_pairs.extend(
        (
            {"left": event0, "right": event1, "same": True},
            {"left": event0, "right": event2, "same": False},
        )
    )
    b.ask(
        "Did my colleague and my dentist attend the same Atlas workshop?",
        expected_answer="No; the colleague's repeated mention is one event and the dentist attended a distinct event.",
        proof_evidence_ids=[e0, e2],
        operator="COMPARE_EVENT_IDENTITY",
        current_state={"same_event": False},
        history=[full, surname, other],
    )


def _event_time(b: ConversationBuilder, i: int, split: str) -> None:
    anchors = _values(
        split,
        [
            "Orion",
            "Maple",
            "Cedar",
            "Harbor",
            "Summit",
            "Aurora",
            "Juniper",
            "Quartz",
            "Willow",
            "Nimbus",
        ],
        ["Delta", "Saffron", "Comet"],
    )
    places = _values(
        split,
        [
            "museum",
            "gallery",
            "library",
            "garden",
            "aquarium",
            "market",
            "theater",
            "archive",
            "studio",
            "observatory",
        ],
        ["fort", "mill", "planetarium"],
    )
    anchor, place = anchors[i], places[i]
    day = 2 + i
    phrase0 = f"attended the {anchor} workshop on March {day}, 2026"
    e0 = b.turn("user", f"I {phrase0}.")
    b.turn("assistant", "I noted the event date from your statement.")
    phrase1 = f"Two days after the {anchor} workshop, I visited the {anchor} {place}"
    e2 = b.turn("user", phrase1 + ".")
    b.turn("assistant", "I will keep the occurrence date separate from message time.")
    start0 = f"2026-03-{day:02d}T00:00:00+00:00"
    start1 = f"2026-03-{day + 2:02d}T00:00:00+00:00"
    event0 = b.event(
        e0,
        phrase0,
        "attend",
        f"{anchor.casefold()}-workshop",
        start=start0,
        end=start0,
        time_basis="EXPLICIT_EVENT_TIME",
        time_category="EXPLICIT",
    )
    event1 = b.event(
        e2,
        phrase1,
        "visit",
        f"{anchor.casefold()}-{place}",
        start=start1,
        end=start1,
        time_basis="INFERRED_EVENT_TIME",
        time_category="RELATIVE_CROSS_EVIDENCE",
    )
    b.event_pairs.append({"left": event0, "right": event1, "same": False})
    repeat_phrase = f"attended that same {anchor} workshop on March {day}, 2026"
    b.turns[2]["content"] += f" For clarity, I {repeat_phrase}."
    event2 = b.event(
        e2,
        repeat_phrase,
        "attend",
        f"{anchor.casefold()}-workshop",
        start=start0,
        end=start0,
        time_basis="EXPLICIT_EVENT_TIME",
        time_category="EXPLICIT",
    )
    b.event_pairs.append({"left": event0, "right": event2, "same": True})
    if i < 6:
        range_phrase = f"worked at the {anchor} expo from June {3 + i}, 2026 through June {8 + i}, 2026"
        b.turns[2]["content"] += f" I also {range_phrase}."
        b.event(
            e2,
            range_phrase,
            "work",
            f"{anchor.casefold()}-expo",
            start=f"2026-06-{3 + i:02d}T00:00:00+00:00",
            end=f"2026-06-{8 + i:02d}T00:00:00+00:00",
            time_basis="EXPLICIT_EVENT_TIME",
            time_category="INTERVAL_DURATIVE",
        )
    b.ask(
        "Which happened first, the workshop or the visit, and when was the visit?",
        expected_answer=f"The workshop happened first; the visit was on March {day + 2}, 2026.",
        proof_evidence_ids=[e0, e2],
        operator="TEMPORAL_ORDER",
        current_state={"visit_date": start1},
        history=[start0, start1],
    )


def _preference(b: ConversationBuilder, i: int, split: str) -> None:
    preferred = _values(
        split,
        [
            "aisle seats",
            "quiet cafés",
            "train travel",
            "dark chocolate",
            "morning runs",
            "paper books",
            "small hotels",
            "green tea",
            "documentaries",
            "window desks",
        ],
        ["spicy noodles", "late flights", "acoustic music"],
    )[i]
    other = _values(
        split,
        [
            "window seats",
            "busy cafés",
            "driving",
            "milk chocolate",
            "evening runs",
            "e-books",
            "resorts",
            "coffee",
            "sitcoms",
            "open-plan desks",
        ],
        ["sweet noodles", "early flights", "electronic music"],
    )[i]
    cities = _values(
        split,
        [
            "Bath",
            "Kochi",
            "Hobart",
            "Malmö",
            "Cusco",
            "Dakar",
            "Sendai",
            "Utrecht",
            "Brno",
            "Valencia",
        ],
        ["Nancy", "Daegu", "Porto"],
    )
    city = cities[i]
    phrase0 = f"prefer {preferred} over {other}"
    e0 = b.turn("user", f"I {phrase0}.")
    b.turn("assistant", "I noted the preference as user-supplied.")
    temporary_case = i < 4 if split != "repair-dev" else i == 0
    if temporary_case:
        phrase1 = f"Until October {10 + i}, 2026, I am staying in {city}"
        e2 = b.turn("user", phrase1 + " while finishing a course.")
        modality, predicate, value = (
            "TEMPORARY",
            "temporary_location",
            {"location": city},
        )
        state_phrase = f"staying in {city}"
        relation = "TEMPORARILY_CONSTRAINS"
        answer = f"{preferred}; temporarily in {city}"
    else:
        actions = _values(
            split,
            [
                "learn pottery",
                "visit Iceland",
                "join a choir",
                "study Italian",
                "build a telescope",
                "take a first-aid course",
                "grow herbs",
                "write a novella",
                "cycle the coast",
                "learn sign language",
            ],
            ["restore a chair", "visit Jeju", "learn cello"],
        )
        action = actions[i]
        phrase1 = f"I am planning to {action}"
        e2 = b.turn("user", phrase1 + ".")
        modality, predicate, value = "INTENT", "current_intent", {"action": action}
        state_phrase = phrase1
        relation = "ESTABLISHES"
        answer = f"{preferred}; intent to {action}"
    b.turn(
        "assistant", "Understood; an intent or temporary state is not a permanent fact."
    )
    s0 = b.state(
        e0, phrase0, "preference", {"preferred": preferred, "over": other}, "PREFERENCE"
    )
    b.transition(
        e0,
        phrase0,
        "preference",
        "ESTABLISHES",
        None,
        {"preferred": preferred, "over": other},
        s0,
    )
    s1 = b.state(
        e2,
        state_phrase,
        predicate,
        value,
        modality,
        "QUERY_LOCAL_ONLY" if modality == "INTENT" else "GOVERNED_REVIEW_REQUIRED",
    )
    b.transition(e2, phrase1, predicate, relation, None, value, s1)
    b.ask(
        "What preference and short-lived plan or constraint should be recalled?",
        expected_answer=answer,
        proof_evidence_ids=[e0, e2],
        operator="COMPOSE_STATE",
        current_state={"preference": preferred, predicate: value},
        history=[preferred, value],
    )


def _abstention(b: ConversationBuilder, i: int, split: str) -> None:
    events = _values(
        split,
        [
            "gala",
            "marathon",
            "conference",
            "reunion",
            "festival",
            "retreat",
            "audition",
            "summit",
            "ceremony",
            "fair",
        ],
        ["parade", "hackathon", "concert"],
    )
    event_name = events[i]
    phrase0 = f"may attend the {event_name} sometime next spring"
    e0 = b.turn("user", f"I {phrase0}, but the date is unresolved.")
    assistant_text = "You definitely live in Oslo and love olives."
    e1 = b.turn("assistant", assistant_text)
    e2 = b.turn(
        "user",
        "That was not information I provided about myself; do not treat it as my memory.",
    )
    b.turn(
        "assistant", "Understood; I will not promote my own statement as user evidence."
    )
    b.event(
        e0,
        phrase0,
        "attend",
        f"possible-{event_name}",
        start=None,
        end=None,
        time_basis="UNRESOLVED",
        time_category="AMBIGUOUS",
    )
    b.negative_controls.append(
        {
            "kind": "ASSISTANT_CONTAMINATION",
            "evidence_id": e1,
            "forbidden_text": assistant_text,
        }
    )
    b.negative_controls.append(
        {
            "kind": "MISSING_ANSWER",
            "evidence_id": e2,
            "forbidden_predicate": "passport_number",
        }
    )
    b.ask(
        "What is my passport number?",
        expected_answer="ABSTAIN",
        proof_evidence_ids=[],
        operator="ABSTAIN",
        current_state=None,
        history=[],
        expected_complete=False,
    )


def _finish_identity_pairs(conversations: list[dict[str, Any]]) -> None:
    first_self: list[str] = []
    for conversation in conversations:
        mentions = conversation["entity_mentions"]
        self_mentions = [
            item for item in mentions if item["identity_key"].endswith(":self")
        ]
        if len(self_mentions) >= 2:
            conversation["entity_identity_pairs"].append(
                {
                    "left": self_mentions[0]["entity_id"],
                    "right": self_mentions[1]["entity_id"],
                    "same": True,
                    "kind": "FIRST_PERSON_COREFERENCE",
                }
            )
        if self_mentions:
            first_self.append(self_mentions[0]["entity_id"])
    by_id = {item["conversation_id"]: item for item in conversations}
    entity_owner = {
        mention["entity_id"]: conversation["conversation_id"]
        for conversation in conversations
        for mention in conversation["entity_mentions"]
    }
    for index in range(0, len(first_self) - 1, 2):
        left, right = first_self[index], first_self[index + 1]
        owner = entity_owner[left]
        by_id[owner]["entity_identity_pairs"].append(
            {
                "left": left,
                "right": right,
                "same": False,
                "kind": "CROSS_SCOPE_HARD_NEGATIVE",
            }
        )


def _values(split: str, sealed: list[str], repair: list[str]) -> list[str]:
    return repair if split == "repair-dev" else sealed


def _span(content: str, phrase: str, *, nth: int = 0) -> tuple[int, int]:
    matches = [
        matched.start()
        for matched in re.finditer(re.escape(phrase), content, re.IGNORECASE)
    ]
    if nth >= len(matches):
        raise DataFreezeError(f"LABEL_SPAN_NOT_FOUND:{phrase}")
    return matches[nth], matches[nth] + len(phrase)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _coverage(labels: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    conversations = labels["conversations"]
    transitions = [row for item in conversations for row in item["state_transitions"]]
    times = [row for item in conversations for row in item["events"]]
    query_counts = {
        stratum: sum(
            query["stratum"] == stratum
            for item in raw["conversations"]
            for query in item["queries"]
        )
        for stratum in QUERY_STRATA
    }
    identity_pairs = [
        row for item in conversations for row in item["entity_identity_pairs"]
    ]
    event_pairs = [
        row for item in conversations for row in item["event_identity_pairs"]
    ]
    return {
        "conversations": len(raw["conversations"]),
        "turns": sum(len(item["turns"]) for item in raw["conversations"]),
        "query_groups": sum(len(item["queries"]) for item in raw["conversations"]),
        "query_strata": query_counts,
        "entity_mentions": sum(len(item["entity_mentions"]) for item in conversations),
        "identity_positive_pairs": sum(bool(row["same"]) for row in identity_pairs),
        "identity_hard_negative_pairs": sum(
            not bool(row["same"]) for row in identity_pairs
        ),
        "event_mentions": len(times),
        "same_event_pairs": sum(bool(row["same"]) for row in event_pairs),
        "distinct_event_pairs": sum(not bool(row["same"]) for row in event_pairs),
        "occurrence_time_labels": len(times),
        "occurrence_explicit": sum(row["time_category"] == "EXPLICIT" for row in times),
        "occurrence_relative_cross": sum(
            row["time_category"] == "RELATIVE_CROSS_EVIDENCE" for row in times
        ),
        "occurrence_interval": sum(
            row["time_category"] == "INTERVAL_DURATIVE" for row in times
        ),
        "occurrence_ambiguous": sum(
            row["time_category"] == "AMBIGUOUS" for row in times
        ),
        "state_assertions": sum(
            len(item["state_assertions"]) for item in conversations
        ),
        "state_transitions": len(transitions),
        "transition_relations": {
            relation: sum(row["relation"] == relation for row in transitions)
            for relation in TRANSITIONS
        },
        "lifecycle_replay_sequences": sum(
            bool(item["lifecycle_replay"]) for item in conversations
        ),
        "assistant_contamination_controls": sum(
            row["kind"] == "ASSISTANT_CONTAMINATION"
            for item in conversations
            for row in item["negative_controls"]
        ),
    }


def _validate(split: str, coverage: dict[str, Any]) -> None:
    minimum = 3 if split == "repair-dev" else 10
    if any(count < minimum for count in coverage["query_strata"].values()):
        raise DataFreezeError("QUERY_STRATUM_COVERAGE_INADEQUATE")
    if split == "repair-dev":
        if coverage["conversations"] < 16:
            raise DataFreezeError("REPAIR_CONVERSATION_DENOMINATOR_INADEQUATE")
        return
    requirements = {
        "conversations": 48,
        "turns": 192,
        "query_groups": 60,
        "entity_mentions": 40,
        "identity_positive_pairs": 20,
        "identity_hard_negative_pairs": 20,
        "event_mentions": 40,
        "same_event_pairs": 16,
        "distinct_event_pairs": 16,
        "occurrence_time_labels": 30,
        "occurrence_explicit": 8,
        "occurrence_relative_cross": 8,
        "occurrence_interval": 6,
        "occurrence_ambiguous": 6,
        "state_assertions": 30,
        "state_transitions": 24,
        "lifecycle_replay_sequences": 16,
    }
    failed = {
        name: (coverage[name], threshold)
        for name, threshold in requirements.items()
        if coverage[name] < threshold
    }
    failed.update(
        {
            f"transition:{name}": (count, 3)
            for name, count in coverage["transition_relations"].items()
            if count < 3
        }
    )
    if failed:
        raise DataFreezeError(f"SEALED_COVERAGE_INADEQUATE:{failed}")


def freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    dataset_dir = root / "evals" / "datasets" / "ml_closure"
    run_dir = root / "var" / "ml_closure" / "ml-closure-20260830-001"
    scorer = root / "evals" / "ml_closure" / "score.py"
    treatment = (
        root
        / "runtime"
        / "src"
        / "milai"
        / "application"
        / "formation_generalization.py"
    )
    if scorer.exists() or treatment.exists():
        raise DataFreezeError("SCORER_OR_TREATMENT_EXISTED_BEFORE_SEAL")
    dataset_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    identities: dict[str, Any] = {}
    for split, count in (("repair-dev", 3), ("sealed-validation", 10)):
        raw, labels = build_split(split, count)
        # Alias pairs are already carried on the builders during scenario creation;
        # build_split materializes them below before coverage is checked.
        coverage = _coverage(labels, raw)
        _validate(split, coverage)
        raw_path = dataset_dir / f"{split}.raw.json"
        labels_path = dataset_dir / f"{split}.labels.json"
        raw_path.write_bytes(_canonical_bytes(raw))
        labels_path.write_bytes(_canonical_bytes(labels))
        identities[split] = {
            "raw_path": str(raw_path.relative_to(root)),
            "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "labels_path": str(labels_path.relative_to(root)),
            "labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
            "coverage": coverage,
        }
    seal = {
        "schema": "milai.memory-lifecycle-data-seal.v0.1",
        "created_at": datetime.now(UTC).isoformat(),
        "execution_authority": "USER_EXPLICIT_20260830_MLC_EXECUTE",
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scorer_absent_before_seal": True,
        "treatment_absent_before_seal": True,
        "formal_holdout_used": False,
        "splits": identities,
    }
    seal["seal_digest"] = _digest(seal)
    seal_path = dataset_dir / "seal.json"
    seal_path.write_bytes(_canonical_bytes(seal))
    return seal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    seal = freeze(args.root)
    print(json.dumps(seal, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
