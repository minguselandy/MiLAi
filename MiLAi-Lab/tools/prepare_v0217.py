"""Pre-scripted unfinished work and semantic change; no authored memory seeds."""

from __future__ import annotations

import argparse
from pathlib import Path

from replay_v0213_cost import save, sha


def materials(root: str, event: str, phase: int) -> tuple[dict, dict, dict]:
    changed = event == "change"
    if root == "route":
        sources = {
            "source-01.txt": "Dispatch study for cargo L27: compare route totals, require "
                "capacity >= 6 tonnes and arrival <= 30 minutes. Current daily bridge approval "
                "is needed before recommending RIVER for dispatch; a draft is not dispatch.",
            "source-02.txt": "Route table: RIVER legs 4+7+5 minutes, capacity 8 tonnes; HILL "
                "legs 8+9+6 minutes, capacity 7 tonnes; PORT legs 6+5+7 minutes, capacity 4 "
                "tonnes. All are otherwise feasible; minimize travel time among eligible routes.",
            "source-03.txt": "Morning work record: RIVER's previous-day bridge approval was "
                "valid, but today's inspection is pending. No current approval or closure has "
                "been established. HILL has no bridge restriction. There is no dispatch yet."}
        initial = ("Begin the multi-session dispatch study for L27. Do the route comparison "
            "now and produce a provisional route draft, identifying whether it can yet be "
            "dispatched. Today's inspection will arrive after this session closes. This is "
            "unfinished planning work, not permission to book a vehicle.")
        continuation = ("Resume the L27 dispatch study and recommend the current eligible "
            "route with the smallest total time. Use the new inspection and preserve any "
            "still-valid completed work. Recommend only; do not dispatch.")
        observation = ("Signed daily inspection for L27's RIVER bridge: CLOSED today; "
            "RIVER cannot be used. HILL conditions are unchanged. The general route newsletter "
            "still calls RIVER the usual fastest route, but is not a daily approval." if changed
            else "Signed daily inspection for L27's RIVER bridge: OPEN and approved today. "
            "Route times/capacities are unchanged. An unrelated notice moves next month's "
            "driver seminar; it does not alter any route.")
        labels = ["DRAFT_RIVER", "DRAFT_HILL", "DRAFT_PORT", "UNRESOLVED"] if phase == 0 else [
            "RIVER", "HILL", "PORT", "INSUFFICIENT_EVIDENCE"]
        expected = "DRAFT_RIVER" if phase == 0 else "HILL" if changed else "RIVER"
        old = "RIVER"
        support = ["RIVER legs 4+7+5", "HILL legs 8+9+6", "PORT legs 6+5+7"]
    else:
        sources = {
            "source-01.txt": "Sensor S14 investigation. A zero-offset correction is appropriate "
                "if the controlled fixed-input test shows approximately the same positive error "
                "at 20C and 40C (difference <= 0.3 units). If the difference exceeds 1.5 units, "
                "choose thermal characterization before correction. Intermediate differences "
                "are inconclusive. This is an investigation recommendation, not calibration.",
            "source-02.txt": "Initial bench readings for S14 at 20C: reference 10 gives 12.0, "
                "reference 20 gives 22.1, reference 30 gives 32.0. The reference source passed "
                "independent checks. A near-constant positive offset is a plausible provisional "
                "explanation at this temperature; temperature dependence has not been tested.",
            "source-03.txt": "Work status: compare the bench errors and prepare the next "
                "investigation step. A controlled fixed-input 20C/40C run is scheduled after "
                "the session pause. No correction has been performed; its result is pending."}
        initial = ("Start the multi-session S14 investigation. Compare the existing readings, "
            "form a provisional diagnostic draft and prepare to continue after the controlled "
            "run arrives. The task remains open after this session; do not perform calibration.")
        continuation = ("Resume S14's investigation. Recommend the next step under the "
            "diagnostic rule using the controlled run, retaining valid previous findings "
            "without treating a provisional draft as a final diagnosis. Do not calibrate.")
        observation = ("Signed controlled S14 fixed-input test: reference=20 at both temperatures; "
            "reading=20.1 at 20C and 23.2 at 40C. Same instrument, validated reference. This "
            "new controlled test supersedes the preliminary bench readings for current correction "
            "choice. A newer staff anecdote about another sensor says offsets are common." if
            changed else "Signed controlled S14 fixed-input test: reference=20 at both "
            "temperatures; reading=22.0 at 20C and 22.1 at 40C. Same instrument, validated "
            "reference. A newer unrelated room-booking notice changes no measurement.")
        labels = ["DRAFT_ZERO_OFFSET", "DRAFT_THERMAL", "UNRESOLVED"] if phase == 0 else [
            "ZERO_OFFSET_CORRECTION", "THERMAL_CHARACTERIZATION", "INSUFFICIENT_EVIDENCE"]
        expected = "DRAFT_ZERO_OFFSET" if phase == 0 else "THERMAL_CHARACTERIZATION" if changed \
            else "ZERO_OFFSET_CORRECTION"
        old = "ZERO_OFFSET_CORRECTION"
        support = ["reference 10 gives 12.0", "reference 20 gives 22.1",
                   "reference 30 gives 32.0"]
    task = {"question": initial if phase == 0 else continuation, "decisions": labels,
        "observation": "Future external result is pending." if phase == 0 else observation,
        "workflow": "This investigation spans separate sessions. The current session's "
            "conversation is not carried into the next Host. Normal work artifacts and source "
            "history remain available. An ordinary free-text notebook is available if useful; "
            "saving is optional and no notebook format is prescribed.",
        "initial_note": None}
    if phase:
        sources["source-04.txt"] = observation
    contract = {"root_cluster": root, "event": event, "phase": phase,
        "expected_decision": expected, "old_provisional_direction": old,
        "new_observation": None if phase == 0 else observation,
        "relation": "CHALLENGES_OLD_DRAFT" if changed else "SUPPORTS_OLD_DRAFT_UNRELATED_NOTICE",
        "required_initial_support": support, "reference_version": "V0217_PRE_RUN_V1",
        "exposure": "SYNTHETIC_AUTHORED_AND_READ_BEFORE_A; same-root event variants correlated",
        "business_actions": "INTENT_ONLY", "time": "SHORT_SIMULATED_EVENT_NOT_LONG_TERM"}
    return task, {name: text + "\n" for name, text in sources.items()}, contract


def prepare(destination: Path):
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for root in ("route", "sensor"):
        for event in ("stable", "change"):
            key = f"{root}-{event}"
            for phase in (0, 1):
                task, sources, contract = materials(root, event, phase)
                online = destination / key / "online" / f"phase-{phase}"
                online.mkdir(parents=True)
                save(online / "task.json", task)
                for name, text in sources.items():
                    (online / name).write_text(text)
                save(destination / key / "evaluation" / f"phase-{phase}.json", contract)
    files = list(destination.rglob("*.txt")) + list(destination.rglob("*.json"))
    save(destination / "provenance.json", {"root_clusters": ["route", "sensor"],
        "event_scripts_before_A": True, "note_seeds": 0, "protected_pool_access": False,
        "files": {str(p.relative_to(destination)): sha(p.read_bytes()) for p in files}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root)
