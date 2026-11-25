"""Full native restart at an optimizer boundary, including actor selection and log tails."""

import random
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def test_bound_state_rewinds_uncommitted_outputs_and_recovers_rng(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    OmegaConf = pytest.importorskip("omegaconf").OmegaConf
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    from qrag_ref_fit_state import LOGS, restore, save

    cfg = OmegaConf.create(
        dict(logger=dict(log_dir=str(tmp_path)), checkpoint_dir=str(tmp_path), accumulate_grads=2)
    )
    (tmp_path / "tb_logs").mkdir()
    for name in LOGS:
        (tmp_path / name).write_bytes(b"committed\n")
    best = tmp_path / "model_best.pt"
    best.write_bytes(b"selected actor")
    critic = torch.nn.Linear(2, 1)
    opt = torch.optim.AdamW(critic.parameters())
    agent = SimpleNamespace(
        critic=critic,
        policy=torch.nn.Linear(2, 1),
        v_net_target=torch.nn.Linear(2, 1),
        action_embed_target=torch.nn.Linear(2, 1),
        critic_optim=opt,
        scheduler=torch.optim.lr_scheduler.StepLR(opt, step_size=2),
        alpha=0.2,
        _update_step=2,
    )
    critic(torch.ones(1, 2)).sum().backward()
    opt.step()
    opt.zero_grad()
    agent.scheduler.step()
    parallel = SimpleNamespace(
        text_envs=[SimpleNamespace(dataset="frozen train", memory=[1])],
        episodic_returns=np.array([1.25]),
        tmp_data=[[]],
    )
    archive = tmp_path / "state.zst"
    save(archive, cfg, agent, parallel, [[1]], 2, 24, [0.75], 0.5, 14.5)
    expected = [p.detach().clone() for p in critic.parameters()]
    moments = [opt.state[p]["exp_avg"].clone() for p in critic.parameters()]
    draws = (random.random(), np.random.random(), torch.rand(4))  # noqa: S311 -- RNG replay
    for param in critic.parameters():
        param.detach().zero_()
        opt.state[param]["exp_avg"].zero_()
    for name in LOGS:
        with (tmp_path / name).open("ab") as stream:
            stream.write(b"later\n")
    later = tmp_path / "new-best"
    later.write_bytes(b"uncommitted winner")
    later.replace(best)
    parallel.text_envs[0].memory = []
    assert restore(archive, cfg, agent, parallel) == (2, 24, [[1]], [0.75], 0.5, 14.5)
    assert best.read_bytes() == b"selected actor"
    assert parallel.text_envs[0].memory == [1] and parallel.text_envs[0].dataset == "frozen train"
    for name in LOGS:
        log = tmp_path / name
        assert log.read_bytes() == b"committed\n"
        assert next(log.parent.glob(log.name + ".superseded-*")).read_bytes() == b"later\n"
    for p, weight, moment in zip(critic.parameters(), expected, moments, strict=True):
        assert torch.equal(p, weight) and torch.equal(opt.state[p]["exp_avg"], moment)
    assert (random.random(), np.random.random()) == draws[:2]  # noqa: S311 -- RNG replay
    assert torch.equal(torch.rand(4), draws[2])
