from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
state = importlib.import_module("v02_e2e_state")
runner = importlib.import_module("run_v02_local_vllm")


def head(payload=None, version=0):
    return {
        "schema_version": "host-cognitive-state-v1",
        "authority": "HOST_WORKING",
        "scope": "TASK",
        "status": "ACTIVE" if version else "ABSENT",
        "state_id": "lineage" if version else None,
        "state_version_id": f"version-{version}" if version else None,
        "version": version,
        "payload": payload or {},
        "warnings": [],
    }


@pytest.fixture
def setup(tmp_path):
    config = {
        "experiment_id": "engineering",
        "state_field": "opaque-container",
        "l1_path": "handoff",
        "l2_path": "details",
        "prefetch_max_bytes": 4096,
    }
    (tmp_path / "handoff").write_bytes("  中文\r\n\t正文\n".encode())
    (tmp_path / "details").write_text("source detail")
    return config, tmp_path


class PublicFixture:
    def __init__(self, before=None, failure=None):
        self.current = before or head()
        self.failure = failure
        self.writes = []

    def __call__(self, tool, args):
        if tool.endswith("get"):
            return copy.deepcopy(self.current)
        self.writes.append(copy.deepcopy(args))
        if self.failure == "reject":
            return {"mcp_error": True, "content": "STALE_WORKING_STATE"}
        self.current = head(copy.deepcopy(args["payload"]), args["expected_version"] + 1)
        receipt = copy.deepcopy(self.current)
        if self.failure in {"advance", "lost_advance"}:
            self.current = head({"other": "new legitimate change"}, self.current["version"] + 1)
        if self.failure in {"lost", "lost_advance"}:
            raise TimeoutError("response lost after commit")
        return receipt


@pytest.mark.parametrize(
    "failure,operation,opportunity",
    [
        (None, "CONFIRMED", True),
        ("advance", "CONFIRMED", False),
        ("lost", "UNKNOWN", False),
        ("lost_advance", "UNKNOWN", False),
        ("reject", "REJECTED", False),
    ],
)
def test_operation_and_current_head_are_independent(setup, failure, operation, opportunity):
    config, workspace = setup
    call = PublicFixture(failure=failure)
    result = state.save_layers(call, workspace, config, {}, "one-operation")
    assert result["operation"]["outcome"] == operation
    assert result["comparison_opportunity"] is opportunity
    assert len(call.writes) == 1
    if failure == "lost":
        assert result["head_observation"]["matches_candidate"] is True
    if failure == "advance":
        assert result["operation"]["version_id"] == "version-1"
        assert result["head_observation"]["value"]["version"] == 2


def test_preserve_old_fields_and_noop_without_another_write(setup):
    config, workspace = setup
    old = {"unrelated": {"text": "  retain\n", "evidence_refs": []}}
    call = PublicFixture(head(copy.deepcopy(old), 1))
    result = state.save_layers(call, workspace, config, {}, "first")
    assert result["operation"]["outcome"] == "CONFIRMED"
    assert result["payload"]["unrelated"] == old["unrelated"]
    again = state.save_layers(call, workspace, config, {}, "unused")
    assert again["selection_reason"] == "NO_CHANGE"
    assert again["operation"]["attempted"] is False and len(call.writes) == 1
    projected = state.assemble_layers(
        call.current, workspace, "B", config, runner.manifest(workspace)
    )
    assert "unrelated" not in projected["payload"]
    assert call.current["payload"]["unrelated"] == old["unrelated"]


@pytest.mark.parametrize(
    "error",
    [
        {"content": "WORKING_STATE_OUTCOME_UNKNOWN: detail mentions OPERATION_CONFLICT"},
        {"content": [{"type": "text", "text": 'Network error; request had "STALE_WORKING_STATE"'}]},
        {"code": "WORKING_STATE_OUTCOME_UNKNOWN", "detail": "EVIDENCE_REFERENCE_INVALID"},
        {"content": "Network error", "payload": {"note": "HOST_WORKING_STATE_SCOPE_DENIED"}},
        {"content": "NOT_STALE_WORKING_STATE"},
        {"content": [{"type": "text", "text": "OPERATION_CONFLICT"},
                     {"type": "text", "text": "WORKING_STATE_OUTCOME_UNKNOWN"}]},
        {"content": "Error executing tool another_tool: STALE_WORKING_STATE: rejected"},
    ],
)
def test_error_mentions_do_not_prove_noncommit_even_when_head_matches(setup, error):
    config, workspace = setup
    fixture = PublicFixture()

    def call(tool, args):
        value = fixture(tool, args)
        if tool.endswith("update"):
            return {"mcp_error": True, **error}
        return value

    result = state.save_layers(call, workspace, config, {}, "uncertain-operation")
    assert result["operation"]["outcome"] == "UNKNOWN"
    assert result["head_observation"]["matches_candidate"] is True
    assert result["comparison_opportunity"] is False
    assert len(fixture.writes) == 1


@pytest.mark.parametrize(
    "receipt",
    [
        {"code": "STALE_WORKING_STATE"},
        {"content": "STALE_WORKING_STATE"},
        {"content": [{"type": "text", "text": "STALE_WORKING_STATE: update rejected"}]},
        {"content": [{"type": "text", "text": (
            "Error executing tool milai_working_state_update: STALE_WORKING_STATE: "
            "Working State update rejected. Reload current State."
        )}]},
    ],
)
def test_explicit_public_rejection_code_remains_rejected(setup, receipt):
    config, workspace = setup
    fixture = PublicFixture(failure="reject")

    def call(tool, args):
        value = fixture(tool, args)
        return {"mcp_error": True, **receipt} if tool.endswith("update") else value

    result = state.save_layers(call, workspace, config, {}, "rejected-operation")
    assert result["operation"]["outcome"] == "REJECTED"
    assert result["operation"]["reason"] == "STALE_WORKING_STATE"
    assert result["head_observation"]["value"]["version"] == 0
    assert len(fixture.writes) == 1


@pytest.mark.parametrize(
    "content",
    [
        {"last": None, "空 键 ": [False, 0, "", {" nested ": " value \n"}], "first": "正文"},
        {"text": "\nMarkdown\n"},
        [False, 0, None],
        "",
        0,
    ],
)
def test_declared_json_values_survive_without_business_schema(setup, content):
    config, workspace = setup
    config["l1_format"] = "json"
    (workspace / "handoff").write_text(json.dumps(content, ensure_ascii=False))
    result = state.save_layers(PublicFixture(), workspace, config, {}, "json")
    assert result["operation"]["outcome"] == "CONFIRMED"
    assert result["payload"][config["state_field"]]["l1"] == content


@pytest.mark.parametrize("change", ["missing", "empty", "oversize", "symlink", "foreign_owner"])
def test_ineligible_candidates_never_write(setup, change):
    config, workspace = setup
    call = PublicFixture()
    path = workspace / "handoff"
    if change == "missing":
        path.unlink()
    elif change == "empty":
        path.write_text(" \r\n")
    elif change == "oversize":
        path.write_text("x" * 4097)
    elif change == "symlink":
        path.unlink()
        path.symlink_to(workspace / "details")
    else:
        call.current = head({config["state_field"]: {"owner": "someone-else"}}, 1)
    result = state.save_layers(call, workspace, config, {}, "unused")
    assert result["operation"]["attempted"] is False and not call.writes


def test_detail_prefetch_limit_and_version_failure_do_not_change_arm(setup):
    config, workspace = setup
    call = PublicFixture()
    (workspace / "details").write_text("x" * 8000)
    state.save_layers(call, workspace, config, {}, "save")
    files = runner.manifest(workspace)
    bootstrap = state.assemble_layers(call.current, workspace, "B", config, files)
    assert "prefetched_detail" not in bootstrap
    with pytest.raises(state.LocalGateError, match="NO_TRUNCATION"):
        state.assemble_layers(call.current, workspace, "A", config, files)
    (workspace / "details").write_text("changed")
    with pytest.raises(state.LocalGateError, match="VERSION_UNAVAILABLE"):
        state.assemble_layers(call.current, workspace, "B", config, files)


def test_unknown_head_layout_is_not_guessed(setup):
    config, workspace = setup
    with pytest.raises(state.LocalGateError, match="LAYOUT_NOT_CONFIGURED"):
        state.assemble_layers(head({"looks_like_l1": "text"}, 1), workspace, "B", config, {})


def test_historical_run_and_worker_refuse_before_any_model_or_service(setup, monkeypatch):
    _, workspace = setup
    monkeypatch.setattr(runner.base, "prepare", lambda *a, **k: pytest.fail("Service launched"))
    with pytest.raises(state.LocalGateError, match="NO_NEW_MODEL_AUTHORIZATION"):
        runner.run(workspace / "unused")
    (workspace / "config.json").write_text("{}")
    with pytest.raises(state.LocalGateError, match="NO_NEW_MODEL_AUTHORIZATION"):
        runner.session(workspace, "G")


def test_retrieved_source_revalidated_before_resend_and_inherited_by_files():
    record = {
        "evidence_id": "source",
        "retention_state": "READABLE",
        "revoked_at": None,
        "permission_snapshot": {"readable": True, "project_ids": ["project"]},
    }
    guard = state.FileDisclosure("project", {"independent": []}, lambda _: record)
    guard.acquired(
        {
            "schema_version": "memory-evidence-context-v1",
            "evidence": [{"text": "arbitrary-uuid-looking-text", "evidence_ids": ["source"]}],
        }
    )
    guard.created("derived")
    assert guard.file_refs["derived"] == ["source"]
    guard.before_request()
    record["revoked_at"] = "now"
    with pytest.raises(state.LocalGateError, match="DISCLOSURE_DENIED"):
        guard.before_request()
    with pytest.raises(state.LocalGateError, match="DISCLOSURE_DENIED"):
        guard.read("derived")
    guard.read("independent")
    assert guard.visible({"derived": "one", "independent": "two"}) == {"independent": "two"}


@pytest.mark.parametrize("change", ["project", "unknown", "retention", "readable"])
def test_file_disclosure_fails_closed_at_current_scope(change):
    record = {
        "evidence_id": "source",
        "retention_state": "READABLE",
        "permission_snapshot": {"readable": True, "project_ids": ["project"]},
    }
    if change == "project":
        record["permission_snapshot"]["project_ids"] = ["another"]
    elif change == "unknown":
        record = {}
    elif change == "retention":
        record["retention_state"] = "PURGED"
    else:
        record["permission_snapshot"]["readable"] = False
    guard = state.FileDisclosure("project", {"file": ["source"]}, lambda _: record)
    with pytest.raises(state.LocalGateError, match="FILE_DISCLOSURE"):
        guard.read("file")


def test_transport_itself_refuses_closed_config_before_constructing_http_client(
    tmp_path, monkeypatch
):
    provider = importlib.import_module("v02_local_provider")
    config = json.loads(runner.CONFIG.read_text())
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: pytest.fail("HTTP constructed"))
    with pytest.raises(provider.LocalGateError, match="NO_NEW_MODEL_AUTHORIZATION"):
        provider.LocalProvider(config, tmp_path, "G")
