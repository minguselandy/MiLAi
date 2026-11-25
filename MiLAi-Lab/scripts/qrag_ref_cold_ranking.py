"""Compare history-conditioned native greedy retrieval with its own frozen first-step ranking."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import torch
from eval_retriever import calc_fact_f1_em, set_all_seeds
from hydra.utils import instantiate
from omegaconf import OmegaConf
from qrag_ref_retrieval import grade_row, load_bound_actor, read, retrieval_protocol, save
from rl.agents.pqn import PQN


@torch.inference_mode()
def cold_episode(env, agent, sample, dynamic):
    state = env.reset(sample)
    online, target = env.get_extra_embeds(
        agent.action_tokenizer, agent.critic.action_embed, agent.action_embed_target
    )
    first, scores, _ = agent.select_action(
        state,
        env.update_embeds(online, agent.critic.action_embed)["rope"],
        env.update_embeds(target, agent.action_embed_target)["rope"],
        random=False,
        evaluate=True,
    )
    scores = scores.float().cpu().numpy()
    if len(scores) != len(sample["chunks"]) or not np.isfinite(scores).all():
        raise ValueError("Incomplete initial chunk scores")
    rank = np.argsort(-scores, kind="stable").tolist()
    if (
        first != rank[0]
        or first != dynamic["pred_idx"][0]
        or float(scores[first]) != dynamic["q_values"][0]
    ):
        raise ValueError(f"Initial greedy action or maximum score differs on {sample['id']}")
    reward = 0.0
    for action in rank:
        if action not in state.available_ids:
            raise ValueError("Cold-ranked action became illegal")
        state, _, gain, done = env.step(action)
        reward += gain
        if done:
            break
    predicted = list(map(int, state.item_ids))
    truth = list(map(int, sample["sf_idx"]))
    f1, em = calc_fact_f1_em(predicted, truth)
    frozen = {"pred_idx": predicted, "sf_idx": truth, "f1": f1, "em": em, "return": reward}
    grade_row(frozen)
    grade_row(dynamic)
    if truth != dynamic["sf_idx"]:
        raise ValueError("Native support annotation changed")
    return {
        "id": sample["id"],
        "support": truth,
        "cold_order": rank,
        "cold": {k: frozen[k] for k in ("pred_idx", "em", "f1")},
        "dynamic": {k: dynamic[k] for k in ("pred_idx", "em", "f1")},
    }


def evaluate(directory, source, roster):
    # Compose the same testing overrides as the original native evaluation.
    cfg = OmegaConf.merge(
        OmegaConf.load(directory / "config.yaml"),
        OmegaConf.load(source / "configs/testing.yaml"),
        {"pretrained_path": str(directory), "num_samples": -1, "envs": {"max_steps": 4}},
    )
    OmegaConf.resolve(cfg)
    set_all_seeds(cfg.seed)
    torch.set_default_device(cfg.device)
    torch.set_float32_matmul_precision("high")
    agent = PQN(cfg.algo)
    binding = read(directory / "actor-binding.json")
    origin = load_bound_actor(agent, binding)
    agent.eval()
    env = instantiate(cfg.envs.test_env)
    common = retrieval_protocol(cfg, env)
    recorded = read(directory / "native-protocol.json")
    if (
        common != recorded["common"]
        or binding["optimizer_updates"] != recorded["optimizer_updates"]
    ):
        raise ValueError("Native evaluator or actor binding changed")
    with (directory / f"eval_seed{cfg.seed}.jsonl").open() as stream:
        observed = [json.loads(line) for line in stream]
    dynamic = {r["id"]: r for r in observed}
    if len(observed) != len(roster) or set(dynamic) != set(roster):
        raise ValueError("Recorded dynamic trajectories differ from the registered roster")
    rows = []
    for i in range(len(env.dataset)):
        sample = env.dataset[i]
        rows.append(cold_episode(env, agent, sample, dynamic[sample["id"]]))
    if len(rows) != len(roster) or {r["id"] for r in rows} != set(roster):
        raise ValueError("Cold policy did not visit every registered question exactly once")
    return dict(step=binding["optimizer_updates"], origin=origin, protocol=common, rows=rows)


def summarize(initial, trained, roster):
    if initial["protocol"] != trained["protocol"] or initial["step"] != 0 or trained["step"] <= 0:
        raise ValueError("Expected an initialization and a trained actor on identical protocols")
    arms = [{r["id"]: r for r in record["rows"]} for record in (initial, trained)]
    if any(arms[0][k]["support"] != arms[1][k]["support"] for k in roster):
        raise ValueError("Paired actors have different support annotations")
    counts = np.array([len(arms[0][k]["support"]) for k in roster])
    seed, repeats = 20261126, 5000
    draws = np.random.default_rng(seed).integers(len(roster), size=(repeats, len(roster)))
    result = dict(
        questions=len(roster),
        paired_bootstrap={"unit": "question", "seed": seed, "repeats": repeats},
        actors={"initial": initial, "trained": trained},
        new_reader_calls=0,
    )
    for metric in ("em", "f1"):
        changes = []
        for label, arm in zip(("initial", "trained"), arms, strict=True):
            values = np.array(
                [[arm[k][mode][metric] for mode in ("dynamic", "cold")] for k in roster]
            )
            delta = values[:, 0] - values[:, 1]
            changes.append(delta)
            result.setdefault(label, {})[metric] = dict(
                dynamic=float(values[:, 0].mean()),
                cold=float(values[:, 1].mean()),
                dynamic_minus_cold=float(delta.mean()),
                interval_95=np.quantile(delta[draws].mean(1), [0.025, 0.975]).tolist(),
                wins=int((delta > 0).sum()),
                ties=int((delta == 0).sum()),
                losses=int((delta < 0).sum()),
                by_support_count={
                    str(n): dict(
                        questions=int((counts == n).sum()),
                        dynamic=float(values[counts == n, 0].mean()),
                        cold=float(values[counts == n, 1].mean()),
                    )
                    for n in sorted(set(counts))
                },
            )
        change = changes[1] - changes[0]
        result.setdefault("change_in_dynamic_minus_cold", {})[metric] = dict(
            mean=float(change.mean()),
            interval_95=np.quantile(change[draws].mean(1), [0.025, 0.975]).tolist(),
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("initial", "trained", "source", "roster", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    roster = read(args.roster)
    if roster["role"] != "TUNE" or len(set(roster["groups"])) != roster["n"]:
        raise ValueError("Expected the registered TUNE population")
    args.output.mkdir(parents=True, exist_ok=True)
    runs = [evaluate(path, args.source, roster["groups"]) for path in (args.initial, args.trained)]
    report = summarize(*runs, roster["groups"])
    with TemporaryDirectory(dir=args.output) as tmp:
        path = Path(tmp) / "comparison.json"
        save(path, report)
        path.replace(args.output / path.name)
