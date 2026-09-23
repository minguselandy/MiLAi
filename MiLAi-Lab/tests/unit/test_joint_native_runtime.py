import copy
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from joint_native_runtime import (
    CLOSE_TAG,
    LAB,
    OPEN_TAG,
    JointMemory,
    Timeline,
    actor_step,
    execute_arm,
    parse_state,
    render_source,
)
from joint_revision_formation import apply_reviewed_proposal, form_proposal, proposal_messages
from milai_lab.methods.controlled_workspace import MemoryCard
from milai_lab.methods.finite_research_budget import BudgetStop, FiniteResearchBudget
from milai_lab.methods.reasoning_bank import BankConfig, ExperienceBank
from milai_lab.methods.state_attention import question_digest
from milai_lab.methods.state_focus import SourceSnapshot, SourceUnit
from reasoningbank_provider import NativeProvider

MODEL = "Qwen3.6-35B-A3B-FP8"


def framed(ids=(), conflicts=(), coverage="SUFFICIENT"):
    return (
        OPEN_TAG
        + json.dumps(
            {
                "selected_source_ids": list(ids),
                "conflict_source_ids": list(conflicts),
                "coverage": coverage,
            }
        )
        + CLOSE_TAG
        + "\nAct: bash\n```bash\nprintf ok\n```"
    )


@pytest.fixture
def harness(tmp_path):
    budget = FiniteResearchBudget(tmp_path / "budget.sqlite", manifest_sha256="a" * 64)
    outputs, requests = [], []

    def transport(request):
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 20})
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["seed"] == 213 and body["top_p"] == 1
        assert body["temperature"] == 0 and body["chat_template_kwargs"] == {
            "enable_thinking": False
        }
        answer = outputs.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                "choices": [
                    {"message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
                ],
            },
        )

    provider = NativeProvider(
        tmp_path / "provider",
        max_tokens=3_000_000,
        max_requests=400,
        deadline=time.monotonic() + 14400,
        batch_budget=budget,
        transport=httpx.MockTransport(transport),
    )
    provider.verify()
    yield budget, provider, outputs, requests
    provider.close()
    budget.close()


def memory(tmp_path, *, arm="ATTENTION", expansion=True):
    root = tmp_path / arm
    root.mkdir()
    units = tuple(SourceUnit(x, "1", "fixture-scope", f"Advice {x}") for x in ("a", "b"))
    return JointMemory(
        root=root,
        admission_sha256="a" * 64,
        row={
            "attempt_id": arm,
            "arm": arm,
            "query": "question",
            "query_sha256": question_digest("question"),
        },
        snapshot=SourceSnapshot("fixture-scope", units),
        ranked_expansion=(SourceUnit("c", "1", "fixture-scope", "Advice c"),) if expansion else (),
        timeline=Timeline(tmp_path / "timeline.jsonl"),
    )


def step(value, harness):
    budget, provider, _, _ = harness
    return actor_step(
        provider=provider,
        budget=budget,
        memory=value,
        native_messages=[{"role": "user", "content": "question"}],
        system_prompt="Native grammar unchanged",
        runtime="Remaining native budget",
    )


def generation_bodies(harness):
    return [json.loads(r.content) for r in harness[3] if r.url.path == "/v1/chat/completions"]


def test_attention_uses_real_response_only_next_turn_and_invalidates_unseen_pool(tmp_path, harness):
    value = memory(tmp_path)
    harness[2].extend([framed(["a"]), framed(["a"]), framed(["a", "b"])])
    try:
        assert step(value, harness) == "Act: bash\n```bash\nprintf ok\n```"
        assert value.state.fields[0].observed_sequence == 1
        step(value, harness)
        assert value.state is None  # b was not in the second actual request
        step(value, harness)
        bodies = generation_bodies(harness)
        assert "Advice b" in bodies[0]["messages"][0]["content"]
        assert "Advice b" not in bodies[1]["messages"][0]["content"]
        assert "Advice b" in bodies[2]["messages"][0]["content"]
        assert [e["sources"] for e in value.exposures] == [["a", "b"], ["a"], ["a", "b"]]
        assert (
            harness[0].status()["total_requests"] == 7
        )  # model-info + 3 tokenize/generation pairs
        assert harness[0].status()["kinds"]["text"]["reported_tokens"] == 90
    finally:
        value.close()


def test_gap_expands_once_exposes_preview_as_unknown_then_needs_fresh_actor_review(
    tmp_path, harness
):
    value = memory(tmp_path)
    harness[2].extend([framed(["a"], coverage="GAP"), framed(["c"]), framed(["c"])])
    try:
        step(value, harness)
        step(value, harness)
        assert value.expansion.receipt()["status"] == "COMPLETED"
        assert value.coverage.snapshot_sha256 == value.snapshot.sha256
        assert value.coverage.observed_sequence == 2
        assert (
            "New retrieval preview: coverage UNKNOWN"
            in generation_bodies(harness)[1]["messages"][0]["content"]
        )
        step(value, harness)
        assert value.exposures[2]["sources"] == ["c"]
        assert harness[0].status()["kinds"]["embedding"]["requests"] == 0
        events = [json.loads(x) for x in value.timeline.path.read_text().splitlines()]
        assert sum(x["event"] == "CACHED_QUERY_EXPANSION" for x in events) == 1
    finally:
        value.close()


def test_static_has_no_state_emission_cost_or_response_rewrite(tmp_path, harness):
    value = memory(tmp_path, arm="STATIC")
    raw = framed(["a"])
    harness[2].append(raw)
    assert step(value, harness) == raw
    assert "milai_attention" not in generation_bodies(harness)[0]["messages"][0]["content"]
    assert value.state is None
    assert (
        LAB / "configs/policies/reasoning_bank/consume.txt"
    ).read_text().strip() in generation_bodies(harness)[0]["messages"][0]["content"]


def test_empty_expansion_spends_attempt_and_abstains_instead_of_reusing_intent(tmp_path, harness):
    value = memory(tmp_path, expansion=False)
    harness[2].extend([framed(["a"], coverage="GAP"), "Act: finish"])
    try:
        step(value, harness)
        step(value, harness)
        assert value.expansion.receipt()["status"] == "COMPLETED"
        assert value.exposures[-1]["sources"] == []
        rows = [json.loads(x) for x in value.timeline.path.read_text().splitlines()]
        projected = [x for x in rows if x["event"] == "JOINT_PROJECTION"][-1]
        assert projected["decision"]["reason"] == "EXPANSION_EXHAUSTED"
        assert projected["decision"]["action"] == "ABSTAIN_MEMORY"
        assert not projected["preview_for_review"]
    finally:
        value.close()


@pytest.mark.parametrize(
    "raw",
    [
        framed(["foreign"]),
        framed(["a", "a"]),
        framed(["a"], ["a"]),
        OPEN_TAG + '{"coverage":"GAP","coverage":"SUFFICIENT"}' + CLOSE_TAG + "\nAct: finish",
        OPEN_TAG + " " * 4097 + CLOSE_TAG + "\nAct: finish",
    ],
)
def test_invalid_state_cannot_become_coverage(tmp_path, raw):
    value = memory(tmp_path)
    try:
        native, state, status = parse_state(raw, value.snapshot)
        assert state is None and status == "MALFORMED_OR_UNBOUNDED"
        assert native.startswith("Act:")
    finally:
        value.close()


def test_failed_generation_keeps_upper_bound_and_has_no_false_exposure(tmp_path, harness):
    value = memory(tmp_path)
    harness[2].append(httpx.ReadTimeout("fixture failure"))
    try:
        with pytest.raises(httpx.ReadTimeout):
            step(value, harness)
        status = harness[0].status()
        assert status["total_requests"] == 3
        assert status["kinds"]["text"]["unknown_token_upper_bound"] == 4116
        assert not value.exposures and value.state is None
        before = len(harness[3])
        with pytest.raises(ValueError, match="UNSETTLED_USAGE_NO_RETRY"):
            step(value, harness)
        assert len(harness[3]) == before
    finally:
        value.close()


def test_deadline_blocks_before_actor_dispatch(tmp_path, harness):
    value = memory(tmp_path)
    harness[0].db.execute("UPDATE batch SET started=?", (time.time() - 14401,))
    before = len(harness[3])
    try:
        with pytest.raises(BudgetStop, match="WALL_TIME_LIMIT"):
            step(value, harness)
        assert len(harness[3]) == before
    finally:
        value.close()


def test_settled_nontext_output_keeps_input_exposure_and_cost(tmp_path, harness):
    value = memory(tmp_path)
    harness[2].append(None)
    try:
        with pytest.raises(ValueError, match="RETURNED_NO_TEXT"):
            step(value, harness)
        assert value.exposures[0]["sources"] == ["a", "b"]
        assert value.state is None
        assert harness[0].status()["kinds"]["text"]["reported_tokens"] == 30
    finally:
        value.close()


def source_window():
    card = MemoryCard("card:1", "Use the old general rule", ["original"])
    bank = ExperienceBank(
        {"domain": "fixture", "split": "DEV"},
        {"config": asdict(BankConfig())},
        cards={card.handle: card},
        sources={"original": "old episode", "feedback": "visible counterexample"},
        records=[
            {
                "task_id": "earlier",
                "query": "prior",
                "embedding": [1.0] + [0.0] * 1023,
                "handles": [card.handle],
            }
        ],
        next_card=2,
    )
    window = {
        "window_id": "window:1",
        "card": asdict(card),
        "original_evidence": {"original": "old episode"},
        "visible_query": {"query": "earlier visible question"},
        "visible_feedback": {"feedback": "visible counterexample"},
        "lineage_clusters": ["prior-cluster"],
        "native_result": "FORBIDDEN_INPUT",
        "later_query": "FORBIDDEN_LATER_QUESTION",
    }
    proposal = {
        "kind": "SCOPE_NARROWING",
        "reason": "visible exception",
        "text": "Use the rule only within supported scope",
        "feedback_refs": ["feedback"],
        "changed_claims": [],
        "changed_applicability": ["exclude observed exception"],
    }
    return bank, window, proposal


@pytest.mark.parametrize("application", ["replace", "append_only"])
def test_real_provider_formation_existing_patch_and_later_revision_exposure(
    tmp_path, harness, application
):
    budget, provider, outputs, _ = harness
    bank, window, proposal = source_window()
    original = copy.deepcopy(bank.checkpoint())
    assert "FORBIDDEN" not in json.dumps(proposal_messages(window))
    timeline = Timeline(tmp_path / "timeline.jsonl")
    outputs.append(json.dumps(proposal))
    formation = form_proposal(
        provider=provider, budget=budget, window=window, formation_id="formation", timeline=timeline
    )
    assert formation["status"] == "SOURCE_REVIEW_REQUIRED"
    review = {
        "formation_sequence": formation["sequence"],
        "support": "SUPPORTED",
        "support_ref": "synthetic-independent-review",
    }
    formed, seal = apply_reviewed_proposal(
        bank=bank,
        window=window,
        formation=formation,
        review=review,
        application=application,
        timeline=timeline,
    )
    assert bank.checkpoint() == original
    handles = formed.records[0]["handles"]
    assert len(handles) == (2 if application == "append_only" else 1)
    units = tuple(
        SourceUnit(h, str(formed.cards[h].revision), "fixture", formed.cards[h].text)
        for h in handles
    )
    root = tmp_path / "later"
    root.mkdir()
    value = JointMemory(
        root=root,
        admission_sha256="a" * 64,
        row={
            "attempt_id": "later",
            "arm": "APPEND_ONLY" if application == "append_only" else "REVISION",
            "query": "question",
            "query_sha256": question_digest("question"),
            "cluster": "later-cluster",
        },
        snapshot=SourceSnapshot("fixture", units),
        ranked_expansion=(),
        timeline=timeline,
        bank=formed,
        revision_reviews=(seal,),
        source_handles={h: h for h in handles},
    )
    outputs.append("Act: finish")
    assert step(value, harness) == "Act: finish"
    result = value.finish(result_ref="synthetic-native-result", costs=provider.task_usage("later"))
    assert result["revision_reuse"][0]["eligible"] is True
    assert result["revision_reuse"][0]["observable_use"] == "UNKNOWN"
    assert budget.status()["total_requests"] == 5
    bodies = generation_bodies(harness)
    assert bodies[0]["max_tokens"] == 2048 and bodies[1]["max_tokens"] == 4096
    for source in units:
        assert render_source(source) in bodies[1]["messages"][0]["content"]
    value.close()


def test_malformed_formation_is_charged_without_repair_or_retry(tmp_path, harness):
    budget, provider, outputs, _ = harness
    _, window, _ = source_window()
    outputs.append("not json")
    value = form_proposal(
        provider=provider,
        budget=budget,
        window=window,
        formation_id="formation",
        timeline=Timeline(tmp_path / "events.jsonl"),
    )
    assert value["status"] == "REJECTED_OUTPUT" and value["proposal"] is None
    assert value["costs"]["settled_requests"] == 1
    assert len(generation_bodies(harness)) == 1


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unsupported", "UNSUPPORTED_REVISION"),
        ("source", "REVISION_SOURCE_CHANGED"),
        ("predecessor", "EXACT_PREDECESSOR_CHANGED"),
        ("formation", "REVIEW_FORMATION_MISMATCH"),
    ],
)
def test_review_application_rejects_unsupported_or_changed_inputs(
    tmp_path, harness, mutation, error
):
    budget, provider, outputs, _ = harness
    bank, window, proposal = source_window()
    timeline = Timeline(tmp_path / "timeline.jsonl")
    outputs.append(json.dumps(proposal))
    formation = form_proposal(
        provider=provider, budget=budget, window=window, formation_id="formation", timeline=timeline
    )
    review = {
        "formation_sequence": formation["sequence"],
        "support": "SUPPORTED",
        "support_ref": "fixture-review",
    }
    if mutation == "unsupported":
        review["support"] = "UNKNOWN"
    elif mutation == "source":
        bank.sources["feedback"] = "changed"
    elif mutation == "predecessor":
        bank.cards["card:1"].text = "changed"
    else:
        review["formation_sequence"] += 1
    before = len(harness[3])
    with pytest.raises(ValueError, match=error):
        apply_reviewed_proposal(
            bank=bank,
            window=window,
            formation=formation,
            review=review,
            application="replace",
            timeline=timeline,
        )
    assert len(harness[3]) == before


def install_native_fixture(monkeypatch, *, release_fails):
    """Exercise execute_arm's native adapter calls without benchmark data or Docker."""
    observed = {"released": 0}

    class History:
        def __init__(self):
            self.messages = [{"role": "user", "content": "question"}]

        def get_item_deep_copy(self, index):
            return SimpleNamespace(content=self.messages[index]["content"])

    class Session:
        def __init__(self, **kwargs):
            self.chat_history = History()
            self.sample_status = "RUNNING"
            self.evaluation_record = SimpleNamespace(outcome="fixture-success")
            self.finish_reason = "fixture"

        def model_dump(self, **kwargs):
            return {"status": self.sample_status}

    class Task:
        def __init__(self, **kwargs):
            observed["kwargs"] = kwargs
            self.task_name = kwargs["task_name"]
            self.max_round, self.current_round = kwargs["max_round"], 0

        def reset(self, session):
            observed["reset"] = True

        def interact(self, session):
            observed["action"] = session.response.content
            self.current_round += 1
            session.sample_status = "COMPLETED"

        def complete(self, session):
            observed["complete"] = True

        def release(self):
            observed["released"] += 1
            if release_fails:
                raise RuntimeError("fixture release failure")

    class LanguageModel:
        def __init__(self, roles):
            assert roles == {"user": "user", "agent": "assistant"}

        def _convert_chat_history_to_message_list(self, history):
            return history

    class Agent:
        def __init__(self, model):
            self.model = model

        def inference(self, session):
            (session.response,) = self.model._inference(
                [session.chat_history.messages], {}, "native system"
            )

    modules = {
        "src.agents.instance.language_model_agent": {"LanguageModelAgent": Agent},
        "src.factories.chat_history_item": {"ChatHistoryItemFactory": str},
        "src.language_models": {"LanguageModel": LanguageModel},
        "src.tasks.instance.db_bench.task": {"DBBench": Task},
        "src.tasks.instance.os_interaction.task": {"OSInteraction": Task},
        "src.typings": {
            "ChatHistoryItem": SimpleNamespace,
            "Role": SimpleNamespace(AGENT="agent"),
            "SampleStatus": SimpleNamespace(RUNNING="RUNNING"),
            "Session": Session,
            "TaskName": str,
        },
    }
    installed = {}
    for name, attrs in modules.items():
        parts = name.split(".")
        for index in range(1, len(parts) + 1):
            key = ".".join(parts[:index])
            if key not in installed:
                module = ModuleType(key)
                module.__path__ = []
                monkeypatch.setitem(sys.modules, key, module)
                installed[key] = module
                if index > 1:
                    setattr(installed[".".join(parts[: index - 1])], parts[index - 1], module)
        for key, value in attrs.items():
            setattr(installed[name], key, value)
    return observed


@pytest.mark.parametrize(
    "domain,release_fails",
    [("db_bench", False), ("os_interaction", False), ("os_interaction", True)],
)
def test_native_adapter_keeps_rounds_grammar_costs_and_cleanup(
    tmp_path, harness, monkeypatch, domain, release_fails
):
    observed = install_native_fixture(monkeypatch, release_fails=release_fails)
    harness[2].append(framed(["a"]))
    row = {
        "attempt_id": "native-fixture",
        "arm": "ATTENTION",
        "domain": domain,
        "task_id": "fixture",
        "query": "question",
        "query_sha256": question_digest("question"),
    }
    root = tmp_path / "native-fixture-root"
    kwargs = dict(
        run_root=root,
        row=row,
        provider=harness[1],
        budget=harness[0],
        admission_sha256="a" * 64,
        timeline=Timeline(tmp_path / "native-events.jsonl"),
        memory_args={
            "snapshot": SourceSnapshot("fixture", (SourceUnit("a", "1", "fixture", "Advice a"),)),
            "ranked_expansion": (),
        },
    )
    if release_fails:
        with pytest.raises(RuntimeError, match="fixture release failure"):
            execute_arm(**kwargs)
    else:
        assert execute_arm(**kwargs)["status"] == "COMPLETED"
    assert observed["released"] == 1
    assert observed["action"] == "Act: bash\n```bash\nprintf ok\n```"
    assert observed["kwargs"]["max_round"] == (3 if domain == "db_bench" else 5)
    if domain == "os_interaction":
        assert observed["kwargs"]["command_execution_timeout"] == 20
    result = json.loads((root / "arms/native-fixture/result.json").read_text())
    assert result["budget_after"]["total_requests"] == 3
    assert result["provider_usage"]["settled_requests"] == 1
    if release_fails:
        assert result["status"] == "FINALIZATION_FAILED"
        assert result["finalization_failures"][0]["step"] == "native_release"
    before = len(harness[3])
    with pytest.raises(FileExistsError):
        execute_arm(**kwargs)
    assert len(harness[3]) == before
