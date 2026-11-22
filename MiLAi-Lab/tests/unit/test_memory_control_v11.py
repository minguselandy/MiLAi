from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from memory_control_coverage import coverage_batches
from milai_lab.datasets.memory_control_episode_archive import compact_scored_episode_packets
from milai_lab.datasets.memory_control_outcomes import outcome_supervision, run_protocols
from milai_lab.datasets.memory_control_revision import REVISION_SCHEMA
from milai_lab.datasets.memory_control_store import SCHEMA, dumps, packed
from milai_lab.memory.source_materials import read_original_materials
from milai_lab.methods.literal_delivery_union import literal_delivery
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
)
from milai_lab.methods.memory_control_dataset import StateIndex
from milai_lab.methods.small_control_learning import state_loss
from milai_lab.runners import memory_control_episode as episode
from milai_lab.runners.memory_control_episode import PolicyMenu
from milai_lab.runners.memory_control_policy_states import _assign_policies
from milai_lab.scorers.memory_control_episode_metrics import _shared_request_quality_delta
from report_memory_control_episode_evidence import _paired_delivery_effects, evidence_report


def test_literal_delivery_preserves_gaps_and_access_scope() -> None:
    body = "abcdefghij"

    def source(ref: str) -> dict:
        return {
            "event_id": ref,
            "source_revision": 1,
            "session": "conversation",
            "role": "user",
            "origin": "dialogue",
            "content": body,
            "observed_at": None,
        }

    def read(materials: list[dict]) -> list[dict]:
        return read_original_materials(materials, source)

    def view(start: int, end: int, scope: str) -> dict:
        binding = {
            "kind": "original_source",
            "id": "same",
            "session_id": "conversation",
            "source_access_scope": scope,
            "turn_range": [0, 1],
            "source_ranges": [
                {"source_ref": "m1", "source_revision": 1, "start": start, "end": end}
            ],
        }
        return {**binding, **read([binding])[0]}

    opened = {0: view(0, 3, "a"), 1: view(2, 5, "a"), 2: view(8, 10, "a"), 3: view(2, 5, "b")}
    delivery = literal_delivery(opened, read, lambda _: 0)
    assert [pieces["label"] for pieces in delivery.evidence] == ["e0", "e3"]
    assert [
        [(piece["content"], piece["range"]) for piece in pack["evidence"]]
        for pack in delivery.evidence
    ] == [[("abcde", [0, 5]), ("ij", [8, 10])], [("cde", [2, 5])]]
    assert delivery.overlap_before_normalization == 1


def test_completed_repeat_pairs_only_and_scaled_loss() -> None:
    torch = pytest.importorskip("torch")
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA + REVISION_SCHEMA)
        for action, repeat, status, quality, cost in (
            ("read_0", 0, "ingested", 1.0, 45),
            ("context_0", 0, "ingested", 0.2, 75),
            ("handoff", 0, "prepared", None, None),
            ("context_0", 1, "reader_error", None, None),
            ("other", 1, "ingested", 1.0, 20),
        ):
            db.execute(
                """
                INSERT INTO action_outcomes
                (state_id,action_id,run_id,repeat_index,reader_protocol,execution_status,
                 training_quality,success_witness,costs) VALUES (1,?, 'shared',?, 'v1',?,?,?,?)
            """,
                (
                    action,
                    repeat,
                    status,
                    quality,
                    quality == 1.0,
                    packed({"reader_input_tokens": cost}),
                ),
            )
        ids = ["read_0", "context_0", "handoff", "other"]
        sup = outcome_supervision(db, 1, set(ids), ("shared",))
        assert sup["observed_values"] == {"read_0": 1.0, "context_0": 0.2, "other": 1.0}
        assert sup["preferences"] == [{"left": "context_0", "right": "read_0", "outcome": "right"}]
        assert sup["success_cost_preferences"] == []
        scores = torch.zeros(len(ids), requires_grad=True)
        loss = state_loss(
            scores, ids, {**sup, "value_loss_weight": 0, "success_cost_loss_weight": 0}
        )
        assert float(loss.detach()) == pytest.approx(float(torch.log(torch.tensor(2.0))) * 0.2)
        loss.backward()
        assert scores.grad.tolist()[2:] == [0.0, 0.0]


def test_outcome_preferences_pool_only_matching_requests_in_each_repeat() -> None:
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA + REVISION_SCHEMA)
        for action, repeat, content, quality, cost in (
            ("read", 0, "shared", 1.0, 45),
            ("context", 0, "shared", 0.0, 45),
            ("handoff", 0, "separate", 0.25, 20),
            ("read", 1, "shared", 1.0, 44),
            ("context", 1, "shared", 1.0, 44),
        ):
            db.execute(
                """
                INSERT INTO action_outcomes
                (state_id,action_id,run_id,repeat_index,reader_protocol,execution_status,
                 training_quality,success_witness,costs,task_result)
                VALUES (1,?,'shared',?,'v1','ingested',?,?,?,?)
            """,
                (
                    action,
                    repeat,
                    quality,
                    quality == 1.0,
                    packed({"reader_input_tokens": cost}),
                    packed({"reader_wire": {"seed": 123 + repeat, "messages": [content]}}),
                ),
            )
        result = outcome_supervision(db, 1, {"read", "context", "handoff"}, ("shared",))
        assert result["observed_values"] == {"read": 0.75, "context": 0.75, "handoff": 0.25}
        assert result["pooled_reader_request_groups"] == 2
        assert result["pooled_reader_request_groups_with_quality_disagreement"] == 1
        assert result["preferences"] == [
            {"left": "context", "right": "handoff", "outcome": "left"},
            {"left": "handoff", "right": "read", "outcome": "right"},
        ]
        assert result["success_cost_preferences"] == []
        assert result["success_cost_witness_values"]["read"] == 0.0


def test_mixed_coverage_preserves_unique_rows_and_reports_equal_draws() -> None:
    index = [StateIndex(i, "source", f"group-{i}", i, "recipe", (0, i)) for i in range(7)]
    policy_ids = {5, 6}
    regular = list(coverage_batches(index, 3, 11))
    assert Counter(row for batch in regular for row in batch) == Counter(range(7))
    mixed = list(coverage_batches(index, 3, 11, policy_ids=policy_ids))
    assert list(map(len, mixed)) == [3, 3, 3, 1]
    assert mixed == list(coverage_batches(index, 3, 11, policy_ids=policy_ids))
    counts = Counter(row for batch in mixed for row in batch)
    assert all(counts[i] == 1 for i in range(5))
    assert counts[5] + counts[6] == 5 and min(counts[5], counts[6]) == 2


def test_policy_rotation_does_not_alias_with_the_alternating_source_order() -> None:
    task_ids = range(100, 120)
    candidates: list[tuple[int, set[str]]] = [(task, set()) for task in task_ids]
    sources = ("source_a", "source_b")
    by_task = {task: sources[task % len(sources)] for task in task_ids}

    assigned = list(_assign_policies(candidates, by_task))
    assert [(sequence, task) for sequence, task, _ in assigned] == list(enumerate(task_ids))
    for source in sources:
        counts = Counter(policy for _, task, policy in assigned if by_task[task] == source)
        assert counts == {"M0": 4, "M1": 4, "rules": 1, "random": 1}

    legacy = list(_assign_policies(candidates, None))
    legacy_exploration = [
        (sequence, policy) for sequence, _, policy in legacy if policy in {"rules", "random"}
    ]
    assert legacy_exploration == [(2, "rules"), (7, "random"), (12, "rules"), (17, "random")]


def test_fixed_r3_preserves_a_candidate_when_only_r2_is_feasible() -> None:
    menu = PolicyMenu(FixedContextMemoryPolicy(), read_limit=4, precision="R3")
    state = MemoryControlState(
        task={}, budget={"successful_reads": 0, "remaining_control_steps": 3}
    )
    focus = MemoryAction("read_0", "READ", "candidate", {"index": 0})
    context = MemoryAction("context_0", "READ", "candidate", {"index": 0, "expand_context": True})
    handoff = MemoryAction("handoff", "HANDOFF", "")
    assert menu.choose(state, [focus, handoff]) == focus.id
    assert menu.choose(state, [focus, context, handoff]) == context.id


def test_episode_batch_resumes_ready_and_collected_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data.sqlite3"
    with closing(sqlite3.connect(data)) as db, db:
        db.execute("CREATE TABLE experiment_tasks(id, dataset, native_group, experiment_role)")
        db.executemany("INSERT INTO experiment_tasks VALUES (?, 'source', 'group', 'dev')",
                       [(task,) for task in (1, 2, 3)])
    task_rows = [{"task_id": task, "dataset": "source", "native_group": "group"}
                 for task in (1, 2, 3)]
    manifest = tmp_path / "manifest.json"
    episode.write_json(manifest, {
        "protocol": episode.EVALUATION_PROTOCOL, "dataset_run_id": "release", "role": "dev",
        "seed": 42, "material_budget": 2048, "tasks": task_rows,
    })
    output = tmp_path / "readout"
    arm = {"policy": "B1", "observation_protocol": "semantic_nav_v1"}
    host = SimpleNamespace(settings={"host": {}}, capacity=None)
    dataset = SimpleNamespace(path=data, run_id="release", host=host, revision={})
    monkeypatch.setattr(episode, "MemoryControlDataset", lambda *a, **kw: dataset)
    monkeypatch.setattr(episode, "comparison_protocol", lambda _: {})
    monkeypatch.setattr(episode, "make_policy", lambda *a: (object(), None))
    monkeypatch.setattr(episode, "ownership_client_configs", lambda _: ())
    monkeypatch.setattr(episode, "VLLMConfig", lambda **kw: None)
    monkeypatch.setattr(episode, "VLLMClient", lambda *a, **kw: nullcontext(None))
    monkeypatch.setattr(
        episode, "remaining_reader_capacity", lambda _: {"requests_remaining": None},
    )
    busy = True
    owned = False
    budget = SimpleNamespace(state={"generation_requests": 0})
    prepared: list[int] = []
    requests: list[int] = []
    scored: list[int] = []

    @contextmanager
    def lease(*args, **kwargs):
        nonlocal owned
        if busy:
            raise RuntimeError("HTTP_OWNER_BUSY")
        owned = True
        try:
            yield budget
        finally:
            owned = False

    def prepare(_dataset, _db, task, _arm, _policy, _model, _material, seed):
        assert not owned
        prepared.append(task["id"])
        return {**task_rows[task["id"] - 1], "status": "ready", "reader_wire": {"seed": seed},
                "capacity": {}, "costs": {"episode_local_wall_ms": 1.0}}

    def request(_client, _host, wire, _capacity):
        assert owned
        requests.append(wire["seed"])
        budget.state["generation_requests"] += 1
        return {"status": "reader_completed"}, {
            "reader_request_attempted": True, "reader_client_wall_ms": 2.0,
        }

    def score(_dataset, _db, task, record):
        assert not owned
        scored.append(task["id"])
        record["status"] = "scored"

    monkeypatch.setattr(episode, "http_budget_scope", lease)
    monkeypatch.setattr(episode, "episode_before_reader", prepare)
    monkeypatch.setattr(episode, "request_reader", request)
    monkeypatch.setattr(episode, "score_episode", score)

    def execute() -> dict:
        return episode.evaluate_episodes(data, manifest, arm, output, device="cpu",
                                         max_reader_requests=1)

    preflight = episode.evaluate_episodes(data, manifest, arm, output, device="cpu",
                                          max_reader_requests=1, prepare_only=True)
    assert preflight["status"] == "PARTIAL_EPISODE_PREPARATION"
    assert preflight["by_episode_status"] == {"ready": 1}
    assert preflight["reader_requests_this_invocation"] == 0
    assert not (output / "run.json").exists()

    with pytest.raises(RuntimeError, match="HTTP_OWNER_BUSY"):
        execute()
    result_path = output / "episodes/1.json"
    assert len(result_path.read_text().splitlines()) == 1
    assert episode.read_json(result_path)["status"] == "ready"
    assert prepared == [1] and requests == []

    busy = False
    first = execute()
    assert first["status"] == "PARTIAL" and first["prepared_episodes_this_invocation"] == 0
    assert first["reader_requests_this_invocation"] == 1
    assert requests == [43] and scored == [1] and prepared == [1]
    assert compact_scored_episode_packets(output)["packets_compacted"] == 1
    assert not result_path.exists()
    assert result_path.with_suffix(".json.gz").is_file()

    for row, status in zip(task_rows[1:], ("reader_completed", "dispatching"), strict=True):
        episode.write_json(output / f"episodes/{row['task_id']}.json", {**row, "status": status})
    busy = True
    preserved = [p.read_bytes() for p in sorted((output / "episodes").iterdir())]
    audit = episode.evaluate_episodes(data, manifest, arm, output, device="cpu", prepare_only=True)
    assert audit["status"] == "PREPARED_EPISODES" and len(scored) == 1
    assert preserved == [p.read_bytes() for p in sorted((output / "episodes").iterdir())]
    assert episode.read_json(output / "run.json") == first
    last = execute()
    assert last["status"] == "COMPLETED" and last["reader_requests_this_invocation"] == 0
    assert last["by_episode_status"] == {"scored": 2, "reader_interrupted": 1}
    assert requests == [43] and scored == [1, 2]


def test_prepared_evidence_cannot_evaluate_confirmation(tmp_path: Path) -> None:
    episode.write_json(tmp_path / "protocol.json", {
        "population": {"protocol": episode.EVALUATION_PROTOCOL, "role": "confirm"},
        "comparison": {},
    })
    with pytest.raises(ValueError, match="requires a DEV cohort"):
        evidence_report(tmp_path / "data.sqlite3", [tmp_path], include_prepared_dev=True)


def test_paired_delivery_weights_tasks_and_resamples_native_groups() -> None:
    effects = _paired_delivery_effects(
        {
            ("trained", "source_a"): {"group_a": [1, 1, 0], "group_b": [-1]},
            ("trained", "source_b"): {"group_c": [0, 1]},
        },
        {"source_a", "source_b"},
        repeats=200,
        seed=11,
    )["trained"]
    assert effects["by_source"]["source_a"]["mapped_task_pairs"] == 4
    assert effects["by_source"]["source_a"]["native_groups"] == 2
    assert effects["by_source"]["source_a"]["difference_points"] == 25.0
    assert effects["by_source"]["source_a"]["interval_95"] == pytest.approx([-100, 200 / 3])
    assert effects["equal_source_difference_points"] == 37.5
    assert effects["equal_source_interval_95"] is None


def test_held_dev_outcomes_cannot_be_loaded_as_training_supervision() -> None:
    declaration = {
        "role": "dev",
        "sealed": True,
        "observation_protocol": "semantic_nav_v1",
        "comparison_protocol": {"continuation": "fixed_context"},
    }
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(SCHEMA + REVISION_SCHEMA)
        db.execute("INSERT INTO outcome_runs VALUES (?,?)", ("held", dumps(declaration)))
        with pytest.raises(ValueError, match="frozen train"):
            run_protocols(db, ("held",), "semantic_nav_v1")
        assert run_protocols(db, ("held",), "semantic_nav_v1", role="dev") == [declaration]


def test_shared_request_sensitivity_preserves_musique_pair_sufficiency() -> None:
    def episode(prompt: str, answerable: bool, sufficient: bool, f1: float) -> dict:
        return {
            "reader_wire": {"messages": [prompt], "seed": 11},
            "grade": {
                "native_metrics": {
                    "gold_answerable": answerable,
                    "sufficiency_correct": sufficient,
                    "answer_f1": f1,
                    "answer_em": 0.0,
                    "support_f1": 0.0,
                }
            },
        }

    left = {1: episode("expanded", True, True, 0.8), 2: episode("shared", False, True, 0.0)}
    right = {1: episode("focus", True, True, 0.4), 2: episode("shared", False, False, 0.0)}
    assert _shared_request_quality_delta("musique_full", [1, 2], left, right) == pytest.approx(0.2)
    right[1]["reader_wire"] = left[1]["reader_wire"]
    assert _shared_request_quality_delta("musique_full", [1, 2], left, right) == 0.0
