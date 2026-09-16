import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0224_native_wma_provider import NativeProvider, parse_evidence, parse_judge


def test_actual_multimodal_payload_usage_and_budget(tmp_path):
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append((request.url, body))
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 20})
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
            },
        )

    p = NativeProvider(
        tmp_path, max_generations=1, max_http=2, transport=httpx.MockTransport(respond)
    )
    assert not seen
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
        }
    ]
    result = p.generate("judge", messages)
    assert result["finish_reason"] == "length"  # caller rejects protocol, usage remains charged
    assert p.usage["total_tokens"] == 23
    assert seen[0][1]["messages"] == seen[1][1]["messages"] == messages
    assert all(str(url).startswith("http://127.0.0.1:7860/") for url, _ in seen)
    assert all(body["chat_template_kwargs"] == {"enable_thinking": False} for _, body in seen)
    with pytest.raises(RuntimeError, match="budget"):
        p.generate("judge", messages)
    assert len(seen) == 2
    assert len(list(tmp_path.glob("*.response.raw"))) == 2
    p.close()


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"prompt_tokens": 19, "completion_tokens": 3, "total_tokens": 22},
        {"prompt_tokens": True, "completion_tokens": 3, "total_tokens": 4},
    ],
)
def test_unknown_usage_never_allows_next_request(tmp_path, usage):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200, json={"count": 20} if request.url.path == "/tokenize" else {"usage": usage}
        )

    p = NativeProvider(
        tmp_path, max_generations=3, max_http=6, transport=httpx.MockTransport(respond)
    )
    with pytest.raises(ValueError, match="usage"):
        p.generate("answer", [{"role": "user", "content": "x"}])
    assert json.loads((tmp_path / "blocked.json").read_text())["unresolved_usage"] is True
    with pytest.raises(RuntimeError, match="blocked"):
        p.generate("answer", [{"role": "user", "content": "x"}])
    assert len(seen) == p.http_attempts == 2
    p.close()


def test_http_error_attempt_no_retry(tmp_path):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "http://external.invalid"})

    p = NativeProvider(
        tmp_path, max_generations=1, max_http=2, transport=httpx.MockTransport(respond)
    )
    with pytest.raises(httpx.HTTPStatusError):
        p.generate("answer", [{"role": "user", "content": "x"}])
    assert len(seen) == p.http_attempts == 1 and p.generations == 0 and p.blocked
    p.close()


@pytest.mark.parametrize("label", ["Correct", "Hallucination", "Omission"])
def test_strict_labels_and_complete_fence(label):
    raw = json.dumps({"reasoning": "synthetic", "evaluation_result": label})
    assert parse_judge(raw, "stop")["evaluation_result"] == label
    assert parse_judge("```json\n" + raw + "\n```", "stop")["evaluation_result"] == label


@pytest.mark.parametrize(
    "raw,finish",
    [
        ('{"reasoning":"x"}', "stop"),
        ('{"reasoning":"x","evaluation_result":"correct"}', "stop"),
        ('{"reasoning":"x","evaluation_result":"Correct"}', "length"),
        ('```json\n{"reasoning":"x","evaluation_result":"Correct"}', "stop"),
        ('{"reasoning":"x","evaluation_result":"Correct","evaluation_result":"Omission"}', "stop"),
        ('{"reasoning":1e999,"evaluation_result":"Correct"}', "stop"),
    ],
)
def test_invalid_judge_is_not_omission(raw, finish):
    with pytest.raises(ValueError):
        parse_judge(raw, finish)


def test_evidence_exact_counts():
    assert (
        parse_evidence('{"reasoning":"x","covered_count":1,"total":2}', "stop", 2)["covered_count"]
        == 1
    )
    for covered, total in [(-1, 2), (3, 2), (1, 3), (True, 2)]:
        with pytest.raises(ValueError):
            parse_evidence(
                json.dumps({"reasoning": "x", "covered_count": covered, "total": total}), "stop", 2
            )
    with pytest.raises(ValueError):
        parse_evidence('{"reasoning":"x","total":2}', "stop", 2)
