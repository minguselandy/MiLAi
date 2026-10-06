"""Opt-in writer protocol against real SQLite. Synthetic local engineering only."""

from __future__ import annotations

import copy
import json
import socket
from contextlib import contextmanager
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.edit_units import clause_proposal
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_memory import EditMemory


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("NO_HTTP_ENGINEERING")

    monkeypatch.setattr(socket.socket, "connect", denied)


@contextmanager
def opened(path, arm="M", profile="I2", owner="alice"):
    with SqliteStore.from_conn_string(str(path / "v2.sqlite")) as store:
        service = MemoryService(
            store,
            ("v2", owner),
            owner,
            path / "lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
        )
        yield service, EditMemory(service, arm, interface_version=profile)


def packet(service, method, key, text, rows=None, allow_create=True):
    ref = service.capture_user("s", key, text)["source_ref"]
    service.bind_source_boundary("s", key, [ref])
    delivery = method.prepare([ref], text, selected_records=rows)
    return method.writer_view(delivery, request_id=key, allow_create=allow_create), delivery


def formation(method, view, op="save"):
    proposal = {
        "action": "create",
        "units": [
            {"text": "Reminders are quiet.", "evidence": ["e1"]},
            {
                "text": "Only during the exhibition.",
                "role": "condition" if method.conditioned else "content",
                "evidence": ["e1"],
            },
        ],
    }
    if method.conditioned:
        proposal["relations"] = [
            {"source": 1, "target": 0, "relation_type": "modifies", "evidence": ["e1"]}
        ]
    return method.apply("s", op, method.decode_proposal(proposal, view["mapping"]))


NEXT_FEATURES = EditFeatures(True, True, True, True, True)


def test_default_envelope_retains_exact_legacy_structure_and_per_proposal_rejection(tmp_path):
    with opened(tmp_path) as (service, method):
        view, _ = packet(service, method, "legacy-envelope", "A synthetic source.", [])
        for malformed in (
            {},
            {"other": []},
            {"proposals": None},
            {"proposals": "not a list"},
            {"proposals": {}},
            {"proposals": [], "unexpected": True},
            [],
        ):
            with pytest.raises(ValueError, match="Writer did not return a proposals list"):
                method.envelope_proposals(malformed, view["mapping"])
        assert method.envelope_proposals({"proposals": []}, view["mapping"]) == []
        mixed = {"proposals": [{"action": "no_change"}, {"action": "invalid"}]}
        proposals = method.envelope_proposals(mixed, view["mapping"])
        assert proposals == mixed["proposals"]
        assert method.decode_proposal(proposals[0], view["mapping"]) == {"action": "no_change"}
        with pytest.raises(FunctionalRejection, match="PROPOSAL_INVALID"):
            method.decode_proposal(proposals[1], view["mapping"])


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_next_contract_legacy_without_any_support_is_read_only_schema(tmp_path, arm):
    with opened(tmp_path, arm) as (service, _):
        method = EditMemory(service, arm, interface_version="I2", features=NEXT_FEATURES)
        preview = method.preview_writer_request(
            {
                "sources": [],
                "records": [
                    {
                        "record_id": "opaque-old-record",
                        "revision": 1,
                        "content": "Old legacy text.",
                        "edit_state": None,
                    }
                ],
            }
        )
        Draft202012Validator.check_schema(preview["schema"])
        variants = preview["schema"]["properties"]["records"]["properties"]["r1"]["oneOf"]
        assert [variant["properties"]["action"]["const"] for variant in variants] == ["no_change"]
        assert preview["schema"]["properties"]["creates"]["maxItems"] == 0


def test_next_contract_exception_cancel_never_restores_a_lost_general_rule(tmp_path):
    with opened(tmp_path) as (service, _):
        method = EditMemory(service, "M", interface_version="I2", features=NEXT_FEATURES)
        saved, _ = next_save(service, method)
        view, _ = next_request(
            service, method, "add", "User reports a room exception.", [service.read(saved["id"])]
        )
        add = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    "operation": "add_exception",
                    "target_unit": "u1",
                    "text": "User reports silence.",
                    "condition": "In the side room.",
                    "evidence": ["e1"],
                    "assertion": {"source": "e1", "kind": "reported"},
                }
            ],
        }
        assert method.apply("s", "add", method.decode_proposal(add, view["mapping"]))["ok"]
        view, _ = next_request(
            service,
            method,
            "drop",
            "User retracts the general report.",
            [service.read(saved["id"])],
        )
        drop = {
            "action": "edit",
            "target": "r1",
            "edits": [{"operation": "retract", "target_unit": "u1", "evidence": ["e1"]}],
        }
        assert method.apply("s", "drop", method.decode_proposal(drop, view["mapping"]))["ok"]
        view, _ = next_request(
            service,
            method,
            "cancel",
            "User cancels the local exception.",
            [service.read(saved["id"])],
        )
        assert view["packet"]["records"][0]["clauses"][0]["local_exception"]
        remove = {
            "action": "edit",
            "target": "r1",
            "edits": [{"operation": "remove_exception", "target_unit": "u1", "evidence": ["e1"]}],
        }
        assert method.apply("s", "cancel", method.decode_proposal(remove, view["mapping"]))["ok"]
        assert service.read(saved["id"], 4)["value"]["edit_state"]["units"] == []
        assert (
            service.read(saved["id"], 1)["value"]["edit_state"]["units"][0]["text"]
            == "User reports quiet reminders."
        )


def next_unit(text, evidence="e1", role="content", kind="reported"):
    return {
        "text": text,
        "role": role,
        "evidence": [evidence],
        "assertion": {"source": evidence, "kind": kind},
    }


def next_request(service, method, key, text, rows=None, role="user", allow_create=True):
    capture = service.capture_user if role == "user" else service.capture_assistant
    ref = capture("s", key, text, occurred_at="2025-03-04T10:00:00Z")["source_ref"]
    service.bind_source_boundary("s", key, [ref])
    delivery = method.prepare([ref], text, selected_records=rows or [])
    preview = method.preview_writer_request(delivery, allow_create=allow_create)
    actual = method.writer_request(delivery, request_id=key, allow_create=allow_create)
    assert preview["mapping"] is None
    assert preview["packet"] == actual["packet"]
    assert preview["schema"] == actual["schema"]
    Draft202012Validator.check_schema(actual["schema"])
    return actual, ref


def next_save(service, method, key="first", conditioned=False):
    view, ref = next_request(
        service, method, key, "User reports quiet reminders during gallery hours."
    )
    units = [next_unit("User reports quiet reminders.")]
    create = {"action": "create", "matter": "User's reminder sound", "units": units}
    if conditioned:
        units.append(next_unit("During gallery hours.", role="condition"))
        create["relations"] = [
            {"source": 1, "target": 0, "relation_type": "modifies", "evidence": ["e1"]}
        ]
    saved = method.apply(
        "s",
        "save-" + key,
        method.decode_envelope(
            {"creates": [clause_proposal(create, conditioned=method.conditioned)], "records": {}},
            view["mapping"],
        )[0],
    )
    assert saved["ok"] and saved["status"] == "committed"
    return saved, ref


def test_next_bound_clauses_share_only_declared_conditions_and_keep_binding_origins(tmp_path):
    with opened(tmp_path, "B2") as (service, _):
        method = EditMemory(service, "B2", interface_version="I2", features=NEXT_FEATURES)
        view, _ = next_request(service, method, "form", "A user reports qualified reminder rules.")

        def condition(text):
            body = next_unit(text)
            body.pop("role")
            return {**body, "binding": {"evidence": ["e1"]}}

        create = {
            "action": "create",
            "matter": "Reminder tones",
            "clauses": [
                {
                    **condition("Use a soft tone."),
                    "conditions": [condition("On weekdays."), condition("Before 18:00.")],
                },
                {
                    **condition("Use a bright tone."),
                    "conditions": [
                        condition("On Tuesday."),
                        {"reuse": 0, "binding": {"evidence": ["e1"]}},
                        {"reuse": 1, "binding": {"evidence": ["e1"]}},
                    ],
                    "overrides": [{"target": 0, "evidence": ["e1"]}],
                },
            ],
        }
        for clause in create["clauses"]:
            clause.pop("binding")
        saved = method.apply("s", "form", method.decode_proposal(create, view["mapping"]))
        assert saved["ok"]
        old = copy.deepcopy(service.read(saved["id"])["value"]["edit_state"])
        assert len(old["units"]) == 5 and len(old["relations"]) == 6
        view, _ = next_request(
            service, method, "change", "The general tone is now clear.", [service.read(saved["id"])]
        )
        public = view["packet"]["records"][0]
        assert "units" not in public and "relations" not in public
        clauses = public["clauses"]
        assert clauses[0]["conditions"][0]["id"] == "u2"
        assert (
            clauses[0]["conditions"][0]["support"]
            != clauses[0]["conditions"][0]["binding"]["support"]
        )
        assert clauses[1]["conditions"][1]["reuse"] == "u2"
        assert clauses[1]["overrides"][0]["target"] == "u1"
        assert json.dumps(public).count('"text": "On weekdays."') == 1

        def retained(item):
            return {
                "text": item["text"],
                "evidence": [],
                "keep_support": item["support"],
                "assertion": {"keep": item["support"][0]},
            }

        rewrite = {
            "action": "rewrite",
            "target": "r1",
            "clauses": [
                {
                    **retained(clauses[0]),
                    "conditions": [
                        {
                            **retained(c),
                            "binding": {"evidence": [], "keep_support": c["binding"]["support"]},
                        }
                        for c in clauses[0]["conditions"]
                    ],
                },
                {
                    **retained(clauses[1]),
                    "conditions": [
                        {
                            **retained(clauses[1]["conditions"][0]),
                            "binding": {
                                "evidence": [],
                                "keep_support": clauses[1]["conditions"][0]["binding"]["support"],
                            },
                        },
                        *[
                            {
                                "reuse": index,
                                "binding": {
                                    "evidence": [],
                                    "keep_support": c["binding"]["support"],
                                },
                            }
                            for index, c in enumerate(clauses[1]["conditions"][1:])
                        ],
                    ],
                    "overrides": [
                        {
                            "target": 0,
                            "evidence": [],
                            "keep_support": clauses[1]["overrides"][0]["support"],
                        }
                    ],
                },
            ],
        }
        rewrite["clauses"][0].update(
            text="Use a clear tone.",
            evidence=["e1"],
            assertion={"source": "e1", "kind": "reported"},
        )
        missing_origin = copy.deepcopy(rewrite)
        missing_origin["clauses"][0].pop("keep_support")
        with pytest.raises(FunctionalRejection, match="RELATION_SUPPORT_BINDING_INVALID"):
            method.decode_proposal(missing_origin, view["mapping"])
        missing_binding = copy.deepcopy(rewrite)
        missing_binding["clauses"][0]["conditions"][0]["binding"].pop("keep_support")
        with pytest.raises(FunctionalRejection, match="EVIDENCE_REQUIRED"):
            method.decode_proposal(missing_binding, view["mapping"])
        decoded = method.decode_proposal(rewrite, view["mapping"])
        revised = method.apply("s", "rewrite", decoded)
        assert revised["id"] == saved["id"] and revised["revision"] == 2
        assert service.read(saved["id"], 1)["value"]["edit_state"] == old
        assert method.apply("s", "rewrite", decoded)["replayed"]
        legacy = EditMemory(service, "B2", interface_version="I2")
        legacy_view, _ = packet(service, legacy, "legacy-orphan", "An older rule was recorded.", [])
        orphan = legacy.apply(
            "s",
            "orphan",
            legacy.decode_proposal(
                {
                    "action": "create",
                    "units": [
                        {"text": "An older general rule.", "evidence": ["e1"]},
                        {
                            "text": "An unconnected qualification.",
                            "role": "condition",
                            "evidence": ["e1"],
                        },
                    ],
                },
                legacy_view["mapping"],
            ),
        )
        view, _ = next_request(
            service,
            method,
            "retain-orphan",
            "The older general rule is now revised.",
            [service.read(orphan["id"])],
            allow_create=False,
        )
        public = view["packet"]["records"][0]
        assert public["clauses"][0]["conditions"] == []
        assert public["unresolved_conditions"][0]["id"] == "u2"
        retained_orphan = {
            "action": "rewrite",
            "target": "r1",
            "clauses": [
                {**retained(public["clauses"][0]), "conditions": []},
            ],
            "unresolved_conditions": [retained(public["unresolved_conditions"][0])],
        }
        retained_orphan["clauses"][0].update(
            text="A revised general rule.",
            evidence=["e1"],
            assertion={"source": "e1", "kind": "reported"},
        )
        copied = method.apply(
            "s", "retain-orphan", method.decode_proposal(retained_orphan, view["mapping"])
        )
        assert copied["ok"], copied.get("reason", copied.get("status"))
        assert service.read(orphan["id"])["value"]["edit_state"]["relations"] == []


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_next_contract_matter_assertion_whole_or_local_and_historical_metadata(tmp_path, arm):
    with opened(tmp_path, arm) as (service, _):
        method = EditMemory(service, arm, interface_version="I2", features=NEXT_FEATURES)
        first, ref = next_save(service, method, conditioned=method.conditioned)
        before = copy.deepcopy(service.read(first["id"])["value"])
        view, _ = next_request(
            service,
            method,
            "later",
            "Assistant infers reminders use a soft tone.",
            [service.read(first["id"])],
            role="assistant",
            allow_create=False,
        )
        historical = [s for s in view["packet"]["source_table"] if not s["body_delivered"]]
        assert historical[0]["role"] == "user"
        assert historical[0]["occurred_at"] == "2025-03-04T10:00:00Z"
        assert "not_redelivered" not in json.dumps(view["packet"])
        assert view["packet"]["records"][0]["matter"] == "User's reminder sound"
        changed = next_unit("Assistant infers reminders use a soft tone.", kind="inferred")
        if arm in {"B0", "B2"}:
            # Deliberately generate ONLY one target unit. No omitted old condition
            # is programmatically filled back into a whole-record rewrite.
            public = {"action": "rewrite", "units": [changed]}
        else:
            changed.pop("role")
            public = {
                "action": "edit",
                "edits": [
                    {
                        **changed,
                        "operation": "change_value" if arm == "M" else "replace",
                        "target_unit": "u1",
                    }
                ],
            }
        decoded = method.decode_envelope(
            {
                "creates": [],
                "records": {"r1": clause_proposal(public, conditioned=method.conditioned)},
            },
            view["mapping"],
        )[0]
        updated = method.apply("s", "update", decoded)
        assert updated["id"] == first["id"] and updated["revision"] == 2
        current = service.read(first["id"])["value"]
        assert (
            current["edit_state"]["matter_description"]
            == before["edit_state"]["matter_description"]
        )
        assert current["edit_state"]["units"][0]["assertion"]["role"] == "assistant"
        assert "speaker=assistant" in current["content"] and "inferred" in current["content"]
        assert service.source(ref)["occurred_at"] == "2025-03-04T10:00:00Z"
        assert service.read(first["id"], 1)["value"] == before
        if arm in {"B1", "M"}:
            assert (
                current["edit_state"]["units"][0]["unit_id"]
                == before["edit_state"]["units"][0]["unit_id"]
            )
        if arm == "M":
            assert current["edit_state"]["units"][1] == before["edit_state"]["units"][1]
        assert method.apply("s", "update", decoded)["replayed"]


def test_next_contract_actual_enums_no_unavailable_branches_and_legacy_envelope(tmp_path):
    with opened(tmp_path) as (service, legacy):
        method = EditMemory(service, "M", interface_version="I2", features=NEXT_FEATURES)
        view, _ = next_request(service, method, "empty", "A source happened.")
        schema_text = json.dumps(view["schema"])
        assert '"edit"' not in schema_text and '"no_change"' not in schema_text
        assert '"not"' not in schema_text
        assert view["schema"]["properties"]["records"]["properties"] == {}
        with pytest.raises(FunctionalRejection, match="ENVELOPE_INVALID"):
            method.envelope_proposals(
                {"creates": [], "records": {"r1": {"action": "no_change"}}}, view["mapping"]
            )
        with pytest.raises(FunctionalRejection, match="PROPOSAL_INVALID"):
            method.decode_proposal(
                clause_proposal(
                    {
                        "action": "create",
                        "matter": "Undelivered",
                        "units": [next_unit("Invented", "e99")],
                    },
                    conditioned=method.conditioned,
                ),
                view["mapping"],
            )
        no_sources = method.preview_writer_request({"sources": [], "records": []})
        assert no_sources["schema"]["properties"]["creates"]["maxItems"] == 0
        assert method.envelope_proposals({"creates": [], "records": {}}, view["mapping"]) == []
        old, _ = packet(service, legacy, "legacy", "A legacy source.", [])
        mixed = {"proposals": [{"action": "no_change"}, {"action": "illegal"}]}
        assert legacy.envelope_proposals(mixed, old["mapping"]) == mixed["proposals"]


def test_next_contract_m_exception_dependency_shared_condition_and_remove(tmp_path):
    with opened(tmp_path) as (service, _):
        method = EditMemory(service, "M", interface_version="I2", features=NEXT_FEATURES)
        saved, _ = next_save(service, method, conditioned=True)
        baseline = copy.deepcopy(service.read(saved["id"])["value"]["edit_state"])
        view, _ = next_request(
            service,
            method,
            "exception",
            "User changes hours and needs silence in the north room.",
            [service.read(saved["id"])],
        )
        edit = {
            "action": "edit",
            "edits": [
                {
                    **next_unit("During afternoon gallery hours.", role="condition"),
                    "operation": "change_condition",
                    "target_unit": "u2",
                },
                {
                    **next_unit("User reports silent reminders."),
                    "operation": "add_exception",
                    "target_unit": "u1",
                    "condition": "In the north room.",
                    "shared_conditions": ["u2"],
                },
            ],
        }
        # role is fixed by the actual selected existing unit in local operations.
        edit["edits"][0].pop("role")
        edit["edits"][1].pop("role")
        decoded = method.decode_envelope({"creates": [], "records": {"r1": edit}}, view["mapping"])[
            0
        ]
        revised = method.apply("s", "scope", decoded)
        state = copy.deepcopy(service.read(saved["id"])["value"]["edit_state"])
        assert revised["revision"] == 2 and state["units"][0] == baseline["units"][0]
        assert state["units"][1]["unit_id"] == baseline["units"][1]["unit_id"]
        assert len(state["units"]) == 4 and len(state["relations"]) == 4
        view, _ = next_request(
            service,
            method,
            "cancel",
            "User cancels the north-room exception.",
            [service.read(saved["id"])],
        )
        remove = {
            "action": "edit",
            "edits": [{"operation": "remove_exception", "target_unit": "u3", "evidence": ["e1"]}],
        }
        decoded = method.decode_envelope(
            {"creates": [], "records": {"r1": remove}}, view["mapping"]
        )[0]
        assert len(decoded["edits"]) == len(decoded["_edit_metadata"]["unit_assertions"]) == 2
        receipt = method.apply("s", "remove", decoded)
        now = service.read(saved["id"])["value"]["edit_state"]
        assert receipt["revision"] == 3 and now["units"] == state["units"][:2]
        assert now["relations"] == state["relations"][:1]
        assert service.read(saved["id"], 2)["value"]["edit_state"] == state
        # The old read revision cannot commit a second change after cancellation.
        stale = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    **next_unit("Changed stale value."),
                    "operation": "change_value",
                    "target_unit": "u1",
                }
            ],
        }
        stale["edits"][0].pop("role")
        rejected = method.apply("s", "stale", method.decode_proposal(stale, view["mapping"]))
        assert not rejected["ok"] and service.read(saved["id"])["value"]["revision"] == 3


def test_next_contract_b1_same_text_inserts_bind_assertion_at_allocation(tmp_path):
    with opened(tmp_path, "B1") as (service, _):
        method = EditMemory(service, "B1", interface_version="I2", features=NEXT_FEATURES)
        saved, _ = next_save(service, method)
        view, _ = next_request(
            service, method, "insert", "User reports a supplement.", [service.read(saved["id"])]
        )
        supplemental = service.capture_assistant(
            "s", "assistant", "Assistant infers a supplement."
        )["source_ref"]
        service.bind_source_boundary(
            "s", "both", [view["mapping"]["evidence"]["e1"]["source_ref"], supplemental]
        )
        delivery = method.prepare(
            [view["mapping"]["evidence"]["e1"]["source_ref"], supplemental],
            "",
            selected_records=[service.read(saved["id"])],
        )
        view = method.writer_request(delivery, request_id="both")
        edits = [
            {
                **next_unit("Same words.", "e1", kind="reported"),
                "operation": "insert",
                "target_unit": "u1",
            },
            {
                **next_unit("Same words.", "e2", kind="inferred"),
                "operation": "insert",
                "target_unit": "u1",
            },
        ]
        for edit in edits:
            edit.pop("role")
        decoded = method.decode_envelope(
            {"creates": [], "records": {"r1": {"action": "edit", "edits": edits}}}, view["mapping"]
        )[0]
        assert method.apply("s", "inserts", decoded)["ok"]
        inserted = service.read(saved["id"])["value"]["edit_state"]["units"][1:]
        assert [u["assertion"]["role"] for u in inserted] == ["assistant", "user"]
        assert [u["assertion"]["kind"] for u in inserted] == ["inferred", "reported"]


@pytest.mark.parametrize("arm", ["B0", "B2"])
def test_next_contract_rewrite_and_withdraw_are_separate_and_keep_assertion_exact(tmp_path, arm):
    with opened(tmp_path, arm) as (service, _):
        method = EditMemory(service, arm, interface_version="I2", features=NEXT_FEATURES)
        saved, _ = next_save(service, method)
        view, _ = next_request(
            service,
            method,
            "cancel",
            "User withdraws the entire reminder report.",
            [service.read(saved["id"])],
        )
        with pytest.raises(FunctionalRejection, match="PROPOSAL_INVALID"):
            method.decode_proposal(
                {"action": "rewrite", "target": "r1", "clauses": []}, view["mapping"]
            )
        retained = {
            "text": "User reports quiet reminders.",
            "evidence": [],
            "keep_support": ["h1"],
            "assertion": {"keep": "h1"},
        }
        copied = method.decode_proposal(
            clause_proposal(
                {"action": "rewrite", "target": "r1", "units": [retained]},
                conditioned=method.conditioned,
            ),
            view["mapping"],
        )
        assert copied["_edit_metadata"]["unit_assertions"][0]["role"] == "user"
        retained["text"] = "Assistant infers quiet reminders."
        retained["evidence"] = ["e1"]
        with pytest.raises(FunctionalRejection, match="CHANGED_ASSERTION"):
            method.decode_proposal(
                clause_proposal(
                    {"action": "rewrite", "target": "r1", "units": [retained]},
                    conditioned=method.conditioned,
                ),
                view["mapping"],
            )
        withdrawal = method.decode_proposal(
            {"action": "retract_record", "target": "r1", "evidence": ["e1"]}, view["mapping"]
        )
        receipt = method.apply("s", "withdraw", withdrawal)
        assert receipt["ok"] and receipt["id"] == saved["id"]
        assert service.read(saved["id"], 1)["value"]["edit_state"]["units"]
        assert service.read(saved["id"], 2)["value"]["edit_state"]["units"] == []


def test_next_contract_occurrence_time_restart_immutable_and_unknown(tmp_path):
    with opened(tmp_path) as (service, _):
        ref = service.capture_user(
            "s", "known", "Actual text.", occurred_at="2025-01-02T00:00:00Z"
        )["source_ref"]
        unknown = service.capture_assistant("s", "unknown", "An actual assistant assertion.")[
            "source_ref"
        ]
    with opened(tmp_path) as (service, _):
        assert service.source(ref)["occurred_at"] == "2025-01-02T00:00:00Z"
        assert "occurred_at" not in service.source(unknown)
        assert service.capture_user("s", "known", "Actual text.")["source_ref"] == ref
        with pytest.raises(ValueError, match="OCCURRENCE_TIME_CHANGED"):
            service.capture_user("s", "known", "Actual text.", occurred_at="2025-01-03T00:00:00Z")


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
@pytest.mark.parametrize("profile", ["I1", "I2"])
def test_arm_schema_mapping_restart_same_id_actual_revision(tmp_path, arm, profile):
    with opened(tmp_path, arm, profile) as (service, method):
        first, _ = packet(service, method, "u1", "Quiet reminders during the exhibition.", [])
        saved = formation(method, first)
        old = copy.deepcopy(service.read(saved["id"])["value"])
        view, _ = packet(
            service,
            method,
            "u2",
            "Reminders now use a soft tone.",
            [service.read(saved["id"])],
            False,
        )
        encoded = json.dumps(view["packet"])
        assert saved["id"] not in encoded
        assert old["edit_state"]["units"][0]["unit_id"] not in encoded
        assert "base_revision" not in encoded
        if arm in {"B0", "B2"}:
            public: dict[str, Any] = {
                "action": "rewrite",
                "target": "r1",
                "units": [
                    {
                        "text": "Reminders use a soft tone.",
                        "evidence": ["e1"],
                        "keep_support": ["h1"],
                    },
                    {
                        "text": "Only during the exhibition.",
                        "role": "condition" if method.conditioned else "content",
                        "evidence": [],
                        "keep_support": ["h2"],
                    },
                ],
            }
            if method.conditioned:
                public["relations"] = [
                    {
                        "source": 1,
                        "target": 0,
                        "relation_type": "modifies",
                        "evidence": [],
                        "keep_support": ["h3"],
                    }
                ]
        else:
            public = {
                "action": "edit",
                "target": "r1",
                "edits": [
                    {
                        "operation": "replace",
                        "target_unit": "u1",
                        "text": "Reminders use a soft tone.",
                        "evidence": ["e1"],
                        "keep_support": ["h1"],
                    }
                ],
            }
        decoded = method.decode_proposal(public, view["mapping"])
        assert decoded["base_revision"] == 1
        changed = method.apply("s", "change", decoded)
        assert changed["id"] == saved["id"] and changed["revision"] == 2
        current = service.read(saved["id"])["value"]
        assert len(current["edit_state"]["units"][0]["evidence_refs"]) == 2
        if arm in {"B1", "M"}:
            assert current["edit_state"]["units"][1:] == old["edit_state"]["units"][1:]
            assert current["edit_state"]["relations"] == old["edit_state"]["relations"]
        assert service.read(saved["id"], 1)["value"] == old
        map_id = view["mapping"]["mapping_id"]
    with opened(tmp_path, arm, profile) as (service, method):
        assert method.load_mapping(map_id) == view["mapping"]
        replay = method.apply("s", "change", method.decode_proposal(public, map_id))
        assert replay["replayed"] and service.read(saved["id"])["value"]["revision"] == 2


def test_preview_pure_subsets_and_no_create(tmp_path, monkeypatch):
    with opened(tmp_path) as (service, method):
        first, _ = packet(service, method, "u1", "Quiet reminders.", [])
        saved = formation(method, first)
        ref = service.capture_user("s", "u2", "Unchanged.")["source_ref"]
        delivery = method.prepare([ref], "unused", selected_records=[service.read(saved["id"])])

        def denied(*args, **kwargs):
            raise AssertionError("PREVIEW_READ_OR_WRITE")

        with monkeypatch.context() as local:
            local.setattr(service.store, "get", denied)
            local.setattr(service.store, "put", denied)
            local.setattr(service, "search", denied)
            preview = method.preview_writer_view(delivery, allow_create=False)
        actual = method.writer_view(delivery, allow_create=False)
        assert actual["packet"] == preview["packet"]
        assert "mapping" not in preview
        with pytest.raises(FunctionalRejection, match="PUBLIC_PROPOSAL_INVALID"):
            method.decode_proposal(
                {"action": "create", "units": [{"text": "New", "evidence": ["e1"]}]},
                actual["mapping"],
            )
        bad = copy.deepcopy(delivery)
        bad["sources"][0]["body_delivered"] = False
        with pytest.raises(FunctionalRejection, match="ACTUAL_DELIVERY"):
            method.writer_view(bad)
        bad = copy.deepcopy(delivery)
        bad["records"][0]["edit_state"]["units"].pop()
        with pytest.raises(FunctionalRejection, match="COMPLETE_ACTUAL_RECORD"):
            method.writer_view(bad)


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
def test_illegal_arm_ops_and_persistent_identifiers_not_in_schema(tmp_path, arm):
    with opened(tmp_path, arm) as (_, method):
        schema = method.envelope_schema()
        Draft202012Validator.check_schema(schema)
        serialized = json.dumps(schema)
        assert "base_revision" not in serialized and "record_id" not in serialized
        assert "target_record" not in serialized
        if arm in {"B0", "B2"}:
            illegal = {"action": "edit", "target": "r1", "edits": []}
        else:
            illegal = {"action": "rewrite", "target": "r1", "units": []}
        assert list(Draft202012Validator(schema).iter_errors({"proposals": [illegal]}))


def test_old_support_cannot_prove_changed_claim_or_new_link_and_override_is_explicit(tmp_path):
    with opened(tmp_path) as (service, method):
        view, _ = packet(service, method, "u1", "Quiet reminders during exhibition.", [])
        saved = formation(method, view)
        view, _ = packet(
            service, method, "u2", "Late shift uses a loud chime.", [service.read(saved["id"])]
        )
        with pytest.raises(FunctionalRejection, match="CHANGED_CLAIM"):
            method.decode_proposal(
                {
                    "action": "edit",
                    "target": "r1",
                    "edits": [
                        {
                            "operation": "replace",
                            "target_unit": "u1",
                            "text": "Opposite.",
                            "evidence": [],
                            "keep_support": ["h1"],
                        }
                    ],
                },
                view["mapping"],
            )
        with pytest.raises(FunctionalRejection, match="SHORT_EVIDENCE"):
            method.decode_proposal(
                {
                    "action": "edit",
                    "target": "r1",
                    "edits": [
                        {
                            "operation": "replace",
                            "target_unit": "u1",
                            "text": "Loud",
                            "evidence": ["e99"],
                        }
                    ],
                },
                view["mapping"],
            )
        public = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    "operation": "override",
                    "target_unit": "u1",
                    "text": "Loud chime.",
                    "condition": "Late shift.",
                    "evidence": ["e1", "e1"],
                }
            ],
        }
        decoded = method.decode_proposal(public, view["mapping"])
        assert len(decoded["edits"][0]["evidence"]) == 1
        updated = method.apply("s", "override", decoded)
        state = service.read(updated["id"])["value"]["edit_state"]
        assert len(state["relations"]) == 3
        assert sum(r["relation_type"] == "modifies" for r in state["relations"]) == 2


def test_whole_withdrawal_requires_new_source_witness(tmp_path):
    with opened(tmp_path, "B0") as (service, method):
        view, _ = packet(service, method, "u1", "Quiet reminders.", [])
        saved = formation(method, view)
        old_ref = view["mapping"]["evidence"]["e1"]["source_ref"]
        repeat = method.writer_view(
            method.prepare([old_ref], "same", selected_records=[service.read(saved["id"])])
        )
        public = {"action": "rewrite", "target": "r1", "units": [], "withdrawal_evidence": ["e1"]}
        with pytest.raises(FunctionalRejection, match="NEW_WITHDRAWAL_WITNESS"):
            method.apply("s", "bad-cancel", method.decode_proposal(public, repeat["mapping"]))
        view, _ = packet(
            service, method, "u2", "Cancel the reminders.", [service.read(saved["id"])]
        )
        result = method.apply("s", "cancel", method.decode_proposal(public, view["mapping"]))
        assert result["ok"] and result["revision"] == 2
        assert service.read(saved["id"])["value"]["retracted"]
        assert service.read(saved["id"], 1)["value"]["edit_state"]["units"]


def test_i1_i2_same_information_timestamp_and_literal_identifiers(tmp_path):
    with opened(tmp_path, "M") as (service, method):
        view, _ = packet(service, method, "u1", "Quiet reminder.", [])
        saved = formation(method, view)
        original = service.read(saved["id"])["value"]
        real_unit = original["edit_state"]["units"][0]["unit_id"]
        view, _ = packet(
            service, method, "u2", "Literal identifier is " + real_unit, [service.read(saved["id"])]
        )
        replaced = method.decode_proposal(
            {
                "action": "edit",
                "target": "r1",
                "edits": [
                    {
                        "operation": "replace",
                        "target_unit": "u1",
                        "text": "Literal " + real_unit,
                        "evidence": ["e1"],
                    }
                ],
            },
            view["mapping"],
        )
        method.apply("s", "literal", replaced)
        ref = service.capture_user("s", "u3", "Read the literal identifier.")["source_ref"]
        delivery = method.prepare([ref], "literal", selected_records=[service.read(saved["id"])])
        delivery["sources"][0]["timestamp"] = "2001-02-03T04:05:06"
        compact = method.preview_writer_view(delivery)["packet"]
        repeated = EditMemory(service, "M", interface_version="I1").preview_writer_view(delivery)[
            "packet"
        ]
        assert compact["source_table"] == repeated["source_table"]
        assert compact["source_table"][0]["timestamp"] == "2001-02-03T04:05:06"
        assert real_unit in repeated["records"][0]["content"]  # Literal claim text is untouched.
        assert compact["records"][0]["units"] == [
            {k: v for k, v in unit.items() if k != "evidence_refs"}
            for unit in repeated["records"][0]["edit_state"]["units"]
        ]
        assert compact["historical_support"] == repeated["historical_support"]
        assert len(json.dumps(compact)) < len(json.dumps(repeated))


def test_exact_mapping_foreign_owner_wrong_record_and_cas(tmp_path):
    with opened(tmp_path) as (service, method):
        view, _ = packet(service, method, "u1", "Quiet reminders.", [])
        one = formation(method, view)
        two = formation(method, view, "save-two")
        view, _ = packet(
            service,
            method,
            "u2",
            "Use soft reminders.",
            [service.read(one["id"]), service.read(two["id"])],
        )
        public = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    "operation": "replace",
                    "target_unit": "u3",
                    "text": "Use soft reminders.",
                    "evidence": ["e1"],
                }
            ],
        }
        with pytest.raises(FunctionalRejection, match="SHORT_UNIT"):
            method.decode_proposal(public, view["mapping"])
        public["edits"][0]["target_unit"] = "u1"
        decoded = method.decode_proposal(public, view["mapping"])
        first = method.apply("s", "change-one", decoded)
        stale = method.apply("s", "change-stale", decoded)
        assert first["revision"] == 2 and stale["reason"] == "revision_conflict"
        altered = copy.deepcopy(view["mapping"])
        altered["records"]["r1"]["revision"] = 2
        with pytest.raises(FunctionalRejection, match="MAPPING_CHANGED"):
            method.decode_proposal(public, altered)
        map_id = view["mapping"]["mapping_id"]
    with opened(tmp_path, owner="bob") as (_, other):
        with pytest.raises(FunctionalRejection, match="MAPPING_UNAVAILABLE"):
            other.decode_proposal(public, map_id)


def test_v1_default_dto_and_prepare_do_not_gain_v2_fields(tmp_path):
    from milai_lab.memory.edit_units import EditProposal

    with opened(tmp_path) as (service, _):
        legacy = EditMemory(service, "M")
        assert legacy.proposal_schema() == EditProposal.model_json_schema()
        assert "keep_support" not in json.dumps(legacy.proposal_schema())
        ref = service.capture_user("s", "u", "Read only.")["source_ref"]
        delivery = legacy.prepare([ref], "Read only", selected_records=[])
        assert delivery["method_version"] == "milai_edit_v1"
        with pytest.raises(FunctionalRejection, match="V2_INTERFACE"):
            legacy.writer_view(delivery)


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
@pytest.mark.parametrize("profile", ["I1", "I2"])
@pytest.mark.parametrize("allow_create", [False, True])
def test_no_maintenance_example_empty_bank_and_guessed_target_remains_rejected(
    tmp_path, arm, profile, allow_create
):
    with opened(tmp_path, arm, profile) as (service, method):
        view, _ = packet(
            service, method, "received", "Thank you. Could you look that up?", [], allow_create
        )
        assert view["packet"]["records"] == [] and view["packet"]["evidence"]
        instructions = method.instructions(allow_create=allow_create)
        example, _ = json.JSONDecoder().raw_decode(instructions.split("empty response: ", 1)[1])
        assert example == {"proposals": []}
        Draft202012Validator(method.envelope_schema(allow_create=allow_create)).validate(example)
        # An empty envelope schedules zero actions and does not form a semantic record.
        before = service.records()
        for proposal in example["proposals"]:
            method.apply("s", "none", method.decode_proposal(proposal, view["mapping"]))
        assert service.records() == before == []
        guessed = {"action": "no_change", "target": "r1"}
        with pytest.raises(FunctionalRejection, match="EDIT_SHORT_REFERENCE_UNAVAILABLE"):
            method.decode_proposal(guessed, view["mapping"])
        assert service.records() == []


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
@pytest.mark.parametrize("profile", ["I1", "I2"])
def test_targeted_no_change_confirms_only_record_in_current_delivery(tmp_path, arm, profile):
    with opened(tmp_path, arm, profile) as (service, method):
        first, _ = packet(service, method, "initial", "Quiet reminders.", [])
        saved = formation(method, first)
        delivered, _ = packet(
            service, method, "read", "Read quiet reminders.", [service.read(saved["id"])]
        )
        confirmation = {"action": "no_change", "target": "r1"}
        decoded = method.decode_proposal(confirmation, delivered["mapping"])
        before = copy.deepcopy(service.read(saved["id"])["value"])
        receipt = method.apply("s", "confirm", decoded)
        assert receipt["status"] == "no_change" and receipt["id"] == saved["id"]
        assert service.read(saved["id"])["value"] == before
        omitted, _ = packet(service, method, "omitted", "Received.", [], False)
        # The bank has a record and a previous packet had r1; neither grants a current alias.
        with pytest.raises(FunctionalRejection, match="EDIT_SHORT_REFERENCE_UNAVAILABLE"):
            method.decode_proposal(confirmation, omitted["mapping"])
        assert service.read(saved["id"])["value"] == before


def example_envelope(instructions, label):
    return json.JSONDecoder().raw_decode(instructions.split(label + " response: ", 1)[1])[0]


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "M"])
@pytest.mark.parametrize("profile", ["I1", "I2"])
def test_balanced_examples_form_correct_and_keep_unrestated_support(tmp_path, arm, profile):
    with opened(tmp_path, arm, profile) as (service, method):
        create_instructions = method.instructions()
        create = example_envelope(create_instructions, "Formation")
        empty = example_envelope(create_instructions, "empty")
        assert create["proposals"] and empty == {"proposals": []}
        Draft202012Validator(method.envelope_schema()).validate(create)
        first, _ = packet(
            service, method, "new", "Reminders are quiet, only during the exhibition.", []
        )
        formed = method.apply(
            "s", "form-example", method.decode_proposal(create["proposals"][0], first["mapping"])
        )
        assert formed["ok"] and formed["revision"] == 1
        before = copy.deepcopy(service.read(formed["id"])["value"])
        # The example's empty envelope schedules no write, including with an existing bank.
        for proposal in empty["proposals"]:
            method.apply("s", "empty-example", method.decode_proposal(proposal, first["mapping"]))
        assert service.read(formed["id"])["value"] == before
        current, _ = packet(
            service,
            method,
            "change",
            "Reminders use a soft tone.",
            [service.read(formed["id"])],
            False,
        )
        instructions = method.instructions(allow_create=False)
        assert "Formation response:" not in instructions
        correction = example_envelope(instructions, "Correction")
        Draft202012Validator(method.envelope_schema(allow_create=False)).validate(correction)
        if arm in {"B0", "B2"}:
            retained = correction["proposals"][0]["units"][1]
            original_unit = before["edit_state"]["units"][1]
            assert retained["text"] == original_unit["text"]
            assert retained["role"] == original_unit["role"] and retained["evidence"] == []
            paraphrase = copy.deepcopy(correction["proposals"][0])
            paraphrase["units"][1]["text"] = "During the exhibition only."
            # Even a synonymous retention is not approved by h metadata alone.
            with pytest.raises(FunctionalRejection, match="CHANGED_CLAIM_REQUIRES_NEW_EVIDENCE"):
                method.decode_proposal(paraphrase, current["mapping"])
        updated = method.apply(
            "s",
            "correction-example",
            method.decode_proposal(correction["proposals"][0], current["mapping"]),
        )
        assert updated["ok"] and updated["id"] == formed["id"] and updated["revision"] == 2
        after = service.read(formed["id"])["value"]["edit_state"]
        assert after["units"][0]["text"] == "Reminders use a soft tone."
        assert after["units"][1]["text"] == before["edit_state"]["units"][1]["text"]
        assert (
            after["units"][1]["evidence_refs"] == before["edit_state"]["units"][1]["evidence_refs"]
        )
        if method.conditioned:
            assert (
                after["relations"][0]["evidence_refs"]
                == before["edit_state"]["relations"][0]["evidence_refs"]
            )
        if arm in {"B1", "M"}:
            assert after["units"][1:] == before["edit_state"]["units"][1:]
            assert after["relations"] == before["edit_state"]["relations"]
        assert service.read(formed["id"], 1)["value"] == before
        omitted, _ = packet(service, method, "no-target", "Reminders use a soft tone.", [], False)
        # Hypothetical r1 in the explanatory example grants no alias to this actual packet.
        with pytest.raises(FunctionalRejection, match="SHORT_REFERENCE_UNAVAILABLE"):
            method.decode_proposal(correction["proposals"][0], omitted["mapping"])


@pytest.mark.parametrize("profile", ["I1", "I2"])
def test_balanced_formation_then_local_exception_and_supported_cancel_keep_general_state(
    tmp_path, profile
):
    with opened(tmp_path, "M", profile) as (service, method):
        view, _ = packet(
            service, method, "initial", "Reminders are quiet, only during the exhibition.", []
        )
        create = example_envelope(method.instructions(), "Formation")["proposals"][0]
        saved = method.apply("s", "formation", method.decode_proposal(create, view["mapping"]))
        assert saved["ok"]
        original = copy.deepcopy(service.read(saved["id"])["value"]["edit_state"])
        view, _ = packet(
            service, method, "scope", "Late shift uses a loud chime.", [service.read(saved["id"])]
        )
        override = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {
                    "operation": "override",
                    "target_unit": "u1",
                    "text": "Reminders use a loud chime.",
                    "condition": "Late shift.",
                    "evidence": ["e1"],
                }
            ],
        }
        scoped = method.apply("s", "scope", method.decode_proposal(override, view["mapping"]))
        assert scoped["ok"] and scoped["revision"] == 2
        state = service.read(saved["id"])["value"]["edit_state"]
        assert state["units"][:2] == original["units"]
        assert state["relations"][0] == original["relations"][0]
        # Retain unrestated conditions for the general arrangement, without copying to a new object.
        assert not any(
            r["source_unit"] == original["units"][1]["unit_id"]
            and r["target_unit"] == state["units"][2]["unit_id"]
            for r in state["relations"]
        )
        view, _ = packet(
            service,
            method,
            "cancel",
            "Cancel the late-shift exception.",
            [service.read(saved["id"])],
        )
        cancellation = {
            "action": "edit",
            "target": "r1",
            "edits": [
                {"operation": "retract", "target_unit": alias, "evidence": ["e1"]}
                for alias in ("u3", "u4")
            ],
        }
        canceled = method.apply(
            "s", "cancel", method.decode_proposal(cancellation, view["mapping"])
        )
        assert canceled["ok"] and canceled["id"] == saved["id"] and canceled["revision"] == 3
        assert service.read(saved["id"])["value"]["edit_state"] == original
        assert service.read(saved["id"], 2)["value"]["edit_state"] == state
