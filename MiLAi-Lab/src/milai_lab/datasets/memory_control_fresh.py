"""Build a cold-evaluation-only SQLite for external QASPER and PersonaMem native groups."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sqlite3
import subprocess
import tarfile
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER, persona, qasper
from milai_lab.datasets.memory_control_reader_task import reader_task
from milai_lab.datasets.memory_control_revision import REVISION_SCHEMA
from milai_lab.datasets.memory_control_store import (
    DB_NAME,
    SCHEMA,
    connect,
    dumps,
    get_meta,
    set_meta,
    unpack,
)
from milai_lab.datasets.memory_control_views import build_views
from milai_lab.methods.memory_control_dataset import MemoryControlDataset

# Only identifiers are emitted by ripgrep. Protected corpus contents and answer
# metrics do not participate in selection.
PAPER = r"[0-9]{4}(?:\.|%2[Ee])[0-9]{4,5}"
MU_ID = r"[2-4]hop[0-9]*__[0-9]+(?:_[0-9]+)+"
IDENTITIES = (
    rf'{MU_ID}|(?:qasper-paper-|qasper/){PAPER}|"(?:(?:paper_id)|native_group)"\s*:\s*"{PAPER}"|'
    r"benchmark_text-[0-9]{6}|v2-benchmark_text-user-[0-9]+|personamem_v2/[0-9]+|"
    r'"(?:persona_id|native_group)"\s*:\s*"?[0-9]+"?(?:\s*[,}])'
)
ROSTERS = [
    "*allocat*.json*",
    "*cohort*.json*",
    "*manifest*.json*",
    "*protocol*.json*",
    "*population*.json*",
    "*selection*.json*",
    "*histories*.json*",
    "*reservation*.json*",
    "source-map.json*",
    "*receipt*.json*",
    "*registration*.json*",
    "*exposure*.json*",
    "*episodes/*.json*",
    "*roster*.json*",
    "*identit*.txt*",
    "answer.json*",
    "complete.json*",
]


def historical_groups(
    roots: list[Path],
    persona_by_row: list[str],
    candidate_groups: dict[str, set[str]],
) -> tuple[dict[str, set[str]], dict[str, dict[str, int]]]:
    found: dict[str, set[str]] = defaultdict(set)
    files: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    cmd = [
        "rg",
        "--no-ignore",
        "--search-zip",
        "--with-filename",
        "--null",
        "--only-matching",
        "--color=never",
    ]
    for glob in ROSTERS:
        cmd += ["--glob", glob]
    for glob in ["!**/.git/**", "!**/site-packages/**", "!**/raw/**", "!**/source-*/MiLAi-Lab/**"]:
        cmd += ["--glob", glob]
    with subprocess.Popen(  # noqa: S603 -- fixed identifier pattern and argv, no shell
        [*cmd, IDENTITIES, *map(str, roots)], stdout=subprocess.PIPE, text=True
    ) as scan:
        assert scan.stdout is not None
        for line in scan.stdout:
            path, key = line.rstrip("\n").split("\0", 1)
            key = unquote(key)
            if re.fullmatch(MU_ID, key):
                source, group = MUSIQUE, key
            elif paper := re.search(r"[0-9]{4}\.[0-9]{4,5}", key):
                source, group = QASPER, paper.group()
            elif key.startswith("benchmark_text-"):
                ordinal = int(key.split("-")[-1])
                if ordinal >= len(persona_by_row):
                    raise ValueError(f"Historical PersonaMem ordinal outside its split in {path}")
                source, group = PERSONA, persona_by_row[ordinal]
            else:
                number = re.search(r'[0-9]+(?=["\s,}]*$)', key)
                if number is None:
                    raise ValueError(f"Unrecognized historical identity in {path}")
                source, group = PERSONA, number.group()
            if group in candidate_groups[source]:
                found[source].add(group)
                files[path][source].add(group)
        if scan.wait() not in {0, 1}:
            raise RuntimeError(f"Unable to complete exposure scan (rg exit {scan.returncode})")
    coverage = {p: {s: len(g) for s, g in rows.items()} for p, rows in files.items()}
    return found, coverage


def copy_musique(db: sqlite3.Connection, parent: Path, groups: set[str]) -> None:
    """Copy the V1.2 native pair, original task IDs, offline labels and prepared views."""
    db.execute("ATTACH DATABASE ? AS src", (parent.resolve().as_uri() + "?mode=ro",))
    db.execute("CREATE TEMP TABLE admitted_mu (native_group TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO admitted_mu VALUES (?)", [(g,) for g in sorted(groups)])
    query = """SELECT count(*) FROM src.experiment_groups JOIN admitted_mu USING(native_group)
               WHERE dataset=? AND role='confirm' AND eligible_fresh_confirmation=1"""
    if db.execute(query, (MUSIQUE,)).fetchone()[0] != len(groups):
        raise ValueError("Unconfirmed parent group in the MuSiQue roster")
    db.execute(
        """INSERT INTO roots SELECT r.* FROM src.roots r JOIN admitted_mu USING(native_group)
                  WHERE r.dataset=?""",
        (MUSIQUE,),
    )
    db.execute("""INSERT INTO tasks SELECT t.* FROM src.tasks t JOIN roots r ON r.id=t.root_id
                  WHERE t.clean_role<>'excluded'""")
    db.execute("UPDATE tasks SET states_built=0")
    db.execute(
        "INSERT INTO annotations SELECT a.* FROM src.annotations a JOIN tasks t ON t.id=a.task_id"
    )
    db.execute("INSERT INTO objects SELECT o.* FROM src.objects o JOIN roots r ON r.id=o.root_id")
    db.execute("INSERT INTO views SELECT v.* FROM src.views v JOIN objects o ON o.id=v.object_id")
    db.execute(
        "INSERT INTO candidates SELECT c.* FROM src.candidates c JOIN views v ON v.id=c.focus_id"
    )
    if db.execute("""SELECT count(*) FROM (
                 SELECT native_group FROM task_index GROUP BY native_group HAVING count(*)=2
               )""").fetchone()[0] != len(groups):
        raise ValueError("Incomplete native pair")
    db.commit()
    db.execute("DETACH DATABASE src")


def build(args: argparse.Namespace) -> None:
    parent = args.parent / DB_NAME if args.parent.is_dir() else args.parent
    csv_name = "benchmark/text/benchmark.csv"
    with (args.persona_root / csv_name).open(newline="") as f:
        persona_by_row = [r["persona_id"] for r in csv.DictReader(f)]
    member = "qasper-test-v0.3.json"
    with tarfile.open(args.qasper) as archive:
        file = archive.extractfile(member)
        if file is None:
            raise ValueError("Missing official QASPER test member")
        with file as stream:
            paper_ids = set(json.load(stream))
    with gzip.open(args.role_inventory, "rt", newline="") as f:
        mu_candidates = {
            r["native_group"]
            for r in csv.DictReader(f, delimiter="\t")
            if r["source"] == MUSIQUE and r["v13_role"] == "CONFIRM_CANDIDATE"
        }
    recorded_ref = json.loads(args.ref_exposure.read_text())
    ref_groups = set(recorded_ref["sample_ids_in_order"])
    if len(recorded_ref["sample_ids_in_order"]) != 300:
        raise ValueError("Incomplete original REF exposure readback")
    protected_ref = set(json.loads(args.ref_roster.read_text())["groups"])
    reserved = {
        s.removeprefix("qasper-paper-") for s in args.reservation.read_text().splitlines() if s
    }
    with closing(connect(parent)) as db:
        existing = {
            dataset: {
                str(r[0])
                for r in db.execute(
                    "SELECT DISTINCT native_group FROM roots WHERE dataset=?", (dataset,)
                )
            }
            for dataset in (QASPER, PERSONA)
        }
        parent_config = get_meta(db, "configuration")
        derivation = get_meta(db, "derivation")
        decl = get_meta(db, "control_release")["declaration"]
        parent_run = get_meta(db, "run_id")
    inputs = {
        MUSIQUE: mu_candidates,
        QASPER: paper_ids - reserved - existing[QASPER],
        PERSONA: set(persona_by_row) - existing[PERSONA],
    }
    observed, paths = historical_groups(args.history, persona_by_row, inputs)
    prior_q, prior_p, prior_mu = observed[QASPER], observed[PERSONA], observed[MUSIQUE]
    selected_mu = mu_candidates - prior_mu - ref_groups - protected_ref
    groups = {
        QASPER: paper_ids - prior_q - existing[QASPER] - reserved,
        PERSONA: set(persona_by_row) - prior_p - existing[PERSONA],
    }
    audit = {
        "scan_roots": list(map(str, args.history)),
        "scan_file_globs": ROSTERS,
        "conservative_metadata_match_files": paths,
        "metadata_interpretation": (
            "Conservative roster and capacity-plan exclusions; "
            "actual packet exposure is checked independently."
        ),
        "prior_identity_patterns": IDENTITIES,
        "reservation": str(args.reservation),
        "excludes_any_v1_root": True,
        "qasper_official_papers": len(paper_ids),
        "qasper_reserved_matches": len(reserved & paper_ids),
        "qasper_other_historical_matches": len((prior_q - reserved) & paper_ids),
        "persona_source_groups": len(set(persona_by_row)),
        "persona_v1_matches": len(set(persona_by_row) & existing[PERSONA]),
        "persona_other_historical_matches": len(
            (prior_p - existing[PERSONA]) & set(persona_by_row)
        ),
        "mu_initial_candidates": len(mu_candidates),
        "mu_historical_scan_matches": len(mu_candidates & prior_mu),
        "mu_original_reference_exposed": len(mu_candidates & ref_groups),
        "mu_fixed_reference_intersection": len(mu_candidates & protected_ref),
        "eligible_groups": {MUSIQUE: len(selected_mu), **{s: len(g) for s, g in groups.items()}},
        "initial_ref_exposure": str(args.ref_exposure),
        "ref_fixed_roster": str(args.ref_roster),
        "scope": "Observed MiLAi group/ordinal metadata and task receipts in named roots",
    }
    args.output.mkdir(exist_ok=True, parents=True)
    (args.output / "source-role-audit.json").write_text(json.dumps(audit, indent=2))
    print(json.dumps(audit["eligible_groups"]), flush=True)
    if not selected_mu or not all(groups.values()):
        raise ValueError("An external source has no eligible historical-identity-disjoint groups")
    path = args.output / DB_NAME
    if path.exists():
        raise FileExistsError(path)
    with tempfile.TemporaryDirectory(dir=args.output) as scratch:
        new = Path(scratch) / DB_NAME
        # Enable URI handling so SQLite enforces mode=ro on the attached parent.
        with closing(sqlite3.connect(new.resolve().as_uri(), uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(SCHEMA + REVISION_SCHEMA)
            copy_musique(db, parent, selected_mu)
            counters = {s: {"test": Counter()} for s in groups}
            qasper(
                db,
                args.qasper,
                {"members": {"test": member}, "archive": str(args.qasper)},
                counters,
                groups=groups[QASPER],
            )
            persona(
                db,
                args.persona_root,
                {**parent_config["sources"][PERSONA], "members": {"test": csv_name}},
                counters,
                groups=groups[PERSONA],
            )
            if any(counters[s]["test"]["excluded"] for s in groups):
                raise ValueError("One or more selected tasks could not be normalized")
            db.execute("UPDATE tasks SET clean_role='validation'")
            db.execute("""INSERT INTO experiment_groups
                       SELECT DISTINCT dataset,native_group,'confirm','external_test_id_scan',1
                       FROM roots""")
            # Retain the established native MCQ order and separate presented options from gold.
            db.execute("""CREATE TABLE public_reader_tasks (
                       task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
                       options TEXT NOT NULL, invalid_reason TEXT)""")
            seed = derivation["revision"]["option_seed"]
            for tid, query, blob in db.execute(
                """SELECT id,query,data FROM experiment_tasks
                                            JOIN annotations ON task_id=id WHERE dataset=?""",
                (PERSONA,),
            ):
                public, _ = reader_task(PERSONA, query, tid, unpack(blob), seed)
                db.execute(
                    "INSERT INTO public_reader_tasks VALUES (?,?,?)",
                    (tid, dumps(public.options), public.invalid_reason),
                )
            config = {
                **parent_config,
                "data_root": str(args.output),
                "dataset_release": "memory_control_v13_external_confirm",
            }
            set_meta(db, "configuration", config)
            build_views(db, config)
            actual = [
                dict(row)
                for row in db.execute("""SELECT dataset,count(*) tasks,
                        count(DISTINCT native_group) groups FROM experiment_tasks
                        WHERE experiment_role='confirm' GROUP BY dataset""")
            ]
            run_id = f"v13-fresh-confirm-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"
            set_meta(db, "run_id", run_id)
            set_meta(
                db, "derivation", {"revision": derivation["revision"], "parent_path": str(parent)}
            )
            set_meta(
                db,
                "control_release",
                {
                    "declaration": {
                        **decl,
                        "dataset_release": config["dataset_release"],
                        "data_root": str(args.output),
                    },
                    "parent_run_id": parent_run,
                },
            )
            set_meta(db, "confirmation_only", True)
            set_meta(db, "build_done", True)
            set_meta(db, "observation_scopes", ["confirm_cold"])
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Unresolved fresh dataset references")
            db.commit()
        with closing(connect(new)) as db:
            dataset = MemoryControlDataset(new)
            for row in db.execute("SELECT * FROM experiment_tasks WHERE dataset=?", (PERSONA,)):
                frozen = dataset.public_reader_task(db, row, row["id"])
                if not frozen.options and not frozen.invalid_reason:
                    raise ValueError("Incomplete frozen public task")
            assert db.execute("SELECT count(*) FROM states").fetchone()[0] == 0
        new.replace(path)
    audit.update(actual=actual, database=str(path), run_id=run_id, reader_calls=0)
    (args.output / "source-role-audit.json").write_text(json.dumps(audit, indent=2))
    print(json.dumps(actual), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--qasper", type=Path, required=True)
    parser.add_argument("--persona-root", type=Path, required=True)
    parser.add_argument("--reservation", type=Path, required=True)
    parser.add_argument("--ref-exposure", type=Path, required=True)
    parser.add_argument("--ref-roster", type=Path, required=True)
    parser.add_argument("--role-inventory", type=Path, required=True)
    parser.add_argument("--history", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args())
