"""Set an explicit V13 resource phase after the previous gated units drain."""

import argparse
import json
from pathlib import Path

from milai_lab.runners.v13_phase import UNITS, activate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allow", nargs="*", required=True, choices=sorted(UNITS))
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    print(json.dumps(activate(args.root, args.allow, parallel=args.parallel, reason=args.reason)))
