"""Fixed workflow purposes and unchanged R04 fresh-scope routes; synthetic only."""

import ast
import inspect
import sys
import textwrap
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0224_cpu_workflow_batch as old
import v0224_retained_static_batch as new


@pytest.mark.parametrize("name", [*new.INSTANCE_ORDER, new.K3_INSTANCE])
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


@pytest.mark.parametrize("name", ["", "digestv1-d1-u1", "retainv1-k3-extra"])
def test_old_or_unknown_selector_refused(name, monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", name)
    with pytest.raises(new.ProviderStop):
        new.selected_root()


def test_old_root_and_cross_purpose_root_refused(monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", new.INSTANCE_ORDER[0])
    monkeypatch.setattr(new, "make_authorization", lambda *args, **kwargs: {})
    for root in (old.CPU_BASE / "flowv1-d1-u1", new.CPU_BASE / new.K3_INSTANCE):
        with pytest.raises(new.ProviderStop):
            new.make_cpu_authorization(root, issued=1, expires=2, history={})


def test_same_scope_lineage_authority_and_all_fresh_routes():
    assert new.StaticAuthority is old.StaticAuthority
    assert new.verify_lineage_r03 is old.verify_lineage_r03

    def tree(function):
        return ast.dump(ast.parse(textwrap.dedent(inspect.getsource(function))))

    for name in (
        "authorize",
        "_operation",
        "artifact",
        "freeze_artifact",
        "finish",
        "_p3_gate",
        "_read_artifact_row",
    ):
        assert tree(getattr(new.OfflineBatch, name)) == tree(getattr(old.OfflineBatch, name)), name


def fake_batch(monkeypatch, purpose_change=None):
    monkeypatch.setenv("MILA_V0224_INSTANCE", new.INSTANCE_ORDER[0])
    monkeypatch.setattr(new, "require_cpu_network_guard", lambda: None)
    monkeypatch.setattr(new, "_guard", lambda scope: nullcontext())
    monkeypatch.setattr(new, "verify_lineage_r03", lambda scope: {"sources": []})
    monkeypatch.setattr(new, "make_authorization", lambda *args, **kwargs: {})
    batch = object.__new__(new.OfflineBatch)
    batch.root = new.selected_root()
    batch.binding_sha = "a" * 64
    batch.binding = {
        "authorization.json": "b",
        "authorization-source.json": "c",
        "manifest.json": "d",
    }
    batch._time_check = lambda auth: None
    auth = new.make_cpu_authorization(batch.root, issued=1, expires=2, history={"sources": []})
    auth.update(issued_unix=1, expires_unix=2)
    monkeypatch.setattr(new, "make_cpu_authorization", lambda *args, **kwargs: dict(auth))
    grant = new.cpu_authorization_source()
    if purpose_change:
        grant["purpose"] = purpose_change
    values = {
        "execution-binding.json": batch.binding,
        "authorization.json": auth,
        "authorization-source.json": grant,
    }
    scope = SimpleNamespace(read_json=lambda path, pin: values[path.name])
    return batch, scope


@pytest.mark.parametrize("stage", ["P3", "P4"])
def test_a1_stages_rejected_before_manifest(monkeypatch, stage):
    batch, scope = fake_batch(monkeypatch)
    monkeypatch.setattr(
        new, "verify_manifest", lambda *args: pytest.fail("manifest must not be reached")
    )
    with pytest.raises(new.ProviderStop, match="STAGE_NOT_AUTHORIZED"):
        batch._authorize(stage, scope)


def test_cross_purpose_grant_rejected(monkeypatch):
    batch, scope = fake_batch(monkeypatch, "K3_FULL_CPU_WORKFLOW")
    with pytest.raises(new.ProviderStop, match="EXPLICIT_CPU_ONLY_SOURCE_REQUIRED"):
        batch._authorize("PREP", scope)


@pytest.fixture
def managed_batch(monkeypatch, tmp_path):
    from v0224_static_bundle import BundleLimits

    events = []
    holder = SimpleNamespace()
    holder.stats = lambda *, owner: {"synthetic_holder": True}
    holder.release = lambda *, owner: events.append(("release", owner))

    def initialize(**kwargs):
        events.append(("initialize", kwargs["owner"]))
        return holder

    class Scope:
        def __enter__(self):
            events.append(("scope", None))
            return self

        def __exit__(self, *args):
            return False

        def read_json(self, *args):
            return {}

    monkeypatch.setenv("MILA_V0224_INSTANCE", new.INSTANCE_ORDER[0])
    monkeypatch.setattr(new, "require_cpu_network_guard", lambda: None)
    monkeypatch.setattr(new, "initialize_retained_authority", initialize)
    monkeypatch.setattr(new.OfflineBatch, "_new_scope", lambda self: Scope())
    monkeypatch.setattr(new.OfflineBatch, "_authorize", lambda *a: ({}, {}))
    monkeypatch.setattr(new.OfflineBatch, "_time_check", lambda *a: None)
    config = new.StaticAuthority(
        tmp_path / "bundle", "a" * 64, tmp_path / "receipt", "b" * 64,
        BundleLimits(100, 100, 100, 100),
    )
    return config, holder, events


def test_batch_initializes_once_before_admission_and_releases(managed_batch):
    config, _, events = managed_batch
    with new.OfflineBatch(new.selected_root(), "c" * 64, static_authority=config) as batch:
        batch.authorize()
        batch.authorize()
        assert events[0] == ("initialize", batch)
        assert [event for event, _ in events].count("initialize") == 1
        assert not batch._static_released
    assert events[-1] == ("release", batch)
    assert batch._static_released
    with pytest.raises(new.ProviderStop, match="ALREADY_RELEASED"):
        with batch:
            pass


def test_constructor_failure_releases_holder(managed_batch, monkeypatch):
    config, _, events = managed_batch
    primary = RuntimeError("authorization")

    def fail(*args):
        raise primary

    monkeypatch.setattr(new.OfflineBatch, "_authorize", fail)
    with pytest.raises(RuntimeError) as caught:
        new.OfflineBatch(new.selected_root(), "c" * 64, static_authority=config)
    assert caught.value is primary
    assert [event for event, _ in events] == ["initialize", "scope", "release"]


def test_body_failure_survives_release_failure(managed_batch):
    config, holder, _ = managed_batch
    primary = RuntimeError("body")

    def fail_release(**kwargs):
        raise OSError("release")

    with pytest.raises(RuntimeError) as caught:
        with new.OfflineBatch(new.selected_root(), "c" * 64, static_authority=config):
            holder.release = fail_release
            raise primary
    assert caught.value is primary
    assert any("SECONDARY_STATIC_AUTHORITY_RELEASE" in note for note in primary.__notes__)


def test_release_failure_without_primary_fails(managed_batch):
    config, holder, _ = managed_batch

    def fail_release(**kwargs):
        raise OSError("release")

    with pytest.raises(OSError, match="release"):
        with new.OfflineBatch(new.selected_root(), "c" * 64, static_authority=config):
            holder.release = fail_release
