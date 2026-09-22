from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("classify_changes.py")
SPEC = importlib.util.spec_from_file_location("classify_changes", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
classify = MODULE.classify


class ChangeClassifierTest(unittest.TestCase):
    def test_runtime_only_stays_fast(self) -> None:
        result = classify(["MiLAi-Product/runtime/src/milai/application/example.py"])
        self.assertIs(result["runtime"], True)
        self.assertIs(result["mcp"], False)
        self.assertIs(result["full_required"], False)
        self.assertEqual(result["integration_matrix"], {"package": []})

    def test_each_integration_maps_to_its_package(self) -> None:
        result = classify(["MiLAi-Product/integrations/openworker-mcp/src/host.py"])
        self.assertIs(result["openworker"], True)
        self.assertEqual(result["integration_matrix"], {"package": ["openworker-mcp"]})
        self.assertIs(result["full_required"], False)

    def test_cross_subsystem_and_ci_changes_require_full(self) -> None:
        cross = classify(
            [
                "MiLAi-Product/runtime/src/milai/example.py",
                "MiLAi-Product/integrations/mcp/src/server.py",
            ]
        )
        ci = classify([".github/workflows/ci.yml"])
        self.assertIs(cross["full_required"], True)
        self.assertIs(ci["full_required"], True)

    def test_lab_and_archive_have_independent_fast_gates(self) -> None:
        lab = classify(["MiLAi-Lab/src/milai_lab/example.py"])
        archive = classify(["MiLAi-Artifact-Archive/catalogs/example.json"])
        self.assertIs(lab["lab"], True)
        self.assertIs(lab["archive"], False)
        self.assertIs(archive["archive"], True)
        self.assertIs(archive["lab"], False)

    def test_explicit_full_request_selects_every_job(self) -> None:
        result = classify([], full_requested=True)
        self.assertIs(result["full_run"], True)
        self.assertTrue(all(result[name] is True for name in MODULE.CLASSIFICATIONS))
        self.assertEqual(result["integration_count"], 6)

    def test_lab_status_docs_only_do_not_select_package_tests(self) -> None:
        result = classify([
            "MiLAi-Lab/docs/LAB_CURRENT_STATUS.md",
            "MiLAi-Lab/docs/LAB_GOALS.md",
            "MiLAi-Product/docs/PRODUCT_CURRENT_STATUS.md",
        ])
        self.assertFalse(any(result[name] for name in MODULE.CLASSIFICATIONS))
        self.assertFalse(result["full_required"])
        self.assertEqual(len(result["changed_paths"]), 3)

    def test_lab_docs_do_not_suppress_any_behavior_bearing_path(self) -> None:
        for path in (
            "MiLAi-Lab/src/milai_lab/example.py",
            "MiLAi-Lab/tests/test_example.py",
            "MiLAi-Lab/tools/example.py",
            "MiLAi-Lab/configs/prompt.md",
            "MiLAi-Lab/docs/contract.json",
            "MiLAi-Lab/docs/check.py",
            "MiLAi-Lab/pyproject.toml",
            "MiLAi-Lab/uv.lock",
        ):
            with self.subTest(path=path):
                result = classify(["MiLAi-Lab/docs/LAB_GOALS.md", path])
                self.assertTrue(result["lab"])

    def test_lab_docs_do_not_expand_runtime_scope_or_disable_explicit_full(self) -> None:
        paths = [
            "MiLAi-Lab/docs/LAB_CURRENT_STATUS.md",
            "MiLAi-Product/runtime/tests/integration/test_worker_once.py",
        ]
        result = classify(paths)
        self.assertTrue(result["runtime"])
        self.assertFalse(result["lab"])
        self.assertFalse(result["full_required"])
        full = classify(paths, full_requested=True)
        self.assertTrue(all(full[name] for name in MODULE.CLASSIFICATIONS))


if __name__ == "__main__":
    unittest.main()
