"""Reconcile physical V1.1/1.2 episode packet IDs and the older Persona benchmark receipts."""

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from milai_lab.datasets.memory_control_store import connect, get_meta, unpack
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.qrag_milai_env import cold_root
from milai_lab.scorers.memory_control_native import qasper_reference


def audit(release, histories, contextual, native_databases):
    counts = Counter()
    exposed = defaultdict(set)
    for release_dir in histories:
        for directory in release_dir.rglob("episodes"):
            if not directory.is_dir() or "MiLAi-Lab" in directory.parts:
                continue
            protocol = directory.parent / "protocol.json"
            population = (
                json.loads(protocol.read_bytes()).get("population") if protocol.is_file() else None
            )
            if not population:
                if directory.parent.name.startswith(("eventqa-", "longmemeval-")):
                    counts["other_source_systems"] += 1
                    continue
                raise ValueError(f"Unbound episode roster in {directory}")
            indexed = {r["task_id"]: (r["dataset"], r["native_group"]) for r in population["tasks"]}
            ids = [p.name for p in directory.glob("*.json*")]
            counts["loose_packet_members"] += len(ids)
            packed = directory.parent / "episodes.tar.zst"
            if packed.is_file():
                result = subprocess.run(  # noqa: S603
                    ["/usr/bin/tar", "--zstd", "-tf", str(packed)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                members = result.stdout.splitlines()
                counts["archive_packet_members"] += len(members)
                counts["archives"] += 1
                ids.extend(members)
            for name in set(ids):
                match = re.fullmatch(r"([0-9]+)\.json(?:\.gz)?", name)
                if match is None:
                    raise ValueError(f"Unexpected member in {directory}")
                source, group = indexed[int(match.group(1))]
                exposed[source].add(group)
            counts["registered_episode_runs"] += 1

    outcome_groups = defaultdict(set)
    source_databases = []
    for database in native_databases:
        with closing(connect(database)) as db:
            source_databases.append({"path": str(database), "run_id": get_meta(db, "run_id")})
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in ("action_outcomes", "action_outcomes_legacy"):
                if name not in names:
                    continue
                query = f"""SELECT DISTINCT t.dataset,t.native_group
                    FROM (SELECT DISTINCT state_id FROM {name}) a
                    JOIN states s ON s.id=a.state_id JOIN task_index t ON t.id=s.task_id"""  # noqa: S608 -- fixed table tuple
                for source, group in db.execute(query):
                    outcome_groups[source].add(group)
    # Every known old contextual run writes per-source/split directories.
    # The formal manifest alone listed planned sources that never executed.
    split_counts = Counter()
    for root in contextual:
        for case_dir in root.rglob("personamem-v2"):
            if case_dir.is_dir():
                for split in case_dir.iterdir():
                    if split.is_dir():
                        split_counts[split.name] += sum(1 for f in split.rglob("*") if f.is_file())
    with closing(connect(release)) as db:
        dataset_run_id = get_meta(db, "run_id")
        if not get_meta(db, "confirmation_only"):
            raise ValueError("A confirmation-only release is required")
        selected = defaultdict(set)
        for source, group in db.execute("SELECT dataset,native_group FROM experiment_groups"):
            selected[source].add(group)
        dataset = MemoryControlDataset(release)
        cold_sources = []
        for source in sorted(selected):
            row = db.execute(
                "SELECT * FROM experiment_tasks WHERE dataset=? ORDER BY id LIMIT 1", (source,)
            ).fetchone()
            _, menu, _ = cold_root(dataset, db, row, 2048)
            if not any(a.kind == "HANDOFF" for a in menu) or not any(
                a.kind == "READ" for a in menu
            ):
                raise ValueError("Cold native task does not offer the expected legal menu")
            cold_sources.append(source)
        pairs = defaultdict(list)
        for group, blob in db.execute("""SELECT native_group,data FROM experiment_tasks t
                JOIN annotations a ON a.task_id=t.id WHERE dataset='musique_full'"""):
            pairs[group].append(unpack(blob)["answerable"])
        if any(sorted(answers) != [False, True] for answers in pairs.values()):
            raise ValueError("Missing answerability member in a protected native pair")
        qasper_tasks = 0
        for (blob,) in db.execute("""SELECT data FROM experiment_tasks t JOIN annotations a
                                  ON a.task_id=t.id WHERE t.dataset='qasper'"""):
            refs = unpack(blob)["answer_annotations"]
            if not refs or not all(qasper_reference(ann["answer"])[0].strip() for ann in refs):
                raise ValueError("A protected QASPER task lacks a usable native reference")
            qasper_tasks += 1
        if db.execute("SELECT count(*) FROM states").fetchone()[0]:
            raise ValueError("Unexpected training states in the confirmation release")
    overlap = {s: len(exposed[s] & groups) for s, groups in selected.items()}
    outcome_overlap = {s: len(outcome_groups[s] & groups) for s, groups in selected.items()}
    if any(overlap.values()) or any(outcome_overlap.values()) or split_counts["benchmark_text"]:
        raise ValueError("Additional prior native-group exposure must be reconciled")
    return {
        "dataset_run_id": dataset_run_id,
        "physical_episode_counts": dict(counts),
        "cold_prepare_sources": cold_sources,
        "reader_calls": 0,
        "complete_mu_pairs": len(pairs),
        "qasper_tasks_with_native_references": qasper_tasks,
        "fitting_states": 0,
        "historical_native_groups_by_source": {s: len(g) for s, g in exposed.items()},
        "current_release_group_overlap": overlap,
        "physical_native_outcome_group_counts": {s: len(g) for s, g in outcome_groups.items()},
        "physical_native_outcome_overlap": outcome_overlap,
        "native_outcome_databases": source_databases,
        "earlier_contextual_packet_files": dict(split_counts),
        "episode_roots": list(map(str, histories)),
        "contextual_roots": list(map(str, contextual)),
        "scope": "Native episode members, registered IDs and contextual split directories",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--history", type=Path, nargs="+", required=True)
    parser.add_argument("--contextual", type=Path, nargs="+", required=True)
    parser.add_argument("--native-databases", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            audit(args.dataset, args.history, args.contextual, args.native_databases), indent=2
        )
    )
