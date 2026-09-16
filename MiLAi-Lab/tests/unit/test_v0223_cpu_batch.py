"""Prospective root binding only; no real-scale admission or timing claim."""

import ast
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_scoped_cpu_batch as old
import v0223_cpu_batch as new
from v0220_provider_hardened import ProviderStop


@pytest.mark.parametrize("name", ["", "../20260912-cold-r1", "k1-u4", "k3-cold/.."])
def test_unfrozen_root_selection_rejected(monkeypatch, name):
    monkeypatch.setenv("MILA_V0223_INSTANCE", name)
    with pytest.raises(ProviderStop, match="FROZEN_V0223_INSTANCE"):
        new.selected_root()


def test_root_change_never_reuses_old_grant(monkeypatch):
    monkeypatch.setenv("MILA_V0223_INSTANCE", "k1-u1")
    history = {"sources": [], "unresolved_reservations": [{"unknown": True}]}
    root = new.selected_root()
    actual = new.make_cpu_authorization(root, issued=100, expires=200, history=history)
    previous = old.make_cpu_authorization(old.CPU_ROOT, issued=100, expires=200, history=history)
    changed = {key for key in actual.keys() | previous.keys() if actual[key] != previous[key]}
    assert changed == {"root", "batch_id", "coordinator_revision"}
    assert actual["accepted_unknown"] == history["unresolved_reservations"]
    assert actual["real_http_allowed"] is False
    with pytest.raises(ProviderStop, match="CANONICAL_CPU"):
        new.make_cpu_authorization(old.CPU_ROOT, issued=100, expires=200, history=history)
    monkeypatch.setenv("MILA_V0223_INSTANCE", "k1-s1")
    with pytest.raises(ProviderStop, match="CANONICAL_CPU"):
        new.make_cpu_authorization(root, issued=100, expires=200, history=history)


def test_constructor_and_authorize_ast_only_change_root_selector():
    old_tree = ast.parse(inspect.getsource(old.OfflineBatch))
    new_tree = ast.parse(inspect.getsource(new.OfflineBatch))

    class Normalize(ast.NodeTransformer):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "selected_root":
                assert not node.args and not node.keywords
                return ast.Name(id="CPU_ROOT", ctx=ast.Load())
            return self.generic_visit(node)

    assert ast.dump(old_tree) == ast.dump(Normalize().visit(new_tree))


def test_all_dynamic_methods_are_identical_inherited_functions():
    own = {name for name, value in vars(new.OfflineBatch).items() if inspect.isfunction(value)}
    assert own == {"__init__", "_authorize"}
    for name in dir(old.OfflineBatch):
        if name not in own and inspect.isfunction(getattr(old.OfflineBatch, name)):
            assert getattr(new.OfflineBatch, name) is getattr(old.OfflineBatch, name)
