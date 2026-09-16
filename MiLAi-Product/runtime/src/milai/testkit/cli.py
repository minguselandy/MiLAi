"""CLI for the published read-only Context replay testkit."""

from __future__ import annotations

import json
import sys

from milai.testkit.context_replay import ContextTestkitRequest, run_live_context_replay


def main() -> None:
    payload = json.load(sys.stdin)
    request = ContextTestkitRequest.model_validate(payload)
    report = run_live_context_replay(request)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
