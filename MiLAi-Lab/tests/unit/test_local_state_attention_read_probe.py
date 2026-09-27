"""Zero-model checks for the frozen read-only first-request probe."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("langmem")

from milai_lab.methods.local_state_attention.read_probe import (
    first_action,
    query_top_two,
    render_view,
    replace_view,
    select_focus,
)


def _state(key: str, title: str) -> dict[str, Any]:
    return {"id": key, "title": title, "content": title + " facts", "needs": [],
            "evidence_refs": [], "revision": 1, "archived": False}


def _request() -> dict[str, Any]:
    return {"model": "mock", "messages": [
        {"role": "system", "content": "Action protocol\nBase prompt\n"
         "[Local State working view: old]\nold state"},
        {"role": "user", "content": "original user"},
        {"role": "assistant", "content": '{"calls":[{"name":"get","arguments":{}}]}'},
        {"role": "tool", "content": '{"ok":false,"reserved":true}',
         "tool_call_id": "call-1"},
        {"role": "user", "content": "current user"}],
        "temperature": 0, "max_tokens": 100,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "action", "strict": True,
            "schema": {"type": "object", "properties": {
                "calls": {"type": "array", "items": {"type": "object"}}},
                "required": ["calls"], "additionalProperties": False}}}}


def test_only_first_system_view_changes_and_first_call_is_not_executed() -> None:
    original = _request()
    view = render_view([_state("b", "Second"), _state("a", "First")])
    request = replace_view(original, view)
    assert request["messages"][0]["content"] == "Action protocol\nBase prompt\n" + view
    assert request["messages"][1:] == original["messages"][1:]
    assert {key: value for key, value in request.items() if key != "messages"} == {
        key: value for key, value in original.items() if key != "messages"}
    assert original["messages"][0]["content"].endswith("old state")
    assert view.index('"title": "First"') < view.index('"title": "Second"')
    assert '"id":' not in view and '"revision":' not in view
    receipt = {"choices": [{"finish_reason": "stop", "message": {
        "content": '{"calls":[{"name":"reserve_and_label","arguments":{}}]}'}}]}
    assert first_action(receipt, request)["calls"][0]["name"] == "reserve_and_label"


def test_query_top_two_uses_one_sorted_bank_batch_and_cosine() -> None:
    class FakeEmbedding:
        def embed(self, texts: list[str], model: str) -> list[list[float]]:
            assert model == "bge-m3"
            assert texts == ["query", "First\nFirst facts", "Second\nSecond facts",
                             "Third\nThird facts"]
            return [[1.0, 0.0], [0.8, 0.6], [1.0, 0.0], [-1.0, 0.0]]

    bank = [_state("c", "Third"), _state("a", "First"), _state("b", "Second")]
    chosen = query_top_two(bank, "query", FakeEmbedding(), "bge-m3")  # type: ignore[arg-type]
    assert [row["id"] for row in chosen] == ["b", "a"]


def test_focus_selector_is_read_only_and_accepts_only_actual_ids() -> None:
    class FakeSelector:
        def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
            assert [row["id"] for row in json.loads(messages[1]["content"])["states"]] == [
                "a", "b"]
            assert "edits" not in kwargs["response_format"]["json_schema"]["schema"][
                "properties"]
            assert kwargs["response_format"]["json_schema"]["schema"]["properties"][
                "focus"]["items"]["enum"] == ["a", "b"]
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"focus":["b","a","b"]}'}}]}

    bank = [_state("b", "Second"), _state("a", "First")]
    chosen = select_focus(bank, "query", FakeSelector())  # type: ignore[arg-type]
    assert [row["id"] for row in chosen] == ["a", "b"]


def test_probe_cli_prepare_and_one_job_cannot_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.methods.freshness_projection.identity import LAB

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_local_state_attention_read_probe as entry

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "host": {"base_url": "http://mock/v1/", "model": "mock", "temperature": 0,
                 "max_tokens": 100, "enable_thinking": False},
        "embedding": {"base_url": "http://mock/v1/", "model": "bge-m3"},
        "control": {"max_tokens": 50},
        "capacity": {"enable_thinking": False},
        "budget_path": str(tmp_path / "budget.json")}))
    input_path = tmp_path / "inputs.json"
    original_view = _request()["messages"][0]["content"].split("Base prompt\n", 1)[1]
    input_path.write_text(json.dumps({"kind": "LSA_READ_PROBE_INPUTS", "cases": [{
        "case_id": "case", "query": "current user", "bank": [_state("a", "First")],
        "host_request": _request(), "variants": {
            "receipt": {"diagnostic_only": True, "context_text": '{"ok":false}'},
            "original": {"diagnostic_only": True, "view_text": original_view}}}],
        "jobs": [{"job_id": "all-one", "case_id": "case", "arm": "all"},
                 {"job_id": "diagnostic-one", "case_id": "case", "arm": "diagnostic",
                  "variant": "receipt"},
                 {"job_id": "original-one", "case_id": "case", "arm": "diagnostic",
                  "variant": "original"}]}))
    root = tmp_path / "run"
    args = SimpleNamespace(config=config_path, inputs=input_path, run="mock-run",
                           runtime_root=root, output=root / "prepared.json",
                           prepared=root / "prepared.json", job="all-one", stage="mock")
    entry.prepare(args)
    sent: list[dict[str, Any]] = []

    class FakeCapacity:
        def __init__(self, _config: Any) -> None:
            pass

        def check(self, messages: Any, max_tokens: Any, _tools: Any = None) -> dict[str, Any]:
            assert max_tokens == 100
            assert messages[-1]["content"] == "current user"
            return {"prompt_tokens": 10, "output_reserve_tokens": 100}

    class FakeClient:
        def __init__(self, _config: Any, **kwargs: Any) -> None:
            self.emit = kwargs.get("emit")

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def _post(self, path: str, request: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
            assert path == "chat/completions"
            sent.append(request)
            if self.emit is not None:
                self.emit({"event": "vllm_response", "path": path,
                           "usage": {"total_tokens": 15}, "wall_seconds": 0.1})
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"calls":[{"name":"reserve_and_label","arguments":{}}]}'}}]}

    monkeypatch.setattr(entry, "HostCapacity", FakeCapacity)
    monkeypatch.setattr(entry, "VLLMClient", FakeClient)
    first = entry.run_job(args)
    assert first["business_tools_executed"] == 0
    assert first["selected_state_ids"] == ["a"]
    assert len(sent) == 1
    with pytest.raises(ValueError, match="ALREADY_ATTEMPTED"):
        entry.run_job(args)
    args.job = "diagnostic-one"
    second = entry.run_job(args)
    assert second["diagnostic_only"] is True
    assert second["view"].endswith('{"ok":false}')
    assert len(sent) == 2
    args.job = "original-one"
    third = entry.run_job(args)
    assert third["view"] == original_view
    assert third["host_request"] == _request()
    assert sent[2] == _request()
    assert len(sent) == 3
    manifest = json.loads((root / "run_manifest.json").read_text())
    assert manifest["status"] == "TERMINAL"
    assert manifest["accounting"]["by_role"]["task_host"]["known_tokens"] == 45


@pytest.mark.parametrize("variant", [
    {"diagnostic_only": True, "view_text": 123},
    {"diagnostic_only": True, "view_text": "raw", "context_text": "wrapped"},
    {"diagnostic_only": False, "view_text": "raw"},
])
def test_probe_view_text_is_diagnostic_only_and_exclusive(
    variant: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.methods.freshness_projection.identity import LAB

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_local_state_attention_read_probe as entry

    inputs = {"kind": "LSA_READ_PROBE_INPUTS", "cases": [{
        "case_id": "case", "query": "current user", "bank": [],
        "host_request": _request(), "variants": {"bad": variant}}], "jobs": []}
    with pytest.raises(ValueError, match="LSA_PROBE_VARIANT_INVALID"):
        entry._cases(inputs, {"host": {"model": "mock", "temperature": 0,
                                         "max_tokens": 100},
                              "capacity": {"enable_thinking": False}})
