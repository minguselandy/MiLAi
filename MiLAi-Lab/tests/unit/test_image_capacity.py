"""Native local image preprocessing, synthetic pixels, no weights or HTTP requests."""
import base64
import copy
import io
import json

import httpx
import pytest
from PIL import Image
from transformers.models.qwen3_vl.processing_qwen3_vl import Qwen3VLProcessor

from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.image_capacity import ImageHostCapacity


@pytest.fixture(scope="module")
def capacity():
    return ImageHostCapacity({"model": "local-image-reader-mechanical-test",
        "tokenizer_path": "/cra/qwen36-35B", "context_tokens": 65536, "output_tokens": 128,
        "safety_tokens": 32, "batch_source_tokens": 1024,
        "related_reserve_tokens": 0, "schema_reserve_tokens": 0,
        "source_message_overhead_tokens": 2, "enable_thinking": True})


def image_part(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}}


@pytest.mark.parametrize("thinking", [False, True])
def test_two_images_match_native_processor_expansion_and_preserve_wire(capacity, thinking):
    images = [Image.new("RGB", (800, 600)), Image.new("RGB", (64, 128))]
    wire = [{"role": "system", "content": "Read the supplied evidence."},
            {"role": "user", "content": [{"type": "text", "text": "Original question"},
                                         *[image_part(image) for image in images]]}]
    before = copy.deepcopy(wire)
    # Exercise the installed, unmodified processor __call__ with its actual local components.
    # The unused video processor is not constructed; this is an image-path conformance check.
    processor = Qwen3VLProcessor.__new__(Qwen3VLProcessor)
    processor.tokenizer = capacity.tokenizer
    processor.image_processor = capacity.image_processor
    processor.video_processor = None
    processor.image_token, processor.video_token = "<|image_pad|>", "<|video_pad|>"
    processor.image_token_id = capacity.tokenizer.convert_tokens_to_ids(processor.image_token)
    processor.video_token_id = capacity.tokenizer.convert_tokens_to_ids(processor.video_token)
    canonical = copy.deepcopy(wire)
    canonical[1]["content"] = [{"type": "text", "text": "Original question"},
                                {"type": "image"}, {"type": "image"}]
    text = capacity.tokenizer.apply_chat_template(canonical, tokenize=False,
        add_generation_prompt=True, enable_thinking=thinking)
    encoded = processor(text=[text], images=images, return_tensors="np")
    expected = encoded["input_ids"].shape[-1]
    assert capacity.count_messages(wire, enable_thinking=thinking) == expected
    assert capacity.check(wire, enable_thinking=thinking)["prompt_tokens"] == expected
    assert wire == before


def test_visual_tokens_can_reject_a_request_whose_text_template_fits(capacity):
    message = [{"role": "user", "content": [image_part(Image.new("RGB", (800, 600)))]}]
    limit = capacity.context_tokens
    capacity.context_tokens = 300
    try:
        text_only = HostCapacity(capacity.config)
        text_only.context_tokens = 300
        assert text_only.check(message)["remaining_tokens"] > 0
        with pytest.raises(CapacityExceeded) as caught:
            capacity.check(message)
        assert caught.value.receipt["prompt_tokens"] >= 475
    finally:
        capacity.context_tokens = limit


def test_text_only_tool_history_keeps_original_capacity(capacity):
    messages = [{"role": "user", "content": "Use stored evidence."},
        {"role": "assistant", "content": "", "reasoning_content": "Need a source.",
         "tool_calls": [{"id": "c1", "type": "function", "function": {
             "name": "lookup", "arguments": '{"query":"past evidence"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "Original receipt"}]
    assert capacity.count_messages(messages) == HostCapacity(capacity.config).count_messages(
        messages)


def test_remote_image_is_not_fetched_without_metered_admission(capacity):
    message = [{"role": "user", "content": [{"type": "image_url", "image_url": {
        "url": "https://example.invalid/image.png"}}]}]
    with pytest.raises(ValueError):
        capacity.check(message)


def test_existing_client_admits_full_image_wire_and_blocks_overflow_before_http(capacity):
    wire, events = [], []
    messages = [{"role": "user", "content": [image_part(Image.new("RGB", (800, 600)))]}]

    def respond(request):
        wire.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [], "usage": {
            "prompt_tokens": 500, "completion_tokens": 1, "total_tokens": 501}})

    limit = capacity.context_tokens
    try:
        with VLLMClient(VLLMConfig("http://fixture/v1", capacity.config["model"],
                max_tokens=128, enable_thinking=True), capacity=capacity,
                transport=httpx.MockTransport(respond), emit=events.append) as client:
            client.chat(messages)
            capacity.context_tokens = 300
            with pytest.raises(CapacityExceeded):
                client.chat(messages)
        assert len(wire) == 1 and wire[0]["messages"] == messages
        response = next(e for e in events if e["event"] == "vllm_response")
        assert response["capacity"]["prompt_tokens"] >= 475
        assert any(e["event"] == "vllm_capacity_rejected" for e in events)
    finally:
        capacity.context_tokens = limit
