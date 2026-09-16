"""Observation falsification only; synthetic files/operations, not a cold matrix."""

import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_scoped_cpu_observation as measurement
from run_v0222_presentation import run_child
from v0222_admission_read_scope import AdmissionReadScope
from v0222_scoped_evidence import _strict_json, read_pinned_events


class SyntheticDeadline(Exception):
    pass


class FalseyError(Exception):
    def __bool__(self):
        return False


@contextmanager
def operation(mode="normal"):
    if mode == "before":
        raise SyntheticDeadline("before")
    yield None, None, None
    if mode == "after":
        raise SyntheticDeadline("after")


@contextmanager
def scoped_operation():
    with AdmissionReadScope() as scope:
        yield None, scope, None


def inner_work():
    return sum(range(100))


def observer():
    return measurement.Observer(
        {
            AdmissionReadScope.__init__.__code__: ("scope_init", "scope.init"),
            AdmissionReadScope._close.__code__: ("scope_close", "scope.close"),
            AdmissionReadScope._regular_bytes.__code__: ("read", "scope.read"),
            json.loads.__code__: ("json_document", "scope.json"),
            _strict_json.__code__: ("strict_json", "history.jsonl"),
            operation.__wrapped__.__code__: ("generator", "operation"),
            scoped_operation.__wrapped__.__code__: ("generator", "scoped_operation"),
            inner_work.__code__: ("operation", "inner"),
            run_child.__code__: ("child", "run_child"),
        },
        jsonl_caller=read_pinned_events.__code__,
        json_document_caller=AdmissionReadScope.read_json.__code__,
    )


def observe(body):
    probe = observer()
    probe.start()
    try:
        body()
    finally:
        report = probe.finish()
    assert report["status"] == "OBSERVED", report
    assert sys.getprofile() is None
    return report


def test_complete_span_includes_with_body_and_scope_close(tmp_path):
    path = tmp_path / "doc.json"
    path.write_bytes(b'{"key":1}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    def body():
        with scoped_operation() as (_, scope, _):
            assert scope.read_json(path, digest) == {"key": 1}
            assert scope.read_json(path, digest) == {"key": 1}
            inner_work()
            _strict_json('{"sql_not_history":true}')

    report = observe(body)
    rows = report["records"]
    scope = next(row for row in rows if row["kind"] == "scope")
    whole = next(row for row in rows if row["kind"] == "generator")
    inner = next(row for row in rows if row["label"] == "inner")
    assert scope["parent_operation"] == inner["parent_operation"] == whole["id"]
    assert (whole["yields"], whole["resumes"]) == (1, 1)
    assert whole["start_wall_ns"] <= scope["start_wall_ns"]
    assert scope["close"]["end_wall_ns"] <= whole["end_wall_ns"]
    assert scope["status"] == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    assert scope["stats"]["json_parses"] == scope["json_parse_attempts"] == 1
    assert scope["stats"]["repeat_references"] == 1
    assert scope["jsonl_parse_attempts"] == 0
    for phase in ("first", "closing"):
        assert scope["stats"][phase + "_reads"] == 1
        assert scope["stats"][phase + "_hashes"] == 1
        assert scope["stats"][phase + "_bytes"] == path.stat().st_size
        assert scope["read_timing"][phase]["calls"] == 1
    assert scope["json_parse_timing"]["wall_ns"] > 0


@pytest.mark.parametrize("mode", ["before", "after", "body", "close"])
def test_generator_exceptions_are_not_successful_yields(mode):
    def body():
        if mode == "close":
            generator = operation.__wrapped__()
            next(generator)
            generator.close()
        else:
            with pytest.raises(SyntheticDeadline):
                with operation(mode):
                    if mode == "body":
                        raise SyntheticDeadline("body")

    report = observe(body)
    assert len(report["records"]) == 1
    assert report["records"][0]["return_observation"] == "UNWOUND"


@pytest.mark.parametrize(
    "raw,passes,count",
    [
        (b'{"event":1}\n{"event":2}\n', True, 2),
        (b"null\n", False, 1),
        (b'{"a":1,"a":2}\n', False, 1),
    ],
)
def test_jsonl_counts_attempts_including_invalid_objects(tmp_path, raw, passes, count):
    path = tmp_path / "events.jsonl"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    def read():
        with AdmissionReadScope() as scope:
            read_pinned_events(scope, path, digest)

    def body():
        if passes:
            read()
        else:
            with pytest.raises(ValueError):
                read()

    row = observe(body)["records"][0]
    assert row["jsonl_parse_attempts"] == count
    assert row["stats"]["json_parses"] == row["json_parse_attempts"] == 0
    assert (row["status"] == "CLOSED_VERIFIED_TWO_OBSERVATIONS") is passes


@pytest.mark.parametrize("raw,loads_calls", [(b'{"a":1,"a":2}', 1), (b"\xff", 0)])
def test_document_decode_failure_is_distinct_from_json_load_attempt(tmp_path, raw, loads_calls):
    path = tmp_path / "doc.json"
    path.write_bytes(raw)

    def body():
        with pytest.raises(ValueError):
            with AdmissionReadScope() as scope:
                scope.read_json(path, hashlib.sha256(raw).hexdigest())

    row = observe(body)["records"][0]
    assert row["status"] == "CLOSED_FAILED"
    assert row["stats"]["json_parses"] == 1
    assert row["json_parse_attempts"] == loads_calls


def test_repeated_close_does_not_count_as_new_verified_scope():
    def body():
        scope = AdmissionReadScope()
        scope.close()
        with pytest.raises(ValueError):
            scope.close()

    report = observe(body)
    assert len(report["records"]) == 2
    assert report["records"][1]["completion"] == "REPEATED_CLOSE_NOT_A_NEW_SUCCESS"
    assert report["records"][1]["return_observation"] == "UNWOUND"


def test_unclosed_scope_is_incomplete_and_finish_is_once():
    probe = observer()
    probe.start()
    scope = AdmissionReadScope()
    report = probe.finish()
    assert report["status"] == "INCOMPLETE_OBSERVATION"
    assert [row["kind"] for row in report["pending"]] == ["scope"]
    with pytest.raises(RuntimeError):
        probe.finish()
    scope.close()


def test_unclosed_collected_scope_id_reuse_cannot_disappear(monkeypatch):
    # Deterministic allocator-id collision; only observation's identity lookup is
    # substituted, not the scope or reader. CPython GC can produce this naturally.
    real_id = id
    monkeypatch.setattr(
        measurement,
        "id",
        lambda value: 1 if isinstance(value, AdmissionReadScope) else real_id(value),
        raising=False,
    )
    probe = observer()
    probe.start()
    unclosed = AdmissionReadScope()
    del unclosed
    with AdmissionReadScope():
        pass
    report = probe.finish()
    assert report["status"] == "INCOMPLETE_OBSERVATION"
    assert len(report["records"]) == 1
    assert len(report["pending"]) == 1 and report["pending"][0]["kind"] == "scope"
    assert report["pending"][0]["id"] != report["records"][0]["id"]


@pytest.mark.parametrize("error_type", [SyntheticDeadline, KeyboardInterrupt, SystemExit])
def test_callback_exception_propagates_and_marks_missing_coverage(error_type, monkeypatch):
    probe = observer()
    original = probe._observe

    def injected(frame, event, arg):
        if frame.f_code is inner_work.__code__ and event == "call":
            raise error_type("synthetic callback exception")
        return original(frame, event, arg)

    monkeypatch.setattr(probe, "_observe", injected)
    probe.start()
    try:
        with pytest.raises(error_type):
            inner_work()
    finally:
        report = probe.finish()
    assert report["status"] == "INCOMPLETE_OBSERVATION"
    assert report["errors"] == ["PROFILE_REMOVED_OR_REPLACED"]


def test_existing_profiler_is_preserved():
    def existing(frame, event, arg):
        return None

    sys.setprofile(existing)
    try:
        with pytest.raises(RuntimeError, match="FRESH_UNPROFILED"):
            observer().start()
        assert sys.getprofile() is existing
    finally:
        sys.setprofile(None)


def test_same_name_different_code_is_not_selected():
    def another():
        return 1

    another.__name__ = "inner_work"
    assert observe(another)["records"] == []


@pytest.mark.parametrize(
    "name,role,entry",
    [
        ("run_v0222_scoped_cpu", "stage", "v0222_scoped_cpu_runner"),
        ("run_v0222_scoped_cpu_worker", "worker", "v0222_scoped_cpu_worker"),
        ("run_v0222_scoped_cpu_prepare", "prepare", "prepare_v0222_scoped_cpu"),
        ("run_v0222_scoped_cpu_preflight", "preflight", "preflight_v0222_scoped_cpu"),
        ("run_v0222_scoped_cpu_seal", "seal", "seal_v0222_scoped_cpu"),
    ],
)
def test_bootstraps_only_add_observation_after_guard_and_stack_import(name, role, entry):
    import importlib

    module = importlib.import_module(name)
    tree = ast.parse(textwrap.dedent(inspect.getsource(module.main))).body[0]
    expected = ast.parse(
        "from v0222_scoped_cpu_guard import enable_cpu_network_guard\n"
        "enable_cpu_network_guard()\n"
        f"from {entry} import main as target\n"
        "from v0222_scoped_cpu_observation import run_observed\n"
        f"return run_observed(target, {role!r})\n"
    )
    alias = tree.body[2].names[0].asname
    expected.body[2].names[0].asname = alias
    expected.body[4].value.args[0].id = alias
    assert [ast.dump(node) for node in tree.body] == [ast.dump(node) for node in expected.body]


def test_without_explicit_opt_in_no_observation_or_report(monkeypatch):
    monkeypatch.delenv(measurement.OBSERVE_ENV, raising=False)
    assert measurement.run_observed(lambda: 7, "worker") == 7
    assert sys.getprofile() is None


@pytest.mark.parametrize("primary_type", [None, SyntheticDeadline, KeyboardInterrupt, SystemExit])
def test_report_failure_cannot_mask_primary_or_succeed(monkeypatch, primary_type):
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setenv(measurement.OBSERVE_ENV, "1")
    monkeypatch.setattr(guard, "require_cpu_network_guard", lambda: None)
    monkeypatch.setattr(measurement, "cpu_targets", lambda main: observer())

    def fail_save(*args):
        raise OSError("synthetic report failure")

    monkeypatch.setattr(measurement, "persist_report", fail_save)
    primary = primary_type("primary") if primary_type else None

    def body():
        if primary is not None:
            raise primary
        return 0

    with pytest.raises(primary_type or OSError) as raised:
        measurement.run_observed(body, "worker")
    if primary is not None:
        assert raised.value is primary
        assert primary.__notes__ == ["SECONDARY_CPU_OBSERVATION_FAILURE: OSError"]


def test_real_guarded_child_cpu_is_separate_from_parent(tmp_path):
    code = """
import json, sys
sys.path.insert(0, sys.argv[1])
from v0222_scoped_cpu_guard import enable_cpu_network_guard
enable_cpu_network_guard()
from v0222_scoped_cpu_observation import Observer
def work():
    return sum(i * i for i in range(100000))
probe = Observer({work.__code__: ('operation', 'synthetic_work')})
probe.start()
work()
print(json.dumps(probe.finish()))
"""
    result = None

    def body():
        nonlocal result
        result = run_child(
            [sys.executable, "-c", code, str(Path(__file__).resolve().parents[2] / "tools")],
            timeout=10,
            on_failure=lambda exc: pytest.fail(type(exc).__name__),
        )

    report = observe(body)
    child = json.loads(result["stdout"])
    assert child["status"] == "OBSERVED"
    assert child["pid"] == result["pid"] != os.getpid()
    assert child["parent_pid"] == os.getpid()
    span = report["records"][0]
    assert span["reaped_children_cpu_seconds"] > 0
    assert span["exit_summary"]["returncode"] == 0
    assert child["process_cpu_ns_before_report"] >= child["timing"]["process_cpu_ns"]


def test_cpu_target_selection_does_not_change_business_functions():
    import v0222_scoped_cpu_worker as worker
    from v0222_scoped_cpu_batch import OfflineBatch

    originals = {name: getattr(OfflineBatch, name) for name in ("_operation", "finish", "admit")}
    probe = measurement.cpu_targets(worker.main)
    assert probe.targets[worker.run.__code__] == ("operation", worker.__name__ + ".run")
    assert probe.targets[OfflineBatch._operation.__wrapped__.__code__][0] == "generator"
    assert all(getattr(OfflineBatch, name) is target for name, target in originals.items())
    assert sys.getprofile() is None


def test_short_lived_additional_thread_invalidates_coverage():
    import v0222_scoped_cpu_worker as worker

    probe = measurement.cpu_targets(worker.main)
    probe.start()
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join(timeout=2)
    report = probe.finish()
    assert not thread.is_alive()
    assert report["status"] == "INCOMPLETE_OBSERVATION"
    assert "ADDITIONAL_THREAD_STARTED_NOT_COVERED" in report["errors"]


def test_report_is_external_exclusive_and_contains_no_batch_writes(tmp_path, monkeypatch):
    import v0222_scoped_cpu_batch as batch

    root = tmp_path / "synthetic-cpu-root"
    monkeypatch.setattr(batch, "CPU_ROOT", root)
    report = {"status": "SYNTHETIC_TEST_REPORT"}
    measurement.persist_report(report, "worker")
    path = root.with_name(root.name + "-measurements") / f"worker-{os.getpid()}.json"
    assert json.loads(path.read_bytes()) == report
    assert not root.exists()
    with pytest.raises(FileExistsError):
        measurement.persist_report({"overwritten": True}, "worker")
    assert json.loads(path.read_bytes()) == report


def test_actual_guarded_main_help_records_no_worker_execution(tmp_path):
    # Main/guard/observer are actual; only report persistence uses a test path.
    code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
target = Path(sys.argv[2])
from v0222_scoped_cpu_guard import enable_cpu_network_guard
enable_cpu_network_guard()
import v0222_scoped_cpu_observation as measurement
from v0222_scoped_cpu_worker import main
measurement.persist_report = lambda report, role: target.write_text(json.dumps(report))
sys.argv = ['worker', '--help']
raise SystemExit(measurement.run_observed(main, 'worker'))
"""
    path = tmp_path / "help-observation.json"
    environment = {**os.environ, measurement.OBSERVE_ENV: "1"}
    result = subprocess.run(  # noqa: S603 -- Fixed guarded help probe, not a worker replay.
        [sys.executable, "-c", code, str(Path(__file__).resolve().parents[2] / "tools"), str(path)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(path.read_bytes())
    assert report["status"] == "OBSERVED"
    assert report["entry_exception_type"] == "SystemExit"
    assert report["role"] == "worker"
    assert [row["label"] for row in report["records"]] == ["v0222_scoped_cpu_worker.main"]


def test_missing_profile_cannot_return_successful_main(monkeypatch):
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setenv(measurement.OBSERVE_ENV, "1")
    monkeypatch.setattr(guard, "require_cpu_network_guard", lambda: None)
    monkeypatch.setattr(measurement, "cpu_targets", lambda main: observer())
    reports = []
    monkeypatch.setattr(measurement, "persist_report", lambda report, role: reports.append(report))

    def body():
        sys.setprofile(None)
        return 0

    with pytest.raises(RuntimeError, match="INCOMPLETE_CPU_OBSERVATION"):
        measurement.run_observed(body, "worker")
    assert reports[0]["status"] == "INCOMPLETE_OBSERVATION"


def test_falsey_exception_is_preserved_and_recorded(monkeypatch):
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setenv(measurement.OBSERVE_ENV, "1")
    monkeypatch.setattr(guard, "require_cpu_network_guard", lambda: None)
    monkeypatch.setattr(measurement, "cpu_targets", lambda main: observer())
    reports = []
    monkeypatch.setattr(measurement, "persist_report", lambda report, role: reports.append(report))
    primary = FalseyError("falsey exception")

    def body():
        raise primary

    with pytest.raises(FalseyError) as raised:
        measurement.run_observed(body, "worker")
    assert raised.value is primary
    assert reports[0]["entry_exception_type"] == "FalseyError"


@pytest.mark.parametrize("failure", ["none", "body", "after_close"])
def test_original_batch_operation_transaction_and_late_deadline(tmp_path, monkeypatch, failure):
    # Actual _operation, read scope, SQL transaction and stop. Only the existing
    # small control fixture's historical roots/bytes are synthetic, not 57 ledgers.
    from test_v0222_presentation_batch_v2_controls import control

    import v0222_presentation_batch_v2 as core
    import v0222_scoped_cpu_worker as worker
    from v0220_provider_hardened import ProviderStop

    item = control.__wrapped__(tmp_path, monkeypatch)
    now = [core.time.time()]
    monkeypatch.setattr(core.time, "time", lambda: now[0])
    batch = core.Batch(item["root"], item["digest"])
    batch.initialize()
    probe = measurement.cpu_targets(worker.main)

    def body():
        with batch._operation("PREP") as (db, _scope, _state):
            db.execute("INSERT INTO meta VALUES ('synthetic_observation_marker','1')")
            if failure == "body":
                raise SyntheticDeadline("body")
            if failure == "after_close":
                now[0] = item["auth"]["expires_unix"] + 1

    probe.start()
    try:
        if failure == "none":
            body()
        else:
            with pytest.raises(SyntheticDeadline if failure == "body" else ProviderStop):
                body()
    finally:
        report = probe.finish()
    assert report["status"] == "OBSERVED", report
    span = next(row for row in report["records"] if row["kind"] == "generator")
    scope = next(row for row in report["records"] if row["kind"] == "scope")
    assert scope["parent_operation"] == span["id"]
    assert scope["close"]["end_wall_ns"] <= span["end_wall_ns"]
    assert (span["return_observation"] == "RETURNED") is (failure == "none")
    assert scope["status"] == (
        "CLOSED_FAILED" if failure == "body" else "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    )
    with batch.transaction() as db:
        marker = db.execute(
            "SELECT value FROM meta WHERE key='synthetic_observation_marker'"
        ).fetchone()
        stop = db.execute("SELECT value FROM meta WHERE key='stop'").fetchone()
    assert (marker is not None) is (failure == "none")
    assert (stop is not None) is (failure != "none")
