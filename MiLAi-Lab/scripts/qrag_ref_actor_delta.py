"""Losslessly retain an untrained REF evaluation actor relative to the public E5 base."""

import argparse
import json
import os
from pathlib import Path

import torch
from safetensors import safe_open

PREFIX = {"policy": "state_embed.model.", "action_embed": "model.model."}


def assemble(delta, base):
    actor = {"format": "qrag_reference_actor", "alpha": delta["alpha"]}
    with safe_open(base, framework="pt", device="cpu") as pretrained:
        for tower in PREFIX:
            actor[tower] = dict(delta["stored"][tower])
            for name, base_key in delta["shared"][tower].items():
                actor[tower][name] = pretrained.get_tensor(base_key)
    return actor


def compact(checkpoint, base, delta_path):
    actor = torch.load(checkpoint, mmap=True, map_location="cpu", weights_only=True)
    if actor.get("format") != "qrag_reference_actor":
        raise ValueError("Expected the saved evaluation actor")
    delta = {
        "format": "qrag_e5_actor_delta_v1",
        "alpha": actor["alpha"],
        "stored": {},
        "shared": {},
    }
    with safe_open(base, framework="pt", device="cpu") as pretrained:
        base_keys = set(pretrained.keys())
        for tower, prefix in PREFIX.items():
            stored, shared = {}, {}
            for name, tensor in actor[tower].items():
                key = name.removeprefix(prefix)
                if key in base_keys:
                    base_tensor = pretrained.get_tensor(key)
                    if base_tensor.dtype == tensor.dtype and torch.equal(base_tensor, tensor):
                        shared[name] = key
                        continue
                stored[name] = tensor
            delta["shared"][tower] = shared
            delta["stored"][tower] = stored
    temp = delta_path.with_suffix(".part")
    torch.save(delta, temp)
    restored = assemble(torch.load(temp, weights_only=True), base)
    checks = 0
    for tower in PREFIX:
        if actor[tower].keys() != restored[tower].keys():
            raise ValueError("Actor tensor keys changed")
        for name, actual in actor[tower].items():
            expected = restored[tower][name]
            if actual.dtype != expected.dtype or not torch.equal(actual, expected):
                raise ValueError(f"Actor tensor differs at {tower}.{name}")
            checks += 1
    if actor["alpha"] != restored["alpha"] or actor["format"] != restored["format"]:
        raise ValueError("Actor control fields changed")
    os.replace(temp, delta_path)
    return {
        "method": "exact_base_tensor_references_with_literal_exceptions",
        "original_size": checkpoint.stat().st_size,
        "delta_size": delta_path.stat().st_size,
        "tensor_equality_checks": checks,
        "delta": str(delta_path),
        "base": str(base),
        "source": str(checkpoint),
        "shared": {k: len(v) for k, v in delta["shared"].items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["compact", "restore"])
    parser.add_argument("--actor", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--delta", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "compact":
        print(json.dumps(compact(args.actor, args.base, args.delta), indent=2))
    else:
        if args.actor.exists():
            raise FileExistsError(args.actor)
        delta = torch.load(args.delta, mmap=True, weights_only=True)
        if delta["format"] != "qrag_e5_actor_delta_v1":
            raise ValueError("Unexpected checkpoint format")
        temp = args.actor.with_suffix(".part")
        torch.save(assemble(delta, args.base), temp)
        os.replace(temp, args.actor)
