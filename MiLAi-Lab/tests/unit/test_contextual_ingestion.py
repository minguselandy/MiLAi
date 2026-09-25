from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import ValidationError, validate

from milai_lab.methods.contextual_user_memory import ContextualMemory, Observation
from milai_lab.runners.contextual_ingestion import (
    bind_proposal_handles,
    prepare_ingestion,
    proposal_schema,
    resolve_handles,
)


def test_ordinary_delta_handles_use_the_same_schema_and_exact_refs() -> None:
    handles = {
        "r0": {"kind": "record", "ref": "owner/card:current@1"},
        "s0": {"kind": "source", "ref": "owner/source:old"},
        "s1": {"kind": "source", "ref": "owner/source:new"},
        "d0": {"kind": "dependency", "ref": "owner/card:premise@1"},
    }
    schema = proposal_schema(2)
    bind_proposal_handles(schema, handles, "ordinary")
    proposal = {"operations": [{
        "op": "REVISE", "basis_mode": "delta", "target_ref": "r0",
        "content_patch": [{"old": "waiting", "new": "done"}],
        "source_delta": {"add": ["s1"], "remove": ["s0"]},
        "dependency_delta": {"add": [], "remove": ["d0"]},
    }]}
    validate(proposal, schema)
    resolved = resolve_handles(proposal, handles)["operations"][0]
    assert resolved["source_delta"] == {
        "add": ["owner/source:new"], "remove": ["owner/source:old"],
    }
    assert resolved["dependency_delta"]["remove"] == ["owner/card:premise@1"]
    with pytest.raises(ValidationError):
        validate({"operations": [{**proposal["operations"][0],
                                  "source_delta": {"add": ["missing"], "remove": []}}]},
                 schema)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
ingestion = importlib.import_module("contextual_ingestion")


def test_related_original_ranges_enter_the_same_bounded_proposal() -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        profile="support",
    )
    source = memory.publish(
        Observation("old", "Tea at home, coffee at work.", "user", "test", actor_ref="current_user")
    )
    memory.save(
        changeset={
            "groups": [
                {
                    "operations": [
                        {"op": "claim", "alias": "new:tea", "content": "Drinks tea"},
                        {
                            "op": "justification",
                            "target_ref": "new:tea",
                            "polarity": "support",
                            "items": [{"ref": source, "start": 0, "end": 11}],
                        },
                    ]
                }
            ]
        }
    )
    calls = []
    new_source = memory.publish(
        Observation("next", "The next task is at work.", "user", "test", actor_ref="current_user")
    )

    class Host:
        def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            calls.append(json.loads(messages[1]["content"]))
            return {"choices": [{"message": {"content": '{"groups":[]}'}, "finish_reason": "stop"}]}

    result = ingestion.ingest_chunk(
        memory,
        [{"source_ref": new_source, "content": "The next task is at work."}],
        host=Host(),
        prompt="Maintain memory.",
        max_operations=4,
        context_bytes=4000,
        old_source_bytes=2000,
        profile="support",
        emit=lambda event: None,
    )
    assert len(calls) == 1
    evidence = calls[0]["related_original_sources"]
    assert evidence["materials"][0]["content"] == "Tea at home"
    assert evidence["materials"][0]["page"]["end"] == 11
    assert evidence["bytes"] <= 2000
    assert result["status"] == "complete"
    insufficient = ingestion.related_sources(
        memory, [memory.read(result["related_record_refs"][0], include_sources=False)], 1
    )
    assert insufficient["materials"] == []
    assert insufficient["unexpanded"] == [{"ref": source, "start": 0, "end": 11}]


def test_frozen_handle_proposal_resumes_after_one_group_without_regeneration() -> None:
    def embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    memory = ContextualMemory(
        "user", host_id="host", embed=embed, embedding_dimension=2, profile="support"
    )
    source = memory.publish(
        Observation("one", "Tea at home; coffee at work.", "user", "test", actor_ref="current_user")
    )
    observed = [{"source_ref": source, "content": "Tea at home", "start": 0, "end": 11}]
    saved: dict[str, Any] = {}
    requests = 0

    class Host:
        def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            nonlocal requests
            requests += 1
            handle = json.loads(messages[1]["content"])["observations"][0]["source_ref"]
            proposal = {
                "groups": [
                    {
                        "operations": [
                            {
                                "op": "claim",
                                "alias": "new:a",
                                "content": "Tea at home",
                                "source_refs": [handle, handle],
                            },
                            {
                                "op": "justification",
                                "target_ref": "new:a",
                                "polarity": "support",
                                "items": [handle],
                            },
                        ]
                    },
                    {
                        "operations": [
                            {"op": "claim", "alias": "new:b", "content": "Home tea preference"},
                            {
                                "op": "justification",
                                "target_ref": "new:b",
                                "polarity": "support",
                                "items": ["new:a"],
                            },
                        ]
                    },
                ]
            }
            return {
                "choices": [{"message": {"content": json.dumps(proposal)}, "finish_reason": "stop"}]
            }

    def persist(state: dict[str, Any]) -> None:
        saved.update(state=copy.deepcopy(state), checkpoint=memory.checkpoint())

    dispatch = memory.dispatch
    commits = 0

    def interrupted(
        name: str,
        arguments: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        nonlocal commits
        commits += 1
        if commits == 2:
            raise RuntimeError("interrupted before second commit")
        return dispatch(name, arguments, operation_id=operation_id)

    memory.dispatch = interrupted  # type: ignore[method-assign]
    kwargs = dict(
        host=Host(),
        prompt="Maintain memory.",
        max_operations=4,
        context_bytes=4000,
        profile="support",
        emit=lambda event: None,
    )
    with pytest.raises(RuntimeError, match="second commit"):
        ingestion.ingest_chunk(memory, observed, persist=persist, **kwargs)
    assert len(saved["state"]["unit_receipts"]) == 1
    proposal_id = saved["state"]["proposal_id"]
    first_id = saved["state"]["unit_receipts"]["0"]["operation_receipt"]["operation_id"]
    assert first_id == f"ingest:{proposal_id}:0"
    assert saved["state"]["normalizations"][0]["after"] == ["s0"]
    memory = ContextualMemory.restore(
        saved["checkpoint"],
        user_id="user",
        embed=embed,
        embedding_model="embedding",
        embedding_dimension=2,
    )
    result = ingestion.ingest_chunk(
        memory, observed, state=saved["state"], persist=persist, **kwargs
    )
    assert requests == 1
    assert result["maintenance_settled"]
    assert [call["operation_receipt"]["operation_id"] for call in result["calls"]] == [
        first_id,
        f"ingest:{proposal_id}:1",
    ]
    assert len(memory.workspace.cards) == 2
    groups = list(memory.revisions.groups.values())
    assert groups[0].items[0].ref == source
    assert (groups[0].items[0].start, groups[0].items[0].end) == (0, 11)
    assert groups[1].items[0].ref == groups[0].target_ref
    repeated = ingestion.ingest_chunk(memory, observed, state=saved["state"], **kwargs)
    assert repeated["calls"][0]["operation_receipt"]["operation_id"] == first_id
    assert len(memory.workspace.cards) == 2 and requests == 1


def test_unknown_handle_rejects_proposal_without_falling_back_to_source() -> None:
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda t: [[1.0] for _ in t], embedding_dimension=1
    )
    source = memory.publish(
        Observation("one", "Original", "user", "test", actor_ref="current_user")
    )

    class Host:
        def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            schema = kwargs["response_format"]["json_schema"]["schema"]
            validate(
                {
                    "operations": [
                        {
                            "op": "CREATE",
                            "certainty": "explicit",
                            "content": "Valid",
                            "about_ref": "u0",
                            "source_refs": ["s0"],
                        }
                    ]
                },
                schema,
            )
            validate({"operations": [{"op": "NO_CHANGE", "reason": "ALREADY_COVERED"}]}, schema)
            with pytest.raises(ValidationError):
                validate({"operations": [{"op": "RETAIN_SOURCE", "source_ref": "s0"}]}, schema)
            with pytest.raises(ValidationError):
                validate({"operations": [{"op": "NO_CHANGE"}]}, schema)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "operations": [
                                        {
                                            "op": "CREATE",
                                            "certainty": "explicit",
                                            "content": "An interpretation",
                                            "about_ref": "u0",
                                            "source_refs": ["s999"],
                                        },
                                    ]
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    with pytest.raises(ValidationError, match="s999"):
        ingestion.ingest_chunk(
            memory,
            [{"source_ref": source, "content": "Original"}],
            host=Host(),
            prompt="Maintain",
            max_operations=2,
            context_bytes=1000,
            emit=lambda event: None,
        )
    assert not memory.workspace.cards


def test_ordinary_history_no_change_reason_can_follow_independent_write() -> None:
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda t: [[1.0] for _ in t], embedding_dimension=1
    )
    source = memory.publish(
        Observation("one", "Already known", "user", "test", actor_ref="current_user")
    )

    class Host:
        def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "operations": [
                                        {
                                            "op": "CREATE",
                                            "certainty": "explicit",
                                            "content": "Known preference",
                                            "about_ref": "u0",
                                            "source_refs": ["s0"],
                                        },
                                        {"op": "NO_CHANGE", "reason": "ALREADY_COVERED"},
                                    ]
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    result = ingestion.ingest_chunk(
        memory,
        [{"source_ref": source, "content": "Already known"}],
        host=Host(),
        prompt="Maintain",
        max_operations=2,
        context_bytes=1000,
        emit=lambda event: None,
    )
    assert result["maintenance_settled"]
    assert result["calls"][0]["operation_receipt"]["decision"] == "COMMITTED"
    assert result["calls"][1]["proposal_reason"] == "ALREADY_COVERED"
    assert result["calls"][1]["arguments"] == {"op": "NO_CHANGE"}
    assert result["calls"][1]["operation_receipt"]["decision"] == "NO_CHANGE"
    assert len(memory.workspace.cards) == 1


def test_ordinary_old_evidence_speaker_and_independent_dependency_are_bounded() -> None:
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda t: [[1.0] for _ in t], embedding_dimension=1
    )
    premise_source = memory.publish(
        Observation(
            "early", "I use tea.", "user", "test", date="2024-01-01", actor_ref="current_user"
        )
    )
    speaker_source = memory.publish(
        Observation("later", "She uses coffee.", "third_party", "test", date="2024-01-02")
    )
    incoming = memory.publish(
        Observation(
            "new", "I need notes.", "user", "test", date="2024-01-03", actor_ref="current_user"
        )
    )
    premise = memory.save(
        op="CREATE",
        content="The user uses tea.",
        about_ref="current_user",
        source_refs=[premise_source],
        certainty="explicit",
    )["record"]["ref"]
    memory.read(premise, include_sources=False)
    target = memory.save(
        op="CREATE",
        content="She uses coffee.",
        about_ref=f"speaker:{speaker_source}",
        source_refs=[speaker_source],
        dependencies=[premise],
        certainty="explicit",
    )["record"]["ref"]
    memory.suggest_existing_records = (  # type: ignore[method-assign]
        lambda *args, **kwargs: [memory.read(target, include_sources=False)]
    )
    state = prepare_ingestion(
        memory,
        [{"source_ref": incoming, "content": "I need notes."}],
        prompt="Maintain",
        max_operations=3,
        context_bytes=12000,
        emit=lambda event: None,
    )
    payload = json.loads(state["messages"][1]["content"])
    observed = payload["observations"][0]
    assert observed["speaker_ref"] == "u0"
    assert (observed["role"], observed["date"], observed["source_sequence"]) == (
        "user",
        "2024-01-03",
        3,
    )
    old = payload["related_records"][0]
    source = payload["related_original_sources"]["materials"][0]
    dependency = payload["related_dependencies"][0]
    assert list(observed).index("role") < list(observed).index("content")
    assert list(source).index("speaker_ref") < list(source).index("content")
    assert list(old).index("about") < list(old).index("text")
    assert list(dependency).index("about") < list(dependency).index("text")
    speaker = source["speaker_ref"]
    assert speaker.startswith("p")
    assert old["ref"] == "r0" and old["about"] == {
        "kind": "source_speaker",
        "source_role": "third_party",
        "about_ref": speaker,
    }
    assert old["source_refs"] == ["s1"] and old["dependencies"] == ["d0"]
    assert source["ref"] == "s1" and source["speaker_ref"] == speaker
    # A new speaker delivered first must not rename the existing source anchor.
    # Arrival metadata need not be unique; exact source identity remains distinct.
    other = memory.publish(Observation("other", "I use water.", "assistant", "test"), sequence=2)
    later = prepare_ingestion(
        memory,
        [{"source_ref": other, "content": "I use water."}],
        prompt="Maintain",
        max_operations=3,
        context_bytes=12000,
        emit=lambda event: None,
    )
    later_payload = json.loads(later["messages"][1]["content"])
    assert later_payload["related_records"][0]["about"]["about_ref"] == speaker
    assert later_payload["observations"][0]["speaker_ref"] != speaker
    assert (
        source["content"],
        source["role"],
        source["page"]["end"],
        source["source_sequence"],
    ) == ("She uses coffee.", "third_party", 16, 2)
    assert dependency["ref"] == "d0" and dependency["text"] == "The user uses tea."
    assert dependency["status"] == "CURRENT"
    assert premise not in state["messages"][1]["content"]
    assert speaker_source not in state["messages"][1]["content"]
    proposal = {
        "operations": [
            {
                "op": "REVISE",
                "certainty": "explicit",
                "content": "She uses coffee, now dark.",
                "target_ref": "r0",
                "about_ref": speaker,
                "source_refs": ["s1"],
                "dependencies": ["d0"],
            }
        ]
    }
    validate(proposal, state["schema"])
    validate({"operations": [{**proposal["operations"][0], "dependencies": []}]}, state["schema"])
    with pytest.raises(ValidationError):
        validate(
            {"operations": [{**proposal["operations"][0], "source_refs": []}]}, state["schema"]
        )
    resolved = resolve_handles(proposal, state["handles"])["operations"][0]
    assert resolved["about_ref"] == f"speaker:{speaker_source}"
    assert resolved["source_refs"] == [speaker_source]
    assert resolved["dependencies"] == [premise]
    with pytest.raises(ValidationError):
        validate(
            {"operations": [{**proposal["operations"][0], "target_ref": "d0"}]}, state["schema"]
        )


def test_ordinary_omitted_old_record_does_not_leave_visible_handles() -> None:
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda t: [[1.0] for _ in t], embedding_dimension=1
    )
    old_source = memory.publish(
        Observation("old", "Old source body.", "user", "test", actor_ref="current_user")
    )
    incoming = memory.publish(
        Observation("new", "New source body.", "user", "test", actor_ref="current_user")
    )
    target = memory.save(
        op="CREATE",
        content="Old interpretation.",
        about_ref="current_user",
        source_refs=[old_source],
        certainty="explicit",
    )["record"]["ref"]
    memory.suggest_existing_records = (  # type: ignore[method-assign]
        lambda *args, **kwargs: [memory.read(target, include_sources=False)]
    )
    memory.seen.clear()
    memory.visible_source_ranges.clear()
    state = prepare_ingestion(
        memory,
        [{"source_ref": incoming, "content": "New source body."}],
        prompt="Maintain",
        max_operations=2,
        context_bytes=250,
        emit=lambda event: None,
    )
    payload = json.loads(state["messages"][1]["content"])
    assert payload["related_records"] == []
    assert payload["related_original_sources"]["materials"] == []
    assert target not in memory.seen and old_source not in memory.seen
    assert old_source not in memory.visible_source_ranges
    assert set(state["handles"]) == {"u0", "unknown", "s0"}


def test_historical_event_survives_transition_to_answer_task() -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        profile="ordinary",
    )
    memory.start_task("history", "")
    source = memory.publish(
        Observation(
            "past", "I made a short film last year.", "user", "test", actor_ref="current_user"
        )
    )
    memory.save(op="RETAIN_SOURCE", source_ref=source)

    class Host:
        def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            handle = json.loads(messages[1]["content"])["observations"][0]["source_ref"]
            proposal = {
                "operations": [
                    {
                        "op": "CREATE",
                        "certainty": "explicit",
                        "about_ref": "u0",
                        "source_refs": [handle],
                        "content": "The user made a short film last year.",
                    }
                ]
            }
            schema = kwargs["response_format"]["json_schema"]["schema"]
            validate(proposal, schema)
            invalid = copy.deepcopy(proposal)
            invalid["operations"][0]["persistence"] = "task"
            with pytest.raises(ValidationError):
                validate(invalid, schema)
            return {
                "choices": [{"message": {"content": json.dumps(proposal)}, "finish_reason": "stop"}]
            }

    result = ingestion.ingest_chunk(
        memory,
        [{"source_ref": source, "content": "I made a short film last year."}],
        host=Host(),
        prompt="Maintain history.",
        max_operations=2,
        context_bytes=4000,
        emit=lambda event: None,
    )
    assert result["status"] == "complete"
    memory.start_task("answer", "What did I make?")
    assert len(memory.workspace.cards) == 1
    card = next(iter(memory.workspace.cards.values()))
    assert card.text == "The user made a short film last year."
    assert card.source_refs == [source]


def test_ordinary_ingestion_patch_preserves_full_record_and_rejects_unseen_old() -> None:
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, profile="ordinary",
    )
    memory.start_task("history", "")
    old_source = memory.publish(Observation(
        "old", "Requirements A, B and C.", "user", "test", actor_ref="current_user",
    ))
    old_ref = memory.save(
        op="CREATE", content="Requirements: A; B; C.", about_ref="current_user",
        source_refs=[old_source], certainty="explicit",
    )["record"]["ref"]
    memory.suggest_existing_records = (  # type: ignore[method-assign]
        lambda *args, **kwargs: [memory.read(old_ref, include_sources=False)]
    )
    incoming = memory.publish(Observation(
        "update", "Change B to B2.", "user", "test", actor_ref="current_user",
    ))

    class Host:
        old = "B"
        new = "B2"

        def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            payload = json.loads(messages[1]["content"])
            record = payload["related_records"][0]
            proposal = {"operations": [{
                "op": "REVISE", "target_ref": record["ref"], "about_ref": "u0",
                "source_refs": [*record["source_refs"],
                                payload["observations"][0]["source_ref"]],
                "dependencies": [], "certainty": "explicit",
                "content_patch": [{"old": self.old, "new": self.new}],
            }]}
            validate(proposal, kwargs["response_format"]["json_schema"]["schema"])
            return {"choices": [{"message": {"content": json.dumps(proposal)},
                                 "finish_reason": "stop"}]}

    host = Host()
    result = ingestion.ingest_chunk(
        memory, [{"source_ref": incoming, "content": "Change B to B2."}],
        host=host, prompt="Maintain", max_operations=2, context_bytes=12000,
        emit=lambda event: None,
    )
    assert result["status"] == "complete"
    current = next(iter(memory.workspace.cards.values()))
    assert current.text == "Requirements: A; B2; C."
    assert current.source_refs == [old_source, incoming]
    current_ref = memory._ref(current)
    memory.suggest_existing_records = (  # type: ignore[method-assign]
        lambda *args, **kwargs: [memory.read(current_ref, include_sources=False, length=4)]
    )
    later = memory.publish(Observation(
        "later", "Change B2 to B3.", "user", "test", actor_ref="current_user",
    ))
    host.old, host.new = "B2", "B3"
    with pytest.raises(ValueError, match="CONTENT_PATCH_OLD_NOT_DELIVERED"):
        ingestion.ingest_chunk(
            memory, [{"source_ref": later, "content": "Change B2 to B3."}],
            host=host, prompt="Maintain", max_operations=2, context_bytes=12000,
            emit=lambda event: None,
        )
    assert memory._ref(next(iter(memory.workspace.cards.values()))) == current_ref
