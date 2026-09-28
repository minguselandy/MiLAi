"""Offline contracts for LSA orchestration, independent of optional LangGraph extras.

The Bank and model below are protocol fakes, not substitutes for Store/integration
coverage. Golden digests use controller.py at
9515017a5dfaba6b6e306fa778fd20f4383b6e35.
They cover complete model requests, ordered events, apply arguments and receipts.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from jsonschema import validate

from milai_lab.methods.local_state_attention import controller
from milai_lab.methods.local_state_attention.protocol import (
    ControlResponseError,
    control_prompt,
    control_schema,
    event_view,
    parse_control_response,
    parse_json_response,
    selected_ids,
    selection_schema,
    state_directory,
    state_view,
)


def _digest(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(serialized).hexdigest()


def _receipt(value: Any, *, reason: str = "stop") -> dict[str, Any]:
    return {"choices": [{"finish_reason": reason, "message": {"content": json.dumps(value)}}]}


class _Bank:
    max_states = 4

    def __init__(self, *, empty: bool = False, no_pending: bool = False,
                 cached: bool = False, invalid: bool = False) -> None:
        self.rows = [] if empty else [
            {"id": key, "title": f"matter {key}", "content": f"正文 {key}",
             "needs": [], "evidence_refs": ["e0"], "revision": 1}
            for key in ("s2", "s1")]
        self.new = [] if no_pending else [
            {"id": "e1", "kind": "user", "actor": "alice", "content": "same event text"},
            {"id": "e2", "kind": "user", "actor": "alice", "content": "same event text"}]
        self.sources = [{"id": "e0", "kind": "user", "content": "prior"}, *self.new]
        self.cached = ["s1", "deleted"] if cached else None
        self.invalid = invalid
        self.calls: list[Any] = []

    def pending(self, scope: Any) -> list[dict[str, Any]]:
        self.calls.append(["pending", scope.user_id])
        return deepcopy(self.new)

    def states(self, scope: Any) -> list[dict[str, Any]]:
        self.calls.append(["states", scope.user_id])
        return deepcopy(self.rows)

    def events(self, scope: Any) -> list[dict[str, Any]]:
        self.calls.append(["events", scope.user_id])
        return deepcopy(self.sources)

    def focus(self, scope: Any, query_id: str) -> Any:
        self.calls.append(["focus", scope.user_id, query_id])
        return deepcopy(self.cached)

    def set_focus(self, scope: Any, query_id: str, ids: list[str]) -> None:
        self.calls.append(["set_focus", scope.user_id, query_id, list(ids)])
        self.cached = list(ids)

    def clear_focus(self, scope: Any) -> None:
        self.calls.append(["clear_focus", scope.user_id])
        self.cached = None

    def apply(self, scope: Any, edits: list[dict[str, Any]], events: set[str],
              **kwargs: Any) -> tuple[list[dict[str, Any]], bool]:
        arguments = {k: sorted(v) if isinstance(v, set) else v for k, v in kwargs.items()}
        self.calls.append(["apply", scope.user_id, deepcopy(edits), sorted(events), arguments])
        receipts = []
        for edit in edits:
            if edit.get("id") is None:
                row = {"id": "new1", "title": edit["title"], "content": edit["content"],
                       "needs": [], "evidence_refs": sorted(events), "revision": 1}
                self.rows.append(row)
                receipts.append({"id": "new1", "status": "created", "revision": 1})
            else:
                for row in self.rows:
                    if row["id"] == edit["id"]:
                        row["content"] = edit["content"]
                        row["revision"] += 1
                        receipts.append({"id": row["id"], "status": "updated",
                                         "revision": row["revision"]})
        if self.invalid:
            receipts.append({"status": "skipped_invalid_edit", "id": "missing"})
        else:
            self.new = []
        return receipts, self.invalid


class _Model:
    def __init__(self, name: str, module: Any) -> None:
        self.name, self.module = name, module
        self.requests: list[Any] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        name = kwargs["response_format"]["json_schema"]["name"]
        stage = name.removeprefix("local_state_").removesuffix("_v1")
        self.requests.append({"messages": deepcopy(messages), **deepcopy(kwargs),
                              "role": self.module.REQUEST_ROLE.get(),
                              "stage": self.module.CONTROL_STAGE.get()})
        if self.name.endswith("timeout"):
            raise httpx.ReadTimeout("offline timeout")
        if self.name.endswith("io_error"):
            raise OSError("do not swallow infrastructure failure")
        if self.name.endswith("length"):
            return _receipt({}, reason="length")
        if self.name.endswith("bad_json"):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "{"}}]}
        payload = json.loads(messages[1]["content"])
        if stage == "update_selector":
            return _receipt({"update_ids": ["s1", "s1"] if "bad_update" in self.name else ["s1"]})
        if stage == "read_selector":
            ids = [row["id"] for row in payload["directory"]]
            return _receipt({"read_ids": ["missing"] if "bad_read" in self.name else ids[::-1]})
        edits = ([] if "empty_edit" in self.name else
                 [{"id": "s1", "content": "changed"}] if "revise" in self.name else
                 [{"id": None, "title": "new matter", "content": "new information"}])
        if "bad_shape" in self.name:
            return _receipt({"unexpected": []})
        value = {"edits": edits}
        if stage == "control":
            value["focus"] = ["new:0", "s1", "s1", "missing"]
        return _receipt(value)


SCENARIOS = (
    "all_create", "all_revise", "all_empty", "all_empty_edit", "all_partial",
    "all_cached", "all_close", "all_close_empty", "all_global", "all_granular",
    "all_maintenance", "all_maintenance_global", "all_maintenance_bad_shape",
    "all_maintenance_timeout", "all_length", "all_bad_json", "all_io_error",
    "all_capacity", "all_pending_limit", "lr_create", "lr_revise", "lr_empty",
    "lr_no_pending", "lr_bad_read", "lr_partial", "lru_create", "lru_empty",
    "lru_no_pending", "lru_bad_update", "lru_bad_read", "lru_timeout",
    "lru_capacity", "lru_bad_shape", "lru_global", "lru_granular",
)


def _run(name: str, tmp_path: Path, module: Any = controller) -> dict[str, Any]:
    policy = name.split("_")[0]
    empty = name.endswith("empty") and "close_empty" not in name
    no_pending = any(marker in name for marker in ("no_pending", "cached", "close_empty"))
    bank = _Bank(empty=empty, no_pending=no_pending, cached="cached" in name,
                 invalid="partial" in name)
    model = _Model(name, module)
    events: list[dict[str, Any]] = []
    capacity = tmp_path / "calls.json" if "capacity" in name else None
    instance = module.LocalStateController(
        bank, model, emit=events.append, update_policy=policy,
        representation="global_note" if "global" in name else "local",
        local_granularity="granular" in name, maintenance_only="maintenance" in name,
        capacity_path=capacity, max_calls_per_message=0 if policy == "all" else 1,
        max_pending_batch=1 if "pending_limit" in name else 24)
    scope = SimpleNamespace(user_id="alice")
    try:
        if "close" in name:
            result = instance.close_turn(scope, "e2", "turn:1")
        else:
            result = instance.prepare(scope, "e2", "current query", "turn:1")
        failure = None
    except Exception as exc:
        result = None
        failure = [type(exc).__name__, str(exc)]
    return {"result": result, "error": failure, "requests": model.requests,
            "events": events, "bank_calls": bank.calls, "rows": bank.rows,
            "pending": bank.new,
            "capacity": (json.loads(capacity.read_text())
                         if capacity and capacity.exists() else None),
            "final_role": module.REQUEST_ROLE.get(), "final_stage": module.CONTROL_STAGE.get()}


# Filled from the original implementation, not from the refactored implementation.
GOLDEN: dict[str, str] = {
    "all_create": "8ee0a530409a85794d7675b52f1d9cd0e3f432249b13736da9a28245b86b9bef",
    "all_revise": "de142998de3ea91d7c1f32b0f753ed778801f2feb76427757a059b15649fb763",
    "all_empty": "33c453c862ea22f55e63d2bc51e42813692be4bb52ca3d2599096d23c2b74133",
    "all_empty_edit": "6597035ab3992b3218a57ebe2339f5f18e9c6537c95cdae374b2d2b12228689a",
    "all_partial": "18219335b989c4c11d4362eb613a1c8833f9531e4b673a53e8ec72a829d77969",
    "all_cached": "c0512e9b518bd49092912d9b9e6fc8ada45a43c2244e70bf0cc20e2d0b2d9629",
    "all_close": "9e5e855cb27c0e67309c32547d14bd4ee103302de3776fa86dbba42f0bf29978",
    "all_close_empty": "b858b0062a3c0423d60a504041bce38183b65b470ab9d3e3165d01dad4781e3c",
    "all_global": "e17eb23b33462d198e62c843ad7918f1f2d83b6a56a92be9ffec2901de00b0b3",
    "all_granular": "abe77907a8cf1e030e78f6e21752b688e7c68e03ac92b81e1c3918887ec92f8e",
    "all_maintenance": "9e5e855cb27c0e67309c32547d14bd4ee103302de3776fa86dbba42f0bf29978",
    "all_maintenance_global": "66398e37a9de0bbb29ff53c90e12540b060251a2da29b0334d44de581aafcdf2",
    "all_maintenance_bad_shape": "65629f9e2edeac525f6de908de8e81d65321eea95d1490b2c0de52b5b60412d6",
    "all_maintenance_timeout": "29b995e3576b1b28c35450408d1736193ea58c55aefd07f85d60aec53f029164",
    "all_length": "427750eb63264015e79c60c375b085ba38bd81acd6c6261e2d9e6ae3328da1cf",
    "all_bad_json": "427750eb63264015e79c60c375b085ba38bd81acd6c6261e2d9e6ae3328da1cf",
    "all_io_error": "2b7e7feff19557ac09afa3d5fd9fa65d02425d2692b9e46ed2b9056457b295aa",
    "all_capacity": "920813cbbdca9272fc44de2c5924e2a0335e4e62b2b16cf08f1c4dcfab60ce11",
    "all_pending_limit": "6c080e705351cfc8334b48c73b355f5d13762ffa0bc06351fd4fe15e0754360e",
    "lr_create": "e86c6e9f0ea504f7af5c02e8c40e20085d4285e985d167cb523cc45c6cf4a4ff",
    "lr_revise": "28e1d0660d0b342e7e92d247cd9685bc8ed7f5fc9157eb9a4a906baf9a833162",
    "lr_empty": "c3f54ff45ea4bb7ca002ecf591a8187660f163b34cba3062b5adacc5a51e7208",
    "lr_no_pending": "48123d35d1db545fb7094fef0f8fb4dbc70bd6ee1f4b6d845be1945f58a75106",
    "lr_bad_read": "d3119c2731fa8de12145d841e7906844c1716d0df5903f0ce6dd8ffaeb647e40",
    "lr_partial": "2b78966b4605290328626fb5e4592fadf97291ef5363a755106b2fe594ff21d6",
    "lru_create": "f20ddc84805dd67755d04d614511509259862454faa152d8c4cf7c6569020695",
    "lru_empty": "d9277f0b79aa6139e9c1072ccafb6ae7de5638dc95a41c50e78bbac553a693ff",
    "lru_no_pending": "f2788b8ac65d3e5b31038a734c0db82b1e8348060e0ab75c0a7b2bd0cf6d37be",
    "lru_bad_update": "dd9ea1be4af0edb5b6f6c2ead90af1900d3abb89ea55123173f92c902ae0d0b0",
    "lru_bad_read": "bc468e96fb79147212249c4d49297a22950f4d6c95e8c8413e82742d404900e6",
    "lru_timeout": "93a7cad06ae88c3a7146b7fb9b5cbc3518ed6da5e6ee81957c0c996a463fd953",
    "lru_capacity": "dc8eeb4e0b1b2b266d92b930b92b7d7e50a8c1f921c32d3ed608ba7d4af6d408",
    "lru_bad_shape": "cfbf9f73e3e3821a23cf1d068278e84c5f999c76cfcd67b2e69e3c85363ea78f",
    "lru_global": "3a5fb5b352dca422256f3ceeabd9386b5f450de5369106dcc4106e68704ab98e",
    "lru_granular": "e5aa2e1d155afd2a6b96ff8b7bf519641de8067ad8420913a43bdf48bd4bcd1b"
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_controller_wire_and_effects_unchanged(name: str, tmp_path: Path) -> None:
    assert _digest(_run(name, tmp_path)) == GOLDEN[name]


@pytest.mark.parametrize("field", ["read_ids", "update_ids"])
@pytest.mark.parametrize("ids", [set(), {"z", "a"}])
def test_selector_contract(field: str, ids: set[str]) -> None:
    schema = selection_schema(field, ids)
    assert schema["properties"][field]["maxItems"] == len(ids)
    validate({field: list(ids)}, schema)
    assert selected_ids({field: []}, field, ids) == []
    assert selected_ids({field: list(ids)}, field, ids) == list(ids)
    assert selected_ids({field: ["unknown"]}, field, ids) is None


@pytest.mark.parametrize("value", [None, "s1", [1], [True], [{}], ["s1", "s1"], ["foreign"]])
def test_selection_rejects_instead_of_repairing(value: Any) -> None:
    assert selected_ids({"read_ids": value}, "read_ids", {"s1"}) is None


def test_selection_rejects_extra_fields() -> None:
    assert selected_ids({"read_ids": ["s1"], "answer": "claim"}, "read_ids", {"s1"}) is None


@pytest.mark.parametrize("receipt,error", [
    ({}, "LSA_CONTROL_INVALID_RESPONSE"),
    ({"choices": []}, "LSA_CONTROL_INVALID_RESPONSE"),
    (_receipt({}, reason="length"), "LSA_CONTROL_INCOMPLETE"),
    (_receipt([]), "LSA_CONTROL_INVALID_SHAPE"),
    ({"choices": [{"finish_reason": "stop", "message": {"content": "{"}}]},
     "LSA_CONTROL_INVALID_RESPONSE"),
])
def test_response_errors_preserved(receipt: Any, error: str) -> None:
    with pytest.raises(ControlResponseError, match=error):
        parse_json_response(receipt)


@pytest.mark.parametrize("value", [{}, {"edits": []}, {"edits": [], "focus": [1]},
                                   {"edits": {}, "focus": []},
                                   {"edits": [], "focus": [], "extra": True}])
def test_control_shape_is_not_relaxed(value: Any) -> None:
    with pytest.raises(ControlResponseError, match="LSA_CONTROL_INVALID_SHAPE"):
        parse_control_response(_receipt(value))


def test_projection_keeps_order_roles_and_distinct_event_ids() -> None:
    bank = _Bank()
    assert list(state_view(bank.rows[0])) == [
        "id", "title", "content", "needs", "evidence_refs", "revision"]
    assert [row["id"] for row in state_directory(bank.rows)] == ["s2", "s1"]
    projected = [event_view({**row, "private": "omit"}) for row in bank.new]
    assert [row["id"] for row in projected] == ["e1", "e2"]
    assert all(row["actor"] == "alice" and "private" not in row for row in projected)


def test_public_imports_remain_compatible() -> None:
    assert controller.control_schema is control_schema
    assert controller.ControlResponseError is ControlResponseError
    assert controller.LocalStateController._parse is parse_control_response


@pytest.mark.parametrize("global_note", [False, True])
@pytest.mark.parametrize("ids", [[], ["s2", "s1"]])
def test_control_schema_creation_and_current_targets(global_note: bool, ids: list[str]) -> None:
    schema = control_schema(ids, 4, single_note=global_note)
    edit = ({"id": ids[0], "content": "updated"} if global_note and ids else
            {"id": None, "title": "new matter", "content": "new"})
    validate({"edits": [edit], "focus": []}, schema)


@pytest.mark.parametrize("representation", ["local", "global_note"])
@pytest.mark.parametrize("granular", [False, True])
@pytest.mark.parametrize("candidate_only", [False, True])
def test_maintenance_prompt_never_requests_focus(representation: str, granular: bool,
                                                candidate_only: bool) -> None:
    text = control_prompt(representation, granular, maintenance=True,
                          candidate_only=candidate_only)
    assert "Return JSON with edits only." in text
    assert "Choose focus for the current_task" not in text
    assert "Focus is an array" not in text
