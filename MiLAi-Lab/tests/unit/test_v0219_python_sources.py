import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_python_sources import redact_literal_credentials


def represent(source: str) -> dict:
    raw = source.encode()
    return redact_literal_credentials(raw, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("target", [
    "API_KEY", "PASSWORD: str", "client.api_key", 'os.environ["API_KEY"]',
])
def test_assignment_literal_only(target):
    result = represent(f'{target} = "private-test-value"  # preserve comment\nprint(42)\n')
    assert "private-test-value" not in result["content"]
    assert result["content"].endswith(
        '"REDACTED_LITERAL_CREDENTIAL"  # preserve comment\nprint(42)\n'
    )
    assert result["redacted_literal_count"] == 1


def test_keyword_and_multiple_replacements():
    result = represent('connect(key="a", token="b", endpoint="keep-me")\n')
    assert result["content"] == (
        'connect(key="REDACTED_LITERAL_CREDENTIAL", '
        'token="REDACTED_LITERAL_CREDENTIAL", endpoint="keep-me")\n'
    )
    assert result["redacted_literal_count"] == 2


def test_nonliteral_and_unrecognized_values_unchanged():
    raw = 'API_KEY = os.environ["API_KEY"]\nordinary_name = "not-classified"\n'
    result = represent(raw)
    assert result["content"] == raw
    assert result["redacted_literal_count"] == 0
    assert "not comprehensive" in result["limits"]


def test_utf8_offsets_and_multiline_literal():
    source = 'label="中文"; API_KEY = """first\nsecond"""; keep="é"\n'
    result = represent(source)
    assert result["content"] == 'label="中文"; API_KEY = "REDACTED_LITERAL_CREDENTIAL"; keep="é"\n'


def test_duplicate_target_span_counted_once():
    assert represent('API_KEY = SECRET = "value"\n')["redacted_literal_count"] == 1


def test_hash_guard():
    with pytest.raises(ValueError, match="SOURCE_HASH_CHANGED"):
        redact_literal_credentials(b'API_KEY = "value"', "0" * 64)


def test_syntax_failure_does_not_echo_source():
    with pytest.raises(ValueError) as error:
        represent('API_KEY = "DO_NOT_ECHO')
    assert str(error.value) == "PYTHON_SOURCE_UNPARSEABLE_NO_SOURCE_ECHO"
    assert error.value.__suppress_context__


def test_no_execution(tmp_path):
    marker = tmp_path / "must-not-exist"
    result = represent(f'open({str(marker)!r}, "w").write("executed")\nAPI_KEY="value"\n')
    assert not marker.exists()
    assert result["foreign_code_executed"] is False
