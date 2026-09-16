from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BUNDLE_ROOT.parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
LOCK_SCOPE = os.environ.get("MILAI_ARCHITECTURE_LOCK_SCOPE", "all")
sys.path.insert(0, str(BUNDLE_ROOT / "scripts"))

from refresh_manifest import refresh_manifest
from validate_bundle import collect_errors, validate_crosswalk
from verify_lock import collect_hash_errors


class ArchitectureBundleTest(unittest.TestCase):
    def test_current_bundle_is_structurally_valid(self) -> None:
        self.assertEqual(collect_errors(BUNDLE_ROOT, PROJECT_ROOT), [])

    def test_current_bundle_hash_lock_is_valid(self) -> None:
        self.assertEqual(
            collect_hash_errors(
                BUNDLE_ROOT,
                PROJECT_ROOT,
                WORKSPACE_ROOT,
                scope=LOCK_SCOPE,
            ),
            [],
        )

    def test_missing_invariant_is_rejected(self) -> None:
        data = json.loads((BUNDLE_ROOT / "crosswalk.json").read_text(encoding="utf-8"))
        changed = copy.deepcopy(data)
        changed["invariants"] = [
            item for item in changed["invariants"] if item["id"] != "I-12"
        ]
        errors = validate_crosswalk(changed, PROJECT_ROOT)
        self.assertTrue(
            any("invariants ID set mismatch" in error for error in errors), errors
        )

    def test_invariant_without_negative_evidence_is_rejected(self) -> None:
        data = json.loads((BUNDLE_ROOT / "crosswalk.json").read_text(encoding="utf-8"))
        changed = copy.deepcopy(data)
        changed["invariants"][0]["negative_tests"] = []
        errors = validate_crosswalk(changed, PROJECT_ROOT)
        self.assertTrue(
            any(
                "I-01.negative_tests.tests must be a non-empty list" in error
                for error in errors
            ),
            errors,
        )

    def test_missing_required_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            (copied / "OBJECTS.md").unlink()
            errors = collect_errors(copied, PROJECT_ROOT)
            self.assertIn("missing required artifact: OBJECTS.md", errors)

    def test_unreviewed_candidate_cannot_claim_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            review_path = copied / "FREEZE_REVIEW.md"
            review_path.write_text(
                review_path.read_text(encoding="utf-8").replace(
                    "Decision：`PENDING`",
                    "Decision：`ACCEPT`",
                    1,
                ),
                encoding="utf-8",
            )
            errors = collect_errors(copied, PROJECT_ROOT)
            self.assertIn(
                "FREEZE_REVIEW candidate state missing: Decision：`PENDING`",
                errors,
            )

    def test_manifest_cannot_claim_unreviewed_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["review"] = {
                "gate": "AF-09",
                "status": "ACCEPTED",
                "independent_reviewer": "forged-reviewer",
                "decision": "ACCEPT",
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = collect_errors(copied, PROJECT_ROOT)
            self.assertIn(
                "manifest.review must remain the unsigned AF-09 pending review record",
                errors,
            )

    def test_author_preflight_cannot_claim_independent_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            preflight_path = copied / "AUTHOR_PREFLIGHT.md"
            preflight_path.write_text(
                preflight_path.read_text(encoding="utf-8").replace(
                    "Independent decision: PENDING",
                    "Independent decision: ACCEPT",
                    1,
                ),
                encoding="utf-8",
            )
            errors = collect_errors(copied, PROJECT_ROOT)
            self.assertIn(
                "AUTHOR_PREFLIGHT boundary missing: Independent decision: PENDING",
                errors,
            )

    def test_omitted_required_bundle_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["locked_files"] = [
                entry
                for entry in manifest["locked_files"]
                if entry["path"] != "OBJECTS.md"
            ]
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = collect_errors(copied, PROJECT_ROOT)
            self.assertTrue(
                any("locked_files must exactly cover" in error for error in errors),
                errors,
            )

    def test_omitted_crosswalk_source_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            omitted = "runtime/src/milai/application/query_planner.py"
            manifest["source_locks"] = [
                entry for entry in manifest["source_locks"] if entry["path"] != omitted
            ]
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = collect_errors(copied, PROJECT_ROOT)
            self.assertIn(
                f"crosswalk reference is not project source-locked: {omitted}",
                errors,
            )

    def test_locked_file_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            with (copied / "OBJECTS.md").open("a", encoding="utf-8") as handle:
                handle.write("\nunauthorized drift\n")
            errors = collect_hash_errors(
                copied,
                PROJECT_ROOT,
                WORKSPACE_ROOT,
                scope=LOCK_SCOPE,
            )
            self.assertTrue(
                any("hash drift: bundle:OBJECTS.md" in error for error in errors),
                errors,
            )

    def test_path_escape_in_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["locked_files"][0]["path"] = "../outside"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = collect_hash_errors(
                copied,
                PROJECT_ROOT,
                WORKSPACE_ROOT,
                scope=LOCK_SCOPE,
            )
            self.assertTrue(
                any("unsafe relative path" in error for error in errors), errors
            )

    def test_git_commit_drift_is_rejected(self) -> None:
        if LOCK_SCOPE != "all":
            self.skipTest("complete workspace Git locks are unavailable in this scope")
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["git_locks"][0]["commit"] = "0" * 40
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = collect_hash_errors(copied, PROJECT_ROOT, WORKSPACE_ROOT)
            self.assertTrue(
                any("git commit drift" in error for error in errors), errors
            )

    def test_unknown_lock_scope_is_rejected(self) -> None:
        errors = collect_hash_errors(
            BUNDLE_ROOT,
            PROJECT_ROOT,
            WORKSPACE_ROOT,
            scope="unsafe",
        )
        self.assertEqual(errors, ["unknown verification scope: 'unsafe'"])

    def test_review_mode_requires_external_manifest_trust_anchor(self) -> None:
        errors = collect_hash_errors(
            BUNDLE_ROOT,
            PROJECT_ROOT,
            WORKSPACE_ROOT,
            scope="bundle",
            verification_mode="review",
        )
        self.assertEqual(
            errors,
            ["review verification requires an external expected manifest SHA-256"],
        )

    def test_review_mode_rejects_external_manifest_digest_mismatch(self) -> None:
        errors = collect_hash_errors(
            BUNDLE_ROOT,
            PROJECT_ROOT,
            WORKSPACE_ROOT,
            scope="bundle",
            verification_mode="review",
            expected_manifest_sha256="0" * 64,
        )
        self.assertTrue(
            any("external manifest trust anchor mismatch" in error for error in errors),
            errors,
        )

    def test_coordinated_bundle_and_manifest_tamper_fails_external_anchor(self) -> None:
        trusted_digest = hashlib.sha256(
            (BUNDLE_ROOT / "architecture_manifest.json").read_bytes()
        ).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            object_path = copied / "OBJECTS.md"
            object_path.write_text(
                object_path.read_text(encoding="utf-8") + "\ncoordinated tamper\n",
                encoding="utf-8",
            )
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            replacement_hash = hashlib.sha256(object_path.read_bytes()).hexdigest()
            for entry in manifest["locked_files"]:
                if entry["path"] == "OBJECTS.md":
                    entry["sha256"] = replacement_hash
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = collect_hash_errors(
                copied,
                PROJECT_ROOT,
                WORKSPACE_ROOT,
                scope="bundle",
                verification_mode="review",
                expected_manifest_sha256=trusted_digest,
            )
        self.assertTrue(
            any("external manifest trust anchor mismatch" in error for error in errors),
            errors,
        )

    def test_manifest_refresh_updates_only_declared_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            rogue = copied / "NOT_DECLARED.txt"
            rogue.write_text("must not be discovered\n", encoding="utf-8")
            manifest_path = copied / "architecture_manifest.json"
            before = json.loads(manifest_path.read_text(encoding="utf-8"))
            before_paths = {
                (entry.get("base", "bundle"), entry["path"])
                for collection in ("locked_files", "source_locks")
                for entry in before[collection]
            }
            before["locked_files"][0]["sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(before, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            refreshed = refresh_manifest(
                copied, PROJECT_ROOT, WORKSPACE_ROOT, write=True
            )
            after_paths = {
                (entry.get("base", "bundle"), entry["path"])
                for collection in ("locked_files", "source_locks")
                for entry in refreshed[collection]
            }
            self.assertEqual(after_paths, before_paths)
            self.assertNotIn(("bundle", rogue.name), after_paths)
            self.assertNotEqual(refreshed["locked_files"][0]["sha256"], "0" * 64)

    def test_manifest_refresh_rejects_manifest_self_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE_ROOT, copied)
            manifest_path = copied / "architecture_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["locked_files"].append(
                {"path": "architecture_manifest.json", "sha256": "0" * 64}
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "must not self-lock"):
                refresh_manifest(copied, PROJECT_ROOT, WORKSPACE_ROOT, write=False)


if __name__ == "__main__":
    unittest.main()
