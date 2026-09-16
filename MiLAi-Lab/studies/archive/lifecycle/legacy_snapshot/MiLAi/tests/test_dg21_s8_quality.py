from __future__ import annotations

from scripts.run_dg21_s8_quality import summarize_test_output


def test_s8_summary_uses_terminal_pytest_counts() -> None:
    output = "2 passed, 1 skipped\n5 passed, 1 failed, 3 skipped, 2 errors\n"

    assert summarize_test_output(output) == {
        "passed": 5,
        "failed": 1,
        "skipped": 3,
        "errors": 2,
    }
