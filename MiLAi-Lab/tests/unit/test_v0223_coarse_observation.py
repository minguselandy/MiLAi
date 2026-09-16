"""Synthetic-clock observation semantics; not performance or Gate A evidence."""

import hashlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope
from v0222_presentation_lineage_v2 import verify_lineage  # noqa: F401 -- installer prerequisite
from v0223_coarse_observation import CoarseObserver, installed


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance(self, value):
        self.value += value


def test_nested_exclusive_and_aggregate_envelopes():
    clock = Clock()
    observer = CoarseObserver("synthetic", enabled=True, clock=clock)
    with observer.span("execution"):
        clock.advance(2)
        for _ in range(2):
            with observer.span("json_parse_copy", aggregate=True):
                clock.advance(3)
                with observer.span("read_first", aggregate=True) as row:
                    row["read_bytes"] = 4
                    clock.advance(5)
            clock.advance(7)
    report = observer.report()
    rows = {row["category"]: row for row in report["records"]}
    assert rows["execution"]["inclusive_wall_ns"] == 32
    assert rows["execution"]["exclusive_wall_ns"] == 16
    assert rows["json_parse_copy"]["exclusive_wall_ns"] == 6
    assert rows["read_first"]["exclusive_wall_ns"] == 10
    assert rows["read_first"]["read_bytes"] == 8
    assert rows["read_first"]["count"] == 2
    assert sum(row["exclusive_wall_ns"] for row in rows.values()) == 32
    ids = {row["span_id"] for row in rows.values()}
    assert all(row["parent_span_id"] in ids | {None} for row in rows.values())


@pytest.mark.parametrize("failure", ["none", "entry", "body", "close", "both", "suppressed"])
def test_operation_includes_cleanup_and_preserves_exception(failure):
    clock = Clock()
    observer = CoarseObserver("synthetic", enabled=True, clock=clock)
    body_error = ValueError("body")
    close_error = RuntimeError("close")

    @contextmanager
    def original():
        clock.advance(3)
        if failure == "entry":
            raise close_error
        try:
            yield 42
        except ValueError as exc:
            if failure == "both":
                exc.add_note("close failed")
            if failure != "suppressed":
                raise
        finally:
            clock.advance(7)
        if failure == "close":
            raise close_error

    expected = body_error if failure in {"body", "both"} else close_error
    if failure in {"none", "suppressed"}:
        with observer.operation(original()) as value:
            assert value == 42
            clock.advance(5)
            if failure == "suppressed":
                raise body_error
    else:
        with pytest.raises(type(expected)) as caught, observer.operation(original()):
            clock.advance(5)
            if failure in {"body", "both"}:
                raise body_error
        assert caught.value is expected
    assert not observer.stack
    row = next(row for row in observer.records if row["category"] == "operation")
    assert row["inclusive_wall_ns"] == (3 if failure == "entry" else 15)
    assert observer.report()["status"] == "COMPLETE_SPANS"


def test_disabled_does_not_read_clock_or_patch():
    def forbidden():
        raise AssertionError("disabled clock")

    observer = CoarseObserver("synthetic", clock=forbidden)
    original = AdmissionReadScope.read_json
    with installed(observer), observer.span("execution"):
        assert AdmissionReadScope.read_json is original
    assert observer.records == []


def test_installed_read_roundtrip_mutation_rejection_and_restore(tmp_path):
    path = tmp_path / "fixture.json"
    raw = b'{"value":1}'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    original = AdmissionReadScope.read_json
    observer = CoarseObserver("synthetic", enabled=True, clock=Clock())
    with installed(observer), observer.span("execution"):
        with AdmissionReadScope() as scope:
            value = scope.read_json(path, digest)
            value["value"] = 99
            assert scope.read_json(path, digest) == {"value": 1}
        with pytest.raises(AdmissionReadError), AdmissionReadScope() as scope:
            scope.read_json(path, digest)
            path.write_bytes(b'{"value":2}')
    assert AdmissionReadScope.read_json is original
    assert not observer.stack
    first = [row for row in observer.records if row["category"] == "read_first"]
    closing = [row for row in observer.records if row["category"] == "read_closing"]
    assert sum(row["count"] for row in first) == 2
    assert sum(row["count"] for row in closing) == 2
    assert sum(row["read_bytes"] for row in first) == 2 * len(raw)
    assert len({row["scope_id"] for row in first}) == 2
    assert any(row["terminal_status"] == "UNWOUND" for row in observer.records)


def test_custom_batch_operation_override_and_restore():
    class Custom:
        def _authorize(self):
            return 1

        @contextmanager
        def _operation(self):
            yield 2

    original = Custom._operation
    observer = CoarseObserver("synthetic", enabled=True, clock=Clock())
    with installed(observer, batch_class=Custom), Custom()._operation() as value:
        assert value == 2
    assert Custom._operation is original
    assert {row["category"] for row in observer.records} >= {
        "operation",
        "operation_entry",
        "operation_body",
        "final_revalidation",
    }


def test_interval_union_rejects_aggregate_and_cross_process():
    from v0223_coarse_observation import interval_union_ns

    rows = [
        {
            "run_id": "r",
            "pid": 1,
            "category": "operation_entry",
            "timing_kind": "CONTIGUOUS_SPAN",
            "start_ns": start,
            "end_ns": end,
        }
        for start, end in [(1, 10), (3, 5), (9, 12), (15, 20)]
    ]
    assert interval_union_ns(rows, {"operation_entry"}) == 16
    rows[-1]["pid"] = 2
    with pytest.raises(ValueError, match="CLOCK_DOMAINS"):
        interval_union_ns(rows, {"operation_entry"})
    rows[-1]["pid"] = 1
    rows[-1]["timing_kind"] = "DISJOINT_CALL_SUM_WITH_TIMESTAMP_ENVELOPE"
    with pytest.raises(ValueError, match="ENVELOPES"):
        interval_union_ns(rows, {"operation_entry"})


def test_lineage_sql_snapshot_has_own_dynamic_span(tmp_path):
    import sqlite3

    import v0222_presentation_lineage_v2 as lineage

    with sqlite3.connect(tmp_path / "batch.sqlite") as db:
        db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        db.execute("CREATE TABLE episodes (stage TEXT, ordinal INTEGER)")
        db.execute("CREATE TABLE events (seq INTEGER, event TEXT)")
        db.execute("INSERT INTO meta VALUES ('stop', '1')")
    original = lineage._snapshot
    observer = CoarseObserver("synthetic", enabled=True, clock=Clock())
    with installed(observer), observer.span("execution"):
        assert lineage._snapshot(tmp_path)["meta"] == {"stop": "1"}
    assert lineage._snapshot is original
    dynamic = [row for row in observer.records if row["category"] == "dynamic_validation"]
    assert len(dynamic) == 1
    assert dynamic[0]["terminal_status"] == "RETURNED"
    assert "SQL rows (no SQL cursor substitution)" in observer.report()["unknown"]
