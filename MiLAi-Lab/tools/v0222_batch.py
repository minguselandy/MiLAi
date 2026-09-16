"""V0222 single finite HTTP batch; diagnostics are observations, never actions.

Only the user's instruction is an authorization source. A delegated review attests
scope, not user consent. Historic debt is retained, never reconciled by this code.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from v02_local_provider import read_events
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS, payload
from v0220_evidence import read, sha, validate
from v0220_provider_hardened import ProviderStop, historical_usage, usage_state, valid_usage
from v0220_wire_contract import fingerprint
from v0221_http_batch import Batch as PriorJournal

REVISION = "V0222_HTTP_ONLY_DIAGNOSTIC_CARRY_V1"
CAPS = {"P1": 24, "P3": 16, "P4": 96}
P1_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "minLength": 1, "pattern": r"\S"}},
    "required": ["text"],
    "additionalProperties": False,
}
HISTORICAL_SOURCES = (
    (
        "/cra/memory/mx_memory/evidence/v0220/provider-compat-v1/provider-ledger.jsonl",
        "c18133ecfcc108fd93f1fe20a038d7b60ff48eee696e7f956f3197a8db7998c6",
    ),
    (
        "/cra/memory/mx_memory/evidence/v0220/v2-candidate1-v1/episodes/"
        "v2c1-01/provider-ledger.jsonl",
        "b752622ac576c85d3a29a9cd58a6d0d50c5f866bc6b3b0d749c6d2e4c77562e7",
    ),
    (
        "/cra/memory/mx_memory/evidence/v0221/20260911-http-r1-v2/episodes/"
        "w2-01/provider/provider-ledger-v2.jsonl",
        "89d5575a237dc76ac9036ac55cb7082644c902e8ad4d7db738f11c72ceeb0d62",
    ),
)


def historical_usage_v0222(paths: tuple[Path, ...]) -> dict:
    """Combine the two legacy SETTLED ledgers with the stopped V0221 v2 ledger."""
    if len(paths) != 3 or len({p.resolve() for p in paths}) != 3:
        raise ProviderStop("THREE_DISTINCT_HISTORICAL_LEDGERS_REQUIRED")
    old = historical_usage(paths[:2])
    latest = usage_state(read_events(paths[2]))
    return {
        **old,
        "sources": [*old["sources"], {"path": str(paths[2].resolve()), "sha256": sha(paths[2])}],
        "requests": old["requests"] + latest["requests"],
        "known_raw_tokens": old["known_raw_tokens"] + latest["known_raw_tokens"],
        "actual_total_raw_tokens": None,
        "unresolved_reservations": [
            *old["unresolved_reservations"],
            *[{"ledger": str(paths[2].resolve()), **r} for r in latest["unresolved_reservations"]],
        ],
        "reserved_raw_upper_bound": (
            old["reserved_raw_upper_bound"] + latest["reserved_raw_upper_bound"]
        ),
        "violations": [*old["violations"], *latest["violations"]],
        "new_generation_allowed": old["new_generation_allowed"]
        and latest["new_generation_allowed"],
    }


def _strict_object(raw: str):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("NONFINITE_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


class Batch(PriorJournal):
    """Reuse immutable SQLite transactions/event FSM, not old stage permissions."""

    def __init__(self, root: Path, binding_sha: str):
        self.root = root.resolve()
        self.binding_sha = binding_sha
        if sha(self.root / "execution-binding.json") != binding_sha:
            raise ProviderStop("EXECUTION_BINDING_DRIFT")
        self.binding = read(self.root / "execution-binding.json")
        self.path = self.root / "batch.sqlite"
        self.auth = self.authorize("P0")
        self.plan = read(self.root / "manifest.json")["contract"]
        self._validate_plan()

    def authorize(self, stage: str) -> dict:
        if sha(self.root / "execution-binding.json") != self.binding_sha:
            raise ProviderStop("EXECUTION_BINDING_DRIFT")
        for name in ("authorization.json", "authorization-source.json", "manifest.json"):
            if sha(self.root / name) != self.binding[name]:
                raise ProviderStop("AUTHORIZATION_OR_MANIFEST_DRIFT")
        auth, grant = (
            read(self.root / "authorization.json"),
            read(self.root / "authorization-source.json"),
        )
        if (
            auth["revision"] != REVISION
            or auth["path"] != "B"
            or auth["historical_usage_settled"] is not False
            or auth.get("reconciliation") is not None
            or grant["origin"] != "USER_CONVERSATION"
            or any(
                grant.get(k) is not True
                for k in (
                    "explicit_historical_carry",
                    "http_only",
                    "execute_goal_and_followup",
                    "subagent_review_delegated",
                    "diagnostic_content_failures_continue",
                )
            )
            or not isinstance(grant.get("user_instruction"), str)
            or not grant["user_instruction"].strip()
        ):
            raise ProviderStop("EXPLICIT_USER_HTTP_DIAGNOSTIC_CARRY_GRANT_REQUIRED")
        if auth["root"] != str(self.root) or auth["batch_id"] != self.root.name:
            raise ProviderStop("AUTHORIZATION_OTHER_BATCH")
        if stage not in auth["stages"] or set(auth["stages"]) - set(grant["stages"]):
            raise ProviderStop("STAGE_NOT_AUTHORIZED")
        if not auth["issued_unix"] <= time.time() < auth["expires_unix"]:
            raise ProviderStop("AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
        if (
            auth["endpoint"] != ENDPOINT
            or auth["model"] != MODEL
            or auth["caps"] != CAPS
            or auth["concurrency"] != 1
            or auth["raw_cap"] is not None
            or auth["automatic_retry"] is not False
            or auth["new_unknown_stops_all"] is not True
            or auth.get("diagnostic_content_failures_continue") is not True
        ):
            raise ProviderStop("AUTHORIZATION_SCOPE_MISMATCH")
        try:
            history = historical_usage_v0222(
                tuple(Path(s["path"]) for s in auth["historical"]["sources"])
            )
            expected = [{"path": p, "sha256": h} for p, h in HISTORICAL_SOURCES]
            original_unknown = historical_usage(tuple(Path(p) for p, _ in HISTORICAL_SOURCES[:2]))
        except (ValueError, KeyError, TypeError, OSError):
            raise ProviderStop("HISTORICAL_LEDGER_CORRUPT") from None
        if (
            history != auth["historical"]
            or history["sources"] != expected
            or history["violations"]
            or auth["accepted_unknown"] != original_unknown["unresolved_reservations"]
            or history["unresolved_reservations"] != auth["accepted_unknown"]
        ):
            raise ProviderStop("EXACT_THREE_LEDGER_HISTORY_AND_OLD_UNKNOWN_REQUIRED")
        manifest = validate(self.root, manifest_sha256=self.binding["manifest.json"])
        if [s["path"] for s in history["sources"]] != manifest["contract"]["historical_paths"]:
            raise ProviderStop("COMPLETE_FROZEN_HISTORY_REQUIRED")
        return auth

    def _validate_plan(self) -> None:
        ids = []
        for stage, count in (("P1", 24), ("P3", 16), ("P4", 24)):
            specs = self.plan[stage]
            if len(specs) != count:
                raise ProviderStop("COMPLETE_FINITE_MATRIX_REQUIRED")
            for spec in specs:
                if spec["stage"] != stage or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", spec["id"]):
                    raise ProviderStop("INVALID_FROZEN_EPISODE")
                ids.append(spec["id"])
        if len(ids) != len(set(ids)):
            raise ProviderStop("EPISODE_IDS_MUST_BE_GLOBALLY_UNIQUE")
        expected = [
            (p, f, c)
            for p in (1, 2)
            for f in ("T1", "T2", "T3")
            for c in (("D00", "D10", "D01", "D11") if p == 1 else ("D11", "D01", "D10", "D00"))
        ]
        actual = [(s["pass"], s["fixture"], s["condition"]) for s in self.plan["P1"]]
        if actual != expected:
            raise ProviderStop("P1_FROZEN_ORDER_MISMATCH")
        targets = {}
        for spec in self.plan["P1"]:
            target = spec["target"]
            if not isinstance(target, str) or not re.search(r"\S", target):
                raise ProviderStop("P1_TARGET_NOT_LEGAL")
            if targets.setdefault(spec["fixture"], target) != target:
                raise ProviderStop("P1_CONDITIONS_MUST_SHARE_EXACT_TARGET")

    def initialize(self) -> None:
        self.authorize("P0")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE episodes (id TEXT PRIMARY KEY,stage TEXT,ordinal INTEGER,
                    cap INTEGER,status TEXT,pid INTEGER,deadline REAL);
                CREATE TABLE events (seq INTEGER PRIMARY KEY,event TEXT NOT NULL);
                CREATE TABLE artifacts (name TEXT PRIMARY KEY,path TEXT,sha256 TEXT,
                    dependencies TEXT NOT NULL);
                CREATE TABLE launches (stage TEXT PRIMARY KEY,pid INTEGER,started REAL);
            """)
            db.execute("INSERT INTO meta VALUES ('binding',?)", (self.binding_sha,))
            for stage in CAPS:
                for i, spec in enumerate(self.plan[stage]):
                    db.execute(
                        "INSERT INTO episodes VALUES (?,?,?,?, 'PENDING',NULL,NULL)",
                        (spec["id"], stage, i, 4 if stage == "P4" else 1),
                    )

    def check_journal(self, db) -> dict:
        if db.execute("SELECT value FROM meta WHERE key='stop'").fetchone():
            raise ProviderStop("BATCH_STOPPED_NO_RETRY")
        events = self.events(db)
        state = usage_state(events)
        if not state["new_generation_allowed"]:
            raise ProviderStop("NEW_BATCH_UNKNOWN_OR_VIOLATION")
        mirrored = []
        for stage in CAPS:
            for spec in self.plan[stage]:
                mirrored.extend(
                    read_events(
                        self.root / "episodes" / spec["id"] / "provider/provider-ledger-v2.jsonl"
                    )
                )

        def normalize(rows):
            return sorted(json.dumps(v, sort_keys=True) for v in rows)

        if normalize(events) != normalize(mirrored):
            raise ProviderStop("CENTRAL_AND_EPISODE_LEDGER_DIVERGED")
        for row in db.execute("SELECT * FROM artifacts"):
            self._artifact(row)
        return state

    def _artifact(self, row):
        if row is None or sha(Path(row["path"])) != row["sha256"]:
            raise ProviderStop("FROZEN_STAGE_ARTIFACT_MISSING_OR_DRIFTED")
        value = read(Path(row["path"]))
        for name, expected in json.loads(row["dependencies"]).items():
            if sha(Path(name)) != expected:
                raise ProviderStop("OBSERVATION_RAW_EVIDENCE_DRIFT")
        if isinstance(value, dict):
            for name, expected in value.get("files", {}).items():
                if sha(Path(name)) != expected:
                    raise ProviderStop("STAGE_ARTIFACT_DEPENDENCY_DRIFT")
        return value

    def artifact(self, name: str):
        with self.transaction() as db:
            return self._artifact(
                db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
            )

    def freeze_artifact(self, name: str, path: Path, status: str | None = None) -> None:
        self.authorize("P0")
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise ProviderStop("STAGE_ARTIFACT_OUTSIDE_BATCH")
        if status is not None and read(path).get("status") != status:
            raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")
        if name in {"P1_firstpass_difference", "P1_final_selection"}:
            if read(path) != self.p1_decision(final=name == "P1_final_selection"):
                raise ProviderStop("P1_DECISION_NOT_DERIVED_FROM_COMPLETE_OBSERVATIONS")
        dependencies = {}
        if name == "P1_references":
            references = read(path)
            if not isinstance(references, list) or [r["episode"] for r in references] != [
                s["id"] for s in self.plan["P1"]
            ]:
                raise ProviderStop("COMPLETE_ORDERED_P1_REFERENCES_REQUIRED")
            canonical_by_fixture = {}
            for reference, spec in zip(references, self.plan["P1"], strict=True):
                self._p1_reference(reference, spec)
                canonical = read(Path(reference["canonical"]))
                canonical_hash = fingerprint(canonical)
                if (
                    canonical_by_fixture.setdefault(spec["fixture"], canonical_hash)
                    != canonical_hash
                ):
                    raise ProviderStop(
                        "P1_CONDITIONS_HAVE_DIFFERENT_CANONICAL_MESSAGES_OR_PARAMETERS"
                    )
                dependencies.update(
                    {
                        reference[kind]: reference["hashes"][kind]
                        for kind in ("canonical", "wire", "output")
                    }
                )
        if name.endswith("_observation"):
            observation = read(path)
            episode, key = observation["id"], observation["request_id"]
            if (
                name != episode + "_observation"
                or not any(s["id"] == episode for s in self.plan["P1"])
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", key)
            ):
                raise ProviderStop("OBSERVATION_OUTSIDE_FROZEN_P1")
            provider = self.root / "episodes" / episode / "provider"
            dependencies = {
                str(p): sha(p)
                for p in (
                    provider / (key + "-request.json"),
                    provider / (key + "-http.json"),
                    provider / (key + "-visible.json"),
                    provider / (key + "-tokenize-request.json"),
                    provider / (key + "-tokenize-http.json"),
                    provider / (key + "-tokenize.json"),
                    provider / "provider-ledger-v2.jsonl",
                )
            }
        with self.transaction() as db:
            self.check_journal(db)
            if db.execute("SELECT 1 FROM artifacts WHERE name=?", (name,)).fetchone():
                raise ProviderStop("STAGE_ARTIFACT_ALREADY_FROZEN")
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (name, str(path), sha(path), json.dumps(dependencies)),
            )

    def references(self, stage: str = "P1") -> list[dict]:
        return self.artifact(stage + "_references")

    def _stage_ready(self, db, stage: str) -> None:
        def gate(name, status):
            value = self._artifact(
                db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
            )
            if value.get("status") != status:
                raise ProviderStop("STAGE_GATE_STATUS_NOT_MET")

        gate("scope_review", "G_AUTH_SCOPE_REVIEW_PASS")
        gate(stage + "_preflight", "G_PREFLIGHT_PASS")
        self._artifact(
            db.execute("SELECT * FROM artifacts WHERE name=?", (stage + "_references",)).fetchone()
        )
        if stage in {"P3", "P4"}:
            gate("P1_final_selection", "STRING_RULE_SIGNAL")
            gate("P2_gate", "G_P2_PASS")
        if (
            stage == "P4"
            and db.execute(
                "SELECT COUNT(*) FROM episodes WHERE stage='P3' AND status='PASS'"
            ).fetchone()[0]
            != 16
        ):
            raise ProviderStop("P4_REQUIRES_COMPLETE_P3_PASS")

    def launch_once(self, stage: str) -> None:
        self.authorize(stage)
        if stage not in CAPS:
            raise ProviderStop("NON_GENERATION_STAGE")
        with self.transaction() as db:
            self.check_journal(db)
            self._stage_ready(db, stage)
            if db.execute("SELECT 1 FROM launches WHERE stage=?", (stage,)).fetchone():
                raise ProviderStop("STAGE_ALREADY_LAUNCHED_NO_RESTART")
            now = time.time()
            db.execute("INSERT INTO launches VALUES (?,?,?)", (stage, os.getpid(), now))
            db.execute(
                "INSERT INTO meta VALUES (?,?)",
                (
                    stage + "_deadline",
                    str(min(now + (7200 if stage == "P4" else 1800), self.auth["expires_unix"])),
                ),
            )

    def claim(self, episode: str) -> None:
        spec = next((s for stage in CAPS for s in self.plan[stage] if s["id"] == episode), None)
        if spec is None:
            raise ProviderStop("EPISODE_OUTSIDE_FROZEN_PLAN")
        stage = spec["stage"]
        self.authorize(stage)
        with self.transaction() as db:
            self.check_journal(db)
            self._stage_ready(db, stage)
            if db.execute("SELECT 1 FROM launches WHERE stage=?", (stage,)).fetchone() is None:
                raise ProviderStop("STAGE_NOT_LAUNCHED")
            if db.execute("SELECT 1 FROM episodes WHERE status='RUNNING'").fetchone():
                raise ProviderStop("SINGLE_ACTIVE_EPISODE_ONLY")
            if db.execute("SELECT 1 FROM episodes WHERE pid=?", (os.getpid(),)).fetchone():
                raise ProviderStop("FRESH_CLIENT_PROCESS_REQUIRED")
            row = db.execute(
                "SELECT * FROM episodes WHERE stage=? AND status NOT IN "
                "('PASS','OBSERVED') ORDER BY ordinal",
                (stage,),
            ).fetchone()
            if row is None or row["id"] != episode or row["status"] != "PENDING":
                raise ProviderStop("NO_RESTART_OR_OUT_OF_ORDER_EPISODE")
            if stage == "P1" and row["ordinal"] >= 12:
                decision = self._artifact(
                    db.execute(
                        "SELECT * FROM artifacts WHERE name='P1_firstpass_difference'"
                    ).fetchone()
                )
                if decision.get("repeat_required") is not True:
                    raise ProviderStop("P1_SECOND_PASS_NOT_TRIGGERED")
            limit = float(
                db.execute("SELECT value FROM meta WHERE key=?", (stage + "_deadline",)).fetchone()[
                    0
                ]
            )
            if time.time() >= limit:
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            db.execute(
                "UPDATE episodes SET status='RUNNING',pid=?,deadline=? WHERE id=?",
                (os.getpid(), min(limit, time.time() + 300), episode),
            )

    def record(self, episode: str, event: dict) -> None:
        if event.get("event") == "RESERVED" and (
            event.get("output_cap") != 4096
            or event.get("cumulative_raw_cap") is not None
            or event.get("raw_upper_bound", 65537) > 65536
        ):
            raise ProviderStop("FROZEN_REQUEST_CAP_MISMATCH")
        super().record(episode, event)

    def _p1_reference(self, reference: dict, spec: dict) -> dict:
        """Independent frozen-pair audit: no reliance on the request constructor."""
        expected = {
            "episode": spec["id"],
            "stage": "P1",
            "fixture": spec["fixture"],
            "condition": spec["condition"],
            "target_sha256": fingerprint(spec["target"]),
        }
        if any(reference.get(k) != v for k, v in expected.items()):
            raise ProviderStop("P1_REFERENCE_SPEC_BINDING_MISMATCH")
        objects = {}
        for kind in ("canonical", "wire", "output"):
            path = Path(reference[kind]).resolve()
            if not path.is_relative_to(self.root) or sha(path) != reference["hashes"][kind]:
                raise ProviderStop("P1_REFERENCE_FILE_DRIFT")
            objects[kind] = _strict_object(path.read_text(encoding="utf-8"))
        canonical, wire = objects["canonical"], objects["wire"]
        if (
            fingerprint(canonical) != fingerprint(payload(canonical["messages"], P1_SCHEMA))
            or canonical["messages"][-1]["role"] != "user"
            or _strict_object(canonical["messages"][-1]["content"]) != {"target": spec["target"]}
            or _strict_object(objects["output"]["raw"]) != {"text": spec["target"]}
        ):
            raise ProviderStop("P1_CANONICAL_AUTHORITY_OR_TARGET_MISMATCH")
        expected_wire = copy.deepcopy(canonical)
        rules = expected_wire["response_format"]["json_schema"]["schema"]["properties"]["text"]
        if spec["condition"] in {"D10", "D11"}:
            rules.pop("pattern")
        if spec["condition"] in {"D01", "D11"}:
            rules.pop("minLength")
        if fingerprint(wire) != fingerprint(expected_wire):
            raise ProviderStop("P1_WIRE_CONDITION_NOT_EXACT_FROZEN_TRANSFORMATION")
        return wire

    def _observation(self, db, spec: dict) -> dict:
        observation = self._artifact(
            db.execute(
                "SELECT * FROM artifacts WHERE name=?", (spec["id"] + "_observation",)
            ).fetchone()
        )
        events = [
            e
            for e in self.events(db)
            if e.get("session") == spec["id"] and e["event"] == "RESERVED"
        ]
        if len(events) != 1:
            raise ProviderStop("DIAGNOSTIC_REQUIRES_ONE_ACTUAL_REQUEST")
        reserved = events[0]
        key = reserved["request_id"]
        provider = self.root / "episodes" / spec["id"] / "provider"
        request = provider / (key + "-request.json")
        references = self._artifact(
            db.execute("SELECT * FROM artifacts WHERE name='P1_references'").fetchone()
        )
        matches = [r for r in references if r["episode"] == spec["id"]]
        if len(matches) != 1:
            raise ProviderStop("UNIQUE_FROZEN_P1_REFERENCE_REQUIRED")
        wire = self._p1_reference(matches[0], spec)
        if fingerprint(_strict_object(request.read_text(encoding="utf-8"))) != fingerprint(wire):
            raise ProviderStop("ACTUAL_REQUEST_DIFFERS_FROM_FROZEN_P1_WIRE")
        tokenize_request = read(provider / (key + "-tokenize-request.json"))
        tokenize_http = read(provider / (key + "-tokenize-http.json"))
        tokenize_count = read(provider / (key + "-tokenize.json"))
        count_body = _strict_object(tokenize_http["body"])
        count = count_body.get("count") if isinstance(count_body, dict) else None
        if (
            tokenize_http["status_code"] != 200
            or type(count) is not int
            or count < 0
            or count + 4096 > 65536
            or fingerprint(tokenize_request) != fingerprint({k: wire[k] for k in TOKENIZE_KEYS})
            or type(tokenize_count.get("count")) is not int
            or tokenize_count != {"count": count}
            or count != reserved["prompt_tokens"]
        ):
            raise ProviderStop("P1_ACTUAL_TOKENIZE_REQUEST_OR_USAGE_MISMATCH")
        http = read(provider / (key + "-http.json"))
        visible = read(provider / (key + "-visible.json"))
        settled = [
            e for e in self.events(db) if e["request_id"] == key and e["event"] == "USAGE_KNOWN"
        ]
        value = _strict_object(http["body"])
        if (
            len(settled) != 1
            or http["status_code"] != 200
            or http["client_request_id"] != key
            or sha(request) != reserved["payload_sha256"]
            or http["request_wire_sha256"] != reserved["payload_sha256"]
            or not valid_usage(value["usage"])
            or value["usage"] != settled[0]["usage"]
            or value["choices"][0]["message"]["content"] != visible["content"]
            or value["usage"]["prompt_tokens"] != reserved["prompt_tokens"]
            or value["usage"]["completion_tokens"] > 4096
        ):
            raise ProviderStop("DIAGNOSTIC_RAW_HTTP_USAGE_AUDIT_FAILED")
        try:
            exact = _strict_object(visible["content"]) == {"text": spec["target"]}
        except (ValueError, TypeError, RecursionError):
            exact = False
        expected = {
            "id": spec["id"],
            "request_id": key,
            "status": "OBSERVED",
            "http_usage_audit": "PASS",
            "exact_fidelity": exact,
        }
        if any(observation.get(k) != v for k, v in expected.items()):
            raise ProviderStop("DIAGNOSTIC_OBSERVATION_NOT_DERIVED_FROM_RAW")
        return expected

    def finish(self, episode: str, outcome: str = "PASS") -> None:
        with self.transaction() as db:
            self.check_journal(db)
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode,)).fetchone()
            if row is None or row["status"] != "RUNNING":
                raise ProviderStop("NO_RUNNING_EPISODE_TO_FINISH")
            self.authorize(row["stage"])
            if time.time() >= row["deadline"]:
                raise ProviderStop("EPISODE_DEADLINE")
            count = sum(
                e["event"] == "RESERVED" and e.get("session") == episode for e in self.events(db)
            )
            if not (3 <= count <= 4 if row["stage"] == "P4" else count == 1):
                raise ProviderStop("EMPTY_OR_INCOMPLETE_EPISODE_CANNOT_PASS")
            if row["stage"] == "P1":
                if outcome != "OBSERVED":
                    raise ProviderStop("P1_IS_OBSERVATION_NOT_BUSINESS_PASS")
                self._observation(db, self.plan["P1"][row["ordinal"]])
            elif outcome != "PASS":
                raise ProviderStop("ACCEPTANCE_FAILURE_MUST_STOP_BATCH")
            db.execute("UPDATE episodes SET status=? WHERE id=?", (outcome, episode))

    def p1_decision(self, final: bool = False) -> dict:
        with self.transaction() as db:
            self.check_journal(db)
            specs = self.plan["P1"][: 24 if final else 12]
            evidence = {}
            for spec in specs:
                row = db.execute("SELECT status FROM episodes WHERE id=?", (spec["id"],)).fetchone()
                if row[0] != "OBSERVED":
                    raise ProviderStop("COMPLETE_P1_PASS_REQUIRED_FOR_DECISION")
                evidence[(spec["pass"], spec["fixture"], spec["condition"])] = self._observation(
                    db, spec
                )["exact_fidelity"]
        fixtures, conditions = ("T1", "T2", "T3"), ("D10", "D01", "D11")
        if not final:
            repeat = any(
                not evidence[1, f, "D00"] and evidence[1, f, c]
                for f in fixtures
                for c in conditions
            )
            return {
                "status": "SECOND_PASS_REQUIRED" if repeat else "NO_DIFFERENTIAL_SIGNAL",
                "repeat_required": repeat,
            }
        selected = None
        if not all(evidence[p, f, "D00"] for p in (1, 2) for f in fixtures):
            for condition in conditions:
                if all(evidence[p, f, condition] for p in (1, 2) for f in fixtures) and any(
                    all(not evidence[p, f, "D00"] and evidence[p, f, condition] for p in (1, 2))
                    for f in fixtures
                ):
                    selected = condition
                    break
        return {
            "status": "STRING_RULE_SIGNAL" if selected else "NO_QUALIFIED_CONDITION",
            "selected_condition": selected,
        }

    def set_p1_decision(self, path: Path, final: bool = False) -> None:
        if read(path) != self.p1_decision(final=final):
            raise ProviderStop("P1_DECISION_NOT_DERIVED_FROM_COMPLETE_OBSERVATIONS")
        name = "P1_final_selection" if final else "P1_firstpass_difference"
        self.freeze_artifact(name, path)
