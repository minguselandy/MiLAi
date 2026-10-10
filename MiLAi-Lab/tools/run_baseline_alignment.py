"""Prepare or explicitly execute aligned native memory backends on the shared ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import configure_runtime_directory, read_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("prepare", "predict", "score"), required=True)
    parser.add_argument("--backend", help="One declared backend; omitted means serial suite")
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    if args.runtime_dir is not None:
        configure_runtime_directory(args.runtime_dir)
    from milai_lab.runners.baseline_alignment import prepare_alignment, run_alignment_arm

    config = read_json(args.config)
    prepare_alignment(config, args.output)
    if args.phase == "prepare":
        return
    backends = [args.backend] if args.backend else config["alignment"]["backends"]
    for backend in backends:
        run_alignment_arm(config, args.output, backend, args.phase)


if __name__ == "__main__":
    main()
