"""Real scoped control/manifest/plan checks over synthetic frozen artifacts.

Only historical lineage is replaced with a pinned synthetic inventory reader;
the independent lineage test suite covers its four SQL snapshots. These tests
do not claim an actual new frozen instance or full end-to-end Batch admission.
"""

import copy
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_batch_v2 as module
import v0222_presentation_lineage_v2 as lineage
import v0222_scoped_evidence as evidence
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def control(tmp_path, monkeypatch):
    root, parent, previous = (tmp_path / name for name in ("new", "parent", "previous"))
    lab = tmp_path / "lab"
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "PARENT_ROOT", parent)
    monkeypatch.setattr(module, "PRESENTATION_ROOT", previous)
    monkeypatch.setattr(evidence, "LAB", lab)
    inputs, old_plans = {}, []
    for prefix, old_root in (("original", parent), ("previous", previous)):
        plan = {
            stage: [
                {
                    "id": f"{prefix}-{stage}-{i}",
                    "scope": f"{prefix}-scope-{stage}-{i}",
                    "stage": stage,
                    "public_source": f"synthetic-{i}",
                    **(
                        {
                            "initial_state_sha256": hashlib.sha256(
                                f"{prefix}-{i}".encode()
                            ).hexdigest(),
                            "actions": [{"synthetic": i}],
                        }
                        if stage == "P4"
                        else {"kind": "full" if i % 2 == 0 else "finish"}
                    ),
                }
                for i in range(16 if stage == "P3" else 24)
            ]
            for stage in ("P3", "P4")
        }
        old_plans.append(plan)
        manifest = old_root / "manifest.json"
        manifest_sha = put(manifest, {"contract": plan})
        binding = old_root / "execution-binding.json"
        binding_sha = put(binding, {"manifest.json": manifest_sha})
        inputs.update({str(manifest): manifest_sha, str(binding): binding_sha})
    history = {
        "sources": [{"path": str(tmp_path / "synthetic-legacy"), "sha256": "a" * 64}],
        "unresolved_reservations": [{"test_only_unknown": True}],
    }
    inventory_path = tmp_path / "inventory.json"
    inventory = {"files": inputs, "synthetic_history": history}
    inventory_sha = put(inventory_path, inventory)
    monkeypatch.setattr(module, "INVENTORY_PATH", inventory_path)
    monkeypatch.setattr(module, "INVENTORY_SHA256", inventory_sha)
    inputs = {**inputs, str(inventory_path): inventory_sha}
    calls = []

    def verify(scope):
        item = scope.read_json(inventory_path, inventory_sha)
        for path, digest in item["files"].items():
            scope.read_bytes(path, digest)
        calls.append(scope)
        return item["synthetic_history"]

    monkeypatch.setattr(lineage, "verify_lineage", verify)
    plan = copy.deepcopy(old_plans[-1])
    for stage in plan:
        for i, spec in enumerate(plan[stage]):
            spec.update(id=f"new-{stage}-{i}", scope=f"new-scope-{stage}-{i}")
            if stage == "P4":
                spec["initial_state_sha256"] = hashlib.sha256(f"new-{i}".encode()).hexdigest()
    plan.update(
        {
            "revision": module.REVISION,
            "coordinator_revision": module.COORDINATOR_REVISION,
            "selected_decoder": "D11",
            "selected_presentation": "B1",
            "parent_root": str(parent),
            "parent_binding": module.PARENT_BINDING,
            "boundary_root": str(module.BOUNDARY_ROOT),
            "boundary_binding": module.BOUNDARY_BINDING,
            "presentation_root": str(previous),
            "presentation_binding": module.PRESENTATION_BINDING,
            "historical_paths": [s["path"] for s in history["sources"]],
            "http_identity": module.IDENTITY,
        }
    )
    source = lab / "tools/synthetic.py"
    source_sha = put(source, b"value = 1\n")
    copied = root / "executed-source/tools/synthetic.py"
    put(copied, source.read_bytes())
    manifest = {
        "contract": plan,
        "dependencies": {str(source): source_sha},
        "inputs": inputs,
        "python": platform.python_version(),
        "packages": {},
    }
    now = time.time()
    auth = module.make_authorization(root, issued=now - 1, expires=now + 3600, history=history)
    grant = module.authorization_source()

    def seal():
        binding = {
            "manifest.json": put(root / "manifest.json", manifest),
            "authorization.json": put(root / "authorization.json", auth),
            "authorization-source.json": put(root / "authorization-source.json", grant),
        }
        return put(root / "execution-binding.json", binding)

    digest = seal()
    return {
        "root": root,
        "digest": digest,
        "manifest": manifest,
        "plan": plan,
        "auth": auth,
        "grant": grant,
        "source": source,
        "copied": copied,
        "calls": calls,
        "seal": seal,
        "old_plans": old_plans,
    }


def test_constructor_actual_control_plan_manifest_checks(control):
    batch = module.Batch(control["root"], control["digest"])
    assert batch.auth == control["auth"] and batch.plan == control["plan"]
    assert len(control["calls"]) == 1
    scope = control["calls"][0]
    assert scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] > 8
    assert not batch.path.exists()  # No coordinator or real grant is created by construction.
    auth = batch.authorize("P3")
    auth["historical"]["sources"].clear()
    assert batch.authorize("P3") == control["auth"]
    assert len({id(s) for s in control["calls"]}) == 3


@pytest.mark.parametrize(
    "change",
    [
        "matrix",
        "order",
        "source",
        "action",
        "old_scope",
        "duplicate_id",
        "duplicate_scope",
        "initial_hash",
        "revision",
    ],
)
def test_fixed_complete_matrix_not_silently_narrowed(control, change):
    plan = control["plan"]
    if change == "matrix":
        plan["P3"].pop()
    elif change == "order":
        plan["P3"][0], plan["P3"][1] = plan["P3"][1], plan["P3"][0]
    elif change == "source":
        plan["P3"][0]["public_source"] = "changed"
    elif change == "action":
        plan["P4"][0]["actions"] = []
    elif change == "old_scope":
        plan["P3"][0]["scope"] = control["old_plans"][0]["P3"][0]["scope"]
    elif change == "duplicate_id":
        plan["P4"][0]["id"] = plan["P3"][0]["id"]
    elif change == "duplicate_scope":
        plan["P4"][0]["scope"] = plan["P3"][0]["scope"]
    elif change == "initial_hash":
        plan["P4"][0]["initial_state_sha256"] = control["old_plans"][0]["P4"][0][
            "initial_state_sha256"
        ]
    else:
        plan["coordinator_revision"] = "old"
    digest = control["seal"]()
    with pytest.raises(ProviderStop):
        module.Batch(control["root"], digest)


@pytest.mark.parametrize(
    "change", ["source", "copy", "input", "python", "auth", "grant", "binding"]
)
def test_frozen_control_drift(control, change):
    digest = control["digest"]
    if change in {"source", "copy"}:
        put(control["source" if change == "source" else "copied"], b"changed")
    elif change == "input":
        put(Path(next(iter(control["manifest"]["inputs"]))), b"changed")
    elif change == "python":
        control["manifest"]["python"] = "0.0"
        digest = control["seal"]()
    elif change == "auth":
        control["auth"]["caps"]["P3"] = 17
        digest = control["seal"]()
    elif change == "grant":
        control["grant"]["http_only"] = False
        digest = control["seal"]()
    else:
        put(control["root"] / "execution-binding.json", {})
    with pytest.raises((ProviderStop, AdmissionReadError, evidence.ScopedEvidenceError)):
        module.Batch(control["root"], digest)


@pytest.mark.parametrize("member", ["auth", "plan", "binding"])
def test_in_memory_controls_cannot_override_pins(control, member):
    batch = module.Batch(control["root"], control["digest"])
    getattr(batch, member)["extra"] = True
    with pytest.raises(ProviderStop, match="IN_MEMORY"):
        batch.authorize("P3")


def test_control_semantic_exception_poison_even_if_caught(control):
    batch = module.Batch(control["root"], control["digest"])
    with pytest.raises(ProviderStop, match="STAGE_NOT_AUTHORIZED"):
        with AdmissionReadScope() as scope:
            with pytest.raises(ProviderStop, match="STAGE_NOT_AUTHORIZED"):
                batch._authorize("E1", scope)
            assert scope.status == "POISONED"


def test_authorization_expiry_checked_after_close(control, monkeypatch):
    original = AdmissionReadScope._close

    def close(self, body_error=None):
        original(self, body_error)
        monkeypatch.setattr(module.time, "time", lambda: control["auth"]["expires_unix"])

    monkeypatch.setattr(AdmissionReadScope, "_close", close)
    with pytest.raises(ProviderStop, match="AUTHORIZATION_EXPIRED"):
        module.Batch(control["root"], control["digest"])
