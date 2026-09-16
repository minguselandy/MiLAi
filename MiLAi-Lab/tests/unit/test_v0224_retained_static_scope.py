"""Real tiny bundle/scope observations; no real authority, workload, SQL or network."""

import hashlib
import inspect
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_v0224_bundle_read_scope import encoded, fixture, sha

import v0224_retained_static_scope as module
from v0224_retained_static_scope import RetainedStaticReadScope, initialize_retained_authority


def setup(tmp_path, **options):
    config, leaf, raw, root, root_raw = fixture(tmp_path, **options)
    owner = object()
    holder = initialize_retained_authority(owner=owner, **config)
    return config, owner, holder, leaf, raw, root, root_raw


def opened(config, owner, holder):
    return RetainedStaticReadScope(owner=owner, retained_authority=holder, **config)


def test_initial_full_hashes_then_only_two_live_files_and_no_blob_reparse(tmp_path, monkeypatch):
    config, leaf, raw, _root, root_raw = fixture(tmp_path)
    bundle = config["bundle_path"].read_bytes()
    counts = []
    original_hash = hashlib.sha256

    def record(data=b"", *args, **kwargs):
        counts.append(bytes(data))
        return original_hash(data, *args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", record)
    owner = object()
    holder = initialize_retained_authority(owner=owner, **config)
    assert counts.count(bundle) == 2
    assert raw in counts and root_raw in counts
    stats = holder.stats(owner=owner)
    assert stats["initialization_physical_stats"]["first_reads"] == 3
    assert stats["initialization_physical_stats"]["closing_reads"] == 3
    counts.clear()
    raw_pin = original_hash(raw).hexdigest()
    for _ in range(2):
        with opened(config, owner, holder) as scope:
            with scope.physical_reads():
                assert scope.read_bytes(config["bundle_path"], config["bundle_sha256"]) == bundle
            scope.read_bytes(leaf, raw_pin)
        assert config["bundle_path"] not in scope._entries
        assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 2
    assert bundle not in counts and raw not in counts and root_raw not in counts
    assert holder.stats(owner=owner)["scope_uses"] == 2
    assert holder.stats(owner=owner)["retained_bundle_reads"] == 2


@pytest.mark.parametrize("change", ["replace", "delete", "alias"])
def test_lost_package_path_freshness_is_intentional(tmp_path, change):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    original = config["bundle_path"].read_bytes()
    if change == "replace":
        config["bundle_path"].write_bytes(b"new unrelated bytes")
    elif change == "delete":
        config["bundle_path"].unlink()
    else:
        other = tmp_path / "other"
        other.write_bytes(b"not authority")
        config["bundle_path"].unlink()
        config["bundle_path"].symlink_to(other)
    with opened(config, owner, holder) as scope:
        assert scope.read_bytes(config["bundle_path"], config["bundle_sha256"]) == original
        assert scope.read_json(leaf, sha(raw)) == {"value": [1, 2]}


def test_scopes_never_share_mutable_json_or_live_entries(tmp_path):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    with opened(config, owner, holder) as first:
        value = first.read_json(leaf, sha(raw))
        value["value"].append(9)
        assert first.read_json(leaf, sha(raw)) == {"value": [1, 2]}
    with opened(config, owner, holder) as second:
        assert second.read_json(leaf, sha(raw)) == {"value": [1, 2]}
        assert second.stats["json_parses"] == 1
    stats = holder.stats(owner=owner)
    stats["initialization_physical_stats"]["first_reads"] = 999
    assert holder.stats(owner=owner)["initialization_physical_stats"]["first_reads"] != 999
    assert not hasattr(holder, "raw") and not hasattr(holder, "index")


@pytest.mark.parametrize("target", ["receipt_path", "verifier", "public"])
def test_every_live_role_remains_fresh_after_initialization(tmp_path, target):
    config, owner, holder, leaf, raw, root, root_raw = setup(tmp_path, fresh=True)
    path = (
        config["receipt_path"]
        if target == "receipt_path"
        else tmp_path / "synthetic-verifier.txt"
        if target == "verifier"
        else leaf
    )
    path.write_bytes(b"drift")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with opened(config, owner, holder) as scope:
            scope.verify_static_tree(root, sha(root_raw))
            scope.read_bytes(leaf, sha(raw))


def test_missing_live_role_close_still_fails(tmp_path):
    config, owner, holder, _, _, root, root_raw = setup(tmp_path, fresh=True)
    with pytest.raises(ValueError, match="FRESH_ROLE_COVERAGE_INCOMPLETE"):
        with opened(config, owner, holder) as scope:
            scope.verify_static_tree(root, sha(root_raw))


def test_dynamic_physical_promotion_remains_per_scope(tmp_path):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    with opened(config, owner, holder) as scope:
        scope.read_bytes(leaf, sha(raw))
        with scope.physical_reads():
            scope.read_bytes(leaf, sha(raw))
        assert leaf in scope._entries
        assert scope.authority_stats["promotions"] == 1
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 3
    with opened(config, owner, holder) as scope:
        scope.read_bytes(leaf, sha(raw))
        assert leaf not in scope._entries


def test_primary_survives_live_close_drift(tmp_path):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    primary = RuntimeError("original body")
    with pytest.raises(RuntimeError) as caught:
        with opened(config, owner, holder) as scope:
            scope.read_bytes(leaf, sha(raw))
            (tmp_path / "synthetic-verifier.txt").write_bytes(b"late drift")
            raise primary
    assert caught.value is primary
    assert any("closing" in note for note in primary.__notes__)


def test_initial_close_failure_cannot_publish(tmp_path, monkeypatch):
    config, *_ = fixture(tmp_path)
    old = module.OriginalScope._close

    def drift(scope, body_error=None):
        config["bundle_path"].write_bytes(b"late drift")
        return old(scope, body_error)

    monkeypatch.setattr(module.OriginalScope, "_close", drift)
    with pytest.raises(ValueError, match="CLOSING_CONTENT"):
        initialize_retained_authority(owner=object(), **config)


def test_factory_bundle_fresh_role_conflict(tmp_path):
    config, *_ = fixture(tmp_path)
    receipt = json.loads(config["receipt_path"].read_bytes())
    receipt["fresh_roles"][str(config["bundle_path"])] = {
        "sha256": config["bundle_sha256"],
        "roles": ["LIVE"],
    }
    receipt["classification_digest"] = sha(encoded(receipt["fresh_roles"]))
    config["receipt_path"].write_bytes(encoded(receipt))
    config["receipt_sha256"] = sha(config["receipt_path"].read_bytes())
    with pytest.raises(ValueError, match="STATIC_AUTHORITY_FRESH_ROLE_CONFLICT"):
        initialize_retained_authority(owner=object(), **config)


def test_runtime_bundle_fresh_role_conflict_even_if_injected_parser_value(tmp_path, monkeypatch):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    old = module._strict_json

    def inject(value):
        parsed = old(value)
        parsed["fresh_roles"][str(config["bundle_path"])] = {
            "sha256": config["bundle_sha256"],
            "roles": ["LIVE"],
        }
        return parsed

    monkeypatch.setattr(module, "_strict_json", inject)
    with pytest.raises(ValueError, match="STATIC_AUTHORITY_FRESH_ROLE_CONFLICT"):
        with opened(config, owner, holder) as scope:
            scope.read_bytes(leaf, sha(raw))


def test_owner_config_release_and_closed_scope(tmp_path):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="OWNER_DRIFT"):
        opened(config, object(), holder)
    bad = {**config, "bundle_sha256": "0" * 64}
    with pytest.raises(ValueError, match="CONFIG_DRIFT"):
        opened(bad, owner, holder)
    with opened(config, owner, holder) as scope:
        scope.read_bytes(leaf, sha(raw))
    with pytest.raises(ValueError, match="ALREADY_CLOSED"):
        scope.read_bytes(leaf, sha(raw))
    holder.release(owner=owner)
    holder.release(owner=owner)
    assert holder.stats(owner=owner)["released"] is True
    assert holder._raw is holder._index is None
    with pytest.raises(ValueError, match="RELEASED"):
        opened(config, owner, holder)


def test_release_mid_scope_fails_but_closes_live_files(tmp_path):
    config, owner, holder, leaf, raw, _, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="RELEASED"):
        with opened(config, owner, holder) as scope:
            scope.read_bytes(leaf, sha(raw))
            holder.release(owner=owner)
    assert scope.stats["closing_reads"] == 2


def test_foreign_thread_and_fork_owner_rejected(tmp_path, monkeypatch):
    config, owner, holder, _, _, _, _ = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match="OWNER_DRIFT"):
            pool.submit(opened, config, owner, holder).result()
    original_pid = os.getpid()
    monkeypatch.setattr(module.os, "getpid", lambda: original_pid + 1)
    with pytest.raises(ValueError, match="OWNER_DRIFT"):
        opened(config, owner, holder)


def test_no_public_raw_digest_mint_or_forged_holder(tmp_path):
    config, *_ = fixture(tmp_path)
    assert "raw" not in inspect.signature(initialize_retained_authority).parameters
    with pytest.raises(ValueError, match="EXACT_FACTORY"):
        opened(config, object(), object())


def test_environment_checked_every_proof_after_initialization(tmp_path, monkeypatch):
    config, owner, holder, _, _, root, root_raw = setup(tmp_path)
    monkeypatch.setattr(module.platform, "python_version", lambda: "drift")
    with pytest.raises(ValueError, match="PYTHON_DRIFT"):
        with opened(config, owner, holder) as scope:
            scope.verify_static_tree(root, sha(root_raw))


def test_fixed_bundle_expected_conflict_is_not_blessed(tmp_path):
    config, owner, holder, *_ = setup(tmp_path)
    with pytest.raises(ValueError, match="CONFLICTING_EXPECTED_FILE_HASH"):
        with opened(config, owner, holder) as scope:
            scope.read_bytes(config["bundle_path"], "0" * 64)


def test_unentered_scope_rejects_before_physical_io(tmp_path):
    config, owner, holder, leaf, raw, *_ = setup(tmp_path)
    scope = opened(config, owner, holder)
    with pytest.raises(ValueError, match="ENTERED_RETAINED_SCOPE_REQUIRED"):
        scope.read_bytes(leaf, sha(raw))
    assert scope.stats["first_reads"] == 0
    with pytest.raises(ValueError):
        scope.__enter__()


def test_buffer_identity_tamper_rejects_before_scope_use(tmp_path):
    config, owner, holder, *_ = setup(tmp_path)
    holder._raw = bytes(bytearray(holder._raw))
    with pytest.raises(ValueError, match="BUFFER_IDENTITY_DRIFT"):
        opened(config, owner, holder)


def test_unknown_current_data_is_never_retained(tmp_path):
    config, owner, holder, *_ = setup(tmp_path)
    current = tmp_path / "current-world.json"
    raw = b'{"value":1}'
    current.write_bytes(raw)
    with opened(config, owner, holder) as scope:
        assert scope.read_json(current, sha(raw)) == {"value": 1}
    current.write_bytes(b'{"value":2}')
    with pytest.raises(ValueError, match="HASH"):
        with opened(config, owner, holder) as scope:
            scope.read_json(current, sha(raw))


def test_original_dynamic_delegates_have_identical_ast():
    import ast
    import textwrap

    for name in ("physical_reads", "verify_static_tree"):
        original = ast.parse(
            textwrap.dedent(inspect.getsource(getattr(module.OriginalScope, name)))
        )
        retained = ast.parse(
            textwrap.dedent(inspect.getsource(getattr(RetainedStaticReadScope, name)))
        )
        assert ast.dump(original) == ast.dump(retained)
