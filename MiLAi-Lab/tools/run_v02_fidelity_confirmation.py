"""Run the prespecified other-history confirmation with the same exact-note candidate."""

from __future__ import annotations

import argparse

import run_v02_low_cost_reuse as study
from check_v02_payload_fidelity import ROOT

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("ba358f49", "cf22b7bf"), required=True)
    parser.add_argument("--arm", choices=("G", "F", "S"), required=True)
    parser.add_argument("--future")
    args = parser.parse_args()
    study.ROOT = ROOT
    study.CONFIG = study.base.LAB / "configs/v02-fidelity-confirmation.json"
    study.PLAN = study.base.LAB / "studies/active/MILA_V02_FIDELITY_CONFIRMATION_C.json"
    study.run(args.case, args.arm, args.future)
