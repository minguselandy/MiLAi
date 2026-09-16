from __future__ import annotations

from scripts.run_dg17_local_gate import gate_commands


def test_dg17_local_gate_covers_runtime_contracts_and_dg17_static_checks() -> None:
    commands = {command.name: command for command in gate_commands()}

    assert set(commands) == {
        "runtime-unit",
        "runtime-contract",
        "runtime-strict-mypy",
        "runtime-ruff",
        "dg17-tests",
        "dg17-ruff",
        "dg17-strict-mypy",
    }
    assert commands["runtime-unit"].argv[-1] == "tests/unit"
    assert commands["runtime-contract"].argv[-1] == "tests/contract"
    assert "test_dg17_q6_matched.py" in " ".join(commands["dg17-tests"].argv)
    assert "test_dg16_reader_stability.py" in " ".join(
        commands["dg17-tests"].argv
    )
    assert "run_dg16_reader_stability.py" in " ".join(
        commands["dg17-ruff"].argv
    )
    assert commands["dg17-tests"].argv[0].endswith("runtime/.venv/bin/python")
    assert commands["dg17-tests"].env["PYTHONPATH"].endswith("runtime/src")
