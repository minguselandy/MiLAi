"""Native-group-first TRAIN eligibility and source-wise feedback quotas."""

from __future__ import annotations

import random
import struct
from collections import Counter, defaultdict

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER


def slate_rng(acquisition_seed, pool_seed, index, *, warm):
    # Keep the in-progress common warm sequence fixed. Independent frozen policy
    # rounds need different native-group draws even when all roots happen to stop cold.
    seed = (
        acquisition_seed * 1000003 + index
        if warm
        else int.from_bytes(struct.pack(">qqQ", acquisition_seed, pool_seed, index), "big")
    )
    return random.Random(seed)  # noqa: S311 -- seeded TRAIN selection


class NativeRootPool:
    def __init__(self, db):
        self.available = defaultdict(lambda: defaultdict(list))
        for (
            source,
            group,
            task,
        ) in db.execute("""SELECT dataset,native_group,id FROM experiment_tasks
                        WHERE experiment_role='train' AND clean_role='train' ORDER BY id"""):
            self.available[source][group].append(task)
        self.ids = set()
        self.group_counts = Counter()
        self.source_counts = Counter()

    def accept(self, row):
        task, source, group = row["task_id"], row["source"], row["native_group_id"]
        if task in self.ids:
            raise ValueError("A TRAIN task was selected twice in the same acquisition pool")
        self.ids.add(task)
        tasks = self.available[source].get(group)
        if tasks is None or task not in tasks:
            raise ValueError("A TRAIN root exceeds its native-group cap or role")
        tasks.remove(task)
        self.group_counts[source, group] += 1
        self.source_counts[source] += 1
        cap = 4 if source == MUSIQUE else 6
        if not tasks or self.group_counts[source, group] >= cap:
            del self.available[source][group]

    def slate(self, window, rng, *, boundary_slot=0):
        count = sum(self.source_counts.values()) + 1
        sources = [k for k, v in self.available.items() if v]
        # Enforce the maximum on realized before states. A preserved legacy prefix can
        # temporarily exceed ten percent: its next Persona slot waits until it fits.
        if self.source_counts[PERSONA] + 1 > count // 10:
            sources = [s for s in sources if s != PERSONA]
        if not sources:
            raise ValueError("No eligible clean TRAIN group remains under source and native caps")
        non_persona = self.source_counts[MUSIQUE] + self.source_counts[QASPER] + 1
        deficits = {
            MUSIQUE: 2 * non_persona / 3 - self.source_counts[MUSIQUE],
            QASPER: non_persona / 3 - self.source_counts[QASPER],
        }
        sources.sort(key=lambda src: (src == PERSONA, deficits.get(src, 0)), reverse=True)
        source = sources[boundary_slot % len(sources)]
        choices = self.available[source]
        groups = rng.sample(list(choices), min(window, len(choices)))
        rows = [(source, group, rng.choice(choices[group])) for group in groups]
        return rows, {
            "available_native_groups": len(choices),
            "slate_size": len(groups),
            "tasks_per_sampled_group": {g: len(choices[g]) for g in groups},
        }


class ExplorationBudget:
    def __init__(self):
        self.exposure = Counter()
        self.reserved = Counter()
        self.fallback = Counter()
        self.new_calls = Counter()
        self.reserved_new = Counter()
        self.fallback_new = Counter()

    def random_slot(self, source, remaining, limit):
        # The correction follows realized paid measurements within each source. A
        # costlier MuSiQue companion cannot consume another source's exploration slots.
        # Allow only complete packs. Protect the final quarter before an active pack
        # could use the last affordable slots; the measured share may exceed it slightly.
        largest = 5 if source == MUSIQUE else 4
        needed = (limit + 3) // 4
        if sum(self.reserved.values()) + remaining - min(largest, remaining) < needed:
            return True
        return self.reserved[source] < 0.25 * self.exposure[source]

    def observe(self, row):
        source = row["source"]
        amount = row.get("realized_new_exposure", row.get("random_exposure", 0))
        new = row.get("realized_new_requests")
        role = row.get("selection_kind", "reserved_uniform")
        self.exposure[source] += amount
        self.reserved[source] += amount if role == "reserved_uniform" else 0
        self.fallback[source] += amount if role == "uniform_zero_priority" else 0
        if new is not None:
            self.new_calls[source] += new
            self.reserved_new[source] += new if role == "reserved_uniform" else 0
            self.fallback_new[source] += new if role == "uniform_zero_priority" else 0

    def report(self):
        return {
            s: {
                "exposure": v,
                "reserved_uniform_exposure": self.reserved[s],
                "fallback_uniform_exposure": self.fallback[s],
                "positive_priority_exposure": v - self.reserved[s] - self.fallback[s],
                "new_requests_with_recorded_selection": self.new_calls[s],
                "reserved_uniform_new_requests": self.reserved_new[s],
                "fallback_uniform_new_requests": self.fallback_new[s],
            }
            for s, v in self.exposure.items()
        }
