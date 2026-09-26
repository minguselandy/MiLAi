"""Inspect read-only v19 reconstruction records and B1 factual sidecar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.methods.on_demand_reconstruction.metrics import summarize_trace
from run_langmem_provenance import TABLES, _read_sidecar, _summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--table", choices=sorted(TABLES))
    parser.add_argument("--filter", action="append", default=[])
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--resolve-body", action="store_true")
    parser.add_argument("--resolve-request", action="store_true")
    args = parser.parse_args()
    result: object
    if args.table:
        if args.sidecar is None:
            parser.error("--table requires --sidecar")
        result = _read_sidecar(args.sidecar, args.table, args.filter, latest=args.latest,
                               resolve_body=args.resolve_body,
                               resolve_request=args.resolve_request)
    elif args.trace is not None:
        result = summarize_trace(args.trace)
    elif args.sidecar is not None:
        result = _summarize(args.sidecar)
    else:
        parser.error("--trace or --sidecar is required")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
