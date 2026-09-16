"""Explicit synthetic development chains; never reads the independently sealed confirmation pool."""

import argparse
from pathlib import Path

from replay_v0213_cost import save, sha


def prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    tools = [{"name": "PrepareArchive", "description": "Draft an archive job, without executing it",
              "parameters": {"type": "object", "properties": {
                  "workspace": {"type": "string"}, "bucket": {"type": "string"},
                  "days": {"type": "integer"}}, "required": ["workspace", "bucket", "days"]}}]
    specs = [
        ("dev-01", "NO_MEMORY", "Quartz", "quartz-new", 12),
        ("dev-02", "SHORT_HISTORY", "Atlas", "atlas-reports", 45),
        ("dev-03", "LONG_SELECTIVE", "Orion", "orion-builds", 90),
        ("dev-04", "CLARIFICATION", "Maple", "maple-east", 30),
        ("dev-05", "NEW_OBSERVATION", "Cedar", "cedar-v1", 20),
        ("dev-06", "SAVE_COLD_RESUME", "Pine", "pine-audit", 60),
        ("dev-07", "CONCURRENT", "Mira", "mira-only", 15),
        ("dev-08", "CONCURRENT", "Vela", "vela-only", 75),
    ]
    entries = []
    for key, category, workspace, bucket, days in specs:
        for phase in (0, 1):
            online = root / key / "online" / f"phase-{phase}"
            online.mkdir(parents=True)
            current_bucket = "cedar-v2" if category == "NEW_OBSERVATION" and phase == 1 else bucket
            fact = (f"Workspace {workspace}: approved archive bucket is {current_bucket}; "
                    f"retention is {days} days. These are configuration decisions, "
                    "not job results.\n")
            question = (f"Prepare an archive job for {workspace} "
                        "using the agreed bucket and retention.")
            current = {}
            source = fact
            if category == "NO_MEMORY":
                question = (f"Prepare an archive for {workspace}, bucket {bucket}, {days} days. "
                            "All required inputs are here; do not consult history.")
                current = {"workspace": workspace, "bucket": bucket, "days": days}
                source = "Unrelated archived configuration; not needed for this request.\n"
            if category == "LONG_SELECTIVE":
                source = ("Unrelated office schedule and maintenance discussion.\n" * 5000 + fact
                          + "Unrelated office schedule and maintenance discussion.\n" * 5000)
            if category == "CLARIFICATION":
                source = ("Workspace Maple has two active archive destinations: maple-east and "
                          "maple-west. Retention is 30 days. "
                          "No preferred destination is recorded.\n")
                if phase == 1:
                    question += " I choose maple-east now."
                    current = {"bucket": "maple-east"}
            if category == "NEW_OBSERVATION" and phase == 1:
                source = (f"Earlier decision: {workspace} used cedar-v1 for 20 days.\n"
                          f"New observation supersedes that bucket decision. {fact}")
                question += " Apply the latest observation, not the old bucket."
            task = {"question": question, "business_tools": tools, "current_inputs": current,
                    "action_mode": "ACTION_INTENT_ONLY"}
            if category == "SAVE_COLD_RESUME":
                if phase == 0:
                    task["remember_sources_on_success"] = True
                    task["question"] += " Remember this agreed configuration for our next session."
                else:
                    source = ""
                    task["question"] += " Use the configuration I asked you to remember."
            save(online / "task.json", task)
            if source:
                (online / "source-01.txt").write_text(source)
            evaluation = root / key / "evaluation"
            evaluation.mkdir(exist_ok=True)
            expected = {"calls": [{"name": "PrepareArchive", "arguments": {
                "workspace": workspace, "bucket": current_bucket, "days": days}}]}
            contract = {"expected_intent": expected, "required_support": [fact.strip()],
                        "category": category, "phase": phase,
                        "no_memory_needed": category == "NO_MEMORY"}
            if category == "CLARIFICATION" and phase == 0:
                contract = {"expected_readiness": "NEEDS_CLARIFICATION", "category": category,
                            "required_support": [], "phase": phase}
            save(evaluation / f"contract-{phase}.json", contract)
        entries.append({"key": key, "category": category, "cluster": key,
                        "lineage": f"V0214_SYNTHETIC_DEV_{workspace}"})
    paths = [path for path in root.rglob("*") if path.is_file()]
    save(root / "manifest.json", {"status": "D5_SYNTHETIC_DEV_FROZEN", "accepted": entries,
                                   "files": {str(path.relative_to(root)): sha(path.read_bytes())
                                             for path in paths}, "confirmation_used": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    prepare(parser.parse_args().root)
    print("D5_SYNTHETIC_DEVELOPMENT_INPUTS_FROZEN")
