"""Preserve failed/partial first readouts instead of manufacturing valid answers."""

import pytest

from run_collected_handoff_readouts import parse_readout


@pytest.mark.parametrize(
    "finish,body,status",
    [
        ("stop", '{"answer":"answer with qualification"}', "COMPLETED"),
        ("length", '{"answer":"apparently valid but truncated"}', "FAILED"),
        ("stop", '{"answer":42}', "FAILED"),
        ("stop", "not JSON", "FAILED"),
    ],
)
def test_first_output_status_is_not_repaired(finish, body, status):
    response = {"choices": [{"finish_reason": finish, "message": {"content": body}}]}
    result = parse_readout(response)
    assert result["status"] == status
    assert (result["answer"] is None) == (status == "FAILED")
    assert response["choices"][0]["message"]["content"] == body
