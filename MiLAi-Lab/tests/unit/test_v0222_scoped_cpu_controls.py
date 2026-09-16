"""Real CPU constructor/authorization over synthetic pinned controls in children.

Each case installs the irreversible network guard in its own fresh Python
process before importing the replay stack. Only root selection and the pinned
synthetic lineage fixture are substituted. No _authorize, guard, manifest/plan
validator, acceptance method or real historical coordinator is replaced here.
This is neither a real 57-ledger replay nor a CPU timing/admission verdict.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _child_case(directory: Path, member: str, change: str) -> dict:
    # Called only by the guarded -c bootstrap below, never by the pytest parent.
    from test_v0222_presentation_batch_v2_controls import control, put

    import v0222_presentation_batch_v2 as core
    import v0222_scoped_cpu_batch as cpu
    from v0220_provider_hardened import ProviderStop
    from v0222_admission_read_scope import AdmissionReadError
    from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
    from v0222_scoped_evidence import ScopedEvidenceError

    require_cpu_network_guard()
    with pytest.MonkeyPatch.context() as patch:
        item = control.__wrapped__(directory, patch)
        root = item["root"]
        assert root == directory / "new"
        # Keep distinct synthetic live and CPU roots; neither is the real root.
        live_root = directory / "synthetic-live-root"
        patch.setattr(core, "ROOT", live_root)
        patch.setattr(cpu, "ROOT", live_root)
        patch.setattr(cpu, "CPU_ROOT", root)
        boundary = directory / "boundary"
        boundary_sha = put(boundary / "execution-binding.json", {"SYNTHETIC_BOUNDARY": True})
        patch.setattr(core, "BOUNDARY_ROOT", boundary)
        patch.setattr(core, "BOUNDARY_BINDING", boundary_sha)
        item["manifest"]["inputs"][str(boundary / "execution-binding.json")] = boundary_sha
        for name in ("PARENT_BINDING", "PRESENTATION_BINDING"):
            old_root = getattr(core, name.removesuffix("_BINDING") + "_ROOT")
            # The fixture already pinned these exact synthetic parent bytes.
            digest = item["manifest"]["inputs"][str(old_root / "execution-binding.json")]
            patch.setattr(core, name, digest)
        for name in (
            "PARENT_ROOT",
            "PARENT_BINDING",
            "PRESENTATION_ROOT",
            "PRESENTATION_BINDING",
            "BOUNDARY_ROOT",
            "BOUNDARY_BINDING",
        ):
            patch.setattr(cpu, name, getattr(core, name))
        history = item["auth"]["historical"]
        issued, expires = item["auth"]["issued_unix"], item["auth"]["expires_unix"]
        item["auth"].clear()
        item["auth"].update(
            cpu.make_cpu_authorization(root, issued=issued, expires=expires, history=history)
        )
        item["grant"].clear()
        item["grant"].update(cpu.cpu_authorization_source())
        item["plan"].update(
            {
                "coordinator_revision": cpu.CPU_REVISION,
                "execution_mode": CPU_MODE,
                "real_http_allowed": False,
                "device_calls_allowed": False,
                "mock_cost_is_not_real_cost": True,
                "parent_root": str(core.PARENT_ROOT),
                "parent_binding": core.PARENT_BINDING,
                "presentation_root": str(core.PRESENTATION_ROOT),
                "presentation_binding": core.PRESENTATION_BINDING,
                "boundary_root": str(core.BOUNDARY_ROOT),
                "boundary_binding": core.BOUNDARY_BINDING,
            }
        )
        expected_authorize = cpu.OfflineBatch._authorize
        assert expected_authorize.__module__ == "v0222_scoped_cpu_batch"
        if member in {"auth", "grant", "plan"}:
            value = item[member]
            if change == "missing_mode":
                del value["execution_mode"]
            elif change == "wrong_mode":
                value["execution_mode"] = "LIVE_HTTP_ONLY"
            elif change == "live_revision":
                value["coordinator_revision"] = core.COORDINATOR_REVISION
            elif change.startswith("int:"):
                field = change.split(":", 1)[1]
                value[field] = int(value[field])
            elif change == "live_contract":
                if member == "auth":
                    replacement = core.make_authorization(
                        live_root, issued=issued, expires=expires, history=history
                    )
                elif member == "grant":
                    replacement = core.authorization_source()
                else:
                    replacement = {
                        key: value
                        for key, value in item["plan"].items()
                        if key
                        not in {
                            "execution_mode",
                            "real_http_allowed",
                            "device_calls_allowed",
                            "mock_cost_is_not_real_cost",
                        }
                    }
                    replacement["coordinator_revision"] = core.COORDINATOR_REVISION
                value.clear()
                value.update(replacement)
            else:
                raise AssertionError("Unknown enumerated case")
        digest = item["seal"]()
        if member == "drift":
            if change in {"source", "copied"}:
                put(item[change], b"changed = True\n")
            elif change == "input":
                put(Path(next(iter(item["manifest"]["inputs"]))), b"changed")
            elif change == "binding":
                put(root / "execution-binding.json", {})
            elif change in {"authorization.json", "authorization-source.json", "manifest.json"}:
                put(root / change, {})
            else:
                raise AssertionError("Unknown drift case")
        if member == "root":
            root = live_root
        if member in {"positive", "memory"}:
            batch = cpu.OfflineBatch(root, digest)
            assert batch._authorize.__func__ is expected_authorize
            assert item["calls"] and all(
                scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS" for scope in item["calls"]
            )
            assert not batch.path.exists()
            if member == "memory":
                getattr(batch, change)["execution_mode"] = "LIVE_HTTP_ONLY"
                with pytest.raises(ProviderStop, match="IN_MEMORY"):
                    batch.authorize("PREP")
                assert not batch.path.exists()
                outcome = "IN_MEMORY_REJECTED"
            else:
                batch.initialize()
                snapshot = batch.snapshot()
                assert snapshot["stop"] is None and len(snapshot["episodes"]) == 40
                assert all(
                    row["status"] == "PENDING" and row["pid"] is None
                    for row in snapshot["episodes"]
                )
                with batch.transaction() as db:
                    assert db.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0
                    assert db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
                    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
                assert not list(root.glob("live-launch-*.json"))
                assert batch.auth["execution_mode"] == batch.plan["execution_mode"] == CPU_MODE
                assert (
                    batch.auth["real_http_allowed"] is batch.auth["device_calls_allowed"] is False
                )
                assert batch.auth["mock_cost_is_not_real_cost"] is True
                assert len({id(scope) for scope in item["calls"]}) == len(item["calls"])
                assert all(
                    scope.stats["first_reads"] == scope.stats["closing_reads"] > 8
                    for scope in item["calls"]
                )
                outcome = "CONSTRUCTED_INITIALIZED_40_PENDING_NO_LAUNCH"
        else:
            with pytest.raises((ProviderStop, AdmissionReadError, ScopedEvidenceError)) as caught:
                cpu.OfflineBatch(root, digest)
            assert not (item["root"] / "batch.sqlite").exists()
            assert not (live_root / "batch.sqlite").exists()
            assert not list(item["root"].glob("live-launch-*.json"))
            outcome = type(caught.value).__name__
        require_cpu_network_guard()
        # Real Python audit dispatch confirms guard is still effective; no socket.
        with pytest.raises(RuntimeError, match="CPU_REPLAY_SOCKET_FORBIDDEN"):
            sys.audit("socket.v0222_cpu_controls_postcheck")
        return {
            "member": member,
            "change": change,
            "outcome": outcome,
            "synthetic_root_and_lineage": True,
            "real_constructor_and_authorize": True,
            "guard_live_in_child": True,
        }


CASES = [
    ("positive", "none"),
    *[
        (member, change)
        for member in ("auth", "grant", "plan")
        for change in (
            "missing_mode",
            "wrong_mode",
            "live_revision",
            "int:real_http_allowed",
            "int:device_calls_allowed",
            "int:mock_cost_is_not_real_cost",
            "live_contract",
        )
    ],
    *[
        ("drift", change)
        for change in (
            "source",
            "copied",
            "input",
            "binding",
            "authorization.json",
            "authorization-source.json",
            "manifest.json",
        )
    ],
    *[("memory", member) for member in ("auth", "plan", "binding")],
    ("root", "live"),
]


@pytest.mark.parametrize("member,change", CASES)
def test_real_cpu_constructor_and_authorization_in_fresh_guarded_process(tmp_path, member, change):
    lab = Path(__file__).resolve().parents[2]
    code = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from v0222_scoped_cpu_guard import enable_cpu_network_guard
enable_cpu_network_guard()
sys.path.insert(0, sys.argv[2])
from test_v0222_scoped_cpu_controls import _child_case
print(json.dumps(_child_case(Path(sys.argv[3]), sys.argv[4], sys.argv[5]), sort_keys=True))
"""
    result = subprocess.run(  # noqa: S603 -- Fixed local code and enumerated synthetic cases.
        [
            sys.executable,
            "-c",
            code,
            str(lab / "tools"),
            str(lab / "tests/unit"),
            str(tmp_path),
            member,
            change,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=lab,
    )
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["member"] == member and record["change"] == change
    assert record["real_constructor_and_authorize"] is record["guard_live_in_child"] is True
    assert record["synthetic_root_and_lineage"] is True
    # The parent never installs the irreversible guard; each child owns it.
    sys.audit("socket.v0222_cpu_controls_parent_not_guarded")
