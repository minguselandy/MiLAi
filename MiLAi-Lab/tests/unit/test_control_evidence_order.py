"""Native-key alignment across independent SQLite task/state assignments."""

import json
import sqlite3
import zlib

import pytest

from milai_lab.datasets.memory_control_store import connect
from milai_lab.runners.control_evidence_order import align, align_file, freeze, read_canonical_row


def fixture(tmp_path, name, task_ids, state_ids):
    master = tmp_path / f"{name}-master.sqlite"
    with sqlite3.connect(master) as db:
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO metadata VALUES('run_id',?)", (json.dumps(name),))
        db.execute("""CREATE TABLE experiment_tasks(id INTEGER PRIMARY KEY,dataset TEXT,split TEXT,
                   native_group TEXT,native_id TEXT,setting TEXT,source_row INTEGER,
                   experiment_role TEXT,clean_role TEXT)""")
        for ordinal, tid in enumerate(task_ids):
            db.execute(
                "INSERT INTO experiment_tasks VALUES(?, 'musique_full','train','pair',"
                "'same-native-id','full',?,'train','train')",
                (tid, ordinal),
            )
    path = tmp_path / f"{name}-evidence.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE manifest(field TEXT PRIMARY KEY,value TEXT)")
        db.executemany(
            "INSERT INTO manifest VALUES(?,?)",
            [
                ("protocol", json.dumps([str(master), 11, 6, 2048, 32, 8])),
                ("complete", "2"),
                ("replay_complete", "2"),
            ],
        )
        db.execute(
            "CREATE TABLE roots(id INTEGER PRIMARY KEY,task_id INTEGER,"
            "source TEXT,native_group TEXT,data BLOB)"
        )
        for local, (tid, prefix) in zip(
            state_ids,
            [
                (task_ids[0], ["search"]),
                (task_ids[1], ["search"]),
                (task_ids[0], ["search", "read_0"]),
            ],
            strict=True,
        ):
            row = dict(
                task_id=tid,
                source="musique_full",
                native_group_id="pair",
                split_role="train",
                root_state_id=[tid, *prefix],
                online=dict(observation={}),
                weak={},
                demo=None,
            )
            db.execute(
                "INSERT INTO roots VALUES(?,?,'musique_full','pair',?)",
                (local, tid, zlib.compress(json.dumps(row).encode())),
            )
    return master, path


def test_restored_members_prefixes_and_full_payloads(tmp_path):
    original, evidence = fixture(tmp_path, "before", [1, 2], [1, 2, 3])
    rebuilt, second = fixture(tmp_path, "after", [42, 11], [70, 20, 10])
    registered = tmp_path / "roots.gz"
    with connect(evidence) as src:
        freeze(src, original, registered)
    with connect(second) as db:
        summary = align_file(db, registered, rebuilt, tmp_path / "readback.gz", evidence)
        assert (
            summary["changed_root_addresses"]
            == summary["changed_task_addresses"]
            == summary["equivalent_payloads"]
            == 3
        )
        _, _, result = align(db, registered, rebuilt)
        assert [(a.frozen_row, a.local_row, a.frozen_task, a.local_task) for a in result] == [
            (1, 70, 1, 42),
            (2, 20, 2, 11),
            (3, 10, 1, 42),
        ]
        assert read_canonical_row(db, result[-1])["root_state_id"] == [1, "search", "read_0"]
    with sqlite3.connect(second) as db:
        db.execute("DELETE FROM roots WHERE id=10")
    with connect(second) as db, pytest.raises(ValueError, match="counts differ"):
        align(db, registered, rebuilt)


def test_native_collision_and_changed_labels_are_visible(tmp_path):
    master, path = fixture(tmp_path, "sample", [1, 2], [1, 2, 3])
    other, copy = fixture(tmp_path, "rebuild", [1, 2], [1, 2, 3])
    registered = tmp_path / "roots.gz"
    with connect(path) as orig:
        freeze(orig, master, registered)
    with sqlite3.connect(copy) as db:
        row = json.loads(
            zlib.decompress(db.execute("SELECT data FROM roots WHERE id=1").fetchone()[0])
        )
        row["demo"] = "handoff"
        db.execute("UPDATE roots SET data=? WHERE id=1", (zlib.compress(json.dumps(row).encode()),))
    with connect(copy) as db, pytest.raises(ValueError, match="supervision differs"):
        align_file(db, registered, other, tmp_path / "out.gz", path)
    with sqlite3.connect(other) as db:
        db.execute("UPDATE experiment_tasks SET source_row=0")
    with connect(copy) as db, pytest.raises(ValueError, match="ambiguous"):
        align(db, registered, other)


def test_fitter_shuffles_and_loads_the_same_native_rows(tmp_path):
    import random
    from argparse import Namespace

    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from milai_lab.runners.pretrained_control_train import TrainingRoots

    master, original = fixture(tmp_path, "v1", [1, 2], [9, 12, 15])
    other, rebuilt = fixture(tmp_path, "v2", [71, 72], [201, 7, 42])
    order = tmp_path / "order.gz"
    with connect(original) as db:
        freeze(db, master, order)
    first = TrainingRoots(Namespace(objective="evidence", data=original, probe=0))
    second = TrainingRoots(
        Namespace(
            objective="evidence",
            data=rebuilt,
            probe=0,
            evidence_order_map=order,
            evidence_master=other,
        )
    )
    try:
        before = list(first.epoch(random.Random(11), {"musique_full": 1.0}))  # noqa: S311
        after = list(second.epoch(random.Random(11), {"musique_full": 1.0}))  # noqa: S311
        assert before == after
        assert all(first.row(key) == second.row(key) for key, _, _ in before)
    finally:
        first.db.close()
        second.db.close()
