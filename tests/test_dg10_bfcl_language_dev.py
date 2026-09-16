from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_language_dev as language_dev
from scripts import run_dg10_bfcl_language_dev_scoring_v2 as scoring_v2


def test_language_contract_freezes_exact_fourteen_without_opening_labels() -> None:
    report = language_dev.build_contract(
        language_dev.PLAN, bfcl_contract.DEFAULT_BFCL_ROOT
    )

    ids = report["generation_schedule"]["ordered_case_ids"]
    assert report["status"] == (
        "BFCL_LANGUAGE_DEV_GENERATION_FROZEN_LABELS_NOT_OPENED"
    )
    assert len(ids) == len(set(ids)) == 14
    assert sum("simple_java_" in case_id for case_id in ids) == 9
    assert sum("simple_javascript_" in case_id for case_id in ids) == 5
    assert report["bfcl_dev_answer_labels_opened"] is False
    assert report["bfcl_test_labels_or_outputs_opened"] is False
    assert report["test_access_authorized"] is False


class _ReturnFormat:
    JAVA = "java"
    JAVASCRIPT = "javascript"


class _Decoder:
    ReturnFormat = _ReturnFormat

    @staticmethod
    def ast_parse(
        response: str, *, language: str, has_tool_call_tag: bool
    ) -> list[dict[str, Any]]:
        assert response == "[fetch(value=\"1\")]"
        assert language in {"java", "javascript"}
        assert has_tool_call_tag is False
        return [{"fetch": {"value": "1"}}]


class _Language:
    JAVA = "java-language"
    JAVASCRIPT = "javascript-language"


class _Checker:
    Language = _Language
    invocations = 0
    last_language: ClassVar[str | None] = None

    @classmethod
    def ast_checker(cls, *_args: Any) -> dict[str, Any]:
        cls.invocations += 1
        cls.last_language = _args[3]
        return {"valid": True}


def test_language_scoring_uses_language_specific_decoder_and_checker() -> None:
    source = {
        "function": [
            {
                "name": "fetch",
                "description": "fixture",
                "parameters": {
                    "type": "dict",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ]
    }
    ground_truth = [{"fetch": {"value": ["1"]}}]

    result = language_dev._score_one(
        category="simple_java",
        source=source,
        response_text='[fetch(value="1")]',
        ground_truth=ground_truth,
        decoder_utils=_Decoder,
        checker=_Checker,
    )

    assert result["decoder_success"] is True
    assert result["official_checker_invocations"] == 1
    assert result["official_checker_valid"] is True
    assert result["tool_selection_correct"] is True
    assert _Checker.last_language == _Language.JAVA


def test_language_decoder_failure_is_invalid_without_checker_call() -> None:
    class FailingDecoder:
        ReturnFormat = _ReturnFormat

        @staticmethod
        def ast_parse(*_args: Any, **_kwargs: Any) -> Any:
            raise SyntaxError("fixture")

    before = _Checker.invocations
    result = language_dev._score_one(
        category="simple_javascript",
        source={"function": []},
        response_text="not valid",
        ground_truth=[{"fetch": {}}],
        decoder_utils=FailingDecoder,
        checker=_Checker,
    )

    assert result["decoder_success"] is False
    assert result["official_checker_invocations"] == 0
    assert result["official_checker_valid"] is False
    assert result["checker_error_type"] == "ast_decoder:decoder_failed"
    assert _Checker.invocations == before


def test_language_runner_source_is_under_repository() -> None:
    assert Path(language_dev.__file__).resolve().is_relative_to(language_dev.ROOT)


def test_language_v2_loads_real_parsers_and_checker_without_provider_sdks() -> None:
    checker, decoder, hashes = scoring_v2._load_checker_and_decoder(
        bfcl_contract.DEFAULT_BFCL_ROOT
    )

    probe = scoring_v2._synthetic_probe(checker, decoder)

    assert probe["status"] == "PASS"
    assert probe["fixture_count"] == 2
    assert all(item["valid"] for item in probe["results"])
    assert probe["benchmark_labels_opened"] is False
    assert hashes["official_ast_checker"] == language_dev.build_contract(
        language_dev.PLAN, bfcl_contract.DEFAULT_BFCL_ROOT
    )["byte_closure"]["official_ast_checker"]["sha256"]
