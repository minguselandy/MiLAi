"""Synthetic native-metric checks; run in the isolated IR metrics environment."""
import copy
import math
import unittest

from milai_lab.datasets.instructir import corpus_sources, evaluate_rankings, retrieval_request


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


if __name__ == "__main__":
    unittest.main()
