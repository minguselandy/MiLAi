"""Fixed workflow purposes and unchanged R04 fresh-scope routes; synthetic only."""

import ast
import inspect
import json
import sqlite3
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0224_cpu_workflow_batch as old
import v0224_k3_cpu_batch as new


@pytest.mark.parametrize("name", list(new.INSTANCE_ORDER))
def test_fixed_purposes_and_stages(name, monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", name)
    monkeypatch.setattr(new, "make_authorization", lambda *args, **kwargs: {})
    root = new.CPU_BASE / name
    grant = new.cpu_authorization_source()
    auth = new.make_cpu_authorization(root, issued=1, expires=2, history={})
    stages = ["PREP", "P3", "P4"] if name == new.K3_INSTANCE else ["PREP"]
    assert auth["stages"] == grant["stages"] == stages
    assert auth["purpose"] == grant["purpose"] == new.workpoint_purpose(root)
    assert new.selected_root() == root


@pytest.mark.parametrize("name", ["", "digestv1-d1-u1", "flowv1-k3-extra"])
def test_old_or_unknown_selector_refused(name, monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", name)
    with pytest.raises(new.ProviderStop):
        new.selected_root()


def test_old_root_and_cross_purpose_root_refused(monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", new.INSTANCE_ORDER[0])
    monkeypatch.setattr(new, "make_authorization", lambda *args, **kwargs: {})
    for root in (old.CPU_BASE / "flowv1-d1-u1", new.CPU_BASE / "invalid"):
        with pytest.raises(new.ProviderStop):
            new.make_cpu_authorization(root, issued=1, expires=2, history={})


def test_same_scope_lineage_authority_and_all_fresh_routes():
    assert new.StaticAuthority is old.StaticAuthority
    assert new.BundleReadScope is old.BundleReadScope
    assert new.verify_lineage_r03 is old.verify_lineage_r03

    def tree(function):
        return ast.dump(ast.parse(textwrap.dedent(inspect.getsource(function))))

    for name in (
        "__init__",
        "_new_scope",
        "authorize",
        "_operation",
        "artifact",
        "freeze_artifact",
        "finish",
        "_p3_gate",
        "_read_artifact_row",
    ):
        assert tree(getattr(new.OfflineBatch, name)) == tree(getattr(old.OfflineBatch, name)), name


def test_cpu_phase_efficiency_is_nonblocking_but_other_caps_retained(monkeypatch):
    monkeypatch.setattr(
        new,
        "make_authorization",
        lambda *args, **kwargs: {
            "episode_wall_seconds": 300,
            "http_wall_seconds": 60,
            "concurrency": 1,
            "new_unknown_stops_all": True,
        },
    )
    auth = new.make_cpu_authorization(new.CPU_ROOT, issued=1, expires=2, history={})
    assert auth["phase_wall_seconds"] == {"P3": 129600, "P4": 129600}
    assert auth["cpu_efficiency_gate_enforced"] is False
    assert auth["episode_wall_seconds"] == 300 and auth["http_wall_seconds"] == 60
    assert auth["new_unknown_stops_all"] is True
    assert auth["stages"] == ["PREP", "P3", "P4"]


def test_phase_source_changes_only_constant_without_losing_journal_checks():
    from v0222_presentation_batch_v2 import Batch

    for name in ("launch_once", "_check_journal", "_check_claims"):
        expected = inspect.getsource(getattr(Batch, name)).replace(
            "PHASE_SECONDS", "CPU_PHASE_SECONDS"
        )
        actual = inspect.getsource(getattr(new.OfflineBatch, name))
        assert ast.dump(ast.parse(textwrap.dedent(expected))) == ast.dump(
            ast.parse(textwrap.dedent(actual))
        )


@pytest.mark.parametrize("corruption", [None, "deadline", "owner", "marker"])
def test_late_cpu_claim_uses_current_phase_and_preserves_integrity(
    tmp_path, monkeypatch, corruption
):
    from v0222_presentation_batch_v2 import PHASE_SECONDS

    batch = object.__new__(new.OfflineBatch)
    batch.auth = {"expires_unix": 129601}
    batch.binding_sha = "binding"
    marker_path = tmp_path / "claim.json"
    monkeypatch.setattr(batch, "claim_marker_path", lambda episode: marker_path)
    started = float(PHASE_SECONDS["P3"] + 5)
    deadline = started + 300
    claim = {"episode": "e1", "pid": 102, "started": started, "deadline": deadline}
    row = {"id": "e1", "stage": "P3", "status": "RUNNING", "pid": 102, "deadline": deadline}
    if corruption == "deadline":
        claim["deadline"] += 1
        row["deadline"] += 1
    if corruption == "owner":
        row["pid"] = 103
    marker = {**claim, "binding_sha256": batch.binding_sha}
    if corruption == "marker":
        marker["binding_sha256"] = "wrong"
    marker_path.write_text(json.dumps(marker))
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE claims (episode TEXT, pid INTEGER, started REAL, deadline REAL)")
        db.execute("CREATE TABLE launches (stage TEXT, pid INTEGER, started REAL)")
        db.execute("INSERT INTO launches VALUES ('P3', 101, 1)")
        db.execute("INSERT INTO claims VALUES (:episode, :pid, :started, :deadline)", claim)
        if corruption:
            with pytest.raises(
                new.ProviderStop,
                match="CLAIM_MARKER_DRIFT"
                if corruption == "marker"
                else "CLAIM_OWNER_OR_EPISODE_DEADLINE_DRIFT",
            ):
                batch._check_claims(db, [row])
        else:
            batch._check_claims(db, [row])
    finally:
        db.close()
