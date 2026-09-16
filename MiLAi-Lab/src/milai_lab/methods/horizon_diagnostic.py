"""HorizonBench's official letter score and separate local ambiguity diagnostics."""

from __future__ import annotations

import re


def official_letter(response: str) -> str:
    """Pinned evaluate.py extract_letter behavior, including its permissive first character."""
    text = response.strip()
    if text and text[0] in "ABCDE":
        return text[0]
    match = re.search(r"\b([A-E])\b", text)
    return match.group(1) if match else ""


def score(response: str, correct_letter: str, distractor_letter: str) -> dict[str, object]:
    predicted = official_letter(response)
    strict = response.strip() if re.fullmatch(r"[A-E]", response.strip()) else ""
    mentioned = sorted(set(re.findall(r"\b([A-E])\b", response)))
    return {"official_predicted": predicted, "official_correct": predicted == correct_letter,
            "strict_predicted": strict, "strict_correct": strict == correct_letter,
            "strict_format_valid": bool(strict), "multiple_letters": len(mentioned) > 1,
            "mentioned_letters": mentioned,
            "old_option_selected": bool(distractor_letter) and predicted == distractor_letter,
            "semantic_use_verdict": "UNSCORED_REQUIRES_PRESENTED_SUPPORT_ADJUDICATION"}
