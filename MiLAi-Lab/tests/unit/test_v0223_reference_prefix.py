"""Synthetic fixtures through the actual original Session; zero provider action."""

import hashlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0220_action_adapter import public, put

from v0220_session import Session
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_references import ReferenceProvider
from v0223_coarse_observation import CoarseObserver, installed
from v0223_reference_prefix import run_reference_prefix


def factory(path, *, callback=lambda: None, stop_callback=lambda reason: None):
    raw = b'{"frozen":1}'
    path.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    action = put()

    class Batch:
        def __init__(self):
            with AdmissionReadScope() as scope:
                scope.read_json(path, pin)
            self.plan = {
                "P4": [
                    {
                        "id": "TEST_ONLY_prefix",
                        "stage": "P4",
                        "scope": "TEST_ONLY_scope",
                        "actions": [action],
                        "initial_state_sha256": "OLD",
                        "intent": {
                            "instruction": "Write then read and finish",
                            "ordered_writes": [
                                {
                                    "object_id": action["arguments"]["object_id"],
                                    "data": action["arguments"]["data"],
                                }
                            ],
                        },
                    }
                ]
            }

        def stop(self, reason):
            return stop_callback(reason)

        def _authorize(self):
            pass

        @contextmanager
        def _operation(self, stage):
            assert stage == "PREP"
            with AdmissionReadScope() as scope:
                scope.read_json(path, pin)
                callback()
                yield

    return Batch


def test_original_prefix_u_s_coverage_and_restore(tmp_path):
    old_run, old_generate, old_close = (
        Session.run,
        ReferenceProvider.generate,
        AdmissionReadScope._close,
    )
    results = []
    for mode in (False, True):
        Batch = factory(tmp_path / "source.json")
        observer = CoarseObserver("synthetic", enabled=mode)
        with installed(observer, batch_class=Batch), observer.span("execution"):
            result = run_reference_prefix(
                Batch, tmp_path / str(mode), public_loader=lambda _: public()
            )
        assert result["terminal_status"] == "PREFIX_REACHED_NOT_REFERENCE_PASS"
        assert result["scope_count"] == 5
        assert result["coverage"]["runtime_guard_count"] == 2
        assert len(result["runtime_guard_wall_ns"]) == 2
        assert result["session_result"]["completed_turns"] == 0
        assert not result["deadline_hit"]
        assert result["batch_stop"]["status"] == "NOT_REQUESTED_INTENTIONAL_DIAGNOSTIC_CUTOFF"
        assert not list((tmp_path / str(mode)).glob("request-*"))
        assert observer.report()["status"] == "COMPLETE_SPANS"
        results.append(result)
    assert results[0]["coverage"] == results[1]["coverage"]
    assert Session.run is old_run
    assert ReferenceProvider.generate is old_generate
    assert AdmissionReadScope._close is old_close


def test_real_session_deadline_check_wins_over_prefix(tmp_path, monkeypatch):
    import v0220_session

    current = [0.0]
    guards = [0]

    def advance_after_two_runtime_guards():
        guards[0] += 1
        if guards[0] == 4:
            current[0] = 61.0

    # Controlled semantic clock only; never used in a performance measurement.
    monkeypatch.setattr(v0220_session.time, "monotonic", lambda: current[0])
    Batch = factory(tmp_path / "source.json", callback=advance_after_two_runtime_guards)
    result = run_reference_prefix(Batch, tmp_path / "deadline", public_loader=lambda _: public())
    assert result["terminal_status"] == "ORIGINAL_SESSION_DEADLINE"
    assert result["deadline_hit"]
    assert result["batch_stop"] == {
        "status": "STOP_RECORDED",
        "reason": "REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET",
    }
    assert not result["prefix_marker"]
    assert result["coverage"]["generate_boundary_count"] == 0
    assert result["coverage"]["runtime_guard_count"] == 2


def test_setup_failure_is_not_prefix_completion(tmp_path):
    def failed():
        raise ValueError("SYNTHETIC_GUARD_FAILURE")

    Batch = factory(tmp_path / "source.json", callback=failed)
    result = run_reference_prefix(Batch, tmp_path / "failed", public_loader=lambda _: public())
    assert result["terminal_status"] == "ORIGINAL_PATH_STOP"
    assert result["session_result"] is None
    assert not result["prefix_marker"]
    assert result["coverage"]["guards"][0]["status"] == "UNWOUND"


def test_profile_rejected_before_stack_import(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "getprofile", lambda: object())
    with pytest.raises(RuntimeError, match="UNPROFILED_UNTRACED"):
        run_reference_prefix(lambda: None, tmp_path)


def test_original_failure_preserved_when_batch_stop_fails(tmp_path):
    primary = ValueError("SYNTHETIC_GUARD_FAILURE")
    stopped = []

    def fail_guard():
        raise primary

    def fail_stop(reason):
        stopped.append(reason)
        raise OSError("SYNTHETIC_STOP_FAILURE")

    Batch = factory(tmp_path / "source.json", callback=fail_guard, stop_callback=fail_stop)
    result = run_reference_prefix(Batch, tmp_path / "failed", public_loader=lambda _: public())
    assert result["terminal_status"] == "ORIGINAL_PATH_STOP"
    assert result["outer_exception_type"] == "ValueError"
    assert result["outer_reason"] == "SYNTHETIC_GUARD_FAILURE"
    assert stopped == ["ValueError"]
    assert result["batch_stop"]["status"] == "SECONDARY_STOP_FAILURE"
    assert result["batch_stop"]["exception_type"] == "OSError"
    assert primary.__notes__ == ["SECONDARY_STOP_FAILURE: OSError"]


def test_constructor_failure_has_no_batch_to_stop(tmp_path):
    def fail_constructor():
        raise ValueError("SYNTHETIC_CONSTRUCTOR_FAILURE")

    result = run_reference_prefix(fail_constructor, tmp_path)
    assert result["terminal_status"] == "ORIGINAL_PATH_STOP"
    assert result["batch_stop"] == {"status": "NO_CONSTRUCTED_BATCH"}


def test_full_prefix_runs_original_materializer_55_scopes(tmp_path, monkeypatch):
    """Synthetic public fixture wiring; historical source auditor tested elsewhere."""
    import copy
    import json

    import prepare_v0222_presentation as materializer

    cases = tmp_path / "cases"
    (cases / "synthetic").mkdir(parents=True)
    (cases / "synthetic" / "public-initial.json").write_text(json.dumps(public()))
    monkeypatch.setattr(materializer, "CASES", cases)
    audited = []
    # Only the historic source lookup auditor needs a synthetic fixture seam;
    # original prepare_p3, reference layer validation and Session stay intact.
    monkeypatch.setattr(
        materializer,
        "validate_reference",
        lambda batch, row, spec: audited.append((row["episode"], spec["id"])),
    )
    stopped = []
    Base = factory(tmp_path / "source.json", stop_callback=stopped.append)

    class FullBatch(Base):
        def __init__(self):
            super().__init__()
            self.root = tmp_path / "batch"
            self.plan["P4"][0]["root"] = "synthetic"
            self.plan["P3"] = [
                {
                    "id": f"TEST_ONLY_p3_{index}",
                    "stage": "P3",
                    "root": "synthetic",
                    "scope": f"TEST_ONLY_scope_{index}",
                    "variant": "full",
                    "expected": put(),
                }
                for index in range(16)
            ]

        def spec(self, episode):
            return copy.deepcopy(
                next(row for stage in self.plan.values() for row in stage if row["id"] == episode)
            )

    result = run_reference_prefix(FullBatch, tmp_path / "unused", full_prefix=True)
    assert result["terminal_status"] == "PREFIX_REACHED_NOT_REFERENCE_PASS"
    assert result["scope_count"] == 55
    assert len(result["coverage"]["guards"]) == 54
    assert result["p3_reference_count"] == 16
    assert len(audited) == 16
    assert result["coverage"]["runtime_guard_count"] == 2
    assert result["batch_stop"]["status"] == "ORIGINAL_MATERIALIZER_DIAGNOSTIC_STOP"
    assert stopped == ["REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET"]
    assert (tmp_path / "batch" / "full-reference" / "preparation-error.json").is_file()
