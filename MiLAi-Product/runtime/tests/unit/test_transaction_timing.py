from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from milai.observability.metrics import OperationTimer, request_operation_timer
from milai.persistence import Database


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "outcome", ["success", "error", "cancel", "suppressed", "entry_error", "exit_error"]
)
def test_transaction_timing_preserves_driver_context_semantics(enabled, outcome):
    timer = OperationTimer() if enabled else None
    token = request_operation_timer.set(timer)
    events = []
    failure = KeyboardInterrupt() if outcome == "cancel" else ValueError("fixture")

    @contextmanager
    def transaction():
        events.append("enter")
        if outcome == "entry_error":
            raise failure
        try:
            yield
        except BaseException as exc:
            assert exc is failure
            events.append("rollback")
            if outcome != "suppressed":
                raise
        else:
            events.append("commit")
            if outcome == "exit_error":
                raise failure

    database = object.__new__(Database)
    connection = Mock(transaction=transaction)

    def invoke():
        with database._transaction(connection):
            events.append("body")
            if outcome in {"error", "cancel", "suppressed"}:
                raise failure

    try:
        if outcome in {"success", "suppressed"}:
            invoke()
        else:
            with pytest.raises(type(failure)) as caught:
                invoke()
            assert caught.value is failure
        assert events == (
            ["enter"]
            if outcome == "entry_error"
            else [
                "enter",
                "body",
                "rollback" if outcome in {"error", "cancel", "suppressed"} else "commit",
            ]
        )
        if timer is not None:
            assert timer.counts == {
                "db_transaction_enter_ms": 1,
                **({} if outcome == "entry_error" else {"db_transaction_exit_ms": 1}),
            }
    finally:
        request_operation_timer.reset(token)
