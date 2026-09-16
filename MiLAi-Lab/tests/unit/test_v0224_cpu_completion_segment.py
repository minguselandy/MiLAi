"""Explicit deadline delta and no imported acceptance; synthetic files/SQLite only."""

import ast
import copy
import inspect
import json
import sqlite3
import sys
import textwrap
from contextlib import nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0222_presentation_batch_v2 as original_batch
import v0222_presentation_terminal_v2 as original_terminal
import v0224_cpu_completion_segment as segment
import v0224_k3_cpu_batch as prior


def tree(value):
    return ast.dump(ast.parse(textwrap.dedent(value)))


def test_only_deadline_business_delta_and_no_global_patch():
    for name in ("claim", "_check_claims"):
        source = inspect.getsource(getattr(original_batch.Batch, name))
        source = source.replace("PHASE_SECONDS", "CPU_PHASE_SECONDS").replace(
            "+ 300", "+ CLAIM_SECONDS"
        )
        assert tree(source) == tree(inspect.getsource(getattr(segment.Batch, name)))
    source = inspect.getsource(original_terminal.audit_claimed_episode)
    source = source.replace("+ 300", "+ CLAIM_SECONDS").replace("<= 300", "<= CLAIM_SECONDS")
    assert tree(source) == tree(inspect.getsource(segment.audit_claimed_episode))
    assert original_terminal.PHASE_SECONDS == {"P3": 1800, "P4": 7200}
    assert original_batch.PHASE_SECONDS == {"P3": 1800, "P4": 7200}
    for name in (
        "_new_scope",
        "_operation",
        "authorize",
        "artifact",
        "finish",
        "_read_artifact_row",
        "initialize",
        "reserve_request",
        "settle_event",
        "launch_once",
        "_check_journal",
    ):
        assert getattr(segment.Batch, name) is getattr(prior.OfflineBatch, name)
    assert segment.StaticAuthority is prior.StaticAuthority
    assert segment.Batch._new_scope.__globals__["BundleReadScope"] is prior.BundleReadScope


def test_exact_cpu_revision_no_contradictory_old_claim(monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", segment.INSTANCE)
    monkeypatch.setattr(
        segment,
        "make_authorization",
        lambda *a, **k: {
            "episode_wall_seconds": 300,
            "http_wall_seconds": 60,
            "concurrency": 1,
            "new_unknown_stops_all": True,
        },
    )
    auth = segment.make_cpu_authorization(segment.CPU_ROOT, issued=1, expires=2, history={})
    assert auth["episode_wall_seconds"] == auth["claim_seconds"] == 3600
    assert auth["phase_wall_seconds"] == {"P3": 129600, "P4": 129600}
    assert auth["http_wall_seconds"] == 60 and auth["new_unknown_stops_all"]
    assert auth["real_http_allowed"] is False and auth["stages"] == ["PREP", "P4"]
    with pytest.raises(segment.ProviderStop):
        segment.make_cpu_authorization(prior.CPU_ROOT, issued=1, expires=2, history={})


@pytest.mark.parametrize("name", ["", "completev1-k3", "segmentv1-p4-copy"])
def test_other_selector_refused(monkeypatch, name):
    monkeypatch.setenv("MILA_V0224_INSTANCE", name)
    with pytest.raises(segment.ProviderStop):
        segment.selected_root()


@pytest.mark.parametrize("corruption", [None, "old300", "owner", "marker"])
def test_new_claim_deadline_preserves_exact_owner_and_marker(tmp_path, monkeypatch, corruption):
    batch = object.__new__(segment.Batch)
    batch.auth = {"expires_unix": 200000.0}
    batch.binding_sha = "binding"
    path = tmp_path / "claim.json"
    monkeypatch.setattr(batch, "claim_marker_path", lambda _: path)
    deadline = 8600.0 if corruption != "old300" else 5300.0
    claim = dict(episode="e", pid=12, started=5000.0, deadline=deadline)
    row = dict(id="e", stage="P4", status="RUNNING", pid=12, deadline=deadline)
    if corruption == "owner":
        row["pid"] = 13
    path.write_text(
        json.dumps({**claim, "binding_sha256": "bad" if corruption == "marker" else "binding"})
    )
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE claims(episode TEXT,pid INTEGER,started REAL,deadline REAL)")
        db.execute("CREATE TABLE launches(stage TEXT,pid INTEGER,started REAL)")
        db.execute("INSERT INTO launches VALUES('P4',11,1.0)")
        db.execute("INSERT INTO claims VALUES(:episode,:pid,:started,:deadline)", claim)
        if corruption:
            with pytest.raises(segment.ProviderStop):
                batch._check_claims(db, [row])
        else:
            batch._check_claims(db, [row])


@pytest.mark.parametrize("seconds,accepted", [(300.01, True), (3600.0, True), (3600.01, False)])
def test_terminal_complete_business_and_new_outer_boundary(
    tmp_path, monkeypatch, seconds, accepted
):
    import test_v0222_presentation_terminal_v2 as fixtures

    batch, kwargs, auditor = fixtures.synthetic(tmp_path, monkeypatch, stage="P4", count=4)
    monkeypatch.setattr(segment, "audit_episode", auditor)
    for key in ("episode_row", "claim_row"):
        kwargs[key]["deadline"] = 3700.0
    fixtures.mutate_json(
        batch.claim_marker_path(batch.episode), lambda x: x.update(deadline=3700.0)
    )
    fixtures.mutate_json(
        batch.root / "exits" / (batch.episode + ".json"), lambda x: x.update(seconds=seconds)
    )
    if accepted:
        result = segment.audit_claimed_episode(batch, batch.episode, **kwargs)
        assert result["status"] == "PASS" and result["cost"]["requests"] == 4
    else:
        with pytest.raises(segment.ProviderStop):
            segment.audit_claimed_episode(batch, batch.episode, **kwargs)


def test_initialize_contains_only_sixteen_new_pending_rows(tmp_path, monkeypatch):
    batch = object.__new__(segment.Batch)
    batch.root, batch.path, batch.binding_sha = tmp_path, tmp_path / "batch.sqlite", "new-binding"
    batch.plan = {"P3": [], "P4": [{"id": f"original-{i}"} for i in range(9, 25)]}
    monkeypatch.setattr(batch, "authorize", lambda stage: {})
    batch.initialize()
    with sqlite3.connect(batch.path) as db:
        assert db.execute(
            "SELECT id,stage,status,pid,deadline FROM episodes ORDER BY ordinal"
        ).fetchall() == [(f"original-{i}", "P4", "PENDING", None, None) for i in range(9, 25)]
        assert db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


class SyntheticScope:
    def __init__(self, values):
        self.values = values
        self.reads = []

    def physical_reads(self):
        return nullcontext()

    def read_bytes(self, path, digest):
        self.reads.append((str(path), digest))
        return b"tiny"

    def read_json(self, path, digest):
        self.read_bytes(path, digest)
        return copy.deepcopy(self.values[str(path)])


def predecessor(monkeypatch):
    old = {
        "P3": [{"id": f"p3-{i}"} for i in range(16)],
        "P4": [
            {"id": f"p4-{i}", "stage": "P4", "scope": f"s{i}", "actions": [1, 2]} for i in range(24)
        ],
    }
    lineage = {
        "predecessor_root": str(segment.PREDECESSOR_ROOT),
        "predecessor_binding_sha256": "old-binding",
        "predecessor_contract": {
            "path": "/old-contract",
            "sha256": segment.PREDECESSOR_CONTRACT_SHA256,
        },
        "failure_terminal": {"path": str(segment.FAILURE_PATH), "sha256": segment.FAILURE_SHA256},
        "predecessor_snapshot": {"path": "/snapshot", "sha256": "snapshot"},
        "files": {"/original-evidence": "fixed"},
        "accepted_prefix": {
            "P3_ids": [s["id"] for s in old["P3"]],
            "P4_ids": [s["id"] for s in old["P4"][:8]],
        },
        "positions": [s["id"] for s in old["P4"][8:]],
    }
    snapshot = {key: [] for key in segment.TABLE_QUERIES}
    snapshot["meta"] = [{"key": "stop", "value": "TimeoutExpired"}]
    snapshot["episodes"] = [
        dict(
            id=s["id"],
            stage=stage,
            ordinal=i,
            status="PASS" if stage == "P3" or i < 8 else "FAIL" if i == 8 else "PENDING",
        )
        for stage in ("P3", "P4")
        for i, s in enumerate(old[stage])
    ]
    values = {
        str(segment.SEGMENT_LINEAGE_PATH): lineage,
        "/snapshot": snapshot,
        "/old-contract": {"root": str(segment.PREDECESSOR_ROOT), "binding_sha256": "old-binding"},
        str(segment.PREDECESSOR_ROOT / "execution-binding.json"): {"manifest.json": "old-manifest"},
        str(segment.PREDECESSOR_ROOT / "manifest.json"): {"contract": old},
    }
    for name, status in [
        ("P3_gate", "G_P3_PASS"),
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("P4_preflight", "G_PREFLIGHT_PASS"),
        ("P3_references", None),
        ("P4_references", None),
    ]:
        snapshot["artifacts"].append(dict(name=name, path="/" + name, sha256="fixed"))
        values["/" + name] = (
            {"status": status}
            if status
            else {"references": [None] * (16 if name.startswith("P3") else 80)}
        )
    monkeypatch.setattr(segment, "_old_snapshot", lambda: copy.deepcopy(snapshot))
    plan = {
        "P3": [],
        "P4": copy.deepcopy(old["P4"][8:]),
        "completion_segment": {
            "path": str(segment.SEGMENT_LINEAGE_PATH),
            "sha256": segment.SEGMENT_LINEAGE_SHA256,
        },
    }
    return SyntheticScope(values), plan, snapshot


@pytest.mark.parametrize(
    "change", [None, "renamed", "missing", "imported_p3", "old_fail_pass", "sql_drift"]
)
def test_only_exact_missing_original_specs_and_immutable_failed_prior(monkeypatch, change):
    scope, plan, snapshot = predecessor(monkeypatch)
    if change == "renamed":
        plan["P4"][0]["id"] += "-new"
    if change == "missing":
        plan["P4"].pop()
    if change == "imported_p3":
        plan["P3"] = [{"id": "fake-pass"}]
    if change == "old_fail_pass":
        snapshot["episodes"][24]["status"] = "PASS"
    if change == "sql_drift":
        monkeypatch.setattr(segment, "_old_snapshot", lambda: {})
    if change:
        with pytest.raises(segment.ProviderStop):
            segment.validate_predecessor(scope, plan)
    else:
        segment.validate_predecessor(scope, plan)
        assert ("/original-evidence", "fixed") in scope.reads


def test_old_sql_uses_read_only_connection_and_closes_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(segment, "PREDECESSOR_ROOT", tmp_path)
    (tmp_path / "batch.sqlite").write_bytes(b"only-existence-marker")
    seen = []
    primary = RuntimeError("bad SQL")

    class Connection:
        def execute(self, query):
            seen.append(query)
            if query != "BEGIN":
                raise primary

        def close(self):
            seen.append("CLOSED")

    def connect(database, **kwargs):
        assert database.endswith("?mode=ro") and kwargs["uri"] is True
        return Connection()

    monkeypatch.setattr(segment.sqlite3, "connect", connect)
    with pytest.raises(RuntimeError) as caught:
        segment._old_snapshot()
    assert caught.value is primary and seen[-1] == "CLOSED"


def test_ready_rejects_replacement_pass_artifact_row(tmp_path, monkeypatch):
    scope, plan, _snapshot = predecessor(monkeypatch)
    batch = object.__new__(segment.Batch)
    batch.plan = plan
    monkeypatch.setattr(
        segment, "validate_predecessor", lambda *a: scope.values[str(segment.SEGMENT_LINEAGE_PATH)]
    )
    # Exact frozen rows required before any content/status-only acceptance.
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE artifacts(name TEXT,path TEXT,sha256 TEXT)")
        db.execute("INSERT INTO artifacts VALUES ('scope_review','/different-pass','other')")
        with pytest.raises(segment.ProviderStop, match="EXACT_INHERITED_ARTIFACT_ROW_REQUIRED"):
            batch._ready(db, "P4", scope)


def test_references_preserve_original_order_and_filter_only_active_ids(monkeypatch):
    batch = object.__new__(segment.Batch)
    batch.plan = {"P3": [], "P4": [{"id": "old-9", "actions": [1, 2]}]}
    rows = [
        {"episode": ident, "turn": turn} for ident in ("old-8", "old-9") for turn in range(1, 5)
    ]
    monkeypatch.setattr(prior.OfflineBatch, "references", lambda *a: copy.deepcopy(rows))
    assert batch.references("P4") == rows[4:]
    rows[-1]["turn"] = 3
    with pytest.raises(
        segment.ProviderStop, match="COMPLETE_UNCHANGED_SEGMENT_REFERENCES_REQUIRED"
    ):
        batch.references("P4")
