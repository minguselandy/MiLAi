"""CLI for the published Product-10 retrieval trace testkit."""

from __future__ import annotations

import json
import sys

from milai.testkit.retrieval_trace import (
    RetrievalTraceTestkitRequest,
    run_live_retrieval_trace,
)


def main() -> None:
    payload = json.load(sys.stdin)
    request = RetrievalTraceTestkitRequest.model_validate(payload)
    report = run_live_retrieval_trace(request)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
