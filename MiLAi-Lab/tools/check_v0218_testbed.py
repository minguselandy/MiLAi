"""Consolidated twelve-lineage replay and boundary audit; no model or Product writes.

Successful structural validation is deliberately not G-TESTBED signoff. The latter
also needs the separately reviewed source adaptations, Note semantics and gates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from audit_v0218_chain import audit
from check_v0218_expansion import execute as replay_expansion
from check_v0218_verticals import execute as replay_verticals
from run_v0218 import costs
from v0218_checker import evaluate
from v0218_world import PRIVATE_KEYS, PUBLIC_RESOURCES, World, WorldError, digest

LAB = Path(__file__).resolve().parents[1]
SOURCE_REVISION = "d1b641b3171e584e69a3763c269069f32a13b574"
# Previously frozen source order. This selects no root using Agent outcomes.
ROOTS = (
    ("20260910/verticals-v1", "executive_assistant_task2"),
    ("20260910/verticals-v1", "insurance_task3"),
    ("20260910/expansion-v2", "research_assistant_task3"),
    ("20260910/expansion-v2", "investment_analyst_task1"),
    ("20260910/expansion-fifth-v2", "journalist_task5"),
    ("20260910/expansion-sixth-v1", "journalist_task1"),
    ("20260910/expansion-seventh-v1", "investment_analyst_task3"),
    ("20260910/expansion-eighth-v1", "legal_assistant_task6"),
    ("20260911/expansion-ninth-v1", "pm_task3"),
    ("20260911/expansion-tenth-v1", "research_assistant_task6"),
    ("20260911/expansion-eleventh-v1", "real_estate_task4"),
    ("20260911/expansion-twelfth-v1", "hr_task1"),
)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def without_scope(state):
    return {key: value for key, value in state.items() if key != "scope"}


def unchanged_rejection(world, operation, error):
    state, ledger = world.snapshot(), world.ledger()
    try:
        operation()
    except (ValueError, WorldError) as caught:
        assert str(caught) == error
    else:
        raise AssertionError(f"FAIL_CLOSED_MISSING:{error}")
    assert world.snapshot() == state and world.ledger() == ledger


def boundaries(spec: dict, initial: World, completed: World, output: Path) -> dict:
    """Exercise generic isolation on each actual profile, including ordinary history."""
    output.mkdir(parents=True, exist_ok=False)
    recreated = [
        World.create(output / f"reset-{index}.sqlite", initial.scope, spec["public"])
        for index in range(2)
    ]
    assert recreated[0].snapshot() == recreated[1].snapshot() == initial.snapshot()
    assert all(not item.ledger() for item in recreated)
    assert evaluate(completed.snapshot())["status"] == "PASS"
    n0, n1 = (
        completed.clone(output / f"{arm}.sqlite", f"{initial.scope}-{arm}") for arm in ("N0", "N1")
    )
    prefix = without_scope(completed.snapshot())
    assert without_scope(n0.snapshot()) == without_scope(n1.snapshot()) == prefix
    assert n0.read("records")["content"] and n0.read("history")["content"]
    for resource in PUBLIC_RESOURCES:
        assert n0.read(resource) == n1.read(resource)
    assert n0.ledger() == n1.ledger() == completed.ledger()
    obj = spec["public"]["objects"][0]
    request = dict(
        operation_id="idempotent",
        expected_version=n0.snapshot()["version"],
        action="put_record",
        object_id=obj,
        data={k: v for k, v in n0.snapshot()["records"][obj].items() if k != "object_id"},
    )
    receipt = n0.act(**request)
    state, ledger = n0.snapshot(), n0.ledger()
    assert n0.act(**request) == receipt
    assert n0.snapshot() == state and n0.ledger() == ledger
    assert without_scope(n1.snapshot()) == prefix
    checks = ["reset", "common_A_clone", "ordinary_history", "idempotency", "branch_isolation"]
    unchanged_rejection(
        n0,
        lambda: n0.act(**{**request, "operation_id": "stale"}),
        "VERSION_CONFLICT_RELOAD_CURRENT_STATE",
    )
    unchanged_rejection(
        n0,
        lambda: n0.act(**{**request, "data": {"tampered": True}}),
        "OPERATION_ID_REUSE_CONFLICT",
    )
    unchanged_rejection(
        n0,
        lambda: n0.act(**{**request, "operation_id": "foreign", "object_id": "FOREIGN"}),
        "OBJECT_SCOPE_DENIED",
    )
    unchanged_rejection(n0, lambda: World(n0.path, "FOREIGN").snapshot(), "SCOPE_DENIED")
    checks += ["CAS", "operation_identity", "object_scope", "tenant_scope"]
    for private in sorted(PRIVATE_KEYS):
        unchanged_rejection(n0, lambda private=private: n0.read(private), "RESOURCE_NOT_PUBLIC")
        unchanged_rejection(
            n0,
            lambda private=private: n0.act(
                **{**request, "data": {"nested": [{private: "CANARY"}]}}
            ),
            "PRIVATE_EVALUATION_FIELD_FORBIDDEN",
        )
        unchanged_rejection(
            n0,
            lambda private=private: n0.publish(
                event_id="canary", current={"nested": {private: "CANARY"}}
            ),
            "PRIVATE_EVALUATION_FIELD_FORBIDDEN",
        )
        checks.append("private_canary:" + private)
    event = dict(
        event_id="predefined-B", current=spec["variants"]["superseded"], task=spec["task_B"]
    )
    n0.publish(**event)
    state, ledger = n0.snapshot(), n0.ledger()
    assert n0.publish(**event)["replayed"]
    assert n0.snapshot() == state and n0.ledger() == ledger
    unchanged_rejection(
        n0, lambda: n0.publish(**{**event, "current": {}}), "EVENT_ID_REUSE_CONFLICT"
    )
    checks += ["publication_idempotency", "publication_identity"]
    known = completed.snapshot()
    negatives = []
    for value in (None, False, 4, "I completed the correct action", [], {}):
        changed = copy.deepcopy(known)
        changed["records"][obj] = value
        assert evaluate(changed)["status"] == "FAIL"
        negatives.append({"kind": "malformed_record", "value": value})
    changed = copy.deepcopy(known)
    changed["records"] = {}
    assert evaluate(changed)["status"] == "FAIL"
    changed = copy.deepcopy(known)
    changed["records"]["FOREIGN"] = {"object_id": "FOREIGN"}
    assert evaluate(changed)["status"] == "FAIL"
    changed = copy.deepcopy(known)
    changed["records"][obj]["object_id"] = "FOREIGN"
    assert evaluate(changed)["status"] == "FAIL"
    checks += ["no_declaration_only", "out_of_scope_record", "forged_record_identity"]
    return {
        "status": "PASS",
        "checks": checks,
        "negative_fixtures": negatives,
        "initial_sha256": digest(initial.snapshot()),
        "A_prefix_sha256": digest(prefix),
        "agent_recovery": "NOT_MEASURED_SCRIPTED_ONLY",
        "model_requests": 0,
    }


def prepare(evidence: Path, source: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for pack, key in ROOTS:
        manifest_path = evidence / pack / "manifest.json"
        manifest = read(manifest_path)
        assert manifest["source_revision"] == SOURCE_REVISION
        item = next(row for row in manifest["roots"] if row["root"] == key)
        original = evidence / pack / key
        spec = read(original / "evaluation-contract.json")
        assert sha(original / "evaluation-contract.json") == item["contract_sha256"]
        assert sha(source / item["source"]) == item["source_sha256"]
        assert spec["root"] == key and spec["source"] == item["source"]
        assert set(spec["variants"]) == set(item["variants"])
        assert {"stable", "superseded", "unresolved"}.issubset(item["variants"])
        assert item["exposure"] == "EXPOSED_DEVELOPMENT"
        shutil.copytree(original, output / "cases" / key)
        rows.append(
            {
                **item,
                "source_pack": str(evidence / pack),
                "source_pack_manifest_sha256": sha(manifest_path),
                "coarse_family": item["source"].split("/")[1],
                "license": "CC-BY-NC-4.0",
                "native_rubric": False,
            }
        )
    assert len({row["source"] for row in rows}) == len(ROOTS) == 12
    assert len({row["coarse_family"] for row in rows}) >= 3
    save(
        output / "cases/manifest.json",
        {
            "revision": "T5_CONSOLIDATED_V1",
            "source_revision": SOURCE_REVISION,
            "profile": "MILAI_ADAPTED_BEHAVIORAL_TESTBED",
            "roots": rows,
            "split": "12_EXPOSED_D_ZERO_UNOPENED_C",
            "model_requests": 0,
        },
    )
    files = sorted(
        set(
            [
                *LAB.glob("tools/*v0218*.py"),
                *LAB.glob("tests/unit/test_v0218*.py"),
                LAB / "studies/active/MILA_V0218_行为真值测试床建设_GOAL_20260910.md",
            ]
        )
    )
    for path in files:
        destination = output / "executed-source" / path.relative_to(LAB)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    manifest = {
        "status": "FROZEN_BEFORE_CONSOLIDATED_VALIDATION",
        "roots": rows,
        "input_files": {
            str(path.relative_to(output)): sha(path)
            for directory in (output / "cases", output / "executed-source")
            for path in directory.rglob("*")
            if path.is_file()
        },
        "source_revision": SOURCE_REVISION,
        "model_requests": 0,
        "G_TESTBED": "NOT_SIGNED_BY_PREPARATION",
    }
    save(output / "validation-manifest.json", manifest)
    return manifest


def execute(evidence: Path, source: Path, output: Path) -> dict:
    manifest = prepare(evidence, source, output)
    subset = output / "first-two"
    subset.mkdir()
    save(subset / "manifest.json", {"roots": manifest["roots"][:2]})
    for item in manifest["roots"][:2]:
        shutil.copytree(output / "cases" / item["root"], subset / item["root"])
    first = replay_verticals(subset, output / "replays/first-two")
    rows, variant_rows = [], list(first["rows"])
    for index, item in enumerate(manifest["roots"]):
        key = item["root"]
        if index < 2:
            completed_path = output / "replays/first-two" / f"{key}-A.sqlite"
        else:
            replay = replay_expansion(output / "cases", output / "replays" / key, key)
            variant_rows.extend(replay["rows"])
            completed_path = output / "replays" / key / "A.sqlite"
        initial = World(output / "cases" / key / "initial.sqlite", key)
        completed = World(completed_path, key + "-A")
        spec = read(output / "cases" / key / "evaluation-contract.json")
        result = boundaries(spec, initial, completed, output / "boundaries" / key)
        rows.append({"root": key, **result})
        save(output / "boundaries" / key / "result.json", rows[-1])
    chain_roots, chain_rows, batches = set(), [], []
    all_cost = {"requests": 0, "raw_tokens": 0}
    for name in ("t3-note-chain-v1", "t3-note-chain-v2", "t3-note-chain-v3", "t4-note-chain-v1"):
        batch = evidence / "20260910" / name
        observed = costs(batch)
        assert observed == read(batch / "result.json")["cost"]
        assert not observed["pending"] and not observed["violations"]
        for field in all_cost:
            all_cost[field] += observed[field]
        batches.append(
            {"path": str(batch), "result_sha256": sha(batch / "result.json"), "cost": observed}
        )
        if name in ("t3-note-chain-v3", "t4-note-chain-v1"):
            checked = audit(batch)  # Uses the batch's immutable checker, not today's checker.
            chain_rows.extend(checked["rows"])
            chain_roots.update(
                row["root"] for row in checked["rows"] if row["both_actual_requests"]
            )
            save(output / "chain-audits" / f"{name}.json", checked)
    assert len(chain_roots) >= 2
    t2_path = evidence / "20260910/t2-note-preflight-v1/result.json"
    t2 = read(t2_path)
    assert t2["status"] == "T2_PUBLIC_NOTE_COLD_TRANSPORT_VERIFIED_NO_AGENT_PRESENTATION"
    assert (
        t2["run_specific_product_lock"]["valid"] and not t2["run_specific_product_lock"]["errors"]
    )
    assert len({row["pid"] for row in t2["rows"]}) == 3
    assert all(row["child_process_exited_before_next"] for row in t2["rows"])
    assert t2["rows"][0]["content_digest"] == t2["rows"][1]["content_digest"]
    assert t2["rows"][2]["status"] == "CROSS_SCOPE_PUBLIC_READ_DENIED"
    assert t2["cleanup"]["api_stopped"] and t2["cleanup"]["compose_stop_returncode"] == 0
    for name, expected in manifest["input_files"].items():
        assert sha(output / name) == expected
        if name.startswith("executed-source/"):
            assert sha(LAB / name.removeprefix("executed-source/")) == expected
    a_rows = [row for row in chain_rows if row["phase"] == "A"]
    b_rows = [row for row in chain_rows if row["phase"] == "B"]
    result = {
        "status": "STRUCTURAL_VALIDATION_PASSED_PENDING_T5_SIGNOFF",
        "roots": 12,
        "coarse_families": len({row["coarse_family"] for row in manifest["roots"]}),
        "variants": dict(Counter(row["variant"] for row in variant_rows)),
        "scripted_replays": len(variant_rows),
        "boundary_rows": rows,
        "A_attempts_valid_protocol": len(a_rows),
        "A_self_note_valid_protocol": sum(row["agent_note_writes"] > 0 for row in a_rows),
        "A_NO_WRITE_valid_protocol": sum(row["agent_note_writes"] == 0 for row in a_rows),
        "B_attempts_valid_protocol": len(b_rows),
        "B_actual_both": sum(bool(row["both_actual_requests"]) for row in b_rows),
        "actual_both_lineages": sorted(chain_roots),
        "valid_protocol_business_statuses": dict(
            Counter(row["business_status"] for row in chain_rows)
        ),
        "t2": {"path": str(t2_path), "sha256": sha(t2_path)},
        "prior_model_batches": batches,
        "all_construction_model_cost": all_cost,
        "new_model_requests": 0,
        "judge_requests": 0,
        "review": "DEVELOPER_SELF_REVIEW_NOT_INDEPENDENT_HUMAN",
        "G_TESTBED": "PENDING_SOURCE_SEMANTIC_REVIEW_AND_REQUIRED_GATES",
        "E0_E5": "NOT_COMPLETED",
        "native_score": False,
    }
    save(output / "validation-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.evidence, args.source, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "boundary_rows"}))
