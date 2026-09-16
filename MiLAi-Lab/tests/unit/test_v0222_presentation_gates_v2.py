"""Synthetic scoped gates: real SQL/scope, explicit fake static authorization.

Mocked validator tests exercise orchestration, not independent source approval.
Additional real validator checks use only newly generated synthetic public data.
No HTTP, GPU, real authorization instance, or existing evidence is modified.
"""

import copy
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_presentation_batch_v2 import put
from test_v0222_presentation_batch_v2 import setup as core_setup

import v0222_presentation_audit as audit
import v0222_presentation_gates_v2 as module
from v0213_provider import MODEL, TOKENIZE_KEYS, payload
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadScope


@pytest.fixture
def setup(tmp_path, monkeypatch):
    batch, clock, pid, scopes, anchor = core_setup.__wrapped__(tmp_path, monkeypatch)
    batch.__class__ = module.Batch  # Test-only extension of the real synthetic core instance.
    with batch.transaction() as db:
        db.execute("DELETE FROM artifacts")
    return batch, clock, pid, scopes, anchor


def candidate(setup, name="scope_review", **extra):
    batch, _, _, _, anchor = setup
    required = install_review_prerequisites(batch, anchor) if name == "scope_review" else {}
    value = {
        "status": "G_AUTH_SCOPE_REVIEW_PASS",
        "root": str(batch.root),
        "binding_sha256": batch.binding_sha,
        "review_is_not_user_consent": True,
        "files": {str(anchor): put(anchor, {"synthetic": True}), **required},
        **extra,
    }
    path = batch.root / (name + ".json")
    put(path, value)
    return path, value


def rows(batch):
    """New registrations, excluding explicitly seeded synthetic prerequisites only."""
    with batch.transaction() as db:
        return [
            dict(row)
            for row in db.execute("SELECT * FROM artifacts ORDER BY name")
            if row["name"] not in getattr(batch, "_test_prerequisite_names", set())
        ]


def install_review_prerequisites(batch, anchor):
    """Synthetic setup only, NOT preparation/source proof or actual authorization.

    Reusable by new orchestration fixtures that subclass GatesBatch. Returns all
    required review pins. Does not register scope_review, launch, or send HTTP.
    """
    if hasattr(batch, "_test_review_pins"):
        return copy.deepcopy(batch._test_review_pins)
    binding = {}
    for name in ("authorization.json", "authorization-source.json", "manifest.json"):
        binding[name] = put(batch.root / name, {"TEST_ONLY_CONTROL": name})
    batch.binding = binding
    binding_sha = put(batch.root / "execution-binding.json", binding)
    put(batch.root / "coordinator-created.json", {"binding_sha256": binding_sha})
    files = {str(batch.root / "execution-binding.json"): binding_sha}
    files.update({str(batch.root / name): digest for name, digest in binding.items()})
    with batch.transaction() as db:
        db.execute("UPDATE meta SET value=? WHERE key='binding'", (binding_sha,))
        batch.binding_sha = binding_sha
        for name in module.SCOPE_PREREQUISITES:
            path = batch.root / (name + ".json")
            dependencies = {str(anchor): audit.sha(anchor)}
            status = (
                "ENGINEERING_CHECKS_PASS"
                if name == "engineering_checks"
                else "REFERENCE_PREPARATION_PASS"
                if name == "P_full_preparation"
                else "TEST_ONLY_SYNTHETIC_PREPARATION"
            )
            value = {"status": status, "files": dependencies, "references": []}
            digest = put(path, value)
            sql_only = batch.root / (name + "-scope-sql-only.json")
            sql_pins = {str(sql_only): put(sql_only, {"TEST_ONLY_SQL_DEP": name})}
            db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)",
                (name, str(path), digest, json.dumps(sql_pins)),
            )
            files.update({str(path): digest, **dependencies, **sql_pins})
    batch._test_prerequisite_names = set(module.SCOPE_PREREQUISITES)
    batch._test_review_pins = files
    return copy.deepcopy(files)


def test_freeze_read_and_defensive_return_complete_scope(setup):
    batch, _, _, scopes, _ = setup
    path, value = candidate(setup)
    batch.freeze_artifact("scope_review", path)
    assert len(rows(batch)) == 1
    actual = batch.artifact("scope_review")
    assert actual == value
    actual["files"].clear()
    assert batch.artifact("scope_review") == value
    assert len({id(scope) for scope in scopes}) == len(scopes)
    assert all(scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS" for scope in scopes)


@pytest.mark.parametrize(
    "name", ["P3_gate", "p3-01_audit", "p3-01_observation", "unknown", "P4_gate"]
)
def test_external_gate_or_episode_audit_cannot_be_forged(setup, name):
    batch = setup[0]
    path, _ = candidate(setup, name, status="G_P3_PASS")
    with pytest.raises(ProviderStop, match="ONLY_PUBLIC"):
        batch.freeze_artifact(name, path)
    assert not rows(batch) and batch.snapshot()["stop"]


def test_duplicate_freeze_preserves_original_registration(setup):
    batch = setup[0]
    path, _ = candidate(setup)
    batch.freeze_artifact("scope_review", path)
    before = rows(batch)
    with pytest.raises(ProviderStop, match="ALREADY_FROZEN"):
        batch.freeze_artifact("scope_review", path)
    assert rows(batch) == before


@pytest.mark.parametrize("target", ["candidate", "dependency", "database", "wal", "shm"])
def test_dynamic_ledgers_cannot_receive_a_minted_artifact_pin(setup, monkeypatch, target):
    batch = setup[0]
    ledger = batch._ledger("P3-00")
    path, value = candidate(setup)
    if target == "candidate":
        ledger.write_bytes(b"")
        path = ledger
    else:
        live = {
            "dependency": ledger,
            "database": batch.path,
            "wal": Path(str(batch.path) + "-wal"),
            "shm": Path(str(batch.path) + "-shm"),
        }[target]
        value["files"][str(live)] = "0" * 64
        put(path, value)
    hashes = []
    original = module.hashlib.sha256

    def counted(raw):
        hashes.append(raw)
        return original(raw)

    monkeypatch.setattr(module.hashlib, "sha256", counted)
    with pytest.raises(ProviderStop):
        batch.freeze_artifact("scope_review", path)
    assert not rows(batch)
    # Whole-candidate hashes occur only after the explicit live-path checks.
    assert path.read_bytes() not in hashes


def test_sql_and_file_dependency_union_is_not_forced_equal(setup):
    batch = setup[0]
    path, _ = candidate(setup)
    batch.freeze_artifact("scope_review", path)
    extra = batch.root / "extra.json"
    digest = put(extra, {"also": "required"})
    with batch.transaction() as db:
        db.execute("UPDATE artifacts SET dependencies=?", (json.dumps({str(extra): digest}),))
    assert batch.artifact("scope_review")["files"]
    extra.write_text("changed")
    with pytest.raises(Exception, match="HASH_MISMATCH"):
        batch.artifact("scope_review")


@pytest.mark.parametrize(
    "change", ["sql", "stop", "source", "candidate", "clock", "marker", "plan"]
)
def test_audit_window_mutation_cannot_register(setup, monkeypatch, change):
    batch, clock, _, _, anchor = setup
    path, _ = candidate(setup)
    original = batch._validate_candidate

    def validate(name, value, facade):
        original(name, value, facade)
        if change == "sql":
            with batch.transaction() as db:
                db.execute("INSERT INTO meta VALUES ('unexpected','mutation')")
        elif change == "stop":
            batch.stop("MID_AUDIT_STOP")
        elif change == "source":
            anchor.write_text("changed")
        elif change == "candidate":
            path.write_text("changed")
        elif change == "clock":
            clock[0] = batch.auth["expires_unix"]
        elif change == "marker":
            put(batch.root / "coordinator-created.json", {"binding_sha256": "changed"})
        else:
            batch.plan["P3"][0]["extra"] = "changed"

    monkeypatch.setattr(batch, "_validate_candidate", validate)
    with pytest.raises((ProviderStop, ValueError)):
        batch.freeze_artifact("scope_review", path)
    assert not rows(batch)
    assert batch.snapshot()["stop"]


def test_auditor_runs_without_sql_connection_and_close_precedes_final(setup, monkeypatch):
    batch, _, _, scopes, _ = setup
    path, _ = candidate(setup)
    connections = []
    baseline = batch._gate_baseline

    @contextmanager
    def tracked_baseline(scope):
        with baseline(scope) as result:
            connections.append(result[0])
            yield result

    monkeypatch.setattr(batch, "_gate_baseline", tracked_baseline)
    original = batch._validate_candidate

    def validate(name, value, view):
        assert not hasattr(view, "transaction") and not hasattr(view, "freeze_artifact")
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[-1].execute("SELECT 1")
        # A separate exclusive lock must be immediately obtainable during audit.
        with sqlite3.connect(batch.path, timeout=0) as db:
            db.execute("BEGIN EXCLUSIVE")
            db.rollback()
        original(name, value, view)

    monkeypatch.setattr(batch, "_validate_candidate", validate)
    final = batch._gate_final

    def check(*args):
        assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
        return final(*args)

    monkeypatch.setattr(batch, "_gate_final", check)
    batch.freeze_artifact("scope_review", path)


def test_scope_close_expiry_rejected_after_hash_work(setup, monkeypatch):
    batch, clock, _, _, _ = setup
    path, _ = candidate(setup)
    close = AdmissionReadScope.__exit__

    def expires(scope, *args):
        result = close(scope, *args)
        clock[0] = batch.auth["expires_unix"]
        return result

    monkeypatch.setattr(AdmissionReadScope, "__exit__", expires)
    with pytest.raises(ProviderStop, match="EXPIRED"):
        batch.freeze_artifact("scope_review", path)
    assert not rows(batch)


def mock_references(setup, monkeypatch):
    """Real gate mechanics with explicitly fake source/reference semantics."""
    batch = setup[0]
    refs, files = [], {}
    source = batch.root / "cases/SYNTHETIC/public-initial.json"
    files[str(source)] = put(source, {"synthetic_source": True})
    monkeypatch.setattr(audit, "CASES", batch.root / "cases")
    wire = payload([{"role": "user", "content": "synthetic public input"}], {"type": "object"})
    raw = '{"synthetic":"full raw output"}'
    for spec in batch.plan["P3"]:
        spec["root"] = "SYNTHETIC"
        row = {
            "stage": "P3",
            "episode": spec["id"],
            "turn": 1,
            "selected_condition": "B1",
            "selected_decoder": "D11",
            "hashes": {},
        }
        for kind in module.KINDS:
            path = batch.root / "full-reference/P3" / spec["id"] / f"request-01.{kind}.json"
            digest = put(path, {"synthetic_layer": kind})
            row[kind], row["hashes"][kind] = str(path), digest
            files[str(path)] = digest
        refs.append(row)

    def fake_reference(view, row, spec):
        assert view.root == batch.root and view.spec(spec["id"]) == spec
        assert not hasattr(view, "transaction")
        return {}, {}, copy.deepcopy(wire), raw

    monkeypatch.setattr(audit, "validate_reference", fake_reference)
    path = batch.root / "references-candidate.json"
    value = {"references": refs, "files": files}
    put(path, value)
    return path, value, wire, raw


def test_reference_freeze_and_defensive_facade(setup, monkeypatch):
    batch = setup[0]
    path, value, _, _ = mock_references(setup, monkeypatch)
    batch.freeze_artifact("P3_references", path)
    first = batch.references("P3")
    assert first == value["references"]
    first[0]["hashes"].clear()
    assert batch.references("P3") == value["references"]
    view = module.AuditView(batch.root, batch.plan, {"P3": value["references"]})
    view.plan["P3"].clear()
    view.references("P3").clear()
    assert len(view.plan["P3"]) == len(view.references("P3")) == 16


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "order",
        "bool_turn",
        "decoder",
        "presentation",
        "stage",
        "unbound_file",
        "audit_reject",
    ],
)
def test_reference_gate_negative_controls(setup, monkeypatch, change):
    batch = setup[0]
    path, value, _, _ = mock_references(setup, monkeypatch)
    row = value["references"][0]
    if change == "missing":
        value["references"].pop()
    elif change == "order":
        value["references"].reverse()
    elif change == "bool_turn":
        row["turn"] = True
    elif change == "decoder":
        row["selected_decoder"] = "D00"
    elif change == "presentation":
        row["selected_condition"] = "B0"
    elif change == "stage":
        row["stage"] = "P4"
    elif change == "unbound_file":
        del value["files"][row["wire"]]
    else:

        def reject(*args):
            raise ProviderStop("SYNTHETIC_INDEPENDENT_AUDITOR_REJECT")

        monkeypatch.setattr(audit, "validate_reference", reject)
    put(path, value)
    with pytest.raises(ProviderStop):
        batch.freeze_artifact("P3_references", path)
    assert not rows(batch)


def preflight_receipts(setup, monkeypatch):
    batch = setup[0]
    path, references, wire, raw = mock_references(setup, monkeypatch)
    batch.plan["http_identity"] = {"model": MODEL, "context": 65536, "version": "TEST_ONLY_VERSION"}
    batch.freeze_artifact("P3_references", path)
    directory, files, calls, result_rows = batch.root / "P3-preflight", {}, [], []

    def save(path, value):
        files[str(path)] = put(path, value)

    for end in ("start", "final"):
        for name, route in (("models", "/v1/models"), ("version", "/version")):
            parent = directory / ("identity-" + end)
            save(parent / (name + "-attempt.json"), {"method": "GET", "route": route})
            body = (
                {"data": [{"id": MODEL, "max_model_len": 65536}]}
                if name == "models"
                else {"version": "TEST_ONLY_VERSION"}
            )
            save(parent / (name + ".json"), {"status_code": 200, "body": json.dumps(body)})
    for reference in references["references"]:
        for kind, body in (
            ("input", {key: wire[key] for key in TOKENIZE_KEYS}),
            ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
        ):
            stem = directory / (reference["episode"] + "-01-" + kind)
            attempt = {
                "episode": reference["episode"],
                "turn": 1,
                "kind": kind,
                "method": "POST",
                "route": "/tokenize",
            }
            save(stem.with_suffix(".request.json"), body)
            save(stem.with_suffix(".attempt.json"), attempt)
            save(
                stem.with_suffix(".http.json"),
                {"status_code": 200, "body": json.dumps({"count": 10 if kind == "input" else 3})},
            )
            calls.append(attempt)
        result_rows.append(
            {
                "episode": reference["episode"],
                "turn": 1,
                "counts": {"input": 10, "output": 3},
                "reference_hashes": reference["hashes"],
            }
        )
    value = {
        "status": "G_PREFLIGHT_PASS",
        "stage": "P3",
        "reason": None,
        "model_requests": 0,
        "files": files,
        "rows": result_rows,
        "tokenize_calls": calls,
    }
    path = directory / "result.json"
    put(path, value)
    return path, value


def test_real_preflight_receipt_auditor_uses_no_nested_db_callback(setup, monkeypatch):
    batch = setup[0]
    path, value = preflight_receipts(setup, monkeypatch)

    def forbidden(*args):
        raise AssertionError("AUDITOR_MUST_USE_FACADE_NOT_LIVE_BATCH")

    monkeypatch.setattr(batch, "references", forbidden)
    batch.freeze_artifact("P3_preflight", path)
    assert len(value["files"]) == 104
    assert batch.artifact("P3_preflight") == value


@pytest.mark.parametrize(
    "change", ["count_bool", "http_201", "capacity", "actual_wire", "extra_attempt"]
)
def test_real_preflight_receipt_rejections(setup, monkeypatch, change):
    batch = setup[0]
    path, value = preflight_receipts(setup, monkeypatch)
    target = path.parent / "P3-00-01-input.http.json"
    if change == "extra_attempt":
        put(path.parent / "extra-attempt.json", {})
    elif change == "actual_wire":
        target = target.with_name("P3-00-01-input.request.json")
        value["files"][str(target)] = put(target, {"wrong": "actual request"})
    else:
        receipt = {
            "status_code": 201 if change == "http_201" else 200,
            "body": json.dumps({"count": True if change == "count_bool" else 65536}),
        }
        value["files"][str(target)] = put(target, receipt)
    put(path, value)
    with pytest.raises(ProviderStop):
        batch.freeze_artifact("P3_preflight", path)
    assert [row["name"] for row in rows(batch)] == ["P3_references"]


@pytest.mark.parametrize("change", [False, True])
def test_real_reference_source_auditor_is_retained(tmp_path, monkeypatch, change):
    from test_v0222_presentation_audit import prepared

    old_fixture, _ = prepared(tmp_path, monkeypatch, "P3")
    old_fixture.plan.setdefault("P4", [])
    view = module.AuditView(old_fixture.root, old_fixture.plan, {"P3": old_fixture.refs})
    value = {
        "references": old_fixture.refs,
        "files": {
            row[kind]: row["hashes"][kind] for row in old_fixture.refs for kind in module.KINDS
        },
    }
    source = audit.CASES / old_fixture.value["root"] / "public-initial.json"
    value["files"][str(source)] = audit.sha(source)
    value["files"].update(
        {
            str(p): audit.sha(p)
            for p in (old_fixture.root / "full-reference/P3").rglob("*")
            if p.is_file()
        }
    )
    batch = object.__new__(module.Batch)
    if change:
        source = audit.CASES / old_fixture.value["root"] / "public-initial.json"
        public = json.loads(source.read_text())
        public["current"]["changed_source"] = "not in the original request"
        put(source, public)
        with pytest.raises(ProviderStop, match="NOT_REBUILT"):
            batch._validate_candidate("P3_references", value, view)
    else:
        batch._validate_candidate("P3_references", value, view)


@pytest.mark.parametrize("change", ["none", "derived_hash", "specs_mismatch"])
def test_resolved_specs_use_real_source_derived_initial_hash(setup, monkeypatch, change):
    from test_v0222_presentation_provider import environment

    from v0218_world import digest

    batch = setup[0]
    public = environment()
    source = batch.root / "cases/SYNTHETIC/public-initial.json"
    source_sha = put(source, public)
    monkeypatch.setattr(audit, "CASES", batch.root / "cases")
    for spec in batch.plan["P4"]:
        spec.update(
            root="SYNTHETIC", scope="scope-" + spec["id"], actions=[], intent={"ordered_writes": []}
        )
        initial = {
            **copy.deepcopy(public),
            "scope": spec["scope"],
            "version": 0,
            "records": {},
            "pending": {},
            "history": [],
        }
        spec["initial_state_sha256"] = digest(initial)
    if change == "derived_hash":
        batch.plan["P4"][0]["initial_state_sha256"] = "0" * 64
    value = {"specs": copy.deepcopy(batch.plan["P4"]), "files": {str(source): source_sha}}
    if change == "specs_mismatch":
        value["specs"][0]["scope"] = "another scope"
    path = batch.root / "resolved-candidate.json"
    put(path, value)
    if change == "none":
        batch.freeze_artifact("P4_resolved_specs", path)
        assert batch.artifact("P4_resolved_specs") == value
    else:
        with pytest.raises(ProviderStop, match=r"INITIAL_STATE_DRIFT|EXACT_RESOLVED"):
            batch.freeze_artifact("P4_resolved_specs", path)
        assert not rows(batch)


def test_expired_completed_p3_does_not_expire_p4_preparation(setup, monkeypatch):
    batch, clock, _, _, anchor = setup
    # Synthetic baseline with no P3 episode ever claimed: purpose is deadline
    # targeting, not a claim that this matrix has completed real P3 execution.
    review, _ = candidate(setup)
    batch.freeze_artifact("scope_review", review)
    for name, status in (("P3_preflight", "G_PREFLIGHT_PASS"),):
        path = batch.root / (name + ".json")
        dependencies = {str(anchor): put(anchor, {"synthetic": True})}
        digest = put(path, {"status": status, "files": dependencies})
        with batch.transaction() as db:
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (name, str(path), digest, json.dumps(dependencies)),
            )
    batch.launch_once("P3")
    clock[0] = 2801.0
    path, _ = candidate(setup, "p4-preflight", status="G_PREFLIGHT_PASS")
    monkeypatch.setattr(audit, "validate_preflight", lambda *args: None)  # Receipts tested above.
    batch.freeze_artifact("P4_preflight", path)
    assert "P4_preflight" in {row["name"] for row in rows(batch)}
    with pytest.raises(ProviderStop, match="PHASE_DEADLINE"):
        batch.references("P3")


def test_original_exception_precedes_secondary_stop_failure(setup, monkeypatch):
    batch = setup[0]
    path, _ = candidate(setup)

    class FalseyError(RuntimeError):
        def __bool__(self):
            return False

    original = FalseyError("original audit failure")

    def fail(*args):
        raise original

    def stop(*args):
        raise OSError("secondary stop persistence failed")

    monkeypatch.setattr(batch, "_validate_candidate", fail)
    monkeypatch.setattr(batch, "stop", stop)
    with pytest.raises(FalseyError) as caught:
        batch.freeze_artifact("scope_review", path)
    assert caught.value is original
    assert any("SECONDARY_STOP_FAILURE" in note for note in original.__notes__)
    assert not rows(batch)


@pytest.mark.parametrize(
    "field,value",
    [
        ("root", "/different/formal-root"),
        ("binding_sha256", "f" * 64),
        ("root", None),
        ("binding_sha256", None),
    ],
)
def test_scope_review_cannot_be_reused_for_another_instance(setup, field, value):
    batch = setup[0]
    path, _ = candidate(setup, **{field: value})
    with pytest.raises(ProviderStop, match="CURRENT_ROOT_AND_BINDING"):
        batch.freeze_artifact("scope_review", path)
    assert not rows(batch) and batch.snapshot()["stop"]


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "world_unbound",
        "turn_unbound",
        "source_unbound",
        "session_binding_unbound",
        "world_changes",
        "turn_changes",
        "extra_turn",
        "late_extra_turn",
        "late_other_file",
        "wal",
        "shm",
        "journal",
    ],
)
def test_real_p4_reference_complete_preparation_read_set(tmp_path, monkeypatch, change):
    from test_v0222_presentation_audit import prepared

    fixture, _ = prepared(tmp_path, monkeypatch, "P4", writes=1)
    fixture.plan.setdefault("P3", [])
    view = module.AuditView(fixture.root, fixture.plan, {"P4": fixture.refs})
    directory = fixture.root / "full-reference/P4" / fixture.value["id"]
    source = audit.CASES / fixture.value["root"] / "public-initial.json"
    paths = [source, *(p for p in directory.rglob("*") if p.is_file())]
    value = {"references": fixture.refs, "files": {str(p): audit.sha(p) for p in paths}}
    targets = {
        "world": directory / "world.sqlite",
        "turn": directory / "session/turn-01.json",
        "source": source,
        "session_binding": directory / "session/session-binding.json",
    }
    assert targets["session_binding"].is_file()
    if change.endswith("_unbound"):
        del value["files"][str(targets[change.removesuffix("_unbound")])]
    elif change == "extra_turn":
        extra = directory / "session/turn-99.json"
        value["files"][str(extra)] = put(extra, {})
    elif change in {"wal", "shm", "journal"}:
        sidecar = Path(str(targets["world"]) + "-" + change)
        value["files"][str(sidecar)] = put(sidecar, {})
    original = audit.validate_reference

    def audited(*args):
        result = original(*args)
        if change in {"world_changes", "turn_changes"}:
            # All old semantics ran first; subsequent real scope close must fail.
            if args[1]["turn"] == len(fixture.refs):
                targets[change.removesuffix("_changes")].write_bytes(b"changed")
        elif change.startswith("late_") and args[1]["turn"] == len(fixture.refs):
            put(
                directory
                / ("session/turn-99.json" if change == "late_extra_turn" else "late.json"),
                {},
            )
        return result

    monkeypatch.setattr(audit, "validate_reference", audited)
    batch = object.__new__(module.Batch)
    scope = AdmissionReadScope()

    def verify():
        with scope:
            for path, digest in value["files"].items():
                scope.read_bytes(Path(path), digest)
            batch._validate_candidate("P4_references", value, view)

    if change == "none":
        verify()
        assert scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    else:
        with pytest.raises((ProviderStop, ValueError)):
            verify()
        assert scope.status == "CLOSED_FAILED"


def preparation_fixture(setup):
    """Pre-registered synthetic artifacts isolate gate orchestration, not source proof."""
    batch, _, _, _, anchor = setup
    artifact_values, all_files = {}, {}
    for stage in ("P3", "P4"):
        refs, files = [], {}
        for index, spec in enumerate(batch.plan[stage]):
            if stage == "P4":
                spec["actions"] = [{"synthetic": True}] * (2 if index < 8 else 1)
            world = batch.root / "full-reference" / stage / spec["id"] / "world.sqlite"
            files[str(world)] = put(world, {"NOT_A_REAL_WORLD": spec["id"]})
            for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3):
                refs.append({"episode": spec["id"], "turn": turn})
        artifact_values[stage + "_references"] = {"references": refs, "files": files}
    artifact_values["P4_resolved_specs"] = {
        "specs": copy.deepcopy(batch.plan["P4"]),
        "files": {str(anchor): audit.sha(anchor)},
    }
    for name, value in artifact_values.items():
        path = batch.root / (name + ".json")
        all_files[str(path)] = put(path, value)
        all_files.update(value["files"])
        sql_only = batch.root / (name + "-sql-only.json")
        sql_deps = {str(sql_only): put(sql_only, {"sql_dependency": name})}
        all_files.update(sql_deps)
        with batch.transaction() as db:
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (name, str(path), all_files[str(path)], json.dumps(sql_deps)),
            )
    value = {
        "status": "REFERENCE_PREPARATION_PASS",
        "revision": module.REVISION,
        "selected_presentation": "B1",
        "selected_decoder": "D11",
        "P3_requests": 16,
        "P4_requests": 80,
        "P4_chains": 24,
        "isolated_offline_worlds": 40,
        "model_requests": 0,
        "http_requests": 0,
        "decoder_membership": "UNOBSERVED",
        "files": all_files,
    }
    path = batch.root / "prepared.json"
    put(path, value)
    return path, value


def test_full_preparation_registers_exact_frozen_artifact_dependency_union(setup):
    batch = setup[0]
    path, value = preparation_fixture(setup)
    batch.freeze_artifact("P_full_preparation", path, "REFERENCE_PREPARATION_PASS")
    assert batch.artifact("P_full_preparation") == value
    assert len(rows(batch)) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("P3_requests", 15),
        ("P4_requests", 79),
        ("P4_chains", 23),
        ("isolated_offline_worlds", 39),
        ("model_requests", False),
        ("http_requests", 0.0),
        ("http_requests", 1),
        ("revision", "other"),
        ("selected_presentation", "B0"),
        ("selected_decoder", "D10"),
        ("decoder_membership", "PASS"),
    ],
)
def test_full_preparation_counts_contract_and_zero_http_are_strict(setup, field, value):
    batch = setup[0]
    path, body = preparation_fixture(setup)
    body[field] = value
    put(path, body)
    with pytest.raises(ProviderStop, match="COUNTS_AND_CONTRACT"):
        batch.freeze_artifact("P_full_preparation", path)
    assert len(rows(batch)) == 3 and batch.snapshot()["stop"]


@pytest.mark.parametrize(
    "change",
    ["missing_artifact", "artifact_pin", "sql_only", "world", "wrong_hash", "artifact_drift"],
)
def test_full_preparation_requires_all_frozen_prerequisites_and_union(setup, change):
    batch = setup[0]
    path, body = preparation_fixture(setup)
    target = batch.root / "P3_references.json"
    if change == "missing_artifact":
        with batch.transaction() as db:
            db.execute("DELETE FROM artifacts WHERE name='P3_references'")
    elif change == "artifact_drift":
        target.write_text("{}")
    elif change == "wrong_hash":
        body["files"][str(target)] = "0" * 64
    else:
        if change == "sql_only":
            target = batch.root / "P3_references-sql-only.json"
        elif change == "world":
            target = batch.root / "full-reference/P3/P3-00/world.sqlite"
        del body["files"][str(target)]
    put(path, body)
    with pytest.raises((ProviderStop, ValueError)):
        batch.freeze_artifact("P_full_preparation", path)
    assert "P_full_preparation" not in {row["name"] for row in rows(batch)}


@pytest.mark.parametrize(
    "change",
    [
        "prepared_self",
        "engineering_self",
        "references_self",
        "resolved_self",
        "sql_only",
        "file_only",
        "execution_binding",
        "authorization",
        "source",
        "manifest",
        "consent_missing",
        "consent_false",
        "consent_int",
    ],
)
def test_scope_review_requires_current_five_artifacts_controls_and_no_new_consent(setup, change):
    batch = setup[0]
    path, value = candidate(setup)
    targets = {
        "prepared_self": "P_full_preparation.json",
        "engineering_self": "engineering_checks.json",
        "references_self": "P4_references.json",
        "resolved_self": "P4_resolved_specs.json",
        "sql_only": "P3_references-scope-sql-only.json",
        "file_only": "anchor.json",
        "execution_binding": "execution-binding.json",
        "authorization": "authorization.json",
        "source": "authorization-source.json",
        "manifest": "manifest.json",
    }
    if change.startswith("consent_"):
        if change == "consent_missing":
            del value["review_is_not_user_consent"]
        else:
            value["review_is_not_user_consent"] = False if change == "consent_false" else 1
    else:
        del value["files"][str(batch.root / targets[change])]
    put(path, value)
    with pytest.raises(ProviderStop, match="SCOPE_REVIEW"):
        batch.freeze_artifact("scope_review", path)
    assert not rows(batch) and batch.snapshot()["stop"]


@pytest.mark.parametrize("missing", module.SCOPE_PREREQUISITES)
def test_scope_review_cannot_precede_any_preparation_prerequisite(setup, missing):
    batch = setup[0]
    path, _ = candidate(setup)
    with batch.transaction() as db:
        db.execute("DELETE FROM artifacts WHERE name=?", (missing,))
    with pytest.raises(ProviderStop, match="FROZEN_ARTIFACT_REQUIRED"):
        batch.freeze_artifact("scope_review", path)
    assert not rows(batch)


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "delete_prepared",
        "replace_prepared",
        "replace_reference",
        "new_sql_dependency",
        "prepared_not_pass",
    ],
)
def test_ready_rechecks_current_preparation_mapping_after_review_freeze(setup, change):
    batch, _, _, scopes, anchor = setup
    path, _ = candidate(setup)
    batch.freeze_artifact("scope_review", path)
    preflight = batch.root / "P3-preflight-test.json"
    files = {str(anchor): audit.sha(anchor)}
    digest = put(preflight, {"status": "G_PREFLIGHT_PASS", "files": files})
    with batch.transaction() as db:
        db.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?)",
            ("P3_preflight", str(preflight), digest, json.dumps(files)),
        )
    batch.launch_once("P3")
    with batch._operation("P3"):
        pass
    old_scope = scopes[-1]
    with batch.transaction() as db:
        if change == "delete_prepared":
            db.execute("DELETE FROM artifacts WHERE name='P_full_preparation'")
        elif change in {"replace_prepared", "replace_reference", "prepared_not_pass"}:
            name = "P3_references" if change == "replace_reference" else "P_full_preparation"
            original = db.execute("SELECT path FROM artifacts WHERE name=?", (name,)).fetchone()[0]
            value = json.loads(Path(original).read_text())
            if change == "prepared_not_pass":
                value["status"] = "NOT_MET"
            replacement = batch.root / (name + "-replacement.json")
            digest = put(replacement, value)
            db.execute(
                "UPDATE artifacts SET path=?,sha256=? WHERE name=?",
                (str(replacement), digest, name),
            )
        elif change == "new_sql_dependency":
            extra = batch.root / "new-dependency.json"
            pins = {str(extra): put(extra, {"new": True})}
            db.execute(
                "UPDATE artifacts SET dependencies=? WHERE name='P4_references'",
                (json.dumps(pins),),
            )
    if change == "none":
        with batch._operation("P3"):
            pass
        assert scopes[-1] is not old_scope
        assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    else:
        with pytest.raises(ProviderStop):
            with batch._operation("P3"):
                pytest.fail("FRESH_READY_SHOULD_REJECT_BEFORE_YIELD")
        assert batch.snapshot()["stop"]
