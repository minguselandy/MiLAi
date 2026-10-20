"""Synthetic native-metric checks; run in the isolated IR metrics environment."""
import copy
import io
import json
import math
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from milai_lab.datasets.instructir import (
    corpus_sources,
    delivered_document_ranking,
    evaluate_rankings,
    retrieval_request,
)


class InstructIRProtocolTests(unittest.TestCase):
    def test_public_fields_and_complete_document_text(self):
        row = {"_id": "offline-id", "text": "  exclude retired entries [SEP] same query  ",
               "answer": "private target"}
        self.assertEqual(retrieval_request(row), {"query": "same query",
                         "read_goal": {"purpose": "exclude retired entries"}})
        documents = [{"_id": "native-doc", "title": "Full title", "text": "全文\nNo clipping",
                      "label": "offline"}]
        sources = corpus_sources(documents)
        self.assertEqual(sources[0]["content"], "Full title\n全文\nNo clipping")
        self.assertEqual(sources[0]["original_event_id"], "native-doc")
        self.assertNotIn("label", sources[0])

    def test_micro_instance_mean_and_macro_worst_instruction_are_distinct(self):
        queries = [{"_id": "q1", "text": "first [SEP] shared"},
                   {"_id": "q2", "text": "second [SEP] shared"},
                   {"_id": "q3", "text": "third [SEP] other"}]
        qrels = {"q1": {"d1": 1}, "q2": {"d2": 1}, "q3": {"d3": 1}}
        results = {"q1": {"d1": 3.0}, "q2": {"wrong": 3.0, "d2": 2.0}, "q3": {"d3": 3.0}}
        before = copy.deepcopy(results)
        report = evaluate_rankings(queries, qrels, results, cutoffs=(1, 3))
        self.assertEqual(results, before)
        self.assertEqual(report["query_groups"], 2)
        metrics = report["metrics"]
        self.assertAlmostEqual(metrics["cluster_NDCG@1_avg"], 2 / 3)
        self.assertAlmostEqual(metrics["cluster_NDCG@1_min_avg"], 0.5)
        self.assertAlmostEqual(metrics["cluster_NDCG@3_min_avg"], (1 / math.log2(3) + 1) / 2)
        self.assertAlmostEqual(metrics["cluster_MAP@3_avg"], 2.5 / 3)
        self.assertAlmostEqual(metrics["cluster_Recall@3_avg"], 1.0)
        self.assertAlmostEqual(metrics["cluster_P@3_avg"], 1 / 3)

    def test_missing_and_empty_results_keep_the_full_denominator(self):
        queries = [{"_id": f"q{i}", "text": f"instruction{i}[SEP]same"} for i in range(3)]
        qrels = {f"q{i}": {f"d{i}": 1} for i in range(3)}
        report = evaluate_rankings(queries, qrels, {"q0": {"d0": 1.0}, "q1": {}}, cutoffs=(1,))
        self.assertEqual(report["missing_rankings"], ["q2"])
        self.assertEqual(report["empty_rankings"], 2)
        self.assertAlmostEqual(report["metrics"]["cluster_NDCG@1_avg"], 1 / 3)
        self.assertEqual(report["metrics"]["cluster_NDCG@1_min_avg"], 0.0)

    def test_native_identical_id_rule_does_not_mutate_the_run(self):
        queries = [{"_id": "same", "text": "instruction[SEP]query"}]
        qrels = {"same": {"same": 1}}
        run = {"same": {"same": 1.0}}
        filtered = evaluate_rankings(queries, qrels, run, cutoffs=(1,))
        retained = evaluate_rankings(queries, qrels, run, cutoffs=(1,), ignore_identical_ids=False)
        self.assertEqual(filtered["metrics"]["cluster_NDCG@1_avg"], 0.0)
        self.assertEqual(retained["metrics"]["cluster_NDCG@1_avg"], 1.0)
        self.assertEqual(run, {"same": {"same": 1.0}})

    def test_ranking_uses_delivered_ranges_and_only_explicit_view_citations(self):
        refs = [{"snapshot_id": "actual", "collection": "materials", "item_index": i}
                for i in range(3)]
        materials = [
            {"source_ranges": [{"source_ref": "source-a", "start": 2, "end": 8}]},
            {"source_bindings": {"cited": {"source_ref": "source-b"},
                                 "duplicate": {"source_ref": "source-a"},
                                 "unused": {"source_ref": "source-not-returned"}}},
            {"source_ranges": [{"source_ref": "source-a", "start": 8, "end": 12}]},
        ]
        packet = {"evidence": [
            {"kind": "original_source", "ref": refs[0], "evidence": [{"range": [2, 8]}]},
            {"kind": "query_structure", "ref": refs[1], "interpretation": {"nodes": {
                "n0": {"text": "Literal delivered claim", "evidence": ["cited", "duplicate"]}}}},
            {"kind": "original_source", "ref": refs[2], "evidence": [{"range": [8, 12]}]},
        ]}
        before = copy.deepcopy(packet)
        result = delivered_document_ranking(packet,
            lambda ref: materials[ref["item_index"]],
            {"source-a": "doc-a", "source-b": "doc-b", "source-not-returned": "not-ranked"})
        self.assertEqual(result["ranking"], {"doc-a": 1.0, "doc-b": .5})
        self.assertEqual([r["basis"] for r in result["entries"]],
                         ["delivered_original_range", "delivered_interpretation_citation"])
        self.assertEqual(packet, before)

    def test_unavailable_packets_do_not_gain_document_credit(self):
        packet = {"evidence": [{"kind": "original_source", "visibility": "unavailable"},
                               {"kind": "query_structure", "visibility": "unavailable"}]}
        result = delivered_document_ranking(
            packet, lambda _: self.fail("No material was delivered"), {})
        self.assertEqual(result["ranking"], {})

    def test_changed_ranges_and_unknown_material_kinds_are_not_silently_scored(self):
        packet = {"evidence": [{"kind": "original_source", "ref": {},
                                "evidence": [{"range": [0, 3]}]}]}
        with self.assertRaisesRegex(ValueError, "ranges differ"):
            delivered_document_ranking(packet, lambda _: {
                "source_ranges": [{"source_ref": "s", "start": 0, "end": 4}]}, {"s": "doc"})
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            delivered_document_ranking({"evidence": [{"kind": "unknown"}]}, lambda _: {}, {})

    def test_offline_score_cli_keeps_missing_queries_and_marks_partial_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release, run = root / "release", root / "run"
            (release / "qrels").mkdir(parents=True)
            run.mkdir()
            queries = [{"_id": "q0", "text": "first[SEP]shared"},
                       {"_id": "q1", "text": "second[SEP]shared"}]
            (release / "queries.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queries))
            (release / "qrels/test.jsonl").write_text("".join(json.dumps({
                "query-id": q["_id"], "corpus-id": "doc", "score": 1}) + "\n" for q in queries))
            (run / "query-cohort.json").write_text(json.dumps({"queries": ["q0", "q1"]}))
            (run / "rankings.json").write_text(json.dumps({"q0": {"doc": 1.0}}))
            (run / "driver.json").write_text(json.dumps({"status": "FAILED", "completed": [{}],
                "ranking_protocol": "synthetic only"}))
            script = Path(__file__).resolve().parents[2] / "tools/score_host_intent_instructir.py"
            output = root / "scores.json"
            with patch("sys.argv", [str(script), str(release), str(run), str(output)]), (
                redirect_stdout(io.StringIO())
            ):
                runpy.run_path(str(script), run_name="__main__")
            report = json.loads(output.read_text())
            self.assertFalse(report["full_cohort_closed"])
            self.assertEqual(report["missing_rankings"], ["q1"])
            self.assertEqual(report["queries"], 2)
            self.assertEqual(report["metrics"]["cluster_NDCG@1_avg"], .5)
            self.assertEqual(report["metrics"]["cluster_NDCG@1_min_avg"], 0.0)


if __name__ == "__main__":
    unittest.main()
