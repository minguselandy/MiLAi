"""Check the outcome fitter's gradient on one real registered TRAIN optimizer window."""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import torch

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.methods.control_state_text import control_sequences
from milai_lab.methods.pretrained_control import PretrainedControl
from milai_lab.methods.pretrained_objective import group_weights, root_loss
from milai_lab.runners.pretrained_control_train import TrainingRoots


def output_derivatives(row, quality, future, head_weights, cost_scale, pair_weight):
    """Differentiate Huber analytically with each mask's actual within-root denominator."""
    ids = [a["id"] for a in row["online"]["actions"]]
    measured = {o["first_action_id"]: o for o in row["outcomes"]}
    weights = quality.new_tensor(head_weights, dtype=torch.float64) / sum(head_weights)
    q, c = quality.detach().double(), future.detach().double()
    dq, dc = torch.zeros_like(q), torch.zeros_like(c)
    for pred, grad, target, flag, scale, coeff in (
        (q, dq, "reader_quality", "quality_observed", 1, 1),
        (c, dc, "future_cost", "future_cost_observed", cost_scale, 0.1),
    ):
        available = [k for k, outcome in measured.items() if outcome[flag]]
        for key in available:
            i = ids.index(key)
            grad[i] += (
                (pred[i] - measured[key][target] / scale).clamp(-1, 1)
                * weights
                * (coeff / len(available))
            )
    pairs = [
        (a, b)
        for a, b in row["comparisons"]
        if all(k in measured and measured[k]["quality_observed"] for k in (a, b))
    ]
    nonzero = 0
    for a, b in pairs:
        ia, ib = ids.index(a), ids.index(b)
        truth = measured[a]["reader_quality"] - measured[b]["reader_quality"]
        nonzero += truth != 0
        contribution = (
            (q[ia] - q[ib] - truth).clamp(-1, 1)
            * weights
            * (pair_weight * min(1, abs(truth) / 0.05) / len(pairs))
        )
        dq[ia] += contribution
        dq[ib] -= contribution
    return dq, dc, len(pairs), nonzero


def compare_parameters(model, first):
    baseline_sq = error_sq = largest = 0.0
    tensors = parameters = nonzero = 0
    per_parameter = {}
    for name, parameter in model.named_parameters():
        previous = first.get(name)
        if (previous is None) != (parameter.grad is None):
            raise ValueError(f"Gradient availability changed for {name}")
        if previous is None:
            continue
        tensors += 1
        parameters += previous.numel()
        previous = previous.reshape(-1)
        current = parameter.grad.detach().cpu().reshape(-1)
        tensor_sq = tensor_error_sq = 0.0
        for start in range(0, previous.numel(), 1 << 20):
            a = previous[start : start + (1 << 20)].double()
            diff = current[start : start + len(a)].double() - a
            tensor_sq += a.dot(a).item()
            tensor_error_sq += diff.dot(diff).item()
            largest = max(largest, diff.abs().max().item())
        nonzero += tensor_sq > 0
        baseline_sq += tensor_sq
        error_sq += tensor_error_sq
        per_parameter[name] = math.sqrt(tensor_error_sq)
    if not baseline_sq or not math.isfinite(baseline_sq + error_sq):
        raise ValueError("No finite nonzero parameter gradient to compare")
    return dict(
        gradient_tensors=tensors,
        nonzero_gradient_tensors=nonzero,
        parameters=parameters,
        reference_l2=math.sqrt(baseline_sq),
        error_l2=math.sqrt(error_sq),
        relative_l2=math.sqrt(error_sq / baseline_sq),
        maximum_absolute_error=largest,
        highest_error_l2=dict(sorted(per_parameter.items(), key=lambda item: -item[1])[:5]),
    )


def check_object_tiling(model, roots, order, cfg, output):
    """Compare single-object microbatches to one dense forward of the same encoded legal menu."""
    if model.device.type != "cpu":
        raise ValueError("Use CPU FP32 for the deterministic object-tiling comparison")
    original_limit = model.limit
    selected = {}
    for key, source, group in order:
        row = roots.row(key)
        online = row["online"]
        encoded = control_sequences(model.tokenizer, online, original_limit, history=model.history)
        sequences = encoded[0]
        dense_tokens = len(sequences) * max(map(len, sequences))
        if len(sequences) < 2 or dense_tokens > 8192:
            continue
        expanded_limit = max(original_limit, (dense_tokens + 1) // 2)
        if expanded_limit != original_limit and encoded != control_sequences(
            model.tokenizer, online, expanded_limit, history=model.history
        ):
            continue
        rank = (dense_tokens, row["root_state_id"])
        if source not in selected or rank < selected[source][0]:
            selected[source] = (rank, row, group, expanded_limit, len(sequences))
    if selected.keys() != roots.groups.keys():
        raise ValueError("No token-identical dense reference for an eligible training source")
    # Keep activation checkpointing while disabling stochastic encoder/head layers.
    model.train()
    model.reranker.eval()
    model.heads.eval()
    reports = {}
    for source, ((work, root_id), row, group, expanded_limit, objects) in selected.items():
        weights = group_weights(cfg["seed"], f"{source}/{group}")
        scores = []
        forwards = []
        for limit, size in ((original_limit, 1), (expanded_limit, objects)):
            model.limit, model.object_batch = limit, size
            model.zero_grad(set_to_none=True)
            before = model.counters["forwards"]
            q, c = model.score(row["online"])
            scores.append((q.detach(), c.detach()))
            loss, pairs = root_loss(
                row, q, c, weights, model.cost_scale, pair_weight=cfg["pair_weight"]
            )
            loss.backward()
            forwards.append(model.counters["forwards"] - before)
            if size == 1:
                first = {
                    name: p.grad.detach()
                    for name, p in model.named_parameters()
                    if p.grad is not None
                }
        if forwards != [objects, 1]:
            raise ValueError("The selected dense reference split its object menu")
        drift = max((a - b).abs().max().item() for a, b in zip(*scores, strict=True))
        reports[source] = dict(
            root=root_id,
            native_group=group,
            objects=objects,
            legal_actions=len(q),
            observed_comparisons=pairs,
            forwards=forwards,
            dense_padded_tokens=work,
            maximum_forward_abs=drift,
            parameter_gradient=compare_parameters(model, first),
        )
        del first
    write_json(
        output,
        dict(
            fit_seed=cfg["seed"],
            observed_sources=reports,
            device="cpu",
            precision="FP32",
            input_ids_owners_levels_equal=True,
            optimizer_updates=0,
            new_reader_calls=0,
        ),
    )
    if any(
        r["maximum_forward_abs"] > 1e-5 or r["parameter_gradient"]["relative_l2"] > 1e-5
        for r in reports.values()
    ):
        raise ValueError("Object tilings exceed the registered FP32 tolerance")


def audit(args):
    fit = read_json(args.fit / "run.json")
    cfg = fit["contract"]
    if fit["status"] != "completed" or cfg["supervision_mode"] not in {"paired", "direct"}:
        raise ValueError("Expected a completed outcome fit")
    if cfg["input"] not in (str(args.packs), str([path.resolve() for path in args.packs])):
        raise ValueError("The package directories differ from the fit's recorded inputs")
    roots = TrainingRoots(SimpleNamespace(objective=cfg["supervision_mode"], data=args.packs))
    if tuple(cfg["target"]) != roots.target:
        raise ValueError("Input continuation differs from the recorded fit")
    weights = cfg["source_weights"]
    order = list(roots.epoch(random.Random(cfg["seed"]), weights))  # noqa: S311 -- registered order
    if len(order) != cfg["selected_per_epoch"] or len(order) != cfg["full_population"]:
        raise ValueError("Expected the full registered epoch")
    batch = order[: cfg["effective_batch"]]
    counts = Counter((s, g) for _, s, g in order)
    groups = Counter(s for s, _ in counts)
    mass = sum(weights[s] for s in groups)
    model = PretrainedControl.load(Path(cfg["parent"]), device=args.device).train()
    model.object_batch = cfg["object_batch"]
    model.cost_scale = cfg["cost_scale"]
    if args.object_tiling:
        torch.use_deterministic_algorithms(True)
        return check_object_tiling(model, roots, order, cfg, args.output)
    torch.manual_seed(cfg["seed"])
    cpu_rng = torch.get_rng_state()
    cuda_rng = torch.cuda.get_rng_state(model.device) if model.device.type == "cuda" else None
    scores = []
    registration = []
    max_output_error = 0.0
    # The native streaming path differentiates one complete weighted root at a time.
    for key, source, group in batch:
        row = roots.row(key)
        heads = group_weights(cfg["seed"], f"{source}/{group}")
        fraction = (
            weights[source]
            * len(order)
            / (mass * groups[source] * counts[source, group])
            / len(batch)
        )
        quality, future = model.score(row["online"])
        loss, pairs = root_loss(
            row, quality, future, heads, model.cost_scale, pair_weight=cfg["pair_weight"]
        )
        scalar = loss * fraction
        actual = torch.autograd.grad(
            scalar, (quality, future), retain_graph=True, allow_unused=True
        )
        dq, dc, n, informative = output_derivatives(
            row, quality, future, heads, model.cost_scale, cfg["pair_weight"]
        )
        # Derive the share independently from the frozen native group inventory.
        share = (
            weights[source]
            / mass
            / len(roots.groups[source])
            / len(roots.groups[source][group])
            * len(order)
            / len(batch)
        )
        if quality.new_tensor(share).item() != quality.new_tensor(fraction).item():
            raise ValueError("Native and inventory-derived FP32 root weights differ")
        for grad, expected in zip(actual, (dq * share, dc * share), strict=True):
            measured = torch.zeros_like(expected) if grad is None else grad.double()
            torch.testing.assert_close(measured, expected, rtol=1e-5, atol=2e-7)
            max_output_error = max(max_output_error, (measured - expected).abs().max().item())
        if pairs != n:
            raise ValueError("Native and analytic pair denominators differ")
        scores.append((quality.detach().cpu(), future.detach().cpu()))
        registration.append(
            dict(
                root=row["root_state_id"],
                source=source,
                group=group,
                head_weights=heads,
                root_share=share,
                legal_actions=len(quality),
                outcomes=len(row["outcomes"]),
                observed_pairs=n,
                nonzero_pairs=informative,
            )
        )
        scalar.backward()
    first = {
        name: p.grad.detach().cpu().clone()
        for name, p in model.named_parameters()
        if p.grad is not None
    }
    native_forwards = model.counters["forwards"]
    model.zero_grad(set_to_none=True)
    torch.set_rng_state(cpu_rng)
    if cuda_rng is not None:
        torch.cuda.set_rng_state(cuda_rng, device=model.device)
    terms = []
    for (key, _, _), recorded, (expected_q, expected_c) in zip(
        batch, registration, scores, strict=True
    ):
        row = roots.row(key)
        q, c = model.score(row["online"])
        if not torch.equal(q.detach().cpu(), expected_q) or not torch.equal(
            c.detach().cpu(), expected_c
        ):
            raise ValueError("The two passes did not see the same stochastic forward")
        loss, _ = root_loss(
            row, q, c, recorded["head_weights"], model.cost_scale, pair_weight=cfg["pair_weight"]
        )
        weighted = loss * recorded["root_share"]
        if args.repeat_streaming:
            weighted.backward()
        else:
            terms.append(weighted)
    if terms:
        torch.stack(terms).sum().backward()
    gradient = compare_parameters(model, first)
    result = dict(
        fit=str(args.fit),
        parent=cfg["parent"],
        device=str(model.device),
        roots=registration,
        population=len(order),
        effective_batch=len(batch),
        object_batch=model.object_batch,
        deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
        second_backward="per_root" if args.repeat_streaming else "whole_batch",
        peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated(model.device)
        if model.device.type == "cuda"
        else None,
        attested_unchanged_forward_roots=len(scores),
        encoder_forwards_per_pass=native_forwards,
        second_encoder_forwards=model.counters["forwards"] - native_forwards,
        max_absolute_analytic_output_gradient_error=max_output_error,
        parameter_gradient=gradient,
        optimizer_updates=0,
        new_reader_calls=0,
    )
    write_json(args.output, result)
    if gradient["relative_l2"] > 1e-5:
        raise ValueError(
            f"Parameter-gradient relative L2 exceeds 1e-5; measured results are in {args.output}"
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fit", type=Path, required=True)
    p.add_argument("--packs", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--device", help="Batch-gradient device (default cuda); object tiling uses cpu")
    p.add_argument(
        "--repeat-streaming",
        action="store_true",
        help="Repeat the per-root backward as a numerical control",
    )
    p.add_argument(
        "--deterministic", action="store_true", help="Use deterministic kernels in both passes"
    )
    p.add_argument(
        "--object-tiling", action="store_true", help="Compare identical legal menus on CPU FP32"
    )
    args = p.parse_args()
    args.device = args.device or ("cpu" if args.object_tiling else "cuda")
    if args.object_tiling and (args.device != "cpu" or args.repeat_streaming):
        p.error("--object-tiling measures a CPU FP32 object partition")
    torch.set_num_threads(4 if args.object_tiling else 2)
    if args.deterministic:
        torch.use_deterministic_algorithms(True)
    audit(args)
