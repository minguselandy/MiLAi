from __future__ import annotations


class DatasetTextError(ValueError):
    pass


def runtime_safe_text(value: str) -> str:
    """Remove PostgreSQL's forbidden null code point without rewriting prose."""
    return value.replace("\x00", " ")


def retrieval_query(question: str, dataset_id: str) -> str:
    """Fit a dataset question to the Runtime's 2,000-character query contract."""
    if len(question) <= 2_000:
        return question
    if dataset_id.startswith("HORIZON-"):
        lines = question.splitlines()
        stem = lines[0].strip()
        options = [
            line.strip()
            for line in lines[1:]
            if line[:2] in {"A:", "B:", "C:", "D:", "E:"}
        ]
        if len(options) != 5:
            raise DatasetTextError("multiple-choice retrieval query options drifted")
        fixed = (
            len(stem) + sum(len(option[:2]) + 2 for option in options) + len(options)
        )
        per_option = max(1, (2_000 - fixed) // len(options))
        query = (
            stem
            + "\n"
            + "\n".join(
                f"{option[:2]} {option[2:].strip()[:per_option]}" for option in options
            )
        )
        return query[:2_000]
    return question[:2_000]
