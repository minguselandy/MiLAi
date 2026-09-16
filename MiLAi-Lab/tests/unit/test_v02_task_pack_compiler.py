from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
compiler = importlib.import_module("compile_v02_task_pack")
chain = importlib.import_module("run_v02_e2e_generality")
host = importlib.import_module("run_v02_local_vllm")
variant = importlib.import_module("v02_variant_plan")


@pytest.fixture
def pack(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler.base, "LAB", tmp_path)
    directory = tmp_path / "pack/task-a"
    directory.mkdir(parents=True)

    def file(name, text):
        return {"path": name, "content": text, "source_uri": "fixture://" + name,
                "sha256": compiler.digest(text.encode()), "observed_at": "2026-09-07T10:00:00Z"}

    initial = {"schema_version": "v02-file-source-only-v1", "files": [
        file("original.md", " 首\r\n原要求\n尾 \n")]}
    future = {**initial, "files": [*initial["files"], file("future.md", "FUTURE_DECISION")]}

    def save(name, value):
        compiler.write_json(directory / name, value)
        return {"path": name, "sha256": compiler.digest((directory / name).read_bytes())}

    a, b = save("g.json", initial), save("future.json", future)
    evaluation = {"schema_version": "v02-file-evaluation-v1", "source_sha256": b["sha256"],
        "question": "Continue now", "question_date": "2026-09-07", "first_use_boundary": "Delivery",
        "necessary_conditions": ["EVALUATOR_ONLY_CONDITION"], "source_assertions": [{
            "statement": "EVALUATOR_ONLY_CONDITION", "spans": [{"path": "future.md",
                "source_uri": "fixture://future.md", "start": 0, "end": 15,
                "sha256": compiler.digest(b"FUTURE_DECISION")}]}]}
    # The exact end offset is part of the frozen source contract, not inferred by the compiler.
    evaluation["source_assertions"][0]["spans"][0]["end"] = len("FUTURE_DECISION")
    task = {"id": "task-a", "family": "arbitrary-family", "sessions": list(variant.ALL_ARMS),
        "generator_task": "Perform original task; optionally hand off.",
        "generator_sources": a, "continuation_sources": b,
        "evaluation": save("eval.json", evaluation),
        "post_g_new_source_paths": ["future.md"], "memory_case": "UNCONFIRMED",
        "representation": {"layer": "L1", "kind": "MARKDOWN_JSON_TEXT_WRAPPING_ONLY"},
        "structure": "BODY_FIRST"}
    ref = save("task.json", task)
    manifest = {"chains": [{"id": "task-a", "family": "arbitrary-family",
        "task_path": "task-a/task.json", "task_sha256": ref["sha256"], "source_assertions": 1}]}
    compiler.write_json(tmp_path / "pack/manifest.json", manifest)
    digest = compiler.digest((tmp_path / "pack/manifest.json").read_bytes())
    index = {"manifest_path": "pack/manifest.json", "manifest_sha256": digest,
             "product_lock": "lock.json", "developer_visibility": "OPEN"}
    bindings = {"manifest_sha256": digest, "bindings": {"task-a": {
        "B_representation": {**task["representation"], "source_format": "text"},
        "B_structure": {"layer": "L2", "source_format": "json", "kind": "BODY_FIRST",
                        "body_key": "body"}}}}
    template = {"product_lock": "lock.json", "l1_format": "text",
                "host_source_recheck": "OFF", "session_token_limit": 1000000}
    for name, value in (("index", index), ("bindings", bindings), ("host", template)):
        compiler.write_json(tmp_path / (name + ".json"), value)
    return tmp_path


def compile_here(root):
    return compiler.compile_pack(root / "index.json", root / "bindings.json", root / "host.json",
                                 root / "compiled")


def test_candidate_preserves_full_inputs_and_g_prompt_without_leaking_future_or_rubric(pack):
    report = compile_here(pack)
    directory = pack / "compiled/task-a"
    config = compiler.base.read_json(directory / "config.json")
    task = compiler.base.read_json(pack / "pack/task-a/task.json")
    assert config["generator_task"] == task["generator_task"]
    assert "FUTURE_DECISION" not in json.dumps(config)
    assert "EVALUATOR_ONLY_CONDITION" not in json.dumps(config)
    for source, copied in (("g.json", "input-source.json"),
                           ("future.json", "continuation-source.json"),
                           ("eval.json", "evaluation-contract.json")):
        assert (pack / "pack/task-a" / source).read_bytes() == (directory / copied).read_bytes()
    assert config["session_token_limit"] == 1000000
    assert config["host_source_recheck"] == "OFF"
    assert config["local_sessions"] == list(variant.ALL_ARMS)
    assert report["chains"][0]["variant_applicability"] == "REQUIRES_ACTUAL_G"
    with pytest.raises(host.LocalGateError, match="NO_NEW_MODEL_AUTHORIZATION"):
        chain.run(directory)
    with pytest.raises(FileExistsError):
        compile_here(pack)
    assert not list((pack / "compiled").rglob("provider-ledger.jsonl"))


@pytest.mark.parametrize("target", ["g.json", "future.json", "eval.json", "task.json"])
def test_changed_task_or_sources_refused_before_output(pack, target):
    path = pack / "pack/task-a" / target
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(host.LocalGateError, match="IDENTITY_CHANGED"):
        compile_here(pack)
    assert not (pack / "compiled").exists()


@pytest.mark.parametrize("fault", ["missing_task", "layer", "kind", "format", "reserved"])
def test_variant_binding_cannot_silently_change_comparison(pack, fault):
    path = pack / "bindings.json"
    value = compiler.base.read_json(path)
    plan = value["bindings"]["task-a"]
    if fault == "missing_task":
        value["bindings"] = {}
    elif fault == "layer":
        plan["B_representation"]["layer"] = "L2"
    elif fault == "kind":
        plan["B_structure"]["kind"] = "BODY_LAST"
    elif fault == "format":
        plan["B_representation"]["source_format"] = "json"
    else:
        plan["B_structure"]["body_key"] = "evidence_refs"
    compiler.write_json(path, value)
    with pytest.raises(host.LocalGateError):
        compile_here(pack)
    assert not (pack / "compiled").exists()


@pytest.mark.parametrize("field", ["model_transport_enabled", "new_model_allocations_authorized",
                                   "formal_d4_d5_enabled", "generator_task"])
def test_old_execution_grants_or_task_specific_template_refused(pack, field):
    path = pack / "host.json"
    value = compiler.base.read_json(path)
    value[field] = True
    compiler.write_json(path, value)
    with pytest.raises(host.LocalGateError):
        compile_here(pack)
    assert not (pack / "compiled").exists()


def test_missing_structure_opportunity_stays_inapplicable_without_changing_artifact(pack):
    compile_here(pack)
    config = compiler.base.read_json(pack / "compiled/task-a/config.json")
    original = b"# Ordinary Markdown\nAll actual content remains here.\n"
    spec = config["memory_variants"]["B_structure"]
    with pytest.raises(variant.NotApplicable):
        variant.transform(original, spec["source_format"], spec)
    assert original == b"# Ordinary Markdown\nAll actual content remains here.\n"


def test_link_cannot_escape_declared_package(pack):
    original = pack / "pack/task-a/g.json"
    reference = {"path": "../../index.json", "sha256": compiler.digest(original.read_bytes())}
    with pytest.raises(host.LocalGateError, match="OUTSIDE_PACKAGE"):
        compiler.linked(original.parent, reference)


def test_pack_validates_later_entries_before_publishing_any_candidate(pack):
    path = pack / "pack/manifest.json"
    manifest = compiler.base.read_json(path)
    extra = copy.deepcopy(manifest["chains"][0])
    extra.update(id="second", task_path="second/missing.json")
    manifest["chains"].append(extra)
    compiler.write_json(path, manifest)
    index = compiler.base.read_json(pack / "index.json")
    index["manifest_sha256"] = compiler.digest(path.read_bytes())
    compiler.write_json(pack / "index.json", index)
    bindings = compiler.base.read_json(pack / "bindings.json")
    bindings["manifest_sha256"] = index["manifest_sha256"]
    bindings["bindings"]["second"] = bindings["bindings"]["task-a"]
    compiler.write_json(pack / "bindings.json", bindings)
    with pytest.raises(host.LocalGateError):
        compile_here(pack)
    assert not (pack / "compiled").exists()


def test_compiled_config_enters_existing_prepare_with_only_initial_sources(pack, monkeypatch):
    template = compiler.base.read_json(pack / "host.json")
    template["data_mode"] = "DEIDENTIFIED_ALLOWED"
    compiler.write_json(pack / "host.json", template)
    compile_here(pack)
    seen = []
    monkeypatch.setattr(chain.base, "pin", lambda _: {"valid": True})
    monkeypatch.setattr(chain.base, "prepare", lambda *args, **kwargs: seen.append("service"))

    def snapshot(root, sources):
        assert [f["path"] for f in sources["files"]] == ["original.md"]
        assert "FUTURE_DECISION" not in json.dumps(sources)
        rubric = compiler.base.read_json(root / "evaluation-contract.json")
        assert rubric["necessary_conditions"] == ["EVALUATOR_ONLY_CONDITION"]
        assert "future.md" in (root / "continuation-source.json").read_text()
        seen.append("initial_snapshot")

    monkeypatch.setattr(chain, "prepare_snapshot", snapshot)
    compose = pack / "compose.yaml"
    compose.write_text("fixture: true\n")
    chain.prepare(pack / "prepared-run", pack / "compiled/task-a/config.json",
                  compose_override=compose)
    assert seen == ["service", "initial_snapshot"]
    assert not (pack / "prepared-run/G/workspace/evaluation-contract.json").exists()
