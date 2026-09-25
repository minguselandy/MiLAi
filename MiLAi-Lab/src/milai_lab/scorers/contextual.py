from __future__ import annotations

import re
from typing import Any

from milai_lab.datasets.contextual import EvaluationCase

PERSONAMEM_V1_SCORING_SOURCE = (
    "https://github.com/bowen-upenn/PersonaMem/blob/"
    "d07e6ade22e85e0e5d562247323a9c3e07553226/inference.py"
)
PERSONAMEM_V1_SCORING_SOURCE_SHA256 = (
    "9b77115a0d92d255c4c6ef6a710f8975e178d7f0c902739a1538411e06b8a71a"
)
LONGMEMEVAL_SCORING_SOURCE = (
    "https://github.com/xiaowu0162/LongMemEval/blob/"
    "9e0b455f4ef0e2ab8f2e582289761153549043fc/src/evaluation/evaluate_qa.py"
)
LONGMEMEVAL_SCORING_SOURCE_SHA256 = (
    "ecce9c4c79dc89d99534ac17b383a5cbb5b9f0c69ee98adaf0684742e3d95251"
)
PERSONAMEM_V2_SCORING_SOURCE = (
    "https://github.com/bowen-upenn/PersonaMem-v2/blob/"
    "d29d91d016add354e459dfeb0d24af08bc402e2a/inference.py"
)
PERSONAMEM_V2_SCORING_SOURCE_SHA256 = (
    "d78b15cb58ad4e9219b90a0ff7713dc3bff997e69df8664889a6cc7fc323484f"
)


def _v1_only_options(text: str) -> set[str]:
    parenthesized = re.findall(r"\(([a-d])\)", text, flags=re.IGNORECASE)
    letters = parenthesized or re.findall(r"\b([a-d])\b", text, flags=re.IGNORECASE)
    return {letter.casefold() for letter in letters}


def _v1_answer(response: str) -> tuple[str | None, set[str]]:
    candidate = response.strip()
    if "<final_answer>" in candidate:
        candidate = candidate.rsplit("<final_answer>", maxsplit=1)[1].strip()
    if candidate.endswith("</final_answer>"):
        candidate = candidate[: -len("</final_answer>")].strip()
    options = _v1_only_options(candidate)
    return (next(iter(options)) if len(options) == 1 else None), _v1_only_options(response)


def _v2_answer(response: str) -> str | None:
    patterns = (
        r"\$\\boxed\{([A-Z])\}\$",
        r"\\boxed\{([A-Z])\}",
        r"Final Answer:\s*([A-Z])",
        r"Answer:\s*([A-Z])",
        r"final answer is\s*\$?\\boxed\{([A-Z])\}\$?",
        r"final answer is\s*([A-Z])",
        r"the answer is\s*\$?\\boxed\{([A-Z])\}\$?",
        r"the answer is\s*([A-Z])",
        r"\b([A-Z])\.\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, response, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).upper()
    return None


def score_mcq(answer: object, case: EvaluationCase) -> dict[str, Any]:
    """Apply each dataset's published deterministic option parser and match."""
    if case.dataset not in {"personamem-v1", "personamem-v2"}:
        raise ValueError(f"unsupported MCQ dataset: {case.dataset}")
    if not isinstance(answer, str):
        return {"success": False, "format_error": True, "predicted_option": None}
    if case.dataset == "personamem-v1":
        predicted, full_options = _v1_answer(answer)
        gold = str(case.answer).strip().casefold().strip("() ")
        success = predicted == gold or full_options == {gold}
        if success and predicted != gold:
            predicted = gold  # Match the upstream full-response fallback.
    else:
        predicted = _v2_answer(answer)
        gold = str(case.answer).upper()
        option_index = ord(predicted) - ord("A") if predicted else -1
        success = (
            0 <= option_index < len(case.task.options)
            and case.task.options[option_index] == case.metadata["correct_answer"]
        )
    if predicted is None:
        return {"success": False, "format_error": True, "predicted_option": None}
    return {
        "success": success,
        "format_error": case.dataset == "personamem-v2" and option_index >= len(case.task.options),
        "predicted_option": predicted,
        "correct_option": gold,
    }


def longmemeval_judge_prompt(case: EvaluationCase, hypothesis: str) -> str:
    """Build the official LongMemEval answer-check prompt for one frozen case."""
    if case.dataset != "longmemeval-s-cleaned":
        raise ValueError("LongMemEval rubric requires a LongMemEval case")
    answer = case.answer
    if not isinstance(answer, dict):
        raise ValueError("LongMemEval evaluation answer must be a mapping")
    task = answer["question_type"]
    question = case.task.question
    reference = answer["answer"]
    abstention = bool(case.metadata["abstention"])
    if abstention:
        template = (
            "I will give you an unanswerable question, an explanation, and a response "
            "from a model. "
            "Please answer yes if the model correctly identifies the question as unanswerable. "
            "The model could say that the information is incomplete, or some other information is "
            "given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\n"
            "Model Response: {}\n\nDoes the model correctly identify the question as "
            "unanswerable? Answer yes or no only."
        )
        return template.format(question, reference, hypothesis)

    if task in {"single-session-user", "single-session-assistant", "multi-session"}:
        template = (
            "I will give you a question, a correct answer, and a response from a model. Please "
            "answer yes if the response contains the correct answer. Otherwise, answer no. If the "
            "response is equivalent to the correct answer or contains all the intermediate steps "
            "to get the correct answer, you should also answer yes. If the response only contains "
            "a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\n"
            "Correct Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer "
            "yes or no only."
        )
    elif task == "temporal-reasoning":
        template = (
            "I will give you a question, a correct answer, and a response from a model. Please "
            "answer yes if the response contains the correct answer. Otherwise, answer no. If the "
            "response is equivalent to the correct answer or contains all the intermediate steps "
            "to get the correct answer, you should also answer yes. If the response only contains "
            "a subset of the information required by the answer, answer no. In addition, do not "
            "penalize off-by-one errors for the number of days. If the question asks for the "
            "number of days/weeks/months, etc., and the model makes off-by-one errors "
            "(e.g., predicting 19 "
            "days when the answer is 18), the model's response is still correct. \n\nQuestion: "
            "{}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response "
            "correct? Answer yes or no only."
        )
    elif task == "knowledge-update":
        template = (
            "I will give you a question, a correct answer, and a response from a model. Please "
            "answer yes if the response contains the correct answer. Otherwise, answer no. If the "
            "response contains some previous information along with an updated answer, "
            "the response should be considered as correct as long as the updated answer "
            "is the required answer.\n\n"
            "Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model "
            "response correct? Answer yes or no only."
        )
    elif task == "single-session-preference":
        template = (
            "I will give you a question, a rubric for desired personalized response, "
            "and a response "
            "from a model. Please answer yes if the response satisfies the desired response. "
            "Otherwise, answer no. The model does not need to reflect all the points in "
            "the rubric. "
            "The response is correct as long as it recalls and utilizes the user's personal "
            "information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    else:
        raise ValueError(f"unsupported LongMemEval question type: {task}")
    return template.format(question, reference, hypothesis)


def parse_judge(response: object) -> dict[str, Any]:
    """Parse the official yes/no-only Judge answer without guessing malformed output."""
    if not isinstance(response, str):
        return {"success": False, "format_error": True, "judgment": None}
    normalized = response.strip().casefold().rstrip(".")
    if normalized == "yes":
        return {"success": True, "format_error": False, "judgment": True}
    if normalized == "no":
        return {"success": False, "format_error": False, "judgment": False}
    return {"success": False, "format_error": True, "judgment": None}
