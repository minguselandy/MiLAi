"""Synthetic scoped IO checks only: no Batch, network, corpus or scale benchmark."""

import hashlib
import json
import platform
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_scoped_evidence as module
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope
from v0222_scoped_evidence import (
    ScopedEvidenceError,
    read_artifact,
    read_pinned_events,
    verify_manifest,
    verify_tree,
)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def manifest(tmp_path, monkeypatch):
    lab = tmp_path / "lab"
    monkeypatch.setattr(module, "LAB", lab)
    root = tmp_path / "sealed"
    source = lab / "tools/example.py"
    source_hash = put(source, b"value = 1\n")
    copied = root / "executed-source/tools/example.py"
    put(copied, source.read_bytes())
    data = tmp_path / "input.json"
    data_hash = put(data, {"value": [1, 2]})
    value = {
        "dependencies": {str(source): source_hash},
        "inputs": {str(data): data_hash},
        "python": platform.python_version(),
        "packages": {"pytest": module.importlib.metadata.version("pytest")},
        "contract": {"TEST_ONLY": True},
    }
    digest = put(root / "manifest.json", value)
    return root, value, digest, source, copied, data


def assert_poisoned(scope, invoke, exception=Exception, match=None):
    with pytest.raises(exception, match=match) as first:
        invoke()
    assert scope.status == "POISONED"
    with pytest.raises(exception) as closing:
        scope.close()
    assert closing.value is first.value and scope.status == "CLOSED_FAILED"
    return first.value


def test_manifest_every_source_copy_input_and_environment(tmp_path, monkeypatch):
    root, value, digest, *_ = manifest(tmp_path, monkeypatch)
    with AdmissionReadScope() as scope:
        returned = verify_manifest(scope, root, digest)
        returned["contract"]["TEST_ONLY"] = False
        assert verify_manifest(scope, root, digest) == value
        assert scope.stats["first_reads"] == 4 and scope.stats["json_parses"] == 1
    assert scope.stats["closing_reads"] == scope.stats["closing_hashes"] == 4


@pytest.mark.parametrize(
    "drift", ["manifest", "source", "copy", "input", "python", "package", "missing_copy"]
)
def test_manifest_drift_poison(tmp_path, monkeypatch, drift):
    root, value, digest, source, copied, data = manifest(tmp_path, monkeypatch)
    if drift in {"manifest", "source", "copy", "input"}:
        target = {
            "manifest": root / "manifest.json",
            "source": source,
            "copy": copied,
            "input": data,
        }[drift]
        target.write_bytes(b"changed")
    elif drift == "missing_copy":
        copied.unlink()
    else:
        if drift == "python":
            value["python"] = "0.0"
        else:
            value["packages"]["pytest"] = "0.0"
        digest = put(root / "manifest.json", value)
    scope = AdmissionReadScope()
    assert_poisoned(scope, lambda: verify_manifest(scope, root, digest))


@pytest.mark.parametrize(
    "field,value",
    [("dependencies", []), ("inputs", None), ("packages", []), ("packages", {"pytest": 1})],
)
def test_manifest_malformed_maps_poison(tmp_path, monkeypatch, field, value):
    root, contents, _, *_ = manifest(tmp_path, monkeypatch)
    contents[field] = value
    digest = put(root / "manifest.json", contents)
    scope = AdmissionReadScope()
    assert_poisoned(scope, lambda: verify_manifest(scope, root, digest), ScopedEvidenceError)


def test_preverified_bytes_never_skip_manifest_semantics(tmp_path, monkeypatch):
    root, value, _, *_ = manifest(tmp_path, monkeypatch)
    value["python"] = "wrong"
    digest = put(root / "manifest.json", value)
    scope = AdmissionReadScope()
    scope.read_bytes(root / "manifest.json", digest)
    assert_poisoned(
        scope,
        lambda: verify_tree(scope, root / "manifest.json", digest),
        ScopedEvidenceError,
        "PYTHON",
    )


def test_repeat_tree_still_checks_environment_not_old_semantic_pass(tmp_path, monkeypatch):
    root, _, digest, *_ = manifest(tmp_path, monkeypatch)
    scope = AdmissionReadScope()
    seen = set()
    verify_tree(scope, root / "manifest.json", digest, seen)
    assert seen == set()
    monkeypatch.setattr(module.platform, "python_version", lambda: "wrong")
    assert_poisoned(
        scope,
        lambda: verify_tree(scope, root / "manifest.json", digest, seen),
        ScopedEvidenceError,
        "PYTHON",
    )


def test_tree_follows_exact_explicit_fields_and_reuses_bytes(tmp_path):
    a, b, c = (tmp_path / name for name in ("a.txt", "b.json", "c.txt"))
    ah, bh, ch = put(a, b"one"), put(b, {"business": "unchanged"}), put(c, b"three")
    ignored = str(tmp_path / "missing-gold-or-model-string")
    value = {
        "files": {str(a): ah},
        "dependencies": {str(b): bh},
        "inputs": {str(a): ah},
        "canonical": str(a),
        "hashes": {"canonical": ah, "unbound_business": "ignored"},
        "references": [{"entries": [{"files": {str(c): ch}}]}],
        "business": {"files": {ignored: "0" * 64}},
        "default": {"files": {ignored: "0" * 64}},
        "example": ignored,
    }
    path = tmp_path / "tree.json"
    digest = put(path, value)
    with AdmissionReadScope() as scope:
        verify_tree(scope, path, digest)
        verify_tree(scope, path, digest)
        assert scope.stats["first_reads"] == 4
        assert scope.stats["json_parses"] == 2
    assert scope.stats["closing_hashes"] == 4


@pytest.mark.parametrize("field", ["files", "dependencies", "inputs", "hashes"])
def test_tree_bad_mapping_poison(tmp_path, field):
    path = tmp_path / "bad.json"
    digest = put(path, {field: []})
    scope = AdmissionReadScope()
    assert_poisoned(scope, lambda: verify_tree(scope, path, digest), ScopedEvidenceError)


def test_tree_conflicting_repeated_reference_not_swallowed(tmp_path):
    leaf = tmp_path / "leaf"
    digest = put(leaf, b"known")
    path = tmp_path / "tree.json"
    expected = put(path, {"files": {str(leaf): digest}, "inputs": {str(leaf): "0" * 64}})
    scope = AdmissionReadScope()
    assert_poisoned(
        scope, lambda: verify_tree(scope, path, expected), AdmissionReadError, "CONFLICTING"
    )


def test_self_reference_cycle_rejects_hash_conflict_without_recursion(tmp_path):
    path = tmp_path / "cycle.json"
    digest = put(path, {"references": [{"files": {str(path): "0" * 64}}]})
    scope = AdmissionReadScope()
    seen = set()
    assert_poisoned(
        scope, lambda: verify_tree(scope, path, digest, seen), AdmissionReadError, "CONFLICTING"
    )
    assert seen == set()


def test_prepopulated_seen_cannot_import_old_success(tmp_path):
    path = tmp_path / "tree.json"
    digest = put(path, {"files": {str(tmp_path / "missing"): "0" * 64}})
    seen = {(str(path), digest)}
    scope = AdmissionReadScope()
    assert_poisoned(
        scope, lambda: verify_tree(scope, path, digest, seen), ScopedEvidenceError, "START_EMPTY"
    )
    assert scope.stats["first_reads"] == 0
    assert seen == {(str(path), digest)}


def test_artifact_union_need_not_have_equal_keys_and_cannot_contaminate(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    h1, h2 = put(one, b"one"), put(two, b"two")
    path = tmp_path / "artifact.json"
    digest = put(path, {"files": {str(two): h2}, "payload": {"values": [1]}})
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "select ? as path, ? as sha256, ? as dependencies",
            (str(path), digest, json.dumps({str(one): h1})),
        ).fetchone()
        with AdmissionReadScope() as scope:
            value = read_artifact(scope, row)
            value["payload"]["values"].append("poison")
            assert read_artifact(scope, row)["payload"]["values"] == [1]
            assert scope.stats["first_reads"] == 3 and scope.stats["json_parses"] == 1
        assert scope.stats["closing_hashes"] == 3


@pytest.mark.parametrize(
    "kind",
    [
        "sql_missing",
        "file_missing",
        "conflict",
        "duplicate_sql",
        "nonfinite_sql",
        "missing_row",
        "sql_badmap",
        "file_badmap",
    ],
)
def test_artifact_complete_union_and_strict_sql_dependencies(tmp_path, kind):
    leaf = tmp_path / "leaf"
    leaf_hash = put(leaf, b"leaf")
    files = {str(leaf): leaf_hash}
    deps = {str(leaf): leaf_hash}
    if kind == "sql_missing":
        deps[str(tmp_path / "missing")] = "0" * 64
    elif kind == "file_missing":
        files[str(tmp_path / "missing")] = "0" * 64
    elif kind == "conflict":
        deps[str(leaf)] = "0" * 64
    elif kind == "sql_badmap":
        deps = []
    elif kind == "file_badmap":
        files = []
    path = tmp_path / "artifact.json"
    digest = put(path, {"files": files})
    encoded_deps = json.dumps(deps)
    if kind == "duplicate_sql":
        encoded_deps = '{"x":1,"x":2}'
    elif kind == "nonfinite_sql":
        encoded_deps = '{"x":NaN}'
    row = {"path": str(path), "sha256": digest, "dependencies": encoded_deps}
    scope = AdmissionReadScope()
    assert_poisoned(scope, lambda: read_artifact(scope, None if kind == "missing_row" else row))


@pytest.mark.parametrize("data", [b"", b'{"event":"A"}\n{"event":"B","x":1.5}\n'])
def test_pinned_jsonl_bytes_shared_but_return_values_independent(tmp_path, data):
    path = tmp_path / "history.jsonl"
    digest = put(path, data)
    with AdmissionReadScope() as scope:
        first = read_pinned_events(scope, path, digest)
        first.append({"poison": True})
        second = read_pinned_events(scope, path, digest)
        assert second == [json.loads(line) for line in data.splitlines()]
        assert scope.stats["first_reads"] == 1 and scope.stats["json_parses"] == 0
    assert scope.stats["closing_hashes"] == 1


@pytest.mark.parametrize(
    "data",
    [
        b"\n",
        b"{}\n\n{}",
        b"[]",
        b"null",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e9999}',
        b'{"x":"\xff"}',
        b"{broken",
    ],
)
def test_invalid_jsonl_poison(tmp_path, data):
    path = tmp_path / "history.jsonl"
    digest = put(path, data)
    scope = AdmissionReadScope()
    assert_poisoned(scope, lambda: read_pinned_events(scope, path, digest))


@pytest.mark.parametrize("entry", ["manifest", "tree", "artifact", "events"])
@pytest.mark.parametrize("state", ["closed", "poisoned"])
def test_every_public_entry_rejects_unusable_scope_before_semantics(
    tmp_path, monkeypatch, entry, state
):
    root, _, digest, *_ = manifest(tmp_path, monkeypatch)
    scope = AdmissionReadScope()
    if state == "closed":
        scope.close()
    else:
        with pytest.raises(AdmissionReadError):
            scope.read_bytes(root / "manifest.json", "invalid")
    invoke = {
        "manifest": lambda: verify_manifest(scope, root, digest),
        "tree": lambda: verify_tree(scope, root / "manifest.json", digest),
        "artifact": lambda: read_artifact(scope, None),
        "events": lambda: read_pinned_events(scope, root / "manifest.json", digest),
    }[entry]
    with pytest.raises(AdmissionReadError, match=r"ALREADY_CLOSED|POISONED"):
        invoke()
    assert scope.stats["first_reads"] == 0


def test_falsey_semantic_error_and_later_body_error_priority(tmp_path, monkeypatch):
    class FalseError(RuntimeError):
        def __bool__(self):
            return False

    root, _, digest, *_ = manifest(tmp_path, monkeypatch)
    original = FalseError("semantic failure")

    def broken_version():
        raise original

    monkeypatch.setattr(module.platform, "python_version", broken_version)
    scope = AdmissionReadScope()
    assert (
        assert_poisoned(scope, lambda: verify_manifest(scope, root, digest), FalseError) is original
    )
    body_error = RuntimeError("subsequent body failure")
    with pytest.raises(RuntimeError) as raised:
        with AdmissionReadScope() as scope:
            with pytest.raises(FalseError):
                verify_manifest(scope, root, digest)
            raise body_error
    assert raised.value is body_error and scope.failure is original
    assert "Earlier scope failure" in body_error.__notes__[0]


def test_semantic_error_kept_when_closing_dependency_disappears(tmp_path, monkeypatch):
    root, value, _, _, _, data = manifest(tmp_path, monkeypatch)
    value["python"] = "wrong"
    digest = put(root / "manifest.json", value)
    with pytest.raises(ScopedEvidenceError, match="PYTHON") as raised:
        with AdmissionReadScope() as scope:
            with pytest.raises(ScopedEvidenceError) as first:
                verify_manifest(scope, root, digest)
            data.unlink()
    assert raised.value is first.value
    assert any("FileNotFoundError" in note for note in raised.value.__notes__)


@pytest.mark.parametrize("prepopulated", [False, True])
def test_tree_grandchild_cannot_be_hidden_by_prepopulated_seen(tmp_path, prepopulated):
    child, root = tmp_path / "child.json", tmp_path / "root.json"
    child_hash = put(child, {"files": {str(tmp_path / "missing-grandchild"): "0" * 64}})
    root_hash = put(root, {"files": {str(child): child_hash}})
    seen = {(str(root), root_hash)} if prepopulated else set()
    scope = AdmissionReadScope()
    expected = ScopedEvidenceError if prepopulated else FileNotFoundError
    assert_poisoned(scope, lambda: verify_tree(scope, root, root_hash, seen), expected)
    if prepopulated:
        assert scope.stats["first_reads"] == 0
    else:
        assert scope.stats["first_reads"] == 2 and seen == set()


@pytest.mark.parametrize("files", ["absent", "empty", "nonempty"])
def test_artifact_empty_sql_and_explicit_files_match_frozen_reader(tmp_path, files):
    # Explicit acceptance/rejection comparison on tiny temporary files only.
    # No Batch constructor, authorization, transaction or historical check runs.
    from v0220_provider_hardened import ProviderStop
    from v0222_boundary_batch import Batch as FrozenArtifacts

    leaf = tmp_path / "leaf"
    leaf_hash = put(leaf, b"leaf")
    value = {"status": "TEST_ONLY"}
    if files != "absent":
        value["files"] = {} if files == "empty" else {str(leaf): leaf_hash}
    path = tmp_path / "artifact.json"
    row = {"path": str(path), "sha256": put(path, value), "dependencies": "{}"}
    scope = AdmissionReadScope()
    if files == "empty":
        with pytest.raises(ProviderStop):
            FrozenArtifacts._artifact(None, row)
        assert_poisoned(scope, lambda: read_artifact(scope, row), ScopedEvidenceError, "NONEMPTY")
    else:
        assert FrozenArtifacts._artifact(None, row) == read_artifact(scope, row) == value
        scope.close()


def test_empty_set_subclass_cannot_forge_completed_membership(tmp_path):
    class ForgedSeen(set):
        def __contains__(self, item):
            return True

    child, root = tmp_path / "child.json", tmp_path / "root.json"
    child_hash = put(child, {"files": {str(tmp_path / "missing-grandchild"): "0" * 64}})
    root_hash = put(root, {"files": {str(child): child_hash}})
    scope = AdmissionReadScope()
    assert_poisoned(
        scope,
        lambda: verify_tree(scope, root, root_hash, ForgedSeen()),
        ScopedEvidenceError,
        "START_EMPTY",
    )
    assert scope.stats["first_reads"] == 0


def diamond(tmp_path, *, missing=False):
    paths = [tmp_path / f"node-{i:02d}.json" for i in range(11)]
    value = {"files": {str(tmp_path / "missing"): "0" * 64}} if missing else {}
    digest = put(paths[-1], value)
    for index in reversed(range(10)):
        child = str(paths[index + 1])
        digest = put(paths[index], {"files": {child: digest}, "inputs": {child: digest}})
    return paths[0], digest


def test_eleven_node_multifield_diamond_has_linear_reference_work(tmp_path):
    root, digest = diamond(tmp_path)
    with AdmissionReadScope() as scope:
        verify_tree(scope, root, digest)
        assert scope.stats["first_reads"] == 11
        assert scope.stats["json_parses"] == 11
        assert scope.stats["repeat_references"] <= 5 * 11
        before = scope.stats["repeat_references"]
        # A second public operation has private fresh completed state, even
        # inside this same bytes-observation scope. It traverses the tree again.
        verify_tree(scope, root, digest)
        assert 11 <= scope.stats["repeat_references"] - before <= 5 * 11
    assert scope.stats["closing_hashes"] == 11


def test_diamond_missing_grandchild_never_completes_failed_tree(tmp_path):
    root, digest = diamond(tmp_path, missing=True)
    scope = AdmissionReadScope()
    with pytest.raises(FileNotFoundError) as failed:
        verify_tree(scope, root, digest)
    assert scope.status == "POISONED"
    with pytest.raises(AdmissionReadError, match="POISONED"):
        verify_tree(scope, root, digest)
    with pytest.raises(FileNotFoundError) as closed:
        scope.close()
    assert closed.value is failed.value
    # New calls/scopes cannot inherit a partial success or failed-node marker.
    other = AdmissionReadScope()
    assert_poisoned(other, lambda: verify_tree(other, root, digest), FileNotFoundError)
    assert other.stats["first_reads"] == scope.stats["first_reads"] == 11


def test_completed_shared_node_still_checks_later_conflicting_hash(tmp_path):
    shared, good, bad, root = (
        tmp_path / name
        for name in (
            "shared.json",
            "good.json",
            "bad.json",
            "root.json",
        )
    )
    shared_hash = put(shared, {})
    good_hash = put(good, {"files": {str(shared): shared_hash}})
    bad_hash = put(bad, {"files": {str(shared): "0" * 64}})
    root_hash = put(root, {"files": {str(good): good_hash, str(bad): bad_hash}})
    scope = AdmissionReadScope()
    assert_poisoned(
        scope, lambda: verify_tree(scope, root, root_hash), AdmissionReadError, "CONFLICTING"
    )
    assert scope.stats["json_parses"] == 4


def test_completed_manifest_rechecks_environment_on_each_encounter(tmp_path, monkeypatch):
    sealed, _, manifest_hash, *_ = manifest(tmp_path, monkeypatch)
    path = sealed / "manifest.json"
    root = tmp_path / "root.json"
    root_hash = put(
        root, {"files": {str(path): manifest_hash}, "inputs": {str(path): manifest_hash}}
    )
    original = module.platform.python_version
    calls = []

    def changing_version():
        calls.append(True)
        return original() if len(calls) == 1 else "changed"

    monkeypatch.setattr(module.platform, "python_version", changing_version)
    scope = AdmissionReadScope()
    assert_poisoned(
        scope, lambda: verify_tree(scope, root, root_hash), ScopedEvidenceError, "PYTHON_DRIFT"
    )
    assert len(calls) == 2


def test_new_scope_after_completed_tree_rereads_changed_child(tmp_path):
    child, root = tmp_path / "child.json", tmp_path / "root.json"
    child_hash = put(child, {"x": 1})
    root_hash = put(root, {"files": {str(child): child_hash}})
    with AdmissionReadScope() as scope:
        verify_tree(scope, root, root_hash)
    put(child, {"x": 2})
    other = AdmissionReadScope()
    assert_poisoned(
        other, lambda: verify_tree(other, root, root_hash), AdmissionReadError, "INITIAL_CONTENT"
    )
    assert other.stats["first_reads"] == 2
