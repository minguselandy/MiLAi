from milai_lab.methods.horizon_diagnostic import score


def test_official_permissiveness_does_not_hide_ambiguity() -> None:
    result = score("A or B", "A", "B")
    assert result["official_correct"] is True
    assert result["strict_format_valid"] is False
    assert result["multiple_letters"] is True
    assert score("Because evidence matters", "B", "")["official_correct"] is True
    assert score("Because evidence matters", "B", "")["strict_correct"] is False


def test_old_option_signal_does_not_claim_use_failure() -> None:
    result = score("C", "A", "C")
    assert result["old_option_selected"] is True and result["official_correct"] is False
    assert result["semantic_use_verdict"] == "UNSCORED_REQUIRES_PRESENTED_SUPPORT_ADJUDICATION"
    abstention = score("I cannot determine this.", "A", "")
    assert abstention["official_correct"] is False
    assert abstention["strict_format_valid"] is False
