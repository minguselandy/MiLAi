"""Run one declared full Host branch; original collection may already be the control arm."""
from __future__ import annotations

import argparse
import site
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captured", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--presentation", required=True,
                        choices=("current", "request_adjacent_metadata_v1"))
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--host-site-packages", type=Path)
    args = parser.parse_args()
    if args.host_site_packages:
        site.addsitedir(str(args.host_site_packages))
    from milai_lab.runners.frozen_host_message import replay_host_message

    result = replay_host_message(args.captured, args.output, args.presentation,
                                 source_version=args.source_version)
    print(result["status"], "generation calls", result.get("generation_calls"))
    if result["status"] != "COMPLETED":
        raise RuntimeError("Original branch failure retained; no automatic retry")


if __name__ == "__main__":
    main()
