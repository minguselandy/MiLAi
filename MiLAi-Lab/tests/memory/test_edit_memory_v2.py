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

from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
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
        view, _ = packet(service, method, "received", "Received.", [], allow_create)
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
