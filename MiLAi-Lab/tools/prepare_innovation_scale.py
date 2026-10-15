"""Prepare controlled unrelated-history sizes for the normal HaluMem lifecycle runner.

The three sizes share one authored target scenario; they are not three independent
users. Only declared history size changes. References remain evaluator-only.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

INITIAL = (
    "Aster archive allows consultation of uncatalogued folios only after orientation and with "
    "either a current archive badge or a valid signed guest voucher. Mira has completed "
    "orientation. Mira's archive badge has expired, but the signed guest voucher is valid. "
    "The reference index is in the white drawer; its location does not determine access."
)
UPDATE = (
    "From 2037-01-03, signed guest vouchers cease to be an access route for Aster's uncatalogued "
    "folios, even while a voucher is valid. The archive badge route still requires orientation. "
    "Mira's badge remains expired and the voucher remains valid. Orientation and the reference "
    "index location have not changed."
)
UNRELATED = (
    "The Aster reference index has moved from the white drawer to the black cabinet. "
    "This move changes no access rule, Mira's credentials or orientation record."
)
INITIAL_QA = [
    ("Can Mira consult Aster's uncatalogued folios under the reported rules and credentials?",
     "Yes: orientation is completed and the valid guest voucher supplies an allowed route."),
    ("Which allowed credential route does Mira have for the uncatalogued folios?",
     "The valid signed guest voucher; the archive badge is expired."),
    ("Does the expired archive badge alone remove Mira's reported access?",
     "No. The valid voucher route remains, and orientation is completed."),
    ("Does holding a valid voucher remove Aster's orientation requirement?",
     "No. Orientation is a common prerequisite for both routes."),
    ("What is Mira's reported orientation status?", "Mira has completed orientation."),
    ("What is the reference index's latest reported location?", "The white drawer."),
    ("Must both credential types be valid before a trained visitor can consult the folios?",
     "No. Orientation and either valid credential route suffice."),
    ("Is the reference index location a condition of folio access?", "No."),
    ("Can Mira use the archive badge route on the reported facts?", "No; the badge is expired."),
    ("Does Mira need a renewed badge while the signed voucher route is still allowed and valid?",
     "No, because orientation is completed and the valid voucher supplies an alternative route."),
    ("Which of Mira's credential statuses are explicitly reported?",
     "The archive badge is expired; the signed guest voucher is valid."),
    ("What shared prerequisite would still be required if Mira later obtained a valid badge?",
     "Completed orientation."),
    ("Where does the latest report say to find Aster's reference index?", "The white drawer."),
    ("Does the report establish that Mira has satisfied the common prerequisite?",
     "Yes. Orientation is completed."),
    ("Is Mira's current voucher described as awaiting verification?", "No; it is reported valid."),
    ("State the currently usable route for Mira without treating both credentials as required.",
     "Completed orientation plus the valid signed guest voucher."),
]
UPDATE_QA = [
    ("Can Mira still consult the uncatalogued folios under the January 3 rules and reported state?",
     "No. The voucher route is removed and Mira's remaining badge route has an expired badge."),
    ("Did removing the voucher access route mean Mira's voucher itself became invalid?",
     "No. The voucher is still valid but no longer grants folio access."),
    ("Did the January 3 policy change undo Mira's orientation completion?", "No."),
    ("What is the reference index's latest reported location after the policy change?",
     "The white drawer."),
]
UNRELATED_QA = [
    ("Where is the reference index according to the latest report?", "The black cabinet."),
    ("Did moving the index restore Mira's folio access?", "No."),
    ("Which access route remains permitted by policy, and what prevents Mira from using it?",
     "The badge route with orientation remains permitted, but Mira's badge is expired."),
    ("Did the move change the validity of Mira's voucher or the completed orientation?",
     "No. The voucher remains valid and orientation remains completed."),
]


def session(text: str, when: datetime, pairs=(), evidence=(), *, query_time=None):
    return {
        "start_time": when.strftime("%b %d, %Y, %H:%M:%S"),
        "end_time": (query_time or when).strftime("%b %d, %Y, %H:%M:%S"),
        "dialogue": [{"role": "user", "content": text, "timestamp": when.isoformat()}],
        "memory_points": [],
        "questions": [{"question": question, "answer": answer,
                       "question_type": "controlled_scale_reuse",
                       "evidence": [{"memory_content": body} for body in evidence]}
                      for question, answer in pairs],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 5000])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat("2037-01-01T09:00:00+08:00")
    manifest = {"scenario_count": 1, "independent_history_claim": False, "sizes": [],
                "reuse_prefixes": [1, 4, 16], "queries_per_size": 24,
                "scope": "Controlled unrelated-source scale, one target scenario. "
                         "Same query clocks and target sources at every size; no formal holdout.",
                "parameter_updates": 0, "model_calls": 0}
    for size in args.sizes:
        sessions = [session(INITIAL, start)]
        for index in range(1, size):
            text = (
                f"Depot inventory note D{index:05d}: sealed crate C{index:05d} is on rack "
                f"R{index % 97:02d}. Its inventory label is amber and the packing list has two "
                "copies. This depot note records packaging and storage only. The inspection "
                "record says the seal was intact at the reported time; no later inspection "
                "or shipment is asserted."
            )
            sessions.append(session(text, start + timedelta(seconds=index)))
        sessions[-1]["end_time"] = "Jan 02, 2037, 09:00:00"
        sessions[-1]["questions"] = session("", start, INITIAL_QA, [INITIAL])["questions"]
        sessions.append(session(UPDATE, start + timedelta(days=2), UPDATE_QA, [INITIAL, UPDATE]))
        sessions.append(session(UNRELATED, start + timedelta(days=3), UNRELATED_QA,
                                [INITIAL, UPDATE, UNRELATED]))
        owner = f"innovation-scale-aster-{size}"
        path = args.output / f"aster-{size}.jsonl"
        path.write_text(json.dumps({"uuid": owner, "sessions": sessions},
                                   ensure_ascii=False) + "\n")
        manifest["sizes"].append({"initial_sources": size, "total_sources": size + 2,
                                  "owner": owner, "path": str(path), "questions": 24})
    (args.output / "preparation.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
