from pathlib import Path

_RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def test_local_console_exposes_agent_status_inbox_joint_trace_and_data_gate() -> None:
    html = (_RUNTIME_ROOT / "src/milai/templates/index.html").read_text(encoding="utf-8")
    javascript = (_RUNTIME_ROOT / "src/milai/static/milai.js").read_text(encoding="utf-8")
    for marker in (
        "data-mode-badge",
        "profile-badge",
        "proposal-inbox",
        "inspect-issue-id",
        "copy-mcp",
        "data-classification",
        "action",
    ):
        assert marker in html
    assert "/v1/capabilities" in javascript
    assert "/v1/proposals?status=PENDING_REVIEW&limit=50" in javascript
    assert "DATA_MODE_BLOCKED" in javascript
    assert "chat-confirmation:v2:" in javascript
    assert "action_digest: actionDigest" in javascript
    config_source = javascript[javascript.index("const config = {") :]
    assert "tokenPlaceholder" in config_source
    assert 'byId("token").value' not in config_source
