"""CPU sealer component tests, not actual lineage/Batch or instance admission.

All created roots and sources are synthetic temporary directories. Scope reads,
dependency discovery, source copying, hashing and append-only evidence saves are
real. Historical selection, authorization data and the final Batch initializer
are explicit fixtures; separate fresh children check the actual network guard.
No actual CPU_ROOT, HTTP, GPU or stage launch is used.
"""

import ast
import copy
import inspect
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import run_v0222_scoped_cpu_seal as bootstrap
import seal_v0222_scoped_cpu as module
import v0220_evidence as evidence
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SYNTHETIC_CPU_SEAL_MUST_NOT_USE_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    lab, root = tmp_path / "lab", tmp_path / "CPU_TEST_ONLY"
    for directory in (lab / "tools", lab / "tests/unit", lab / "src/milai_lab/nested"):
        directory.mkdir(parents=True)
    source = lab / "tools/entry.py"
    source.write_text("import dependency\n")
    dependency = lab / "tools/dependency.py"
    dependency.write_text("VALUE = 1\n")
    test = lab / "tests/unit/test_entry.py"
    test.write_text("TEST_ONLY = True\n")
    helpers = [
        lab / "tests/unit" / name
        for name in (
            "test_v0222_presentation_batch_v2_controls.py",
            "test_v0222_presentation_runner_v2.py",
        )
    ]
    for helper in helpers:
        helper.write_text("SYNTHETIC_TEST_HELPER = True\n")
    package_sources = [
        lab / "src/milai_lab/__init__.py",
        lab / "src/milai_lab/nested/__init__.py",
        lab / "src/milai_lab/nested/component.py",
    ]
    for path in package_sources:
        path.write_text("SYNTHETIC_LOCAL_PACKAGE = True\n")
    for name in ("pyproject.toml", "uv.lock"):
        (lab / name).write_text("# synthetic source metadata\n")
    monkeypatch.setattr(module, "LAB", lab)
    monkeypatch.setattr(evidence, "LAB", lab)
    monkeypatch.setattr(module, "CPU_ROOT", root)
    monkeypatch.setattr(module, "ENTRY_NAMES", ("entry.py",))
    monkeypatch.setattr(module, "TEST_NAMES", ("test_entry.py", *(p.name for p in helpers)))
    calls, scopes, instances = [], [], []
    monkeypatch.setattr(module, "require_cpu_network_guard", lambda: calls.append("guard"))

    class ObservedScope(AdmissionReadScope):
        def __init__(self):
            super().__init__()
            scopes.append(self)

    monkeypatch.setattr(module, "AdmissionReadScope", ObservedScope)
    pins = {}
    for name, constant in (
        ("inventory.json", "INVENTORY"),
        ("launch-review.json", "LAUNCH_REVIEW"),
        ("index.json", "EVIDENCE_INDEX"),
    ):
        path = tmp_path / name
        evidence.save(path, {"TEST_ONLY": name})
        pins[str(path)] = evidence.sha(path)
        monkeypatch.setattr(module, constant + "_PATH", path)
        monkeypatch.setattr(module, constant + "_SHA256", evidence.sha(path))
    history = {
        "TEST_ONLY_NOT_REAL_HISTORY": True,
        "sources": [{"path": str(tmp_path / f"synthetic-history-{i}")} for i in range(57)],
    }

    def lineage(scope):
        calls.append("lineage")
        for name, digest in pins.items():
            scope.read_bytes(Path(name), digest)
        return copy.deepcopy(history)

    monkeypatch.setattr(module, "verify_lineage", lineage)
    monkeypatch.setattr(module, "read_inventory", lambda scope: {"files": dict(pins)})
    matrix = {
        stage: [{"id": f"synthetic-{stage}-{i}"} for i in range(count)]
        for stage, count in (("P3", 16), ("P4", 24))
    }
    monkeypatch.setattr(module, "episode_specs", lambda scope: copy.deepcopy(matrix))

    def authorization(root, **kwargs):
        assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
        calls.append("authorization")
        return {"TEST_ONLY": True, "root": str(root), **kwargs}

    monkeypatch.setattr(module, "make_cpu_authorization", authorization)
    entries = [source, test, *helpers, *package_sources]
    source_pins = {str(path): evidence.sha(path) for path in evidence.dependencies(entries)}
    engineering, review = tmp_path / "engineering.json", tmp_path / "review.json"
    evidence.save(
        engineering,
        {
            "status": "ENGINEERING_CHECKS_PASS",
            "checks": [
                {"command": command, "exit_code": 0}
                for command in sorted(module.ENGINEERING_COMMANDS)
            ],
            "files": source_pins,
        },
    )
    evidence.save(
        review,
        {
            "status": "CPU_REPLAY_IMPLEMENTATION_REVIEW_PASS",
            "root": str(root),
            "execution_mode": module.CPU_MODE,
            "review_is_not_user_consent": True,
            "real_http_allowed": False,
            "blocking_findings": [],
            "files": source_pins,
        },
    )

    class FixtureBatch:
        """Records initializer orchestration; does not pretend to authorize."""

        def __init__(self, directory, binding):
            calls.append("construct")
            assert directory == root
            assert evidence.sha(root / "execution-binding.json") == binding
            evidence.validate(root)
            self.first_stop = None
            self.artifacts = []
            instances.append(self)

        def initialize(self):
            calls.append("initialize")

        def freeze_artifact(self, name, path, status):
            calls.append("freeze:" + name)
            self.artifacts.append((name, path, status))

        def stop(self, reason):
            calls.append("stop:" + reason)
            if self.first_stop is None:
                self.first_stop = reason

    monkeypatch.setattr(module, "OfflineBatch", FixtureBatch)
    return SimpleNamespace(
        root=root,
        lab=lab,
        engineering=engineering,
        review=review,
        calls=calls,
        scopes=scopes,
        instances=instances,
        source=source,
        dependency=dependency,
        helpers=helpers,
        package_sources=package_sources,
        source_pins=source_pins,
        pins=pins,
        history=history,
        fixture_batch=FixtureBatch,
    )


def rewrite(path, mutate):
    value = evidence.read(path)
    mutate(value)
    path.write_text(encoded(value))


def run(sample):
    return module.prepare(sample.root, sample.engineering, sample.review)


def test_complete_synthetic_seal_initializes_only_and_never_signs_scope(sample):
    result = run(sample)
    assert result["status"] == "CPU_INSTANCE_INITIALIZED_PREPARATION_AND_SCOPE_REVIEW_REQUIRED"
    assert result["model_requests"] == result["http_requests"] == 0
    assert result["model_capability_or_live_admission"] is False
    assert (result["P3"], result["P4"], result["Memory"]) == (
        "NOT_STARTED",
        "NOT_TRIGGERED",
        "NOT_ADMITTED",
    )
    manifest = evidence.read(sample.root / "manifest.json")
    assert manifest["dependencies"] == sample.source_pins
    for path in [*sample.helpers, *sample.package_sources]:
        assert manifest["dependencies"][str(path)] == evidence.sha(path)
        copied = sample.root / "executed-source" / path.relative_to(sample.lab)
        assert copied.read_bytes() == path.read_bytes()
    assert manifest["contract"]["historical_paths"] == [
        row["path"] for row in sample.history["sources"]
    ]
    assert manifest["contract"]["future_recovery_task_memory"] == "NOT_ADMITTED_BY_THIS_INSTANCE"
    assert len(manifest["contract"]["P3"]) == 16
    assert len(manifest["contract"]["P4"]) == 24
    assert [row[0] for row in sample.instances[0].artifacts] == ["engineering_checks"]
    assert not (sample.root / "scope-review.json").exists()
    assert not (sample.root / "full-reference").exists()
    assert not (sample.root / "episodes").exists()
    assert not list(sample.root.glob("*launch*"))
    assert sample.calls == [
        "guard",
        "lineage",
        "authorization",
        "construct",
        "initialize",
        "freeze:engineering_checks",
    ]


@pytest.mark.parametrize("value", [False, True, 0.0, "0", 1, None])
def test_engineering_exit_requires_exact_integer_zero(sample, value):
    rewrite(sample.engineering, lambda v: v["checks"][0].update(exit_code=value))
    with pytest.raises(ProviderStop, match="ALL_SIX_TERMINAL"):
        run(sample)
    assert "authorization" not in sample.calls and not sample.root.exists()


@pytest.mark.parametrize("change", ["missing", "duplicate", "unrelated", "empty_files", "stale"])
def test_engineering_requires_six_commands_and_complete_current_closure(sample, change):
    def mutate(value):
        if change == "missing":
            value["checks"].pop()
        elif change == "duplicate":
            value["checks"][0] = value["checks"][1]
        elif change == "unrelated":
            value["checks"][0]["command"] = "echo TEST_ONLY"
        elif change == "empty_files":
            value["files"] = {}
        else:
            value["files"].pop(str(sample.dependency))

    rewrite(sample.engineering, mutate)
    with pytest.raises(ProviderStop):
        run(sample)
    assert not sample.root.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "PASS"),
        ("root", "/wrong/root"),
        ("execution_mode", "LIVE_HTTP_ONLY"),
        ("review_is_not_user_consent", 1),
        ("real_http_allowed", 0),
        ("real_http_allowed", True),
        ("blocking_findings", ["pending"]),
        ("blocking_findings", None),
        ("files", {}),
    ],
)
def test_review_must_be_explicit_complete_cpu_only(sample, field, value):
    rewrite(sample.review, lambda v: v.update({field: value}))
    with pytest.raises(ProviderStop):
        run(sample)
    assert not sample.root.exists()


def test_partial_review_source_closure_is_rejected(sample):
    rewrite(sample.review, lambda v: v["files"].pop(str(sample.dependency)))
    with pytest.raises(ProviderStop, match="CURRENT_COMPLETE_CPU_SOURCE_CLOSURE"):
        run(sample)
    assert not sample.root.exists()


def test_fixed_test_entries_explicitly_include_both_transitive_helpers():
    assert {
        "test_v0222_presentation_batch_v2_controls.py",
        "test_v0222_presentation_runner_v2.py",
    } <= set(module.TEST_NAMES)


@pytest.mark.parametrize("mode", ["all_sources", "root_init_only"])
def test_missing_local_package_rejected_before_evidence_reads(sample, mode):
    paths = sample.package_sources if mode == "all_sources" else sample.package_sources[:1]
    for path in paths:
        path.unlink()  # Only enumerated synthetic files created by this fixture.
    with pytest.raises(ProviderStop, match="COMPLETE_LOCAL_CPU_PACKAGE_SOURCES_REQUIRED"):
        run(sample)
    assert not sample.scopes and not sample.root.exists()


@pytest.mark.parametrize("record", ["engineering", "review"])
@pytest.mark.parametrize(
    "member", ["package", "nested_package", "controls_helper", "runner_helper"]
)
def test_review_and_engineering_each_cover_package_and_helper_sources(sample, record, member):
    path = {
        "package": sample.package_sources[0],
        "nested_package": sample.package_sources[-1],
        "controls_helper": sample.helpers[0],
        "runner_helper": sample.helpers[1],
    }[member]
    rewrite(getattr(sample, record), lambda value: value["files"].pop(str(path)))
    with pytest.raises(ProviderStop, match="CURRENT_COMPLETE_CPU_SOURCE_CLOSURE_REQUIRED"):
        run(sample)
    assert "authorization" not in sample.calls and not sample.root.exists()


@pytest.mark.parametrize("kind", ["wrong", "existing", "alias", "parent_traversal"])
def test_root_must_be_fresh_exact_canonical(sample, monkeypatch, kind):
    root = sample.root
    if kind == "wrong":
        root = root.parent / "wrong"
    elif kind == "existing":
        root.mkdir()
    elif kind == "alias":
        alias = root.parent / "alias"
        alias.symlink_to(root.parent, target_is_directory=True)
        root = alias / root.name
        monkeypatch.setattr(module, "CPU_ROOT", root)
    else:
        root = root.parent / "missing" / ".." / root.name
        monkeypatch.setattr(module, "CPU_ROOT", root)
    with pytest.raises(ProviderStop, match="ONE_FRESH_CANONICAL_CPU_INSTANCE"):
        module.prepare(root, sample.engineering, sample.review)
    assert not sample.scopes


def test_missing_entry_or_test_rejected_before_evidence_reads(sample, monkeypatch):
    monkeypatch.setattr(module, "TEST_NAMES", ("not-created.py",))
    with pytest.raises(ProviderStop, match="ALL_CPU_ENTRYPOINTS_AND_TESTS_REQUIRED"):
        run(sample)
    assert not sample.scopes and not sample.root.exists()


def test_conflicting_file_pins_are_not_silently_overwritten():
    target = {"file": "a"}
    with pytest.raises(ProviderStop, match="CONFLICTING_INPUT_PIN"):
        module._merge(target, {"file": "b"})
    assert target == {"file": "a"}


@pytest.mark.parametrize("kind", ["source", "input"])
def test_mutation_after_scope_close_is_rejected_before_batch(sample, monkeypatch, kind):
    original = module.make_cpu_authorization

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        path = sample.dependency if kind == "source" else Path(next(iter(sample.pins)))
        path.write_text("CHANGED = True\n")
        return result

    monkeypatch.setattr(module, "make_cpu_authorization", change)
    reason = (
        "SOURCE_CLOSURE_CHANGED_AFTER_REVIEW"
        if kind == "source"
        else "INPUT_CHANGED_AFTER_SCOPE_CLOSE"
    )
    with pytest.raises(ProviderStop, match=reason):
        run(sample)
    assert "construct" not in sample.calls
    assert (sample.root / "manifest.json").exists()  # Failed partial evidence is retained.
    assert not (sample.root / "execution-binding.json").exists()


def test_drift_during_scope_body_is_caught_by_mandatory_close(sample, monkeypatch):
    original = module.episode_specs

    def drift(scope):
        result = original(scope)
        sample.dependency.write_text("VALUE = 2\n")
        return result

    monkeypatch.setattr(module, "episode_specs", drift)
    with pytest.raises(AdmissionReadError):
        run(sample)
    assert sample.scopes[-1].status == "CLOSED_FAILED"
    assert not sample.root.exists()


@pytest.mark.parametrize("mode", ["omit", "extra"])
def test_second_discovery_must_match_reviewed_source_closure(sample, monkeypatch, mode):
    original = evidence.dependencies
    extra = sample.lab / "tools/not_reviewed.py"
    extra.write_text("NOT_REVIEWED = True\n")

    def second_discovery(entries):
        paths = original(entries)
        return [p for p in paths if p != sample.dependency] if mode == "omit" else [*paths, extra]

    # Only seal's second traversal changes; first scoped traversal remains real.
    # This deterministically isolates a discovery/restore window, no repo edits.
    monkeypatch.setattr(evidence, "dependencies", second_discovery)
    with pytest.raises(ProviderStop, match="SOURCE_CLOSURE"):
        run(sample)
    assert "construct" not in sample.calls


def test_real_temporary_source_change_during_discovery_then_restore_is_rejected(
    sample, monkeypatch
):
    original = evidence.dependencies
    original_bytes = sample.source.read_bytes()

    def changed_scan(entries):
        sample.source.write_text("# dependency import temporarily absent\n")
        try:
            result = original(entries)
            assert sample.dependency not in result
        finally:
            sample.source.write_bytes(original_bytes)
        return result

    monkeypatch.setattr(evidence, "dependencies", changed_scan)
    with pytest.raises(ProviderStop, match="SOURCE_CLOSURE"):
        run(sample)
    assert sample.source.read_bytes() == original_bytes
    assert "construct" not in sample.calls


def test_same_source_path_different_sealed_hash_rejected_before_constructor(sample, monkeypatch):
    original = module.seal

    def different_hash(*args, **kwargs):
        manifest = original(*args, **kwargs)
        manifest["dependencies"][str(sample.source)] = "0" * 64
        (sample.root / "manifest.json").write_text(encoded(manifest))
        return manifest

    monkeypatch.setattr(module, "seal", different_hash)
    with pytest.raises(ProviderStop, match="SOURCE_CLOSURE"):
        run(sample)
    assert "construct" not in sample.calls


@pytest.mark.parametrize("phase", ["construct", "initialize", "freeze", "result_save"])
def test_initializer_failures_stop_before_propagating_original(sample, monkeypatch, phase):
    marker = OSError("SYNTHETIC_FAILURE_" + phase)
    original_save = module.save
    stops = []

    class FailingBatch(sample.fixture_batch):
        def __init__(self, *args):
            if phase == "construct":
                raise marker
            super().__init__(*args)

        def initialize(self):
            super().initialize()
            if phase == "initialize":
                raise marker

        def freeze_artifact(self, *args):
            if phase == "freeze":
                raise marker
            return super().freeze_artifact(*args)

    def save(path, value):
        if phase == "result_save" and path.name == "cpu-instance-initialized.json":
            raise marker
        return original_save(path, value)

    def stop(root, binding, batch, exc):
        assert root == sample.root and evidence.sha(root / "execution-binding.json") == binding
        assert exc is marker
        stops.append((batch, exc))
        if batch is not None:
            batch.stop("ORIGINAL_STOP")
            batch.stop("SECONDARY_STOP")

    monkeypatch.setattr(module, "OfflineBatch", FailingBatch)
    monkeypatch.setattr(module, "save", save)
    monkeypatch.setattr(module, "stop_batch", stop)
    with pytest.raises(OSError) as caught:
        run(sample)
    assert caught.value is marker and len(stops) == 1
    if sample.instances:
        assert sample.instances[0].first_stop == "ORIGINAL_STOP"
    assert not (sample.root / "cpu-instance-initialized.json").exists()


@pytest.mark.parametrize("stop_raises", [False, True])
def test_actual_stop_helper_preserves_prior_stop_and_primary_failure(
    sample, monkeypatch, stop_raises
):
    import v0222_scoped_cpu_worker as worker

    monkeypatch.setattr(worker, "require_cpu_network_guard", lambda: None)
    marker = OSError("PRIMARY_INITIALIZATION_FAILURE")

    class Failure(sample.fixture_batch):
        def initialize(self):
            self.first_stop = "PREEXISTING_STOP"
            raise marker

        def stop(self, reason):
            if stop_raises:
                raise RuntimeError("SECONDARY_STOP_UNAVAILABLE")
            super().stop(reason)

    monkeypatch.setattr(module, "OfflineBatch", Failure)
    with pytest.raises(OSError) as caught:
        run(sample)
    assert caught.value is marker
    assert sample.instances[0].first_stop == "PREEXISTING_STOP"
    if stop_raises:
        assert "SECONDARY_STOP_FAILURE: RuntimeError" in marker.__notes__


def test_bootstrap_guard_precedes_sealer_import_and_has_no_stage_actions():
    body = ast.parse(inspect.getsource(bootstrap.main)).body[0].body
    assert body[0].module == "v0222_scoped_cpu_guard"
    assert body[1].value.func.id == "enable_cpu_network_guard"
    assert body[2].module == "seal_v0222_scoped_cpu"
    assert body[3].module == "v0222_scoped_cpu_observation"
    assert body[4].value.func.id == "run_observed"
    assert body[4].value.args[0].id == "seal_main"
    assert body[4].value.args[1].value == "seal"


@pytest.mark.parametrize("mode", ["unguarded", "help", "wrong_root"])
def test_fresh_child_entry_installs_guard_and_refuses_invalid_use(tmp_path, mode):
    lab = Path(__file__).resolve().parents[2]
    target = tmp_path / "NEVER_CREATED"
    if mode == "unguarded":
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from seal_v0222_scoped_cpu import prepare
try:
    prepare(Path(sys.argv[2]), Path('absent-engineering'), Path('absent-review'))
except RuntimeError as exc:
    assert str(exc) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
else:
    raise AssertionError('unguarded accepted')
"""
        command = [sys.executable, "-c", code, str(lab / "tools"), str(target)]
    else:
        command = [sys.executable, str(lab / "tools/run_v0222_scoped_cpu_seal.py")]
        command += (
            ["--help"]
            if mode == "help"
            else [
                "--root",
                str(target),
                "--engineering-checks",
                str(tmp_path / "absent"),
                "--implementation-review",
                str(tmp_path / "absent-review"),
            ]
        )
    result = subprocess.run(  # noqa: S603 -- Fixed local help/refusal child, no valid instance.
        command, capture_output=True, text=True, timeout=30, cwd=lab
    )
    if mode == "wrong_root":
        assert result.returncode != 0
        assert "ONE_FRESH_CANONICAL_CPU_INSTANCE_REQUIRED" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
    assert not target.exists()
