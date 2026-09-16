"""Synthetic four-coordinator lineage tests, not a real-instance admission."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_scoped_history import legacy, poisoned, put, reserved, v2

import v0222_presentation_lineage_v2 as module
import v0222_scoped_history as history_module
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope


def fixture(tmp_path, monkeypatch):
    roots = [tmp_path / f"coordinator-{index}" for index in range(4)]
    sources, all_events, terminals, files, launch_rows = [], [], [], {}, []
    launch_files = {}
    for index, events in enumerate(
        [legacy("a", 1000, 100) + legacy("b", 1000, 121), [reserved("old", 24188, 4096)]]
    ):
        source = put(tmp_path / f"legacy-{index}.jsonl", jsonl(events))
        sources.append(source)
    counter = 0
    for index, (root, count) in enumerate(zip(roots, (1, 25, 16, 13), strict=True)):
        root.mkdir()
        episodes, central = [], []
        launches = None if index == 0 else [{"stage": "P3", "pid": 100 + index, "started": 1.5}]
        binding = put(root / "execution-binding.json", {"test_only": index})
        files[binding["path"]] = binding["sha256"]
        stop = None if index == 2 else "TEST_ONLY_PERMANENT_STOP"
        for ordinal in range(count):
            episode = f"test-{index}-{ordinal}"
            events = v2(f"v2-{counter}", 1078613 if counter == 54 else 10, 1)
            counter += 1
            for event in events:
                if event["event"] == "RESERVED":
                    event["session"] = episode
            source = put(
                root / "episodes" / episode / "provider/provider-ledger-v2.jsonl", jsonl(events)
            )
            sources.append(source)
            central.extend(events)
            episodes.append(
                {
                    "id": episode,
                    "stage": "P3",
                    "ordinal": ordinal,
                    "cap": 1,
                    "status": "PASS",
                    "pid": 1000 + counter,
                    "deadline": 2.5,
                }
            )
        all_events.append(central)
        result = put(root / "result.json", {"batch": {"episodes": episodes, "stop": stop}})
        files[result["path"]] = result["sha256"]
        with sqlite3.connect(root / "batch.sqlite") as db:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE episodes(id TEXT PRIMARY KEY,stage TEXT,ordinal INTEGER,cap INTEGER,
                    status TEXT,pid INTEGER,deadline REAL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY,event TEXT NOT NULL);
            """)
            db.execute("INSERT INTO meta VALUES ('binding',?)", (binding["sha256"],))
            if stop is not None:
                db.execute("INSERT INTO meta VALUES ('stop',?)", (stop,))
            for row in episodes:
                db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?)", tuple(row.values()))
            for event in central:
                db.execute("INSERT INTO events(event) VALUES (?)", (json.dumps(event),))
            if launches is not None:
                db.execute("CREATE TABLE launches(stage TEXT PRIMARY KEY,pid INTEGER,started REAL)")
                db.execute(
                    "CREATE TABLE artifacts(name TEXT PRIMARY KEY,path TEXT,"
                    "sha256 TEXT,dependencies TEXT NOT NULL)"
                )
                for row in launches:
                    db.execute("INSERT INTO launches VALUES (?,?,?)", tuple(row.values()))
            db.row_factory = sqlite3.Row
            tables = sorted(
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            )
            columns = {
                table: [
                    dict(row) for row in db.execute("SELECT * FROM pragma_table_info(?)", (table,))
                ]
                for table in tables
            }
        terminals.append(
            {
                "root": str(root),
                "binding_sha256": binding["sha256"],
                "terminal_result_path": result["path"],
                "terminal_result_sha256": result["sha256"],
                "stop": stop,
                "episodes_snapshot": episodes,
                "episodes_fingerprint": fingerprint(episodes),
                "episode_state_counts": [{"stage": "P3", "status": "PASS", "count": count}],
                "unrun": [],
                "failed": [],
                "central_event_count": len(central),
                "central_events_fingerprint": fingerprint(central),
                "local_mirror_exact_multiset": True,
                "central_not_counted_as_an_additional_ledger": True,
                "read_only_snapshots_unchanged": True,
                "database_files_not_bound": True,
            }
        )
        source_pin = put(
            root / "executed-source/Batch.py",
            b"# synthetic schema fixture; not historical evidence",
        )
        launch_files[source_pin["path"]] = source_pin["sha256"]
        markers = []
        if index != 1:
            value = {"pid": 100 + index, "unix": 1.5, "binding_sha256": binding["sha256"]}
            if index == 3:
                value["stage"] = "P3"
            marker_pin = put(
                root / ("live-launch-P3.json" if index == 3 else "live-launch.json"), value
            )
            launch_files[marker_pin["path"]] = marker_pin["sha256"]
            marker = {**marker_pin, "expected_value": value}
            if index == 0:
                marker["expected_value_for_future_drift_check"] = marker.pop("expected_value")
                marker["historical_original_pid_and_time"] = "UNKNOWN"
            markers.append(marker)
        launch_rows.append(
            {
                "root": str(root),
                "binding_sha256": binding["sha256"],
                "schema": {
                    "tables": tables,
                    "columns": columns,
                    "source_path": source_pin["path"],
                    "source_sha256": source_pin["sha256"],
                },
                "launches": {
                    "table_present": index != 0,
                    "expected_rows": launches,
                    "markers": markers,
                },
                "terminal": {**terminals[-1], "inventory_pointer": f"/terminal_states/{index}"},
            }
        )
    files.update({row["path"]: row["sha256"] for row in sources})
    frozen_world = put(tmp_path / "static" / "World.sqlite", b"synthetic immutable world bytes")
    files[frozen_world["path"]] = frozen_world["sha256"]
    inventory = {
        "status": "INDEPENDENT_HISTORY_INVENTORY_REVIEW_PASS_NOT_AUTHORIZATION",
        "sources": sources,
        "aggregate": {
            "ledger_files": 57,
            "requests": 58,
            "known_raw_tokens": 1081429,
            "unknown_reservations": 1,
            "reserved_raw_upper_bound": 28284,
            "actual_total_raw_tokens": None,
            "reservation_is_actual_usage": False,
            "violations": [],
            "new_unknown_reservations": [],
        },
        "original_unknown_complete_objects": [
            {**reserved("old", 24188, 4096), "ledger": sources[1]["path"]}
        ],
        "terminal_states": terminals,
        "files": files,
    }
    pin = put(tmp_path / "inventory.json", inventory)
    for target in (module, history_module):
        monkeypatch.setattr(target, "INVENTORY_PATH", Path(pin["path"]))
        monkeypatch.setattr(target, "INVENTORY_SHA256", pin["sha256"])
    launch_files[pin["path"]] = pin["sha256"]
    review = {
        "status": "INDEPENDENT_HISTORY_LAUNCH_REVIEW_WITH_EXPLICIT_UNKNOWN_NOT_AUTHORIZATION",
        "history_inventory": pin,
        "roots": launch_rows,
        "files": launch_files,
    }
    launch_pin = put(tmp_path / "launch-review.json", review)
    monkeypatch.setattr(module, "LAUNCH_REVIEW_PATH", Path(launch_pin["path"]))
    monkeypatch.setattr(module, "LAUNCH_REVIEW_SHA256", launch_pin["sha256"])
    index_pin = put(
        tmp_path / "lineage-index.json",
        {
            "status": module.INDEX_STATUS,
            "description": "TEST_ONLY_TWO_ROOT_INDEX",
            "files": {pin["path"]: pin["sha256"], launch_pin["path"]: launch_pin["sha256"]},
        },
    )
    monkeypatch.setattr(module, "EVIDENCE_INDEX_PATH", Path(index_pin["path"]))
    monkeypatch.setattr(module, "EVIDENCE_INDEX_SHA256", index_pin["sha256"])
    return inventory, roots, launch_rows, all_events


def jsonl(events):
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


def reseal_index(monkeypatch):
    index = json.loads(module.EVIDENCE_INDEX_PATH.read_text())
    index["files"] = {
        str(module.INVENTORY_PATH): module.INVENTORY_SHA256,
        str(module.LAUNCH_REVIEW_PATH): module.LAUNCH_REVIEW_SHA256,
    }
    monkeypatch.setattr(
        module, "EVIDENCE_INDEX_SHA256", put(module.EVIDENCE_INDEX_PATH, index)["sha256"]
    )


def reseal_inventory(monkeypatch, inventory):
    pin = put(module.INVENTORY_PATH, inventory)
    for target in (module, history_module):
        monkeypatch.setattr(target, "INVENTORY_SHA256", pin["sha256"])
    review = json.loads(module.LAUNCH_REVIEW_PATH.read_text())
    review["files"][pin["path"]] = pin["sha256"]
    review["history_inventory"] = pin
    monkeypatch.setattr(
        module, "LAUNCH_REVIEW_SHA256", put(module.LAUNCH_REVIEW_PATH, review)["sha256"]
    )
    reseal_index(monkeypatch)


def check_terminals(scope, inventory, launch_rows):
    for row, launches in zip(inventory["terminal_states"], launch_rows, strict=True):
        module._terminal(scope, inventory, row, launches)


def test_same_schema_four_readonly_terminal_snapshots(tmp_path, monkeypatch):
    inventory, roots, launches, _ = fixture(tmp_path, monkeypatch)
    hashes = [hashlib.sha256((root / "batch.sqlite").read_bytes()).hexdigest() for root in roots]
    with AdmissionReadScope() as scope:
        check_terminals(scope, inventory, launches)
    assert hashes == [
        hashlib.sha256((root / "batch.sqlite").read_bytes()).hexdigest() for root in roots
    ]


@pytest.mark.parametrize("position", range(4))
@pytest.mark.parametrize(
    "change", ["binding", "stop", "episode", "event", "delete_event", "launch", "delete_db"]
)
def test_four_terminal_drift_cases(tmp_path, monkeypatch, position, change):
    _, roots, _, _ = fixture(tmp_path, monkeypatch)
    path = roots[position] / "batch.sqlite"
    if change == "delete_db":
        path.unlink()
    else:
        with sqlite3.connect(path) as db:
            if change == "binding":
                db.execute("UPDATE meta SET value='changed' WHERE key='binding'")
            elif change == "stop":
                db.execute("INSERT OR REPLACE INTO meta VALUES ('stop','changed')")
            elif change == "episode":
                db.execute("UPDATE episodes SET cap=2 WHERE ordinal=0")
            elif change == "event":
                db.execute("UPDATE events SET event='{}' WHERE seq=1")
            elif change == "delete_event":
                db.execute("DELETE FROM events WHERE seq=1")
            elif position == 0:
                db.execute("CREATE TABLE launches(stage TEXT,pid INTEGER,started REAL)")
            else:
                db.execute("INSERT INTO launches VALUES ('P4',999,2.0)")
    scope = AdmissionReadScope()

    poisoned(scope, lambda: module.verify_lineage(scope))
    if change == "delete_db":
        assert not path.exists()


def test_inventory_defensive_objects(tmp_path, monkeypatch):
    inventory, _, _, _ = fixture(tmp_path, monkeypatch)
    with AdmissionReadScope() as scope:
        actual = module.read_inventory(scope)
        actual["files"].clear()
        actual["terminal_states"][0]["root"] = "modified"
        assert module.read_inventory(scope) == inventory
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 1


def test_sql_rechecked_in_same_scope_without_cached_pass(tmp_path, monkeypatch):
    inventory, roots, launches, _ = fixture(tmp_path, monkeypatch)
    scope = AdmissionReadScope()
    check_terminals(scope, inventory, launches)
    with sqlite3.connect(roots[2] / "batch.sqlite") as db:
        db.execute("INSERT INTO meta VALUES ('stop','new stop')")

    def call():
        with module._guard(scope):
            check_terminals(scope, inventory, launches)

    poisoned(scope, call, "HISTORICAL_TERMINAL")


def test_explicit_null_stop_row_is_not_absence(tmp_path, monkeypatch):
    inventory, roots, launches, _ = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(roots[2] / "batch.sqlite") as db:
        db.execute("ALTER TABLE meta RENAME TO original_meta")
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO meta SELECT * FROM original_meta")
        db.execute("DROP TABLE original_meta")
        db.execute("INSERT INTO meta VALUES ('stop',NULL)")
    scope = AdmissionReadScope()

    def call():
        with module._guard(scope):
            check_terminals(scope, inventory, launches)

    poisoned(scope, call, "HISTORICAL_TERMINAL")


def test_fake_launch_view_is_not_original_absence(tmp_path, monkeypatch):
    inventory, roots, launches, _ = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(roots[0] / "batch.sqlite") as db:
        db.execute("CREATE VIEW launches AS SELECT 1 AS stage")
    scope = AdmissionReadScope()

    def call():
        with module._guard(scope):
            check_terminals(scope, inventory, launches)

    poisoned(scope, call, "LAUNCHES_MUST")


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e9999}', "[]"])
def test_central_event_strict_json(tmp_path, monkeypatch, raw):
    inventory, roots, launches, _ = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(roots[0] / "batch.sqlite") as db:
        db.execute("UPDATE events SET event=? WHERE seq=1", (raw,))
    scope = AdmissionReadScope()

    def call():
        with module._guard(scope):
            check_terminals(scope, inventory, launches)

    poisoned(scope, call)


@pytest.mark.parametrize(
    "change",
    [
        "root_count",
        "duplicate_root",
        "relative_root",
        "empty_files",
        "dynamic_db",
        "missing_ledger",
        "orphan_ledger",
    ],
)
def test_inventory_semantic_failure_poisons_scope(tmp_path, monkeypatch, change):
    inventory, roots, _, _ = fixture(tmp_path, monkeypatch)
    if change == "root_count":
        inventory["terminal_states"].pop()
    elif change == "duplicate_root":
        inventory["terminal_states"][1]["root"] = str(roots[0])
    elif change == "relative_root":
        inventory["terminal_states"][0]["root"] = "relative"
    elif change == "empty_files":
        inventory["files"] = {}
    elif change == "dynamic_db":
        inventory["files"][str(roots[0] / "batch.sqlite")] = "0" * 64
    elif change == "missing_ledger":
        del inventory["files"][inventory["sources"][0]["path"]]
    else:
        inventory["sources"][2]["path"] = str(tmp_path / "unowned.jsonl")
        inventory["files"][str(tmp_path / "unowned.jsonl")] = inventory["sources"][2]["sha256"]
    pin = put(module.INVENTORY_PATH, inventory)
    monkeypatch.setattr(module, "INVENTORY_SHA256", pin["sha256"])
    scope = AdmissionReadScope()
    poisoned(scope, lambda: module.read_inventory(scope))


def test_closed_scope_cannot_read_inventory(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    scope = AdmissionReadScope()
    scope.close()
    with pytest.raises(Exception, match="CLOSED"):
        module.read_inventory(scope)


def test_every_terminal_call_opens_new_readonly_connections(tmp_path, monkeypatch):
    inventory, _, launches, _ = fixture(tmp_path, monkeypatch)
    original, calls = sqlite3.connect, []

    def connect(path, *args, **kwargs):
        calls.append((path, kwargs))
        assert path.endswith("?mode=ro")
        assert kwargs["uri"] is True
        return original(path, *args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    with AdmissionReadScope() as scope:
        check_terminals(scope, inventory, launches)
        reads = scope.stats["first_reads"]
        check_terminals(scope, inventory, launches)
        assert scope.stats["first_reads"] == reads
    assert len(calls) == 8


def test_mirror_check_not_replaced_by_self_consistent_central_fingerprint(tmp_path, monkeypatch):
    inventory, roots, launches, all_events = fixture(tmp_path, monkeypatch)
    all_events[0][0]["session"] = "wrong local mirror"
    with sqlite3.connect(roots[0] / "batch.sqlite") as db:
        db.execute("UPDATE events SET event=? WHERE seq=1", (json.dumps(all_events[0][0]),))
    inventory["terminal_states"][0]["central_events_fingerprint"] = fingerprint(all_events[0])
    scope = AdmissionReadScope()

    def call():
        with module._guard(scope):
            check_terminals(scope, inventory, launches)

    poisoned(scope, call, "CENTRAL_LOCAL_MIRROR")


def test_complete_public_lineage_does_not_count_central_mirrors(tmp_path, monkeypatch):
    inventory, _, _, _ = fixture(tmp_path, monkeypatch)
    with AdmissionReadScope() as scope:
        actual = module.verify_lineage(scope)
        assert actual == history_module.presentation_history(scope)
        assert actual["requests"] == 58
        assert actual["known_raw_tokens"] == 1081429
        assert actual["actual_total_raw_tokens"] is None
        assert actual["reserved_raw_upper_bound"] == 28284
        assert actual["unresolved_reservations"] == inventory["original_unknown_complete_objects"]
        actual["sources"].clear()
        assert len(module.verify_lineage(scope)["sources"]) == 57
    assert scope.stats["first_reads"] == scope.stats["closing_reads"]


@pytest.mark.parametrize(
    "change",
    [
        "column",
        "extra_table",
        "marker",
        "extra_marker",
        "frozen_world",
        "source",
        "ledger",
        "inventory",
    ],
)
def test_full_entry_static_and_schema_drift(tmp_path, monkeypatch, change):
    inventory, roots, proofs, _ = fixture(tmp_path, monkeypatch)
    if change in {"column", "extra_table"}:
        with sqlite3.connect(roots[3] / "batch.sqlite") as db:
            db.execute(
                "ALTER TABLE launches ADD COLUMN extra TEXT"
                if change == "column"
                else "CREATE TABLE extra(value TEXT)"
            )
    elif change == "extra_marker":
        put(roots[3] / "live-launch-P4.json", {})
    else:
        paths = {
            "marker": Path(proofs[0]["launches"]["markers"][0]["path"]),
            "frozen_world": tmp_path / "static/World.sqlite",
            "source": Path(proofs[0]["schema"]["source_path"]),
            "ledger": Path(inventory["sources"][2]["path"]),
            "inventory": module.INVENTORY_PATH,
        }
        paths[change].write_bytes(b"changed")
    scope = AdmissionReadScope()
    poisoned(scope, lambda: module.verify_lineage(scope))


def test_public_same_scope_sql_change_and_close_failure(tmp_path, monkeypatch):
    _, roots, _, _ = fixture(tmp_path, monkeypatch)
    scope = AdmissionReadScope()
    module.verify_lineage(scope)
    with sqlite3.connect(roots[0] / "batch.sqlite") as db:
        db.execute("UPDATE episodes SET status='PENDING'")
    poisoned(scope, lambda: module.verify_lineage(scope), "HISTORICAL_TERMINAL")


def test_full_tree_child_is_not_only_direct_hash_checked(tmp_path, monkeypatch):
    inventory, _, _, _ = fixture(tmp_path, monkeypatch)
    child = put(
        tmp_path / "child.json", {"files": {str(tmp_path / "missing-grandchild"): "0" * 64}}
    )
    inventory["files"][child["path"]] = child["sha256"]
    reseal_inventory(monkeypatch, inventory)
    scope = AdmissionReadScope()
    poisoned(scope, lambda: module.verify_lineage(scope), "missing-grandchild")


def test_falsey_sql_error_poisoned_and_preserved(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)

    class FalseyError(RuntimeError):
        def __bool__(self):
            return False

    error = FalseyError("synthetic connection failure")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(module.sqlite3, "connect", fail)
    scope = AdmissionReadScope()
    assert poisoned(scope, lambda: module.verify_lineage(scope)) is error


def test_public_closed_and_poisoned_scope_cannot_begin(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    scope = AdmissionReadScope()
    scope.close()
    with pytest.raises(Exception, match="CLOSED"):
        module.verify_lineage(scope)
    scope = AdmissionReadScope()
    with pytest.raises(FileNotFoundError):
        scope.read_bytes(tmp_path / "absent", "0" * 64)
    with pytest.raises(Exception, match="POISONED"):
        module.verify_lineage(scope)
    with pytest.raises(FileNotFoundError):
        scope.close()


@pytest.mark.parametrize(
    "change",
    [
        "missing_file",
        "missing_inventory",
        "missing_launch_review",
        "extra_root",
        "replacement_path",
        "replacement_hash",
        "relative_path",
        "non_mapping",
        "extra_field",
        "wrong_status",
    ],
)
def test_exact_index_rejects_missing_added_or_replaced_roots(tmp_path, monkeypatch, change):
    fixture(tmp_path, monkeypatch)
    if change == "missing_file":
        module.EVIDENCE_INDEX_PATH.unlink()
    else:
        index = json.loads(module.EVIDENCE_INDEX_PATH.read_text())
        if change == "missing_inventory":
            del index["files"][str(module.INVENTORY_PATH)]
        elif change == "missing_launch_review":
            del index["files"][str(module.LAUNCH_REVIEW_PATH)]
        elif change == "extra_root":
            index["files"][str(tmp_path / "extra.json")] = "0" * 64
        elif change == "replacement_path":
            index["files"][str(tmp_path / "replacement.json")] = index["files"].pop(
                str(module.INVENTORY_PATH)
            )
        elif change == "replacement_hash":
            index["files"][str(module.INVENTORY_PATH)] = "0" * 64
        elif change == "relative_path":
            index["files"]["inventory.json"] = index["files"].pop(str(module.INVENTORY_PATH))
        elif change == "non_mapping":
            index["files"] = []
        elif change == "extra_field":
            index["additional_roots"] = []
        else:
            index["status"] = "PASS"
        monkeypatch.setattr(
            module, "EVIDENCE_INDEX_SHA256", put(module.EVIDENCE_INDEX_PATH, index)["sha256"]
        )
    calls = []
    original = module.verify_tree

    def tracked(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "verify_tree", tracked)
    scope = AdmissionReadScope()
    poisoned(scope, lambda: module.verify_lineage(scope))
    assert calls == []  # Reject malformed index before entering any subtree.


def test_one_tree_call_per_invocation_not_cross_call_completed_cache(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    original, calls = module.verify_tree, []

    def tracked(scope, path, digest):
        calls.append((path, digest))
        return original(scope, path, digest)

    monkeypatch.setattr(module, "verify_tree", tracked)
    with AdmissionReadScope() as scope:
        module.verify_lineage(scope)
        first = scope.stats["first_reads"]
        module.verify_lineage(scope)
        assert scope.stats["first_reads"] == first
    assert calls == [(module.EVIDENCE_INDEX_PATH, module.EVIDENCE_INDEX_SHA256)] * 2


def test_launch_root_grandchild_dependency_is_reached(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    child = put(
        tmp_path / "launch-child.json",
        {"files": {str(tmp_path / "missing-launch-grandchild"): "0" * 64}},
    )
    review = json.loads(module.LAUNCH_REVIEW_PATH.read_text())
    review["files"][child["path"]] = child["sha256"]
    monkeypatch.setattr(
        module, "LAUNCH_REVIEW_SHA256", put(module.LAUNCH_REVIEW_PATH, review)["sha256"]
    )
    reseal_index(monkeypatch)
    scope = AdmissionReadScope()
    poisoned(scope, lambda: module.verify_lineage(scope), "missing-launch-grandchild")


@pytest.mark.parametrize("root", ["inventory", "launch_review"])
def test_tree_success_does_not_skip_root_purpose_semantics(tmp_path, monkeypatch, root):
    inventory, _, _, _ = fixture(tmp_path, monkeypatch)
    if root == "inventory":
        inventory["status"] = "WRONG_PURPOSE"
        reseal_inventory(monkeypatch, inventory)
    else:
        review = json.loads(module.LAUNCH_REVIEW_PATH.read_text())
        review["roots"][0]["launches"]["markers"][0]["historical_original_pid_and_time"] = "PROVEN"
        monkeypatch.setattr(
            module, "LAUNCH_REVIEW_SHA256", put(module.LAUNCH_REVIEW_PATH, review)["sha256"]
        )
        reseal_index(monkeypatch)
    scope = AdmissionReadScope()
    poisoned(scope, lambda: module.verify_lineage(scope), "EXACT_REVIEWED|UNKNOWN_MUST_REMAIN")
