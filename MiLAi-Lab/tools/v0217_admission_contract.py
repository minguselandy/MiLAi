"""Thin offline admission boundary: no provider, memory policy, Judge, or runtime imports."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit


def local_provider_config(config: dict) -> dict:
    url = urlsplit(config["base_url"])
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.port != 7860 or
            url.path.rstrip("/") != "/v1" or url.username or url.password or url.query):
        raise ValueError("LOCAL_ENDPOINT_ONLY_NO_FALLBACK")
    if config.get("model") != "Qwen3.6-35B-A3B-FP8":
        raise ValueError("MODEL_ID_NOT_PINNED")
    if config.get("allow_gold_fallback") is not False or config.get(
            "allow_remote_fallback") is not False:
        raise ValueError("FALLBACK_MUST_BE_EXPLICITLY_DISABLED")
    if not config.get("api_key_env"):
        raise ValueError("EXPLICIT_KEY_ENV_MAPPING_REQUIRED")
    return {key: config[key] for key in ("base_url", "model", "api_key_env",
                                        "allow_gold_fallback", "allow_remote_fallback")}


def online_question(question: dict) -> dict:
    text = question.get("question")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("QUESTION_TEXT_REQUIRED")
    return {"question": text}


def checkpoint_session_prefix(sample: dict, covered_sessions: list[str]) -> list[str]:
    """Coverage labels can be a window; native runner triggers at its latest session."""
    names = [session["_v2_session_id"] for session in sample["sessions"]]
    if (len(set(names)) != len(names) or not covered_sessions or
            len(set(covered_sessions)) != len(covered_sessions) or
            not set(covered_sessions).issubset(names)):
        raise ValueError("INVALID_CHECKPOINT_SESSION_REFERENCES")
    end = max(names.index(name) for name in covered_sessions)
    return names[:end + 1]


def online_sessions(sample: dict, covered_sessions: list[str], *, profile: str = "text") -> dict:
    """Whitelist raw dialogue only; never gold memory, QA answers, categories or future turns."""
    if profile not in ("text", "official_caption_diagnostic"):
        raise ValueError("MODALITY_PROFILE_NOT_VERIFIED")
    sessions = sample["sessions"]
    names = [session["_v2_session_id"] for session in sessions]
    if len(set(names)) != len(names) or not covered_sessions or covered_sessions != names[
            :len(covered_sessions)]:
        raise ValueError("EXPLICIT_CHRONOLOGICAL_PREFIX_REQUIRED")
    result = []
    for session in sessions[:len(covered_sessions)]:
        turns = []
        for turn in session["dialogue"]:
            if turn.get("role") not in ("user", "assistant", "system", "tool"):
                raise ValueError("UNSUPPORTED_ROLE_REVIEW_REQUIRED")
            attachments = turn.get("attachments") or []
            if attachments and profile == "text":
                raise ValueError("MISSING_MODALITY_NO_SILENT_CAPTION_OR_DROP")
            visible = {key: turn[key] for key in ("role", "content", "timestamp") if key in turn}
            visible["attachments"] = [{key: item[key] for key in ("image_id", "type", "caption")
                                      if key in item} for item in attachments]
            turns.append(visible)
        result.append({"session_id": session["_v2_session_id"], "dialogue": turns})
    return {"profile": profile, "sessions": result,
            "native_multimodal_equivalence": False, "images_presented": False}


def exposure_receipt(payload: bytes, *, expected_sha256: str, transport_ack: bool) -> dict:
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise ValueError("PAYLOAD_CHANGED")
    return {"payload_sha256": actual,
            "status": "TRANSPORT_ACKNOWLEDGED" if transport_ack else "ASSEMBLED_ONLY",
            "understanding_or_use_proved": False}
