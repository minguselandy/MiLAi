from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDE = ROOT / "docs/contracts/DG13U-U1-user-direct-execution-override-20260825.md"
INTERFACE = ROOT / "contracts/agent/v1/dg13u-u1-interface-freeze.md"
PROPOSAL = ROOT / "docs/contracts/DG13U-U1-owner-decisions-v1.md"
HEADERS = ROOT / "contracts/agent/v1/openworker-task-metadata-headers.md"
FIXTURE = ROOT / "contracts/agent/v1/dg13u-u1-candidate-fixture.json"

EXPECTED_BINDINGS = {
    PROPOSAL: "9e38110f2eaea14f4fe94465b24e994b7ab7d770a2a0bfce5349a6d358f6745d",
    HEADERS: "b36feaff924cc10275040a458f17449907621b4ecadf5af2f92771784db60c4f",
    FIXTURE: "47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def test_user_direct_override_binds_the_exact_accepted_u1_decisions() -> None:
    text = OVERRIDE.read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())
    assert "ACCEPT_FOR_EXECUTION_BY_USER_DIRECTIVE" in text
    assert (
        "Human owner identity and a separate human acceptance receipt are not required"
        in normalized_text
    )
    assert "independent, read-only model audit evidence" in text
    for path, expected in EXPECTED_BINDINGS.items():
        assert _sha256(path) == expected
        assert expected in text


def test_interface_freeze_contains_the_complete_provider_barrier_matrix() -> None:
    text = INTERFACE.read_text(encoding="utf-8")
    expected_rows = {
        "`NO_MEMORY_NEEDED` | `CONTINUE` | `ALLOWED`",
        "`CONTEXT_READY_CURRENT` | `CONTINUE` | `ALLOWED`",
        "`MEMORY_REQUIRED_BUT_UNAVAILABLE` | `RETRY` | `PROHIBITED`",
        "`MEMORY_INSUFFICIENT` | `ASK_USER` | `PROHIBITED`",
        "`GOVERNANCE_BLOCKED` | `ABSTAIN` | `PROHIBITED`",
    }
    assert all(row in text for row in expected_rows)
    assert "Provider calls are never automatically retried" in text
    assert "one logical hidden MCP call" in text


def test_execution_binding_rejects_a_one_byte_proposal_drift() -> None:
    expected = EXPECTED_BINDINGS[PROPOSAL]
    drifted = hashlib.sha256(PROPOSAL.read_bytes() + b"\n").hexdigest()
    assert drifted != expected


def test_frozen_state_key_aliases_are_exact_and_non_colliding() -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    families = value["families"]
    assert [row["state_key"] for row in families] == [
        "release.target",
        "release.database",
        "release.decision",
    ]
    owners: dict[str, tuple[str, str, str]] = {}
    for row in families:
        owner = (row["project"], row["state_key"], row["claim_type"])
        for alias in row["aliases"]:
            normalized = _normalize(alias)
            assert normalized not in owners
            owners[normalized] = owner
    assert set(owners) == {
        "current release target",
        "当前发布目标",
        "current release database",
        "current release config",
        "当前发布数据库",
        "当前发布配置",
        "current governed release decision",
        "当前受治理的发布决定",
    }
