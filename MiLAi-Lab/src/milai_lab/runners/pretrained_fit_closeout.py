"""Exclusive fit ownership and checkpoint/receipt reconciliation."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path


def write_json(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, allow_nan=False))
    tmp.replace(path)


@contextmanager
def fit_owner(output, metrics):
    with ExitStack() as locks:
        directories = []
        for path in (output, metrics):
            path.mkdir(parents=True, exist_ok=True)
            if any(path.samefile(other) for other in directories):
                continue
            directories.append(path)
            handle = locks.enter_context((path / ".fit.lock").open("a"))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f"Another fit owns {path}") from exc
        # An already-running pre-lock trainer must also retain exclusive ownership.
        for path in directories:
            run = path / "run.json"
            if not run.exists():
                continue
            try:
                state = json.loads(run.read_text())
            except json.JSONDecodeError:
                if path.samefile(output):
                    raise
                # Only the canonical run declaration is authoritative.
                continue
            if state["status"] != "running" or "fit_identity" in state:
                continue
            for proc in Path("/proc").glob("[0-9]*"):
                if proc.name == str(os.getpid()):
                    continue
                with suppress(FileNotFoundError, PermissionError, ProcessLookupError):
                    argv = (proc / "cmdline").read_bytes().split(b"\0")
                    if b"milai_lab.runners.pretrained_control_train" not in argv:
                        continue
                    for flag in (b"--output", b"--metrics"):
                        if flag in argv:
                            named = Path(os.fsdecode(argv[argv.index(flag) + 1]))
                            if (proc / "cwd" / named).samefile(path):
                                raise RuntimeError(f"Pre-lock fit PID {proc.name} owns {path}")
        yield


def finish_verified(model_type, output, metrics, identity, contract, device):
    import torch

    directory = output / "checkpoint"
    proof = json.loads((directory / "fit_completion.json").read_text())
    if (
        proof["fit_identity"] != identity
        or proof["contract"] != contract
        or proof["device_type"] != torch.device(device).type
    ):
        raise ValueError("Published fit or parity device differs from the requested run")
    receipt = proof["summary"]
    if (
        receipt["optimizer_updates"] != contract["updates"]
        or receipt["roots"] != contract["epochs"] * contract["selected_per_epoch"]
    ):
        raise ValueError("The published package does not cover the finite training schedule")
    completed_contract = dict(receipt["contract"])
    fitted = completed_contract.pop("fitted_groups")
    if (
        {**completed_contract, "fitted_groups": contract["fitted_groups"]} != contract
        or not set(contract["fitted_groups"]).issubset(fitted)
        or sum(receipt["source_exposures"].values()) != receipt["roots"]
    ):
        raise ValueError("Completion receipt disagrees with its original fit declaration")
    reloaded = model_type.load(directory, device=device)
    with torch.inference_mode():
        actual = torch.stack(reloaded.score(proof["online"])).cpu()
    expected = torch.tensor(proof["scores"], dtype=torch.float32, device="cpu")
    torch.testing.assert_close(actual, expected, atol=0, rtol=0)
    result = dict(receipt, fit_identity=identity, status="completed", reload_scores_equal=True)
    write_json(output / "run.json", result)
    if not output.samefile(metrics):
        write_json(metrics / "run.json", result)
    (output / "resume.pt").unlink(missing_ok=True)
