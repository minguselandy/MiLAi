"""Scoped artifact/reference gates, not a complete execution coordinator.

The baseline uses a consistent mode=ro SQL transaction (which may remain open
while existing files are verified), never a writer lock. Independent auditors
run after that connection closes, against a defensive read-only reference
facade. After scope close, a short write transaction rechecks exact SQL state,
fresh dynamic evidence and deadlines before registration. No HTTP is sent.
Finish and P3-gate derivation are intentionally not implemented here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_batch_v2 import REVISION
from v0222_presentation_batch_v2 import Batch as CoreBatch
from v0222_presentation_references import KINDS
from v0222_scoped_evidence import _strict_json

TABLE_QUERIES = {
    "meta": "SELECT * FROM meta ORDER BY key",
    "episodes": "SELECT * FROM episodes ORDER BY stage,ordinal",
    "claims": "SELECT * FROM claims ORDER BY episode",
    "launches": "SELECT * FROM launches ORDER BY stage",
    "events": "SELECT * FROM events ORDER BY seq",
    "artifacts": "SELECT * FROM artifacts ORDER BY name",
}
FREEZABLE = {
    "scope_review",
    "engineering_checks",
    "P3_references",
    "P4_references",
    "P3_preflight",
    "P4_preflight",
    "P4_resolved_specs",
    "P_full_preparation",
}
SCOPE_PREREQUISITES = (
    "engineering_checks",
    "P3_references",
    "P4_references",
    "P4_resolved_specs",
    "P_full_preparation",
)


class AuditView:
    """No live Batch/SQL callbacks; every returned business object is a copy."""

    def __init__(
        self,
        root: Path,
        plan: dict,
        references: dict,
        *,
        binding_sha=None,
        artifacts=None,
        control_pins=None,
    ):
        self._root = root
        self._plan = copy.deepcopy(plan)
        self._references = copy.deepcopy(references)
        self.binding_sha = binding_sha
        self._artifacts = copy.deepcopy(artifacts or {})
        self._control_pins = copy.deepcopy(control_pins or {})

    @property
    def root(self):
        return self._root

    @property
    def plan(self):
        return copy.deepcopy(self._plan)

    def spec(self, episode):
        for stage in ("P3", "P4"):
            for spec in self._plan[stage]:
                if spec["id"] == episode:
                    return copy.deepcopy(spec)
        raise ProviderStop("AUDIT_EPISODE_OUTSIDE_SNAPSHOT")

    def references(self, stage):
        if stage not in self._references:
            raise ProviderStop("AUDIT_REFERENCE_STAGE_NOT_SNAPSHOTTED")
        return copy.deepcopy(self._references[stage])

    def frozen_artifact(self, name):
        return copy.deepcopy(self._artifacts[name])

    @property
    def control_pins(self):
        return copy.deepcopy(self._control_pins)


class Batch(CoreBatch):
    def _capture_artifacts(self, db, scope, names):
        captured = {}
        for name in names:
            value = self._artifact(db, name, scope)
            row = dict(db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone())
            captured[name] = {"row": row, "value": value}
        return captured

    def _scope_control_pins(self, scope):
        binding = scope.read_json(self.root / "execution-binding.json", self.binding_sha)
        if set(binding) != {"authorization.json", "authorization-source.json", "manifest.json"}:
            raise ProviderStop("EXACT_EXECUTION_BINDING_REQUIRED")
        pins = {str(self.root / "execution-binding.json"): self.binding_sha}
        for name, digest in binding.items():
            scope.read_json(self.root / name, digest)
            pins[str(self.root / name)] = digest
        return pins

    def _ready(self, db, stage, scope):
        super()._ready(db, stage, scope)
        artifacts = self._capture_artifacts(db, scope, SCOPE_PREREQUISITES)
        view = AuditView(
            self.root,
            self.plan,
            {},
            binding_sha=self.binding_sha,
            artifacts=artifacts,
            control_pins=self._scope_control_pins(scope),
        )
        self._scope_review(self._artifact(db, "scope_review", scope), view)

    @contextmanager
    def _gate_failure(self):
        try:
            yield
        except BaseException as exc:
            # SQL and scope contexts have already unwound before this handler.
            try:
                self.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
            except BaseException as secondary:
                exc.add_note("SECONDARY_STOP_FAILURE: " + type(secondary).__name__)
            raise

    @staticmethod
    def _table_snapshot(db):
        return {
            table: [dict(row) for row in db.execute(query)]
            for table, query in TABLE_QUERIES.items()
        }

    @contextmanager
    def _gate_baseline(self, scope):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            binding = db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
            if binding is None or binding[0] != self.binding_sha:
                raise ProviderStop("COORDINATOR_BINDING_DRIFT")
            self._check_journal(db, scope)
            snapshot = self._table_snapshot(db)
            yield db, snapshot

    def _gate_final(self, db, snapshot, auth, stage, plan):
        """Fresh final checks only; no closed scope or cached SQL is consulted."""
        if fingerprint(self._table_snapshot(db)) != fingerprint(snapshot):
            raise ProviderStop("GATE_SQL_CHANGED_DURING_AUDIT")
        if fingerprint(self.auth) != fingerprint(auth) or fingerprint(self.plan) != fingerprint(
            plan
        ):
            raise ProviderStop("IN_MEMORY_AUTHORIZATION_OR_PLAN_DRIFT")
        self._time_check(auth)
        if db.execute("SELECT 1 FROM meta WHERE key='stop'").fetchone():
            raise ProviderStop("BATCH_STOPPED_NO_RETRY")
        self._mirrors(db)
        rows = [dict(row) for row in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")]
        self._check_claims(db, rows)
        marker = _strict_json((self.root / "coordinator-created.json").read_text())
        if fingerprint(marker) != fingerprint({"binding_sha256": self.binding_sha}):
            raise ProviderStop("COORDINATOR_INITIALIZATION_MARKER_DRIFT")
        for launch in db.execute("SELECT * FROM launches ORDER BY stage"):
            actual = _strict_json(
                (self.root / ("live-launch-" + launch["stage"] + ".json")).read_text()
            )
            if fingerprint(actual) != fingerprint(
                {
                    "stage": launch["stage"],
                    "pid": launch["pid"],
                    "unix": launch["started"],
                    "binding_sha256": self.binding_sha,
                }
            ):
                raise ProviderStop("LAUNCH_MARKER_DRIFT")
        for row in rows:
            if row["status"] == "RUNNING" and (
                type(row["deadline"]) not in (int, float)
                or not math.isfinite(row["deadline"])
                or time.time() >= row["deadline"]
            ):
                raise ProviderStop("EPISODE_DEADLINE")
        if stage in {"P3", "P4"}:
            deadline = db.execute(
                "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
            ).fetchone()
            if deadline is not None and time.time() >= float(deadline[0]):
                raise ProviderStop("BATCH_PHASE_DEADLINE")
        self._time_check(auth)

    @staticmethod
    def _artifact_stage(name):
        return (
            name[:2]
            if name
            in {
                "P3_references",
                "P4_references",
                "P3_preflight",
                "P4_preflight",
                "P4_resolved_specs",
            }
            else "PREP"
        )

    def artifact(self, name):
        with self._gate_failure():
            with AdmissionReadScope() as scope:
                auth, plan = self._authorize("PREP", scope)
                with self._gate_baseline(scope) as (db, snapshot):
                    value = self._artifact(db, name, scope)
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, self._artifact_stage(name), plan)
            return value

    def references(self, stage):
        with self._gate_failure():
            if stage not in {"P3", "P4"}:
                raise ProviderStop("NON_GENERATION_STAGE")
            value = self.artifact(stage + "_references")
            if not isinstance(value.get("references"), list):
                raise ProviderStop("FROZEN_REFERENCE_LIST_REQUIRED")
            return copy.deepcopy(value["references"])

    def _candidate(self, db, name, path, scope):
        # Reject live journals before minting the prospective artifact's hash.
        dynamic = {self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")}
        dynamic.update(
            self._ledger(row[0])
            for row in db.execute("SELECT id FROM episodes WHERE status!='PASS'")
        )
        if path in dynamic:
            raise ProviderStop("DYNAMIC_JOURNAL_CANNOT_BE_PINNED_AS_ARTIFACT")
        if not path.is_file():
            raise ProviderStop("REGULAR_ARTIFACT_FILE_REQUIRED")
        raw = path.read_bytes()
        value = _strict_json(raw.decode("utf-8"))
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("files"), dict)
            or not value["files"]
        ):
            raise ProviderStop("EXPLICIT_NONEMPTY_ARTIFACT_FILES_REQUIRED")
        dependencies = value["files"]
        if any(Path(candidate) in dynamic for candidate in dependencies):
            raise ProviderStop("DYNAMIC_JOURNAL_CANNOT_BE_PINNED_AS_ARTIFACT")
        row = {
            "name": name,
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "dependencies": json.dumps(dependencies),
        }
        verified = self._artifact_row(db, row, scope)
        return row, verified

    def _validate_candidate(self, name, value, view):
        from v0222_presentation_audit import initial_for, validate_preflight, validate_reference

        required_status = {
            "scope_review": "G_AUTH_SCOPE_REVIEW_PASS",
            "engineering_checks": "ENGINEERING_CHECKS_PASS",
            "P3_preflight": "G_PREFLIGHT_PASS",
            "P4_preflight": "G_PREFLIGHT_PASS",
            "P_full_preparation": "REFERENCE_PREPARATION_PASS",
        }.get(name)
        if required_status is not None and value.get("status") != required_status:
            raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        if name == "scope_review":
            self._scope_review(value, view)
        elif name in {"P3_preflight", "P4_preflight"}:
            validate_preflight(view, value, name[:2])
        elif name in {"P3_references", "P4_references"}:
            stage, refs = name[:2], value["references"]
            expected = [
                (spec["id"], turn)
                for spec in view.plan[stage]
                for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
            ]
            if [(row.get("episode"), row.get("turn")) for row in refs] != expected:
                raise ProviderStop("COMPLETE_ORDERED_STAGE_REFERENCES_REQUIRED")
            self._reference_read_set(value, view, stage)
            for row in refs:
                if (
                    row.get("stage") != stage
                    or type(row.get("turn")) is not int
                    or row.get("selected_condition") != "B1"
                    or row.get("selected_decoder") != "D11"
                ):
                    raise ProviderStop("FIXED_PRESENTATION_AND_DECODER_REFERENCE_REQUIRED")
                validate_reference(view, row, view.spec(row["episode"]))
                if any(value["files"].get(row[kind]) != row["hashes"][kind] for kind in KINDS):
                    raise ProviderStop("ALL_REFERENCE_FILES_MUST_BE_BOUND")
            # File bytes were already admitted into scope; re-enumerate the
            # auditor's glob and reject newly appearing unpinned inputs too.
            self._reference_read_set(value, view, stage)
        elif name == "P4_resolved_specs":
            if fingerprint(value.get("specs")) != fingerprint(view.plan["P4"]):
                raise ProviderStop("EXACT_RESOLVED_24_SCOPE_INITIAL_HASH_SPECS_REQUIRED")
            for spec in value["specs"]:
                initial_for(spec)
        elif name == "P_full_preparation":
            self._preparation(value, view)

    @staticmethod
    def _scope_review(value, view):
        if value.get("root") != str(view.root) or value.get("binding_sha256") != view.binding_sha:
            raise ProviderStop("SCOPE_REVIEW_MUST_BIND_CURRENT_ROOT_AND_BINDING")
        if value.get("review_is_not_user_consent") is not True:
            raise ProviderStop("SCOPE_REVIEW_CANNOT_REPLACE_USER_CONSENT")
        if (
            view.frozen_artifact("P_full_preparation")["value"].get("status")
            != "REFERENCE_PREPARATION_PASS"
        ):
            raise ProviderStop("FULL_PREPARATION_MUST_ALREADY_BE_FROZEN")
        required = view.control_pins
        if set(required) != {
            str(view.root / name)
            for name in (
                "execution-binding.json",
                "authorization.json",
                "authorization-source.json",
                "manifest.json",
            )
        }:
            raise ProviderStop("COMPLETE_SCOPE_CONTROL_PINS_REQUIRED")
        for name in SCOPE_PREREQUISITES:
            frozen = view.frozen_artifact(name)
            row, artifact = frozen["row"], frozen["value"]
            for mapping in (
                {row["path"]: row["sha256"]},
                _strict_json(row["dependencies"]),
                artifact["files"],
            ):
                for path, digest in mapping.items():
                    if path in required and required[path] != digest:
                        raise ProviderStop("SCOPE_REVIEW_DEPENDENCY_CONFLICT")
                    required[path] = digest
        if any(value["files"].get(path) != digest for path, digest in required.items()):
            raise ProviderStop("SCOPE_REVIEW_MUST_COVER_CURRENT_COMPLETE_PREPARATION")

    @staticmethod
    def _reference_read_set(value, view, stage):
        from v0222_presentation_audit import CASES

        # The materializer freezes the whole stage preparation tree, including
        # Session bindings/intent/presentation/results, not just the auditor's
        # narrow immediate read set. Re-enumeration below also detects additions.
        required = {
            path for path in (view.root / "full-reference" / stage).rglob("*") if path.is_file()
        }
        for spec in view.plan[stage]:
            required.add(CASES / spec["root"] / "public-initial.json")
            if stage == "P4":
                directory = view.root / "full-reference" / stage / spec["id"]
                world = directory / "world.sqlite"
                if any(
                    Path(str(world) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
                ):
                    raise ProviderStop("REFERENCE_WORLD_SIDECARS_NOT_ALLOWED")
                turns = {
                    directory / "session" / f"turn-{i:02d}.json"
                    for i in range(1, len(spec["actions"]) + 3)
                }
                if set((directory / "session").glob("turn-*.json")) != turns:
                    raise ProviderStop("EXACT_REFERENCE_TURN_FILE_SET_REQUIRED")
                required.update(turns | {world})
        if any(str(path) not in value["files"] for path in required):
            raise ProviderStop("COMPLETE_REFERENCE_AUDITOR_READ_SET_MUST_BE_BOUND")

    @staticmethod
    def _preparation(value, view):
        expected = {
            "revision": REVISION,
            "selected_presentation": "B1",
            "selected_decoder": "D11",
            "P3_requests": 16,
            "P4_requests": 80,
            "P4_chains": 24,
            "isolated_offline_worlds": 40,
            "model_requests": 0,
            "http_requests": 0,
            "decoder_membership": "UNOBSERVED",
        }
        if fingerprint({key: value.get(key) for key in expected}) != fingerprint(expected):
            raise ProviderStop("COMPLETE_OFFLINE_PREPARATION_COUNTS_AND_CONTRACT_REQUIRED")
        if len(view.plan["P3"]) != 16 or len(view.plan["P4"]) != 24:
            raise ProviderStop("COMPLETE_OFFLINE_PREPARATION_MATRIX_REQUIRED")
        required = {}
        for name in ("P3_references", "P4_references", "P4_resolved_specs"):
            frozen = view.frozen_artifact(name)
            row, artifact = frozen["row"], frozen["value"]
            for mapping in (
                {row["path"]: row["sha256"]},
                _strict_json(row["dependencies"]),
                artifact["files"],
            ):
                for path, digest in mapping.items():
                    if path in required and required[path] != digest:
                        raise ProviderStop("FROZEN_PREPARATION_DEPENDENCY_CONFLICT")
                    required[path] = digest
            if name != "P4_resolved_specs":
                stage = name[:2]
                positions = [
                    (spec["id"], turn)
                    for spec in view.plan[stage]
                    for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
                ]
                if len(positions) != (16 if stage == "P3" else 80) or fingerprint(
                    [(ref.get("episode"), ref.get("turn")) for ref in artifact["references"]]
                ) != fingerprint(positions):
                    raise ProviderStop("COMPLETE_FROZEN_PREPARATION_REFERENCES_REQUIRED")
            elif fingerprint(artifact["specs"]) != fingerprint(view.plan["P4"]):
                raise ProviderStop("EXACT_RESOLVED_24_SCOPE_INITIAL_HASH_SPECS_REQUIRED")
        if any(value["files"].get(path) != digest for path, digest in required.items()):
            raise ProviderStop("COMPLETE_FROZEN_PREPARATION_DEPENDENCY_UNION_REQUIRED")
        worlds = {
            str(view.root / "full-reference" / stage / spec["id"] / "world.sqlite")
            for stage in ("P3", "P4")
            for spec in view.plan[stage]
        }
        if len(worlds) != 40 or not worlds <= value["files"].keys():
            raise ProviderStop("ALL_40_OFFLINE_REFERENCE_WORLDS_MUST_BE_BOUND")

    def freeze_artifact(self, name, path: Path, status: str | None = None):
        with self._gate_failure():
            if name not in FREEZABLE:
                raise ProviderStop("ONLY_PUBLIC_PREPARATION_ARTIFACTS_MAY_BE_FROZEN")
            path = Path(path)
            if (
                not path.is_absolute()
                or ".." in path.parts
                or path.resolve() != path
                or not path.is_relative_to(self.root)
            ):
                raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_CANONICAL_BATCH_PATH")
            with AdmissionReadScope() as scope:
                auth, plan = self._authorize("PREP", scope)
                with self._gate_baseline(scope) as (db, snapshot):
                    if db.execute("SELECT 1 FROM artifacts WHERE name=?", (name,)).fetchone():
                        raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
                    row, value = self._candidate(db, name, path, scope)
                    references = {}
                    artifacts = {}
                    control_pins = {}
                    if name in {"P3_preflight", "P4_preflight"}:
                        stage = name[:2]
                        references[stage] = self._artifact(db, stage + "_references", scope)[
                            "references"
                        ]
                    elif name in {"P3_references", "P4_references"}:
                        references[name[:2]] = value["references"]
                    elif name == "P_full_preparation":
                        for artifact_name in (
                            "P3_references",
                            "P4_references",
                            "P4_resolved_specs",
                        ):
                            artifact_value = self._artifact(db, artifact_name, scope)
                            artifact_row = dict(
                                db.execute(
                                    "SELECT * FROM artifacts WHERE name=?", (artifact_name,)
                                ).fetchone()
                            )
                            artifacts[artifact_name] = {
                                "row": artifact_row,
                                "value": artifact_value,
                            }
                    elif name == "scope_review":
                        artifacts = self._capture_artifacts(db, scope, SCOPE_PREREQUISITES)
                        control_pins = self._scope_control_pins(scope)
                # Independent auditing may call references; it never gets a live DB callback.
                if status is not None and value.get("status") != status:
                    raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
                self._validate_candidate(
                    name,
                    value,
                    AuditView(
                        self.root,
                        plan,
                        references,
                        binding_sha=self.binding_sha,
                        artifacts=artifacts,
                        control_pins=control_pins,
                    ),
                )
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, self._artifact_stage(name), plan)
                db.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?)",
                    (row["name"], row["path"], row["sha256"], row["dependencies"]),
                )
