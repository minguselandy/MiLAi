"""Measure budget-conditioned choices on the same offered action bindings."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.control_numeric import STATE_FIELDS
from milai_lab.methods.memory_control import MemoryAction
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.runners.memory_control_episode import checkpoint_contract, start_cold
from milai_lab.scorers.memory_control_episode_metrics import input_result


def _without_budget_inputs(online: dict[str, Any]) -> dict[str, Any]:
    """Remove only the material limit and remainder, retaining the common action bindings."""
    observation = online["observation"]
    budget = {
        key: value for key, value in observation["budget"].items()
        if key not in {"reader_material_tokens", "remaining_reader_material_tokens"}
    }
    comparison = {**online, "observation": {**observation, "budget": budget}}
    if numeric := online.get("control_numeric"):
        positions = {STATE_FIELDS.index(name) for name in ("budget", "remaining_budget")}
        comparison["control_numeric"] = {
            **numeric,
            "state": [None if i in positions else value
                      for i, value in enumerate(numeric["state"])],
        }
    return comparison


def _best(scores: list[float], menu: list[MemoryAction], handoff_ties: bool) -> str:
    return menu[max(range(len(menu)), key=lambda i: (
        scores[i], handoff_ties and menu[i].kind == "HANDOFF",
    ))].id


def inspect_common_budget_menus(
    data: Path, reference: Path, *, budgets: list[int], device: str,
    task_ids: set[int] | None = None,
) -> dict[str, Any]:
    protocol, observed = input_result(reference)
    population, arm = protocol["population"], protocol["arm"]
    if (population["role"] != "dev" or arm["policy"] != "checkpoint"
            or not budgets or any(b <= 0 or b == population["material_budget"] for b in budgets)):
        raise ValueError("Use registered DEV checkpoint episodes and distinct alternate budgets")
    checkpoint = Path(arm["checkpoint"])
    contract = checkpoint_contract(checkpoint)
    model = SmallControlModel.load(checkpoint, device=device)
    if "utility_lambda" in arm:
        model.set_utility_lambda(arm["utility_lambda"])
    model.configure_base_encoding_cache(16 * 1024**2)
    dataset = MemoryControlDataset(
        data, observation_protocol=contract["observation_protocol"],
        numeric_observation=model.config.numeric_mode != "off",
    )
    if dataset.run_id != population["dataset_run_id"]:
        raise ValueError("Common-budget replay requires the reference release")
    cohort = population["tasks"]
    if task_ids is not None:
        cohort = [row for row in cohort if row["task_id"] in task_ids]
        if {row["task_id"] for row in cohort} != task_ids or not cohort:
            raise ValueError("Replay tasks must be a nonempty subset of the actual readout roster")
    groups: dict[int, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    score_differences: dict[tuple[int, str], float] = defaultdict(float)
    preflight_wall: dict[tuple[int, str], float] = defaultdict(float)
    preflight_records = 0
    started, cpu = time.perf_counter(), time.process_time()
    max_steps = dataset.config["states"]["control_steps"]
    with closing(connect(dataset.path)) as db:
        for metadata in cohort:
            ident = metadata["task_id"]
            if ident not in observed:
                raise ValueError("Complete the reference episode roster before common-menu replay")
            task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (ident,)).fetchone()
            if task is None or task["experiment_role"] != "dev" or any(
                task[key] != metadata[key] for key in ("dataset", "native_group")
            ):
                raise ValueError("Reference episode changed its DEV identity")
            episode = observed[ident]
            prefix = episode["actual_cold_prefix"]
            left, _ = start_cold(dataset, db, task, population["material_budget"])
            # Cache the exact packet size and Host check within this source and prefix.
            # Each session still applies its own material threshold to the packet.
            shared_preflight: dict[
                tuple[tuple[str, ...], str], tuple[int, bool | None, str | None]
            ] = {}
            for position, budget in enumerate(budgets):
                if position:
                    left = dataset.start_task(
                        db, task, left.pool, left.focus, population["material_budget"],
                    )
                right = dataset.start_task(db, task, left.pool, left.focus, budget)
                left.shared_preflight = right.shared_preflight = shared_preflight
                stats = groups[budget][task["dataset"]]
                stats["tasks"] += 1
                for selected in [*prefix, None]:
                    left.menu(max_steps)
                    right.menu(max_steps)
                    base = left.actions(left.state)
                    alternate = right.actions(right.state)
                    base_map, other_map = {a.id: a for a in base}, {a.id: a for a in alternate}
                    common = [a for a in base if other_map.get(a.id) == a]
                    if not common:
                        stats["no_common_actions"] += 1
                        break
                    stats["paired_states"] += 1
                    stats["reference_only_actions"] += len(base) - len(common)
                    stats["alternate_only_actions"] += len(alternate) - len(common)
                    if len(common) > 1:
                        canonical, changed = left.online(common), right.online(common)
                        if _without_budget_inputs(canonical) == _without_budget_inputs(changed):
                            low = model.score(canonical)
                            high = model.score(changed)
                            if low.action_ids != high.action_ids or low.action_ids != [
                                a.id for a in common
                            ]:
                                raise ValueError("Budget-score comparison lost its common bindings")
                            stats["common_choice_states"] += 1
                            stats["common_choice_changes"] += _best(
                                low.scores, common, low.handoff_wins_ties,
                            ) != _best(high.scores, common, high.handoff_wins_ties)
                            score_differences[budget, task["dataset"]] += sum(
                                abs(a - b) for a, b in zip(low.scores, high.scores, strict=True)
                            )
                            stats["common_action_scores"] += len(common)
                        else:
                            stats["common_states_with_nonbudget_changes"] += 1
                    if selected is None:
                        break
                    action = base_map.get(selected)
                    if action is None:
                        raise ValueError("The reference execution prefix does not replay")
                    if other_map.get(selected) != action:
                        stats["reference_prefix_blocked_by_alternate_menu"] += 1
                        break
                    if not left.take(action) or not right.take(action):
                        raise ValueError("A common feasible action failed in replay")
                    if len(left.prefix) >= max_steps:
                        break
                preflight_wall[budget, task["dataset"]] += (
                    left.preflight_wall_ms + right.preflight_wall_ms
                )
            preflight_records += len(shared_preflight)
    return {
        "scope": "real DEV prefixes; common action scores with matched nonbudget observations",
        "reference": str(reference.resolve()), "checkpoint": str(checkpoint.resolve()),
        "reference_budget": population["material_budget"],
        "by_budget_and_source": {
            budget: {
                source: {**values,
                         "common_score_absolute_delta_sum": score_differences[budget, source],
                         "host_preflight_wall_ms": preflight_wall[budget, source]}
                for source, values in sources.items()
            } for budget, sources in groups.items()
        },
        "shared_preflight_records": preflight_records,
        "reader_requests": 0, "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu, "encoder_work": model.counters,
        "sha_validation": False,
    }
