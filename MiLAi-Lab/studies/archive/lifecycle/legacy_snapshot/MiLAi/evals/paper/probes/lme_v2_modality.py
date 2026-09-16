"""Label-free multimodal feasibility probe for LongMemEval-V2."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import struct
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import git_tracked_identity, sha256_file
from evals.paper.provider import MODEL_ID, _post_json, _strict_loopback_base_url

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_ROOT = Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2")
DATA_ROOT = BENCHMARK_ROOT / "data/longmemeval-v2"
MODEL_ROOT = Path("/cra/qwen36-35B")
DEFAULT_OUTPUT = ROOT / "var/dg11/paper/freeze/lme-v2-modality-feasibility.json"
EXPECTED_COMMIT = "2cc8c540bdb87fe6761629b585e727e1c4704520"
EXPECTED_MODEL_CONFIG_SHA256 = (
    "570ef7ea45a7e1d3de2b1d3c70c4ac3562d0e768acdc195778cb4f4d95025845"
)
EXPECTED_PREPROCESSOR_SHA256 = (
    "27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516"
)
REQUIRED_DATA_FILES = (
    "checksums.sha256",
    "questions.jsonl",
    "trajectories.jsonl",
    "haystacks/lme_v2_small.json",
    "trajectory_screenshots/web_screenshots.tar.gz",
    "trajectory_screenshots/enterprise_screenshots_base.tar.gz",
)


class LMEV2ModalityError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _two_band_png(
    *,
    width: int,
    height: int,
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    vertical: bool,
) -> bytes:
    if not 32 <= width <= 256 or not 32 <= height <= 256:
        raise LMEV2ModalityError("synthetic image dimensions are invalid")
    rows: list[bytes] = []
    for y in range(height):
        pixels = bytearray()
        for x in range(width):
            use_first = x < width // 2 if vertical else y < height // 2
            pixels.extend(first if use_first else second)
        rows.append(b"\x00" + bytes(pixels))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(b"".join(rows), level=9))
        + _chunk(b"IEND", b"")
    )


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise LMEV2ModalityError("LME-V2 modality decision is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _served_models(base_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _strict_loopback_base_url(base_url) + "/v1/models", method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise LMEV2ModalityError("served model inventory request failed") from exc
    if len(raw) > 1024 * 1024:
        raise LMEV2ModalityError("served model inventory is oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LMEV2ModalityError("served model inventory is not JSON") from exc
    if not isinstance(value, dict):
        raise LMEV2ModalityError("served model inventory is not an object")
    return value


def _model_identity() -> dict[str, Any]:
    config_path = MODEL_ROOT / "config.json"
    if (
        sha256_file(config_path) != EXPECTED_MODEL_CONFIG_SHA256
        or sha256_file(MODEL_ROOT / "preprocessor_config.json")
        != EXPECTED_PREPROCESSOR_SHA256
    ):
        raise LMEV2ModalityError("frozen answer model identity drifted")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or config.get("architectures") != ["Qwen3_5MoeForConditionalGeneration"]
        or not isinstance(config.get("vision_config"), dict)
    ):
        raise LMEV2ModalityError("frozen answer model has no vision architecture")
    return {
        "architecture": config["architectures"][0],
        "chat_template_sha256": sha256_file(MODEL_ROOT / "chat_template.jinja"),
        "config_sha256": EXPECTED_MODEL_CONFIG_SHA256,
        "model_id": MODEL_ID,
        "model_root": str(MODEL_ROOT),
        "preprocessor_sha256": EXPECTED_PREPROCESSOR_SHA256,
        "tokenizer_sha256": sha256_file(MODEL_ROOT / "tokenizer.json"),
        "video_preprocessor_sha256": sha256_file(
            MODEL_ROOT / "video_preprocessor_config.json"
        ),
        "vision_config_present": True,
    }


def _benchmark_identity() -> dict[str, Any]:
    identity = git_tracked_identity(BENCHMARK_ROOT)
    if identity.get("commit") != EXPECTED_COMMIT:
        raise LMEV2ModalityError("LongMemEval-V2 commit drifted")
    files: list[dict[str, Any]] = []
    for relative in REQUIRED_DATA_FILES:
        path = DATA_ROOT / relative
        if not path.is_file():
            raise LMEV2ModalityError(f"required LME-V2 data file is absent: {relative}")
        files.append({"bytes": path.stat().st_size, "path": relative})
    return {
        "commit": identity["commit"],
        "diff_sha256": identity["diff_sha256"],
        "dirty": identity["dirty"],
        "inventory_root_sha256": identity["inventory_root_sha256"],
        "required_data_files": files,
        "required_data_manifest_sha256": sha256_file(DATA_ROOT / "checksums.sha256"),
        "status_porcelain": identity["status_porcelain"],
    }


def _probe(base_url: str) -> dict[str, Any]:
    image_one = _two_band_png(
        width=96,
        height=64,
        first=(255, 0, 0),
        second=(0, 0, 255),
        vertical=True,
    )
    image_two = _two_band_png(
        width=96,
        height=64,
        first=(0, 255, 0),
        second=(255, 255, 0),
        vertical=False,
    )
    instruction = (
        "This is a synthetic capability probe, not benchmark data. "
        "For IMAGE_1 report which half is red. For IMAGE_2 report which band is green."
    )
    messages = [
        {
            "role": "system",
            "content": "Inspect the supplied synthetic images and return only the required JSON.",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "IMAGE_1 follows."},
                {"type": "image_url", "image_url": {"url": _data_url(image_one)}},
                {"type": "text", "text": "IMAGE_2 follows."},
                {"type": "image_url", "image_url": {"url": _data_url(image_two)}},
                {"type": "text", "text": instruction},
            ],
        },
    ]
    contract = {
        "expected": {"green_band": "TOP", "red_half": "LEFT"},
        "image_sha256": [
            hashlib.sha256(image_one).hexdigest(),
            hashlib.sha256(image_two).hexdigest(),
        ],
        "messages_without_image_bytes": [
            "SYSTEM:synthetic-image-inspection",
            "IMAGE_1:left-red-right-blue",
            "IMAGE_2:top-green-bottom-yellow",
            instruction,
        ],
        "seed": 20260824,
    }
    models = _served_models(base_url)
    model_rows = models.get("data")
    if (
        not isinstance(model_rows, list)
        or len(model_rows) != 1
        or not isinstance(model_rows[0], dict)
        or model_rows[0].get("id") != MODEL_ID
    ):
        raise LMEV2ModalityError("served answer model identity drifted")
    response, headers = _post_json(
        base_url,
        "/v1/chat/completions",
        {
            "model": MODEL_ID,
            "messages": messages,
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 64,
            "seed": contract["seed"],
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "milai_lme_v2_vision_probe",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "green_band": {"type": "string", "enum": ["TOP", "BOTTOM"]},
                            "red_half": {"type": "string", "enum": ["LEFT", "RIGHT"]},
                        },
                        "required": ["green_band", "red_half"],
                        "additionalProperties": False,
                    },
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "cache_salt": hashlib.sha256(
                b"milai-dg11-lme-v2-vision-probe-v1"
            ).hexdigest(),
        },
        timeout=240,
    )
    choices = response.get("choices")
    usage = response.get("usage")
    native_id = response.get("id") or headers.get("x-request-id")
    if (
        not isinstance(choices, list)
        or len(choices) != 1
        or not isinstance(choices[0], dict)
        or not isinstance(usage, dict)
        or not isinstance(native_id, str)
    ):
        raise LMEV2ModalityError("vision probe response envelope drifted")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    try:
        answer = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as exc:
        raise LMEV2ModalityError("vision probe answer is not JSON") from exc
    if answer != contract["expected"] or choices[0].get("finish_reason") != "stop":
        raise LMEV2ModalityError("frozen answer model failed synthetic vision probe")
    return {
        "answer": answer,
        "completion_tokens": usage.get("completion_tokens"),
        "contract_sha256": hashlib.sha256(_canonical(contract)).hexdigest(),
        "expected": contract["expected"],
        "finish_reason": choices[0]["finish_reason"],
        "image_count": 2,
        "image_sha256": contract["image_sha256"],
        "model_calls": 1,
        "native_request_id": native_id,
        "paper_data_used": False,
        "prompt_tokens": usage.get("prompt_tokens"),
        "status": "PASS",
    }


def run(*, base_url: str, output: Path) -> dict[str, Any]:
    benchmark = _benchmark_identity()
    model = _model_identity()
    probe = _probe(base_url)
    result: dict[str, Any] = {
        "adapter_contract": {
            "implementation_status": "REQUIRED_BEFORE_PE06_SMOKE",
            "lossiness": "NONE_ALLOWED_FOR_OFFICIAL_LOCAL_REPRODUCTION",
            "question_image": "PASS_UNCHANGED_TO_MEMORY_QUERY_AND_READER",
            "retrieved_screenshot": "RETURN_AS_IMAGE_CONTEXT_WITH_IMMUTABLE_FILE_IDENTITY",
            "semantic_index": "ACCESSIBILITY_TREE_STATE_ACTION_AND_SCREENSHOT_REFERENCE_TEXT",
            "visual_only_retrieval_limitation": (
                "NO_FROZEN_IMAGE_EMBEDDER; PIXELS_REMAIN_VISIBLE_TO_READER_AFTER_TEXTUAL_RETRIEVAL"
            ),
        },
        "answer_model": model,
        "benchmark": benchmark,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "official_protocol": {
            "decision": "OFFICIAL_LOCAL_REPRODUCTION",
            "leaderboard_equivalence": False,
            "published_reader_model": "Qwen3.5-9B",
            "reader_difference_disclosure": "LOCAL_CONTROLLED_READER_IS_QWEN3.6_35B_A3B_FP8",
            "text_only_adapted_protocol": False,
        },
        "paper_labels_opened": False,
        "required_modalities": {
            "question_image_optional": True,
            "question_text": True,
            "trajectory_accessibility_tree": True,
            "trajectory_actions": True,
            "trajectory_screenshot": True,
        },
        "schema": "milai.dg11.paper-lme-v2-modality-feasibility.v1",
        "source_contracts": {
            "harness_sha256": sha256_file(BENCHMARK_ROOT / "evaluation/harness.py"),
            "memory_interface_sha256": sha256_file(
                BENCHMARK_ROOT / "memory_modules/memory.py"
            ),
            "public_data_sha256": sha256_file(BENCHMARK_ROOT / "data/public_data.py"),
            "readme_sha256": sha256_file(BENCHMARK_ROOT / "README.md"),
        },
        "status": "PASS_ADAPTER_IMPLEMENTATION_PENDING",
        "synthetic_vision_probe": probe,
        "test_question_records_read": 0,
        "tool_browser_requirement": {
            "agentrunbook_c": "OFFLINE_CODEX_CLI_AND_LOCAL_TRAJECTORY_FILES",
            "agentrunbook_r": "LOCAL_MODEL_AND_EMBEDDING_ENDPOINTS_NO_LIVE_BROWSER",
            "no_retrieval_and_rag": "OFFLINE_DATA_ONLY_NO_LIVE_BROWSER",
        },
        "work_package": "DG11-PE06-MODALITY-FEASIBILITY",
    }
    _atomic_json_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7860/v1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(base_url=args.base_url, output=args.output.resolve())
    print(
        json.dumps(
            {
                "decision": result["official_protocol"]["decision"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
