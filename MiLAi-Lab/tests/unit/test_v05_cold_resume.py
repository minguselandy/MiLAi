"""Ensure the cold policy comparison does not inject differential source information."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from check_v0210_control import LAB
from run_v0210_v05_resume import messages_for


def test_cold_policy_changes_only_trusted_policy_and_keeps_return_conditions():
    config = json.loads((LAB / "configs/v0210-v05-resume.json").read_text())
    head = {"status": "ACTIVE", "version": 3, "payload": {"return_text": config["return_text"]},
            "authority": "HOST_WORKING", "warnings": []}
    for scenario in config["scenarios"]:
        normal = messages_for(config, scenario + "-N", head)
        control = messages_for(config, scenario + "-S", head)
        assert normal[:2] == control[:2] and normal[2] != control[2]
        content = json.loads(normal[1]["content"])
        assert content["restored"]["payload"] == head["payload"]
        assert content["sources"][-1] == config["scenarios"][scenario]
        assert "rubric" not in content
