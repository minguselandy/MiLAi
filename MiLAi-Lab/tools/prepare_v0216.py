"""Synthetic stress trajectories: quantitative trace joins and multi-constraint placement."""

from __future__ import annotations

import argparse
from pathlib import Path

from replay_v0213_cost import save, sha


def materials(key: str, phase: int, distractors: int) -> tuple[dict, dict, dict]:
    changed = phase == 2
    if key == "trace":
        question = ("For the CURRENT measurement of upload U32, identify the measured component "
            "with the largest exclusive critical-path duration. Return the component category, "
            "not an intervention. Do not infer an unmeasured root cause.")
        decisions = ["DATABASE_WAIT", "FILESYSTEM_SYNC", "CPU_PARSING", "NETWORK_WAIT",
                     "INSUFFICIENT_EVIDENCE"]
        trace = "T92" if changed else "T81"
        mapping = f"Current trace registry: upload U32 -> {trace}. This registry selects the " \
            "current measurement, not the largest historical or project-wide trace."
        old = "T81 exclusive critical-path durations in ms: DB=84, SYNC=6, PARSE=9, NET=3."
        current = "T92 exclusive critical-path durations in ms: DB=3, SYNC=196, PARSE=8, NET=4."
        background = "\n".join(
            f"Other-upload record U{400+i}/T{400+i}: DB={210+i}, SYNC=5, PARSE=7, NET=4 ms. "
            "The database wait dominates this other upload. A support discussion proposes "
            "database saturation as a plausible explanation of slow uploads; its scope is "
            f"U{400+i}, not a measurement of every upload."
            for i in range(distractors))
        sources = {
            "source-01.txt": "Timing dictionary: DB means DATABASE_WAIT, SYNC means "
                "FILESYSTEM_SYNC, PARSE means CPU_PARSING, NET means NETWORK_WAIT. Values are "
                "exclusive durations on the measured critical path; compare within one trace.",
            "source-02.txt": mapping,
            "source-03.txt": background + "\n" + old + ("\n" + current if changed else ""),
            "source-04.txt": "Several hypotheses can explain a slow upload: database waiting, "
                "filesystem synchronization, parsing or network waiting. Hypotheses are not "
                "measurements. Resolve the question with the current registry and trace.",
            "source-05.txt": "Unrelated activity: maintenance review starts at " +
                ("tick 12." if phase == 0 else "tick 13; no measurement changed for this notice.")}
        expected = "FILESYSTEM_SYNC" if changed else "DATABASE_WAIT"
        support = [mapping, current if changed else old,
                   "SYNC means FILESYSTEM_SYNC" if changed else "DB means DATABASE_WAIT"]
        domain = "QUANTITATIVE_CURRENT_TRACE_JOIN"
    else:
        question = ("Choose a processing site for job J17 using the CURRENT allocation snapshot. "
            "J17 requires a ceramic-compatible machine, uninterrupted power, at least 8 capacity "
            "units available to J17, and finish tick no later than 40. Propose a site only; "
            "do not book or execute it. All requirements must hold together.")
        decisions = ["NORTH", "EAST", "WEST", "INSUFFICIENT_EVIDENCE"]
        revision = "R8" if changed else "R7"
        mapping = f"Allocation registry: the current snapshot for job J17 is {revision}. " \
            "Other jobs' reserved capacity is not availability for J17."
        old = "J17/R7: NORTH power=on, capacity=12, finish=38; EAST power=on, capacity=4, " \
            "finish=30; WEST power=on, capacity=20, finish=22."
        current = "J17/R8: NORTH power=off, capacity=12, finish=38; EAST power=on, capacity=10, " \
            "finish=39; WEST power=on, capacity=20, finish=22."
        background = "\n".join(
            f"Booking for OTHER job J{600+i}/R{600+i}: NORTH power=on, capacity=16, finish=28; "
            "EAST power=on, capacity=4, finish=45; WEST power=on, capacity=20, finish=20. "
            "The dispatcher favors NORTH for this other booking. Reserved capacity and timing "
            f"here apply to J{600+i}, not to every job in the project."
            for i in range(distractors))
        sources = {
            "source-01.txt": "Placement rule: eligibility is the conjunction of the job's "
                "material, power, capacity and deadline constraints in its current snapshot. "
                "Faster completion alone does not waive another requirement.",
            "source-02.txt": mapping,
            "source-03.txt": background + "\n" + old + ("\n" + current if changed else ""),
            "source-04.txt": "Machine compatibility: NORTH supports ceramic and polymer; "
                "EAST supports ceramic and glass; WEST supports polymer only, not ceramic. "
                "These machine capabilities are unchanged across R7 and R8.",
            "source-05.txt": "Unrelated activity: the supply seminar starts at " +
                ("tick 21." if phase == 0 else "tick 23; this notice changes no allocation.")}
        expected = "EAST" if changed else "NORTH"
        support = [mapping, current if changed else old,
                   "EAST supports ceramic and glass" if changed else "NORTH supports ceramic"]
        domain = "CONJUNCTIVE_RESOURCE_PLACEMENT"
    task = {"question": question, "decisions": decisions, "domain": domain,
        "observation": ("A new current registry and data snapshot is now available; it replaces "
            "the prior current snapshot for this same object. Other historical records remain "
            "available." if changed else "Only an unrelated scheduling notice changed; "
            "the current registry and relevant data are unchanged." if phase == 1 else
            "Initial investigation: no inherited handoff or control judgment is provided."),
        "initial_note": None, "persistence": "A separate Host handles the next snapshot. "
            "Ordinary optional TASK notes survive; conversation messages do not."}
    contract = {"expected_decision": expected, "required_support": support,
        "evaluation_version": "V0216_PRE_RUN_REFERENCE_V1",
        "exogenous_reopen_opportunity": changed, "stable_negative_control": phase == 1,
        "required_current_source": "source-03.txt", "root_cluster": key,
        "phase": phase, "pressure": {"axes": ["P3", "P4"],
            "other_object_records": distractors, "current_revision_changes": int(changed),
            "source_files": len(sources), "cold_process": True,
            "simulated_time": True, "injected_control_notes": 0},
        "reference_scope": "Exact current component/site; explanations separately reviewed"}
    return task, {name: text + "\n" for name, text in sources.items()}, contract


def prepare(root: Path, distractors: int) -> None:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    for key in ("trace", "placement"):
        for phase in range(3):
            task, sources, contract = materials(key, phase, distractors)
            online = root / key / "online" / f"phase-{phase}"
            online.mkdir(parents=True)
            save(online / "task.json", task)
            for name, text in sources.items():
                (online / name).write_text(text)
            contract["pressure"]["source_bytes"] = sum(len(x.encode()) for x in sources.values())
            contract["pressure"]["required_data_offset"] = sources["source-03.txt"].encode().find(
                contract["required_support"][1].encode())
            evaluation = root / key / "evaluation"
            evaluation.mkdir(exist_ok=True)
            save(evaluation / f"phase-{phase}.json", contract)
    files = [path for path in root.rglob("*") if path.is_file()]
    save(root / "provenance.json", {"kind": "SYNTHETIC_STRESS_DISCOVERY",
        "root_clusters": ["trace", "placement"], "distractors": distractors,
        "root_relation": "All pressure levels and repeats keep the same two root clusters",
        "researcher_exposure": "All synthetic references and bodies authored/read before execution",
        "old_protected_pool_access": False, "notes": "No injected old judgment; baseline selects "
            "its own notes. Inter-phase updates are fixed independently of saving behavior.",
        "files": {str(p.relative_to(root)): sha(p.read_bytes()) for p in files}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--distractors", type=int, required=True)
    args = parser.parse_args()
    prepare(args.root, args.distractors)
