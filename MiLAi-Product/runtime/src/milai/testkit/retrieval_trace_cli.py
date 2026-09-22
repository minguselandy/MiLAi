"""CLI for the published Product-10 retrieval trace testkit."""

from __future__ import annotations

import argparse
import json
import sys

from milai.testkit.retrieval_trace import (
    RetrievalTraceTestkitRequest,
    run_live_retrieval_trace,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-trace", action="store_true", help="emit Runtime owner facts")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    request = RetrievalTraceTestkitRequest.model_validate(payload)
    report = run_live_retrieval_trace(request, include_owner_trace=args.owner_trace)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
