"""A tiny local model fixture proves v9 preparation without provider calls."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai_lab.harness.contextual_artifacts import digest, read_json, write_json

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_contextual_v9 as preparer
import run_contextual_merit as merit


def test_prepare_v9_from_local_files_rebuilds_exact_original_arc(tmp_path: Path) -> None:
    host_dir = tmp_path / "host"
    embedding_dir = tmp_path / "embedding"
    host_dir.mkdir()
    embedding_dir.mkdir()
    for name, value in {
        "layers-0.safetensors": "host weight", "config.json": "{}",
        "tokenizer.json": "{}", "tokenizer_config.json": "{}",
        "chat_template.jinja": "{{ messages }}",
    }.items():
        (host_dir / name).write_text(value)
    for name, value in {
        "pytorch_model.bin": "embedding weight", "config.json": "{}",
        "tokenizer.json": "{}", "tokenizer_config.json": "{}",
    }.items():
        (embedding_dir / name).write_text(value)
    pinned = read_json(preparer.PINNED_SELECTION)
    managed = preparer.LAB / "artifacts/contextual-user-memory"
    managed.mkdir(parents=True, exist_ok=True)
    budget = tmp_path / "shared-budget.json"
    with tempfile.TemporaryDirectory(prefix="v9-prepare-test-", dir=managed) as temporary:
        result = preparer.prepare(
            output_dir=Path(temporary) / "fresh", merit_root=Path(pinned["external_root"]),
            host_dir=host_dir, embedding_dir=embedding_dir,
            host_url="http://host.test/v1/", embedding_url="http://embed.test/v1/",
            budget_path=budget,
        )
        selection, config, identity, _, _, _, _, diagnostic, _ = merit.prepared_inputs(
            Path(result["selection"]), Path(result["config"]), Path(result["freeze"]),
        )
        assert selection["execution_plan"]["arms"] == ["ordinary_v9_off"]
        assert diagnostic["episode_count"] == 5
        assert diagnostic["user_message_count"] == 7
        assert identity["arc_sha256"] == preparer.ARC_SHA256
        assert identity["initial_world_sha256"] == preparer.WORLD_SHA256
        assert config["maintenance_protocol"] == "turn-maintenance-v3"
        assert config["budget_path"] == str(budget)
        assert not budget.exists()
        assert not Path(result["run_output"]).exists()
        weights = read_json(Path(temporary) / "fresh/model-weights.json")
        assert config["model_identity"]["host"]["weights_sha256"] == digest(weights["host"])
        freeze = read_json(Path(result["freeze"]))
        assert "tools/prepare_contextual_v9.py" in freeze["source_sha256"]
        assert "src/milai_lab/runners/contextual_session.py" in freeze["source_sha256"]
        assert "data/manifests/contextual-memory-v9-document-sequence.json" in (
            freeze["source_sha256"]
        )


def test_prepare_v10_notes_and_basis_reuse_same_pinned_arc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_dir, embedding_dir = tmp_path / "host", tmp_path / "embedding"
    host_dir.mkdir()
    embedding_dir.mkdir()
    for name in ("layers-0.safetensors", "config.json", "tokenizer.json",
                 "tokenizer_config.json", "chat_template.jinja"):
        (host_dir / name).write_text("{}")
    for name in ("pytorch_model.bin", "config.json", "tokenizer.json",
                 "tokenizer_config.json"):
        (embedding_dir / name).write_text("{}")
    pinned = read_json(preparer.PINNED_SELECTION)
    managed = preparer.LAB / "artifacts/contextual-user-memory"
    managed.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v10-prepare-test-", dir=managed) as temporary:
        local = Path(temporary)
        template_paths = {policy: local / f"{policy}-template.json"
                          for policy in ("notes", "basis")}
        monkeypatch.setattr(preparer, "V10_TEMPLATES", tuple(
            preparer._within_lab(path) for path in template_paths.values()
        ))
        for policy, path in template_paths.items():
            template = read_json(preparer.TEMPLATE)
            template.update(config_version="contextual-task-v10", decision_policy=policy,
                            decision_feedback=policy == "basis",
                            decision_gap_focus=policy == "basis")
            write_json(path, template)
        mappings = []
        for policy, arm in (("notes", "react_notes_v10_off"),
                            ("basis", "decision_basis_v10_off")):
            template_path = template_paths[policy]
            result = preparer.prepare(
                output_dir=local / policy, merit_root=Path(pinned["external_root"]),
                host_dir=host_dir, embedding_dir=embedding_dir,
                host_url="http://host.test/v1/", embedding_url="http://embed.test/v1/",
                budget_path=tmp_path / "shared-budget.json", template_path=template_path,
            )
            selection, config, _, _, _, _, _, diagnostic, _ = merit.prepared_inputs(
                Path(result["selection"]), Path(result["config"]), Path(result["freeze"]),
            )
            assert selection["execution_plan"]["arms"] == [arm]
            assert config["decision_policy"] == policy
            assert diagnostic["episode_count"] == 5
            mapping = read_json(Path(result["freeze"]))["source_sha256"]
            mappings.append(mapping)
            assert all(preparer._within_lab(path) in mapping
                       for path in template_paths.values())
        assert mappings[0] == mappings[1]


def test_prepare_v11_three_arms_share_source_identity_on_exposed_arc(tmp_path: Path) -> None:
    host_dir, embedding_dir = tmp_path / "host", tmp_path / "embedding"
    host_dir.mkdir()
    embedding_dir.mkdir()
    for name in ("layers-0.safetensors", "config.json", "tokenizer.json",
                 "tokenizer_config.json", "chat_template.jinja"):
        (host_dir / name).write_text("{}")
    for name in ("pytorch_model.bin", "config.json", "tokenizer.json",
                 "tokenizer_config.json"):
        (embedding_dir / name).write_text("{}")
    pinned = read_json(preparer.PINNED_SELECTION)
    managed = preparer.LAB / "artifacts/contextual-user-memory"
    managed.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v11-prepare-test-", dir=managed) as temporary:
        mappings = []
        for short, arm in (("notes", "react_notes_v11_off"),
                           ("sparse", "sparse_basis_v11_off"),
                           ("attention", "sparse_basis_attention_v11_off")):
            result = preparer.prepare(
                output_dir=Path(temporary) / short,
                merit_root=Path(pinned["external_root"]),
                host_dir=host_dir, embedding_dir=embedding_dir,
                host_url="http://host.test/v1/", embedding_url="http://embed.test/v1/",
                budget_path=tmp_path / "shared-budget.json",
                template_path=preparer.LAB / f"configs/contextual-memory-v11-{short}-template.json",
            )
            selection, config, identity, _, _, _, _, diagnostic, _ = merit.prepared_inputs(
                Path(result["selection"]), Path(result["config"]), Path(result["freeze"]),
            )
            assert selection["execution_plan"]["arms"] == [arm]
            assert config["config_version"] == "contextual-task-v11"
            assert diagnostic["episode_count"] == 5
            assert identity["selection_template_sha256"] == preparer.file_sha256(
                preparer.PINNED_SELECTION
            )
            mappings.append(read_json(Path(result["freeze"]))["source_mapping_sha256"])
        assert len(set(mappings)) == 1


def test_prepare_accepts_a_frozen_nondefault_arc_identity_without_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned = read_json(preparer.PINNED_SELECTION)
    arcs, native_tools, metrics, runner = merit.pinned_merit(pinned)
    original = arcs.generate_suite(**pinned["generator_arguments"])[0]
    fixture_arc = replace(original, arc_id="fixture-other-arc", seed=123)
    fixture_bytes = json.dumps(asdict(fixture_arc), ensure_ascii=False,
                               sort_keys=True, separators=(",", ":")).encode()
    world = fixture_arc.make_world()
    try:
        world_sha = hashlib.sha256(world.dump_json().encode()).hexdigest()
    finally:
        world.conn.close()
    selection = read_json(preparer.PINNED_SELECTION)
    selection["arc_id"] = fixture_arc.arc_id
    selection["arc_seed"] = fixture_arc.seed
    selection["private_artifacts"]["arc_sha256"] = hashlib.sha256(fixture_bytes).hexdigest()
    selection["private_artifacts"]["initial_world_sha256"] = world_sha
    managed = preparer.LAB / "artifacts/contextual-user-memory"
    managed.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v11-other-arc-fixture-", dir=managed) as temp:
        local = Path(temp)
        selection_template = local / "frozen-selection.json"
        write_json(selection_template, selection)
        fixture_arcs = SimpleNamespace(generate_suite=lambda **_: [fixture_arc])
        monkeypatch.setattr(merit, "pinned_merit",
                            lambda _: (fixture_arcs, native_tools, metrics, runner))
        host_dir, embedding_dir = local / "host", local / "embedding"
        host_dir.mkdir()
        embedding_dir.mkdir()
        for name in ("layers-0.safetensors", "config.json", "tokenizer.json",
                     "tokenizer_config.json", "chat_template.jinja"):
            (host_dir / name).write_text("{}")
        for name in ("pytorch_model.bin", "config.json", "tokenizer.json",
                     "tokenizer_config.json"):
            (embedding_dir / name).write_text("{}")
        result = preparer.prepare(
            output_dir=local / "prepared", merit_root=Path(pinned["external_root"]),
            host_dir=host_dir, embedding_dir=embedding_dir,
            host_url="http://host.test/v1/", embedding_url="http://embed.test/v1/",
            budget_path=tmp_path / "shared-budget.json",
            template_path=preparer.LAB / "configs/contextual-memory-v11-attention-template.json",
            selection_template_path=selection_template,
        )
        selected, _, _, arc, _, _, _, _, _ = merit.prepared_inputs(
            Path(result["selection"]), Path(result["config"]), Path(result["freeze"]),
        )
        assert selected["arc_id"] == arc.arc_id == "fixture-other-arc"
        assert Path(result["selection"]).parent.joinpath(
            "fixture-other-arc.original.json"
        ).exists()
        selection_template.write_text(selection_template.read_text() + " ")
        with pytest.raises(ValueError, match="MERIT_SELECTION_TEMPLATE_CHANGED"):
            merit.prepared_inputs(Path(result["selection"]), Path(result["config"]),
                                  Path(result["freeze"]))


@pytest.mark.parametrize(("template", "arm", "protocol"), [
    (preparer.V12_TEMPLATES[0], "react_notes_v12_off", "turn-maintenance-v4"),
    (preparer.V14_TEMPLATES[0], "react_notes_v14_off", "turn-maintenance-v5"),
])
def test_prepare_current_notes_preserves_repair_protocol_and_rejects_other_controls(
    tmp_path: Path, template: str, arm: str, protocol: str,
) -> None:
    host_dir, embedding_dir = tmp_path / "host", tmp_path / "embedding"
    host_dir.mkdir()
    embedding_dir.mkdir()
    for name in ("layers-0.safetensors", "config.json", "tokenizer.json",
                 "tokenizer_config.json", "chat_template.jinja"):
        (host_dir / name).write_text("{}")
    for name in ("pytorch_model.bin", "config.json", "tokenizer.json",
                 "tokenizer_config.json"):
        (embedding_dir / name).write_text("{}")
    pinned = read_json(preparer.PINNED_SELECTION)
    managed = preparer.LAB / "artifacts/contextual-user-memory"
    budget = tmp_path / "v13-budget.json"
    with tempfile.TemporaryDirectory(prefix="current-notes-prepare-", dir=managed) as temporary:
        result = preparer.prepare(
            output_dir=Path(temporary) / "prepared",
            merit_root=Path(pinned["external_root"]),
            host_dir=host_dir, embedding_dir=embedding_dir,
            host_url="http://host.test/v1/", embedding_url="http://embed.test/v1/",
            budget_path=budget,
            template_path=preparer.LAB / template,
        )
        selection_path = Path(result["selection"])
        config_path = Path(result["config"])
        freeze_path = Path(result["freeze"])
        selected, config, identity, _, _, _, _, diagnostic, _ = merit.prepared_inputs(
            selection_path, config_path, freeze_path,
        )
        assert selected["execution_plan"]["arms"] == [arm]
        assert config["maintenance_protocol"] == protocol
        assert config["host"]["enable_thinking"] is False
        assert config["capacity"]["enable_thinking"] is False
        assert diagnostic["user_message_count"] == 7
        assert identity["arc_sha256"] == preparer.ARC_SHA256
        assert not budget.exists()
        assert not Path(result["run_output"]).exists()
        frozen = read_json(freeze_path)
        assert template in frozen["source_sha256"]
        if arm == "react_notes_v14_off":
            assert "tools/run_contextual_semantic_v14.py" in frozen["source_sha256"]

        original = read_json(config_path)
        for field, value in (("decision_gap_focus", True),
                             ("maintenance_protocol", "turn-maintenance-v3")):
            write_json(config_path, {**original, field: value})
            selected["config_sha256"] = merit.sha256(config_path)
            write_json(selection_path, selected)
            with pytest.raises(ValueError, match="MERIT_ARM_CONFIG_MISMATCH"):
                merit.prepared_inputs(selection_path, config_path, freeze_path)
