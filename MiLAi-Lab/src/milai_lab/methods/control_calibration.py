"""Fixed symbolic positive, partial, negative, failed and ambiguous review cases.

These are controlled calibration examples, not natural-task outcomes or an
independent human review. Expected fields are offline and never sent to a judge.
"""
# ruff: noqa: RUF001 -- Chinese calibration examples retain their native punctuation.
from __future__ import annotations

from typing import Any


def calibration_cases(protocol: str = "literal_v1") -> list[dict[str, Any]]:
    if protocol not in {"literal_v1", "missing_fact_v2"}:
        raise ValueError("Unknown calibration protocol")
    cases = []
    strata = ["complete", "incomplete", "incorrect", "failed", "unknown"]
    for index in range(200):
        stratum = strata[index % len(strata)]
        actor, amount = f"Entity-{index}", 1000 + 17 * index
        chinese = (index // len(strata)) % 2 == 0
        source = (f"{actor}的批准额度为{amount}积分，自2032年7月1日起生效。" if chinese else
                  f"{actor}'s approved limit is {amount} credits, effective 1 July 2032.")
        question = (f"{actor}的批准额度和生效日期分别是什么？" if chinese else
                    f"What are {actor}'s approved limit and effective date?")
        full_answer = (f"{amount}积分；2032年7月1日。" if chinese else
                       f"{amount} credits; 1 July 2032.")
        answer = full_answer
        expected = {"execution_status": "COMPLETED", "material_status": "sufficient",
                    "answer_status": "complete", "answer_support": "supported"}
        if stratum == "incomplete":
            answer = f"{amount}积分。" if chinese else f"{amount} credits."
            expected["answer_status"] = "incomplete"
        elif stratum == "incorrect":
            answer = (f"{amount + 500}积分；2032年7月1日。" if chinese else
                      f"{amount + 500} credits; 1 July 2032.")
            expected.update(answer_status="incorrect", answer_support="unsupported")
        elif stratum == "failed":
            answer = ""
            expected.update(execution_status="FAILED", answer_status="unknown",
                            answer_support="unknown")
        elif stratum == "unknown":
            # Conflicting reports without an ordering or authority rule cannot
            # establish the current value within this explicitly supplied world.
            source = (f"两份同日、同等权限的记录分别称{actor}的当前额度是{amount}积分和"
                      f"{amount + 500}积分，未说明哪份作废。" if chinese else
                      f"Two equally authoritative same-date records give {actor}'s current "
                      f"limit as {amount} and {amount + 500} credits. Neither is revoked.")
            question = (f"{actor}的当前额度是多少？" if chinese else
                        f"What is {actor}'s current limit?")
            answer = "无法确定。" if chinese else "Cannot determine."
            expected.update(material_status="unknown", answer_status="unknown",
                            answer_support="unknown")
            if protocol == "missing_fact_v2":
                # The assertion is neither established nor contradicted by this
                # evidence. Unlike a justified abstention, it cannot be a complete
                # supported answer. Do not treat absence as an explicit falsehood.
                source = (f"{actor}在文档团队任职。"
                          "记录没有提供其审批额度或生效日期。" if chinese else
                          f"{actor} works in the documentation team. The record does not "
                          "provide an approved limit or effective date.")
                question = (f"{actor}的批准额度和生效日期分别是什么？" if chinese else
                            f"What are {actor}'s approved limit and effective date?")
                answer = full_answer
                expected.update(material_status="insufficient", answer_support="unsupported")
        candidate = {"candidate": "candidate-A", "delivered_evidence": [{
            "label": "e0", "kind": "original_source", "evidence": [{
                "source": "s0", "role": "tool", "origin": "controlled_reference",
                "content": source}]}], "answer_status": expected["execution_status"],
            "answer": {"answer": answer, "explanation": "", "evidence": []}}
        sample = (f"calibration-unverified-{index:03d}"
                  if protocol == "missing_fact_v2" and stratum == "unknown"
                  else f"calibration-{index:03d}")
        cases.append({"sample_id": sample, "stratum": stratum,
            "language": "zh" if chinese else "en", "expected": expected,
            "payload": {"question": question, "offline_reference_annotations": [],
                        "candidates": [candidate]}})
    return cases


def four_axis_cases() -> list[dict[str, Any]]:
    """200 fixed cases; unreviewable means missing capture, not an empty actual packet."""
    import random

    cases: list[dict[str, Any]] = []
    for stratum, count in (("complete", 40), ("partial", 40), ("contradicted", 40),
                            ("unsupported", 40), ("failed", 20), ("unreviewable", 20)):
        for variant in range(count):
            index = len(cases)
            chinese = variant % 2 == 0
            actor, amount = f"Subject-{index}", 1500 + index * 19
            text = (f"{actor}的批准额度为{amount}积分，自2025年7月1日起生效。" if chinese else
                    f"{actor}'s approved limit is {amount} credits, effective 1 July 2025.")
            question = (f"{actor}的批准额度和生效日期是什么？" if chinese else
                        f"What are {actor}'s approved limit and effective date?")
            answer: str | None = (f"{amount}积分；2025年7月1日。" if chinese else
                      f"{amount} credits; 1 July 2025.")
            expected: dict[str, Any] = {"execution_status": "COMPLETED",
                "material_sufficiency": "sufficient", "answer_support": "supported",
                "answer_completeness": "complete", "primary_outcome": True}
            if stratum == "complete" and variant % 8 in {6, 7}:
                text = (f"{actor}从未获得批准，因此不存在批准额度或生效日期。" if chinese else
                        f"{actor} has never been approved, so no approved limit or effective "
                        "date exists.")
                answer = ("尚未批准，所以没有批准额度或生效日期。" if chinese else
                          "No approval has occurred, so there is no approved limit "
                          "or effective date.")
            if stratum == "partial":
                answer = f"{amount}积分。" if chinese else f"{amount} credits."
                expected.update(answer_completeness="incomplete", primary_outcome=False)
            elif stratum == "contradicted":
                answer = (f"{amount + 400}积分；2025年7月1日。" if chinese else
                          f"{amount + 400} credits; 1 July 2025.")
                expected.update(answer_support="unsupported", primary_outcome=False)
            elif stratum == "unsupported":
                text = (f"{actor}在文档团队任职。" if chinese else
                        f"{actor} works in the documentation team.")
                expected.update(material_sufficiency="insufficient", answer_support="unsupported",
                                primary_outcome=False)
            elif stratum == "failed":
                answer = None
                expected.update(execution_status="FAILED", answer_support="unknown",
                                answer_completeness="unknown", primary_outcome=False)
            evidence: Any = [{"label": "e0", "kind": "original_source", "evidence": [{
                "source": "s0", "role": "tool", "origin": "controlled_reference",
                "content": text}]}]
            if stratum == "unsupported" and variant % 4 < 2:
                evidence = []  # Known empty delivery is a measurable negative, not missing data.
            available = "complete"
            if stratum == "unreviewable":
                evidence, available = None, "missing_delivery_capture"
                expected.update(material_sufficiency="unknown", answer_support="unknown",
                                answer_completeness="unknown", primary_outcome=None)
            cases.append({"sample_id": f"axes3-{stratum}-{variant:02d}", "stratum": stratum,
                "language": "zh" if chinese else "en", "question": question,
                "execution_status": expected["execution_status"], "review_input_status": available,
                "delivered_evidence": evidence, "answer": answer, "expected": expected,
                "label_grade": "A_defined_symbolic_attributes_only",
                "scope": "Author-designed controlled calibration, not natural-task accuracy"})
    random.Random(17).shuffle(cases)  # noqa: S311 -- frozen presentation order
    return cases
