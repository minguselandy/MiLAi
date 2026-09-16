"""Original/candidate differential refusals and copy isolation, no timing claim."""

import copy
import hashlib
import json
import platform
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_admission_read_scope as reads
import v0222_scoped_evidence as evidence
from v0223_tree_readonly_candidate import installed_candidate


def write(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def exercise(path, pin, *, candidate, before_close=lambda scope: None, seen=None):
    class Tracked(reads.AdmissionReadScope):
        def __init__(self):
            super().__init__()
            self.calls = []

        def _entry(self, path, digest):
            self.calls.append((str(path), copy.deepcopy(digest)))
            return super()._entry(path, digest)

    scope = Tracked()
    outcome = None
    with installed_candidate() if candidate else nullcontext():
        try:
            with scope:
                assert evidence.verify_tree(scope, path, pin, seen) is None
                before_close(scope)
        except BaseException as exc:
            outcome = (type(exc).__name__, str(exc), list(getattr(exc, "__notes__", [])))
    return {
        "outcome": outcome,
        "calls": scope.calls,
        "stats": scope.stats,
        "status": scope.status,
        "close_failure_types": [type(e).__name__ for e in scope.close_failures],
    }


def compare(path, pin, **kwargs):
    original = exercise(path, pin, candidate=False, **kwargs)
    candidate = exercise(path, pin, candidate=True, **kwargs)
    assert candidate == original
    return original


@pytest.mark.parametrize(
    "raw",
    [
        b'{"files":{},"unused":{"key":1,"key":2}}',
        b'{"files":{},"unused":[NaN]}',
        b'{"files":{},"unused":[Infinity]}',
        b'{"files":{},"unused":[1e999]}',
        b'{"files":{},"unused":"\xff"}',
        b'{"files":{},"unused":[1,]}',
    ],
)
def test_unused_body_is_still_fully_strict_parsed(tmp_path, raw):
    path = tmp_path / "tree.json"
    result = compare(path, write(path, raw))
    assert result["outcome"] is not None and result["stats"]["json_parses"] == 1
    assert result["status"] == "CLOSED_FAILED"


def test_diamond_and_multiple_field_edges_exact_order_and_counts(tmp_path):
    leaf = tmp_path / "leaf.json"
    leaf_sha = write(leaf, {"unused": [{"text": "body"}]})
    left = tmp_path / "left.json"
    left_sha = write(left, {"files": {str(leaf): leaf_sha}})
    right = tmp_path / "right.json"
    right_sha = write(right, {"inputs": {str(leaf): leaf_sha}})
    root = tmp_path / "root.json"
    digest = write(
        root,
        {
            "dependencies": {str(left): left_sha},
            "inputs": {str(right): right_sha},
            "references": [{"files": {str(leaf): leaf_sha}}],
        },
    )
    result = compare(root, digest)
    assert result["outcome"] is None
    assert result["stats"]["json_parses"] == result["stats"]["first_reads"] == 4
    assert result["stats"]["closing_reads"] == 4


def test_late_conflicting_hash_and_earlier_missing_direct_edge(tmp_path):
    leaf = tmp_path / "leaf.json"
    leaf_sha = write(leaf, {})
    root = tmp_path / "root.json"
    digest = write(
        root, {"files": {str(leaf): leaf_sha}, "entries": [{"files": {str(leaf): "0" * 64}}]}
    )
    assert "CONFLICTING_EXPECTED_FILE_HASH" in compare(root, digest)["outcome"][1]
    missing = tmp_path / "missing.json"
    digest = write(root, {"files": {str(missing): "0" * 64, str(leaf): {"malformed": [1, 2]}}})
    result = compare(root, digest)
    assert result["outcome"][0] == "FileNotFoundError"
    assert result["calls"][-1][0] == str(missing)


def test_invalid_digest_reaches_original_rejection_without_borrowing(tmp_path):
    leaf = tmp_path / "leaf.json"
    write(leaf, {})
    root = tmp_path / "root.json"
    digest = write(root, {"files": {str(leaf): {"bad": [1]}}})
    result = compare(root, digest)
    assert result["outcome"][1] == "EXACT_LOWERCASE_SHA256_REQUIRED"
    with installed_candidate():
        scope = reads.AdmissionReadScope()
        original_read = scope.read_bytes
        received = []

        def mutate_bad_digest(path, expected):
            if isinstance(expected, dict):
                expected["bad"].append(2)
                received.append(expected)
            return original_read(path, expected)

        scope.read_bytes = mutate_bad_digest
        with pytest.raises(reads.AdmissionReadError):
            evidence.verify_tree(scope, root, digest)
        assert received == [{"bad": [1, 2]}]
        assert scope._entries[root].parsed["files"][str(leaf)] == {"bad": [1]}
        with pytest.raises(reads.AdmissionReadError):
            scope.close()


@pytest.mark.parametrize("invalid", ["python", "dependency"])
def test_manifest_failure_precedes_malformed_edges(tmp_path, invalid):
    root = tmp_path / "manifest.json"
    value = {
        "dependencies": {},
        "inputs": {},
        "packages": {},
        "python": platform.python_version(),
        "hashes": [],
    }
    if invalid == "python":
        value["python"] = "0.0.0"
    else:
        value["dependencies"] = {str(tmp_path / "outside-lab.py"): "0" * 64}
    result = compare(root, write(root, value))
    assert result["outcome"] is not None
    assert "HASHES_MAPPING_REQUIRED" not in result["outcome"][1]
    assert (
        result["outcome"][1] == "PYTHON_DRIFT"
        if invalid == "python"
        else "outside-lab.py" in result["outcome"][1]
    )


def test_completed_manifest_rechecks_environment(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    pin = write(
        manifest,
        {"dependencies": {}, "inputs": {}, "packages": {}, "python": platform.python_version()},
    )
    root = tmp_path / "tree.json"
    digest = write(root, {"files": {str(manifest): pin}, "inputs": {str(manifest): pin}})
    original = evidence.verify_manifest
    outputs = []
    for candidate in (False, True):
        calls = []

        def check(scope, directory, expected, calls=calls):
            calls.append(str(directory))
            if len(calls) == 2:
                raise evidence.ScopedEvidenceError("SECOND_MANIFEST_ENVIRONMENT_DRIFT")
            return original(scope, directory, expected)

        monkeypatch.setattr(evidence, "verify_manifest", check)
        outputs.append(exercise(root, digest, candidate=candidate))
        assert len(calls) == 2
    assert outputs[0] == outputs[1]
    assert outputs[0]["outcome"][1] == "SECOND_MANIFEST_ENVIRONMENT_DRIFT"


def test_public_return_nested_mutation_isolation_and_same_scope_different_purpose(tmp_path):
    root = tmp_path / "manifest.json"
    value = {
        "dependencies": {},
        "inputs": {},
        "packages": {},
        "python": platform.python_version(),
        "unused": [{"mutable": [1, 2]}],
    }
    digest = write(root, value)
    original_reader = reads.AdmissionReadScope.read_json

    def body(scope):
        returned = scope.read_json(root, digest)
        returned["unused"][0]["mutable"].append(99)
        assert scope.read_json(root, digest) == value
        manifest = evidence.verify_manifest(scope, root.parent, digest)
        manifest["unused"].clear()
        assert scope.read_json(root, digest) == value

    assert compare(root, digest, before_close=body)["outcome"] is None
    assert reads.AdmissionReadScope.read_json is original_reader


def test_close_mutation_and_fresh_scope_same_size_drift(tmp_path):
    root = tmp_path / "tree.json"
    old = b'{"value":1}'
    new = b'{"value":2}'
    results = []
    for candidate in (False, True):
        digest = write(root, old)
        results.append(
            exercise(
                root, digest, candidate=candidate, before_close=lambda scope: root.write_bytes(new)
            )
        )
    # Runtime file identity numbers are intentionally not exposed by either API.
    assert results[0] == results[1]
    assert "CLOSING_CONTENT_OR_PATH_IDENTITY_MISMATCH" in results[0]["outcome"][1]
    assert "INITIAL_CONTENT_HASH_MISMATCH" in compare(root, digest)["outcome"][1]


def test_installer_alias_coverage_future_imports_restore_and_uncovered_entry(monkeypatch):
    selected = ModuleType("v0223_synthetic_alias")
    outside = ModuleType("unrelated_synthetic_alias")
    original = evidence.verify_tree
    selected.entry = outside.entry = original
    monkeypatch.setitem(sys.modules, selected.__name__, selected)
    monkeypatch.setitem(sys.modules, outside.__name__, outside)
    with installed_candidate():
        assert selected.entry is evidence.verify_tree and selected.entry is not original
        assert outside.entry is original  # A frozen caller outside the allowlist is not covered.
        exec(  # noqa: S102 - fixed synthetic import tests late alias restoration
            "from v0222_scoped_evidence import verify_tree as future_entry", selected.__dict__
        )
        assert selected.future_entry is evidence.verify_tree
        with pytest.raises(RuntimeError, match="NESTED"):
            with installed_candidate():
                pass
    assert (
        evidence.verify_tree is selected.entry is selected.future_entry is outside.entry is original
    )


def test_cycle_conflict_and_seen_cannot_skip_dependencies(tmp_path):
    root = tmp_path / "cycle.json"
    digest = write(root, {"files": {str(root): "0" * 64}})
    assert "CONFLICTING_EXPECTED_FILE_HASH" in compare(root, digest)["outcome"][1]
    seen = {(str(root), digest)}
    result = compare(root, digest, seen=seen)
    assert result["outcome"][1] == "TREE_SEEN_MUST_START_EMPTY"
    assert result["stats"]["first_read_attempts"] == 0
    assert seen == {(str(root), digest)}


def test_same_size_mtime_drift_and_body_error_keep_first_cause(tmp_path):
    import os

    root = tmp_path / "tree.json"
    original = b'{"value":1}'
    changed = b'{"value":2}'
    results = []
    for candidate in (False, True):
        digest = write(root, original)
        before = root.stat()

        def mutate_and_fail(scope, before=before):
            root.write_bytes(changed)
            os.utime(root, ns=(before.st_atime_ns, before.st_mtime_ns))
            raise ValueError("ORIGINAL_BODY_FAILURE")

        results.append(exercise(root, digest, candidate=candidate, before_close=mutate_and_fail))
    assert results[0] == results[1]
    assert results[0]["outcome"][:2] == ("ValueError", "ORIGINAL_BODY_FAILURE")
    assert len(results[0]["outcome"][2]) == 1
    assert "Additional closing failure" in results[0]["outcome"][2][0]


def test_only_traversal_whole_object_copy_removed_public_reader_unchanged(tmp_path, monkeypatch):
    root = tmp_path / "tree.json"
    digest = write(root, {"unused": [{"text": "body", "nested": [1, 2, 3]}]})
    original_copy = copy.deepcopy
    counts = []
    for candidate in (False, True):
        copied = []

        def observe_copy(value, *args, copied=copied, **kwargs):
            if isinstance(value, dict) and "unused" in value:
                copied.append(type(value).__name__)
            return original_copy(value, *args, **kwargs)

        monkeypatch.setattr(copy, "deepcopy", observe_copy)
        # No tracking subclass: its argument-copy logging is intentionally absent.
        with installed_candidate() if candidate else nullcontext():
            with reads.AdmissionReadScope() as scope:
                evidence.verify_tree(scope, root, digest)
                counts.append(len(copied))
                value = scope.read_json(root, digest)
                value["unused"].clear()
                assert scope.read_json(root, digest)["unused"]
                assert scope.stats["json_parses"] == 1
    assert counts[0] > 0
    assert counts[1] == 0


def test_deep_unused_json_preserves_original_recursion_failure(tmp_path):
    root = tmp_path / "deep.json"
    raw = b'{"unused":' + b"[" * 600 + b"0" + b"]" * 600 + b"}"
    result = compare(root, write(root, raw))
    assert result["outcome"][0] == "RecursionError"


@pytest.mark.parametrize("depth", [0, 1, 61, 62, 63, 64, 65, 120, 400, 480, 600])
def test_fallback_boundary_and_deep_data_differential(tmp_path, depth):
    root = tmp_path / "depth.json"
    raw = b'{"unused":' + b"[" * depth + b"0" + b"]" * depth + b"}"
    compare(root, write(root, raw))


@pytest.mark.parametrize("limit,depth", [(180, 20), (180, 65), (180, 110), (300, 110), (300, 180)])
def test_low_recursion_headroom_and_c_callback_differential(tmp_path, limit, depth):
    root = tmp_path / "low-stack.json"
    digest = write(root, b'{"unused":' + b"[" * depth + b"0" + b"]" * depth + b"}")
    previous = sys.getrecursionlimit()

    def through_c(level, candidate):
        if level == 0:
            return exercise(root, digest, candidate=candidate)
        box = []
        # sorted invokes the Python key through a C callback. Its recursion
        # budget is why Python f_back counting alone is not accepted as proof.
        sorted([0], key=lambda _: box.append(through_c(level - 1, candidate)) or 0)
        return box[0]

    try:
        sys.setrecursionlimit(limit)
        old = through_c(8, False)
        new = through_c(8, True)
    finally:
        sys.setrecursionlimit(previous)
    assert old == new


def test_fallback_recursion_error_has_no_probe_context(tmp_path):
    root = tmp_path / "context.json"
    pin = write(root, b'{"unused":' + b"[" * 600 + b"0" + b"]" * 600 + b"}")
    contexts = []
    for candidate in (False, True):
        with installed_candidate() if candidate else nullcontext():
            scope = reads.AdmissionReadScope()
            with pytest.raises(RecursionError) as caught:
                evidence.verify_tree(scope, root, pin)
            contexts.append(caught.value.__context__)
            with pytest.raises(RecursionError):
                scope.close()
    assert contexts == [None, None]
