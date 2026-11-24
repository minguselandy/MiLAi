"""Losslessly retain FP32 REF actors relative to the public E5 base."""

import argparse
import json
import os
import zipfile
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


CHUNK_BYTES = 4 * 1024 * 1024


def raw_bytes(tensor):
    return tensor.detach().contiguous().reshape(-1).view(torch.uint8)


def write_xor_archive(destination, actor, pretrained):
    entries = []
    keys = set(pretrained.keys())
    for tower, prefix in PREFIX.items():
        for name, tensor in actor[tower].items():
            key = name.removeprefix(prefix)
            base = pretrained.get_tensor(key) if key in keys else None
            if base is not None and (base.shape != tensor.shape or base.dtype != tensor.dtype):
                base = None
            record = {
                "tower": tower,
                "name": name,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype).removeprefix("torch."),
                "base_key": key if base is not None else None,
            }
            entries.append(record)
            raw = raw_bytes(tensor)
            source = raw_bytes(base) if base is not None else None
            if source is not None and torch.equal(raw, source):
                record["mode"] = "base"
                continue
            record["mode"] = "xor" if source is not None else "literal"
            record["member"] = f"tensors/{len(entries)}"
            with destination.open(record["member"], "w", force_zip64=True) as out:
                for start in range(0, raw.numel(), CHUNK_BYTES):
                    part = raw[start : start + CHUNK_BYTES]
                    if source is not None:
                        part = torch.bitwise_xor(part, source[start : start + CHUNK_BYTES])
                    out.write(memoryview(part.numpy()))
    destination.writestr(
        "manifest.json",
        json.dumps(
            {
                "format": "qrag_e5_xor_v1",
                "actor_format": actor["format"],
                "alpha": actor["alpha"],
                "base_repository": "intfloat/multilingual-e5-large",
                "base_revision": "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3",
                "entries": entries,
            }
        ),
    )


def read_xor_archive(path, base_path, expected=None):
    """Verify reconstructed chunks against the actual actor, or materialize a restore on CPU."""
    with (
        zipfile.ZipFile(path) as stored,
        safe_open(base_path, framework="pt", device="cpu") as base,
    ):
        manifest = json.loads(stored.read("manifest.json"))
        if manifest["format"] != "qrag_e5_xor_v1":
            raise ValueError("Unexpected actor archive version")
        restored = {
            "format": manifest["actor_format"],
            "alpha": manifest["alpha"],
            **{k: {} for k in PREFIX},
        }
        seen = {k: set() for k in PREFIX}
        modes = {"base": 0, "literal": 0, "xor": 0}
        if expected is not None and any(expected[k] != restored[k] for k in ("format", "alpha")):
            raise ValueError("Actor metadata mismatch")
        for row in manifest["entries"]:
            tower, name, mode = row["tower"], row["name"], row["mode"]
            if name in seen[tower]:
                raise ValueError("Duplicate tensor name")
            seen[tower].add(name)
            modes[mode] += 1
            dtype = getattr(torch, row["dtype"])
            target = (
                expected[tower][name]
                if expected is not None
                else torch.empty(row["shape"], dtype=dtype, device="cpu")
            )
            if list(target.shape) != row["shape"] or target.dtype != dtype:
                raise ValueError("Actor tensor metadata mismatch")
            raw = raw_bytes(target)
            source = raw_bytes(base.get_tensor(row["base_key"])) if row["base_key"] else None
            if mode == "base":
                if source is None:
                    raise ValueError("Missing public base tensor")
                if expected is not None:
                    if not torch.equal(raw, source):
                        raise ValueError(f"Base tensor mismatch: {tower}.{name}")
                else:
                    raw.copy_(source)
            else:
                with stored.open(row["member"]) as member:
                    for start in range(0, raw.numel(), CHUNK_BYTES):
                        ref = raw[start : start + CHUNK_BYTES]
                        block = bytearray(member.read(ref.numel()))
                        if len(block) != ref.numel():
                            raise ValueError("Truncated actor tensor")
                        part = torch.frombuffer(block, dtype=torch.uint8)
                        if mode == "xor":
                            if source is None:
                                raise ValueError("Missing XOR base")
                            part.bitwise_xor_(source[start : start + CHUNK_BYTES])
                        if expected is not None:
                            if not torch.equal(part, ref):
                                raise ValueError(f"Actor chunk mismatch: {tower}.{name}")
                        else:
                            ref.copy_(part)
                    if member.read(1):
                        raise ValueError("Oversized actor tensor")
            if expected is None:
                restored[tower][name] = target
        if expected is not None and any(seen[k] != set(expected[k]) for k in PREFIX):
            raise ValueError("Incomplete reconstructed actor")
        return restored, modes


def compact_trained(checkpoint, base_path, output):
    original = torch.load(checkpoint, mmap=True, map_location="cpu", weights_only=True)
    if original["format"] != "qrag_reference_actor":
        raise ValueError("Unexpected actor checkpoint")
    tmp = output.with_suffix(".part")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as dest:
            with safe_open(base_path, framework="pt", device="cpu") as base:
                write_xor_archive(dest, original, base)
        _, counts = read_xor_archive(tmp, base_path, expected=original)
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    return {
        "method": "chunkwise_xor_deflate_with_literal_nonbase_tensors",
        "source": str(checkpoint),
        "base": str(base_path),
        "delta": str(output),
        "original_size": checkpoint.stat().st_size,
        "delta_size": output.stat().st_size,
        "exact_tensors_verified": sum(counts.values()),
        "tensor_modes": counts,
        "chunk_bytes": CHUNK_BYTES,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["compact", "restore"])
    parser.add_argument("--actor", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--delta", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "compact":
        encode = compact_trained if args.delta.suffix == ".zip" else compact
        print(json.dumps(encode(args.actor, args.base, args.delta), indent=2))
    else:
        if args.actor.exists():
            raise FileExistsError(args.actor)
        if args.delta.suffix == ".zip":
            restored, _ = read_xor_archive(args.delta, args.base)
        else:
            delta = torch.load(args.delta, mmap=True, weights_only=True)
            if delta["format"] != "qrag_e5_actor_delta_v1":
                raise ValueError("Unexpected checkpoint format")
            restored = assemble(delta, args.base)
        temp = args.actor.with_suffix(".part")
        torch.save(restored, temp)
        os.replace(temp, args.actor)
