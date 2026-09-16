from __future__ import annotations

import json
from pathlib import Path

from milai_hooks.config import install, uninstall


def test_install_is_idempotent_and_preserves_other_hooks_then_uninstalls_only_milai(
    tmp_path: Path,
) -> None:
    target = tmp_path / "agent-hooks.json"
    target.write_text(
        json.dumps(
            {
                "unrelated": {"preserve": True},
                "hooks": {
                    "SessionStart": [{"type": "command", "command": "existing-hook", "args": []}]
                },
            }
        ),
        encoding="utf-8",
    )
    target.chmod(0o640)
    first = install(target, scope="project")
    second = install(target, scope="project")
    assert first["entries_added"] == 5
    assert second["status"] == "ALREADY_INSTALLED"
    installed = json.loads(target.read_text())
    assert installed["unrelated"] == {"preserve": True}
    assert installed["hooks"]["SessionStart"][0]["command"] == "existing-hook"
    serialized = target.read_text()
    assert "MILAI_AGENT_TOKEN" not in serialized
    assert "capture_default" in serialized
    assert target.stat().st_mode & 0o777 == 0o640

    removed = uninstall(target)
    assert removed["entries_removed"] == 5
    final = json.loads(target.read_text())
    assert final["hooks"] == {
        "SessionStart": [{"args": [], "command": "existing-hook", "type": "command"}]
    }
    assert final["unrelated"] == {"preserve": True}


def test_installer_requires_explicit_regular_config_parent(tmp_path: Path) -> None:
    missing_parent = tmp_path / "missing" / "hooks.json"
    try:
        install(missing_parent, scope="user")
    except ValueError as error:
        assert "parent" in str(error)
    else:
        raise AssertionError("missing parent must be rejected")
