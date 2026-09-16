"""Frozen V/T3 batch: shared real A, actual Note CRUD, then paired fresh Host processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from check_v0218_persistence import freeze_delivery
from v02_local_provider import accounting, read_events
from v0210_v05_product import observer
from v0213_provider import Provider, payload
from v0218_checker import evaluate
from v0218_host import REMINDER, SCHEMA, SYSTEM, decode_action
from v0218_memory import read_note, save_note
from v0218_world import World

LAB = Path(__file__).resolve().parents[1]


def save(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def episode_plan(
    roots: list[dict], arms: tuple[str, ...], variants: tuple[str, ...] = ("stable", "superseded")
) -> list[dict]:
    episodes = []
    for item in roots:
        key = item["root"]
        episodes.append(
            {"id": key + "-A", "root": key, "phase": "A", "variant": "initial", "arm": "A"}
        )
        for variant in variants:
            ordered_arms = sorted(
                arms,
                key=lambda arm: hashlib.sha256(f"218:{key}:{variant}:{arm}".encode()).hexdigest(),
            )
            for arm in ordered_arms:
                episodes.append(
                    {
                        "id": f"{key}-{variant}-{arm}",
                        "root": key,
                        "phase": "B",
                        "variant": variant,
                        "arm": arm,
                    }
                )
    return episodes


def verify_testbed(gate: Path, verticals: Path, wave: int) -> tuple[dict, list[dict]]:
    if wave not in (1, 2, 3):
        raise ValueError("E0_MAX_SIX_SEQUENTIAL_D_ROOTS")
    path = gate / "testbed-manifest.json"
    assert sha(path) == json.loads((gate / "testbed-manifest-sha256.json").read_text())["sha256"]
    testbed = json.loads(path.read_text())
    assert testbed["status"] == "TESTBED_READY_FOR_DISCOVERY"
    assert testbed["G_TESTBED"] == "PASSED_LIMITED_ADAPTED_PROFILE"
    assert testbed["checker_sha256"] == sha(LAB / "tools/v0218_checker.py")
    assert all(item["exit_code"] == 0 for item in testbed["gates"])
    for name, expected in testbed["signed_artifacts"].items():
        assert sha(gate / name) == expected
    validation = Path(testbed["validation_path"])
    assert sha(validation / "validation-manifest.json") == testbed["validation_manifest_sha256"]
    assert sha(validation / "validation-result.json") == testbed["validation_result_sha256"]
    inputs = json.loads((validation / "validation-manifest.json").read_text())["input_files"]
    roots = json.loads((verticals / "manifest.json").read_text())["roots"]
    assert roots == testbed["roots"] and len(roots) == 12
    # Every actual selected input must be byte-identical to the accepted testbed.
    for name, expected in inputs.items():
        if name.startswith("cases/"):
            assert sha(verticals / name.removeprefix("cases/")) == expected
    return testbed, roots[(wave - 1) * 2 : wave * 2]


def carries_note(arm: str) -> bool:
    if arm not in ("A", "N0", "N1", "N2"):
        raise ValueError("UNKNOWN_MEMORY_ARM")
    return arm in ("N1", "N2")


def verify_protocol_revision(path: Path) -> dict:
    decision = json.loads(path.read_text())
    assert decision["revision"] == "COMMON_HOST_V4_SETTLED_ENCODING_ERROR_FEEDBACK"
    failed = Path(decision["failed_batch"])
    result = json.loads((failed / "result.json").read_text())
    previous = json.loads((failed / "manifest.json").read_text())
    assert result["status"] == "E0_STOPPED_PRESERVED"
    assert result["cost"] == costs(failed)
    assert not result["cost"]["pending"] and not result["cost"]["violations"]
    assert result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
    request = failed / "episodes" / decision["failed_episode"] / decision["failed_request"]
    http = json.loads(request.with_name(request.name + "-http.json").read_text())
    response = json.loads(http["body"])
    assert http["status_code"] == decision["expected_diagnosis"]["http_status"] == 200
    assert response["choices"][0]["finish_reason"] == "stop"
    assert response["usage"]["completion_tokens"] == 1814 < 4096
    outer = json.loads(response["choices"][0]["message"]["content"])
    try:
        json.loads(outer["arguments_json"])
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("DECLARED_ENCODING_REPRODUCER_DID_NOT_FAIL")
    assert previous["system_prompt"] == SYSTEM and previous["schema"] == SCHEMA
    for name in ("v0218_world.py", "v0218_checker.py", "v0218_memory.py", "v0213_provider.py"):
        assert previous["implementation"]["tools/" + name] == sha(LAB / "tools" / name)
    return {
        **decision,
        "config_sha256": sha(path),
        "failed_result_sha256": sha(failed / "result.json"),
        "failed_http_sha256": sha(request.with_name(request.name + "-http.json")),
        "previous_cost_reference_only_not_recharged": result["cost"],
        "old_host_sha256": previous["implementation"]["tools/v0218_host.py"],
        "new_host_sha256": sha(LAB / "tools/v0218_host.py"),
    }


def verify_probes(path: Path, testbed: dict, protocol: dict) -> dict:
    plan = json.loads(path.read_text())
    expected = [row["root"] for row in testbed["roots"] if "helpful" in row["variants"]][:2]
    assert plan["roots"] == expected and len(expected) == 2
    assert plan["variants"] == ["helpful", "irrelevant", "unresolved"]
    assert plan["arms"] == ["N0", "N1", "N2"]
    assert plan["episodes"] == 20 and plan["max_requests"] == 320
    assert plan["generation_cap"] == 16 and plan["seconds_per_episode"] == 900
    assert plan["batch_seconds"] == 19800
    assert protocol["revision"] == "COMMON_HOST_V4_SETTLED_ENCODING_ERROR_FEEDBACK"
    assert len(plan["prior_waves"]) == 3
    verified = []
    for index, name in enumerate(plan["prior_waves"], 1):
        prior = Path(name)
        manifest = json.loads((prior / "manifest.json").read_text())
        result = json.loads((prior / "result.json").read_text())
        audit = json.loads((prior / "baseline-audit-v1.json").read_text())
        assert manifest["stage"] == f"E0_STRONG_SIMPLE_BASELINE_WAVE_{index}"
        assert manifest["protocol_revision"]["revision"] == protocol["revision"]
        assert manifest["implementation"]["tools/v0218_host.py"] == protocol["new_host_sha256"]
        assert result["status"] == "E0_EXECUTED_REQUIRES_CHAIN_AND_BEHAVIOR_AUDIT"
        assert len(result["rows"]) == 14 and all(r["status"] == "FINISHED" for r in result["rows"])
        assert result["cost"] == audit["cost"] == costs(prior)
        assert not result["cost"]["pending"] and not result["cost"]["violations"]
        assert (
            result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
        )
        verified.append(
            {
                "path": name,
                "manifest_sha256": sha(prior / "manifest.json"),
                "result_sha256": sha(prior / "result.json"),
                "audit_sha256": sha(prior / "baseline-audit-v1.json"),
            }
        )
    return {**plan, "config_sha256": sha(path), "verified_prior_waves": verified}


def freeze(
    root: Path,
    verticals: Path,
    prior_compatibility: Path | None = None,
    prior_attempt: Path | None = None,
    protocol_evidence: Path | None = None,
    e0_gate: Path | None = None,
    e0_wave: int = 1,
    protocol_revision: Path | None = None,
    e0_probes: Path | None = None,
) -> dict:
    testbed = None
    if e0_gate is not None:
        assert prior_compatibility is not None and protocol_evidence is not None
        assert prior_attempt is None
        testbed, roots = verify_testbed(e0_gate, verticals, e0_wave)
    else:
        assert e0_wave == 1
        roots = json.loads((verticals / "manifest.json").read_text())["roots"]
    protocol = verify_protocol_revision(protocol_revision) if protocol_revision else None
    probes = None
    if e0_probes is not None:
        assert testbed is not None and protocol is not None and e0_wave == 3
        probes = verify_probes(e0_probes, testbed, protocol)
        assert [row["root"] for row in roots] == probes["roots"]
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    if testbed is None:
        shutil.copytree(verticals, root / "cases")
    else:
        for item in roots:
            shutil.copytree(verticals / item["root"], root / "cases" / item["root"])
        save(
            root / "cases/manifest.json",
            {
                "revision": f"E0_WAVE_{e0_wave}_T5_SUBSET_UNCHANGED",
                "profile": testbed["profile"],
                "roots": roots,
            },
        )
    arms = ("N0", "N1", "N2") if testbed is not None else ("N0", "N1")
    variants = tuple(probes["variants"]) if probes else ("stable", "superseded")
    episodes = episode_plan(roots, arms, variants)
    code = [
        "run_v0218.py",
        "v0218_host.py",
        "v0218_world.py",
        "v0218_checker.py",
        "v0218_memory.py",
        "v0213_provider.py",
        "v02_local_provider.py",
        "replay_v0213_cost.py",
        "run_v0212_horizon.py",
        "v0210_v05_product.py",
        "check_v0211_backend.py",
        "check_v0210_control.py",
        "check_v0218_persistence.py",
        "run_v02_memory_flow.py",
    ]
    for name in code:
        target = root / "executed-source" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(LAB / "tools" / name, target)
    manifest = {
        "status": "SEALED_BEFORE_MODEL_GENERATION",
        "stage": "T4_CHAIN_AND_WORLD_EXPANSION_NOT_E0" if protocol_evidence else "V_AND_T3_NOT_E1",
        "profile": "MILAI_ADAPTED_BEHAVIORAL_TESTBED",
        "episodes": episodes,
        "generation_cap": 16,
        "seconds_per_episode": 900,
        "batch_seconds": 14400 if testbed is not None else 9600,
        "compatibility_requests": 0 if prior_compatibility else 2,
        "max_requests": (0 if prior_compatibility else 2) + 16 * len(episodes),
        "output_cap_per_request": 4096,
        "request_timeout_seconds": 60,
        "model_generation_parallelism": 1,
        "raw_token_cap": None,
        "judge_requests": 0,
        "model": "Qwen3.6-35B-A3B-FP8",
        "provider_origin": "http://127.0.0.1:7860",
        "seed": 213,
        "temperature": 0,
        "enable_thinking": False,
        "carrier": "PUBLIC_NOTE_CRUD_HOST_WORKING",
        "note_selection": "ONE_OPTIONAL_FREE_TEXT_NOTE_SLOT",
        "shared_A_cost": "COUNT_ONCE",
        "NO_WRITE": "RETAIN_ALL_B_ARMS_NO_REPLACEMENT",
        "split": "TWO_PREVIOUSLY_EXPOSED_D_LINEAGES",
        "E0_reuse": "Only if later frozen conditions remain identical",
        "implementation": {"tools/" + name: sha(LAB / "tools" / name) for name in code},
        "input_files": {
            str(p.relative_to(root)): sha(p) for p in (root / "cases").rglob("*") if p.is_file()
        },
        "model_assets": {
            str(p): sha(p)
            for p in [
                Path("/cra/qwen36-35B") / name
                for name in (
                    "config.json",
                    "tokenizer.json",
                    "tokenizer_config.json",
                    "chat_template.jinja",
                )
            ]
        },
        "schema": SCHEMA,
        "system_prompt": SYSTEM,
        "unknown_usage": "STOP_NO_AUTOMATIC_RETRY",
        "recovery_reserve": (
            "At least two action opportunities before last finish-only slot when reached"
        ),
        "semantic_review": (
            "Nonblind developer review of free Notes against A public facts; "
            "uncertain stays UNKNOWN"
        ),
    }
    if testbed is not None:
        manifest.update(
            stage=f"E0_STRONG_SIMPLE_BASELINE_WAVE_{e0_wave}",
            split="EXPOSED_D_FROM_T5_FIXED_ORDER_NO_CONFIRMATION",
            E0_reuse="Prospectively frozen E0; previous T3/T4 is exposed context, not recharged",
            G_TESTBED={
                "path": str(e0_gate),
                "manifest_sha256": sha(e0_gate / "testbed-manifest.json"),
            },
            arms=list(arms),
            variants=["stable", "superseded"],
            reminder=REMINDER,
            reminder_policy="N2_B_ONLY_EXACT_SAME_A_NOTE_AS_N1",
            order="sha256('218:' + root + ':' + variant + ':' + arm), ascending",
            wave=e0_wave,
            cold_repeats=1,
            estimand="Conditional consumption exposure of one shared natural A Note; "
            "not autonomous retrieval or end-to-end independent writing policies",
            no_effect_stopping="Finish all arms including NO_WRITE and semantic failures; "
            "stop on unknown usage or infrastructure/protocol failure",
        )
    if protocol is not None:
        shutil.copyfile(protocol_revision, root / "protocol-revision.json")
        manifest["input_files"]["protocol-revision.json"] = sha(root / "protocol-revision.json")
        manifest["protocol_revision"] = protocol
    if probes is not None:
        shutil.copyfile(e0_probes, root / "probe-plan.json")
        manifest["input_files"]["probe-plan.json"] = sha(root / "probe-plan.json")
        manifest.update(
            stage=probes["stage"],
            probes=probes,
            variants=list(variants),
            batch_seconds=probes["batch_seconds"],
        )
    if prior_compatibility is not None:
        previous = json.loads((prior_compatibility / "result.json").read_text())
        assert previous["cost"]["requests"] == 2
        assert not previous["cost"]["pending"] and not previous["cost"]["violations"]
        manifest["prior_compatibility"] = {
            "path": str(prior_compatibility),
            "result_sha256": sha(prior_compatibility / "result.json"),
            "status": previous["status"],
            "cost": previous["cost"],
            "interpretation": "Read action passed; write omitted required arguments. "
            "No new compatibility generation allocated. Common Host exposes its action "
            "schema and uses a required JSON-string argument carrier, not optional nested "
            "decoding fields. Offline tests do not imply model compliance. "
            "T3 retains all real task attempts and their protocol errors.",
        }
    if prior_attempt is not None:
        previous = json.loads((prior_attempt / "result.json").read_text())
        assert previous["status"] == "T3_STOPPED_PRESERVED"
        assert previous["cost"] == costs(prior_attempt)
        assert not previous["cost"]["pending"] and not previous["cost"]["violations"]
        manifest["technical_replay"] = {
            "previous_attempt": str(prior_attempt),
            "result_sha256": sha(prior_attempt / "result.json"),
            "previous_cost_retained": previous["cost"],
            "reason": "Uniform required JSON-string argument encoding after repeated missing "
            "write parameters and malformed structured output. Same roots, tasks, worlds, "
            "checker and arms; no Note-content or outcome-based task replacement.",
            "previous_episodes_valid_for_effects": False,
        }
    if protocol_evidence is not None:
        previous = json.loads((protocol_evidence / "result.json").read_text())
        prior_manifest = json.loads((protocol_evidence / "manifest.json").read_text())
        assert previous["status"] == "T3_EXECUTED_REQUIRES_CHAIN_AND_SEMANTIC_AUDIT"
        assert previous["cost"] == costs(protocol_evidence)
        assert not previous["cost"]["pending"] and not previous["cost"]["violations"]
        assert all(row["status"] == "FINISHED" for row in previous["rows"])
        for name in ("tools/v0213_provider.py", "tools/v0218_memory.py"):
            assert manifest["implementation"][name] == prior_manifest["implementation"][name]
        if protocol is None:
            assert (
                manifest["implementation"]["tools/v0218_host.py"]
                == prior_manifest["implementation"]["tools/v0218_host.py"]
            )
        else:
            assert (
                protocol["old_host_sha256"]
                == prior_manifest["implementation"]["tools/v0218_host.py"]
            )
        manifest["preceding_protocol_evidence"] = {
            "path": str(protocol_evidence),
            "result_sha256": sha(protocol_evidence / "result.json"),
            "interpretation": "Actual common Host/Provider/Note transport exercised in ten "
            "completed prior episodes. Business semantic misses and NO_WRITE retained. "
            "Expand along the original source order; not a replacement of failed roots, "
            "not a new compatibility generation or a memory mechanism.",
            "prior_cost_reference_only_not_recharged": previous["cost"],
        }
    save(root / "manifest.json", manifest)
    save(root / "manifest-sha256.json", {"sha256": sha(root / "manifest.json")})
    shutil.copyfile(
        LAB / "studies/active/MILA_V0218_行为真值测试床建设_GOAL_20260910.md",
        root / "goal-as-executed.md",
    )
    return manifest


def validate(root: Path) -> dict:
    assert (
        sha(root / "manifest.json")
        == json.loads((root / "manifest-sha256.json").read_text())["sha256"]
    )
    manifest = json.loads((root / "manifest.json").read_text())
    for base, rows in (
        (LAB, manifest["implementation"]),
        (root, manifest["input_files"]),
        (Path("/"), manifest["model_assets"]),
    ):
        for name, digest in rows.items():
            assert sha(base / name) == digest, name
    return manifest


def costs(root: Path) -> dict:
    rows = [accounting(read_events(path)) for path in root.rglob("provider-ledger.jsonl")]
    return {
        "requests": sum(row["requests"] for row in rows),
        "raw_tokens": sum(row["raw_tokens"] for row in rows),
        "pending": sum(len(row["pending"]) for row in rows),
        "violations": sum(len(row["violations"]) for row in rows),
    }


def compatibility(root: Path) -> None:
    provider = Provider(root, deadline=time.monotonic() + 150, max_requests=2)
    try:
        provider.verify()
        for index, prompt in enumerate(
            [
                "Transport check only: return action read with resource current.",
                "Transport check only: return action put_record, object_id fixture, "
                "expected_version 0, data containing confirmed true and start example. "
                "Do not actually execute anything.",
            ]
        ):
            response = provider.generate(
                f"compat-{index}",
                payload(
                    [
                        {
                            "role": "system",
                            "content": "Return a JSON action using the supplied schema; "
                            "arguments_json contains JSON-encoded named parameters. "
                            + json.dumps(SCHEMA),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    SCHEMA,
                ),
            )
            value = decode_action(response)
            assert value["action"] == ("read" if index == 0 else "put_record")
            if index == 1:
                assert isinstance(value["data"], dict) and value["data"]["confirmed"] is True
    finally:
        provider.close()


def cold(config: dict, config_path: Path, remaining: float) -> dict:
    save(config_path, config)
    host_name = "v0218_policy_host.py" if "policy" in config else "v0218_host.py"
    if "public_prefetch" in config:
        host_name = "v0218_e2_host.py"
    with config_path.with_suffix(".log").open("w") as log:
        child = subprocess.Popen(  # noqa: S603 -- own frozen Host; no shell/model paths
            [sys.executable, str(LAB / "tools" / host_name), "--config", str(config_path)],
            cwd=LAB,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = child.wait(timeout=min(remaining, config["seconds"] + 90))
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            raise
    if code:
        raise ValueError("COLD_HOST_PROCESS_FAILED:" + str(code))
    result = json.loads((Path(config["output"]) / "result.json").read_text())
    assert result["pid"] == child.pid
    result["exit_verified_before_next_episode"] = True
    result["business_outcome"] = evaluate(
        json.loads((Path(config["output"]) / "final-world.json").read_text())
    )
    return result


def run(root: Path, installed: Path) -> dict:
    from run_v0212_horizon import product

    manifest = validate(root)
    if (root / "result.json").exists() or any(root.rglob("provider-ledger.jsonl")):
        raise ValueError("PRESERVE_PREVIOUS_ATTEMPT_NEW_RUN_REQUIRED")
    rows, upstream = [], {}
    started = time.monotonic()
    result = {}
    try:
        freeze_delivery(root / "pinned-delivery")
        if manifest["compatibility_requests"]:
            compatibility(root / "compatibility")
        else:
            prior = manifest["prior_compatibility"]
            assert sha(Path(prior["path"]) / "result.json") == prior["result_sha256"]
        with product(root / "product", installed) as owned:
            for episode in manifest["episodes"]:
                validate(root)
                used = costs(root)
                if used["pending"] or used["violations"]:
                    raise ValueError("UNSETTLED_PROVIDER_USAGE_STOP")
                if used["requests"] + manifest["generation_cap"] > manifest["max_requests"]:
                    raise ValueError("BATCH_ALLOCATION_EXHAUSTED")
                remaining = manifest["batch_seconds"] - (time.monotonic() - started)
                if remaining <= 90:
                    raise ValueError("BATCH_DEADLINE_NO_NEW_EPISODE")
                key, phase, arm, variant = (episode[k] for k in ("root", "phase", "arm", "variant"))
                scope = (
                    "v0218-" + hashlib.sha256(f"{root}:{episode['id']}".encode()).hexdigest()[:24]
                )
                source = (
                    root / "cases" / key / "initial.sqlite"
                    if phase == "A"
                    else Path(upstream[key]["world"])
                )
                source_scope = key if phase == "A" else upstream[key]["scope"]
                world = World(source, source_scope).clone(
                    root / "worlds" / (episode["id"] + ".sqlite"), scope
                )
                note_commit = None
                if phase == "B":
                    spec = json.loads(
                        (root / "cases" / key / "evaluation-contract.json").read_text()
                    )
                    world.publish(
                        event_id="predefined-B",
                        current=spec["variants"][variant],
                        task=spec["task_B"],
                    )
                    with observer(
                        owned,
                        root / "branch-audits" / episode["id"],
                        task=scope,
                        principal=scope,
                        project=scope,
                    ) as public:
                        before = public(
                            "milai_memory_list", {"selection": {"kind": "NOTE"}, "limit": 100}
                        )
                        save(
                            root / "branch-audits" / episode["id"] / "initial-memory-list.json",
                            before,
                        )
                        assert not before.get("mcp_error") and before["items"] == []
                        note_enabled = (
                            manifest["policies"][arm]["carry_note"]
                            if "policies" in manifest
                            else carries_note(arm)
                        )
                        if note_enabled and upstream[key]["note"] is not None:
                            note_commit = save_note(
                                public, upstream[key]["note"]["content"], scope + "-branch"
                            )
                            copied = read_note(public, note_commit)
                            assert copied["content"] == upstream[key]["note"]["content"]
                            save(
                                root / "branch-audits" / episode["id"] / "note-copy.json",
                                {
                                    "kind": "HARNESS_EXACT_COPY_OF_AGENT_NOTE",
                                    "origin": upstream[key]["commit"],
                                    "destination": note_commit,
                                    "content_rewritten": False,
                                },
                            )
                config = {
                    "root": key,
                    "episode_id": episode["id"],
                    "phase": phase,
                    "arm": arm,
                    "variant": variant,
                    "world": str(world.path),
                    "world_scope": scope,
                    "memory_scope": scope,
                    "owned": str(owned),
                    "note_commit": note_commit,
                    "output": str(root / "episodes" / episode["id"]),
                    "seconds": min(manifest["seconds_per_episode"], remaining - 90),
                    "generation_cap": manifest["generation_cap"],
                }
                if phase == "B" and "policies" in manifest:
                    config.update(policy=arm, policy_system=manifest["policy_systems"][arm])
                if phase == "B" and "public_prefetch" in manifest:
                    config["public_prefetch"] = manifest["public_prefetch"]
                row = cold(config, root / "episode-configs" / (episode["id"] + ".json"), remaining)
                rows.append(row)
                save(root / "progress.json", {"rows": rows, "cost": costs(root)})
                if row["status"] == "INFRASTRUCTURE_OR_PROTOCOL_STOP":
                    raise ValueError("HOST_PROTOCOL_FAILURE_PRESERVE:" + row.get("reason", ""))
                if phase == "A":
                    note_path = Path(config["output"]) / "final-public-note.json"
                    upstream[key] = {
                        "world": str(world.path),
                        "scope": scope,
                        "note": json.loads(note_path.read_text()) if note_path.exists() else None,
                        "commit": row.get("note_commit"),
                    }
        result = {
            "status": "E0_EXECUTED_REQUIRES_CHAIN_AND_BEHAVIOR_AUDIT"
            if manifest["stage"].startswith("E0_")
            else "T3_EXECUTED_REQUIRES_CHAIN_AND_SEMANTIC_AUDIT",
            "rows": rows,
        }
        if "policies" in manifest:
            result.update(status="DISCOVERY_EXECUTED_REQUIRES_AUDIT", stage=manifest["stage"])
    except Exception as exc:
        result = {
            "status": "E0_STOPPED_PRESERVED"
            if manifest["stage"].startswith("E0_")
            else "T3_STOPPED_PRESERVED",
            "reason": str(exc),
            "exception_type": type(exc).__name__,
            "rows": rows,
        }
        if "policies" in manifest:
            result.update(status="DISCOVERY_STOPPED_PRESERVED", stage=manifest["stage"])
    result.update(
        cost=costs(root),
        seconds=time.monotonic() - started,
        raw_token_cap=None,
        G_TESTBED="NOT_YET_AUDITED",
        E1="NOT_ENTERED",
    )
    if manifest["stage"].startswith("E0_"):
        result.update(stage=manifest["stage"], G_TESTBED="PASSED_LIMITED_ADAPTED_PROFILE")
    if "policies" in manifest:
        result.update(G_TESTBED="PASSED_LIMITED_ADAPTED_PROFILE", E1="ATTEMPTED_NOT_YET_AUDITED")
    if manifest["stage"].startswith("E2_"):
        result.update(E1="COMPLETE_PRECEDING_EVIDENCE", E2="ATTEMPTED_NOT_YET_AUDITED")
    if (root / "product/cleanup.json").exists():
        result["cleanup"] = json.loads((root / "product/cleanup.json").read_text())
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze-from", type=Path)
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--prior-compatibility", type=Path)
    parser.add_argument("--prior-attempt", type=Path)
    parser.add_argument("--protocol-evidence", type=Path)
    parser.add_argument("--e0-gate", type=Path)
    parser.add_argument("--e0-wave", type=int, default=1)
    parser.add_argument("--protocol-revision", type=Path)
    parser.add_argument("--e0-probes", type=Path)
    args = parser.parse_args()
    value = (
        freeze(
            args.root,
            args.freeze_from,
            args.prior_compatibility,
            args.prior_attempt,
            args.protocol_evidence,
            args.e0_gate,
            args.e0_wave,
            args.protocol_revision,
            args.e0_probes,
        )
        if args.freeze_from
        else run(args.root, args.installed)
    )
    print(
        json.dumps(
            {
                key: value[key]
                for key in ("status", "cost", "max_requests", "reason")
                if key in value
            }
        )
    )
