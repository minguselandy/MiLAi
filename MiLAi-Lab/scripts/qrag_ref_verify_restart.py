"""Replay a trusted REF snapshot to the next logged update without changing the fit."""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from hydra.utils import instantiate
from omegaconf import OmegaConf
from qrag_ref_fit_state import restore


def verify(directory, state, source):
    sys.path.insert(0, str(source))
    from envs.parallel_env import ParallelTextEnv
    from eval_retriever import evaluate_episode
    from rl.agents.pqn import PQN

    cfg = OmegaConf.load(directory / "config.yaml")
    torch.set_default_device(cfg.device)
    torch.set_float32_matmul_precision("high")
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    torch.cuda.manual_seed(cfg.seed)
    torch.backends.cudnn.deterministic = True
    agent = PQN(cfg.algo)
    probe = agent.critic.state_embed.model.encoder.layer[0].attention.self.query.weight
    initial = probe[:32, :32].detach().clone()
    env = instantiate(cfg.envs.env)
    validation_env = instantiate(cfg.envs.test_env)
    parallel = ParallelTextEnv(
        [env] + [env.copy() for _ in range(cfg.envs_parallel - 1)],
        state_tokenizer=agent.state_tokenizer,
        action_tokenizer=agent.action_tokenizer,
    )
    next_it, step, states, train_rewards, saved_best, _ = restore(
        state, cfg, agent, parallel, rewind_outputs=False
    )
    saved_best = float(saved_best)
    restored = next_it // cfg.accumulate_grads
    progress = [
        json.loads(s) for s in (directory / "optimizer-progress.jsonl").read_text().splitlines()
    ]
    expected = next((r for r in progress if r["optimizer_updates"] > restored), None)
    if expected is None:
        raise ValueError("No later uninterrupted measurement is available yet")
    count = expected["optimizer_updates"]
    iterations = (count - restored) * cfg.accumulate_grads
    curve = {
        row["rollout_iterations"]: row
        for row in map(
            json.loads, (directory / "tb_logs/reference-curve.jsonl").read_text().splitlines()
        )
    }
    prior_best = max(row["gt_dev_return"] for n, row in curve.items() if n <= next_it)
    validations = []
    validation_episodes = 0
    eval_interval = cfg.eval_interval * cfg.accumulate_grads
    total_rollouts = cfg.steps_count * cfg.accumulate_grads
    for it in range(next_it, next_it + iterations):
        agent.train()
        states, rewards, data = parallel.rollout(
            cfg.batch_size, states, agent, random=(step < 2 * cfg.learning_start)
        )
        step += data.reward.numel()
        train_rewards.extend(rewards)
        loss = agent.update(
            data.state, data.action, data.next_state, data.q_values, data.reward, data.not_done
        )
        if it % eval_interval == 0 or it + 1 == total_rollouts:
            agent.eval()
            returns = [
                evaluate_episode(validation_env, agent, validation_env.dataset[i])["return"]
                for i in range(cfg.eval_episodes)
            ]
            validation_episodes += len(returns)
            replayed = dict(
                rollout_iterations=it + 1,
                optimizer_updates=(it + 1) // cfg.accumulate_grads,
                official_logged_step=int(step),
                critic_transitions=(it + 1) * cfg.batch_size,
                gt_train_return=float(np.mean(train_rewards)),
                gt_dev_return=float(np.mean(returns)),
                dev_episodes=len(returns),
                loss=float(loss),
                backbone_probe_max_change=float((probe[:32, :32] - initial).abs().max().item()),
            )
            uninterrupted = {k: curve[it + 1][k] for k in replayed}
            validations.append(
                dict(
                    uninterrupted=uninterrupted, recovered=replayed, equal=replayed == uninterrupted
                )
            )
            train_rewards = []
    observed = dict(
        loss=float(loss),
        backbone_probe_max_change=float((probe[:32, :32] - initial).abs().max().item()),
    )
    return dict(
        restored_optimizer_updates=restored,
        replayed_optimizer_updates=count - restored,
        compared_update=count,
        training_transitions=cfg.batch_size * iterations,
        replayed_validation_episodes=validation_episodes,
        uninterrupted={k: expected[k] for k in observed},
        recovered=observed,
        restored_best_return=saved_best,
        uninterrupted_best_at_restore=prior_best,
        replayed_validations=validations,
        measured_fields_equal=(
            saved_best == prior_best
            and all(row["equal"] for row in validations)
            and all(v == expected[k] for k, v in observed.items())
        ),
        reader_calls=0,
        training_outputs_rewound=False,
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("run", "state", "source", "output"):
        cli.add_argument("--" + key, type=Path, required=True)
    args = cli.parse_args()
    start = time.monotonic()
    result = verify(args.run, args.state, args.source)
    result["one_gpu_wall_seconds"] = time.monotonic() - start
    part = args.output.with_suffix(".part")
    part.write_text(json.dumps(result, indent=2) + "\n")
    part.replace(args.output)
    if not result["measured_fields_equal"]:
        raise SystemExit("Recovered training or validation differs from the recorded run")
