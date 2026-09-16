"""Private inventory observation differential checks; no performance claim."""

import ast
import hashlib
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_admission_read_scope as reads
import v0222_scoped_evidence as evidence
import v0223_inventory_breakdown as breakdown
import v0223_tree_readonly_candidate as candidate
from v0223_coarse_observation import CoarseObserver


def write(path, raw):
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def exercise(path, digest, enabled, *, limit=None):
    observer = CoarseObserver("synthetic", enabled=enabled)
    scope = reads.AdmissionReadScope()
    result = None
    old_limit = sys.getrecursionlimit()
    try:
        with candidate.installed_candidate(), breakdown.installed_inventory_breakdown(observer):
            if limit is not None:
                sys.setrecursionlimit(limit)
            try:
                with observer.span("inventory", operation_id="runtime-one"):
                    with scope:
                        evidence.verify_tree(scope, path, digest)
            except BaseException as exc:
                result = (type(exc), str(exc), type(exc.__context__), scope.failure is exc)
    finally:
        sys.setrecursionlimit(old_limit)
    return result, scope.stats, scope.status, observer


@pytest.mark.parametrize(
    "raw",
    [
        b'{"files":{},"unused":{"x":1,"x":2}}',
        b'{"unused":NaN}',
        b'{"unused":Infinity}',
        b'{"unused":1e999}',
        b'{"unused":"\xff"}',
        b'{"unused":[1,]}',
        b'{"files":{},"unused":[1,true,null,{"x":"text"}]}',
    ],
)
def test_strict_parse_outcome_and_scope_counters_match(tmp_path, raw):
    path = tmp_path / "tree.json"
    digest = write(path, raw)
    plain = exercise(path, digest, False)
    observed = exercise(path, digest, True)
    assert observed[:3] == plain[:3]
    report = breakdown.inventory_breakdown_report(observed[3])
    assert report["status"] == "COMPLETE_AGGREGATES"
    parse = next(row for row in observed[3].records if row["category"] == "private_json_parse")
    assert parse["attempted_count"] == 1
    assert parse["completed_count"] == int(observed[0] is None)
    assert parse["failed_count"] == int(observed[0] is not None)


@pytest.mark.parametrize(
    "depth,limit", [(61, 180), (64, 180), (65, 180), (120, 300), (480, None), (600, None)]
)
def test_recursion_fallback_same_outcome_and_context(tmp_path, depth, limit):
    path = tmp_path / "tree.json"
    digest = write(path, b'{"unused":' + b"[" * depth + b"0" + b"]" * depth + b"}")
    assert (
        exercise(path, digest, True, limit=limit)[:3]
        == exercise(path, digest, False, limit=limit)[:3]
    )


def test_traversal_algorithm_outside_parsed_is_identical():
    old = ast.parse(inspect.getsource(candidate.verify_tree))
    new = ast.parse(inspect.getsource(breakdown.verify_tree))
    for tree in (old, new):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "parsed":
                node.body = [ast.Pass()]
    assert ast.dump(old) == ast.dump(new)


def test_u_no_patch_no_clock_and_s_alias_restore(monkeypatch):
    def forbidden():
        raise AssertionError("U clock")

    observer = CoarseObserver("U", enabled=False, clock=forbidden)
    alias = ModuleType("v0223_breakdown_alias_test")
    monkeypatch.setitem(sys.modules, alias.__name__, alias)
    with candidate.installed_candidate():
        original = evidence.verify_tree
        alias.tree = original
        with breakdown.installed_inventory_breakdown(observer):
            assert evidence.verify_tree is original
            assert alias.tree is original
        assert breakdown.inventory_breakdown_report(observer)["status"] == "DISABLED"
        observed = CoarseObserver("S", enabled=True)
        with pytest.raises(ValueError, match="body"):
            with breakdown.installed_inventory_breakdown(observed):
                assert alias.tree is evidence.verify_tree
                assert evidence.verify_tree is not original
                alias.new_tree = evidence.verify_tree
                raise ValueError("body")
        assert evidence.verify_tree is original
        assert alias.tree is alias.new_tree is original


def test_install_order_nested_refusal():
    observer = CoarseObserver("S", enabled=True)
    with pytest.raises(RuntimeError, match="CANDIDATE_FIRST"):
        with breakdown.installed_inventory_breakdown(observer):
            pass
    with candidate.installed_candidate(), breakdown.installed_inventory_breakdown(observer):
        with pytest.raises(RuntimeError, match="REENTRY"):
            with breakdown.installed_inventory_breakdown(observer):
                pass


def test_aggregate_accounting_scope_ownership_and_no_per_file_rows(tmp_path):
    child = tmp_path / "child.json"
    child_sha = write(child, b'{"unused":[]}')
    root = tmp_path / "root.json"
    digest = write(root, json.dumps({"files": {str(child): child_sha}}).encode())
    result, stats, _, observer = exercise(root, digest, True)
    assert result is None
    rows = observer.records
    parent = next(row for row in rows if row["category"] == "inventory")
    phases = [row for row in rows if row["category"] in breakdown.PHASES]
    assert len(phases) == 3
    assert all(row["count"] == 2 for row in phases)
    assert all(row["scope_id"] == 1 and row["operation_id"] == "runtime-one" for row in phases)
    assert all(row["parent_span_id"] == parent["span_id"] for row in phases)
    assert all(row["timing_kind"] == "DISJOINT_CALL_SUM_WITH_TIMESTAMP_ENVELOPE" for row in phases)
    assert parent["inclusive_wall_ns"] == parent["exclusive_wall_ns"] + sum(
        row["exclusive_wall_ns"] for row in phases
    )
    assert stats["first_reads"] == stats["closing_reads"] == 2
    assert sum(row["json_docs"] for row in phases) == stats["json_parses"] == 2
    assert str(tmp_path) not in repr(rows)


@pytest.mark.parametrize("fail_call", [1, 2])
def test_primary_failure_survives_private_timer_failure(tmp_path, fail_call):
    path = tmp_path / "tree.json"
    digest = write(path, b'{"unused":NaN}')
    observer = CoarseObserver("S", enabled=True)
    scope = reads.AdmissionReadScope()
    with candidate.installed_candidate(), breakdown.installed_inventory_breakdown(observer):
        with observer.span("inventory"):
            original_clock = observer.clock
            calls = 0

            def broken_clock():
                nonlocal calls
                calls += 1
                if calls == fail_call:
                    raise RuntimeError("timer unavailable")
                return original_clock()

            observer.clock = broken_clock
            try:
                with pytest.raises(
                    reads.AdmissionReadError, match="NONFINITE_JSON_NUMBER"
                ) as caught:
                    with scope:
                        evidence.verify_tree(scope, path, digest)
                assert scope.failure is caught.value
            finally:
                observer.clock = original_clock
    assert breakdown.inventory_breakdown_report(observer)["status"] == "INVALID_OBSERVATION"


def test_missing_first_edge_still_precedes_later_invalid_digest(tmp_path):
    root = tmp_path / "tree.json"
    raw = json.dumps(
        {"files": {str(tmp_path / "missing"): "a" * 64, str(tmp_path / "later"): []}}
    ).encode()
    digest = write(root, raw)
    observed = exercise(root, digest, True)
    assert observed[:3] == exercise(root, digest, False)[:3]
    assert observed[0][0] is FileNotFoundError


@pytest.mark.parametrize("limit,depth", [(180, 20), (180, 65), (180, 110), (300, 110), (300, 180)])
def test_low_recursion_budget_through_c_callbacks(tmp_path, limit, depth):
    path = tmp_path / "tree.json"
    digest = write(path, b'{"unused":' + b"[" * depth + b"0" + b"]" * depth + b"}")
    previous = sys.getrecursionlimit()

    def through_c(level, enabled):
        if level == 0:
            return exercise(path, digest, enabled)
        box = []
        sorted([0], key=lambda _: box.append(through_c(level - 1, enabled)) or 0)
        return box[0]

    try:
        sys.setrecursionlimit(limit)
        plain = through_c(8, False)
        observed = through_c(8, True)
    finally:
        sys.setrecursionlimit(previous)
    assert observed[:3] == plain[:3]
