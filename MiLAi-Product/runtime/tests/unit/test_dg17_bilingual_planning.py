from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import infer_operator_family
from milai.domain.query_task_contract import ParseDisposition

REFERENCE = datetime(2023, 3, 27, 23, 35, tzinfo=UTC)


@pytest.mark.parametrize(
    ("english", "chinese", "family"),
    [
        (
            "What game did I finally beat last weekend?",
            "我上周末最终打败了什么游戏?",
            "LOOKUP",
        ),
        (
            "Which espresso machine did I get 10 days ago?",
            "我十天前买了哪台意式咖啡机?",
            "TEMPORAL_FILTER",
        ),
        (
            "Which happened earlier, planting the cedar tree or painting the shed?",
            "种下雪松和粉刷棚子, 哪件事发生得更早?",
            "TEMPORAL_ORDER",
        ),
        (
            "What is the elapsed time in days from the robotics demo to the choir concert?",
            "从机器人演示到合唱音乐会相隔多少天?",
            "TEMPORAL_DISTANCE",
        ),
        (
            "How many times did I bake bread in the past two weeks?",
            "过去两周我烤面包多少次?",
            "COUNT",
        ),
        (
            "How much did I pay per ceramic planter?",
            "我买每个陶瓷花盆花了多少钱?",
            "DIVIDE",
        ),
        (
            "Using both sessions, combine the evidence about my final city choice.",
            "结合两个会话中的证据, 我最后选择了什么城市?",
            "MULTI_JOIN",
        ),
    ],
)
def test_q3b_first_operator_batch_has_english_and_chinese_plans(
    english: str, chinese: str, family: str
) -> None:
    compiler = MemoryQueryCompiler()

    for query in (english, chinese):
        plan = compiler.compile(query, reference_time=REFERENCE)
        assert plan.schema_version == "memory-query-ir-v0.2"
        assert plan.mode != "AMBIGUOUS", query
        assert infer_operator_family(plan) == family
        assert plan.planner_trace.source == "DETERMINISTIC"
        assert plan.planner_trace.auxiliary_model_calls == 0
        assert plan.requirements
        cue_by_requirement = {
            cue.requirement_slot: cue for cue in plan.lexical_cues
        }
        assert all(
            requirement.entity_constraints
            or cue_by_requirement[requirement.slot_id].surface_terms
            for requirement in plan.requirements
        )


@pytest.mark.parametrize(
    "query",
    [
        "sensitive synthetic query",
        "Enumerate every memory in chronological sequence.",
        "What is the order of all four events from earliest to latest?",
        "Combien de souvenirs sont pertinents?",
        "把所有事件按完整时间线排序。",
        "这是一条没有问题形式的陈述。",
    ],
)
def test_q3b_uncertain_generic_query_is_grounded_best_effort_recall(query: str) -> None:
    compiler = MemoryQueryCompiler()
    contract = compiler.compile_contract(query, reference_time=REFERENCE)
    plan = compiler.compile(query, reference_time=REFERENCE)

    assert contract.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL
    assert plan.mode == "EVIDENCE"
    assert plan.steps
    assert plan.requirements
    assert plan.completeness == "TOP_K_ACCEPTABLE"
    assert plan.planner_trace.source == "DETERMINISTIC"
    assert infer_operator_family(plan) == "LOOKUP"


def test_q3b_bilingual_compilation_is_byte_stable_and_label_free() -> None:
    compiler = MemoryQueryCompiler()
    queries = [
        "How many times did I repair a bicycle in the past two weeks?",
        "过去两周我修理自行车多少次?",
    ]

    for query in queries:
        first = compiler.compile(query, reference_time=REFERENCE).model_dump_json()
        second = compiler.compile(query, reference_time=REFERENCE).model_dump_json()
        assert hashlib.sha256(first.encode()).digest() == hashlib.sha256(
            second.encode()
        ).digest()
        assert "case_id" not in first
        assert "gold_answer" not in first


@pytest.mark.parametrize(
    ("query", "family"),
    [
        ("我上次旅行住在什么酒店?", "LOOKUP"),
        ("两周前我参加了什么活动?", "TEMPORAL_FILTER"),
        ("种树还是粉刷车库, 哪个先发生?", "TEMPORAL_ORDER"),
        ("机器人演示与合唱音乐会之间有多少周?", "TEMPORAL_DISTANCE"),
        ("最近三个月内我参加音乐会多少次?", "COUNT"),
        ("陶瓷杯的单价是多少?", "DIVIDE"),
        ("跨会话查找我最终选择城市的证据", "MULTI_JOIN"),
    ],
)
def test_q3b_unseen_chinese_paraphrases_keep_the_same_operator_family(
    query: str, family: str
) -> None:
    plan = MemoryQueryCompiler().compile(query, reference_time=REFERENCE)

    assert plan.mode != "AMBIGUOUS"
    assert infer_operator_family(plan) == family


def test_q3b_count_plan_exposes_filter_dedup_and_reduce_steps() -> None:
    plan = MemoryQueryCompiler().compile(
        "过去两周我修理自行车多少次?", reference_time=REFERENCE
    )

    assert [step.kind for step in plan.steps] == [
        "RETRIEVE",
        "TEMPORAL_SCAN",
        "FILTER",
        "BIND_SLOT",
        "DEDUPLICATE",
        "REDUCE",
    ]
