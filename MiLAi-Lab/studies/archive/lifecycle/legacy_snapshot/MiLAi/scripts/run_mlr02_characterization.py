"""Write the single ML-R02 B0 characterization artifact."""

from __future__ import annotations

import json
import os
from pathlib import Path

from evals.ml_r02.characterization import characterize

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/ml_r02/ml-r02-20260831-001/baseline-results.json"


def main() -> int:
    first = characterize()
    second = characterize()
    if first != second:
        raise RuntimeError("ML-R02 B0 characterization is not deterministic")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_name(f".{OUTPUT.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, OUTPUT)
    print(json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

