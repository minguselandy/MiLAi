"""Public collection inputs preserve literal source arrivals and exclude offline labels."""
from milai_lab.datasets.intent_training import memops_intent_history, musique_intent_request


def test_memops_first_last_cuts_keep_intervening_roles_without_expected_answers():
    def event(i, role):
        return {"session_id": "session", "event_key": str(i), "role": role,
                "content": f"literal turn {i}", "occurred_at": None,
                "gold_evidence": "must not reach Host"}

    history = {"id": "history", "source_family": "background", "split": "train", "steps": [
        {"id": "early", "content": "Current status?", "incoming_sources": [event(0, "user")],
         "expected": "offline answer"},
        {"id": "repeat", "content": "Current status?", "incoming_sources": []},
        {"id": "middle", "content": "Current status?", "incoming_sources": [event(1, "assistant")]},
        {"id": "late", "content": "Current status?", "incoming_sources": [event(2, "user")],
         "expected": "different offline answer"}]}
    projected = memops_intent_history(history)
    assert [r["id"] for r in projected["requests"]] == ["early", "late"]
    assert [s["role"] for s in projected["requests"][1]["incoming_sources"]] == [
        "assistant", "user"]
    assert all("gold_evidence" not in s for r in projected["requests"]
               for s in r["incoming_sources"])
    assert all("expected" not in r for r in projected["requests"])
    assert projected["continuous"] and projected["source_group"] == "background"


def test_multihop_answerability_and_support_do_not_change_public_projection():
    row = {"question": "Who founded the institution?", "answer": "OFFLINE ANSWER",
           "answerable": True, "question_decomposition": [{"answer": "HIDDEN BRIDGE"}],
           "paragraphs": [{"title": "Institution", "paragraph_text": "Literal public passage.",
                            "idx": 4, "is_supporting": True}]}
    first = musique_intent_request(row, 7)
    row.update(answer="OTHER OFFLINE ANSWER", answerable=False, question_decomposition=[])
    row["paragraphs"][0]["is_supporting"] = False
    assert musique_intent_request(row, 7) == first
    assert first["sources"][0]["content"] == "Institution\nLiteral public passage."
    assert "is_supporting" not in first["sources"][0]
