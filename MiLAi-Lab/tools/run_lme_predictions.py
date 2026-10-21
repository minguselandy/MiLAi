"""Run the complete supplied LME Small snapshot once; scoring is a separate closed phase."""
from __future__ import annotations

import argparse
import site
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--site-packages", action="append", type=Path, default=[],
                        help="Declared HTTP/Pillow sites; preserve the selected interpreter first")
    args = parser.parse_args()
    for path in args.site_packages:
        site.addsitedir(str(path))
    import torch

    from milai_lab.harness.artifact_io import entrypoint_settings, read_json
    from milai_lab.runners.lme_evaluation import predict_cohort

    settings = entrypoint_settings(read_json(args.config), "functional")
    torch.set_num_threads(settings["memory_control"].get("threads", 4))
    torch.backends.mha.set_fastpath_enabled(False)
    result = predict_cohort(args.config, args.snapshot, args.upstream, args.output,
                            source_version=args.source_version)
    print({"status": result["status"], "positions": result["planned_positions"]})


if __name__ == "__main__":
    main()
