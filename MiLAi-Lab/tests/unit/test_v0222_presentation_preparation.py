"""Preparation control tests; real full matrix is a separately retained offline proof."""

import copy
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0220_action_adapter import public, put

import prepare_v0222_presentation as prep
import v0222_presentation_audit as audit
from v0218_world import digest
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("OFFLINE_PREPARATION_CANNOT_SEND_HTTP")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.skipif(
    not (prep.PARENT_ROOT / "manifest.json").is_file(),
    reason="external historical V0222 preparation evidence is not part of the Git checkout",
)
def test_full_original_matrix_changes_only_id_scope_and_initial_hash():
    before = read(prep.PARENT_ROOT / "manifest.json")["contract"]
    plan = prep.episode_specs()
    assert len(plan["P3"]) == 16 and len(plan["P4"]) == 24
    ids, scopes, roots = set(), set(), set()
    for stage in ("P3", "P4"):
        for old, new in zip(before[stage], plan[stage], strict=True):
            ignored = {"id", "scope", "initial_state_sha256"} if stage == "P4" else {"id", "scope"}
            assert {k: v for k, v in old.items() if k not in ignored} == {
                k: v for k, v in new.items() if k not in ignored
            }
            assert new["id"] != old["id"] and new["scope"] != old["scope"]
            if stage == "P4":
                assert digest(audit.initial_for(new)) == new["initial_state_sha256"]
                assert new["initial_state_sha256"] != old["initial_state_sha256"]
            ids.add(new["id"])
            scopes.add(new["scope"])
            roots.add(new["root"])
    assert len(ids) == len(scopes) == 40 and len(roots) == 4
    assert prep.episode_specs() == plan


@pytest.mark.parametrize("report_fails", [False, True])
def test_partial_matrix_is_failure_and_stop_precedes_failure_report(
    tmp_path, monkeypatch, report_fails
):
    cases = tmp_path / "cases"
    save(cases / "SYNTHETIC_ONLY" / "public-initial.json", public())
    monkeypatch.setattr(prep, "CASES", cases)
    monkeypatch.setattr(audit, "CASES", cases)
    spec = {
        "stage": "P3",
        "variant": "full",
        "id": "synthetic",
        "scope": "new-test-scope",
        "root": "SYNTHETIC_ONLY",
        "expected": put(),
    }
    stopped, frozen = [], []
    batch = SimpleNamespace(
        root=tmp_path / "proof",
        plan={"P3": [spec], "P4": []},
        authorize=lambda _: None,
        stop=stopped.append,
        freeze_artifact=lambda *args: frozen.append(args),
    )
    original_save = prep.save

    def checked_save(path, value):
        if path.name == "preparation-error.json":
            assert stopped == ["COMPLETE_16_PLUS_80_AND_24_CHAINS_REQUIRED"]
            if report_fails:
                raise OSError("TEST_ONLY_REPORT_FAILURE")
        original_save(path, value)

    monkeypatch.setattr(prep, "save", checked_save)
    original = copy.deepcopy(batch.plan)
    with pytest.raises(ProviderStop, match="COMPLETE_16_PLUS_80_AND_24_CHAINS_REQUIRED"):
        prep.materialize_references(batch)
    assert not frozen and batch.plan == original
    assert (batch.root / "full-reference/P3/synthetic/world.sqlite").exists()
    assert not (batch.root / "authorization.json").exists()


def test_offline_cli_cannot_create_formal_or_reused_roots(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("INVALID_ROOT_MUST_BE_REJECTED_BEFORE_LINEAGE_OR_WRITES")

    monkeypatch.setattr(prep, "verify_lineage", forbidden)
    monkeypatch.setattr(prep, "OFFLINE_PARENT", tmp_path)
    for root in (tmp_path, prep.ROOT, tmp_path.parent / "outside"):
        with pytest.raises(ProviderStop, match="FRESH_DEDICATED_OFFLINE_PROOF_ROOT_REQUIRED"):
            prep.offline_proof(root)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ProviderStop, match="FRESH_DEDICATED_OFFLINE_PROOF_ROOT_REQUIRED"):
        prep.offline_proof(existing)
