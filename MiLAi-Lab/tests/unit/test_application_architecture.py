"""Application ownership, compatibility imports and source identity regressions."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[2]


def test_application_layer_has_no_runner_imports() -> None:
    package = LAB / "src/milai_lab/application"
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                modules = [importlib.util.resolve_name(
                    "." * node.level + module, "milai_lab.application")
                    if node.level else module]
            assert all(not module.startswith("milai_lab.runners") for module in modules), path
            if path.name in {"__init__.py", "world.py"}:
                assert all(module.split(".")[0] in sys.stdlib_module_names
                           for module in modules), path


def test_world_import_needs_no_optional_model_dependencies() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        "from milai_lab.application.world import ApplicationWorld; "
        "assert ApplicationWorld._receipt(ok=True) == '{\"ok\": true}'; "
        "assert not any(name.startswith(('langmem', 'langchain', 'langgraph', "
        "'milai_lab.runners', 'milai_lab.methods.local_state_attention')) "
        "for name in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-S", "-c", code],  # noqa: S603
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_old_application_imports_are_the_canonical_objects() -> None:
    from milai_lab.application import journal, recovery, tools, world
    from milai_lab.methods import memory_lifecycle
    from milai_lab.runners import langmem_application, langmem_foundation

    assert langmem_foundation.BusinessActionJournal is journal.BusinessActionJournal
    assert langmem_foundation.UnknownBusinessAction is journal.UnknownBusinessAction
    assert langmem_foundation.native_business_tools is tools.native_business_tools
    assert memory_lifecycle.BusinessActionJournal is journal.BusinessActionJournal
    assert langmem_application.ApplicationWorld is world.ApplicationWorld
    assert langmem_application.uuid is world.uuid
    assert langmem_application.BUSINESS_SCHEMAS is tools.BUSINESS_SCHEMAS
    assert langmem_application.BUSINESS_NAMES is tools.BUSINESS_NAMES
    assert langmem_application._business_tools is tools._business_tools
    assert (langmem_application.recover_pending_application_call
            is recovery.recover_pending_application_call)
    # Existing catalog consumers inspect schemas without executing the world closures.
    assert [tool.name for tool in tools._business_tools(None, "schema-only")] == (
        tools.BUSINESS_NAMES)


def test_explicit_identities_bind_all_canonical_application_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.application import APPLICATION_SOURCE_FILES
    from milai_lab.baselines import langmem_b1_identity, langmem_identity
    from milai_lab.harness.source_identity import REQUEST_SOURCE_FILES
    from milai_lab.methods.freshness_projection import identity

    required = set(APPLICATION_SOURCE_FILES)
    assert required == {path.relative_to(LAB).as_posix()
                        for path in (LAB / "src/milai_lab/application").glob("*.py")}
    assert required <= langmem_b1_identity.REQUIRED_OVERLAY
    assert required <= identity.REQUIRED_APPLICATION_V25_RUNTIME
    assert required <= identity.REQUIRED_LIFECYCLE_V24_RUNTIME
    monkeypatch.syspath_prepend(str(LAB / "tools"))
    entry = importlib.import_module("run_langmem_foundation")
    config = tmp_path / "config.json"
    config.write_text("{}")
    settings = {"checkpoint_path": str(tmp_path / "checkpoints.sqlite")}
    entry._verify_development_spike(config, settings, "architecture")
    receipt = json.loads(next(tmp_path.glob("spike-identity-*.json")).read_text())
    assert required <= receipt["source_sha256"].keys()
    original_sha = entry.sha256_file
    monkeypatch.setattr(entry, "sha256_file", lambda path: (
        "0" * 64 if path == LAB / "src/milai_lab/application/journal.py"
        else original_sha(path)))
    with pytest.raises(ValueError, match="DEVELOPMENT_SPIKE_IDENTITY_CHANGED"):
        entry._verify_development_spike(config, settings, "architecture")

    # A fresh synthetic lock cannot omit implementation hashes or accept tampered bytes.
    monkeypatch.setattr(langmem_identity, "LAB", tmp_path)
    for relative in ("uv.lock", "pyproject.toml", "upstream.json", *APPLICATION_SOURCE_FILES,
                     *REQUEST_SOURCE_FILES):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic identity input\n")
    sha = langmem_identity.sha256_file
    lock = {
        "status": "FROZEN", "upstream_manifest": "upstream.json",
        "uv_lock_sha256": sha(tmp_path / "uv.lock"),
        "pyproject_sha256": sha(tmp_path / "pyproject.toml"),
        "upstream_manifest_sha256": sha(tmp_path / "upstream.json"),
        "recipe_id": langmem_identity.RECIPE_ID, "transport_variant": "json_action",
        "generation_schema_variant": "free_order_arguments_v1",
        "system_prompt": langmem_identity.SYSTEM_PROMPT,
        "system_prompt_sha256": hashlib.sha256(langmem_identity.SYSTEM_PROMPT.encode()).hexdigest(),
        "namespace": list(langmem_identity.MEMORY_NAMESPACE), "source_sha256": {},
    }
    lock_path = tmp_path / "new-lock.json"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="FOUNDATION_APPLICATION_SOURCE_MAP_MISSING"):
        langmem_identity.verify_foundation_lock(lock_path, config)
    lock["source_sha256"] = {relative: sha(tmp_path / relative)
                             for relative in (*APPLICATION_SOURCE_FILES, *REQUEST_SOURCE_FILES)}
    lock_path.write_text(json.dumps(lock))
    (tmp_path / APPLICATION_SOURCE_FILES[-1]).write_text("changed implementation\n")
    with pytest.raises(ValueError, match=r"FOUNDATION_SOURCE_CHANGED:.*application/recovery"):
        langmem_identity.verify_foundation_lock(lock_path, config)
