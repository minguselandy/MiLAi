"""Synthetic routing and source equivalence, never a real R03 fixture."""

import ast
import copy
import inspect
import sys
import textwrap
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0224_bundle_cpu_batch as batch
from v0222_presentation_batch_v2 import Batch as Core
from v0222_presentation_finish_v2 import Batch as Finish
from v0222_presentation_gates_v2 import Batch as Gates
from v0224_bundle_read_scope import BundleReadScope
from v0224_static_bundle import BundleLimits


def authority(tmp_path):
    return batch.StaticAuthority(
        tmp_path / "bundle",
        "a" * 64,
        tmp_path / "receipt",
        "b" * 64,
        BundleLimits(10000, 10000, 100, 100),
    )


@pytest.mark.parametrize(
    "owner,name",
    [
        (Core, "authorize"),
        (Core, "_operation"),
        (Gates, "artifact"),
        (Gates, "freeze_artifact"),
        (Finish, "finish"),
        (Finish, "_p3_gate"),
    ],
)
def test_fresh_scope_entry_copies_only_change_factory(owner, name):
    original = ast.parse(textwrap.dedent(inspect.getsource(getattr(owner, name))))
    revised = ast.parse(textwrap.dedent(inspect.getsource(getattr(batch.OfflineBatch, name))))

    class Replace(ast.NodeTransformer):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "AdmissionReadScope":
                node.func = ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()), attr="_new_scope", ctx=ast.Load()
                )
            return self.generic_visit(node)

    assert ast.dump(Replace().visit(original), include_attributes=False) == ast.dump(
        revised, include_attributes=False
    )


def test_all_inherited_scope_creation_sites_are_overridden():
    sites = set()
    for owner in batch.OfflineBatch.__mro__[1:]:
        for name, value in vars(owner).items():
            if inspect.isfunction(value):
                parsed = ast.parse(textwrap.dedent(inspect.getsource(value)))
                if any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "AdmissionReadScope"
                    for n in ast.walk(parsed)
                ):
                    sites.add(name)
    assert sites == {
        "__init__",
        "authorize",
        "_operation",
        "artifact",
        "freeze_artifact",
        "finish",
        "_p3_gate",
    }
    assert sites <= set(vars(batch.OfflineBatch))


def test_external_authority_is_immutable_and_factory_is_fresh(tmp_path):
    value = authority(tmp_path)
    obj = object.__new__(batch.OfflineBatch)
    obj._static_authority = value
    first, second = obj._new_scope(), obj._new_scope()
    assert (
        type(first) is BundleReadScope and type(second) is BundleReadScope and first is not second
    )
    with pytest.raises(FrozenInstanceError):
        value.bundle_sha256 = "0" * 64
    contract = value.contract_value()
    contract["limits"]["max_paths"] = 1
    assert value.limits.max_paths == 100
    assert value.contract_value()["bundle_sha256"] == "a" * 64
    with pytest.raises(ValueError):
        batch.StaticAuthority(
            tmp_path / "bundle", "not-pin", tmp_path / "receipt", "b" * 64, value.limits
        )
    with pytest.raises(batch.ProviderStop, match="IMMUTABLE_BUNDLE_LIMITS"):
        batch.StaticAuthority(tmp_path / "bundle", "a" * 64, tmp_path / "receipt", "b" * 64, {})


def test_fixed_selector_and_guard_before_constructor_io(monkeypatch, tmp_path):
    monkeypatch.setenv("MILA_V0224_INSTANCE", "bundle-v1-slice")
    assert batch.selected_root() == batch.CPU_BASE / "bundle-v1-slice"
    monkeypatch.setenv("MILA_V0224_INSTANCE", "arbitrary")
    with pytest.raises(Exception, match="INSTANCE"):
        batch.selected_root()

    def refused():
        raise RuntimeError("guard first")

    monkeypatch.setattr(batch, "require_cpu_network_guard", refused)
    with pytest.raises(RuntimeError, match="guard first"):
        batch.OfflineBatch(tmp_path, "c" * 64, static_authority=authority(tmp_path))


def test_artifact_row_delegates_unchanged_inside_physical_context(monkeypatch):
    events = []

    class Scope:
        @contextmanager
        def physical_reads(self):
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

    scope = Scope()
    row, db, expected = object(), object(), object()

    def original(self, passed_db, passed_row, passed_scope):
        assert (passed_db, passed_row, passed_scope) == (db, row, scope)
        events.append("original")
        return expected

    monkeypatch.setattr(Core, "_read_artifact_row", original)
    obj = object.__new__(batch.OfflineBatch)
    assert obj._read_artifact_row(db, row, scope) is expected
    assert events == ["enter", "original", "exit"]


def test_manifest_authority_binding_refuses_changed_external_hash(monkeypatch, tmp_path):
    obj = object.__new__(batch.OfflineBatch)
    obj.root = tmp_path
    obj.binding_sha = "c" * 64
    obj._static_authority = authority(tmp_path)
    binding = {
        name: (str(i) * 64)
        for i, name in enumerate(
            ["authorization.json", "authorization-source.json", "manifest.json"], 1
        )
    }
    obj.binding = binding
    auth = {"issued_unix": 1, "expires_unix": 2, "stages": ["PREP"]}
    history = {"sources": []}
    plan = {
        "static_authority": obj._static_authority.contract_value(),
        "revision": batch.REVISION,
        "coordinator_revision": batch.CPU_REVISION,
        "execution_mode": batch.CPU_MODE,
        "real_http_allowed": False,
        "device_calls_allowed": False,
        "mock_cost_is_not_real_cost": True,
        "selected_decoder": "D11",
        "selected_presentation": "B1",
        "parent_root": str(batch.PARENT_ROOT),
        "parent_binding": batch.PARENT_BINDING,
        "boundary_root": str(batch.BOUNDARY_ROOT),
        "boundary_binding": batch.BOUNDARY_BINDING,
        "presentation_root": str(batch.PRESENTATION_ROOT),
        "presentation_binding": batch.PRESENTATION_BINDING,
        "historical_paths": [],
        "http_identity": batch.IDENTITY,
    }
    monkeypatch.setattr(batch, "require_cpu_network_guard", lambda: None)
    monkeypatch.setattr(batch, "verify_lineage_r03", lambda scope: history)
    monkeypatch.setattr(batch, "make_cpu_authorization", lambda *a, **k: auth)
    monkeypatch.setattr(batch, "verify_manifest", lambda *a: {"contract": copy.deepcopy(plan)})
    monkeypatch.setattr(obj, "_time_check", lambda a: None)
    monkeypatch.setattr(obj, "_validate_plan", lambda *a: None)

    class Scope(BundleReadScope):
        def read_json(self, path, digest):
            return copy.deepcopy(
                {
                    "execution-binding.json": binding,
                    "authorization.json": auth,
                    "authorization-source.json": batch.cpu_authorization_source(),
                }[path.name]
            )

    scope = Scope(**obj._static_authority.scope_arguments())
    assert obj._authorize("PREP", scope)[1] == plan
    plan["static_authority"]["bundle_sha256"] = "0" * 64
    with pytest.raises(Exception, match="FROZEN_SCOPED_CPU_CONTRACT"):
        obj._authorize("PREP", scope)
    assert scope.failure is not None


def test_constructor_and_authorize_close_before_final_time_check(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(batch, "selected_root", lambda: tmp_path)
    monkeypatch.setattr(batch, "require_cpu_network_guard", lambda: None)

    class Scope:
        def __enter__(self):
            events.append("scope_enter")
            return self

        def __exit__(self, *args):
            events.append("scope_close")

        def read_json(self, *args):
            events.append("binding")
            return {}

    # Construct authority before replacing the scope factory used for route testing.
    config = authority(tmp_path)
    monkeypatch.setattr(batch, "BundleReadScope", lambda **kwargs: Scope())
    monkeypatch.setattr(batch.OfflineBatch, "_authorize", lambda *args: ({}, {}))
    monkeypatch.setattr(batch.OfflineBatch, "_time_check", lambda *args: events.append("time"))
    obj = batch.OfflineBatch(tmp_path, "a" * 64, static_authority=config)
    assert events == ["scope_enter", "binding", "scope_close", "time"]
    events.clear()
    assert obj.authorize() == {}
    assert events == ["scope_enter", "scope_close", "time"]


def test_operation_body_failure_closes_then_stops_preserving_primary(monkeypatch):
    obj = object.__new__(batch.OfflineBatch)
    events = []
    primary = RuntimeError("body-primary")

    @contextmanager
    def transaction():
        events.append("transaction_enter")
        try:
            yield object()
        finally:
            events.append("transaction_exit")

    @contextmanager
    def scope():
        events.append("scope_enter")
        try:
            yield object()
        finally:
            events.append("scope_exit")

    monkeypatch.setattr(obj, "transaction", transaction)
    monkeypatch.setattr(obj, "_new_scope", scope)
    monkeypatch.setattr(obj, "_authorize", lambda *a: ({}, {}))
    monkeypatch.setattr(obj, "_check_journal", lambda *a, **k: {})

    def stop(reason):
        events.append("stop")
        raise RuntimeError("secondary-stop")

    monkeypatch.setattr(obj, "stop", stop)
    generator = obj._operation("PREP")
    assert events == []
    with pytest.raises(RuntimeError) as caught:
        with generator:
            events.append("body")
            raise primary
    assert caught.value is primary
    assert events == [
        "transaction_enter",
        "scope_enter",
        "body",
        "scope_exit",
        "transaction_exit",
        "stop",
    ]
    assert primary.__notes__ == ["SECONDARY_STOP_FAILURE: RuntimeError"]


def test_authority_validation_creates_no_scope(monkeypatch, tmp_path):
    def forbidden(**kwargs):
        raise AssertionError("configuration must not create scope")

    monkeypatch.setattr(batch, "BundleReadScope", forbidden)
    value = authority(tmp_path)
    assert value.bundle_path == tmp_path / "bundle"
    with pytest.raises(batch.ProviderStop, match="DISTINCT_EXTERNAL_AUTHORITY"):
        batch.StaticAuthority(
            tmp_path / "same", "a" * 64, tmp_path / "same", "b" * 64, value.limits
        )
