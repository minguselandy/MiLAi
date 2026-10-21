"""Actual declared pixel bounds in both pinned Transformer environments; no model weights."""
import json
import socket

import httpx
import pytest
from PIL import Image
from test_lme_protocol import UPSTREAM
from test_v13_5_functional_integration import prepared

from milai_lab.datasets.lme_protocol import NativeLmeProtocol
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.image_capacity import ImageHostCapacity
from milai_lab.runners.functional import prepare
from milai_lab.runners.lme_reader import predict_reader


@pytest.fixture(scope="module")
def capacity():
    return ImageHostCapacity({"model": "mechanical", "tokenizer_path": "/cra/qwen36-35B",
        "context_tokens": 65536, "output_tokens": 128, "batch_source_tokens": 1024,
        "safety_tokens": 32, "related_reserve_tokens": 0, "schema_reserve_tokens": 0,
        "source_message_overhead_tokens": 2})


@pytest.mark.parametrize("shape,expected", [((64, 128), 72), ((2048, 1024), 2048)])
def test_local_model_pixel_bounds_are_applied(capacity, shape, expected):
    assert capacity.image_processor.size == {"shortest_edge": 65536, "longest_edge": 16777216}
    result = capacity.image_processor(images=[Image.new("RGB", shape)], return_tensors="np")
    count = int(result["image_grid_thw"][0].prod()) // capacity.image_processor.merge_size**2
    assert count == expected


def test_fixed_reader_preserves_two_images_and_uses_native_image_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("REAL_NETWORK_FORBIDDEN"))
    prepared(tmp_path, native=False)
    settings = read_json(tmp_path/"settings.json")
    settings["capacity"]["tokenizer_path"] = "/cra/qwen36-35B"
    config = tmp_path/"image-settings.json"
    write_json(config, settings)
    runtime = tmp_path/"image-runtime"
    prepare(runtime, config, source_version="mechanical")
    capacity = ImageHostCapacity(settings["capacity"])
    source, question = tmp_path/"source.png", tmp_path/"question.png"
    Image.new("RGB", (1280, 720), "red").save(source)
    Image.new("RGB", (800, 480), "blue").save(question)
    wires = []

    def respond(request):
        wires.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "\\boxed{A}"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}})

    result = predict_reader(runtime, tmp_path/"reader", NativeLmeProtocol(UPSTREAM), capacity,
        domain="web", query="Synthetic question", query_image=str(question),
        context=[{"type": "image", "value": str(source)}], source_version="mechanical",
        transport=httpx.MockTransport(respond))
    assert result["status"] == "COMPLETED" and len(wires) == 1
    images = [p for p in wires[0]["messages"][1]["content"] if p["type"] == "image_url"]
    assert len(images) == 2
    call = read_json(tmp_path/"reader/reader/call.json")
    event = next(e for e in call["usage"] if e["event"] == "vllm_response")
    assert event["capacity"]["prompt_tokens"] >= 880+375
    assert event["capacity"]["identity"]["image_processor_config"]["size"]["shortest_edge"] == 65536
