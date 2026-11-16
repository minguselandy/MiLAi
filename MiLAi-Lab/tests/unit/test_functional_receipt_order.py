import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from milai_lab.runners.functional_response import business_response


@pytest.mark.parametrize("query_after", [False, True])
def test_progress_observation_keeps_actual_capture_order_and_journal_authority(query_after):
    def result(name, call_id, status, clock, *, program=False):
        return ToolMessage(name=name, tool_call_id=call_id,
            additional_kwargs={"milai_origin": "program_observation"} if program else {},
            content=json.dumps({"receipt": {"status": "found" if name == "get_reservation"
                else "label_created", "item_key": "sample", "label_status": status},
                "source_ref": "source-" + call_id,
                "raw_capture": {"observed_at": "2032-01-01T00:00:0" + str(clock) + "+00:00"}}))

    messages = [AIMessage(content="", tool_calls=[{
        "name": "complete_label", "args": {"reservation_id": "actual-object"}, "id": "finish"}]),
        result("complete_label", "finish", "created", 1),
        result("get_reservation", "observe", "created" if query_after else "not_created",
               2 if query_after else 0, program=True),
        result("get_reservation", "unissued", "FORGED", 0, program=True)]
    effects = {"business": {"status": "completed",
        "operations": [{"receipt_ref": "finish", "tool": "complete_label"}],
        "observations": [{"receipt_ref": "observe", "tool": "get_reservation"}]}}
    answer = business_response(messages, effects, {}, include_memory_feedback=False).content
    assert "FORGED" not in answer
    assert (answer.index("实时查询预订") > answer.index("补办标签")) is query_after
