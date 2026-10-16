"""A task-wording intervention changes no delivered evidence or source request."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_meme_reader_rules import messages_for


def test_paired_messages_only_add_generic_rule_task_to_system_instruction():
    request = {"messages": [{"role": "system", "content": "original instructions"},
                            {"role": "user", "content": '{"question":"q","facts":["if"]}'}],
               "private_reference": "EVALUATOR_ONLY"}
    original = copy.deepcopy(request)
    baseline = messages_for(request, None)
    treatment = messages_for(request, "Apply the supplied rules.")
    assert request == original
    assert baseline == request["messages"]
    assert treatment[1:] == baseline[1:]
    assert treatment[0]["content"] == baseline[0]["content"] + "\nApply the supplied rules."
    assert "EVALUATOR_ONLY" not in str(treatment)
