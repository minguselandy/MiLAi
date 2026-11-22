"""Real snapshot isolation and pre-outcome sampling, without action-quality assumptions."""
import sqlite3

import pytest

from small_control_branches import copy_source_bank, select_pool


def test_sqlite_branches_and_original_remain_independent_with_percent_encoded_path(tmp_path):
    source = tmp_path / "paper%2E1.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE source_value (value TEXT)")
        connection.execute("INSERT INTO source_value VALUES ('original')")
    first, second = tmp_path / "first", tmp_path / "second"
    copy_source_bank(source, first)
    copy_source_bank(source, second)
    with sqlite3.connect(first / "memory.sqlite") as connection:
        connection.execute("UPDATE source_value SET value='branch' ")
    for path in [source, second / "memory.sqlite"]:
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT value FROM source_value").fetchone()[0] == "original"
    with pytest.raises(sqlite3.OperationalError):
        copy_source_bank(tmp_path / "absent.sqlite", tmp_path / "absent-copy")
    assert not (tmp_path / "absent.sqlite").exists()


def test_random_source_quota_and_KO_priority_are_fixed_without_quality_labels():
    rows = [{"sample_id": str(i), "group_id": str(i), "split": "train",
        "observation": {"observed_materials": [{"selected": False}]},
        "actions": [{"kind": "HANDOFF"}, {"kind": "HANDOFF"}],
        "offline_supervision": {"unreviewed": True}} for i in range(20)]
    selected = select_pool(rows, 16, .30, 17)
    assert len({s["row"]["group_id"] for s in selected}) == 16
    assert sum(s["sampling"].startswith("random") for s in selected) == 5
    changed = [{**row, "offline_supervision": {"quality": "opposite"}} for row in rows]
    assert [s["row"]["sample_id"] for s in selected] == [
        s["row"]["sample_id"] for s in select_pool(changed, 16, .30, 17)]
    with pytest.raises(ValueError, match="TRAIN"):
        select_pool([{**rows[0], "split": "confirm"}], 1, 1., 17)
