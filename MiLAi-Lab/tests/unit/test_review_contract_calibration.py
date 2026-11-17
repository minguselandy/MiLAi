"""Calibration truth stays separate from model input and natural research claims."""

import json

from prepare_review_contract_calibration import KINDS, build_calibration


def test_real_visibility_schema_and_partial_world_cases_are_frozen_without_models(tmp_path):
    output = tmp_path / "calibration"
    report = build_calibration(output, worlds=2, seed=71)
    cases = json.loads((output / "judge-cases.json").read_text())
    truths = json.loads((output / "private-truth.json").read_text())
    by_code = {row["case_code"]: row for row in cases}
    assert report["cases"] == 18 and report["source_worlds"] == 2
    assert report["kind_counts"] == dict.fromkeys(KINDS, 2)
    assert report["Reader_calls"] == report["judge_calls"] == 0
    assert report["actual_source_revocations"] == 2
    assert report["actual_source_captures"] == 9
    assert report["actual_common_open_calls"] == 13
    for private in truths:
        public = by_code[private["case_code"]]
        assert not {"world", "kind", "expected", "proof", "grade", "pilot"} & public.keys()
        assert public["observation_origin"] == "scripted_protocol_fixture_not_model_first"
        expected = private["expected"]
        if private["kind"] == "format":
            assert public["first_observation"]["status"] == "FAILED"
            assert private["proof"]["actual_common_schema_rejection"] == "ValidationError"
            assert (
                expected["material_status"] == "SUFFICIENT" and expected["task_resolution"] is False
            )
        elif private["kind"] == "revoked":
            assert private["proof"]["actual_common_source_revocation"] is True
            assert all(not p.get("evidence") for p in public["packet"]["evidence"])
            assert expected["material_status"] == "INSUFFICIENT"
        elif private["kind"] == "unknown_execution":
            assert public["first_observation"]["status"] == "UNKNOWN"
            assert expected["task_resolution"] is None
        elif private["kind"] == "interval_unknown":
            assert private["proof"]["possible_query_truths"] == [False, True]
            assert expected["task_resolution"] is None and expected["answer_grounding"] is False
        elif private["kind"] == "supported":
            assert expected["task_resolution"] is True
        elif private["kind"] == "missing":
            assert public["first_observation"]["answer_fields"]["evidence"] == []
        elif private["kind"] == "question_role":
            assert expected["material_status"] == "SUFFICIENT"
            assert expected["task_resolution"] is False and expected["answer_grounding"] is False
    pilot = json.loads((output / "pilot-case-codes.json").read_text())
    assert len(pilot) == 10 and set(pilot) <= set(by_code)


def test_blinding_and_world_parameters_are_reproducible_without_reusing_source_ids(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    build_calibration(first, worlds=2, seed=71)
    build_calibration(second, worlds=2, seed=71)
    a = json.loads((first / "private-truth.json").read_text())
    b = json.loads((second / "private-truth.json").read_text())
    assert a == b
    left = json.loads((first / "judge-cases.json").read_text())
    right = json.loads((second / "judge-cases.json").read_text())
    # Source addressing remains runtime-created. Judge-visible literal text and
    # observations, rather than original source identifiers, define the fixture.
    assert left == right
