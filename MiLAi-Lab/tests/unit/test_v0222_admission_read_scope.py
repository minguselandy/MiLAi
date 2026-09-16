"""Small synthetic local files only; no Batch, HTTP, corpus or performance test."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_admission_read_scope as module
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope


def sample(tmp_path, data=b'{"items":[{"value":1}],"flag":false}', name="sample.json"):
    path = tmp_path / name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def test_dedup_is_one_first_hash_and_one_fresh_closing_hash(tmp_path, monkeypatch):
    path, digest = sample(tmp_path)
    hashes = []
    original = module.hashlib.sha256

    def counted(data):
        hashes.append(data)
        return original(data)

    monkeypatch.setattr(module.hashlib, "sha256", counted)
    with AdmissionReadScope() as scope:
        raw = scope.read_bytes(path, digest)
        first = scope.read_json(path, digest)
        assert first == scope.read_json(path.parent / "." / path.name, digest)
        assert raw == scope.read_bytes(path, digest)
        assert len(hashes) == 1
        assert scope.stats["repeat_references"] == 3
        assert scope.stats["json_parses"] == 1
    assert hashes == [raw, raw]
    assert scope.stats == {
        "first_read_attempts": 1,
        "first_reads": 1,
        "first_hashes": 1,
        "first_bytes": len(raw),
        "json_parses": 1,
        "repeat_references": 3,
        "closing_read_attempts": 1,
        "closing_reads": 1,
        "closing_hashes": 1,
        "closing_bytes": len(raw),
    }
    assert scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"


@pytest.mark.parametrize("data", [b'{"x":[1]}', b'[1,{"x":[2]}]', b"null", b"false", b"42"])
def test_returned_json_and_stats_cannot_contaminate_cache(tmp_path, data):
    path, digest = sample(tmp_path, data)
    with AdmissionReadScope() as scope:
        value = scope.read_json(path, digest)
        if isinstance(value, dict):
            value["x"].append("poison")
        elif isinstance(value, list):
            value[1]["x"].append("poison")
        scope.stats["first_reads"] = 999
        assert scope.read_json(path, digest) == json.loads(data)
        assert scope.stats["first_reads"] == scope.stats["json_parses"] == 1


@pytest.mark.parametrize(
    "change", ["write", "restored_mtime", "replace", "replace_identical", "delete"]
)
def test_close_rejects_content_replacement_and_deletion(tmp_path, change):
    path, digest = sample(tmp_path, b'{"x":1}')
    scope = AdmissionReadScope()
    scope.read_json(path, digest)
    old = path.stat()
    if change == "delete":
        path.unlink()
    elif change.startswith("replace"):
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(b'{"x":1}' if change == "replace_identical" else b'{"x":2}')
        os.replace(replacement, path)
    else:
        path.write_bytes(b'{"x":2}')
        if change == "restored_mtime":
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    with pytest.raises((AdmissionReadError, FileNotFoundError)):
        scope.close()
    assert scope.status == "CLOSED_FAILED" and scope.close_failures
    assert scope.stats["closing_read_attempts"] == 1
    if change != "delete":
        assert scope.stats["closing_hashes"] == 1


def test_new_scope_rehashes_same_size_rewrite_even_restored_mtime(tmp_path):
    path, digest = sample(tmp_path, b'{"x":1}')
    with AdmissionReadScope() as first:
        first.read_json(path, digest)
    old = path.stat()
    path.write_bytes(b'{"x":2}')
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    second = AdmissionReadScope()
    with pytest.raises(AdmissionReadError, match="INITIAL_CONTENT_HASH") as error:
        second.read_json(path, digest)
    with pytest.raises(AdmissionReadError) as closing:
        second.close()
    assert closing.value is error.value
    assert second.stats["first_hashes"] == second.stats["closing_hashes"] == 1
    with AdmissionReadScope() as third:
        assert third.read_json(path, hashlib.sha256(path.read_bytes()).hexdigest()) == {"x": 2}
    assert third.stats["first_reads"] == 1


def test_conflicting_hash_poison_cannot_be_caught_into_success(tmp_path):
    path, digest = sample(tmp_path)
    scope = AdmissionReadScope()
    scope.read_bytes(path, digest)
    with pytest.raises(AdmissionReadError, match="CONFLICTING") as first:
        scope.read_bytes(path, "0" * 64)
    assert scope.status == "POISONED"
    with pytest.raises(AdmissionReadError, match="POISONED"):
        scope.read_bytes(path, digest)
    with pytest.raises(AdmissionReadError) as closing:
        scope.close()
    assert closing.value is first.value
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 1


@pytest.mark.parametrize(
    "data",
    [
        b'{"x":1,"x":2}',
        b'{"x": {"a":1,"a":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e9999}',
        b'{"x":-1e9999}',
        b"not-json",
        b'{"x":"\xff"}',
    ],
)
def test_strict_json_failure_is_permanent_for_scope(tmp_path, data):
    path, digest = sample(tmp_path, data)
    scope = AdmissionReadScope()
    with pytest.raises((ValueError, UnicodeError)) as first:
        scope.read_json(path, digest)
    with pytest.raises(AdmissionReadError, match="POISONED"):
        scope.read_bytes(path, digest)
    with pytest.raises((ValueError, UnicodeError)) as closing:
        scope.close()
    assert closing.value is first.value and scope.failure is first.value
    assert scope.stats["json_parses"] == 1
    assert scope.stats["first_hashes"] == scope.stats["closing_hashes"] == 1


@pytest.mark.parametrize("digest", [None, True, "", "a" * 63, "A" * 64, "z" * 64])
def test_invalid_expected_hash_poison(tmp_path, digest):
    path, _ = sample(tmp_path)
    scope = AdmissionReadScope()
    with pytest.raises(AdmissionReadError, match="SHA256") as first:
        scope.read_bytes(path, digest)
    with pytest.raises(AdmissionReadError) as closing:
        scope.close()
    assert closing.value is first.value and scope.stats["first_reads"] == 0


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "directory", "fifo"])
def test_only_nonaliased_regular_files(tmp_path, kind):
    path, digest = sample(tmp_path)
    if kind == "file_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(path)
        path = alias
    elif kind == "parent_symlink":
        alias = tmp_path / "aliasdir"
        alias.symlink_to(tmp_path, target_is_directory=True)
        path = alias / path.name
    elif kind == "directory":
        path = tmp_path
    else:
        path = tmp_path / "fifo"
        os.mkfifo(path)
    scope = AdmissionReadScope()
    with pytest.raises(AdmissionReadError):
        scope.read_bytes(path, digest)
    with pytest.raises(AdmissionReadError):
        scope.close()
    assert scope.status == "CLOSED_FAILED"


@pytest.mark.parametrize("method", ["read_bytes", "read_json", "close", "__enter__"])
def test_closed_scope_cannot_be_used_again(tmp_path, method):
    path, digest = sample(tmp_path)
    with AdmissionReadScope() as scope:
        scope.read_bytes(path, digest)
    with pytest.raises(AdmissionReadError, match="ALREADY_CLOSED"):
        getattr(scope, method)(path, digest) if method.startswith("read") else getattr(
            scope, method
        )()
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 1


def test_body_exception_preserved_and_all_closing_failures_attached(tmp_path):
    one, digest_one = sample(tmp_path, b"one", "one")
    two, digest_two = sample(tmp_path, b"two", "two")
    original = RuntimeError("original consumer failure")
    with pytest.raises(RuntimeError) as raised:
        with AdmissionReadScope() as scope:
            scope.read_bytes(one, digest_one)
            scope.read_bytes(two, digest_two)
            one.unlink()
            two.write_bytes(b"bad")
            raise original
    assert raised.value is original
    assert len(original.__notes__) == len(scope.close_failures) == 2
    assert scope.stats["closing_read_attempts"] == 2
    assert scope.stats["closing_hashes"] == 1 and scope.status == "CLOSED_FAILED"


def test_caught_parse_exception_and_closing_failure_preserve_original(tmp_path):
    path, digest = sample(tmp_path, b'{"x":NaN}')
    with pytest.raises(AdmissionReadError, match="NONFINITE") as raised:
        with AdmissionReadScope() as scope:
            try:
                scope.read_json(path, digest)
            except AdmissionReadError as exc:
                original = exc
            path.unlink()
    assert raised.value is original and "FileNotFoundError" in original.__notes__[0]


def test_json_is_parsed_from_verified_bytes_not_a_second_file_read(tmp_path):
    path, digest = sample(tmp_path, b'{"x":1}')
    scope = AdmissionReadScope()
    scope.read_bytes(path, digest)
    path.write_bytes(b'{"x":2}')
    assert scope.read_json(path, digest) == {"x": 1}
    assert scope.stats["first_reads"] == scope.stats["json_parses"] == 1
    with pytest.raises(AdmissionReadError, match="CLOSING"):
        scope.close()


def test_mutation_during_first_observation_poisoned(tmp_path, monkeypatch):
    path, digest = sample(tmp_path, b'{"x":1}')
    original_read = module.os.read
    modified = False

    def changing(fd, size):
        nonlocal modified
        result = original_read(fd, size)
        if not modified and result and os.fstat(fd).st_ino == path.stat().st_ino:
            modified = True
            before = path.stat()
            path.write_bytes(b'{"x":2}')
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return result

    monkeypatch.setattr(module.os, "read", changing)
    scope = AdmissionReadScope()
    with pytest.raises(AdmissionReadError, match="DURING_OBSERVATION") as first:
        scope.read_json(path, digest)
    with pytest.raises(AdmissionReadError) as closing:
        scope.close()
    assert closing.value is first.value and scope.status == "CLOSED_FAILED"


def test_reentrant_context_poisoned(tmp_path):
    path, digest = sample(tmp_path)
    with pytest.raises(AdmissionReadError, match="REENTERED"):
        with AdmissionReadScope() as scope:
            scope.read_bytes(path, digest)
            with pytest.raises(AdmissionReadError, match="REENTERED"):
                scope.__enter__()
    assert scope.status == "CLOSED_FAILED"


@pytest.mark.parametrize("kind", ["symlink", "missing", "ordinary_directory"])
def test_parent_traversal_rejected_before_normalization_or_content_read(tmp_path, kind):
    requested = tmp_path / "requested"
    requested.mkdir()
    path, digest = sample(requested, b"requested object", "file")
    segment = requested / "segment"
    if kind == "symlink":
        other = tmp_path / "other"
        (other / "child").mkdir(parents=True)
        sample(other, b"different object", "file")
        segment.symlink_to(other / "child", target_is_directory=True)
    elif kind == "ordinary_directory":
        segment.mkdir()
    supplied = segment / ".." / path.name
    scope = AdmissionReadScope()
    with pytest.raises(AdmissionReadError, match="PARENT_TRAVERSAL") as first:
        scope.read_bytes(supplied, digest)
    assert scope.status == "POISONED"
    with pytest.raises(AdmissionReadError, match="POISONED"):
        scope.read_bytes(path, digest)
    with pytest.raises(AdmissionReadError) as closing:
        scope.close()
    assert closing.value is first.value and scope.status == "CLOSED_FAILED"
    assert all(value == 0 for value in scope.stats.values())


@pytest.mark.parametrize("origin", ["body", "parse"])
def test_falsey_exception_never_reports_success(tmp_path, monkeypatch, origin):
    class FalseError(RuntimeError):
        def __bool__(self):
            return False

    original = FalseError("original falsey failure")
    path, digest = sample(tmp_path)
    with pytest.raises(FalseError) as raised:
        with AdmissionReadScope() as scope:
            scope.read_bytes(path, digest)
            if origin == "body":
                raise original

            def broken_parse(*args, **kwargs):
                raise original

            monkeypatch.setattr(module.json, "loads", broken_parse)
            with pytest.raises(FalseError) as parsed:
                scope.read_json(path, digest)
            assert parsed.value is original
            assert scope.failure is original and scope.status == "POISONED"
    assert raised.value is original
    assert scope.failure is original and scope.status == "CLOSED_FAILED"
    assert scope.stats["closing_hashes"] == 1
