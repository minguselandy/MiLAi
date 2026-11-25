"""Local, lossless optimizer-boundary restart for the pinned native PQN/GT loop."""

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf

MODULES = ("critic", "policy", "v_net_target", "action_embed_target")
LOGS = ("optimizer-progress.jsonl", "tb_logs/reference-curve.jsonl")


def save(path, cfg, agent, parallel, states, next_it, step, rewards, best, elapsed):
    run = Path(cfg.logger.log_dir)
    updates = next_it // cfg.accumulate_grads
    if agent._update_step != next_it or next_it % cfg.accumulate_grads:
        raise ValueError("REF restart requires a completed optimizer step")
    best_actor = Path(cfg.checkpoint_dir) / "model_best.pt"
    retained = best_actor.with_name(f"restart-best-{updates}-{time.time_ns()}.pt")
    os.link(best_actor, retained)

    payload = dict(
        format="native-pqn-fit-v1",
        config=OmegaConf.to_container(cfg, resolve=True),
        modules={name: getattr(agent, name).state_dict() for name in MODULES},
        optimizer=agent.critic_optim.state_dict(),
        scheduler=agent.scheduler.state_dict(),
        alpha=agent.alpha,
        next_it=next_it,
        step=step,
        rewards=rewards,
        best=best,
        environment=[
            {k: v for k, v in vars(e).items() if k != "dataset"} for e in parallel.text_envs
        ],
        states=states,
        episodic_returns=parallel.episodic_returns,
        tmp_data=parallel.tmp_data,
        python_rng=random.getstate(),
        numpy_rng=np.random.get_state(),
        cpu_rng=torch.get_rng_state(),
        cuda_rng=torch.cuda.get_rng_state_all(),
        best_actor=str(retained),
        elapsed=elapsed,
        offsets={name: (run / name).stat().st_size for name in LOGS},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    try:
        with (
            part.open("wb") as out,
            subprocess.Popen(
                ["/usr/bin/zstd", "-q", "-1", "-T1", "--no-check", "-c"],
                stdin=subprocess.PIPE,
                stdout=out,
            ) as compressor,
        ):
            with compressor.stdin as stream:
                torch.save(payload, stream)
            if compressor.wait():
                raise OSError("REF training-state compression failed")
            out.flush()
            os.fsync(out.fileno())
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
    # These links retain the exact evaluation winner across discarded tail updates.
    for old in best_actor.parent.glob("restart-best-*.pt"):
        if old != retained:
            old.unlink()
    print(f"[REF state] saved {updates} updates, {path.stat().st_size} bytes", flush=True)


def restore(path, cfg, agent, parallel, *, rewind_outputs=True):
    # This privately produced file contains native environment classes and RNG arrays.
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        raw = Path(temp) / "restored.pt"
        with raw.open("wb") as out:
            subprocess.run(["/usr/bin/zstd", "-qdc", str(path)], stdout=out, check=True)  # noqa: S603 -- fixed local decompressor, no shell
        saved = torch.load(raw, map_location="cpu", mmap=True, weights_only=False)
        if saved["format"] != "native-pqn-fit-v1" or saved["config"] != OmegaConf.to_container(
            cfg, resolve=True
        ):
            raise ValueError("REF restart configuration does not match")
        for name in MODULES:
            getattr(agent, name).load_state_dict(saved["modules"][name])
        agent.critic_optim.load_state_dict(saved["optimizer"])
        # Adam may retain CPU step scalars from the mmap even with CUDA parameters.
        for slots in agent.critic_optim.state.values():
            for key, value in slots.items():
                if torch.is_tensor(value) and value.device.type == "cpu":
                    slots[key] = value.clone()
        agent.scheduler.load_state_dict(saved["scheduler"])
        agent.alpha, agent._update_step = saved["alpha"], saved["next_it"]
        for env, record in zip(parallel.text_envs, saved["environment"], strict=True):
            vars(env).update(record)
        parallel.episodic_returns, parallel.tmp_data = saved["episodic_returns"], saved["tmp_data"]
        run = Path(cfg.logger.log_dir)
        retained = Path(saved["best_actor"])
        destination = Path(cfg.checkpoint_dir) / "model_best.pt"
        if not retained.is_file():
            raise ValueError("Missing saved REF evaluation winner")
        for name, offset in saved["offsets"].items():
            log = run / name
            if log.stat().st_size < offset:
                raise ValueError("REF log is shorter than committed training state")
        if rewind_outputs:
            for name, offset in saved["offsets"].items():
                log = run / name
                if log.stat().st_size > offset:
                    with (
                        log.open("r+b") as stream,
                        log.with_name(f"{log.name}.superseded-{time.time_ns()}").open("xb") as tail,
                    ):
                        stream.seek(offset)
                        shutil.copyfileobj(stream, tail)
                        stream.truncate(offset)
            if not destination.exists() or not destination.samefile(retained):
                link = destination.with_suffix(".restore")
                link.unlink(missing_ok=True)
                os.link(retained, link)
                link.replace(destination)
            marker = run / "fit-resumed.json"
            partial = marker.with_suffix(".part")
            partial.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "start_ticks": int(
                            Path("/proc/self/stat").read_text().rpartition(")")[2].split()[19]
                        ),
                        "restored_rollouts": saved["next_it"],
                        "run": str(run.resolve()),
                    }
                )
                + "\n"
            )
            partial.replace(marker)
        random.setstate(saved["python_rng"])
        np.random.set_state(saved["numpy_rng"])
        torch.set_rng_state(saved["cpu_rng"])
        torch.cuda.set_rng_state_all(saved["cuda_rng"])
        return (
            saved["next_it"],
            saved["step"],
            saved["states"],
            saved["rewards"],
            saved["best"],
            saved["elapsed"],
        )
