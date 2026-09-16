"""Prepare one fresh B/C fixture only after the actual functional Gate A.

This CPU-only entry preserves the full original matrix and immutable source
burden. It does not send HTTP, launch a stage, or approve its own scope.
"""

import argparse
import copy
import time
from pathlib import Path


def prepare(gate_path, gate_sha256):
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from v0220_evidence import LAB, dependencies, save, seal, sha
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_evidence import verify_manifest
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0224_k3_cpu_batch import CPU_ROOT
    from v0224_live_completion_batch import (
        GATE_A_STATUS,
        LIVE_MODE,
        LIVE_REVISION,
        ROOT,
        Batch,
        authorization_source,
        make_live_authorization,
    )
    from v0224_static_bundle import BundleLimits
    from v0224_verified_digest_batch import StaticAuthority

    gate_path = Path(gate_path)
    if ROOT.exists() or ROOT.is_symlink():
        raise ValueError("FRESH_LIVE_ROOT_REQUIRED")
    with AdmissionReadScope() as scope:
        gate = scope.read_json(gate_path, gate_sha256)
        assert gate["status"] == GATE_A_STATUS and gate["blocking_findings"] == []
        files = dict(gate["files"])
        for path, digest in files.items():
            scope.read_bytes(Path(path), digest)
        binding_path = CPU_ROOT / "execution-binding.json"
        binding = scope.read_json(binding_path, files[str(binding_path)])
        original = verify_manifest(scope, CPU_ROOT, binding["manifest.json"])
        plan = copy.deepcopy(original["contract"])
        gate_pin = {"path": str(gate_path), "sha256": gate_sha256}
        plan.update(
            coordinator_revision=LIVE_REVISION,
            execution_mode=LIVE_MODE,
            real_http_allowed=True,
            device_calls_allowed=False,
            gate_a=gate_pin,
        )
        for key in ("cpu_efficiency_gate_enforced", "mock_cost_is_not_real_cost", "purpose"):
            plan.pop(key, None)
        public_pins = original["inputs"]
        for stage in ("P3", "P4"):
            for index, spec in enumerate(plan[stage], 1):
                before = copy.deepcopy(spec)
                spec["id"] = f"livev1-bc-{stage.lower()}-{index:02d}"
                spec["scope"] = "v0224-completion-" + spec["id"]
                if stage == "P4":
                    public_path = CASES / spec["root"] / "public-initial.json"
                    public = scope.read_json(public_path, public_pins[str(public_path)])
                    resolved, _ = resolve_p4_spec(spec, public)
                    spec.update(resolved)
                allowed = (
                    {"id", "scope", "initial_state_sha256"} if stage == "P4" else {"id", "scope"}
                )
                assert {k: v for k, v in before.items() if k not in allowed} == {
                    k: v for k, v in spec.items() if k not in allowed
                }
        authority = gate["static_authority"]
        assert authority == plan["static_authority"]
        static = StaticAuthority(
            Path(authority["bundle_path"]),
            authority["bundle_sha256"],
            Path(authority["receipt_path"]),
            authority["receipt_sha256"],
            BundleLimits(**authority["limits"]),
        )
        engineering_pin = gate["engineering_checks"]
        assert files[engineering_pin["path"]] == engineering_pin["sha256"]
        engineering = scope.read_json(Path(engineering_pin["path"]), engineering_pin["sha256"])
        assert engineering["status"] == "ENGINEERING_CHECKS_PASS"
        files.update(original["inputs"])
        files.update(original["dependencies"])
        files.update(
            {
                str(CPU_ROOT / "executed-source" / Path(name).relative_to(LAB)): digest
                for name, digest in original["dependencies"].items()
            }
        )
        files[str(gate_path)] = gate_sha256
        entries = [Path(p) for p in original["dependencies"]]
        entries += [
            LAB / "tools" / name
            for name in (
                "v0224_live_completion_batch.py",
                "v0224_live_http.py",
                "run_v0224_live_completion.py",
                "prepare_v0224_live_completion.py",
            )
        ]
        entries.append(LAB / "tests/unit/test_v0224_live_completion.py")
        source_pins = {str(path): sha(path) for path in dependencies(entries)}
        for path, digest in {**files, **source_pins}.items():
            scope.read_bytes(Path(path), digest)
        history = scope.read_json(CPU_ROOT / "authorization.json", binding["authorization.json"])[
            "historical"
        ]
    manifest = seal(ROOT, entries=entries, inputs=[Path(p) for p in files], contract=plan)
    assert manifest["inputs"] == files and manifest["dependencies"] == source_pins
    issued = int(time.time())
    save(
        ROOT / "authorization.json",
        make_live_authorization(
            ROOT, issued=issued, expires=issued + 36 * 3600, history=history, gate_a=gate_pin
        ),
    )
    save(ROOT / "authorization-source.json", authorization_source())
    save(
        ROOT / "execution-binding.json",
        {
            name: sha(ROOT / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    digest = sha(ROOT / "execution-binding.json")
    with installed_transaction_fix():
        batch = Batch(
            ROOT, digest, static_authority=static, gate_a_path=gate_path, gate_a_sha256=gate_sha256
        )
        batch.initialize()
        save(ROOT / "engineering-checks.json", engineering)
        batch.freeze_artifact(
            "engineering_checks", ROOT / "engineering-checks.json", "ENGINEERING_CHECKS_PASS"
        )
    result = {
        "status": "LIVE_FIXTURE_PREPARED_NOT_HTTP_ADMISSION",
        "root": str(ROOT),
        "binding_sha256": digest,
        "gate_a": gate_pin,
        "static_authority": authority,
        "files": {
            str(ROOT / name): sha(ROOT / name)
            for name in (
                "authorization.json",
                "authorization-source.json",
                "manifest.json",
                "execution-binding.json",
                "engineering-checks.json",
            )
        },
        "http_requests": 0,
        "model_requests": 0,
    }
    save(ROOT / "fixture-prepared.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-path", type=Path, required=True)
    parser.add_argument("--gate-a-sha256", required=True)
    args = parser.parse_args()
    print(prepare(args.gate_a_path, args.gate_a_sha256))
