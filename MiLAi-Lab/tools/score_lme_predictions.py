"""Score retained LME predictions with native rules/rubrics and the original metered Judge."""
from __future__ import annotations

import argparse
import site
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--site-packages", action="append", type=Path, default=[])
    args = parser.parse_args()
    for path in args.site_packages:
        site.addsitedir(str(path))
    from milai_lab.runners.lme_evaluation import score_cohort

    result = score_cohort(args.predictions, args.output, source_version=args.source_version)
    print({"status": result["status"], "status_counts": result["status_counts"]})


if __name__ == "__main__":
    main()
