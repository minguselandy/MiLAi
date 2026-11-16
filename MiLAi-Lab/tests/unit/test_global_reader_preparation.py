"""Source identities, state changes and splits survive broad offline preparation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_global_reader import derive_global_states, select_questions


def test_metadata_sampling_keeps_pairs_and_excludes_whole_questions():
    rows = [{"row": i, "family": f, "question_id": q, "split": "train"}
            for i, (f, q) in enumerate([
                ("a", "2hop__one"), ("a", "2hop__one"),
                ("a", "3hop__two"), ("a", "3hop__two"),
                ("b", "2hop__three"), ("c", "4hop__four")])]
    result = select_questions(rows, {"3hop__two", "4hop__four"}, 7)
    assert set(result) == {2}
    assert {g["family"] for g in result[2]} == {"a", "b"}
    assert next(g for g in result[2] if g["family"] == "a")["rows"] == rows[:2]
    reordered = select_questions(list(reversed(rows)), {"3hop__two", "4hop__four"}, 7)
    assert [g["question_id"] for g in result[2]] == [g["question_id"] for g in reordered[2]]
    assert {r["row"] for g in reordered[2] for r in g["rows"]} == {0, 1, 4}


def test_state_changes_track_literal_equivalent_supports_and_random_aliases():
    paragraphs = [{"title": f"topic {i}", "paragraph_text": f"fact {i} about the query",
                   "idx": i, "is_supporting": i in (1, 4)} for i in range(8)]
    paragraphs[6].update(title=paragraphs[1]["title"],
                         paragraph_text=paragraphs[1]["paragraph_text"])
    record = {"metadata": {"row": 42, "family": "f", "question_id": "2hop__test",
                           "split": "dev"},
              "source": {"question": "What fact?", "answer": "NEVER_VISIBLE_ANSWER",
                         "answerable": True, "paragraphs": paragraphs}}
    rows = derive_global_states(record, 7)
    assert any("stop_sufficient" in r["gold"]["next"]["probabilities"] for r in rows)
    for row in rows:
        meta = row["metadata"]
        assert meta["family"] == "f" and meta["split"] == "dev"
        assert not meta["training_allowed"]
        assert "NEVER_VISIBLE_ANSWER" not in str({k: row[k] for k in ("state", "questions")})
        visible = row["state"]["read_evidence"] + row["state"]["candidates"]
        assert len(visible) == 8
        for item in visible:
            idx = meta["pool_source_indices"][int(item["id"][1:])]
            assert item["text"] == paragraphs[idx]["paragraph_text"]
        seen = {(paragraphs[i]["title"], paragraphs[i]["paragraph_text"])
                for i in meta["opened_source_indices"]}
        for action in row["gold"]["next"]["probabilities"]:
            if action.startswith("open_"):
                idx = meta["pool_source_indices"][int(action.removeprefix("open_p"))]
                key = paragraphs[idx]["title"], paragraphs[idx]["paragraph_text"]
                assert key in {(paragraphs[i]["title"], paragraphs[i]["paragraph_text"])
                               for i in (1, 4)} - seen
                assert action in row["questions"]["next"]["criteria"]
    record["source"]["answerable"] = False
    negative = derive_global_states(record, 7)
    full = next(r for r in negative if "reference_complete" in r["metadata"]["prefix_origins"])
    assert full["gold"]["next"]["probabilities"] == {"stop_exhausted": 1.0}
