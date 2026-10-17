"""Shuffled mixed-corpus pools retain true lexical controls and full delivery."""

import json

from global_reader_controls import prepare
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from prepare_musique_decisions import ranked_pool


def test_variable_pool_lexical_mapping_and_full_delivery(tmp_path):
    source = {"id": "uuid", "question": "Which planet is red?", "paragraphs": [
        {"idx": i, "title": title, "paragraph_text": body, "is_supporting": i == 2}
        for i, (title, body) in enumerate([
            ("Water", "Water is liquid."), ("Wind", "Wind blows."),
            ("Mars", "Mars is the red planet."), ("Grass", "Grass grows."),
            ("Cloud", "Clouds move."), ("Ice", "Ice is frozen water.")])]}
    lexical = ranked_pool(source, 6)
    pool = list(reversed(lexical))
    meta = {"row": 0, "family": "family", "dataset": "two_wiki_train_mirror",
            "pool_source_indices": pool, "bm25_source_indices": lexical}
    candidates = [{"id": f"p{slot}", "title": source["paragraphs"][i]["title"],
                   "text": source["paragraphs"][i]["paragraph_text"]}
                  for slot, i in enumerate(pool)]
    decisions, sources, budget = [tmp_path / name for name in
                                 ("decisions.jsonl", "sources.jsonl", "budget.json")]
    decisions.write_text(json.dumps({"metadata": meta, "state": {
        "question": source["question"], "read_evidence": [], "candidates": candidates}}) + "\n")
    sources.write_text(json.dumps({"metadata": meta, "source": source}) + "\n")
    RunBudget(RunLimits(), budget).record_compute("fixture", {})
    output = tmp_path / "output"
    prepare(decisions, sources, budget, output, "test-only")
    def read(path):
        return json.loads(path.read_text())
    selected = read(output / "selections/bm25/row-0/k4.json")["selected_ids"]
    assert selected == [f"p{pool.index(i)}" for i in lexical[:4]]
    full = read(output / "selections/bm25/row-0/full_pool.json")["selected_ids"]
    assert len(full) == 6 and set(full) == {p["id"] for p in candidates}
    assert read(output / "common-retrieval-costs.json")[0]["source_paragraphs"] == 6
    assert read(output / "labels.jsonl")["dataset"] == "two_wiki_train_mirror"
    assert read(output / "labels.jsonl")["source"]["answer_aliases"] == []
