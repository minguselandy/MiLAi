"""Complete offline references for the sole B1 full/finish and conditional chain gate.

This entry currently creates offline proof only, never an authorization, launch,
HTTP request, or formal presentation instance. Frozen Batch callers can reuse the
same materializer once all implementation and independent reviews are complete.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from types import SimpleNamespace

from prepare_v0221_http_v2 import CASES
from prepare_v0222_full import resolve_p4_spec
from v0220_evidence import dependencies, read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_presentation_audit import validate_reference
from v0222_presentation_batch import PARENT_ROOT, REVISION, ROOT, verify_lineage
from v0222_presentation_references import prepare_p3, prepare_p4

OFFLINE_PARENT = ROOT.parent.parent / "v0222-presentation-offline"


def episode_specs() -> dict:
    """Keep the entire frozen original matrix; derive only new IDs/scopes/hash."""
    original = read(PARENT_ROOT / "manifest.json")["contract"]
    plan = {}
    for stage in ("P3", "P4"):
        plan[stage] = []
        for index, source in enumerate(original[stage], 1):
            spec = copy.deepcopy(source)
            spec["id"] = f"presentation-{stage.lower()}-{index:02d}"
            spec["scope"] = f"v0222-presentation-20260912-{spec['id']}"
            if stage == "P4":
                public = read(CASES / spec["root"] / "public-initial.json")
                spec, _ = resolve_p4_spec(spec, public)
            plan[stage].append(spec)
    return plan


def materialize_references(batch) -> dict:
    """Actual original Sessions/SQLite, followed by independent source reconstruction."""
    batch.authorize("PREP")
    directory = batch.root / "full-reference"
    directory.mkdir(parents=True, exist_ok=False)
    refs, resolutions = {"P3": [], "P4": []}, []
    sources = {}
    try:
        for stage in ("P3", "P4"):
            for spec in batch.plan[stage]:
                batch.authorize("PREP")
                source = CASES / spec["root"] / "public-initial.json"
                sources[str(source)] = sha(source)
                public = read(source)
                target = directory / stage / spec["id"]

                def guard():
                    batch.authorize("PREP")

                if stage == "P3":
                    rows = prepare_p3(target, spec, public, guard)
                else:
                    rows, resolved = prepare_p4(target, spec, public, guard)
                    if fingerprint(resolved["spec"]) != fingerprint(spec):
                        raise ProviderStop("P4_INITIAL_HASH_MUST_BE_RESOLVED_BEFORE_FREEZING")
                    resolutions.append(resolved)
                for row in rows:
                    validate_reference(batch, row, spec)
                refs[stage].extend(rows)
                print(f"offline {stage} {spec['id']}: {len(rows)} references verified", flush=True)
        if len(refs["P3"]) != 16 or len(refs["P4"]) != 80 or len(resolutions) != 24:
            raise ProviderStop("COMPLETE_16_PLUS_80_AND_24_CHAINS_REQUIRED")
        for source, expected in sources.items():
            if sha(Path(source)) != expected:
                raise ProviderStop("PUBLIC_SOURCE_CHANGED_DURING_OFFLINE_PREPARATION")
        paths = {}
        for stage, rows in refs.items():
            path = directory / (stage + "-reference-index.json")
            stage_directory = directory / stage
            save(
                path,
                {
                    "references": rows,
                    "files": {
                        **sources,
                        **{
                            str(p): sha(p)
                            for p in sorted(stage_directory.rglob("*"))
                            if p.is_file()
                        },
                    },
                },
            )
            paths[stage + "_references"] = path
        path = directory / "P4-resolved-specs.json"
        save(
            path,
            {
                "status": "DERIVED_INITIAL_HASHES_RESOLVED",
                "specs": [r["spec"] for r in resolutions],
                "diffs": [r["derived_hash_diff"] for r in resolutions],
                "files": sources,
            },
        )
        paths["P4_resolved_specs"] = path
        files = {str(p): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
        result = {
            "status": "REFERENCE_PREPARATION_PASS",
            "revision": REVISION,
            "selected_presentation": "B1",
            "selected_decoder": "D11",
            "P3_requests": 16,
            "P4_requests": 80,
            "P4_chains": 24,
            "isolated_offline_worlds": 40,
            "model_requests": 0,
            "http_requests": 0,
            "decoder_membership": "UNOBSERVED",
            "files": {**sources, **files},
        }
        result_path = directory / "prepared.json"
        save(result_path, result)
        for name in ("P4_resolved_specs", "P3_references", "P4_references"):
            batch.freeze_artifact(name, paths[name])
        batch.freeze_artifact("P_full_preparation", result_path, "REFERENCE_PREPARATION_PASS")
        return result
    except BaseException as exc:
        batch.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
        try:
            save(
                directory / "preparation-error.json",
                {
                    "status": "LOCAL_PREPARATION_NOT_MET",
                    "exception_type": type(exc).__name__,
                    "reason": str(exc),
                    "model_requests": 0,
                    "http_requests": 0,
                },
            )
        except Exception as report_error:
            print(
                f"offline failure report could not be saved: {type(report_error).__name__}",
                flush=True,
            )
        raise


def offline_proof(root: Path) -> dict:
    root = root.resolve()
    if not root.is_relative_to(OFFLINE_PARENT) or root == OFFLINE_PARENT or root.exists():
        raise ProviderStop("FRESH_DEDICATED_OFFLINE_PROOF_ROOT_REQUIRED")
    verify_lineage()
    plan = episode_specs()
    source_paths = {
        CASES / spec["root"] / "public-initial.json"
        for stage in ("P3", "P4")
        for spec in plan[stage]
    }
    inputs = {str(p): sha(p) for p in source_paths}
    code_paths = dependencies([Path(__file__).resolve()])
    code = {str(p): sha(p) for p in code_paths}
    root.mkdir(parents=True)
    save(root / "offline-plan.json", {"mode": "OFFLINE_ONLY_NOT_AUTHORIZATION", **plan})

    def guard(stage):
        if stage != "PREP":
            raise ProviderStop("OFFLINE_PROOF_HAS_NO_HTTP_OR_GENERATION_AUTHORITY")
        if any(sha(Path(p)) != h for p, h in inputs.items()):
            raise ProviderStop("OFFLINE_SOURCE_DRIFT")

    def record_artifact(name, path, status=None):
        value = read(path)
        if status is not None and value.get("status") != status:
            raise ProviderStop("OFFLINE_ARTIFACT_STATUS_MISMATCH")
        if any(sha(Path(p)) != h for p, h in value["files"].items()):
            raise ProviderStop("OFFLINE_ARTIFACT_DEPENDENCY_DRIFT")

    batch = SimpleNamespace(
        root=root,
        plan=plan,
        authorize=guard,
        freeze_artifact=record_artifact,
        stop=lambda reason: save(root / "offline-stopped.json", {"reason": reason}),
    )
    result = materialize_references(batch)
    # Concurrent implementation edits mean the proof must not pretend to bind a
    # stable code closure. Fail safely; never create or launch the formal Batch.
    if any(sha(Path(p)) != h for p, h in code.items()):
        raise ProviderStop("OFFLINE_CODE_CLOSURE_CHANGED_DURING_PROOF")
    proof = {
        **result,
        "mode": "OFFLINE_ONLY_NOT_AUTHORIZATION",
        "sources": code,
        "files": {
            **result["files"],
            str(root / "offline-plan.json"): sha(root / "offline-plan.json"),
        },
        "formal_instance_created": False,
    }
    save(root / "summary.json", proof)
    return proof


def revalidate_offline_proof(root: Path) -> dict:
    """Append current-auditor proof without modifying or regenerating any old World."""
    root = root.resolve()
    if not root.is_relative_to(OFFLINE_PARENT) or root == OFFLINE_PARENT:
        raise ProviderStop("DEDICATED_OFFLINE_PROOF_ROOT_REQUIRED")
    previous = read(root / "summary.json")
    if previous.get("mode") != "OFFLINE_ONLY_NOT_AUTHORIZATION":
        raise ProviderStop("OFFLINE_REFERENCE_PROOF_REQUIRED")
    files = {**previous["files"], str(root / "summary.json"): sha(root / "summary.json")}
    if any(sha(Path(p)) != h for p, h in files.items()):
        raise ProviderStop("OFFLINE_REFERENCE_PROOF_DRIFT")
    plan = read(root / "offline-plan.json")
    expected = episode_specs()
    if any(fingerprint(plan[stage]) != fingerprint(expected[stage]) for stage in ("P3", "P4")):
        raise ProviderStop("OFFLINE_PLAN_NOT_COMPLETE_CURRENT_ORIGINAL_MATRIX")
    code = {str(p): sha(p) for p in dependencies([Path(__file__).resolve()])}
    batch = SimpleNamespace(root=root, plan=plan)
    counts = {}
    for stage, total in (("P3", 16), ("P4", 80)):
        rows = read(root / "full-reference" / (stage + "-reference-index.json"))["references"]
        specs = {s["id"]: s for s in plan[stage]}
        positions = [
            (s["id"], i)
            for s in plan[stage]
            for i in range(1, 2 if stage == "P3" else len(s["actions"]) + 3)
        ]
        if len(rows) != total or [(r["episode"], r["turn"]) for r in rows] != positions:
            raise ProviderStop("COMPLETE_ORDERED_OFFLINE_REFERENCE_MATRIX_REQUIRED")
        for row in rows:
            validate_reference(batch, row, specs[row["episode"]])
        counts[stage] = len(rows)
        print(
            f"current independent auditor revalidated {stage}: {len(rows)} references", flush=True
        )
    if any(sha(Path(p)) != h for p, h in {**files, **code}.items()):
        raise ProviderStop("OFFLINE_REVALIDATION_SOURCE_OR_EVIDENCE_DRIFT")
    result = {
        "status": "CURRENT_AUDITOR_FULL_REFERENCE_PASS",
        "mode": "OFFLINE_ONLY_NOT_AUTHORIZATION",
        "P3_requests": counts["P3"],
        "P4_requests": counts["P4"],
        "P4_chains": 24,
        "model_requests": 0,
        "http_requests": 0,
        "new_worlds_created": 0,
        "files": files,
        "sources": code,
    }
    save(root / "current-auditor-revalidation.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline-root", type=Path)
    mode.add_argument("--revalidate-root", type=Path)
    args = parser.parse_args()
    outcome = (
        offline_proof(args.offline_root)
        if args.offline_root
        else revalidate_offline_proof(args.revalidate_root)
    )
    print({k: v for k, v in outcome.items() if k not in {"files", "sources"}})
