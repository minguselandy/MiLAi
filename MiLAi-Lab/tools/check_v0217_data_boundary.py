"""Real WMA structure projection, plus explicit event postconditions; zero model calls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from v0217_admission_contract import checkpoint_session_prefix, online_question, online_sessions


def check(root: Path) -> dict:
    path = root / "wma/lifelong/personal/personal_18.json"
    raw = path.read_bytes()
    sample = json.loads(raw)
    checks = []

    def record(name: str, passed: bool) -> None:
        checks.append({"name": name, "passed": passed})

    forbidden = {"memory_points", "qa_checkpoints", "answer", "gold_answer", "evidence",
                 "question_type", "question_type_abbrev", "difficulty", "file_path"}

    def public_keys_only(value):
        if isinstance(value, dict):
            return not (set(value) & forbidden) and all(
                public_keys_only(item) for item in value.values())
        if isinstance(value, list):
            return all(public_keys_only(item) for item in value)
        return True

    for checkpoint in sample["qa_checkpoints"]:
        prefix = checkpoint_session_prefix(sample, checkpoint["covered_sessions"])
        view = online_sessions(sample, prefix,
                               profile="official_caption_diagnostic")
        record(checkpoint["checkpoint_id"] + ":prefix_and_private_fields", public_keys_only(view)
               and [s["session_id"] for s in view["sessions"]] == prefix)
        for index, question in enumerate(checkpoint["questions"]):
            record(checkpoint["checkpoint_id"] + f":question_{index}",
                   public_keys_only(online_question(question)))
    first = sample["qa_checkpoints"][0]
    try:
        online_sessions(sample, first["covered_sessions"])
    except ValueError as exc:
        record("native_text_profile_fails_closed_for_missing_images", "MODALITY" in str(exc))
    else:
        record("native_text_profile_fails_closed_for_missing_images", False)
    # Same raw structure, private-field and future-dialogue canaries; no gold text output.
    contaminated = copy.deepcopy(sample)
    contaminated["memory_points"] = "PRIVATE_LABEL_CANARY"
    contaminated["sessions"][0]["memory_points"] = "PRIVATE_LABEL_CANARY"
    for session in contaminated["sessions"][len(first["covered_sessions"]):]:
        for turn in session["dialogue"]:
            turn["content"] = "PRIVATE_FUTURE_CANARY"
    visible = online_sessions(contaminated, first["covered_sessions"],
                              profile="official_caption_diagnostic")
    record("real_structure_label_and_future_canary", "PRIVATE_" not in json.dumps(visible))

    replay_path = root / "fixtures-v1/event-replays.json"
    events = json.loads(replay_path.read_text())
    for family in events:
        for index, replay in enumerate(family["replays"]):
            state = replay["state"][0]["properties"]
            if family["family"] == "executive":
                valid = "10:30" in state["Notes"]["rich_text"][0]["text"]["content"]
                valid &= replay["events"][0]["time"] == "2026-03-24T09:00:00+08:00"
                valid &= len(replay["messages"]) == 1
            else:
                valid = state["Compliance Flag"]["select"]["name"] == "enhanced_review_required"
                valid &= "operational_rotation" in state["Official Delay Reason"][
                    "rich_text"][0]["text"]["content"]
                valid &= [e["time"] for e in replay["events"]] == [
                    "2024-03-17T14:52:00+08:00", "2024-03-18T09:05:00+08:00"]
                valid &= len(replay["messages"]) == 2
            record(f"{family['family']}:stub_event_state_version_{index}", valid)
    report = {"status": "DATA_BOUNDARY_AND_STUB_POSTCONDITIONS_ONLY",
              "source_sha256": hashlib.sha256(raw).hexdigest(),
              "event_receipt_sha256": hashlib.sha256(replay_path.read_bytes()).hexdigest(),
              "sessions": len(sample["sessions"]), "checkpoints": len(sample["qa_checkpoints"]),
              "questions": sum(len(cp["questions"]) for cp in sample["qa_checkpoints"]),
              "attachment_references": sum(len(turn.get("attachments") or [])
                  for session in sample["sessions"] for turn in session["dialogue"]),
              "checks": checks, "passed": sum(row["passed"] for row in checks),
              "total": len(checks), "model_requests": 0, "images_downloaded": 0,
              "native_runtime_verified": False, "native_multimodal_equivalence": False,
              "semantic_judge_validated": False}
    with (root / "data-boundary-result.json").open("x") as stream:
        json.dump(report, stream, indent=2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    result = check(parser.parse_args().root)
    print(json.dumps({key: value for key, value in result.items() if key != "checks"}))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)
