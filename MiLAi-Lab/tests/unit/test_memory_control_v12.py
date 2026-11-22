from __future__ import annotations

import gzip
import shutil
import sqlite3
from contextlib import closing, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from memory_control_coverage import (
    exposure_source_weights,
    record_action_calibration,
    source_weights,
    summarize_action_calibration,
)
from memory_control_outcome_diagnostic import (
    compare_held_calibration,
    verify_added_outcome_supervision,
)
from memory_control_outcome_fits import select_numeric_representation, select_outcome_objective
from memory_control_outcome_stage import CORE, DELTA, dispatch_delta
from milai_lab.datasets.memory_control_episode_archive import (
    archive_completed_readout,
    compact_scored_episode_packets,
)
from milai_lab.datasets.memory_control_outcomes import outcome_supervision
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_revision import OUTCOME_PREPARATION_SCHEMA, REVISION_SCHEMA
from milai_lab.datasets.memory_control_store import SCHEMA, dumps, packed, set_meta, unpack
from milai_lab.datasets.memory_control_views import SourceObject
from milai_lab.memory.reader_projection import subtract_source_ranges
from milai_lab.methods.control_numeric import ACTION_WIDTH, STATE_WIDTH
from milai_lab.methods.corpus_navigation import delta_preview, query_terms
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_dataset import StateIndex
from milai_lab.methods.memory_object_policy import build_object_head, object_semantic_texts
from milai_lab.methods.small_control_learning import paired_state_losses
from milai_lab.methods.small_memory_policy import PolicyScores, SmallMemoryPolicy
from milai_lab.runners import memory_control_outcome_run
from milai_lab.runners.memory_control_common_menu import _without_budget_inputs
from milai_lab.runners.memory_control_confirmation import (
    confirmation_capacity,
    confirmation_repeat_population,
    plan_confirmation_power,
)
from milai_lab.runners.memory_control_delta_sampling import _online_priority_reasons
from milai_lab.runners.memory_control_outcome_reuse import _rebind_state
from milai_lab.runners.memory_control_pair_report import (
    pair_information_report,
    registered_pair_coverage,
)
from milai_lab.scorers.memory_control_episode_metrics import (
    _paired_metrics,
    _primary_group_quality,
    centered_bootstrap_pvalue,
    holm_adjust,
    input_result,
    summarize_inline_policy_load,
)


def test_delta_navigation_uses_bounded_literal_intervals() -> None:
    def span(ref: str, revision: int, start: int, end: int) -> dict:
        return {"source_ref": ref, "source_revision": revision, "start": start, "end": end}

    assert subtract_source_ranges(
        [span("x", 1, 0, 10), span("x", 2, 0, 10), span("y", 1, 0, 10)],
        [span("x", 1, 3, 7)],
    ) == [span("x", 1, 0, 3), span("x", 1, 7, 10), span("x", 2, 0, 10), span("y", 1, 0, 10)]

    encoder = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    encoder.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    focus = " ".join(f"focus{i}" for i in range(65))
    context = " ".join(f"context{i}" for i in range(65))
    body = focus + " " + context
    objects = {1: SourceObject(1, 0, "paragraph", "user", "", body, "")}
    arguments = (objects, {1: "source"}, encoder)
    terms = query_terms("focus5 context5")
    first = [(1, 0, len(focus))]
    second = [(1, len(focus) + 1, len(body))]
    preview = delta_preview(terms, first, second, *arguments, source_revision=2)
    assert preview["encoder_tokens"] == 64
    for component in ("focus", "expansion_only"):
        fragment = preview[component]
        assert fragment["encoder_tokens"] == len(encoder.encode(fragment["text"]).ids) == 32
        assert fragment["text"] == body[fragment["start"]:fragment["end"]]
        assert fragment["source_revision"] == 2
    assert preview["focus"]["end"] <= preview["expansion_only"]["start"]
    absent = delta_preview(terms, first, None, *arguments, source_revision=2)
    assert absent["focus"]["encoder_tokens"] == 64
    assert absent["expansion_only"]["status"] == "absent"
    missing = delta_preview(terms, first, [(2, 0, 4)], *arguments, source_revision=2)
    assert missing["focus"]["encoder_tokens"] == 32
    assert missing["expansion_only"]["status"] == "missing"

    import json

    candidate = {"body_delivered": False, "navigation_only": True, "navigation": preview}
    objects_text = ['{"task":{"request":"query"}}', '{"context":{}}',
                    json.dumps({"object": candidate})]
    assert object_semantic_texts(objects_text, [])[0][-1] == ""
    shown = object_semantic_texts(objects_text, [], navigation_v2=True)[0][-1]
    assert preview["expansion_only"]["text"] in shown


def test_measured_pairs_keep_common_repeats_and_independent_cost_masks() -> None:
    focus = {"kind": "READ", "parameters": {"index": 3}}
    context = {"kind": "READ", "parameters": {"index": 3, "expand_context": True}}
    handoff = {"kind": "HANDOFF", "parameters": {}}
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA + REVISION_SCHEMA)
        for action, repeat, binding, wire, value, tokens, usage in (
            ("focus", 0, focus, "a", 0.1, 100, "provider"),
            ("context", 0, context, "b", 0.7, 90, "provider"),
            ("context", 1, context, "c", 0.0, 95, "local_tokenizer"),
            ("focus", 2, focus, "shared", 0.4, 50, "provider"),
            ("context", 2, context, "shared", 0.4, 50, "provider"),
            ("handoff", 3, handoff, "e", 0.8, 80, "provider"),
        ):
            receipt = {"reader_input_tokens": tokens, "reader_usage_source": usage}
            branch = {"reader_wire": {"seed": repeat, "messages": [wire]},
                      "reader_result": {"response": {"id": wire}}, "action_binding": binding}
            db.execute("""
                INSERT INTO action_outcomes
                (state_id,action_id,run_id,repeat_index,reader_protocol,branch_seed,
                 execution_status,training_quality,costs,task_result)
                VALUES (1,?, 'r',?, 'native',?, 'ingested',?,?,?)
            """, (action, repeat, repeat, value, packed(receipt), packed(branch)))
        summary = outcome_supervision(db, 1, {"focus", "context", "handoff", "unknown"}, ("r",),
                                      paired=True)
    assert "unknown" not in summary["observed_values"]
    (pair,) = summary["paired_deltas"]
    assert (pair["left"], pair["right"], pair["kind"]) == ("context", "focus", "precision")
    assert pair["quality_delta"] == pytest.approx(0.3)
    assert pair["cost_delta"] == -5 and pair["common_quality_repeats"] == 2
    assert summary["outcome_cost_tokens"]["context"] == 70
    assert summary["pooled_reader_request_groups"] == 1


def test_action_calibration_preserves_unknowns_and_provider_token_units() -> None:
    groups = {}
    record_action_calibration(
        groups,
        [{"id": "focus", "kind": "READ", "parameters": {"index": 3}},
         {"id": "context", "kind": "READ", "parameters": {"index": 3, "expand_context": True}},
         {"id": "handoff", "kind": "HANDOFF", "parameters": {}}],
        [0.25, 0.8, 0.6], [0.5, 1.0, 0.25], {"focus": 0.0}, {"focus": 1000, "handoff": 512},
        top=1,
    )
    focus = summarize_action_calibration(groups["R2"])
    assert focus["quality_measured"] == 1 and focus["quality_observed_mean"] == 0.0
    assert focus["quality_mse"] == pytest.approx(0.0625)
    assert focus["input_tokens_predicted_mean"] == 1024
    assert focus["input_tokens_mae"] == 24
    context = summarize_action_calibration(groups["R3"])
    assert context["selected"] == 1 and context["selected_quality_measured"] == 0
    assert context["selected_provider_input_measured"] == 0
    assert context["quality_mse"] is None and context["input_tokens_mae"] is None
    handoff = summarize_action_calibration(groups["HANDOFF"])
    assert handoff["quality_measured"] == 0 and handoff["input_tokens_mae"] == 0


def test_bounded_scoring_keeps_replies_reusable_at_open_before_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "outcomes.sqlite3"
    reply = packed({
        "reader_result": {"response": {"choices": [{"message": {"content": "answer"}}]}},
        "source_aliases": {},
    })
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA + REVISION_SCHEMA)
        db.execute("INSERT INTO roots VALUES(1,'qasper','paper','raw','{}',NULL,0)")
        db.execute("INSERT INTO tasks VALUES(1,1,'train',0,'qa','query','native','train',1)")
        db.execute("INSERT INTO experiment_groups VALUES('qasper','paper','train','test',0)")
        for sid in (1, 2):
            db.execute("INSERT INTO states VALUES(?,1,'r','s',6,?,?,?,?,0,1,1)",
                       (sid, *([packed([])] * 4)))
        db.execute("INSERT INTO outcome_runs VALUES('D',?)", (dumps({
            "role": "train", "sealed": False, "comparison_protocol": {},
        }),))
        for sid, action, state in (
            (1, "focus", "reader_completed"), (1, "handoff", "prepared"),
            (2, "handoff", "reader_completed"),
        ):
            db.execute("""
                INSERT INTO action_outcomes
                    (state_id,action_id,run_id,repeat_index,reader_protocol,execution_status,
                     task_result) VALUES (?,?,'D',0,'native',?,?)
            """, (sid, action, state, reply))
    data = SimpleNamespace(path=path, revision={},
                           scoring_reader_task=lambda *_: (None, ()))
    monkeypatch.setattr(memory_control_outcome_run, "_current_comparison",
                        lambda _, declared: declared["comparison_protocol"])
    monkeypatch.setattr(memory_control_outcome_run, "task_annotation", lambda *_: {})
    monkeypatch.setattr(memory_control_outcome_run, "score_answer", lambda *_args, **_kw: {
        "status": "scored", "native_metrics": {}, "training_quality": 0.75, "success_witness": 1,
    })
    bounded = memory_control_outcome_run.score_outcomes(data, "D", seal=False, limit=1)
    assert bounded["scored_this_invocation"] == 1 and not bounded["sealed"]
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("""
            SELECT state_id,execution_status FROM action_outcomes
            ORDER BY state_id,action_id
        """).fetchall() == [(1, "reader_completed"), (1, "prepared"), (2, "ingested")]
    with pytest.raises(ValueError, match="positive limit and an open run"):
        memory_control_outcome_run.score_outcomes(data, "D", seal=True, limit=1)
    final = memory_control_outcome_run.score_outcomes(data, "D", seal=False)
    assert final["scored_this_invocation"] == 1 and final["outcomes_by_status"]["ingested"] == 2


def test_common_budget_comparison_preserves_nonbudget_inputs_and_masks() -> None:
    left = {
        "observation": {
            "budget": {"reader_material_tokens": 2048, "remaining_reader_material_tokens": 1024,
                       "successful_reads": 1},
            "visible_sources": ["delivered"],
        },
        "actions": [{"id": "handoff"}],
        "control_numeric": {
            "schema": "control_numeric_v1",
            "state": [1.0, 0.5, 0.5, *([1.0] * (STATE_WIDTH - 3))],
            "actions": [[0.0] * ACTION_WIDTH],
        },
    }
    other = deepcopy(left)
    other["observation"]["budget"].update(
        reader_material_tokens=1536, remaining_reader_material_tokens=512,
    )
    other["control_numeric"]["state"][:2] = [0.75, 0.25]
    assert _without_budget_inputs(left) == _without_budget_inputs(other)
    altered_action = deepcopy(other)
    altered_action["control_numeric"]["actions"][0][0] = 1.0
    assert _without_budget_inputs(left) != _without_budget_inputs(altered_action)
    altered_mask = deepcopy(other)
    altered_mask["control_numeric"]["state"][STATE_WIDTH // 2] = 0.0
    assert _without_budget_inputs(left) != _without_budget_inputs(altered_mask)
    other["observation"]["visible_sources"] = ["different"]
    assert _without_budget_inputs(left) != _without_budget_inputs(other)


def test_inline_setup_amortizes_measured_load_and_preserves_missing_task_times() -> None:
    population = {"tasks": [{"task_id": i} for i in (1, 2, 3)],
                  "predeclared_unevaluable_tasks": {"3": "known unavailable"}}
    rows = {
        1: {"status": "scored", "costs": {
            "reader_request_attempted": True, "episode_live_readout_ms": 200.0,
        }},
        2: {"status": "scored_format_failure", "costs": {
            "reader_request_attempted": True, "episode_live_readout_ms": 500.0,
        }},
        3: {"status": "action_failed"},
    }
    windows = [{"readout_schedule": "inline", "policy_load_ms_this_invocation": load,
                "reader_attempts_this_invocation": attempts}
               for load, attempts in ((100, 1), (20, 1), (0, 0))]
    result = summarize_inline_policy_load(population, rows, windows)
    assert result["timed_live_reader_tasks"] == result["eligible_tasks"] == 2
    assert result["policy_load_count"] == 2
    assert result["policy_load_ms_per_eligible_task"] == 60
    assert result["mean_live_task_wall_ms_with_amortized_policy_load"] == 410
    assert result["logged_reader_attempts"] == result["episode_reader_attempts"] == 2
    assert result["reader_attempts_reconciled"]
    rows[2]["costs"]["reader_request_attempted"] = False
    partial = summarize_inline_policy_load(population, rows, windows)
    assert partial["timed_live_reader_tasks"] == 1 and not partial["inline_timings_complete"]
    assert not partial["reader_attempts_reconciled"]
    assert partial["live_task_wall_ms"]["p95"] == 200
    assert partial["mean_live_task_wall_ms_with_amortized_policy_load"] is None
    windows[0].pop("policy_load_ms_this_invocation")
    unknown_setup = summarize_inline_policy_load(population, rows, windows)
    assert not unknown_setup["policy_load_records_complete"]
    assert unknown_setup["total_policy_load_ms"] is None


def test_added_outcome_contrast_rejects_a_different_completed_schedule(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    reference, candidate = tmp_path / "C", tmp_path / "R"
    for path, outcomes in ((reference, ["C"]), (candidate, ["C", "D"])):
        initial = path / "checkpoints/initial"
        initial.mkdir(parents=True)
        torch.save({"head": {"qc.weight": torch.ones(1)}}, initial / "weights.pt")
        write_json(path / "run.json", {"status": "COMPLETED", "contract": {
            "supervision_mode": "outcome", "outcome_runs": outcomes,
            "outcome_protocols": [{"run": r} for r in outcomes],
            "eligible_states": [4, 7], "seed": 11, "epochs": 1, "steps": 1,
            "dev_outcome_runs": ["held"],
        }})
        write_json(path / "coverage.json", {
            "full_coverage": True, "eligible_states": 2, "full_epochs": 1,
            "total_optimizer_updates": 1, "total_states_exposed": 2,
        })
        (path / "steps.jsonl").write_text(dumps({
            "step": 1, "epoch": 1, "states": 2, "lr_next_step": 0.0001,
        }) + "\n")
    good = verify_added_outcome_supervision(reference, candidate, ["C", "D"])
    assert good["matched_initial_head_tensors"] == 1
    assert good["total_optimizer_updates"] == 1 and good["total_states_exposed"] == 2
    (candidate / "steps.jsonl").write_text(dumps({
        "step": 1, "epoch": 1, "states": 2, "lr_next_step": 0.0002,
    }) + "\n")
    with pytest.raises(ValueError, match="completed update schedules"):
        verify_added_outcome_supervision(reference, candidate, ["C", "D"])


def test_held_calibration_contrast_uses_the_same_menus_and_measured_rows(tmp_path: Path) -> None:
    reference, candidate = tmp_path / "C", tmp_path / "R"
    for path, qerr, mae in ((reference, 0.25, 32.0), (candidate, 0.125, 16.0)):
        write_json(path / "run.json", {
            "status": "COMPLETED", "data": "release.sqlite3", "reader_calls": 0,
            "source_overlap": 0, "dev_outcome_runs": ["held"], "states": 1, "groups": 1,
        })
        write_json(path / "result.json", {
            "by_dataset": {"source": {
                "observed_value_brier": qerr, "observed_choice_coverage": 1.0,
            }},
            "outcome_calibration": {"utility_lambda": 0.05, "by_dataset_and_action": {
                "source": {"HANDOFF": {"offered": 1, "quality_measured": 1,
                                       "provider_input_measured": 1, "input_tokens_mae": mae}},
            }},
        })
        (path / "predictions.jsonl").write_text(dumps({
            "sample_id": "before", "group_id": "source/group", "actions": ["handoff"],
        }) + "\n")
    comparison = compare_held_calibration(reference, candidate, utility_lambda=0.05)
    effect = comparison["source_macro"]["candidate_minus_reference"]
    assert effect == {"quality_mse": -0.125, "observed_delta_mse": None,
                      "provider_input_mae_tokens": -16.0, "observed_top1_coverage": 0.0}
    (candidate / "predictions.jsonl").write_text(dumps({
        "sample_id": "before", "group_id": "source/group", "actions": ["other"],
    }) + "\n")
    with pytest.raises(ValueError, match="different before-state menus"):
        compare_held_calibration(reference, candidate, utility_lambda=0.05)


def test_continuation_report_matches_forced_actions_and_separates_request_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "outcomes.sqlite3"
    actions = {
        "focus": {"kind": "READ", "parameters": {"index": 0}},
        "context": {"kind": "READ", "parameters": {"index": 0, "expand_context": True}},
        "handoff": {"kind": "HANDOFF", "parameters": {}},
    }
    entries = [{
        "state_id": 1, "actions": list(actions), "repeats": 1,
        "dataset": "qasper", "native_group": "paper", "material_budget": 1024,
    }]
    roster = {"scope": {"registered_branch_entries": entries}}
    plan = tmp_path / "plan.json"
    write_json(plan, {"dataset_run_id": "release", "observation_protocol": "metadata_v1",
                      "states": entries})
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA + REVISION_SCHEMA + OUTCOME_PREPARATION_SCHEMA)
        db.execute("INSERT INTO roots VALUES(1,'qasper','paper','raw','{}',NULL,0)")
        db.execute("INSERT INTO tasks VALUES(1,1,'train',0,'qa','query','native','train',1)")
        db.execute("INSERT INTO experiment_groups VALUES('qasper','paper','train','test',0)")
        menu = [{"id": action, **binding} for action, binding in actions.items()]
        db.execute("INSERT INTO states VALUES(1,1,'r','s',6,?,?,?,?,0,1,1)",
                   (packed([]), packed([]), packed(menu), packed([])))
        db.execute("INSERT INTO state_variants VALUES(1,'release',NULL,1024,'metadata_v1',?,?)",
                   (packed({}), packed({})))
        for run, kind in (("ref", "reference-short"), ("peer", "frozen-policy-short")):
            declaration = {
                "branch_plan": str(plan), "dataset_run_id": "release", "selection_seed": 11,
                "role": "train", "sealed": True, "observation_protocol": "metadata_v1",
                "sample_kind": "continuation_audit", "registered_state_count": 1,
                "declared_branch_slots": 3,
                "comparison_protocol": {"reader_protocol": "native", "continuation": {
                    "kind": kind, "max_followup_decisions": 2, "terminal_rule": "handoff",
                }},
            }
            db.execute("INSERT INTO outcome_runs VALUES(?,?)", (run, dumps(declaration)))
            db.execute("INSERT INTO outcome_preparation_batches VALUES(?,0,1,1,?,?)",
                       (run, packed(roster), packed([])))
        measured = (
            ("ref", "focus", "shared", 0.2, 100, "provider", True),
            ("ref", "context", "shared", 0.2, 100, "provider", True),
            ("ref", "handoff", "halt", 0.6, 70, "provider", False),
            ("peer", "focus", "shared", 0.2, 100, "provider", True),
            ("peer", "context", "expanded", 0.8, 140, "local_tokenizer", False),
            ("peer", "handoff", "halt", 0.5, 70, "provider", False),
        )
        for run, action, content, quality, tokens, usage, shared in measured:
            stages = {"action_binding": actions[action], "first_action_effect": {"ok": True},
                      "reader_wire": {"seed": 42, "messages": [content]},
                      "reader_result": {"status": "reader_completed", "response": {"id": content}}}
            if shared:
                stages["reader_measurement_ref"] = {
                    "run_id": "ref", "state_id": 1, "action_id": "focus", "repeat_index": 0,
                }
                stages["reader_measurement_reused"] = True
            costs = {"reader_input_tokens": tokens, "reader_usage_source": usage,
                     "reader_request_attempted": not shared, "reader_wall_ms": 100.0}
            db.execute("""
                INSERT INTO action_outcomes
                    (state_id,run_id,action_id,repeat_index,branch_seed,bound_action,reader_protocol,
                     execution_status,training_quality,task_result,costs)
                VALUES (1,?,?,0,42,?,'native','ingested',?,?,?)
            """, (run, action, packed(actions[action]), quality, packed(stages), packed(costs)))

    dataset = SimpleNamespace(path=path, observation_protocol="metadata_v1", run_id="release",
                              host=SimpleNamespace(settings={"host": {}}, capacity=None),
                              control_release=True)
    result = pair_information_report(dataset, "ref", "peer")
    direct = result["continuation_comparison_by_source"]["qasper"]
    assert direct["common_bound_branches"] == 3 and direct["same_terminal_wire"] == 2
    assert direct["shared_reader_measurement_branches"] == 1
    assert direct["same_wire_independent_quality_disagreements"] == 1
    strata = result["continuation_comparison_by_source_and_pair_kind"]
    assert strata["qasper/precision"]["reference_only_convergence"] == 1
    assert strata["qasper/read_handoff"]["common_clear_directions"] == 2
    assert strata["qasper/read_handoff"]["agreeing_clear_directions"] == 1
    deltas = result["frozen_minus_reference_branch_deltas"]["qasper"]
    assert deltas["R3/quality"]["mean_delta"] == pytest.approx(0.6)
    assert "R3/reader_input_tokens" not in deltas
    coverage = registered_pair_coverage(dataset, "peer", ("ref",))
    assert coverage["by_source_and_material_budget"][0]["material_budget"] == 1024
    assert coverage["totals"]["precision/scheduled_pair_repeats"] == 1
    assert coverage["totals"]["precision/observed_quality_pair_repeats"] == 1
    assert coverage["totals"]["precision/observed_provider_cost_pair_repeats"] == 0
    assert coverage["totals"]["physical_reader/attempted_branches"] == 2
    assert coverage["totals"]["physical_reader/provider/reader_input_tokens"] == 70
    assert coverage["totals"]["physical_reader/local_tokenizer/reader_input_tokens"] == 140
    assert coverage["physical_reader_latency_ms"]["reader_wall_ms"]["measurements"] == 2

    budget = SimpleNamespace(state={"generation_requests": 0, "limits": {
        "generation_requests": None, "generation_tokens": None,
    }})
    monkeypatch.setattr(memory_control_outcome_run, "http_budget_scope",
                        lambda *a, **kw: nullcontext(budget))
    monkeypatch.setattr(memory_control_outcome_run, "ownership_client_configs", lambda _: ())
    monkeypatch.setattr(memory_control_outcome_run, "VLLMConfig", lambda **_: None)
    monkeypatch.setattr(memory_control_outcome_run, "VLLMClient", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(memory_control_outcome_run, "_current_comparison",
                        lambda _, declared: declared["comparison_protocol"])
    monkeypatch.setattr(memory_control_outcome_run, "request_reader",
                        lambda *a: pytest.fail("The already measured literal request was issued"))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""UPDATE outcome_runs SET config=json_set(config,'$.sealed',json('false'))
                      WHERE run_id='peer'""")
        stages = {"action_binding": actions["focus"], "first_action_effect": {"ok": True},
                  "reader_wire": {"seed": 42, "messages": ["shared"]}, "capacity": {}}
        db.execute("""UPDATE action_outcomes SET execution_status='prepared', task_result=?
                      WHERE run_id='peer' AND action_id='focus'""", (packed(stages),))
    coverage = registered_pair_coverage(dataset, "peer", ("ref",))
    assert not coverage["sealed"] and coverage["totals"]["status/prepared"] == 1
    assert coverage["totals"]["prepared_branches_with_exact_saved_response"] == 1
    assert coverage["totals"]["precision/observed_quality_pair_repeats"] == 0
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE outcome_runs SET config=json_set(config,'$.sealed',json('false'))")
    dispatched = memory_control_outcome_run.execute_outcomes(
        dataset, "peer", limit=1, state_ids=(1,), continuation_peer="ref",
    )
    assert dispatched["reader_requests"] == 0
    assert dispatched["reader_measurements_reused_from_peer"] == 1
    with closing(sqlite3.connect(path)) as db, db:
        result = db.execute("""SELECT task_result FROM action_outcomes
                              WHERE run_id='peer' AND action_id='focus'""").fetchone()[0]
        assert unpack(result)["reader_measurement_ref"]["run_id"] == "ref"
        db.execute("UPDATE outcome_runs SET config=json_set(config,'$.sealed',json('true'))")
        db.execute("UPDATE action_outcomes SET branch_seed=43 WHERE run_id='peer' AND action_id=?",
                   ("context",))
    with pytest.raises(ValueError, match="exact first action or repeat seed"):
        pair_information_report(dataset, "ref", "peer")


def test_paired_objective_gradient_and_globally_frozen_weighting() -> None:
    torch = pytest.importorskip("torch")
    head = build_object_head(8, architecture="object_mlp", width=12, heads=3, ffn_width=16,
                             numeric=True, quality_cost=True, dropout=0)
    states, actions = torch.rand(1, 3, 8), torch.rand(3, 8)
    owners = torch.zeros(3, dtype=torch.long)
    result = head(states, actions, owners, (torch.zeros(1, STATE_WIDTH),
                                          torch.zeros(3, ACTION_WIDTH)))
    result.quality_logits.retain_grad()
    result.cost_units.retain_grad()
    labels = {
        "observed_action_ids": ["a", "b"], "observed_values": {"a": 1.0, "b": 0.0},
        "preferences": [{"left": "a", "right": "b", "outcome": "left"}],
        "outcome_cost_tokens": {"b": 420},
        "paired_deltas": [
            {"left": "a", "right": "b", "common_quality_repeats": 1, "quality_known": True,
             "quality_delta": 1.0},
        ],
    }
    first = paired_state_losses(result.quality_logits, result.cost_units, ["a", "b", "c"],
                                labels, "u1")
    second = paired_state_losses(result.quality_logits, result.cost_units, ["a", "b", "c"],
                                 labels, "u2")
    assert set(second) - set(first) == {"quality_delta"}
    assert all(torch.equal(value, second[key]) for key, value in first.items())
    sum(second.values()).backward()
    assert result.quality_logits.grad[2].item() == 0 and result.quality_logits.grad[0].item() != 0
    assert result.cost_units.grad[0].item() == 0 and result.cost_units.grad[1].item() != 0
    assert head.evidence_output.weight.grad is None

    dual_success = {
        "observed_action_ids": ["a", "b"],
        "observed_values": {"a": 1.0, "b": 1.0},
        "success_cost_witness_values": {"a": 1.0, "b": 1.0},
        "observed_costs": {"a": {"reader_input_tokens": 70}, "b": {"reader_input_tokens": 100}},
        "success_cost_preferences": [
            {"left": "a", "right": "b", "outcome": "left", "axis": "reader_input_tokens"},
        ],
        "outcome_cost_tokens": {"a": 70, "b": 100},
    }
    reset = paired_state_losses(result.quality_logits, result.cost_units, ["a", "b", "c"],
                                dual_success, "u0-reset")
    separated = paired_state_losses(result.quality_logits, result.cost_units, ["a", "b", "c"],
                                    dual_success, "u1")
    assert set(reset) - set(separated) == {"success_cost_quality"}
    assert all(torch.equal(value, reset[key]) for key, value in separated.items())

    index = [StateIndex(i, source, "g", 0, "after_read", (0, 0))
             for i, source in enumerate(("a", "a", "a", "b"))]
    weights = source_weights(index, "g1")
    assert weights["a"] * 3 == pytest.approx(weights["b"])
    assert source_weights(index, "g0") == {"a": 1.0, "b": 1.0}


def test_pooled_replay_corrects_uneven_repetitions_inside_each_source() -> None:
    sources = ("a", "a", "b", "a", "b")
    index = [StateIndex(i, source, f"g{i}", 0, "after_read", (0, 0))
             for i, source in enumerate(sources)]
    mixed = [[0, 1, 2], [3, 4, 3]]
    weights = exposure_source_weights(index, mixed, policy_ids={3, 4},
                                      expected_sources={"a", "b"})
    assert weights == {0: .75, 1: .75, 2: 1.5, 3: .75, 4: 1.5}
    replay = [[0, 0, 1, 2], [0, 2]]
    control = exposure_source_weights(index[:3], replay, policy_ids=None,
                                      expected_sources={"a", "b"})
    assert control == {0: .5, 1: 1.5, 2: 1.5}
    with pytest.raises(ValueError, match="lacks a required source"):
        exposure_source_weights(index, mixed, policy_ids={3, 4}, expected_sources={"a", "b", "c"})


def test_dev_objective_and_representation_use_their_fixed_references() -> None:
    points = {
        "u0-reset": {"quality_points": 22., "reader_input_tokens": 1400},
        "u1": {"quality_points": 24., "reader_input_tokens": 1450},
        "u2": {"quality_points": 26., "reader_input_tokens": 1100},
    }
    contrasts = {
        "u1_vs_u0-reset": {"quality_interval_95": [-1., 5.]},
        "u2_vs_u0-reset": {"quality_interval_95": [-1.01, 9.]},
        "u2_vs_u1": {"quality_interval_95": [1., 3.]},
    }
    assert select_outcome_objective(points, contrasts) == ("u1", ["u0-reset", "u1"])
    effect = {"quality_interval_95": [-1., 3.], "token_savings_interval_95": [0., .2]}
    assert not select_numeric_representation(effect)
    effect["token_savings_interval_95"] = [.01, .2]
    assert select_numeric_representation(effect)


def test_holm_family_uses_null_centering_and_retains_unknown_comparisons() -> None:
    assert centered_bootstrap_pvalue([1., 2., 3., 4.], 2.5, 0.) == pytest.approx(.2)
    assert centered_bootstrap_pvalue([1., 2., 3., 4.], 2.5, 2.) == pytest.approx(.6)
    assert holm_adjust({"train": .005, "architecture": None, "efficiency": .013}) == {
        "train": .015, "efficiency": .026, "architecture": None,
    }


def test_terminal_failure_quality_and_handoff_ties_are_explicit() -> None:
    measured = {"grade": {"native_metrics": {"answer_f1": 0.8}}}
    failed = {"status": "reader_error"}
    pending = {"status": "ready"}
    assert _primary_group_quality("qasper", [measured, failed], failure_zero=True) == [0.8, 0]
    assert _primary_group_quality("qasper", [measured, pending], failure_zero=True) == []
    assert _primary_group_quality("qasper", [measured, failed], failure_zero=False) == []

    class Scores:
        def score(self, online: dict) -> PolicyScores:
            ids = [action["id"] for action in online["actions"]]
            return PolicyScores(ids, [0.1, 0.1], handoff_wins_ties=True)

    policy = SmallMemoryPolicy(Scores())
    state = MemoryControlState(task={"request": "an actual reading decision"})
    menu = [MemoryAction("read", "READ", "an object"),
            MemoryAction("handoff", "HANDOFF", "Reader")]
    assert policy.choose(state, menu) == "handoff"


def test_incremental_dispatch_advances_on_reused_measurements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import memory_control_outcome_stage as stage

    pending, requests = 3, []
    monkeypatch.setattr(stage, "MemoryControlDataset", lambda *_a, **_kw: object())
    monkeypatch.setattr(stage, "branch_state", lambda *_a: ({}, {"prepared": pending}, 3))
    monkeypatch.setattr(stage.time, "sleep", lambda _interval: None)

    def execute(_dataset: object, run: str, *, limit: int, share_reader_runs: tuple) -> dict:
        nonlocal pending
        assert run == DELTA and share_reader_runs == (CORE,)
        requests.append(limit)
        pending -= limit
        return {"reader_requests": 0, "reused_reader_measurements": limit}

    closed = []
    monkeypatch.setattr(stage, "execute_outcomes", execute)
    dispatch_delta(
        tmp_path, tmp_path / "data.sqlite3", "semantic_nav_delta_v2",
        lambda name, **payload: closed.append((name, payload["pending"])),
        slots=3, window=2, defer=1,
    )
    assert requests == [2, 1]
    assert closed == [("D_READER_WINDOW_CLOSED", 1), ("D_READER_WINDOW_CLOSED", 0)]
    assert len((tmp_path / "D-dispatch-invocations.jsonl").read_text().splitlines()) == 2


def test_confirmation_repeat_keeps_native_groups_and_original_cap(tmp_path: Path) -> None:
    tasks = [
        {"task_id": 10 * group + offset, "dataset": "source", "native_group": f"g{group}"}
        for group in range(20) for offset in (1, 2)
    ]
    original = {"role": "confirm", "arms": [{"name": str(i)} for i in range(13)],
                "tasks": tasks, "seed": 11, "predeclared_unevaluable_tasks": {}}
    path = tmp_path / "first.json"
    repeat = confirmation_repeat_population(original, path, reader_cap=13 * 43)
    assert repeat["seed"] != original["seed"]
    assert repeat["primary_plus_repeat_slots"] == 13 * 42
    assert repeat["measurement_repeat_of"] == str(path)
    group = repeat["tasks"][0]["native_group"]
    assert repeat["tasks"] == [row for row in tasks if row["native_group"] == group]


def test_confirmation_capacity_excludes_the_whole_group_after_partial_compaction(
    tmp_path: Path,
) -> None:
    data = tmp_path / "dataset.sqlite3"
    groups = [(1, "qasper", "exposed-paper"), (2, "qasper", "fresh-paper"),
              (3, "musique_full", "original-pair"), (4, "personamem_v2", "persona")]
    with closing(sqlite3.connect(data)) as db:
        db.executescript(SCHEMA + REVISION_SCHEMA)
        set_meta(db, "run_id", "confirmation-capacity")
        db.executemany(
            "INSERT INTO roots(id,dataset,native_group,raw_path,location) "
            "VALUES (?,?,?,'test','test')",
            groups,
        )
        db.executemany(
            "INSERT INTO experiment_groups VALUES (?,?,'confirm','test',1)",
            [(source, group) for _, source, group in groups],
        )
        db.executemany(
            "INSERT INTO tasks(id,root_id,split,source_row,native_id,query,setting,clean_role) "
            "VALUES (?,?,'test',0,'native','query','setting','confirm')",
            [(1, 1), (2, 1), (3, 2), (4, 3), (5, 3), (6, 4)],
        )
        db.commit()

    historical = tmp_path / "historical"
    tasks = [{"task_id": task, "dataset": "qasper", "native_group": "exposed-paper"}
             for task in (1, 2)]
    write_json(historical / "protocol.json", {"population": {"role": "confirm", "tasks": tasks}})
    write_json(historical / "run.json", {"status": "PARTIAL", "by_episode_status": {"scored": 1}})
    packet = historical / "episodes" / "1.json"
    write_json(packet, {**tasks[0], "status": "scored"})
    before = confirmation_capacity(data, 6, 11, [historical])
    assert before["excluded_exposed_native_groups"] == [("qasper", "exposed-paper")]
    assert before["actual_tasks"] == 4

    assert compact_scored_episode_packets(historical)["packets_compacted"] == 1
    assert packet.with_suffix(".json.gz").is_file() and not packet.exists()
    assert confirmation_capacity(data, 6, 11, [historical]) == before

def test_online_sampling_distinguishes_model_votes_from_coverage() -> None:
    branches = ["handoff", "read_2", "context_2"]
    measured = {"handoff", "read_2"}
    assert _online_priority_reasons(["read_2", "read_2"], branches, measured) == []
    assert _online_priority_reasons(["context_2", "context_2"], branches, measured) == [
        "unmeasured_top_action",
    ]
    assert _online_priority_reasons(["read_2", "read_7"], branches, measured) == [
        "model_disagreement",
    ]
    assert _online_priority_reasons(["read_7", "read_8"], branches, measured) == []
    assert _online_priority_reasons([], branches, measured) == []


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is unavailable")
def test_compaction_preserves_packets_until_the_complete_archive_is_available(
    tmp_path: Path,
) -> None:
    tasks = [
        {"task_id": 7, "dataset": "qasper", "native_group": "paper"},
        {"task_id": 8, "dataset": "qasper", "native_group": "paper"},
    ]
    protocol = {"population": {"tasks": tasks}}
    write_json(tmp_path / "protocol.json", protocol)
    write_json(tmp_path / "run.json", {"status": "COMPLETED", "by_episode_status": {"scored": 2}})
    first, second = (tmp_path / "episodes" / f"{row['task_id']}.json" for row in tasks)
    a, b = [{**row, "status": "scored", "reader_wire": {"material": "MiLAi 回执"}} for row in tasks]
    write_json(first, a)
    original = first.read_bytes()
    with pytest.raises(ValueError, match="source packets differ"):
        archive_completed_readout(tmp_path)
    assert first.read_bytes() == original
    assert not (tmp_path / "episodes.tar.zst").exists()

    write_json(tmp_path / "run.json", {"status": "PARTIAL", "by_episode_status": {"scored": 1}})
    pending = {**b, "status": "ready"}
    write_json(second, pending)
    pending_bytes = second.read_bytes()
    compacted = first.with_suffix(".json.gz")
    assert compact_scored_episode_packets(tmp_path)["packets_compacted"] == 1
    assert not first.exists()
    assert gzip.decompress(compacted.read_bytes()) == original
    assert second.read_bytes() == pending_bytes
    assert input_result(tmp_path) == (protocol, {7: a, 8: pending})
    first.write_bytes(original)
    assert compact_scored_episode_packets(tmp_path)["packets_compacted"] == 1
    assert not first.exists()

    write_json(tmp_path / "run.json", {"status": "COMPLETED", "by_episode_status": {"scored": 2}})
    write_json(second, b)
    first.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="Archive copy changed the bytes"):
        archive_completed_readout(tmp_path)
    assert first.is_file() and compacted.is_file() and second.is_file()
    first.unlink()

    receipt = archive_completed_readout(tmp_path)
    assert not first.exists() and not second.exists() and not compacted.exists()
    assert input_result(tmp_path) == (protocol, {7: a, 8: b})
    first.write_bytes(original)
    assert archive_completed_readout(tmp_path) == receipt
    assert not first.exists()


def test_confirmation_keeps_the_accepted_window_if_compaction_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_memory_control_v12_followthrough as followthrough

    plan, output = tmp_path / "plan.json", tmp_path / "confirmation"
    write_json(plan, {
        "role": "confirm", "capacity_registration": True, "power_registration": True,
        "confirmation_slots": 2, "tasks": [{"task_id": 1}, {"task_id": 2}],
        "arms": [{"name": "fixed", "policy": "B1", "observation_protocol": "metadata_v1"}],
    })
    window = {"status": "PARTIAL", "reader_requests_this_invocation": 1}
    monkeypatch.setattr(followthrough, "MemoryControlDataset", lambda *_a, **_kw: None)
    monkeypatch.setattr(followthrough, "evaluate_episodes", lambda *_a, **_kw: window)
    attempts = []

    def fail_compaction(root: Path) -> None:
        attempts.append(root)
        assert read_json(root / "dispatch-invocations.jsonl") == window
        assert read_json(root / "dispatch.json")["reader_requests_this_invocation"] == 1
        raise OSError("staging file could not be written")

    monkeypatch.setattr(followthrough, "compact_scored_episode_packets", fail_compaction)
    followthrough.run_registered_readout(SimpleNamespace(
        command="dispatch-confirmation-arm", plan=plan, output=output,
        slots=2, window=1, data=tmp_path / "dataset.sqlite3",
        registered_arm="fixed", inline_readout=True, single_window=True, device="cpu",
    ))
    assert attempts == [output]
    assert read_json(output / "dispatch-invocations.jsonl") == window


def test_confirmation_quality_support_does_not_impute_missing_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import milai_lab.scorers.memory_control_episode_metrics as metrics

    monkeypatch.setattr(metrics, "_primary_group_quality",
                        lambda *_a, **_kw: [_a[1][0]["quality"]])
    tasks = [
        {"task_id": i, "dataset": dataset, "native_group": f"g{i}"}
        for i, dataset in enumerate(metrics.SOURCES, 1)
    ]
    population = {
        "role": "confirm", "tasks": tasks, "confirmation_seeds": [11, 29, 47],
        "quality_noninferiority_points": 1.0, "reader_input_savings_floor": 0.15,
    }
    warm = {r["task_id"]: {"quality": 0.8} for r in tasks}
    cold = {r["task_id"]: {"quality": 0.5} for r in tasks}
    result = _paired_metrics(
        population, [warm] * 3, [cold], [11, 29, 47], [None], repeats=10, seed=1,
    )
    assert result["quality_path_supported"] and result["paired_quality_complete"]
    assert not result["cost_path_supported"] and not result["paired_reader_input_complete"]
    assert result["reader_input_token_savings"] is None
    assert all(seed["reader_input_token_savings"] is None for seed in result["by_seed"])
    assert result["seed_spread"]["reader_input_token_savings"]["observed_seeds"] == 0


def test_confirmation_retains_matched_seed_effects_on_the_common_native_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import milai_lab.scorers.memory_control_episode_metrics as metrics

    tasks = [
        {"task_id": 100 * i + 10 * group + j, "dataset": source, "native_group": str(group)}
        for i, source in enumerate(metrics.SOURCES)
        for group in range(2) for j in range(2 if source == metrics.MUSIQUE else 1)
    ]
    seeds = [11, 29, 47]
    population = {
        "role": "confirm", "tasks": tasks, "confirmation_seeds": seeds,
        "quality_noninferiority_points": 1.0, "reader_input_savings_floor": 0.15,
    }

    def observed(quality: float, input_tokens: int) -> dict:
        return {row["task_id"]: {**row, "status": "scored", "grade": {"native_metrics": {
            "answer_f1": quality, "accuracy": quality, "answer_em": quality,
            "support_f1": quality, "sufficiency_correct": True,
            "gold_answerable": row["task_id"] % 10 == 0,
        }}, "costs": {"reader_input_tokens": input_tokens,
                      "reader_request_attempted": True,
                      "episode_live_readout_ms": input_tokens}} for row in tasks}

    baseline = [observed(quality, cost) for quality, cost in ((.4, 1000), (.5, 500), (.55, 2000))]
    policies = [observed(quality, cost) for quality, cost in ((.5, 700), (.45, 450), (.75, 1700))]
    result = _paired_metrics(
        population, policies, [baseline[2], baseline[0], baseline[1]], seeds, [47, 11, 29],
        repeats=40, seed=123,
    )
    assert result["interval_conditioned_on_model_seeds"] == seeds
    assert result["independent_groups"] == {source: 2 for source in metrics.SOURCES}
    assert [item["baseline_seed"] for item in result["by_seed"]] == seeds
    assert [r["quality_delta_points"] for r in result["by_seed"]] == pytest.approx([10, -5, 20])
    assert result["by_seed"][1]["quality_interval_95"] == pytest.approx([-5, -5])
    assert result["seed_spread"]["quality_delta_points"]["range"] == pytest.approx([-5, 20])
    assert result["reader_input_token_savings"] == pytest.approx(1 - 2850 / 3500)
    assert result["seed_spread"]["reader_input_token_savings"]["mean"] == pytest.approx(.55 / 3)

    latency_inputs = {}
    for label, rows in [(None, baseline[0]), *zip(seeds, policies, strict=True)]:
        latency_inputs[Path(str(label))] = ({
            "population": population, "arm": {"seed": label}, "comparison": {},
            "readout_schedule": "inline",
        }, rows)
    monkeypatch.setattr(metrics, "input_result", latency_inputs.__getitem__)
    candidate_paths, baseline_path = [Path(str(s)) for s in seeds], Path("None")
    timing = metrics.paired_inline_latency(candidate_paths, baseline_path, repeats=40, seed=123)
    assert timing["paired_latency_complete"]
    assert [row["latency_saving"] for row in timing["by_seed"]] == pytest.approx([.3, .55, -.7])
    assert timing["latency_saving"] == pytest.approx(.15 / 3)
    assert {source: row["paired_groups"] for source, row in timing["by_source"].items()} == {
        source: 2 for source in metrics.SOURCES
    }
    offsets = dict(zip([*candidate_paths, baseline_path], [100, 200, 400, 50], strict=True))
    timing_with_setup = metrics.paired_inline_latency(
        candidate_paths, baseline_path, repeats=40, seed=123, policy_load_ms_per_task=offsets,
    )
    assert timing_with_setup["latency_saving_interval_95"] == timing["latency_saving_interval_95"]
    with_setup = timing_with_setup["with_amortized_policy_load"]
    assert with_setup["paired_latency_complete"]
    assert with_setup["baseline_macro_latency_ms"] == pytest.approx(1050)
    assert with_setup["candidate_macro_latency_ms"] == pytest.approx((800 + 650 + 2100) / 3)
    expected = 1 - (800 + 650 + 2100) / (3 * 1050)
    assert with_setup["latency_saving_interval_95"] == pytest.approx([expected, expected])
    del offsets[candidate_paths[0]]
    missing = metrics.paired_inline_latency(
        candidate_paths, baseline_path, repeats=40, seed=123, policy_load_ms_per_task=offsets,
    )["with_amortized_policy_load"]
    assert not missing["paired_latency_complete"] and missing["latency_saving"] is None


def test_confirmation_power_aligns_the_measured_baseline_seeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import milai_lab.runners.memory_control_confirmation as confirmation

    sources = confirmation.SOURCES
    tasks = [
        {"task_id": 10 * i + j, "dataset": source, "native_group": str(j)}
        for i, source in enumerate(sources) for j in range(2)
    ]
    population = {"role": "dev", "tasks": tasks}
    evidence = {}
    for seed, baseline, advantage in ((11, .3, .1), (29, .4, .2), (47, .5, .3)):
        for label, quality in (("base", baseline), ("fit", baseline + advantage)):
            proto = {"population": population, "arm": {"seed": seed}, "comparison": {}}
            rows = {r["task_id"]: {"quality": quality, "costs": {"reader_input_tokens": 100}}
                    for r in tasks}
            evidence[Path(f"{label}-{seed}")] = proto, rows
    monkeypatch.setattr(confirmation, "input_result", evidence.__getitem__)
    monkeypatch.setattr(confirmation, "_primary_group_quality",
                        lambda *_a, **_kw: [_a[1][0]["quality"]])
    capacity = {"dataset_run_id": "test", "seed": 11, "target_tasks": 6, "selected_groups": {
        src: [{"native_group": str(i), "tasks": 1} for i in range(2)] for src in sources
    }}
    result = plan_confirmation_power(
        capacity, [Path(f"fit-{s}") for s in (11, 29, 47)],
        [Path(f"base-{s}") for s in (47, 11, 29)],
        draws=3, repeats=6, analysis_seed=11, primary_comparisons=3,
    )
    assert result["conservative_dev_design"]["seed_quality_delta_points"] == pytest.approx(
        [10, 20, 30],
    )
    assert result["conservative_dev_design"]["true_quality_delta_points"] == pytest.approx(10)
    assert result["confirm_labels_read"] == 0


def test_rebinding_verifies_the_actual_target_corpus() -> None:
    row = {
        "id": 3, "task_id": 7, "dataset": "source", "native_group": "one", "prefix": [],
        "candidates": [1], "material_budget": 2048, "experiment_role": "train",
    }

    def session(body: str) -> SimpleNamespace:
        def observe(actions: list) -> dict:
            return {"observation": {"pending_candidates": [], "visible_evidence": [body]},
                    "actions": actions}

        return SimpleNamespace(pool=object(), online=observe, feasible_menu=lambda a: a)

    parent = session("from the parent release")
    target = session("changed in the target release")

    def target_replay(_db: object, _sid: int, pool: object = None) -> tuple:
        return row, parent if pool is parent.pool else target, []

    inputs = SimpleNamespace(
        parent=SimpleNamespace(replay=lambda *_args: (row, parent, [])),
        data=SimpleNamespace(replay=target_replay), role="train", source=object(), target=object(),
    )
    with pytest.raises(ValueError, match="Parent before-state or legal menu changed"):
        _rebind_state(inputs, 3)
