"""Small-tier snapshots retain complete histories and every referenced image."""
import json
from pathlib import Path

import pytest

from prepare_lme_small_snapshot import prepare_snapshot


def release(root: Path):
    root.mkdir()
    (root / "haystacks").mkdir()
    questions = [{"id": "q1", "question": "one\u2028line\u2029next", "answer": "offline one",
                  "image": "q/one.png"},
                 {"id": "q2", "question": "two", "answer": "offline two", "image": None}]
    (root / "questions.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in questions))
    (root / "haystacks/lme_v2_small.json").write_text(json.dumps({"q1": ["b", "a"], "q2": ["a"]}))
    trajectories = [{"id": "a", "states": [{"accessibility_tree": "entire first observation",
        "thought": "recorded interpretation", "action": None, "screenshot": "screens/a/0.png"},
        {"accessibility_tree": "entire later observation", "action": "click",
         "screenshot": "screens/a/1.png"}]},
        {"id": "unused", "states": [{"screenshot": "absent-unused.png"}]},
        {"id": "b", "states": [{"accessibility_tree": "another trajectory",
                                  "screenshot": "screens/b/0.png"}]}]
    lines = [json.dumps(row, indent=None) + "\n" for row in trajectories]
    (root / "trajectories.jsonl").write_text("".join(lines))
    for name in ["q/one.png", "screens/a/0.png", "screens/a/1.png", "screens/b/0.png"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic asset bytes")
    return lines


def test_all_questions_full_states_order_and_assets_survive(tmp_path):
    source, output = tmp_path / "source", tmp_path / "snapshot"
    lines = release(source)
    report = prepare_snapshot(source, output)
    assert report["status"] == "COMPLETE_SMALL_SNAPSHOT"
    assert report["questions"] == 2 and report["retained_trajectories"] == 2
    assert report["retained_states"] == 3 and report["copied_assets"] == 4
    assert (output / "trajectories.jsonl").read_text() == lines[0] + lines[2]
    assert (output / "questions.jsonl").read_bytes() == (source / "questions.jsonl").read_bytes()
    assert json.loads((output / "haystacks/lme_v2_small.json").read_text())["q1"] == ["b", "a"]
    (source / "screens/a/1.png").write_bytes(b"changed original")
    assert (output / "screens/a/1.png").read_bytes() == b"synthetic asset bytes"


def test_missing_selected_image_is_not_silently_dropped(tmp_path):
    source, output = tmp_path / "source", tmp_path / "snapshot"
    release(source)
    (source / "screens/a/1.png").unlink()
    with pytest.raises(FileNotFoundError):
        prepare_snapshot(source, output)
    report = json.loads((output / "preparation.json").read_text())
    assert report["status"] == "FAILED" and report["model_calls"] == 0
    assert report["cpu_seconds"] > 0
