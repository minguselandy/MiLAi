"""Seal the one reviewed residual-boundary design, without HTTP or business state."""

from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path

from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import LAB, read, save, seal, sha, validate
from v0220_wire_contract import encoded
from v0222_boundary_batch import (
    PARENT_BINDING,
    PARENT_ROOT,
    REVISION,
    ROOT,
    Batch,
    authorization_source,
    make_authorization,
)
from v0222_boundary_contract import SOURCE_EPISODES, audit_transform, transform
from v0222_string_contract import compile_contract


def episode_specs() -> list[dict]:
    parent = read(PARENT_ROOT / "manifest.json")["contract"]
    first = [next(s for s in parent["P3"] if s["id"] == ep) for ep in SOURCE_EPISODES]
    return [
        {
            "id": f"r1-{cold_index * 8 + root_index * 2 + condition_index + 1:02d}",
            "stage": "R1",
            "root": source["root"],
            "cold": cold_index + 1,
            "condition": condition,
            "source_episode": source["id"],
            "expected": copy.deepcopy(source["expected"]),
        }
        for cold_index, conditions in enumerate((("B0", "B1"), ("B1", "B0")))
        for root_index, source in enumerate(first)
        for condition_index, condition in enumerate(conditions)
    ]


def prepare(root: Path) -> dict:
    root = root.resolve()
    if root != ROOT:
        raise ValueError("ONE_REVIEWED_RESIDUAL_BOUNDARY_INSTANCE_ONLY")
    # All source data already belongs to the stopped, reviewed full experiment.
    parent_binding = read(PARENT_ROOT / "execution-binding.json")
    validate(PARENT_ROOT, manifest_sha256=parent_binding["manifest.json"])
    gate = read(PARENT_ROOT / "P2-gate.json")
    if gate["status"] != "G_P2_PASS":
        raise ValueError("FROZEN_D11_IMPLEMENTATION_REQUIRED")
    review = read(PARENT_ROOT / "P3-independent-review.json")
    inputs = {
        **gate["files"],
        **review["files"],
        str(PARENT_ROOT / "P2-gate.json"): sha(PARENT_ROOT / "P2-gate.json"),
        str(PARENT_ROOT / "P3-independent-review.json"): sha(
            PARENT_ROOT / "P3-independent-review.json"
        ),
    }
    if any(sha(Path(path)) != expected for path, expected in inputs.items()):
        raise ValueError("STOPPED_PARENT_EVIDENCE_DRIFT")
    issued = time.time()
    auth = make_authorization(root, issued=issued, expires=issued + 36 * 3600)
    specs = episode_specs()
    design = LAB / "docs/V0222_RESIDUAL_INTENT_BOUNDARY_DIAGNOSTIC_PLAN.md"
    inputs[str(design)] = sha(design)
    proof_path = PARENT_ROOT.parent / "boundary-contract-casproof-8AkfUG" / "summary.json"
    if sha(proof_path) != "1204334809c116a116ae6d05c0ff05ff75c67c8e5aee6b1b783f20b678be9b3b":
        raise ValueError("BOUNDARY_TRANSFORM_AND_CAS_PROOF_DRIFT")
    proof = read(proof_path)
    inputs[str(proof_path)] = sha(proof_path)
    inputs.update(proof["files"])
    for source in auth["historical"]["sources"]:
        inputs[source["path"]] = source["sha256"]
    if any(sha(Path(path)) != expected for path, expected in inputs.items()):
        raise ValueError("BOUNDARY_PROOF_OR_INPUT_DEPENDENCY_DRIFT")
    plan = {
        "revision": REVISION,
        "episodes": specs,
        "parent_root": str(PARENT_ROOT),
        "parent_binding": PARENT_BINDING,
        "historical_paths": [r["path"] for r in auth["historical"]["sources"]],
        "http_identity": {
            "endpoint": ENDPOINT,
            "model": MODEL,
            "context": 65536,
            "version": "0.27.1",
        },
        "selected_decoder": "D11",
        "conditions": ["B0", "B1"],
        "raw_cap": None,
        "reference_model_visible_scopes": "Unchanged original validate-only full request scopes",
        "repetition": "first8; paired same-root improvement triggers all reverse-condition8",
        "selector": "B1 exact8/8 and a same-root repeated B0 failure/B1 success; B0all8 no choice",
        "business_execution": False,
        "later_stages": "NOT_ALLOCATED_BY_THIS_DIAGNOSTIC",
    }
    entries = [
        LAB / "tools" / name
        for name in (
            "prepare_v0222_boundary.py",
            "preflight_v0222_boundary.py",
            "run_v0222_boundary.py",
            "v0222_boundary_worker.py",
        )
    ]
    entries += [
        LAB / "tests/unit" / name
        for name in (
            "test_v0222_boundary_contract.py",
            "test_v0222_boundary_batch.py",
            "test_v0222_boundary_transport.py",
            "test_v0222_boundary_integration.py",
            "test_v0222_boundary_preparation.py",
            "test_v0220_action_adapter.py",
        )
    ]
    seal(root, entries=entries, inputs=[Path(p) for p in inputs], contract=plan)
    save(root / "authorization-source.json", authorization_source())
    save(root / "authorization.json", auth)
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    binding = sha(root / "execution-binding.json")
    batch = Batch(root, binding)
    batch.initialize()
    references = []
    for spec in specs:
        source = (
            PARENT_ROOT / "full-reference/P3" / spec["source_episode"] / "request-01.canonical.json"
        )
        original = read(source)
        canonical = transform(original, spec["condition"])
        diff = audit_transform(original, canonical, spec["condition"])
        compiled = compile_contract(canonical["response_format"]["json_schema"]["schema"], "D11")
        raw = encoded(spec["expected"])
        compiled.validate_output(raw)
        row = {
            "episode": spec["id"],
            "stage": "R1",
            **{k: spec[k] for k in ("root", "cold", "condition", "source_episode")},
            "source_canonical": str(source),
            "source_canonical_sha256": sha(source),
            "schema_pair": compiled.manifest(),
        }
        for kind, value in (
            ("canonical", canonical),
            ("wire", compiled.prepare(canonical)),
            ("output", {"raw": raw}),
            ("diff", diff),
        ):
            path = root / "references" / (spec["id"] + "." + kind + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(encoded(value).encode())
            row[kind] = str(path)
        row["hashes"] = {
            kind: sha(Path(row[kind])) for kind in ("canonical", "wire", "output", "diff")
        }
        references.append(row)
    reference_path = root / "reference-index.json"
    save(
        reference_path,
        {
            "references": references,
            "files": {
                **{
                    row[kind]: row["hashes"][kind]
                    for row in references
                    for kind in ("canonical", "wire", "output", "diff")
                },
                **{row["source_canonical"]: row["source_canonical_sha256"] for row in references},
            },
        },
    )
    batch.freeze_artifact("references", reference_path)
    result = {
        "status": "PREPARED_NOT_REVIEWED_NOT_LIVE",
        "binding_sha256": binding,
        "positions": len(references),
        "source_roots": 4,
        "candidate_count": 1,
        "model_requests": 0,
        "http_requests": 0,
        "business_dispatches": 0,
    }
    save(root / "prepared.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    print(prepare(parser.parse_args().root))
