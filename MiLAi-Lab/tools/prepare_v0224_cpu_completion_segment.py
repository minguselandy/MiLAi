"""Freeze only the missing P4 segment; never modify or rerun its predecessor."""

import argparse
import copy
import json
import os
import time
from pathlib import Path


def prepare(review_path, review_sha256):
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0220_evidence import LAB, dependencies, save, seal, sha
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_evidence import verify_manifest
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0224_cpu_completion_segment import (
        CLAIM_SECONDS,
        CPU_BASE,
        CPU_REVISION,
        CPU_ROOT,
        Batch,
        cpu_authorization_source,
        make_cpu_authorization,
        validate_predecessor,
    )
    from v0224_static_bundle import BundleLimits
    from v0224_verified_digest_batch import StaticAuthority
    from v0224_verified_digest_lineage import verify_lineage_r03
    from v0224_verified_digest_scope import BundleReadScope

    root = CPU_ROOT
    if root.exists() or root.is_symlink():
        raise ValueError("FRESH_COMPLETION_SEGMENT_ROOT_REQUIRED")
    lineage_path = CPU_BASE / "completion-segment-lineage.json"
    lineage_sha = "99247ca5971eba845dc01cf5a6cb104556a1bdffc04fb1ebbfd70ee8ccb2afac"
    policy = LAB / "studies/active/MILA_V0224_CPU_COMPLETION_SEGMENT_DELTA_20260913.md"
    with AdmissionReadScope() as scope:
        review = scope.read_json(review_path, review_sha256)
        assert review["blocking_findings"] == [] and review["files"]
        for name, expected in review["files"].items():
            scope.read_bytes(Path(name), expected)
        lineage = scope.read_json(lineage_path, lineage_sha)
        prior = Path(lineage["predecessor_root"])
        binding = scope.read_json(
            prior / "execution-binding.json", lineage["predecessor_binding_sha256"]
        )
        original = verify_manifest(scope, prior, binding["manifest.json"])
        plan = copy.deepcopy(original["contract"])
        plan.update(
            coordinator_revision=CPU_REVISION,
            purpose="K3_MISSING_P4_COMPLETION_SEGMENT",
            claim_seconds=CLAIM_SECONDS,
            completion_segment={"path": str(lineage_path), "sha256": lineage_sha},
            P3=[],
            P4=copy.deepcopy(plan["P4"][8:]),
        )
        assert len(plan["P4"]) == 16
        files = dict(lineage["files"])
        for mapping in (original["inputs"], original["dependencies"], review["files"]):
            for name, expected in mapping.items():
                assert name not in files or files[name] == expected
                files[name] = expected
        files.update(
            {
                str(lineage_path): lineage_sha,
                str(review_path): review_sha256,
                str(policy): sha(policy),
            }
        )
        entries = [Path(name) for name in original["dependencies"]]
        entries.extend(
            LAB / "tools" / name
            for name in (
                "v0224_cpu_completion_segment.py",
                "run_v0224_cpu_completion_segment.py",
                "prepare_v0224_cpu_completion_segment.py",
            )
        )
        entries.extend(
            LAB / "tests/unit" / name
            for name in (
                "test_v0224_cpu_completion_segment.py",
                "test_run_v0224_cpu_completion_segment.py",
            )
        )
        source_pins = {str(path): sha(path) for path in dependencies(entries)}
        for name, expected in {**files, **source_pins}.items():
            scope.read_bytes(Path(name), expected)
        authority = plan["static_authority"]
        static = StaticAuthority(
            Path(authority["bundle_path"]),
            authority["bundle_sha256"],
            Path(authority["receipt_path"]),
            authority["receipt_sha256"],
            BundleLimits(**authority["limits"]),
        )
    with BundleReadScope(**static.scope_arguments()) as scope:
        history = verify_lineage_r03(scope)
        validate_predecessor(scope, plan)
        with scope.physical_reads():
            for name, expected in {**files, **source_pins}.items():
                scope.read_bytes(Path(name), expected)
    manifest = seal(root, entries=entries, inputs=[Path(name) for name in files], contract=plan)
    assert manifest["inputs"] == files and manifest["dependencies"] == source_pins
    issued = int(time.time())
    save(
        root / "authorization.json",
        make_cpu_authorization(
            root,
            issued=issued,
            expires=issued + 36 * 3600,
            history=history,
        ),
    )
    save(root / "authorization-source.json", cpu_authorization_source())
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    binding_sha = sha(root / "execution-binding.json")
    with installed_transaction_fix():
        batch = Batch(root, binding_sha, static_authority=static)
        batch.initialize()
        # These are immutable predecessor artifact references, not new PASS episode rows.
        snapshot_pin = lineage["predecessor_snapshot"]
        with AdmissionReadScope() as scope:
            previous_sql = scope.read_json(Path(snapshot_pin["path"]), snapshot_pin["sha256"])
        with batch.transaction() as db:
            for artifact in previous_sql["artifacts"]:
                db.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?)",
                    (
                        artifact["name"],
                        artifact["path"],
                        artifact["sha256"],
                        artifact["dependencies"],
                    ),
                )
        observed = batch.snapshot()
        assert len(observed["episodes"]) == 16
        assert all(
            row["status"] == "PENDING" and row["pid"] is None for row in observed["episodes"]
        )
        assert not observed["stop"]
    contract_files = {**files, **source_pins}
    contract_files.update(
        {
            str(root / "executed-source" / Path(name).relative_to(LAB)): expected
            for name, expected in source_pins.items()
        }
    )
    for name in (
        "authorization.json",
        "authorization-source.json",
        "manifest.json",
        "execution-binding.json",
    ):
        contract_files[str(root / name)] = sha(root / name)
    contract = {
        "status": "CPU_COMPLETION_SEGMENT_FROZEN",
        "execution_revision": CPU_REVISION,
        "root": str(root),
        "binding_sha256": binding_sha,
        "static_authority": authority,
        "files": contract_files,
        "completion_segment": plan["completion_segment"],
        "priority_policy": {"path": str(policy), "sha256": sha(policy)},
    }
    save(root / "contract.json", contract)
    result = {
        "status": "CPU_COMPLETION_SEGMENT_PREPARED_NOT_EXECUTED",
        "pid": os.getpid(),
        "root": str(root),
        "contract_path": str(root / "contract.json"),
        "contract_sha256": sha(root / "contract.json"),
        "binding_sha256": binding_sha,
        "episodes": 16,
        "copied_episode_pass_rows": 0,
        "inherited_artifact_rows": len(previous_sql["artifacts"]),
        "real_model_requests": 0,
        "real_http_requests": 0,
    }
    save(root / "preparation-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-path", type=Path, required=True)
    parser.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.review_path, args.review_sha256)), flush=True)
