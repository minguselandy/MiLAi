"""Summarize actual saved-pool delivery controls, including navigation text exposure."""

from __future__ import annotations

import json
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text())


def costs(root: Path):
    stages = {}
    for path in sorted((root / "http").rglob("response.json")):
        parts = path.relative_to(root / "http").parts
        stage = ("judge" if "judge" in parts else "query_structure"
                 if parts[0] == "query-structure" else "reader_packet"
                 if "view" in parts else "reader")
        row = stages.setdefault(stage, {"responses": 0, "input_tokens": 0, "output_tokens": 0,
                                        "total_tokens": 0})
        usage = read(path)["usage"]
        row["responses"] += 1
        for target, key in (("input_tokens", "prompt_tokens"),
                            ("output_tokens", "completion_tokens"),
                            ("total_tokens", "total_tokens")):
            row[target] += usage[key]
    return stages


def ledger_delta(root: Path):
    before, after = [read(root / f"accounting-{point}.json") for point in ("start", "end")]
    return {"generation_requests": after["generation_requests"] - before["generation_requests"],
            **{kind: {key: after[kind][key] - before[kind][key]
                      for key in ("known_tokens", "charged_tokens", "unknown_usage")}
               for kind in ("generation", "embedding")}}


def main() -> None:
    lab = Path(__file__).resolve().parents[1]
    area = lab / "artifacts/innovation-v4"
    roots = {"alongside": area / "structure-delivery-v2/alongside",
             "structure_first": area / "structure-delivery-v2/first",
             "raw_first": area / "structure-raw-first-v1/raw-first"}
    summary = {"status": "CLOSED", "independent_histories": 1, "arms": {},
               "scope": "Sixteen exposed questions over identical saved source prefixes. "
                        "Cached arms reuse identical actual interpretations; raw-first excludes "
                        "them. Not independent formation, a full lifecycle or a formal holdout.",
               "source_versions": {"cached_arms": "72f1bf35", "raw_first": "5237b6e6"}}
    for name, root in roots.items():
        official = read(root / "evidence-summary.json")
        labels = {row["question_id"]: row["official_label"]
                  for row in read(root / "evidence-results.json")}
        rows = []
        for path in sorted((root / "predictions").rglob("complete.json")):
            key = path.parent.relative_to(root / "predictions")
            view = read(root / "http" / key / "memory-view.json")
            materials = read(root / "native" / key / "retrieval.json")["materials"]
            exposed, complete_excerpts = 0, 0
            for request in (root / "http" / key).rglob("request.json"):
                if not request.with_name("response.json").exists():
                    continue
                payload = json.loads(read(request)["messages"][1]["content"])
                for candidate in payload.get("candidates", []):
                    index = candidate["item_index"]
                    if materials[index]["kind"] != "original_source":
                        continue
                    content = [part["content"] for part in json.loads(materials[index]["text"])]
                    exposed += 1
                    complete_excerpts += all(text in candidate["excerpt"] for text in content)
            parts = key.parts
            rows.append({"session": int(parts[2]), "question": int(parts[4]),
                "official_label": labels[str(key)], "reader_calls": view["steps"],
                "opened_kinds": [materials[i]["kind"] for i in view["opened_indices"]],
                "declared_body_range_complete": view["range_coverage"]["complete"],
                "raw_catalog_entries_seen": exposed,
                "complete_raw_contents_in_catalog": complete_excerpts,
                "core_author_review": None if parts[2] == "2" and parts[4] == "3" else True})
        stages = costs(root)
        summary["arms"][name] = {"first_correct": official["correct"], "labels": official["labels"],
            "stages": stages, "reading_tokens": sum(v["total_tokens"] for k, v in stages.items()
                                                       if k != "judge"),
            "queries": rows, "formation_calls": 0, "retrieval_calls": 0}
    shared = area / "query-reuse-v2/incremental/MiLAi-memory-only/http/query-structure"
    receipts = [read(path)["usage"] for path in shared.rglob("response.json")]
    summary["original_shared_structure_cost"] = {
        "responses": len(receipts), "input_tokens": sum(r["prompt_tokens"] for r in receipts),
        "output_tokens": sum(r["completion_tokens"] for r in receipts),
        "total_tokens": sum(r["total_tokens"] for r in receipts),
        "accounting": "Paid in the original query-reuse run, shared once in this diagnostic; "
                      "not newly charged. A raw-only method does not require this construction."}
    summary["ledger_deltas"] = {name: ledger_delta(area / name) for name in (
        "structure-delivery-v2", "structure-raw-first-v1")}
    receipt_total = sum(stage["total_tokens"] for arm in summary["arms"].values()
                        for stage in arm["stages"].values())
    summary["receipt_ledger_difference"] = receipt_total - sum(
        delta["generation"]["known_tokens"] for delta in summary["ledger_deltas"].values())
    summary["author_review"] = {
        "coverage": "All48 full answers read; packets inventoried and three cache-only examples "
                    "inspected in full. All original sources and cached views reviewed earlier.",
        "navigation": "Structure-first opened only the cached view on all16 questions, but "
                      "its candidate catalog exposed all28 raw contents in full. Answers about "
                      "omitted night/battery facts therefore cannot establish cache sufficiency.",
        "alongside": ["Night eligibility is generalized to depend only on night training.",
                      "One cancellation is generalized to universal credential independence.",
                      "Final day-route answer wrongly says night information is unavailable, "
                      "despite full delivered raw evidence of completed night training."],
        "structure_first": ["Some answers infer female gender without source support.",
                            "Answers are shorter; packet vs free-form generation also differs."],
        "raw_first": ["Final unchanged-night answer also guesses female gender.",
                      "A one-word yes answers the current-night question using catalog information "
                      "outside its admitted old raw body; all prompt text must count as exposure."],
        "shared_ambiguity": "Session2/question3 conflates latest reported battery position with "
                            "freshly confirmed physical position. Preserve every official label "
                            "and mark author core judgement unresolved symmetrically."}
    summary["decision"] = (
        "No demonstrated graph/cache advantage. The simpler raw-first condition gives the best "
        "official score in this one exposed history. Body opening counts are not information "
        "isolation; common candidate excerpts expose all short sources. Keep cache construction "
        "cost separate, and test stronger controls/new histories before scaling a graph claim.")
    summary.update(independent_blind_review=False, official_scores_modified=False,
                   prior_misroute="innovation-v4-structure-delivery-v1-misroute.json",
                   full_goal_complete=False)
    output = lab / "data/manifests/innovation-v4-structure-delivery-comparison.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"arms": {k: {field: v[field] for field in ("first_correct", "reading_tokens")}
                               for k, v in summary["arms"].items()},
                      "shared_structure": summary["original_shared_structure_cost"],
                      "ledger_deltas": summary["ledger_deltas"],
                      "receipt_difference": summary["receipt_ledger_difference"]}, indent=2))


if __name__ == "__main__":
    main()
