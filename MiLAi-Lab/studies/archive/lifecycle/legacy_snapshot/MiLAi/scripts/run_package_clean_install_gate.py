from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai.operations.packaging import run_package_clean_install_gate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/reports/UA-package-clean-install-gate-2026-08-17.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean-install the canonical MiLAi wheels")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_package_clean_install_gate(ROOT, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
