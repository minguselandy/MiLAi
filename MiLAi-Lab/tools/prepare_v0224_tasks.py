"""Freeze an externally reviewed public D plan after actual B/C qualification."""

import argparse
import time
from pathlib import Path


def prepare(plan_path, plan_sha256, bc_path, bc_sha256, *, d1_path=None, d1_sha256=None):
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0218_world import assert_public
    from v0220_evidence import LAB, dependencies, save, seal, sha
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_evidence import verify_manifest
    from v0224_live_completion_batch import ROOT as LIVE_ROOT
    from v0224_static_bundle import BundleLimits
    from v0224_task_batch import BC_STATUS, REVISION, ROOTS, Batch, require, validate_plan
    from v0224_verified_digest_batch import StaticAuthority
    from v0224_verified_digest_lineage import verify_lineage_r03
    from v0224_verified_digest_scope import BundleReadScope

    with AdmissionReadScope() as scope:
        plan = scope.read_json(plan_path, plan_sha256)
        stages = [stage for stage in ROOTS if stage in plan]
        require(len(stages) == 1, "EXACT_ONE_TASK_STAGE")
        stage = stages[0]
        validate_plan(plan, stage)
        root = ROOTS[stage]
        require(not root.exists() and not root.is_symlink(), "FRESH_TASK_ROOT_REQUIRED")
        bc = scope.read_json(bc_path, bc_sha256)
        require(
            bc.get("status") == BC_STATUS and bc.get("blocking_findings") == [] and bc.get("files"),
            "ACTUAL_COMPLETE_BC_REQUIRED",
        )
        files = dict(bc["files"])
        for name, expected in files.items():
            scope.read_bytes(Path(name), expected)
        binding_path = LIVE_ROOT / "execution-binding.json"
        binding = scope.read_json(binding_path, files[str(binding_path)])
        previous = verify_manifest(scope, LIVE_ROOT, binding["manifest.json"])
        authority = bc["static_authority"]
        require(authority == previous["contract"]["static_authority"], "BC_STATIC_AUTHORITY_DRIFT")
        if stage == "D2":
            require(
                d1_path is not None and d1_sha256 is not None,
                "ACTUAL_D1_ROOT_QUALIFICATION_REQUIRED",
            )
            d1 = scope.read_json(d1_path, d1_sha256)
            require(
                d1.get("status") == "D1_RECOVERY_ROOTS_QUALIFIED"
                and d1.get("blocking_findings") == []
                and d1.get("files")
                and {spec["root"] for spec in plan[stage]}.issubset(d1["qualified_roots"]),
                "ALL_NATURAL_ROOTS_REQUIRE_ACTUAL_RECOVERY_QUALIFICATION",
            )
            for name, expected in d1["files"].items():
                scope.read_bytes(Path(name), expected)
            files.update(d1["files"])
            files[str(d1_path)] = d1_sha256
        else:
            require(d1_path is None and d1_sha256 is None, "NO_UNRELATED_D1_CERTIFICATE")
        for spec in plan[stage]:
            source = spec["public_source"]
            public = scope.read_json(Path(source["path"]), source["sha256"])
            assert_public(public)
            files[source["path"]] = source["sha256"]
        files.update(previous["inputs"])
        files.update(previous["dependencies"])
        files.update(
            {
                str(LIVE_ROOT / "executed-source" / Path(name).relative_to(LAB)): expected
                for name, expected in previous["dependencies"].items()
            }
        )
        files.update({str(plan_path): plan_sha256, str(bc_path): bc_sha256})
        entries = [Path(name) for name in previous["dependencies"]]
        entries.extend(
            LAB / "tools" / name
            for name in (
                "v0224_task_batch.py",
                "v0224_task_provider.py",
                "v0224_natural_session.py",
                "v0224_recovery_session.py",
                "run_v0224_tasks.py",
                "prepare_v0224_tasks.py",
            )
        )
        entries.extend(
            LAB / "tests/unit" / name
            for name in (
                "test_v0224_task_batch.py",
                "test_v0224_task_provider.py",
                "test_v0224_natural_session.py",
                "test_v0224_recovery_session.py",
                "test_run_v0224_tasks.py",
            )
        )
        source_pins = {str(path): sha(path) for path in dependencies(entries)}
        for name, expected in {**files, **source_pins}.items():
            scope.read_bytes(Path(name), expected)
    static = StaticAuthority(
        Path(authority["bundle_path"]),
        authority["bundle_sha256"],
        Path(authority["receipt_path"]),
        authority["receipt_sha256"],
        BundleLimits(**authority["limits"]),
    )
    with BundleReadScope(**static.scope_arguments()) as scope:
        history = verify_lineage_r03(scope)
        # Fulfil executing-source/current-public fresh roles in this same scope.
        # The earlier independent AdmissionReadScope cannot satisfy its close.
        with scope.physical_reads():
            for name, expected in {**files, **source_pins}.items():
                scope.read_bytes(Path(name), expected)
    manifest = seal(root, entries=entries, inputs=[Path(name) for name in files], contract=plan)
    require(
        manifest["inputs"] == files and manifest["dependencies"] == source_pins,
        "PREPARATION_PIN_DRIFT",
    )
    issued = time.time()
    authorization = {
        "revision": REVISION,
        "root": str(root),
        "stages": ["PREP", stage],
        "issued_unix": issued,
        "expires_unix": issued + 36 * 3600,
        "cap": sum(spec["max_generations"] for spec in plan[stage]),
        "concurrency": 1,
        "episode_wall_seconds": 900 if stage == "D1" else 3600,
        "http_wall_seconds": 60,
        "auxiliary_http_seconds": 5,
        "output_cap": 4096,
        "raw_upper_bound": 65536,
        "automatic_retry": False,
        "new_unknown_stops_all": True,
        "device_calls_allowed": False,
        "historical": history,
        "accepted_unknown": history["unresolved_reservations"],
    }
    save(
        root / "contract.json",
        {
            "status": "D_TASK_ACTOR_CONTRACT_FROZEN",
            "root": str(root),
            "stage": stage,
            "plan": plan,
            "authorization": authorization,
            "manifest_sha256": sha(root / "manifest.json"),
            "bc_certificate": {"path": str(bc_path), "sha256": bc_sha256},
            "static_authority": authority,
            "control_files": files,
        },
    )
    contract_sha = sha(root / "contract.json")
    batch = Batch(root, contract_sha, static_authority=static)
    batch.initialize()
    result = {
        "status": "TASK_FIXTURE_PREPARED_NOT_STAGE_STARTED",
        "stage": stage,
        "contract_path": str(root / "contract.json"),
        "contract_sha256": contract_sha,
        "episodes": len(plan[stage]),
        "generation_cap": authorization["cap"],
        "http_cap": 2 * len(plan[stage]) + 2 * authorization["cap"],
        "model_requests": 0,
        "http_requests": 0,
        "direct_device_calls": 0,
    }
    save(root / "preparation-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("plan", "bc"):
        parser.add_argument("--" + field + "-path", required=True, type=Path)
        parser.add_argument("--" + field + "-sha256", required=True)
    parser.add_argument("--d1-path", type=Path)
    parser.add_argument("--d1-sha256")
    args = parser.parse_args()
    import json

    print(json.dumps(prepare(**vars(args))))


if __name__ == "__main__":
    main()
