"""Two disclosed synthetic discovery probes; no benchmark or confirmation inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from replay_v0213_cost import save, sha


def probes() -> dict:
    return {
        "pipeline": {
            "domain": "software_delivery_diagnosis",
            "question": "Investigate the current delivery J42 and select the next justified step. "
                "Do not execute it. Distinguish completed stages from the current bottleneck.",
            "decisions": ["WAIT_FOR_APPROVAL", "REQUEST_PUBLICATION", "INVESTIGATE_EXPORTER",
                          "CLOSE_DELIVERY", "INSUFFICIENT_EVIDENCE"],
            "initial_note": "Old handoff, unverified: delivery was considered closed after a "
                "success receipt. If the receiver still reports a problem, investigate exporter. "
                "Publication was not to be revisited. This may be a mistaken control note.",
            "sources": {
                "source-01.txt": "Procedure: exporter creates the delivery file; signed approval "
                    "permits publisher to publish it. Only a receiver receipt for the SAME job "
                    "closes delivery. Diagnostic users cannot approve, publish or restart systems.",
                "source-02.txt": "Exporter log for J42: file created; checksum verified; no "
                    "export error. These findings remain valid through all three snapshots.",
                "source-03.txt": "Snapshot 0: J42 approval is PENDING. Publication has not "
                    "started. The receiver has no J42 receipt. Success receipt R41 belongs to J41.",
                "source-04.txt": "An unrelated old incident K9 involved an exporter retry loop. "
                    "A colleague suggests an exporter restart by analogy but has no J42 evidence.",
                "source-05.txt": "Office schedule: the design meeting is at 10:00. This is "
                    "not a delivery-system observation."
            },
            "updates": ["Initial investigation.",
                "New activity since the previous session: only the design meeting changed to "
                "09:50. Delivery logs and approvals are unchanged.",
                "New activity: a signed approval for J42 arrived. The publication/approval "
                "source has a new version. No publication or receipt is reported by this notice."],
            "changed_source": "Snapshot 2: J42 approval is SIGNED and valid. Publication has "
                "not started; the receiver still has no J42 receipt. R41 is still only for J41.",
            "expected": ["WAIT_FOR_APPROVAL", "WAIT_FOR_APPROVAL", "REQUEST_PUBLICATION"]
        },
        "grant": {
            "domain": "research_application_review",
            "question": "Review application G17 under the current call rules and select the next "
                "justified administrative step. Do not submit or change the application.",
            "decisions": ["REQUEST_LOCAL_APPROVAL", "PREPARE_STANDARD_SUBMISSION",
                          "REJECT_INELIGIBLE", "USE_EMERGENCY_WAIVER", "INSUFFICIENT_EVIDENCE"],
            "initial_note": "Old handoff, unverified: the application was treated as eligible "
                "for an emergency waiver and ready to submit; don't reopen the local approval "
                "check. This interpretation may have mixed calls.",
            "sources": {
                "source-01.txt": "Call N rules: eligible standard applications require local "
                    "approval before submission. Emergency waivers exist only for Call E. "
                    "A valid Call N amendment can remove the local approval requirement.",
                "source-02.txt": "Application G17 is for Call N, meets the scientific and "
                    "institutional eligibility requirements, and is not submitted. These facts "
                    "remain unchanged through all three snapshots.",
                "source-03.txt": "Snapshot 0: Call N requires local approval. G17 has no local "
                    "approval yet. There is no applicable amendment in this snapshot.",
                "source-04.txt": "A successful application for Call E used an emergency waiver. "
                    "A colleague suggests copying that approach for G17, without checking scope.",
                "source-05.txt": "The seminar is scheduled for 14:00. It does not change the "
                    "funding call, application, eligibility or approval requirements."
            },
            "updates": ["Initial review.",
                "New activity since the previous session: only the seminar changed to 14:30. "
                "Application and call rules are unchanged.",
                "New activity: Call N has published a signed current amendment. The rules/status "
                "source has a new version. Check applicability to the pending application."],
            "changed_source": "Snapshot 2: signed Call N amendment N-2 is effective now and "
                "applies to all pending Call N applications, including G17. It removes local "
                "approval as a requirement. G17 is eligible and unsubmitted. The standard route "
                "is available; this is NOT a Call E emergency waiver.",
            "expected": ["REQUEST_LOCAL_APPROVAL", "REQUEST_LOCAL_APPROVAL",
                         "PREPARE_STANDARD_SUBMISSION"]
        }
    }


def prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    for key, probe in probes().items():
        for phase in range(3):
            online = root / key / "online" / f"phase-{phase}"
            online.mkdir(parents=True)
            task = {field: probe[field] for field in ("question", "decisions", "domain")}
            task.update(observation=probe["updates"][phase],
                initial_note=probe["initial_note"] if phase == 0 else None,
                persistence="A new process will handle the next scheduled snapshot. Optional "
                    "working notes survive in your own TASK State; conversation messages do not.")
            save(online / "task.json", task)
            for name, text in probe["sources"].items():
                if phase == 2 and name == "source-03.txt":
                    text = probe["changed_source"]
                if phase > 0 and name == "source-05.txt":
                    text = text.replace("10:00", "09:50").replace("14:00", "14:30")
                (online / name).write_text(text + "\n")
            evaluation = root / key / "evaluation"
            evaluation.mkdir(exist_ok=True)
            save(evaluation / f"phase-{phase}.json", {
                "expected_decision": probe["expected"][phase],
                "exogenous_reopen_opportunity": phase == 2,
                "stable_negative_control": phase == 1,
                "initial_wrong_control": phase == 0,
                "required_current_source": "source-03.txt",
                "evaluation_version": "PRE_RUN_DECISION_V1",
                "claim": "Controlled synthetic sandbox decision, not general task quality"})
    paths = [p for p in root.rglob("*") if p.is_file()]
    save(root / "provenance.json", {"kind": "SYNTHETIC_CONTROLLED_DISCOVERY",
        "clusters": list(probes()), "shared_lineage_warning": "Three phases per root; not six "
        "independent tasks. No independent confirmation claim.",
        "researcher_exposure": "All source bodies/evaluator references authored/read before run",
        "benchmark_bodies_read": False,
        "files": {str(p.relative_to(root)): sha(p.read_bytes()) for p in paths}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    prepare(parser.parse_args().root)
