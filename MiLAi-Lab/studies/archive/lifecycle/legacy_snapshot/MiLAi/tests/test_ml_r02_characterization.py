from evals.ml_r02.characterization import characterize


def test_mlr02_b0_characterization_is_deterministic_and_fail_closed() -> None:
    first = characterize()
    second = characterize()

    assert first == second
    assert first["external_model_calls"] == 0
    assert first["formal_holdout_consumed"] is False
    assert first["T"]["bounded_complete"] == {
        "status": "COMPLETE",
        "closure_complete": True,
    }
    assert first["T"]["max_items_hit"]["closure_complete"] is False
    assert first["T"]["ambiguous_time"]["closure_complete"] is False
    assert first["F"]["deterministic_replay"] is True
    assert first["F"]["assistant_contamination"] is False
    assert first["F"]["revoked_contamination"] is False
    assert first["F"]["canonical_mutation"] is False
