"""Materialize the preregistered label-free Memora paper strata."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evals.paper.datasets.memora import build_label_free_inputs

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = Path("/cra/memory/mx_memory/benchmarks/Memora/data")
DEFAULT_OUTPUT = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
STRATA = (
    ("weekly", "academic_researcher"),
    ("monthly", "financial_analyst"),
    ("quarterly", "software_engineer"),
)


class PrepareMemoraError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PrepareMemoraError("Memora label-free input artifact is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(
            value, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def run(*, data_root: Path, output: Path) -> dict[str, object]:
    value = build_label_free_inputs(data_root=data_root, strata=STRATA)
    _atomic_json_once(output, value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = run(data_root=args.data_root.resolve(), output=args.output.resolve())
    print(
        json.dumps(
            {
                "case_count": value["case_count"],
                "cohort_count": value["cohort_count"],
                "output": str(args.output.resolve()),
                "paper_labels_opened": value["paper_labels_opened"],
                "status": "PASS",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
