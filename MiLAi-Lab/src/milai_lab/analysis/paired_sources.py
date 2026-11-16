"""Paired bounded outcomes with source-family and seed dependence retained."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Any

from milai_lab.analysis.edit_results import paired_interval


def compare_sources(rows: list[dict[str, Any]], *, seed: int = 0,
                    repeats: int = 10000) -> dict[str, Any]:
    """Rows are planned {seed,unit_id,family,baseline,candidate};None means unscored."""
    maps: dict[int, dict[str, str]] = defaultdict(dict)
    cells: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sample_seed, unit, family = row["seed"], row["unit_id"], row["family"]
        if unit in maps[sample_seed]:
            raise ValueError("A planned unit occurs twice in the same seed")
        maps[sample_seed][unit] = family
        for key in ("baseline", "candidate"):
            value = row[key]
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Paired bounded outcomes must be in [0,1] or explicit None")
        cells[sample_seed, family].append(row)
    seeds = sorted(maps)
    if not seeds or any(maps[s] != maps[seeds[0]] for s in seeds):
        raise ValueError("Paired seeds need the same complete planned unit/family mapping")
    families = sorted(set(maps[seeds[0]].values()))
    values: dict[tuple[int, str], dict[str, Any]] = {}
    for identity, cell in cells.items():
        scored = [r for r in cell if r["baseline"] is not None and r["candidate"] is not None]
        values[identity] = {"planned": len(cell), "scored": len(scored),
            "baseline": mean(r["baseline"] for r in scored) if scored else None,
            "candidate": mean(r["candidate"] for r in scored) if scored else None,
            "lower": mean((0 if r["candidate"] is None else r["candidate"])
                          - (1 if r["baseline"] is None else r["baseline"]) for r in cell),
            "upper": mean((1 if r["candidate"] is None else r["candidate"])
                          - (0 if r["baseline"] is None else r["baseline"]) for r in cell)}
    covered = [f for f in families if all(values[s, f]["scored"] for s in seeds)]
    family_results = {f: {"baseline": mean(values[s, f]["baseline"] for s in seeds),
        "candidate": mean(values[s, f]["candidate"] for s in seeds)} for f in covered}
    interval = None
    if covered:
        interval = paired_interval([family_results[f]["baseline"] for f in covered],
            [family_results[f]["candidate"] for f in covered], seed=seed, repeats=repeats)
        interval["families"] = interval.pop("users")
        interval["sampling_unit"] = (
            "source family;paired states and seed means remain inside family")
        interval["degenerate"] = interval["percentile_95_interval"][0] == (
            interval["percentile_95_interval"][1])
        interval["limit"] = ("Conditional on frozen grouping,annotations and scored pairs. "
            "A zero-width empirical interval is not population equivalence. No independent "
            "sample count is gained from additional states or seeds of the same family.")
    per_seed = {}
    for sample_seed in seeds:
        observed = [values[sample_seed, f] for f in families if values[sample_seed, f]["scored"]]
        per_seed[str(sample_seed)] = {"families_with_scores": len(observed),
            "scored_pairs": sum(v["scored"] for v in observed),
            "family_macro_baseline": mean(v["baseline"] for v in observed) if observed else None,
            "family_macro_candidate": mean(v["candidate"] for v in observed) if observed else None}
    return {"planned_pairs": len(rows), "planned_units_per_seed": len(maps[seeds[0]]),
        "paired_scored": sum(v["scored"] for v in values.values()),
        "unscored_pairs": sum(v["planned"] - v["scored"] for v in values.values()),
        "seeds": seeds, "planned_families": len(families),
        "families_with_scored_pairs_in_every_seed": len(covered),
        "families_without_complete_seed_coverage": sorted(set(families) - set(covered)),
        "family_results": family_results, "per_seed": per_seed,
        "paired_family_interval": interval,
        "all_planned_family_macro_difference_bounds": [
            mean(mean(values[s, f][bound] for s in seeds) for f in families)
            for bound in ("lower", "upper")],
        "scope": "Unknowns are not failures. Scored-pair estimates are conditional;all-planned "
                 "bounds retain unknown outcomes. Equal family weight and equal seed weight "
                 "within family;no unpaired or per-seed checkpoint selection is performed."}
