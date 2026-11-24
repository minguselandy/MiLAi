"""Storage-aware, exact 12k QR continuation state."""

from __future__ import annotations

import errno
import os

import torch

from milai_lab.datasets.memory_control_report import read_json, write_json


def tensor_bytes(item):
    if torch.is_tensor(item):
        return item.numel() * item.element_size()
    if isinstance(item, dict):
        return sum(tensor_bytes(v) for v in item.values())
    if isinstance(item, (list, tuple)):
        return sum(map(tensor_bytes, item))
    return 0


def free_bytes(path):
    info = os.statvfs(path)
    blocks = info.f_bfree if os.geteuid() == 0 else info.f_bavail
    return info.f_frsize * blocks


def save_resume(run, checkpoint, model, target, optimizer, contract):
    path = run / "resume-12000.pt"
    if path.exists():
        return
    part = path.with_suffix(".part")
    reserve = 4 * 1024**3
    payload = dict(
        format="qrag_milai_online_resume_v1",
        contract=contract,
        training=read_json(checkpoint / "training.json"),
        architecture=read_json(checkpoint / "controller.json"),
        probe=read_json(checkpoint / "score_probe.json"),
        target=target.state_dict(),
        optimizer=optimizer.state_dict(),
        rng_cpu=torch.get_rng_state(),
        rng_gpu=torch.cuda.get_rng_state(model.device) if model.device.type == "cuda" else None,
    )
    available = free_bytes(run)
    required = tensor_bytes(payload) + 4 * 1024**2
    actor = model.state_dict()
    actor_size = tensor_bytes(actor)
    if available >= required + actor_size + reserve:
        payload["actor"] = actor
        required += actor_size
    info = dict(
        estimated_bytes=required,
        initial_free_bytes=available,
        reserve_bytes=reserve,
        includes_actor="actor" in payload,
        checkpoint=str(checkpoint),
    )
    if available < required + reserve:
        write_json(
            run / "resume-storage.json", dict(info, status="replay_required_insufficient_space")
        )
        return
    try:
        with part.open("w+b") as stream:
            # Reserve the particular artifact and leave shared-service headroom.
            os.posix_fallocate(stream.fileno(), 0, required)
            if free_bytes(run) < reserve:
                raise OSError(errno.ENOSPC, "shared reservation unavailable")
            torch.save(payload, stream)
            stream.truncate(stream.tell())
            stream.flush()
            os.fsync(stream.fileno())
        loaded = torch.load(part, map_location="cpu", mmap=True, weights_only=True)
        if (
            loaded["contract"] != contract
            or loaded["training"] != payload["training"]
            or not loaded["optimizer"]["state"]
            or set(loaded["target"]) != set(payload["target"])
        ):
            raise ValueError("Incomplete QR continuation archive")
        del loaded
        part.replace(path)
    except OSError as exc:
        if exc.errno not in (errno.ENOSPC, errno.EDQUOT):
            raise
        write_json(
            run / "resume-storage.json", dict(info, status="replay_required_storage_changed")
        )
        return
    finally:
        part.unlink(missing_ok=True)
    write_json(run / "resume-storage.json", dict(info, status="saved", bytes=path.stat().st_size))


def restore_resume(run, directory, model, target, optimizer, contract, receipts):
    path = run / "resume-12000.pt"
    if not path.is_file():
        return None
    saved = torch.load(path, map_location="cpu", mmap=True, weights_only=True)
    binding = saved["training"]
    if (
        saved["format"] != "qrag_milai_online_resume_v1"
        or saved["contract"] != contract
        or binding["calls"] != 12000
        or not binding["fitted_groups"]
        or binding["dataset_run_id"] != contract["dataset_run_id"]
    ):
        raise ValueError("QR resume archive differs from the immutable training contract")
    if not directory.exists() and "actor" not in saved:
        return None
    if not directory.exists() and "actor" in saved:
        tmp = directory.with_name(directory.name + ".restore")
        tmp.mkdir(parents=True, exist_ok=True)
        torch.save(saved["actor"], tmp / "control.pt")
        for name, key in (
            ("controller", "architecture"),
            ("training", "training"),
            ("score_probe", "probe"),
        ):
            write_json(tmp / (name + ".json"), saved[key])
        tmp.rename(directory)
    if any(
        read_json(directory / (file + ".json")) != saved[key]
        for file, key in (
            ("training", "training"),
            ("controller", "architecture"),
            ("score_probe", "probe"),
        )
    ):
        raise ValueError("Restored QR state does not match the registered 12k evaluation actor")
    actor = (
        saved["actor"]
        if "actor" in saved
        else torch.load(directory / "control.pt", map_location="cpu", mmap=True, weights_only=True)
    )
    model.load_state_dict(actor)
    target.load_state_dict(saved["target"])
    steps = [int(item["step"]) for item in saved["optimizer"]["state"].values() if "step" in item]
    if not steps or max(steps) != binding["optimizer_updates"]:
        raise ValueError("Stored Adam step differs from the registered 12k update")
    optimizer.load_state_dict(saved["optimizer"])
    probe = saved["probe"]
    from milai_lab.runners.control_policy_iteration import read_gzip

    receipt = read_gzip(receipts.path(probe["receipt_id"]))
    online = receipt["transitions"][probe["transition_index"]]["online"]
    with torch.inference_mode():
        score = model.net(online, probe["utility_lambda"]).cpu()
    torch.testing.assert_close(
        score, torch.tensor(probe["saved_live_scores"]), rtol=1e-6, atol=1e-7
    )
    torch.set_rng_state(saved["rng_cpu"])
    if saved["rng_gpu"] is not None:
        torch.cuda.set_rng_state(saved["rng_gpu"], model.device)
    return binding
