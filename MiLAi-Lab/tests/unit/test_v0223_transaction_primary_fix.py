"""Corrected DEV baseline only; old missing-guarantee characterizations remain."""

import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0222_presentation_batch_v2 import claimed
from test_v0222_presentation_batch_v2 import setup as core_fixture

import v0221_http_batch as original
import v0222_presentation_batch_v2 as core
from v0220_provider_hardened import ProviderStop
from v0223_transaction_primary_fix import corrected_transaction, installed_transaction_fix


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / "journal.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO meta VALUES ('binding','bound')")
    return SimpleNamespace(path=path, binding_sha="bound")


def inserted(connect, path):
    with connect(path) as db:
        return db.execute("SELECT value FROM meta WHERE key='body'").fetchone()


@pytest.mark.parametrize(
    "origin", ["body", "interrupt", "commit", "commit_after", "begin", "binding"]
)
@pytest.mark.parametrize("cleanup", ["none", "rollback", "close", "both"])
def test_primary_identity_and_cleanup_notes(journal, monkeypatch, origin, cleanup):
    connect = sqlite3.connect
    primary = KeyboardInterrupt("primary") if origin == "interrupt" else RuntimeError("primary")
    calls = []
    if origin == "binding":
        journal.binding_sha = "wrong"

    class Connection:
        def __init__(self, db):
            object.__setattr__(self, "db", db)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def __setattr__(self, name, value):
            setattr(self.db, name, value)

        def execute(self, sql, *args):
            calls.append(sql)
            if origin == "begin" and sql == "BEGIN IMMEDIATE":
                raise primary
            return self.db.execute(sql, *args)

        def commit(self):
            calls.append("COMMIT")
            if origin == "commit_after":
                self.db.commit()
            if origin in {"commit", "commit_after"}:
                raise primary
            return self.db.commit()

        def rollback(self):
            calls.append("ROLLBACK")
            if cleanup in {"rollback", "both"}:
                raise OSError("rollback injected")
            return self.db.rollback()

        def close(self):
            calls.append("CLOSE")
            self.db.close()
            if cleanup in {"close", "both"}:
                raise OSError("close injected")

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: Connection(connect(*a, **kw)))
    with installed_transaction_fix():
        with pytest.raises(BaseException) as caught:
            with original.Batch.transaction(journal) as db:
                db.execute("INSERT INTO meta VALUES ('body','one')")
                if origin in {"body", "interrupt"}:
                    raise primary
    if origin == "binding":
        assert type(caught.value) is ProviderStop
        assert str(caught.value) == "COORDINATOR_BINDING_DRIFT"
    else:
        assert caught.value is primary
    notes = getattr(caught.value, "__notes__", [])
    assert len(notes) == (2 if cleanup == "both" else 0 if cleanup == "none" else 1)
    if cleanup in {"rollback", "both"}:
        assert any(
            "SECONDARY_TRANSACTION_ROLLBACK_FAILURE: OSError('rollback injected')" == n
            for n in notes
        )
    if cleanup in {"close", "both"}:
        assert any(
            "SECONDARY_TRANSACTION_CLOSE_FAILURE: OSError('close injected')" == n for n in notes
        )
    assert calls[-2:] == ["ROLLBACK", "CLOSE"]
    assert calls.count("COMMIT") == (1 if origin in {"commit", "commit_after"} else 0)
    assert inserted(connect, journal.path) == (("one",) if origin == "commit_after" else None)


def test_normal_sql_and_cleanup_order_matches_original(journal, monkeypatch):
    connect = sqlite3.connect
    arms = []
    for transaction in (original.Batch.transaction, corrected_transaction):
        calls = []

        class Connection:
            def __init__(self, db, log):
                object.__setattr__(self, "db", db)
                object.__setattr__(self, "log", log)

            def __getattr__(self, name):
                value = getattr(self.db, name)
                if name in {"commit", "rollback", "close"}:

                    def call():
                        self.log.append(name)
                        return value()

                    return call
                return value

            def __setattr__(self, name, value):
                setattr(self.db, name, value)

            def execute(self, sql, *args):
                self.log.append(sql)
                return self.db.execute(sql, *args)

        monkeypatch.setattr(
            sqlite3, "connect", lambda *a, _log=calls, **kw: Connection(connect(*a, **kw), _log)
        )
        with transaction(journal) as db:
            assert db.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 1
        arms.append(calls)
    assert arms[0] == arms[1]
    assert arms[1][-2:] == ["commit", "close"]


def test_cleanup_only_failure_after_commit_stops_without_erasing_effect(tmp_path, monkeypatch):
    batch = claimed(core_fixture.__wrapped__(tmp_path, monkeypatch))[0]
    connect = sqlite3.connect
    first = True
    close_error = OSError("post-commit close failure")

    class Connection:
        def __init__(self, db):
            object.__setattr__(self, "db", db)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def __setattr__(self, name, value):
            setattr(self.db, name, value)

        def close(self):
            self.db.close()
            raise close_error

    def connect_once(*a, **kw):
        nonlocal first
        db = connect(*a, **kw)
        if first:
            first = False
            return Connection(db)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect_once)
    with installed_transaction_fix():
        with pytest.raises(OSError) as caught:
            with batch._operation("P3", episode="P3-00") as (db, _, _state):
                db.execute("INSERT INTO meta VALUES ('body','one')")
        assert caught.value is close_error
        assert inserted(connect, batch.path) == ("one",)  # Commit really occurred.
        with pytest.raises(ProviderStop, match="BATCH_STOPPED_NO_RETRY"):
            batch.http_admit("P3-00")
        with connect(batch.path) as db:
            assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM meta WHERE key='body'").fetchone()[0] == 1
        assert batch.snapshot()["stop"] == "OSError"


def test_installation_restores_classes_aliases_and_new_imports(monkeypatch):
    before = original.Batch.transaction
    module = ModuleType("v0223_test_transaction_alias")
    module.alias = before
    module.Child = type(
        "Child", (original.Batch,), {"__module__": module.__name__, "copied": before}
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    late = ModuleType("v0223_test_transaction_late")
    with pytest.raises(RuntimeError, match="body outside transaction"):
        with installed_transaction_fix():
            assert original.Batch.transaction is core.Batch.transaction is corrected_transaction
            assert module.alias is module.Child.copied is corrected_transaction
            late.alias = original.Batch.transaction
            monkeypatch.setitem(sys.modules, late.__name__, late)
            with pytest.raises(RuntimeError, match="MUST_NOT_BE_NESTED"):
                with installed_transaction_fix():
                    pass
            raise RuntimeError("body outside transaction")
    assert original.Batch.transaction is core.Batch.transaction is before
    assert module.alias is module.Child.copied is late.alias is before


def test_body_cleanup_and_stop_failures_keep_body_primary(tmp_path, monkeypatch):
    batch = core_fixture.__wrapped__(tmp_path, monkeypatch)[0]
    connect = sqlite3.connect
    primary = RuntimeError("body primary")

    class Connection:
        def __init__(self, db):
            object.__setattr__(self, "db", db)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def __setattr__(self, name, value):
            setattr(self.db, name, value)

        def rollback(self):
            raise OSError("rollback injected")

        def close(self):
            self.db.close()
            raise OSError("close injected")

    def fail_stop(reason):
        raise OSError("stop injected")

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: Connection(connect(*a, **kw)))
    monkeypatch.setattr(batch, "stop", fail_stop)
    with installed_transaction_fix():
        with pytest.raises(RuntimeError) as caught:
            with batch._operation("PREP") as (db, _, _state):
                db.execute("INSERT INTO meta VALUES ('body','one')")
                raise primary
    assert caught.value is primary
    assert len(primary.__notes__) == 3
    assert "SECONDARY_TRANSACTION_ROLLBACK_FAILURE" in primary.__notes__[0]
    assert "SECONDARY_TRANSACTION_CLOSE_FAILURE" in primary.__notes__[1]
    assert primary.__notes__[2] == "SECONDARY_STOP_FAILURE: OSError"
    assert inserted(connect, batch.path) is None
