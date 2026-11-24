"""True terminal TD targets and frozen online-Q gradients on paired MuSiQue TRAIN edges."""

import json
import math
import random
import statistics
import time
from pathlib import Path

import torch


def prefix_pair(sample, rng):
    support = sorted(set(sample["sf_idx"]))
    others = sorted(set(range(len(sample["chunks"]))) - set(support))
    if not 1 <= len(support) <= 4 or len(others) < 5 - len(support):
        return None
    rng.shuffle(support)
    rng.shuffle(others)
    n_fill = 4 - len(support)
    prefix = support[:-1] + others[:n_fill]
    rng.shuffle(prefix)
    return prefix, support[-1], others[n_fill]


def terminal_edge(env, sample, prefix, first):
    state = env.reset(sample)
    for idx in prefix:
        state, _, reward, done = env.step(idx)
        if done or reward != 0:
            raise ValueError("Diagnostic prefix consumed the completion reward")
    _, action, reward, done = env.step(first)
    if not done or env.num_steps != 4:
        raise ValueError("Diagnostic TD edge must have a genuine zero-bootstrap terminal mask")
    return state, action, float(reward)


def parameters(critic):
    selected = {}
    for name, encoder in (
        ("state", critic.state_embed.model),
        ("action", critic.action_embed.model.model),
    ):
        selected[name + "_layer0_query"] = encoder.encoder.layer[0].attention.self.query.weight
        selected[name + "_last_layer_output_norm"] = encoder.encoder.layer[
            -1
        ].output.LayerNorm.weight
    return selected


def measure_pair(critic, selected, env, sample, actions):
    from envs.utils import stack_actions, stack_memory

    prefix, support, distractor = actions
    pos = terminal_edge(env, sample, prefix, support)
    neg = terminal_edge(env, sample, prefix, distractor)
    if pos[0].text != neg[0].text or not pos[2] > 0 or neg[2] != 0:
        raise ValueError("Matched before state or native terminal rewards differ")
    states = stack_memory(
        [pos[0], neg[0]], critic.state_embed.tokenizer, env.max_action_length_in_memory
    )
    chosen = stack_actions([pos[1], neg[1]], critic.action_embed.tokenizer, env.action_embed_length)
    with torch.enable_grad():
        q1, q2 = critic(states, chosen)
        q1, q2 = q1.flatten(), q2.flatten()
        target = q1.new_tensor([pos[2], neg[2]])
        errors = [2 * q1 - target, 2 * q2 - target]
        loss = (errors[0].square() + errors[1].square()) / 2
        grads = [
            torch.autograd.grad(loss[i], tuple(selected.values()), retain_graph=i == 0)
            for i in (0, 1)
        ]

    def floats(v):
        return v.detach().cpu().tolist()

    norms = {}
    for (key, _), p, n in zip(selected.items(), *grads, strict=True):
        positive = p.float().flatten()
        negative = n.float().flatten()
        a = float(positive.norm())
        b = float(negative.norm())
        norms[key] = {
            "positive_norm": a if math.isfinite(a) else None,
            "zero_norm": b if math.isfinite(b) else None,
            "direction_cosine": float(positive.dot(negative) / (a * b))
            if a * b and math.isfinite(a * b)
            else None,
        }
    total = q1 + q2
    return {
        "train_id": sample["id"],
        "prefix": prefix,
        "actions": [support, distractor],
        "terminal_rewards": floats(target),
        "twice_q1": floats(2 * q1),
        "twice_q2": floats(2 * q2),
        "loss": floats(loss),
        "net_score_positive_minus_zero": float((total[0] - total[1]).detach()),
        "dL_dq1": floats(2 * errors[0]),
        "dL_dq2": floats(2 * errors[1]),
        "gradients": norms,
    }


def target_fit(pairs):
    result = {}
    for head in ("twice_q1", "twice_q2"):
        predicted = [r[head] for r in pairs]
        errors = [
            [y - t for y, t in zip(r[head], r["terminal_rewards"], strict=True)] for r in pairs
        ]
        result[head] = {
            "mean_predictions": [statistics.fmean(col) for col in zip(*predicted, strict=True)],
            "mean_residuals": [statistics.fmean(col) for col in zip(*errors, strict=True)],
            "both_residuals_positive_fraction": statistics.fmean(
                a > 0 and b > 0 for a, b in errors
            ),
            "both_residuals_negative_fraction": statistics.fmean(
                a < 0 and b < 0 for a, b in errors
            ),
        }
    return result


def run_probe(agent, cfg, binding):
    """Readout only. Positive and zero terminal edges share a legal three-action prefix."""
    from hydra.utils import instantiate
    from qrag_ref_retrieval import save
    from rl.q_module import TextQNet

    design = binding["terminal_td_probe"]
    if not design["enabled"]:
        return
    path = Path(cfg.pretrained_path) / "terminal-td-probe.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if (
            previous["design"] != design
            or previous["optimizer_updates"] != binding["optimizer_updates"]
        ):
            raise ValueError("Conflicting paired terminal-edge probe")
        return
    device = next(agent.policy.parameters()).device
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    env = instantiate(cfg.envs.env)
    if (
        env.dataset.dataset.split != "train"
        or env.max_steps != 4
        or not env.feedback_model.penalize_extra_steps
        or not env.feedback_model.never_terminate
        or env.feedback_model.per_fact_reward != 0
    ):
        raise ValueError("Expected official MuSiQue TRAIN environment and GT reward")
    # Upstream hard-copies state_embed into policy at every optimizer step. The
    # action tower is the actual online critic tower. Do not substitute a base
    # target network for the historical EMA; terminal TD targets equal reward.
    critic = TextQNet(agent.policy.state_embed, agent.critic.action_embed).eval()
    selected = parameters(critic)
    rng = random.Random(design["seed"])  # noqa: S311 -- prespecified TRAIN-only comparison
    indices = list(range(len(env.dataset)))
    rng.shuffle(indices)
    pairs = []
    for index in indices:
        sample = env.dataset[index]
        actions = prefix_pair(sample, rng)
        if actions:
            pairs.append(measure_pair(critic, selected, env, sample, actions))
        if len(pairs) == design["pairs"]:
            break
    if len(pairs) != design["pairs"]:
        raise ValueError("Insufficient valid paired terminal TRAIN edges")
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    result = {
        "stage": binding["stage"],
        "optimizer_updates": binding["optimizer_updates"],
        "design": design,
        "wall_seconds": elapsed,
        "assigned_gpu_seconds": elapsed if device.type == "cuda" else 0.0,
        "device": str(device),
        "source": "official MuSiQue-Ans TRAIN",
        "gt_discount_gamma": agent.gamma,
        "td_lambda": agent.Lambda,
        "target_ema_tau": agent.tau,
        "reader_calls": 0,
        "optimizer_steps": 0,
        "weights_mode": "frozen online towers, dropout disabled during paired backward",
        "true_target_scope": (
            "Native terminal reward since not_done=0. Nonterminal historical EMA values "
            "and historical optimizer gradients are unavailable from an actor."
        ),
        "normalization": "Per-edge twin MSE before the official rollout/accumulation reduction.",
        "pair_score_win_rate": statistics.fmean(
            r["net_score_positive_minus_zero"] > 0 for r in pairs
        ),
        "pair_score_ties": sum(r["net_score_positive_minus_zero"] == 0 for r in pairs),
        "terminal_value_fit": target_fit(pairs),
        "mean_model_score_gap": statistics.fmean(r["net_score_positive_minus_zero"] for r in pairs),
        "mean_true_target_gap": statistics.fmean(
            r["terminal_rewards"][0] - r["terminal_rewards"][1] for r in pairs
        ),
        "positive_mean_loss": statistics.fmean(r["loss"][0] for r in pairs),
        "zero_mean_loss": statistics.fmean(r["loss"][1] for r in pairs),
        "mean_gradient_norms": {
            k: {
                field: statistics.fmean(v)
                if (
                    v := [
                        r["gradients"][k][field]
                        for r in pairs
                        if r["gradients"][k][field] is not None
                    ]
                )
                else None
                for field in ("positive_norm", "zero_norm")
            }
            for k in selected
        },
        "nonfinite_gradient_norms": sum(
            r["gradients"][k][field] is None
            for r in pairs
            for k in selected
            for field in ("positive_norm", "zero_norm")
        ),
        "pairs": pairs,
    }
    save(path, result)
