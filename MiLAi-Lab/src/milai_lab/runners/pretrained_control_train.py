"""Fit S1 evidence demonstrations or DQ/PQ on a frozen TRAIN feedback pack."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sqlite3
import statistics
import time
import zlib
from collections import Counter, defaultdict, deque
from pathlib import Path

import torch

from milai_lab.methods.control_cost_scale import (
    HOST_COST_STATISTIC,
    load_host_cost_scale,
    require_same_host_cost_scale,
)
from milai_lab.methods.pretrained_control import PretrainedControl
from milai_lab.methods.pretrained_objective import group_weights, root_loss
from milai_lab.runners.pretrained_fit_closeout import (
    finish_verified,
    fit_owner,
    fit_window,
    write_json,
)


def validate_terminal_pack(row):
    if row["continuation_mode"] != "full_episode" or row["split_role"] != "train":
        raise ValueError("Pack outside full TRAIN protocol")
    terminal = {
        "handoff",
        "no_feasible_read",
        "max_operations",
        "budget_exhausted",
        "material_budget_exhausted",
    }
    for result in row["outcomes"]:
        has_quality = result["quality_observed"]
        has_cost = result["future_cost_observed"]
        if has_quality != (result["reader_quality"] is not None) or has_cost != (
            result["future_cost"] is not None
        ):
            raise ValueError("Observed masks disagree with the supplied targets")
        if (has_quality or has_cost) and (
            result["termination_reason"] not in terminal or not result["reader_receipt_ids"]
        ):
            raise ValueError("Measured targets require a formal terminal Reader receipt")
        if (
            has_quality
            and row["source"] == "musique_full"
            and (
                not result["companion_receipt_id"]
                or not result["pair_metrics"]
                or result["pair_metrics"]["group_answer_sufficiency_f1"] != result["reader_quality"]
            )
        ):
            raise ValueError("MuSiQue quality requires the native pair and its companion receipt")


class TrainingRoots:
    def __init__(self, args):
        self.groups = defaultdict(lambda: defaultdict(list))
        self.costs = []
        self.target = None
        self.db = None
        self.files = []
        self.addresses = {}
        if args.objective == "evidence":
            self.db = sqlite3.connect(f"file:{args.data}?mode=ro", uri=True)
            if not (
                args.probe
                or self.db.execute(
                    "SELECT count(*) FROM manifest WHERE field IN ('complete','replay_complete')"
                ).fetchone()[0]
                == 2
            ):
                raise ValueError("Evidence population preparation is still running")
            self.index_evidence(
                getattr(args, "evidence_order_map", None), getattr(args, "evidence_master", None)
            )
        else:
            if getattr(args, "evidence_order_map", None) or getattr(args, "evidence_master", None):
                raise ValueError("Native root-order restoration applies to evidence inputs")
            roots = set()
            protocols = set()
            for directory in args.data:
                for file in sorted(directory.glob("*.json.gz")):
                    with gzip.open(file) as handle:
                        row = json.load(handle)
                    validate_terminal_pack(row)
                    key = row["root_state_id"]
                    if key in roots:
                        raise ValueError("Duplicate root within epoch")
                    roots.add(key)
                    protocols.add((row["collection_round"], row["continuation_policy_id"]))
                    if not any(
                        o["quality_observed"] or o["future_cost_observed"] for o in row["outcomes"]
                    ):
                        continue
                    self.groups[row["source"]][row["native_group_id"]].append(len(self.files))
                    self.files.append(file)
                    self.costs.extend(
                        o["future_cost"] for o in row["outcomes"] if o["future_cost_observed"]
                    )
            if len(protocols) != 1:
                raise ValueError(f"Expected one frozen continuation target, found {protocols}")
            self.target = protocols.pop()
        if not self.groups:
            raise ValueError("Empty TRAIN pool")

    def index_evidence(self, order_path, master_path):
        if order_path is None:
            if master_path is not None:
                raise ValueError("An explicit order-map master requires a frozen order map")
            for key, source, group in self.db.execute("SELECT id,source,native_group FROM roots"):
                self.groups[source][group].append(key)
            return
        from milai_lab.runners.control_evidence_order import align

        _, _, addresses = align(self.db, order_path, master_path)
        self.addresses = {a.frozen_row: a for a in addresses}
        for a in addresses:
            self.groups[a.source][a.group].append(a.frozen_row)

    def row(self, key):
        if self.db is not None:
            if self.addresses:
                from milai_lab.runners.control_evidence_order import read_canonical_row

                return read_canonical_row(self.db, self.addresses[key])
            (data,) = self.db.execute("SELECT data FROM roots WHERE id=?", (key,)).fetchone()
            row = json.loads(zlib.decompress(data))
            history = row["root_state_id"][1:]
        else:
            with gzip.open(self.files[key]) as handle:
                row = json.load(handle)
            task_prefix = f'{row["task_id"]}_'
            if not row["root_state_id"].startswith(task_prefix):
                raise ValueError("Unrecognized root identity")
            history = row["root_state_id"][len(task_prefix) :].split("-")
        obs = row["online"]["observation"]
        if obs.setdefault("action_history", history) != history:
            raise ValueError("Recorded action history disagrees with actual root prefix")
        return row

    def epoch(self, rng, source_weights, allocation_window=256):
        # Spread each group's roots across the traversal. This retains rare sources
        # through the LR schedule, including when their total inventory is small.
        caps = {"musique_full": 4, "qasper": 6, "personamem_v2": 6}
        total = sum(len(rows) for groups in self.groups.values() for rows in groups.values())
        windows = max(
            math.ceil(total / allocation_window),
            max(
                math.ceil(len(rows) / caps[s])
                for s, groups in self.groups.items()
                for rows in groups.values()
            ),
        )
        slots = [defaultdict(lambda: defaultdict(deque)) for _ in range(windows)]
        for source, groups in self.groups.items():
            for group, rows in groups.items():
                values = list(rows)
                rng.shuffle(values)
                phase = rng.random()
                for j, key in enumerate(values):
                    index = min(windows - 1, int((j + phase) * windows / len(values)))
                    slots[index][source][group].append(key)
        for slot in slots:
            group_order = {}
            for source, groups in slot.items():
                keys = list(groups)
                rng.shuffle(keys)
                group_order[source] = deque(keys)
            while group_order:
                sources = sorted(group_order)
                source = rng.choices(sources, weights=[source_weights[s] for s in sources])[0]
                queue = group_order[source]
                group = queue.popleft()
                rows = slot[source][group]
                yield rows.popleft(), source, group
                if rows:
                    queue.append(group)
                if not queue:
                    del group_order[source]


def fit(args):
    with fit_owner(args.output, args.metrics or args.output), fit_window(args.output, args.device):
        fit_locked(args)


def fit_locked(args):
    if args.objective == "evidence":
        if len(args.data) != 1:
            raise ValueError("One evidence database required")
        args.data = args.data[0]
    if args.probe and args.probe < args.batch:
        raise ValueError("Probe must include an effective batch")
    torch.manual_seed(args.seed)
    torch.set_num_threads(1)
    roots = TrainingRoots(args)
    weights = (
        {"musique_full": 0.50, "qasper": 0.35, "personamem_v2": 0.15}
        if args.objective == "evidence"
        else {"musique_full": 0.60, "qasper": 0.30, "personamem_v2": 0.10}
    )
    population = sum(len(rows) for groups in roots.groups.values() for rows in groups.values())
    selected = min(args.probe or population, population)
    if args.initialize:
        model = PretrainedControl.load(args.initialize, device=args.device)
    else:
        model = PretrainedControl(args.backbone, device=args.device, object_batch=args.object_batch)
    parent_run = args.initialize.parent / "run.json" if args.initialize else None
    parent_contract = json.loads(parent_run.read_text())["contract"] if parent_run else {}
    scale_source = parent_contract.get("scale_source")
    report_path = getattr(args, "cost_scale_report", None)
    if report_path and args.objective == "evidence":
        raise ValueError("Host cost normalization applies at the outcome fit")
    if args.objective != "evidence":
        if report_path or (scale_source and scale_source.get("statistic") == HOST_COST_STATISTIC):
            if args.warm_packs:
                raise ValueError(
                    "A Host-normalized parent cannot switch to paid-feedback normalization"
                )
            path = report_path or Path(scale_source["report"])
            scale, new_source = load_host_cost_scale(path)
            for directory in args.data:
                protocol = json.loads((directory.parent / "round.json").read_text())
                if (
                    new_source["dataset_run_id"] != protocol["dataset_run"]
                    or new_source["memory_budget_tokens"] != protocol["material_budget"]
                    or new_source["observation"] != protocol["observation"]
                    or new_source["reader_model"] != protocol["reader"]["model_revision"]
                    or new_source["max_operations"] != protocol["environment"]["max_operations"]
                ):
                    raise ValueError("Cost scale and collected branch protocol differ")
            if scale_source:
                require_same_host_cost_scale(scale_source, new_source)
                if model.cost_scale != scale:
                    raise ValueError("Parent checkpoint value scales disagree")
            else:
                scale_source = new_source
            model.cost_scale = scale
        elif args.warm_packs:
            costs = []
            for file in sorted(args.warm_packs.glob("*.json.gz")):
                with gzip.open(file) as handle:
                    warm_row = json.load(handle)
                validate_terminal_pack(warm_row)
                if (
                    warm_row["split_role"] != "train"
                    or warm_row["collection_round"] != 0
                    or warm_row["acquisition_method"] != "uniform"
                    or warm_row["continuation_mode"] != "full_episode"
                ):
                    raise ValueError("Cost scale requires the shared uniform TRAIN warm package")
                costs.extend(
                    o["future_cost"] for o in warm_row["outcomes"] if o["future_cost_observed"]
                )
            scale = max(1.0, statistics.median(costs))
            if scale_source and scale != model.cost_scale:
                raise ValueError("Measured cost scale differs from the frozen parent scale")
            model.cost_scale = scale
            scale_source = dict(
                warm_packs=str(args.warm_packs.resolve()),
                measured=len(costs),
                statistic="median_observed_future_cost",
            )
        elif not scale_source:
            raise ValueError(
                "First outcome fit requires --cost-scale-report or a legacy --warm-packs source"
            )
    model.train()
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.lr, weight_decay=0.01, fused=args.device.startswith("cuda")
    )
    epochs = args.epochs or (1 if args.objective == "evidence" else 3)
    updates = math.ceil(selected / args.batch) * epochs
    warm = max(1, round(0.05 * updates))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda n: min((n + 1) / warm, max(0.0, (updates - n) / max(1, updates - warm)))
    )
    args.output.mkdir(parents=True, exist_ok=True)
    metrics = args.metrics or args.output
    metrics.mkdir(parents=True, exist_ok=True)
    fitted = set()
    if parent_run is not None:
        fitted.update(json.loads(parent_run.read_text())["contract"]["fitted_groups"])
    contract = {
        "seed": args.seed,
        "observation_protocol": "semantic_nav_delta_v2",
        "supervision_mode": args.objective,
        "parent": str(args.initialize) if args.initialize else None,
        "full_population": population,
        "selected_per_epoch": selected,
        "effective_batch": args.batch,
        "object_batch": model.object_batch,
        "padded_tokens_per_encoder_batch": 2 * model.limit,
        "epochs": epochs,
        "updates": updates,
        "mixed_precision": "bf16" if args.device.startswith("cuda") else "float32",
        "optimizer_dtype": "float32",
        "cost_scale": model.cost_scale,
        "target": list(roots.target) if roots.target else None,
        "scale_source": scale_source,
        "source_inventory": {
            s: {"groups": len(groups), "roots": sum(map(len, groups.values()))}
            for s, groups in roots.groups.items()
        },
        "pair_weight": 0.2 if args.objective == "paired" else 0.0,
        "source_weights": weights,
        "lr": args.lr,
        "warmup_updates": warm,
        "allocation_window_target": 256,
        "schedule": "even_native_group_phase_then_group_first",
        "group_caps_per_allocation_pass": {"musique_full": 4, "qasper": 6, "personamem_v2": 6},
        "root_weighting": "source_mass_divided_by_native_groups_and_group_roots",
        "input": str(args.data),
        "probe": bool(args.probe),
        "fitted_groups": sorted(fitted),
    }
    if getattr(args, "evidence_order_map", None):
        contract["frozen_native_root_order"] = str(args.evidence_order_map.resolve())
        if getattr(args, "evidence_master", None):
            contract["frozen_native_root_master"] = str(args.evidence_master.resolve())
    rolling = args.output / "resume.pt"
    path = args.output / "checkpoint"
    run_path = args.output / "run.json"
    previous = json.loads(run_path.read_text()) if run_path.is_file() else {}
    if previous:
        prior = dict(previous["contract"])
        previous_scale = prior.get("scale_source") or {}
        current_scale = contract.get("scale_source") or {}
        if (
            previous_scale.get("statistic") == HOST_COST_STATISTIC
            and current_scale.get("statistic") == HOST_COST_STATISTIC
        ):
            require_same_host_cost_scale(previous_scale, current_scale)
            contract["scale_source"] = prior["scale_source"]
        if previous["status"] == "completed":
            prior["fitted_groups"] = contract["fitted_groups"]
        if prior != contract or previous["status"] not in {"completed", "running"}:
            raise ValueError("Existing fit identity differs from the requested schedule")
    elif path.exists() or rolling.exists():
        raise ValueError("Artifacts without an original run declaration cannot be adopted")
    identity = previous.get("fit_identity", {"id": time.time_ns(), "backbone": str(model.backbone)})
    declared_backbone = Path(identity["backbone"])
    if str(declared_backbone) != str(model.backbone) and (
        not declared_backbone.is_dir() or not declared_backbone.samefile(model.backbone)
    ):
        raise ValueError("Backbone differs from the declared fit")
    if not metrics.samefile(args.output) and (metrics / "run.json").exists():
        try:
            m = json.loads((metrics / "run.json").read_text())
        except json.JSONDecodeError:
            if not previous:
                raise
            m = {}
        if not previous or (m.get("fit_identity") and m["fit_identity"] != identity):
            raise ValueError("Metrics belong to another fit")
    if (path / "fit_completion.json").is_file():
        del model, optimizer, scheduler
        finish_verified(PretrainedControl, args.output, metrics, identity, contract, args.device)
        return
    if previous.get("status") == "completed":
        if previous.get("fit_identity"):
            raise ValueError("Completed fit lost its original checkpoint parity payload")
        # Complete pre-journal receipts already record the original live-model reload.
        if (
            not previous.get("reload_scores_equal")
            or previous["optimizer_updates"] != updates
            or not (path / "control.pt").is_file()
            or not (path / "controller.json").is_file()
        ):
            raise ValueError("Inconsistent completed legacy fit")
        if not metrics.samefile(args.output):
            write_json(metrics / "run.json", previous)
        rolling.unlink(missing_ok=True)
        return
    if (
        path.exists()
        and previous.get("fit_identity")
        and not previous.get("legacy_unjournaled_publish")
    ):
        raise ValueError("Published checkpoint is missing its completion probe")
    step = 0
    start = time.monotonic()
    counts, sources, task_ids = Counter(), Counter(), set()
    elapsed_before = 0.0
    if rolling.exists():
        saved = torch.load(rolling, map_location="cpu", weights_only=False, mmap=True)
        if (
            json.loads(json.dumps(saved["contract"])) != contract
            or saved.get("fit_identity", identity) != identity
        ):
            raise ValueError("Resume protocol differs from original fit")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        scheduler.load_state_dict(saved["scheduler"])
        step = saved["step"]
        counts, sources, task_ids, fitted = saved["exposure"]
        torch.set_rng_state(saved["cpu_rng"])
        if args.device.startswith("cuda"):
            torch.cuda.set_rng_state(saved["gpu_rng"], device=args.device)
        elapsed_before = saved["elapsed"]
        del saved
    running = {
        "contract": contract,
        "status": "running",
        "fit_identity": identity,
        "resumed_at_update": step,
    }
    if path.exists():
        running["legacy_unjournaled_publish"] = True
    write_json(run_path, running)
    if not metrics.samefile(args.output):
        write_json(metrics / "run.json", running)
    attempt = time.time_ns()
    resumed_at = step
    for ep in range(epochs):
        order = list(roots.epoch(random.Random(args.seed + ep), weights))[:selected]  # noqa: S311
        group_counts = Counter((s, g) for _, s, g in order)
        source_groups = Counter(s for s, g in group_counts)
        mass = sum(weights[s] for s in source_groups)
        for window_index, offset in enumerate(range(0, len(order), args.batch)):
            n = ep * math.ceil(selected / args.batch) + window_index + 1
            if n <= step:
                continue
            batch = order[offset : offset + args.batch]
            root_weights = [
                weights[s] * len(order) / (mass * source_groups[s] * group_counts[s, g])
                for _, s, g in batch
            ]
            total_weight = len(batch)
            optimizer.zero_grad(set_to_none=True)
            losses = 0.0
            for (key, source, group), w in zip(batch, root_weights, strict=True):
                row = roots.row(key)
                group_name = f"{source}/{group}"
                quality, future = model.score(row["online"])
                loss, pairs = root_loss(
                    row,
                    quality,
                    future,
                    group_weights(args.seed, group_name),
                    model.cost_scale,
                    pair_weight=contract["pair_weight"],
                )
                fraction = w / total_weight
                (loss * fraction).backward()
                losses += loss.detach().item() * fraction
                counts.update(
                    roots=1, comparisons=pairs, demo_steps=int(row.get("demo") is not None)
                )
                if "weak" in row:
                    counts["known_evidence_actions"] += sum(
                        v is not None for v in row["weak"].values()
                    )
                else:
                    counts["measured_quality_actions"] += sum(
                        o["quality_observed"] for o in row["outcomes"]
                    )
                    counts["measured_cost_actions"] += sum(
                        o["future_cost_observed"] for o in row["outcomes"]
                    )
                sources[source] += 1
                task_ids.add(row["task_id"])
                fitted.add(group_name)
            grad = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            # Probe a real encoder parameter with nonzero gradient at its largest-gradient index.
            if n == 1:
                selected_param = next(
                    (name, p)
                    for name, p in model.reranker.named_parameters()
                    if p.ndim == 2 and "encoder.layer.0." in name and p.grad is not None
                )
                name, p = selected_param
                index = p.grad.abs().argmax()
                before = p.flatten()[index].item()
            optimizer.step()
            scheduler.step()
            if n == 1:
                after = p.flatten()[index].item()
                if before == after or p.grad.flatten()[index] == 0:
                    raise RuntimeError("Real backbone failed to update")
                write_json(
                    metrics / "encoder_update.json",
                    {
                        "parameter": name,
                        "value_before": before,
                        "value_after": after,
                        "gradient": p.grad.flatten()[index].item(),
                        "trainable": sum(p.numel() for p in model.parameters()),
                        "optimizer_parameters": sum(
                            p.numel() for g in optimizer.param_groups for p in g["params"]
                        ),
                    },
                )
            counts.update(
                input_tokens=model.counters["input_tokens"],
                padded_tokens=model.counters["padded_tokens"],
                encoder_calls=model.counters["forwards"],
            )
            for name in ("input_tokens", "padded_tokens", "forwards"):
                model.counters[name] = 0
            elapsed = elapsed_before + time.monotonic() - start
            entry = {
                "step": n,
                "attempt": attempt,
                "resumed_at_update": resumed_at,
                "epoch": ep + 1,
                "loss": losses,
                "grad_norm": grad.item(),
                "roots": counts["roots"],
                "wall_seconds": elapsed,
                "cuda_peak_bytes": torch.cuda.max_memory_allocated(args.device)
                if args.device.startswith("cuda")
                else None,
            }
            with (metrics / "curve.jsonl").open("a") as log:
                print(json.dumps(entry), file=log)
            if n % 20 == 0 or n == 1:
                print(json.dumps(entry), flush=True)
            if args.save_every and n % args.save_every == 0 and n < updates:
                tmp = rolling.with_suffix(".tmp")
                torch.save(
                    {
                        "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "fit_identity": identity,
                        "scheduler": scheduler.state_dict(),
                        "step": n,
                        "contract": contract,
                        "exposure": (counts, sources, task_ids, fitted),
                        "elapsed": elapsed,
                        "cpu_rng": torch.get_rng_state(),
                        "gpu_rng": torch.cuda.get_rng_state(device=args.device)
                        if args.device.startswith("cuda")
                        else None,
                    },
                    tmp,
                )
                tmp.replace(rolling)
    path = args.output / "checkpoint"
    model.eval()
    with torch.inference_mode():
        example = roots.row(order[-1][0])["online"]
        expected = torch.stack(model.score(example)).cpu()
    summary = {
        "contract": dict(contract, fitted_groups=sorted(fitted)),
        "roots": counts["roots"],
        "comparisons": counts["comparisons"],
        "paired_loss_comparisons": counts["comparisons"] if args.objective == "paired" else 0,
        "demo_steps": counts["demo_steps"],
        "known_evidence_actions": counts["known_evidence_actions"],
        "measured_quality_actions": counts["measured_quality_actions"],
        "measured_cost_actions": counts["measured_cost_actions"],
        "unique_tasks": len(task_ids),
        "groups_including_parent": len(fitted),
        "source_exposures": sources,
        "optimizer_updates": updates,
        "wall_seconds": elapsed,
        "cuda_peak_bytes": entry["cuda_peak_bytes"],
        "encoder_input_tokens": counts["input_tokens"],
        "encoder_padded_tokens": counts["padded_tokens"],
        "encoder_forward_batches": counts["encoder_calls"],
    }
    proof = dict(
        fit_identity=identity,
        contract=contract,
        summary=summary,
        online=example,
        device_type=torch.device(args.device).type,
        scores=expected.tolist(),
    )
    if path.exists():
        # A legacy trainer interrupted after publishing had no parity payload. Only
        # link it to this replay if every trained tensor agrees exactly.
        original = torch.load(path / "control.pt", map_location="cpu", weights_only=True, mmap=True)
        replayed = model.state_dict()
        if original.keys() != replayed.keys() or any(
            (original[k].dtype != v.dtype or not torch.equal(original[k], v.cpu()))
            for k, v in replayed.items()
        ):
            raise ValueError("Existing pre-journal weights differ from the finite replay")
        write_json(path / "fit_completion.json", proof)
        write_json(run_path, running)
    else:
        model.save(path, completion=proof)
    del optimizer, scheduler, model
    finish_verified(PretrainedControl, args.output, metrics, identity, contract, args.device)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--objective", choices=["evidence", "direct", "paired"], required=True)
    p.add_argument("--data", type=Path, nargs="+", required=True)
    p.add_argument(
        "--evidence-order-map",
        type=Path,
        help="Frozen native task and prefix order for a rebuilt evidence DB",
    )
    p.add_argument(
        "--evidence-master",
        type=Path,
        help="Relocated rebuilt native task index for order alignment",
    )
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--metrics", type=Path, help="Persistent directory for compact receipts")
    p.add_argument(
        "--backbone", type=Path, default=Path("/cra/milai-experiments/v13-qrag/staging/gte/base")
    )
    p.add_argument("--initialize", type=Path)
    p.add_argument("--probe", type=int, default=0, help="Explicitly diagnostic limited roots")
    p.add_argument("--epochs", type=int)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--device", default="cuda")
    p.add_argument("--object-batch", type=int, default=8)
    scale = p.add_mutually_exclusive_group()
    scale.add_argument(
        "--cost-scale-report", type=Path, help="Frozen TRAIN Host terminal prompt sizes"
    )
    scale.add_argument("--warm-packs", type=Path, help="Legacy median future-cost normalization")
    p.add_argument("--save-every", type=int, default=256)
    fit(p.parse_args())
