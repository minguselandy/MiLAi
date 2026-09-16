"""Parent-owned scoped finish and complete P3-gate derivation, without HTTP.

Raw independent audit runs outside SQL connections and writer locks. Fixed
inputs have a per-operation read scope; active episode evidence is freshly
read and hashed, never inserted into that scope using a self-minted ledger pin.
Only after scope close, unchanged SQL, fresh evidence and deadline checks can
the parent register acceptance. This module does not launch or attest workers.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_gates_v2 import Batch as ArtifactBatch


class Batch(ArtifactBatch):
    def _finish_owner(self, db, episode):
        row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
        launch = (
            None
            if row is None
            else db.execute("SELECT * FROM launches WHERE stage=?", (row["stage"],)).fetchone()
        )
        if (
            row is None
            or row["status"] != "RUNNING"
            or launch is None
            or type(row["pid"]) is not int
            or row["pid"] <= 0
            or launch["pid"] != os.getpid()
            or row["pid"] == launch["pid"]
            or type(row["deadline"]) not in (int, float)
            or not math.isfinite(row["deadline"])
            or time.time() >= row["deadline"]
        ):
            raise ProviderStop("NO_OWNED_LIVE_EPISODE_TO_FINISH")
        return dict(row)

    @staticmethod
    def _audit_rows(db, episode):
        row = dict(db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone())
        claim = dict(db.execute("SELECT * FROM claims WHERE episode=?", (episode,)).fetchone())
        launch = dict(
            db.execute("SELECT * FROM launches WHERE stage=?", (row["stage"],)).fetchone()
        )
        return {"episode_row": row, "claim_row": claim, "launch_row": launch}

    def _audit(self, episode, rows, events):
        from v0222_presentation_terminal_v2 import audit_claimed_episode

        return audit_claimed_episode(self, episode, **rows, events=events)

    def _verify_dependencies(self, files):
        if not isinstance(files, dict) or not files:
            raise ProviderStop("NONEMPTY_TERMINAL_EVIDENCE_REQUIRED")
        dynamic = {self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")}
        for value, expected in files.items():
            path = Path(value)
            if (
                not path.is_absolute()
                or ".." in path.parts
                or path.resolve() != path
                or not path.is_relative_to(self.root)
                or path in dynamic
                or not path.is_file()
            ):
                raise ProviderStop("TERMINAL_EVIDENCE_PATH_INVALID")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ProviderStop("TERMINAL_EVIDENCE_DRIFT")

    def _verify_episode_files(self, episode, audit):
        directory = self.root / "episodes" / episode
        required = {
            str(path)
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix in {".json", ".jsonl"}
            and path != directory / "independent-audit.json"
        }
        required.update(
            {
                str(self.claim_marker_path(episode)),
                str(self.root / "exits" / (episode + ".json")),
                str(self.root / ("live-launch-" + self.spec(episode)["stage"] + ".json")),
            }
        )
        if self.spec(episode)["stage"] == "P4":
            world = self.root / "worlds" / (episode + ".sqlite")
            if any(Path(str(world) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                raise ProviderStop("CLOSED_WORLD_WITHOUT_UNBOUND_SQLITE_SIDECARS_REQUIRED")
            required.add(str(world))
        if set(audit["files"]) != required:
            raise ProviderStop("EXACT_RAW_EPISODE_AND_PARENT_FILES_REQUIRED")
        self._verify_dependencies(audit["files"])

    def _last_deadline(self, db, auth, stage, episode=None):
        # Called AFTER potentially expensive fresh file reads, before commit.
        self._time_check(auth)
        if episode is not None:
            self._finish_owner(db, episode)
        for running in db.execute("SELECT deadline FROM episodes WHERE status='RUNNING'"):
            if (
                type(running[0]) not in (int, float)
                or not math.isfinite(running[0])
                or time.time() >= running[0]
            ):
                raise ProviderStop("EPISODE_DEADLINE")
        deadline = db.execute(
            "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
        ).fetchone()
        if deadline is None or time.time() >= float(deadline[0]):
            raise ProviderStop("BATCH_PHASE_DEADLINE")

    def finish(self, episode):
        with self._gate_failure():
            stage = self.spec(episode)["stage"]
            with AdmissionReadScope() as scope:
                auth, plan = self._authorize(stage, scope)
                with self._gate_baseline(scope) as (db, snapshot):
                    self._finish_owner(db, episode)
                    rows = self._audit_rows(db, episode)
                    events = self.events(db)
                audit = self._audit(episode, rows, events)
                if (
                    audit.get("status") != "PASS"
                    or audit.get("id") != episode
                    or audit.get("stage") != stage
                    or audit.get("pid") != rows["episode_row"]["pid"]
                ):
                    raise ProviderStop("FULL_ACCEPTANCE_AUDIT_NOT_PASS")
                self._verify_episode_files(episode, audit)
                path = self.root / "episodes" / episode / "independent-audit.json"
                save(path, audit)
                audit_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                # Only the new audit document itself enters scope; its dynamic
                # raw ledger dependencies are deliberately not traversed here.
                if fingerprint(scope.read_json(path, audit_sha)) != fingerprint(audit):
                    raise ProviderStop("SAVED_AUDIT_DRIFT")
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, stage, plan)
                self._verify_episode_files(episode, audit)
                self._last_deadline(db, auth, stage, episode)
                db.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?)",
                    (episode + "_audit", str(path), audit_sha, json.dumps(audit["files"])),
                )
                db.execute("UPDATE episodes SET status='PASS' WHERE id=?", (episode,))
            return audit

    @staticmethod
    def _merge_files(target, source):
        for path, sha in source.items():
            if path in target and target[path] != sha:
                raise ProviderStop("CONFLICTING_GATE_EVIDENCE_HASH")
            target[path] = sha

    def _p3_gate(self, path=None):
        with self._gate_failure():
            if path is not None:
                path = Path(path)
                if (
                    not path.is_absolute()
                    or ".." in path.parts
                    or path.resolve() != path
                    or not path.is_relative_to(self.root)
                ):
                    raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_CANONICAL_BATCH_PATH")
            with AdmissionReadScope() as scope:
                auth, plan = self._authorize("P3", scope)
                specs = plan["P3"]
                if (
                    len(specs) != 16
                    or sum(s["variant"] == "full" for s in specs) != 8
                    or sum(s["variant"] == "finish" for s in specs) != 8
                ):
                    raise ProviderStop("COMPLETE_8_FULL_8_FINISH_MATRIX_REQUIRED")
                audits, rows, files = [], [], {}
                with self._gate_baseline(scope) as (db, snapshot):
                    launch = db.execute("SELECT * FROM launches WHERE stage='P3'").fetchone()
                    if launch is None or launch["pid"] != os.getpid():
                        raise ProviderStop("ONLY_STAGE_PARENT_CAN_DERIVE_P3_GATE")
                    if (
                        path is not None
                        and db.execute("SELECT 1 FROM artifacts WHERE name='P3_gate'").fetchone()
                    ):
                        raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
                    events = self.events(db)
                    for spec in specs:
                        episode = spec["id"]
                        row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
                        if row is None or row["status"] != "PASS":
                            raise ProviderStop("P3_GATE_REQUIRES_16_ACTUAL_PASS")
                        artifact = db.execute(
                            "SELECT * FROM artifacts WHERE name=?", (episode + "_audit",)
                        ).fetchone()
                        audits.append(self._artifact_row(db, artifact, scope))
                        rows.append(self._audit_rows(db, episode))
                        self._merge_files(files, {artifact["path"]: artifact["sha256"]})
                        self._merge_files(files, json.loads(artifact["dependencies"]))
                        self._merge_files(files, audits[-1]["files"])
                for spec, audit, audit_rows in zip(specs, audits, rows, strict=True):
                    current = self._audit(spec["id"], audit_rows, events)
                    if fingerprint(current) != fingerprint(audit):
                        raise ProviderStop("P3_AUDIT_NOT_REPRODUCIBLE_FROM_RAW")
                    self._verify_episode_files(spec["id"], current)
                gate = {
                    "status": "G_P3_PASS",
                    "binding_sha256": self.binding_sha,
                    "episodes": [s["id"] for s in specs],
                    "full_passed": 8,
                    "finish_passed": 8,
                    "files": files,
                }
                if path is not None:
                    if not path.exists():
                        save(path, gate)
                    gate_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                    if fingerprint(scope.read_json(path, gate_sha)) != fingerprint(gate):
                        raise ProviderStop("P3_GATE_NOT_DERIVED_FROM_16_ACTUAL_PASS_AUDITS")
            with self.transaction() as db:
                self._gate_final(db, snapshot, auth, "P3", plan)
                self._verify_dependencies(files)
                for spec, audit in zip(specs, audits, strict=True):
                    self._verify_episode_files(spec["id"], audit)
                self._last_deadline(db, auth, "P3")
                if path is not None:
                    db.execute(
                        "INSERT INTO artifacts VALUES (?,?,?,?)",
                        ("P3_gate", str(path), gate_sha, json.dumps(files)),
                    )
            return gate

    def p3_gate(self):
        return self._p3_gate()

    def freeze_p3_gate(self, path):
        """Derive and register once; an existing candidate must match exactly."""
        return self._p3_gate(path)
