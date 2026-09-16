import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_artifacts import artifact_bytes, export_artifacts


def fixture():
    return ({"objects": ["code", "report"], "scope": "isolated", "version": 3,
             "records": {"code": {"object_id": "code", "content": "raise RuntimeError('未执行')\n"},
                         "report": {"object_id": "report", "status": "blocked"}}},
            {"code": {"path": "src/draft.py", "format": "text"},
             "report": {"path": "report.json", "format": "json"}})


def test_exact_bytes_no_execution_no_implicit_success(tmp_path):
    state, mapping = fixture()
    prior = copy.deepcopy(state)
    result = export_artifacts(state, mapping, tmp_path / "export")
    assert (tmp_path / "export/src/draft.py").read_text() == state["records"]["code"]["content"]
    assert state == prior
    assert not result["execution_proven_by_exporter"]
    assert not result["external_publication"] and not result["files_executed"]
    for name, expected in result["files"].items():
        assert hashlib.sha256((tmp_path / "export" / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("name", ["../escape", "/escape", "a/../b", "a//b", "./b",
                                  "a\\b", "C:drive", ".git/config", "a\x00b"])
def test_unsafe_paths_rejected_before_write(tmp_path, name):
    state, mapping = fixture()
    mapping["code"]["path"] = name
    with pytest.raises(ValueError):
        export_artifacts(state, mapping, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("path", ["src/draft.py", "src"])
def test_path_collision(path):
    state, mapping = fixture()
    mapping["report"]["path"] = path
    with pytest.raises(ValueError):
        artifact_bytes(state, mapping)


@pytest.mark.parametrize("change", ["missing", "wrong_identity", "empty", "nontext"])
def test_done_claim_does_not_materialize_missing_work(change):
    state, mapping = fixture()
    if change == "missing":
        del state["records"]["code"]
    elif change == "wrong_identity":
        state["records"]["code"]["object_id"] = "report"
    else:
        state["records"]["code"]["content"] = "" if change == "empty" else {"done": True}
    with pytest.raises(ValueError):
        artifact_bytes(state, mapping)


def test_existing_directory_preserved(tmp_path):
    state, mapping = fixture()
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "user.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError):
        export_artifacts(state, mapping, destination)
    assert sentinel.read_text() == "keep"


def test_symlink_parent_denied(tmp_path):
    state, mapping = fixture()
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ValueError, match="SYMLINK"):
        export_artifacts(state, mapping, tmp_path / "link/export")
    assert not (tmp_path / "real/export").exists()
