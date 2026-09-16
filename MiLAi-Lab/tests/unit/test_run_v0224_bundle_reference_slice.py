"""Synthetic World only; no historical fixture, HTTP, or performance experiment."""

import copy
import socket
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

import run_v0224_bundle_reference_slice as worker
import v0224_reference_outer_bounds as bounded


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("SYNTHETIC_TEST_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    import prepare_v0221_http_v2 as case_module
    import v0222_presentation_audit as audit
    import v0224_bundle_cpu_batch as batch_module
    from prepare_v0222_full import resolve_p4_spec

    def make(writes=1):
        root = tmp_path / "root"
        root.mkdir()
        out = tmp_path / "reference-slice"
        out.mkdir()
        cases = tmp_path / "cases"
        source = cases / "synthetic" / "public-initial.json"
        source.parent.mkdir(parents=True)
        worker._save(source, public())
        actions = [put(), put("right", 1)][:writes]
        spec = {
            "id": worker.INSTANCE + "-p4-01",
            "stage": "P4",
            "root": "synthetic",
            "scope": "TEST_ONLY_complete_reference",
            "actions": actions,
            "intent": {
                "instruction": "Perform these synthetic writes in order.",
                "ordered_writes": [
                    {k: a["arguments"][k] for k in ("object_id", "data")} for a in actions
                ],
            },
            "initial_state_sha256": "TEST_ONLY_unresolved",
        }
        spec, _ = resolve_p4_spec(spec, public())
        plan = {
            "P3": [{"id": f"synthetic-p3-{i}"} for i in range(16)],
            "P4": [spec] + [{"id": f"synthetic-p4-{i}"} for i in range(1, 24)],
        }
        worker._save(root / "manifest.json", {"inputs": {str(source): worker._sha(source)}})
        binding = {"manifest.json": worker._sha(root / "manifest.json")}
        worker._save(root / "execution-binding.json", binding)
        binding_sha = worker._sha(root / "execution-binding.json")
        with sqlite3.connect(root / "batch.sqlite") as db:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE episodes(id TEXT PRIMARY KEY,stage TEXT,ordinal INTEGER,
                                      cap INTEGER,status TEXT,pid INTEGER,deadline REAL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY,event TEXT NOT NULL);
                CREATE TABLE artifacts(name TEXT PRIMARY KEY,path TEXT,
                                       sha256 TEXT,dependencies TEXT);
                CREATE TABLE launches(stage TEXT PRIMARY KEY,pid INTEGER,started REAL);
                CREATE TABLE claims(episode TEXT PRIMARY KEY,pid INTEGER,
                                    started REAL,deadline REAL);
            """)
            db.execute("INSERT INTO meta VALUES('binding',?)", (binding_sha,))
            for stage in ("P3", "P4"):
                db.executemany(
                    "INSERT INTO episodes VALUES(?,?,?,?,?,NULL,NULL)",
                    [
                        (s["id"], stage, i, 1 if stage == "P3" else 4, "PENDING")
                        for i, s in enumerate(plan[stage])
                    ],
                )
        baseline = tmp_path / "coordinator-baseline.json"
        worker._save(baseline, worker.sql_snapshot(root))
        for name in ("bundle", "receipt"):
            (tmp_path / name).write_bytes(b"synthetic authority not used by fake admission")
        authority = {
            "bundle_path": str(tmp_path / "bundle"),
            "bundle_sha256": worker._sha(tmp_path / "bundle"),
            "receipt_path": str(tmp_path / "receipt"),
            "receipt_sha256": worker._sha(tmp_path / "receipt"),
            "limits": {
                "max_header_bytes": 10000,
                "max_payload_bytes": 10000,
                "max_paths": 100,
                "max_blobs": 100,
            },
        }
        contract = {
            "status": "R03_SINGLE_REFERENCE_SLICE_FROZEN",
            "execution_revision": worker.REVISION,
            "instance": worker.INSTANCE,
            "root": str(root),
            "binding_sha256": binding_sha,
            "first_p4_spec": spec,
            "public_source": {"path": str(source), "sha256": worker._sha(source)},
            "coordinator_baseline": {"path": str(baseline), "sha256": worker._sha(baseline)},
            "static_authority": authority,
            **worker.FIXED_LIMITS,
            "files": {
                str(p): worker._sha(p)
                for p in [
                    source,
                    baseline,
                    root / "execution-binding.json",
                    tmp_path / "bundle",
                    tmp_path / "receipt",
                ]
            },
        }
        state = SimpleNamespace(
            contract=contract,
            out=out,
            plan=plan,
            hook=lambda: None,
            root=root,
            source=source,
            operations=[],
        )

        class SyntheticBatch:
            def __init__(self, selected, pin, *, static_authority):
                assert selected == root and pin == binding_sha
                self.root, self.plan, self.binding = root, plan, binding

            @contextmanager
            def _operation(self, phase):
                state.operations.append(phase)
                state.hook()
                yield

        monkeypatch.setattr(worker, "CPU_ROOT", root)
        monkeypatch.setattr(batch_module, "selected_root", lambda: root)
        monkeypatch.setattr(batch_module, "OfflineBatch", SyntheticBatch)
        monkeypatch.setattr(case_module, "CASES", cases)
        monkeypatch.setattr(audit, "CASES", cases)
        return state

    return make


@pytest.mark.parametrize("writes,turns,total", [(1, 3, 9), (2, 4, 11)])
def test_real_complete_session_original_row_audit_world_and_unchanged_sql(
    synthetic, writes, turns, total
):
    state = synthetic(writes)
    worker.validate_contract(state.contract)
    before = worker.sql_snapshot(state.root)
    details, phases = {}, []
    worker._run_slice(state.contract, state.out, phases, details)
    assert worker.sql_snapshot(state.root) == before
    assert details["provider_rows"] == turns
    assert details["runtime_guard_count"] == total - 2
    assert details["guard_counts"] == {"attempted": total, "returned": total}
    assert state.operations == ["PREP"] * total
    assert details["independent_effects"]["status"] == "PASS"
    assert details["outer_bounds"][0]["status"] == "QUALIFIED_OUTER_UPPER_BOUND"
    assert len(worker._read(state.out / "reference-rows.json")) == turns


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "DRAFT"),
        ("execution_revision", "R02"),
        ("concurrency", True),
        ("http_requests_allowed", 1),
        ("session_seconds", 61),
        ("session_outer_upper_bound_seconds", 19),
        ("worker_outer_seconds", 301),
        ("slice_count", 2),
        ("instance", "another"),
    ],
)
def test_contract_rejects_scope_and_limit_drift(synthetic, key, value):
    contract = synthetic().contract
    contract[key] = value
    with pytest.raises(ValueError):
        worker.validate_contract(contract)


def test_current_sql_must_be_semantically_checked_not_immutable_pin(synthetic):
    state = synthetic()
    state.contract["files"][str(state.root / "batch.sqlite")] = worker._sha(
        state.root / "batch.sqlite"
    )
    with pytest.raises(ValueError, match="MUTABLE_CURRENT_SQL"):
        worker.validate_contract(state.contract)


def test_nonfirst_spec_rejected(synthetic):
    state = synthetic()
    state.contract["first_p4_spec"] = copy.deepcopy(state.contract["first_p4_spec"])
    state.contract["first_p4_spec"]["id"] = worker.INSTANCE + "-p4-02"
    with pytest.raises(ValueError, match="EXACT_FIRST_P4"):
        worker.validate_contract(state.contract)


def test_initial_state_checks_all_episode_columns_and_tables(synthetic):
    state = synthetic()
    with sqlite3.connect(state.root / "batch.sqlite") as db:
        db.execute("UPDATE episodes SET deadline=0 WHERE ordinal=23")
    baseline = state.contract["coordinator_baseline"]
    worker._save(baseline["path"], worker.sql_snapshot(state.root))
    baseline["sha256"] = worker._sha(baseline["path"])
    with pytest.raises(ValueError, match="FRESH_40_PENDING"):
        worker._run_slice(state.contract, state.out, [], {})
    assert state.operations == []


def test_sql_drift_is_secondary_to_original_admission_failure(synthetic):
    state = synthetic()
    primary = RuntimeError("synthetic original admission refusal")

    def fail():
        with sqlite3.connect(state.root / "batch.sqlite") as db:
            db.execute("INSERT INTO events VALUES(1,'unexpected')")
        raise primary

    state.hook = fail
    with pytest.raises(RuntimeError) as raised:
        worker._run_slice(state.contract, state.out, [], {})
    assert raised.value is primary
    assert any("CURRENT_COORDINATOR_SQL_CHANGED" in note for note in primary.__notes__)
    assert worker._read(state.out / "coordinator-after.json")["events"]


def test_successful_reference_with_sql_mutation_rejected(synthetic):
    state = synthetic()

    def mutate():
        with sqlite3.connect(state.root / "batch.sqlite") as db:
            db.execute("INSERT OR IGNORE INTO events VALUES(1,'unexpected')")

    state.hook = mutate
    with pytest.raises(ValueError, match="CURRENT_COORDINATOR_SQL_CHANGED"):
        worker._run_slice(state.contract, state.out, [], {})


def test_current_manifest_must_directly_pin_public_source(synthetic):
    state = synthetic()
    state.contract["public_source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="CURRENT_MANIFEST_PUBLIC_PIN_DRIFT"):
        worker._run_slice(state.contract, state.out, [], {})
    assert state.operations == []


def test_original_raw_validator_detects_tampering(synthetic, monkeypatch):
    state = synthetic()
    original = bounded.prepare_p4_bounded

    def tamper(*args, **kwargs):
        rows, spec = original(*args, **kwargs)
        Path(rows[0]["output"]).write_text("{}")
        return rows, spec

    monkeypatch.setattr(bounded, "prepare_p4_bounded", tamper)
    with pytest.raises(bounded.ProviderStop, match="PRESENTATION_REFERENCE_HASH_DRIFT"):
        worker._run_slice(state.contract, state.out, [], {})
    assert (state.out / "reference-rows.json").is_file()


def test_extra_guard_call_is_not_accepted_as_complete_mapping(synthetic, monkeypatch):
    state = synthetic()
    original = bounded.prepare_p4_bounded

    def extra(directory, spec, public_data, guard, **kwargs):
        result = original(directory, spec, public_data, guard, **kwargs)
        guard()
        return result

    monkeypatch.setattr(bounded, "prepare_p4_bounded", extra)
    with pytest.raises(ValueError, match="FULL_REFERENCE_GUARD_COVERAGE"):
        worker._run_slice(state.contract, state.out, [], {})


def test_phase_clock_failure_preserves_primary(monkeypatch):
    values = iter([1])
    monkeypatch.setattr(worker.time, "monotonic_ns", lambda: next(values))
    primary = RuntimeError("body")
    with pytest.raises(RuntimeError) as raised, worker._phase([], "test"):
        raise primary
    assert raised.value is primary
    assert "SECONDARY_PHASE_OBSERVATION_FAILURE" in primary.__notes__[0]


def test_phase_limit_rejects_after_return(monkeypatch):
    values = iter([1, 300_000_000_002])
    monkeypatch.setattr(worker.time, "monotonic_ns", lambda: next(values))
    with pytest.raises(ValueError, match="SLICE_PHASE_OUTER_LIMIT"), worker._phase([], "test"):
        pass


def test_guard_refusal_precedes_contract_read_or_output(monkeypatch, tmp_path):
    import v0222_scoped_cpu_guard as guard

    def refuse():
        raise RuntimeError("synthetic guard refusal")

    monkeypatch.setattr(guard, "enable_cpu_network_guard", refuse)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", "--contract", str(tmp_path / "absent"), "--contract-sha256", "0" * 64],
    )
    with pytest.raises(RuntimeError, match="guard refusal"):
        worker.main()
    assert not list(tmp_path.iterdir())


def setup_main(state, monkeypatch, tmp_path):
    import v0222_scoped_cpu_guard as guard
    from v0220_evidence import dependencies

    state.out.rmdir()
    state.contract["files"].update(
        {str(p): worker._sha(p) for p in dependencies([Path(worker.__file__)])}
    )
    path = tmp_path / "execution-contract.json"
    worker._save(path, state.contract)
    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["worker", "--contract", str(path), "--contract-sha256", worker._sha(path)]
    )
    return path


def test_main_pins_complete_raw_and_reports_only_bounded_not_parent_verdict(
    synthetic, monkeypatch, tmp_path
):
    state = synthetic()
    setup_main(state, monkeypatch, tmp_path)
    assert worker.main() == 0
    report = worker._read(state.out / "worker-result.json")
    assert report["status"] == "R03_REFERENCE_SLICE_VALIDATED_NOT_GATE_A"
    assert report["model_requests"] == report["http_requests"] == report["device_calls"] == 0
    assert report["wall_before_result_write_ns"] > 0
    assert all(worker._sha(path) == digest for path, digest in report["raw_files"].items())
    assert any("Parent must check actual exit" in row for row in report["limits"])
    with pytest.raises(FileExistsError):
        worker.main()


def test_main_keeps_original_failure_when_postpins_drift(synthetic, monkeypatch, tmp_path):
    state = synthetic()
    setup_main(state, monkeypatch, tmp_path)
    primary = RuntimeError("primary guard failure")

    def fail():
        state.source.write_text("{}")
        raise primary

    state.hook = fail
    with pytest.raises(RuntimeError) as raised:
        worker.main()
    assert raised.value is primary
    report = worker._read(state.out / "worker-result.json")
    assert report["reason"] == str(primary)
    assert any("FROZEN_EXECUTION_INPUT_DRIFT" in note for note in report["notes"])
    assert report["status"] == "R03_REFERENCE_SLICE_FAILED"


def test_missing_worker_dependency_pin_rejected_before_constructor(
    synthetic, monkeypatch, tmp_path
):
    state = synthetic()
    path = setup_main(state, monkeypatch, tmp_path)
    state.contract["files"].pop(str(Path(bounded.__file__).resolve()))
    worker._save(path, state.contract)
    monkeypatch.setattr(
        sys, "argv", ["worker", "--contract", str(path), "--contract-sha256", worker._sha(path)]
    )
    with pytest.raises(ValueError, match="COMPLETE_WORKER_SOURCE_CLOSURE_REQUIRED"):
        worker.main()
    assert state.operations == []
    assert worker._read(state.out / "worker-result.json")["status"] == "R03_REFERENCE_SLICE_FAILED"


@pytest.mark.parametrize("token", ["1e999", "-1e999", "NaN", "Infinity"])
def test_strict_json_rejects_nonfinite_in_unknown_nested_field(tmp_path, token):
    path = tmp_path / "contract.json"
    path.write_text('{"unused": {"value": ' + token + "}}")
    with pytest.raises(ValueError, match="NONFINITE_JSON_NUMBER"):
        worker._read(path)


def test_contract_path_must_preserve_canonical_spelling_and_reject_alias(tmp_path):
    path = tmp_path / "contract.json"
    path.write_text("{}")
    assert worker._contract_path(str(path)) == path
    for value in (
        "contract.json",
        str(tmp_path) + "/./contract.json",
        str(tmp_path) + "/../" + tmp_path.name + "/contract.json",
    ):
        with pytest.raises(ValueError, match="CANONICAL_ABSOLUTE_EXECUTION_CONTRACT"):
            worker._contract_path(value)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="PATH_ALIAS_FORBIDDEN"):
        worker._contract_path(str(alias))


def test_cli_rejects_symlink_contract_before_output(synthetic, monkeypatch, tmp_path):
    state = synthetic()
    path = setup_main(state, monkeypatch, tmp_path)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    monkeypatch.setattr(
        sys, "argv", ["worker", "--contract", str(alias), "--contract-sha256", worker._sha(path)]
    )
    with pytest.raises(ValueError, match="PATH_ALIAS_FORBIDDEN"):
        worker.main()
    assert not state.out.exists() and not state.operations


def test_coordinator_baseline_pin_is_mandatory(synthetic):
    state = synthetic()
    state.contract["files"].pop(state.contract["coordinator_baseline"]["path"])
    with pytest.raises(ValueError, match="MANDATORY_CONTROL_PINS"):
        worker.validate_contract(state.contract)


def test_coordinator_baseline_all_tables_including_artifacts_are_frozen(synthetic):
    state = synthetic()
    with sqlite3.connect(state.root / "batch.sqlite") as db:
        db.execute("INSERT INTO artifacts VALUES('engineering_checks','synthetic','sha','{}')")
    with pytest.raises(ValueError, match="CURRENT_COORDINATOR_BASELINE_MISMATCH"):
        worker._run_slice(state.contract, state.out, [], {})
    assert not state.operations
    assert worker._read(state.out / "coordinator-before.json")["artifacts"]


def test_coordinator_baseline_bytes_must_match_external_pin(synthetic):
    state = synthetic()
    Path(state.contract["coordinator_baseline"]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="FROZEN_COORDINATOR_BASELINE_DRIFT"):
        worker._run_slice(state.contract, state.out, [], {})
    assert not state.operations


def test_contract_alias_introduced_during_run_is_rejected_on_recheck(
    synthetic, monkeypatch, tmp_path
):
    state = synthetic()
    path = setup_main(state, monkeypatch, tmp_path)

    def replace_contract(*args):
        target = tmp_path / "same-contract-bytes.json"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)

    monkeypatch.setattr(worker, "_run_slice", replace_contract)
    with pytest.raises(ValueError, match="PATH_ALIAS_FORBIDDEN"):
        worker.main()
    assert worker._read(state.out / "worker-result.json")["status"] == "R03_REFERENCE_SLICE_FAILED"
