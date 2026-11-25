"""Read-only replay of the next native optimizer update from a trusted local REF snapshot."""

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
    instantiate(cfg.envs.test_env)
    parallel = ParallelTextEnv(
        [env] + [env.copy() for _ in range(cfg.envs_parallel - 1)],
        state_tokenizer=agent.state_tokenizer,
        action_tokenizer=agent.action_tokenizer,
    )
    next_it, step, states, _, _, _ = restore(state, cfg, agent, parallel, rewind_outputs=False)
    restored = next_it // cfg.accumulate_grads
    progress = [
        json.loads(s) for s in (directory / "optimizer-progress.jsonl").read_text().splitlines()
    ]
    expected = next((r for r in progress if r["optimizer_updates"] > restored), None)
    if expected is None:
        raise ValueError("No later uninterrupted measurement is available yet")
    count = expected["optimizer_updates"]
    iterations = (count - restored) * cfg.accumulate_grads
    for _ in range(iterations):
        agent.train()
        states, _, data = parallel.rollout(
            cfg.batch_size, states, agent, random=(step < 2 * cfg.learning_start)
        )
        step += data.reward.numel()
        loss = agent.update(
            data.state, data.action, data.next_state, data.q_values, data.reward, data.not_done
        )
    observed = dict(
        loss=float(loss),
        backbone_probe_max_change=float((probe[:32, :32] - initial).abs().max().item()),
    )
    return dict(
        restored_optimizer_updates=restored,
        replayed_optimizer_updates=count - restored,
        compared_update=count,
        training_transitions=cfg.batch_size * iterations,
        uninterrupted={k: expected[k] for k in observed},
        recovered=observed,
        measured_fields_equal=all(v == expected[k] for k, v in observed.items()),
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
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["measured_fields_equal"]:
        raise SystemExit("Recovered native update differs from the uninterrupted update")
