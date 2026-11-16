"""A small lexical conditional-value control fitted to actual Reader outcomes.

This is an explicit-vocabulary linear model, not an LLM value estimate. It has
separate observed immediate, two-open and answer-return heads. Training and
inference use the same input projection; outcome/review metadata is never read.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
from numpy.typing import NDArray

from milai_lab.memory.retrieval import _lexical_tokens

Vector = NDArray[np.float64]


def evidence_text(value: Any) -> list[str]:
    """Only actual content and report-time strings, without source/item identities."""
    if isinstance(value, list):
        return [text for item in value for text in evidence_text(item)]
    if isinstance(value, dict):
        result = [
            value[key]
            for key in ("content", "text", "reported_at")
            if isinstance(value.get(key), str)
        ]
        for key, child in value.items():
            if key not in {"content", "text", "reported_at"} and isinstance(child, (dict, list)):
                result.extend(evidence_text(child))
        return result
    return []


def input_texts(payload: dict[str, Any]) -> tuple[str, str, str]:
    question = payload["question"] + " " + payload["date"]
    state = "\n".join(evidence_text(payload["memories"]))
    candidate = "\n".join(
        item["excerpt"] + " " + str(item["date"] or "")
        for item in payload.get("candidate_actions", [])
    )
    return question, state, candidate


@dataclass
class ValueFeatures:
    vocabulary: list[str]
    idf: Vector

    @classmethod
    def fit(cls, inputs: Iterable[dict[str, Any]], max_vocabulary: int = 2048) -> ValueFeatures:
        # Literal equality deduplicates repeated training inputs; no content fingerprints.
        documents = sorted({text for payload in inputs for text in input_texts(payload) if text})
        frequency: Counter[str] = Counter()
        for text in documents:
            frequency.update(set(_lexical_tokens(text)))
        vocabulary = sorted(frequency, key=lambda token: (-frequency[token], token))[
            :max_vocabulary
        ]
        return cls(
            vocabulary,
            np.asarray(
                [
                    math.log((1 + len(documents)) / (1 + frequency[token])) + 1
                    for token in vocabulary
                ],
                dtype=np.float64,
            ),
        )

    def text_vector(self, text: str) -> Vector:
        counts = Counter(_lexical_tokens(text))
        vector = np.asarray([math.log1p(counts[token]) for token in self.vocabulary]) * self.idf
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def encode(self, payload: dict[str, Any], *, conditional: bool) -> Vector:
        question, state, candidate = [self.text_vector(text) for text in input_texts(payload)]
        actions = payload.get("candidate_actions", [])
        # The independent control receives identical inputs before masking state features.
        state_count = math.log1p(len(payload["memories"]))
        if not conditional:
            state = np.zeros_like(state)
            state_count = 0.0
        return np.concatenate(
            (
                question,
                candidate,
                state,
                question * candidate,
                question * state,
                candidate * state,
                np.asarray(
                    [
                        1.0,
                        math.log1p(len(actions)),
                        state_count,
                        float(any(a["expand_context"] for a in actions)),
                    ]
                ),
            )
        )

    def to_json(self) -> dict[str, Any]:
        return {"vocabulary": self.vocabulary, "idf": self.idf.tolist()}


@dataclass
class LearnedValue:
    features: ValueFeatures
    conditional: bool
    heads: dict[str, Vector]

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> LearnedValue:
        features = value["features"]
        return cls(
            ValueFeatures(features["vocabulary"], np.asarray(features["idf"])),
            value["conditional"],
            {name: np.asarray(weights) for name, weights in value["heads"].items()},
        )

    def predict(self, payload: dict[str, Any]) -> dict[str, float]:
        vector = self.features.encode(payload, conditional=self.conditional)
        return {name: float(weights @ vector) for name, weights in self.heads.items()}

    def to_json(self) -> dict[str, Any]:
        return {
            "format": "lexical_conditional_value_v1",
            "conditional": self.conditional,
            "features": self.features.to_json(),
            "heads": {name: weights.tolist() for name, weights in self.heads.items()},
            "score_semantics": "Uncalibrated fitted observed returns, not sufficiency or "
            "expected utility. Costs and number of opens remain separate.",
        }


def ridge_fit(matrix: Vector, targets: Vector, regularization: float) -> Vector:
    """Dual ridge solution; examples are far fewer than explicit-vocabulary features."""
    return matrix.T @ np.linalg.solve(
        matrix @ matrix.T + regularization * np.eye(len(targets)), targets
    )


def select_by_return(
    candidates: list[int],
    *,
    payload_for: Callable[[list[int]], dict[str, Any]],
    measure: Callable[[list[int]], int],
    predict_return: Callable[[dict[str, Any]], float],
    input_limit: int,
    pair_width: int = 0,
) -> dict[str, Any]:
    """Choose actual bodies using fitted return differences and measured input cost.

    Pairs include zero/nonpositive singleton offers, so complementary evidence is
    not discarded merely because either singleton has no immediate task gain.
    The shortlist bounds local computation; it is not a claim of optimal search.
    """
    started, cpu_started = time.perf_counter(), time.process_time()
    chosen: list[int] = []
    trace, predictions, measurements = [], 0, 0
    current_cost = measure(chosen)
    current_return = predict_return(payload_for(chosen))
    predictions += 1
    measurements += 1
    offers: list[dict[str, Any]] = []

    def offer(additions: list[int]) -> None:
        nonlocal predictions, measurements
        indices = [*chosen, *additions]
        cost = measure(indices)
        measurements += 1
        if cost > input_limit:
            return
        value = predict_return(payload_for(indices))
        predictions += 1
        gain = value - current_return
        offers.append(
            {
                "indices": indices,
                "added_indices": additions,
                "predicted_return": value,
                "predicted_gain": gain,
                "input_tokens": cost,
                "gain_per_input_token": gain / max(1, cost - current_cost),
            }
        )

    while len(chosen) < len(candidates):
        offers = []
        for index in candidates:
            if index not in chosen:
                offer([index])
        shortlist = sorted(offers, key=lambda o: -o["gain_per_input_token"])[:pair_width]
        for first, second in combinations(shortlist, 2):
            offer([first["added_indices"][0], second["added_indices"][0]])
        positive = [o for o in offers if o["predicted_gain"] > 0]
        step = {
            "before_indices": list(chosen),
            "before_return": current_return,
            "offers": offers,
            "selected": None,
        }
        trace.append(step)
        if not positive:
            break
        best = max(positive, key=lambda o: o["gain_per_input_token"])
        step["selected"] = best
        chosen = best["indices"]
        current_return, current_cost = best["predicted_return"], best["input_tokens"]
    return {
        "selected_indices": chosen,
        "trace": trace,
        "pair_width": pair_width,
        "prediction_evaluations": predictions,
        "token_measurements": measurements,
        "input_tokens": current_cost,
        "input_limit": input_limit,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "score_semantics": "Raw fitted answer-return differences per incremental Reader "
        "input token; no calibration or correctness guarantee. "
        "Pair shortlist contains up to pair_width affordable singletons.",
    }
