from summarize_continuous_view_work import summarize_trace


def test_rejected_delivery_keeps_executed_builder_work_once():
    common = {"event": "memory_control_step", "step": 0,
              "actions": [{"id": "refresh", "kind": "REFRESH_VIEW"}], "selected": "refresh"}
    result = summarize_trace([
        {**common, "phase": "decision_input", "before": {"views": [{"pending_events": [1]}]}},
        {**common, "phase": "decision_output", "control_wall_seconds": 0.1},
        {**common, "phase": "operation_result", "control_wall_seconds": 0.1,
         "operation_wall_seconds": 0.4, "result": {"ok": False,
          "status": "material_budget_exhausted", "revision": 1,
          "report": {"action": "build", "source_bodies_delivered": 10, "elapsed_ms": 200}}},
        {"event": "milai_retrieve_result", "retrieval_wall_seconds": 0.7}])
    assert result["counts"]["selected:REFRESH_VIEW"] == 1
    assert result["counts"]["operation_returns:REFRESH_VIEW"] == 1
    assert result["counts"]["operation_ok:REFRESH_VIEW"] == 0
    assert result["counts"]["view_report_action:build"] == 1
    assert result["counts"]["view_report_sum:source_bodies_delivered"] == 10
    assert result["seconds"] == {"control_wall_seconds": 0.1,
        "operation_wall_seconds_inclusive": 0.4,
        "view_builder_elapsed_seconds_nested": 0.2, "retrieval_wall_seconds_inclusive": 0.7}


def test_selection_without_operation_return_does_not_become_execution():
    result = summarize_trace([{"event": "memory_control_step", "phase": "decision_output",
        "step": 0, "actions": [{"id": "reuse", "kind": "USE_VIEW"}], "selected": "reuse"}])
    assert result["counts"] == {"selected:USE_VIEW": 1}
    assert result["operations"] == []
