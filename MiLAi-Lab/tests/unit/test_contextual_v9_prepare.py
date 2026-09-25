"""A tiny local model fixture proves v9 preparation without provider calls."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from milai_lab.harness.contextual_artifacts import digest, read_json

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
