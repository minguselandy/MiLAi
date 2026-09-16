"""Identity-pinned entrypoint for the official LongMemEval-V2 harness."""

from __future__ import annotations

import json

from evals.paper.lme_v2_adapter import register_with_official_harness


def main() -> None:
    identity = register_with_official_harness()
    print(
        "[milai-paper] registered LongMemEval-V2 adapter "
        + json.dumps(
            {
                "commit": identity["commit"],
                "paper_data_opened": identity["paper_data_opened"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    from evaluation.harness import (  # type: ignore[import-not-found]
        main as official_main,
    )

    official_main()


if __name__ == "__main__":
    main()
