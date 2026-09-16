"""Continue the sealed F/S plan using unchanged G artifacts and the repaired Product pin."""

from __future__ import annotations

import argparse

import run_v02_low_cost_reuse as study
from check_v02_payload_fidelity import ROOT

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("27016adc", "852ce960"), required=True)
    parser.add_argument("--arm", choices=("F", "S"), required=True)
    parser.add_argument("--future", required=True)
    args = parser.parse_args()
    study.ROOT = ROOT
    study.CONFIG = study.base.LAB / "configs/v02-fidelity-followup.json"
    study.run(args.case, args.arm, args.future)
