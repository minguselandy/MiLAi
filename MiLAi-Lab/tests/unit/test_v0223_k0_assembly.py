"""Offline K0 assembler integrity checks; no fixture or process creation."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from assemble_v0223_k0 import (
    compare_scopes,
    normalize_auth,
    normalize_plan,
    validate_snapshot,
)


def plan(instance="k1-u1"):
    return {
        stage: [
            {
                "id": f"{instance}-{stage.lower()}-{index:02d}",
                "scope": f"v0223-{instance}-{stage.lower()}-{index:02d}",
                "root": "open-root",
                "initial_state_sha256": "correct",
                "business": {"value": "unchanged"},
            }
            for index in range(1, count + 1)
        ]
        for stage, count in (("P3", 16), ("P4", 24))
    }


def test_auth_maps_only_root_batch_and_valid_clock():
    root = Path("/synthetic/k1-u1")
    auth = {
        "root": str(root),
        "batch_id": root.name,
        "issued_unix": 10,
        "expires_unix": 129610,
        "accepted_unknown": ["preserved"],
    }
    assert normalize_auth(auth, root) == {"accepted_unknown": ["preserved"]}
    auth["expires_unix"] += 1
    with pytest.raises(ValueError, match="UNCHANGED_AUTH_WINDOW"):
        normalize_auth(auth, root)


@pytest.mark.parametrize("change", ["id", "scope", "initial_state_sha256"])
def test_mechanical_plan_mapping_cannot_hide_arbitrary_changes(change):
    value = plan()
    value["P4"][0][change] = "wrong"
    with pytest.raises(ValueError):
        normalize_plan(
            value,
            "k1-u1",
            {"open-root": {}},
            lambda spec, public: ({**spec, "initial_state_sha256": "correct"}, {}),
        )


def test_normalization_preserves_business_fields():
    first = normalize_plan(plan(), "k1-u1", {"open-root": {}}, lambda spec, public: (spec, {}))
    second_plan = plan("k1-s1")
    second = normalize_plan(
        second_plan, "k1-s1", {"open-root": {}}, lambda spec, public: (spec, {})
    )
    assert first == second
    second_plan["P3"][0]["business"]["value"] = "changed"
    changed = normalize_plan(
        second_plan, "k1-s1", {"open-root": {}}, lambda spec, public: (spec, {})
    )
    assert first != changed


@pytest.mark.parametrize("field", ["id", "stage", "ordinal", "cap", "pid", "deadline"])
def test_snapshot_requires_exact_sql_plan_not_just_pending_count(field):
    value = plan()
    snapshot = {
        "episodes": [
            {
                "id": spec["id"],
                "stage": stage,
                "ordinal": index,
                "cap": 1 if stage == "P3" else 4,
                "status": "PENDING",
                "pid": None,
                "deadline": None,
            }
            for stage in ("P3", "P4")
            for index, spec in enumerate(value[stage])
        ],
        "meta": [{"key": "binding", "value": "pin"}],
        "events": [],
        "launches": [],
        "claims": [],
        "artifacts": [{"name": "engineering_checks"}],
    }
    validate_snapshot(snapshot, value, "pin", {"requests": 0}, {"requests": 0})
    snapshot["episodes"][0][field] = "wrong"
    with pytest.raises(ValueError, match="EXACT_FORTY_PENDING"):
        validate_snapshot(snapshot, value, "pin", {"requests": 0}, {"requests": 0})


def test_current_accounting_must_equal_empty_ledger_not_old_total():
    snapshot = {
        "episodes": [],
        "meta": [{"key": "binding", "value": "pin"}],
        "events": [],
        "launches": [],
        "claims": [],
        "artifacts": [{"name": "engineering_checks"}],
    }
    with pytest.raises(ValueError, match="EXACT_EMPTY_CURRENT_ACCOUNTING"):
        validate_snapshot(snapshot, {"P3": [], "P4": []}, "pin", {"requests": 0}, {"requests": 1})


def test_equal_file_count_cannot_hide_role_or_content_change():
    before = {
        "roles": {
            "/file": {"hash": "a", "bytes": 10, "json_parsed": False, "mechanically_mapped": False}
        },
        "stats": {"first_bytes": 10, "closing_bytes": 10},
    }
    changed = copy.deepcopy(before)
    changed["roles"]["/file"]["hash"] = "b"
    with pytest.raises(ValueError, match="NONMECHANICAL"):
        compare_scopes(before, changed, allow_mechanical_bytes=False)
    changed = copy.deepcopy(before)
    changed["roles"]["/other"] = changed["roles"].pop("/file")
    with pytest.raises(ValueError, match="ROLES_DIFFER"):
        compare_scopes(before, changed, allow_mechanical_bytes=False)


def test_prefix_reports_only_verified_mechanical_byte_delta():
    before = {
        "roles": {
            "<ROOT>/manifest.json": {
                "hash": "normalized",
                "bytes": 10,
                "json_parsed": True,
                "mechanically_mapped": True,
            }
        },
        "stats": {"first_bytes": 10, "closing_bytes": 10},
    }
    changed = copy.deepcopy(before)
    changed["roles"]["<ROOT>/manifest.json"]["bytes"] = 14
    changed["stats"] = {"first_bytes": 14, "closing_bytes": 14}
    with pytest.raises(ValueError, match="BYTES_DIFFER"):
        compare_scopes(before, changed, allow_mechanical_bytes=False)
    delta = compare_scopes(before, changed, allow_mechanical_bytes=True)
    assert delta["total_bytes_delta"] == 4
    assert delta["file_deltas"] == [{"role": "<ROOT>/manifest.json", "bytes_delta": 4}]
