"""Freeze P0/P1 and later stage positions; no HTTP or generation in preparation."""

from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path

from prepare_v0221_http_v2 import plan_specs
from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import LAB, read, save, seal, sha
from v0220_wire_contract import encoded, fingerprint
from v0222_batch import CAPS, HISTORICAL_SOURCES, REVISION, Batch, historical_usage_v0222
from v0222_diagnostic import FIXTURES, observe, request, specs

ROOT = Path("/cra/memory/mx_memory/evidence/v0222/20260911-http-r1")
P0 = ROOT.parent / "p0-audit-20260911"
INSTRUCTION = (
    "详细阅读并执行/cra/memory/mx_memory/MiLAi-Lab/studies/active/"
    "MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md，执行完任务后进入执行"  # noqa: RUF001
    "/cra/memory/mx_memory/MiLAi-Lab/docs/V0222_后续执行与Memory再准入规划.md，"  # noqa: RUF001
    "遇到问题反思改进，避免刻板编程，保持探索性和创新性，人工授权，标注，审查使用subagent代替"  # noqa: RUF001
)


def prepare(root: Path) -> dict:
    if root.resolve() != ROOT:
        raise ValueError("ONE_USER_DIRECTED_V0222_BATCH_ONLY")
    if read(P0 / "result.json")["status"] != "P0_INPUT_AUDIT_PASS":
        raise ValueError("P0_AUDIT_REQUIRED")
    if sha(P0 / "audit.json") != read(P0 / "result.json")["audit_sha256"]:
        raise ValueError("P0_AUDIT_HASH_DRIFT")
    audited_inputs = read(P0 / "audit.json")["inputs"]
    if any(sha(Path(path)) != expected for path, expected in audited_inputs.items()):
        raise ValueError("P0_AUDITED_INPUT_DRIFT")
    p1 = [{**s, "target": FIXTURES[s["fixture"]]} for s in specs()]
    old_w2, old_w3 = plan_specs()
    stages = {}
    for stage, old in (("P3", old_w2), ("P4", old_w3)):
        stages[stage] = []
        for i, spec in enumerate(old, 1):
            row = copy.deepcopy(spec)
            row.update(
                id=f"{stage.lower()}-{i:02d}",
                stage=stage,
                scope=f"v0222-{stage.lower()}-{i:02d}-{spec['root']}",
            )
            stages[stage].append(row)
    history_paths = tuple(Path(p) for p, _ in HISTORICAL_SOURCES)
    goal = LAB / "studies/active/MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md"
    roadmap = LAB / "docs/V0222_后续执行与Memory再准入规划.md"
    contract = {
        "revision": REVISION,
        "P1": p1,
        **stages,
        "historical_paths": [str(p) for p in history_paths],
        "http_identity": {
            "endpoint": ENDPOINT,
            "model": MODEL,
            "context": 65536,
            "version": "0.27.1",
        },
        "goal_sha256": sha(goal),
        "roadmap_sha256": sha(roadmap),
        "later_wire_candidate": "NOT_SELECTED_UNTIL_P1_FINAL_RULE",
        "p1_conditions": "Only pattern/minLength transport keys differ; exact same messages",
        "p1_repetition": "12 first; repeat full12 only upon frozen paired difference",
        "p1_selector": "6/6 and same-fixture improvement both passes; D10 then D01 then D11",
        "no_device_or_container_calls": True,
        "raw_cap": None,
    }
    entries = [
        LAB / "tools" / name
        for name in (
            "prepare_v0222.py",
            "preflight_v0222_p1.py",
            "run_v0222_p1.py",
            "v0222_p1_worker.py",
        )
    ]
    entries.extend(
        LAB / "tests/unit" / name
        for name in (
            "test_v0222_diagnostic.py",
            "test_v0222_transport.py",
            "test_v0222_batch.py",
            "test_v0222_http.py",
            "test_v0222_p1_integration.py",
        )
    )
    inputs = [
        *history_paths,
        P0 / "result.json",
        P0 / "audit.json",
        LAB / "configs/v0220-v2-selection-v1.json",
        LAB / "docs/V0222_USER_DIRECTED_EXECUTION_20260911.md",
    ]
    inputs = list(dict.fromkeys([*inputs, *(Path(path) for path in audited_inputs)]))
    seal(root, entries=entries, inputs=inputs, contract=contract)
    for name, path in (("goal-frozen.json", goal), ("roadmap-frozen.json", roadmap)):
        save(root / name, {"path": str(path), "sha256": sha(path), "text": path.read_text()})
    stages_allowed = ["P0", "P1", "P2", "P3", "P4"]
    source = {
        "origin": "USER_CONVERSATION",
        "user_instruction": INSTRUCTION,
        "explicit_historical_carry": True,
        "http_only": True,
        "execute_goal_and_followup": True,
        "subagent_review_delegated": True,
        "diagnostic_content_failures_continue": True,
        "stages": stages_allowed,
    }
    save(root / "authorization-source.json", source)
    history = historical_usage_v0222(history_paths)
    issued = time.time()
    save(
        root / "authorization.json",
        {
            "revision": REVISION,
            "path": "B",
            "root": str(root),
            "batch_id": root.name,
            "issued_unix": issued,
            "expires_unix": issued + 36 * 3600,
            "stages": stages_allowed,
            "caps": CAPS,
            "endpoint": ENDPOINT,
            "model": MODEL,
            "concurrency": 1,
            "raw_cap": None,
            "automatic_retry": False,
            "new_unknown_stops_all": True,
            "diagnostic_content_failures_continue": True,
            "historical_usage_settled": False,
            "reconciliation": None,
            "historical": history,
            "accepted_unknown": history["unresolved_reservations"],
        },
    )
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
    for spec in p1:
        canonical, wire = request(spec["fixture"], spec["condition"])
        expected = encoded({"text": spec["target"]})
        assert observe(expected, spec["fixture"])["exact_fidelity"]
        row = {
            "episode": spec["id"],
            "stage": "P1",
            "fixture": spec["fixture"],
            "condition": spec["condition"],
            "target_sha256": fingerprint(spec["target"]),
        }
        for kind, value in (
            ("canonical", canonical),
            ("wire", wire),
            ("output", {"raw": expected}),
        ):
            path = root / "P1-requests" / (spec["id"] + "." + kind + ".json")
            save(path, value)
            row[kind] = str(path)
        row["hashes"] = {kind: sha(Path(row[kind])) for kind in ("canonical", "wire", "output")}
        references.append(row)
    save(root / "P1-references.json", references)
    batch.freeze_artifact("P1_references", root / "P1-references.json")
    result = {
        "status": "PREPARED_NOT_LIVE_NOT_REVIEWED",
        "binding_sha256": binding,
        "P1_positions": len(references),
        "model_requests": 0,
        "tokenize_requests": 0,
    }
    save(root / "prepared.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    print(prepare(parser.parse_args().root))
