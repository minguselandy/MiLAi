"""Pinned, exposed MERIT arc input with scorer material kept outside the agent."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import read_json


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_exposed_arc(selection_path: Path) -> tuple[dict[str, Any], Any, Any, Any, Any]:
    """Regenerate only the already exposed seed-0 arc and verify its original bytes."""
    selection = read_json(selection_path)
    if (
        selection["dataset"] != "MERIT"
        or selection["source_commit"] != "293933d96b1d1849e1f20d1bb324def5de9ed33f"
        or selection["generator_arguments"] != {
            "n_arcs": 1, "episodes_per_arc": 5, "dep_ratio": 0.5,
            "base_seed": 0, "difficulty": "hard",
        }
    ):
        raise ValueError("MERIT_EXPOSED_SELECTION_CHANGED")
    return load_frozen_arc(selection_path)


def load_frozen_arc(selection_path: Path) -> tuple[dict[str, Any], Any, Any, Any, Any]:
    """Regenerate one declared arc and bind it to its frozen bytes and world."""
    selection = read_json(selection_path)
    arguments = selection["generator_arguments"]
    if (selection["dataset"] != "MERIT"
            or selection["source_commit"] != "293933d96b1d1849e1f20d1bb324def5de9ed33f"
            or selection["generator"] != "merit.arcs.generate_suite"
            or not isinstance(arguments, dict)
            or set(arguments) != {"n_arcs", "episodes_per_arc", "dep_ratio",
                                  "base_seed", "difficulty"}
            or arguments["n_arcs"] != 1):
        raise ValueError("MERIT_FROZEN_SELECTION_CHANGED")
    root = Path(selection["external_root"]).resolve()
    for relative, expected in selection["source_sha256"].items():
        if _sha256(root / relative) != expected:
            raise ValueError(f"MERIT_SOURCE_CHANGED:{relative}")
    package_dir = root / "merit"
    package_name = f"_milai_pinned_merit_{hashlib.sha256(str(root).encode()).hexdigest()[:12]}"
    package = sys.modules.get(package_name)
    if package is None:
        spec = importlib.util.spec_from_file_location(
            package_name,
            package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise ValueError("MERIT_PACKAGE_SPEC_MISSING")
        package = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = package
        spec.loader.exec_module(package)
    parts = ("arcs", "tools", "metrics", "runner")
    modules = [importlib.import_module(f"{package_name}.{part}") for part in parts]
    if (
        package.__file__ is None
        or Path(package.__file__).resolve() != (package_dir / "__init__.py").resolve()
        or any(module.__file__ is None or Path(module.__file__).resolve()
               != (package_dir / f"{part}.py").resolve()
               for part, module in zip(parts, modules, strict=True))
        or any(module.__file__ is None or not Path(module.__file__).resolve().is_relative_to(
            package_dir
        ) for name, module in sys.modules.items() if name.startswith(package_name + "."))
    ):
        raise ValueError("MERIT_IMPORT_OUTSIDE_PINNED_ROOT")
    arcs, tools, metrics, native_runner = modules
    (arc,) = arcs.generate_suite(**selection["generator_arguments"])
    payload = json.dumps(asdict(arc), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode()
    pinned = selection["private_artifacts"]
    if (
        arc.arc_id != selection["arc_id"]
        or hashlib.sha256(payload).hexdigest() != pinned["arc_sha256"]
        or payload != Path(pinned["arc"]).read_bytes()
        or len(arc.episodes) != selection["episode_count"]
        or sum(item.task.dependent for item in arc.episodes)
        != selection["dependent_episode_count"]
        or sum(len(item.task.user_messages) for item in arc.episodes)
        != selection["user_message_count"]
    ):
        raise ValueError("MERIT_ARC_IDENTITY_MISMATCH")
    world = arc.make_world()
    try:
        if _sha256(Path(pinned["initial_world"])) != pinned["initial_world_sha256"]:
            raise ValueError("MERIT_PINNED_WORLD_CHANGED")
        if world.dump_json().encode() != Path(pinned["initial_world"]).read_bytes():
            raise ValueError("MERIT_INITIAL_WORLD_CHANGED")
    finally:
        world.conn.close()
    return selection, arc, tools, metrics, native_runner
