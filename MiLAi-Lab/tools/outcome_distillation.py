"""Executed-subset utility KL and explicit main/replay optimizer windows.

Integration of the v3 equations, cross-checked against the retained standalone
prototype on non-flat KL losses/gradients and reviewed pairs. Numerical deadbands,
actual-action alignment and optimizer-window scheduling are integration additions.
"""
from __future__ import annotations

import copy
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from retrieval_mixture import event_weights


@dataclass
class StateLoss:
    per_state: Any
    active: Any


def utility_distillation(logits: Any, scores: Any, known: Any,
                         teacher_temperature: float = .5,
                         student_temperature: float = 1.,
                         flat_tolerance: float = 1e-6) -> StateLoss:
    """Unscored actions have no direct logit gradient; Teacher targets are detached."""
    import torch

    if (logits.shape != scores.shape or logits.shape != known.shape or logits.ndim != 2):
        raise ValueError("Utility tensors must have matching batch/action dimensions")
    if (not all(math.isfinite(t) and t > 0 for t in
                (teacher_temperature, student_temperature)) or flat_tolerance < 0):
        raise ValueError("Temperatures must be positive finite and tolerance nonnegative")
    scores = scores.detach().float()
    if not torch.isfinite(scores[known]).all():
        raise ValueError("Known teacher scores must be finite")
    spread = (scores.masked_fill(~known, -torch.inf).amax(-1)
              - scores.masked_fill(~known, torch.inf).amin(-1))
    active = (known.sum(-1) >= 2) & (spread > flat_tolerance)
    support = known | ~active[:, None]  # Empty rows use harmless finite dummy softmax inputs.
    teacher = torch.where(active[:, None], scores / teacher_temperature, 0.)
    student = torch.where(active[:, None], logits.float() / student_temperature, 0.)
    log_q = teacher.masked_fill(~support, -torch.inf).log_softmax(-1)
    log_p = student.masked_fill(~support, -torch.inf).log_softmax(-1)
    log_q = log_q.masked_fill(~support, 0.)
    log_p = log_p.masked_fill(~support, 0.)
    q = log_q.exp().masked_fill(~support, 0.)
    values = (q * (log_q - log_p)).sum(-1)
    return StateLoss(torch.where(active, values, 0.), active)


def attach_utilities(rows: list[dict[str, Any]],
                     scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join actual full bindings once. References and likelihoods never enter state/questions."""
    from milai_lab.methods.laya_memory_policy import payload_actions

    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in scores:
        by_event[score["event_id"]].append(score)
    result = copy.deepcopy(rows)
    for row in result:
        meta = row["metadata"]
        candidates = by_event.get(meta["event_id"], [])
        if not candidates:
            continue
        bindings = {a.id: asdict(a) for a in payload_actions(row)}
        if len({s["action"]["id"] for s in candidates}) != len(candidates):
            raise ValueError("Repeated scored binding within one event")
        reference = candidates[0]["reference_set_id"]
        configuration = [(s["teacher"], s["template_version"], s["continuation"],
                          s.get("scoring_configuration"))
                         for s in candidates]
        if any(config != configuration[0] for config in configuration):
            raise ValueError("Utility candidates must share the same scoring/continuation protocol")
        for score in candidates:
            if (score["family"] != meta["family"] or score["research_split"] != meta["split"]
                    or bindings.get(score["action"]["id"]) != score["action"]
                    or score["reference_set_id"] != reference):
                raise ValueError("Utility differs from the event, full action or reference set")
            if observed_utility(score) and not math.isfinite(score["mean_logprob"]):
                raise ValueError("Known utility must be finite")
        row["utility"] = {"event_id": meta["event_id"], "candidates": candidates,
                          "semantic_meaning": "weak_answer_predictability_not_sufficiency"}
    extra = set(by_event) - {r["metadata"]["event_id"] for r in rows}
    if extra:
        raise ValueError("Scored events are absent from the supplied student states")
    return result


def align_utilities(rows: list[dict[str, Any]], keys: list[list[str]],
                    logits: Any) -> tuple[Any, Any]:
    """Resolve after option permutation, using action IDs rather than old positions."""
    import torch

    scores = torch.zeros_like(logits, dtype=torch.float32)
    known = torch.zeros_like(logits, dtype=torch.bool)
    for i, (row, order) in enumerate(zip(rows, keys, strict=True)):
        positions = {key: j for j, key in enumerate(order)}
        for candidate in row.get("utility", {}).get("candidates", []):
            key = candidate["action"]["id"]
            if key not in positions:
                raise ValueError("Scored action is missing from the actual encoded menu")
            if observed_utility(candidate):
                scores[i, positions[key]] = candidate["mean_logprob"]
                known[i, positions[key]] = True
    return scores, known


def is_main(row: dict[str, Any]) -> bool:
    return "utility" in row or "feedback" in row


def observed_utility(candidate: dict[str, Any]) -> bool:
    """Legacy scores filtered failed executions; new records retain that status explicitly."""
    return (candidate["score_known"]
            and candidate.get("execution_status", "completed") == "completed")


def active_support(row: dict[str, Any], objective: str, feedback_target: str | None,
                   include_ties: bool, flat_tolerance: float) -> bool:
    if not is_main(row):
        return bool(row["gold"])
    if objective == "utility-kl":
        scores = [c["mean_logprob"] for c in row.get("utility", {}).get("candidates", [])
                  if observed_utility(c)]
        return len(scores) >= 2 and max(scores) - min(scores) > flat_tolerance
    known = {"left", "right", "tie"} if include_ties else {"left", "right"}
    return any(p[feedback_target] in known for p in row.get("feedback", {}).get("comparisons", []))


def component_weights(rows: list[dict[str, Any]], objective: str,
                      feedback_target: str | None, include_ties: bool,
                      flat_tolerance: float) -> list[float]:
    weights = [0.] * len(rows)
    for main in (True, False):
        indices = [i for i, r in enumerate(rows) if is_main(r) == main and
                   active_support(r, objective, feedback_target, include_ties, flat_tolerance)]
        if indices:
            for i, w in zip(indices, event_weights([rows[i] for i in indices]), strict=True):
                weights[i] = w
    return weights


def mixed_windows(rows: list[dict[str, Any]], passes: int, seed: int,
                  main_rows: int = 24, replay_rows: int = 8) -> list[list[tuple[int, int]]]:
    """Exactly one main exposure per pass, crossing pass boundaries; no main tail dropped.

    Replay cycles independently. Tail replay is ceil(tail_main * replay/main), explicitly
    retained rather than filling the main tail with repeated task states.
    """
    main = [i for i, r in enumerate(rows) if is_main(r)]
    replay = [i for i, r in enumerate(rows) if not is_main(r)]
    if not main or not replay or min(passes, main_rows, replay_rows) < 1:
        raise ValueError("Explicit windows require positive main/replay pools and counts")
    rng = random.Random(seed)  # noqa: S311 -- reproducible research schedule
    replay_rng = random.Random(seed + 1)  # noqa: S311
    draws = []
    for data_pass in range(1, passes + 1):
        order = main.copy()
        rng.shuffle(order)
        draws.extend((data_pass, i) for i in order)
    replay_order, cursor = [], 0
    windows = []
    for start in range(0, len(draws), main_rows):
        window = draws[start:start + main_rows]
        augmentation_pass = window[-1][0]
        count = math.ceil(len(window) * replay_rows / main_rows)
        for _ in range(count):
            if cursor == len(replay_order):
                replay_order = replay.copy()
                replay_rng.shuffle(replay_order)
                cursor = 0
            # Option augmentation follows the primary pass, not the much faster replay
            # cycle; otherwise the trainer would re-encode the entire pool every window.
            window.append((augmentation_pass, replay_order[cursor]))
            cursor += 1
        windows.append(window)
    return windows


def window_normalizers(window: list[tuple[int, int]], rows: list[dict[str, Any]],
                       weights: list[float]) -> dict[bool, float]:
    return {main: sum(weights[i] for _, i in window if is_main(rows[i]) == main)
            for main in (True, False)}


def normalized_micro_loss(losses: Any, indices: list[int], rows: list[dict[str, Any]],
                          weights: list[float], normalizers: dict[bool, float],
                          replay_weight: float) -> Any:
    import torch

    factors = []
    for i in indices:
        main = is_main(rows[i])
        denominator = normalizers[main]
        factors.append(weights[i] * (1. if main else replay_weight) / denominator
                       if denominator else 0.)
    return (losses * torch.tensor(factors, device=losses.device)).sum()


def score_utility_predictions(rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
                              teacher_temperature: float, student_temperature: float,
                              flat_tolerance: float) -> dict[str, Any]:
    """Report supported-subset fit separately from the actual full-menu first choice."""
    import torch

    counts: Counter[str] = Counter()
    families: dict[str, list[float]] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        if "utility" not in row:
            continue
        counts["utility_states"] += 1
        order = list(prediction["logits"])
        logits = torch.tensor([[prediction["logits"][key] for key in order]])
        scores, known = align_utilities([row], [order], logits)
        loss = utility_distillation(logits, scores, known, teacher_temperature,
                                    student_temperature, flat_tolerance)
        if not loss.active.item():
            counts["inactive_states"] += 1
            continue
        families[row["metadata"]["family"]].append(loss.per_state.item())
        selected = order.index(prediction["choice"])
        if not known[0, selected]:
            counts["full_menu_choice_outside_scored_support"] += 1
        else:
            counts["full_menu_choice_in_scored_support"] += 1
            best = scores.masked_fill(~known, -torch.inf).max().item()
            counts["full_menu_choice_teacher_best"] += int(scores[0, selected].item() == best)
    means = {family: sum(values) / len(values) for family, values in families.items()}
    return {"counts": dict(counts), "family_mean_subset_kl": means,
            "source_macro_subset_kl": sum(means.values()) / len(means) if means else None,
            "scope": "Offline weak fit only. Outside-support choices are unknown, not wrong. "
                     "Neither Teacher-best selection nor lower KL establishes Host success."}
