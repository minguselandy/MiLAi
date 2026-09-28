"""Pure operation support, separate from intent or content correctness."""

from __future__ import annotations

from typing import Any

from milai_lab.methods.memory_result import correction_marker, verify_result

SCOPE = {"run_id": "run", "arm_id": "C", "user_id": "alice", "message_key": "thread:0"}


def _receipt(ref: str, status: str, *, owner: str = "alice") -> dict[str, Any]:
    return {
        **SCOPE,
        "user_id": owner,
        "ref": ref,
        "name": "manage_memory",
        "transport_status": "success" if status != "not_found" else "error",
        "parsed": {"ok": status != "not_found", "status": status},
    }


def test_committed_without_actual_change_or_with_foreign_receipt_is_not_supported() -> None:
    claim = {"status": "committed", "receipt_refs": ["foreign"]}
    result = verify_result(claim, [_receipt("foreign", "created", owner="bob")], SCOPE)
    assert not result["declaration_supported"]
    assert "MEMORY_RESULT_RECEIPT_NOT_CURRENT" in result["reasons"]
    assert result["successful_change_refs"] == []
    assert verify_result({"status": "committed", "receipt_refs": []}, [], SCOPE)["needs_correction"]


def test_partial_commits_and_unreferenced_errors_never_certify_semantic_completion() -> None:
    result = verify_result(
        {"status": "committed", "receipt_refs": ["ok"]},
        [_receipt("ok", "created"), _receipt("bad", "not_found")],
        SCOPE,
    )
    assert result["declaration_supported"]
    assert result["partial_operations_observed"]
    assert result["unreferenced_failed_operation_refs"] == ["bad"]
    assert result["semantic_completion"] is None


def test_no_change_without_writes_is_not_semantic_success_or_an_automatic_correction() -> None:
    result = verify_result({"status": "no_change", "receipt_refs": []}, [], SCOPE)
    assert result["declaration_supported"] and not result["needs_correction"]
    assert result["semantic_completion"] is None
    contradicted = verify_result(
        {"status": "no_change", "receipt_refs": []}, [_receipt("write", "updated")], SCOPE
    )
    assert contradicted["reasons"] == ["MEMORY_RESULT_NO_CHANGE_CONTRADICTS_WRITE"]


def test_unchanged_update_and_read_are_not_new_commits() -> None:
    rows = [
        _receipt("unchanged", "no_change"),
        {**SCOPE, "ref": "read", "name": "read_memory", "transport_status": "success"},
    ]
    result = verify_result({"status": "no_change", "receipt_refs": ["read"]}, rows, SCOPE)
    assert result["declaration_supported"] and result["zero_write_refs"] == ["unchanged"]
    assert not verify_result({"status": "committed", "receipt_refs": ["read"]}, rows, SCOPE)[
        "declaration_supported"
    ]


def test_marker_is_bound_to_current_public_turn_and_does_not_cross_next_user() -> None:
    marker = {"message_key": "thread:0"}
    rows = [{"type": "human"}, {"type": "ai", "response_metadata": {"memory_correction": marker}}]
    assert correction_marker(rows, "thread:0") == marker
    assert correction_marker(rows, "thread:1") is None
    assert correction_marker([*rows, {"type": "human"}], "thread:0") is None
