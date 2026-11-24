"""Export clean-source inventory and group roles using the V1 parent and inherited exposure."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sqlite3
import zlib
from collections import Counter
from contextlib import closing
from pathlib import Path


def readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return closing(db)


def groups(roster):
    return {(t["dataset"], t["native_group"]) for t in roster["tasks"]}


def export(parent, derived, historical_run, rosters, output):
    output.mkdir(parents=True, exist_ok=True)
    confirmation = json.loads((historical_run / "protocol.json").read_text())["population"]
    run = json.loads((historical_run / "run.json").read_text())
    if run["status"] != "COMPLETED" or run["configured_tasks"] != len(confirmation["tasks"]):
        raise ValueError("A completed historical confirmation run is required")
    exposed = groups(confirmation)
    tune, cal = [
        groups(json.loads((rosters / f"{name}-2048.json").read_text()))
        for name in ("tune", "calibration")
    ]
    if exposed & (tune | cal) or tune & cal:
        raise ValueError("The registered group roles overlap")
    with readonly(parent) as v1:
        raw = [
            dict(r)
            for r in v1.execute("""
            SELECT dataset,split,clean_role,count(*) AS tasks,
                   count(DISTINCT native_group) AS native_groups
            FROM task_index GROUP BY 1,2,3 ORDER BY 1,2,3""")
        ]
        states, known, weak_rows = 0, 0, 0
        for row in v1.execute(
            "SELECT evidence FROM states LEFT JOIN weak_labels ON states.id=weak_labels.state_id"
        ):
            states += 1
            if row[0] is not None:
                weak_rows += 1
                known += any(v is not None for v in json.loads(zlib.decompress(row[0])))
        excluded = v1.execute("SELECT count(DISTINCT task_id) FROM exclusions").fetchone()[0]
        parent_run = json.loads(
            v1.execute("SELECT value FROM metadata WHERE key='run_id'").fetchone()[0]
        )
    dev_roster = cal | tune
    tally = Counter()
    with readonly(derived) as v12, gzip.open(output / "native-groups.tsv.gz", "wt") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(
            [
                "source",
                "native_group",
                "inherited_role",
                "origin",
                "v13_role",
                "tasks",
                "excluded_tasks",
                "exposure_basis",
            ]
        )
        rows = v12.execute("""
            SELECT g.dataset,g.native_group,g.role,g.origin,g.eligible_fresh_confirmation,
                   sum(t.clean_role<>'excluded') AS tasks,sum(t.clean_role='excluded') AS excluded
            FROM experiment_groups g JOIN task_index t USING(dataset,native_group)
            GROUP BY g.dataset,g.native_group ORDER BY g.dataset,g.native_group""")
        seen = set()
        for source, group, prior, origin, old_fresh, n, ex in rows:
            key = source, group
            seen.add(key)
            if key in exposed:
                if prior != "confirm":
                    raise ValueError("Historical confirmation group role changed")
                role, history = "TUNE", "completed_historical_confirmation"
            elif key in cal:
                role, history = "CALIBRATION", "inherited_dev"
            elif prior == "train":
                role, history = "TRAIN", origin
            elif prior == "dev":
                role, history = "TUNE", "registered_dev"
            elif old_fresh:
                role, history = "CONFIRM_CANDIDATE", "outside_completed_v12_confirmation"
            else:
                role, history = "RESERVED", origin
            if key in dev_roster and prior != "dev":
                raise ValueError("Development roster changed")
            writer.writerow([source, group, prior, origin, role, n, ex, history])
            tally[source, role, "groups"] += 1
            tally[source, role, "tasks"] += n
            tally[source, role, "excluded"] += ex
        if (cal | tune | exposed) - seen:
            raise ValueError("Unknown roster group")
        inherited_run = json.loads(
            v12.execute("SELECT value FROM metadata WHERE key='run_id'").fetchone()[0]
        )
    records = [
        dict(
            source=s,
            role=r,
            groups=tally[s, r, "groups"],
            tasks=tally[s, r, "tasks"],
            excluded_tasks=tally[s, r, "excluded"],
        )
        for s, r in sorted({(s, r) for s, r, _ in tally})
    ]
    result = dict(
        parent=str(parent),
        derived=str(derived),
        parent_run_id=parent_run,
        derived_run_id=inherited_run,
        official=raw,
        total_states=states,
        weak_label_rows=weak_rows,
        states_with_known_weak_evidence=known,
        excluded_task_ids=excluded,
        roles=records,
        historical_confirmation=str(historical_run),
        historical_confirmation_tasks=len(confirmation["tasks"]),
        historical_confirmation_groups=len(exposed),
        calibration_groups=len(cal),
        primary_dev_groups=len(tune),
        exposure_scope=(
            "Inherited experiment roles, completed V12 confirmation roster and V13 calibration. "
            "Remaining groups require cross-study exposure reconciliation before confirmation."
        ),
        sha_validation=False,
    )
    (output / "inventory.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("parent", "derived", "historical-run", "rosters", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    export(args.parent, args.derived, args.historical_run, args.rosters, args.output)
