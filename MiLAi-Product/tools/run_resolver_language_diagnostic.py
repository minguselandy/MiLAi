"""Record a frozen pure-resolver diagnosis, including explicit semantic failures.

Exit zero means collection completed, not that every expected behavior passed.
The output's behavior_status and mismatch records are the behavioral evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def evaluate(corpus: dict[str, Any], surface: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    prior: dict[str, Any] = {}
    for case in corpus["cases"]:
        if case["surface"] != surface:
            continue
        actual = (
            _client(case, corpus["keysets"], prior)
            if surface == "client_typed"
            else _runtime(case)
        )
        expected = case["expected"]
        fields = (
            ("intent", "route", "key")
            if surface == "client_typed"
            else (
                "intent",
                "requirement",
                "retrieval_intent",
                "route",
                "key",
            )
        )
        differences = [name for name in fields if expected[name] != actual[name]]
        if case.get("accepted_error") == actual.get("error_code") and actual.get(
            "error_code"
        ):
            differences = []
        families = _families(case, actual, differences)
        rows.append(
            {
                "case_id": case["id"],
                "categories": case["categories"],
                "expected": expected,
                "actual": actual,
                "status": "FAIL" if differences else "PASS",
                "mismatched_fields": differences,
                "reason_matches": expected["reason_code"] == actual["reason_code"],
                "failure_families": families,
            }
        )
    if not rows:
        raise ValueError("NO_CASES_FOR_SURFACE")
    counts = Counter(row["status"] for row in rows)
    return {
        "schema_version": "milai-resolver-language-diagnostic-v1",
        "surface": surface,
        "collection_status": "COMPLETE",
        "behavior_status": "FAIL" if counts["FAIL"] else "PASS",
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "reason_only_differences": sum(
            not row["reason_matches"] and row["status"] == "PASS" for row in rows
        ),
        "failure_family_counts": dict(
            Counter(family for row in rows for family in row["failure_families"])
        ),
        "model_requests": 0,
        "embedding_calls": 0,
        "retrieval_calls": 0,
        "claim_ceiling": "PURE_RESOLVER_DIAGNOSIS_NOT_RUNTIME_RETRIEVAL_OR_MODEL_EFFECT",
        "cases": rows,
    }


def _client(
    case: dict[str, Any], keysets: dict[str, Any], prior: dict[str, Any]
) -> dict[str, Any]:
    from milai_client import (
        CanonicalStateKey,
        DeterministicMemoryNeedResolver,
        StateKeyAliasAmbiguousError,
    )

    previous_id = case.get("previous_case")
    if previous_id is not None and previous_id not in prior:
        raise ValueError("ACTUAL_PREVIOUS_RESOLUTION_UNAVAILABLE")
    try:
        result = DeterministicMemoryNeedResolver().resolve(
            case["query"],
            scope=case["scope"],
            required_authority=case["required_authority"],
            consistency_floor=case["consistency_floor"],
            known_state_keys=tuple(
                CanonicalStateKey(**key) for key in keysets[case["keyset"]]
            ),
            previous=prior.get(previous_id),
        )
    except StateKeyAliasAmbiguousError as exc:
        return {
            "intent": None,
            "route": "ERROR",
            "key": None,
            "reason_code": exc.code,
            "error_code": exc.code,
        }
    prior[case["id"]] = result
    if (
        result.resolver_model_calls
        or result.resolver_embedding_calls
        or result.resolver_retrieval_calls
    ):
        raise ValueError("UNEXPECTED_RESOLVER_SIDE_EFFECT_COUNT")
    key = result.state_key_ref
    return {
        "intent": result.signature.intent_class,
        "route": result.requested_route,
        "key": None
        if key is None
        else {
            "subject": key.subject,
            "predicate": key.predicate,
            "claim_type": key.claim_type,
        },
        "reason_code": result.reason_code,
        "error_code": None,
    }


def _runtime(case: dict[str, Any]) -> dict[str, Any]:
    from milai.application.memory_resolve import MemoryQueryInterpreter

    result = MemoryQueryInterpreter().interpret(
        case["query"],
        invocation_mode=case["invocation_mode"],
        exact_target=case["exact_target"],
    )
    return {
        "intent": result.intent,
        "requirement": result.requirement,
        "retrieval_intent": result.retrieval_intent,
        "route": "NOT_OWNED",
        "key": None,
        "reason_code": result.reason_code,
        "error_code": None,
    }


def _families(
    case: dict[str, Any], actual: dict[str, Any], differences: list[str]
) -> list[str]:
    if not differences:
        return []
    expected = case["expected"]
    families: list[str] = []
    if (
        expected["intent"] in {"NONE", "NOT_NEEDED"}
        and actual["intent"] != expected["intent"]
    ):
        families.append("FALSE_RECALL")
    elif "intent" in differences or "retrieval_intent" in differences:
        families.append("INTENT_MISS")
    if "route" in differences or "requirement" in differences:
        families.append("WRONG_ROUTE")
    if "key" in differences:
        families.append(
            "STATE_KEY_AMBIGUITY"
            if "ambiguous-state-key" in case["categories"]
            else "STATE_KEY_MISS"
        )
    if "retry" in case["categories"]:
        families.append("RETRY_CARRYOVER_ERROR")
    if "alias-overfit-control" in case["categories"]:
        families.append("ALIAS_OVERFIT")
    if set(case["categories"]) & {"chinese", "unicode-normalization"}:
        families.append("LANGUAGE_TOKENIZATION")
    # Families classify observed diagnostic symptoms; they are not causal proof.
    return families


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-commit", required=True)
    parser.add_argument(
        "--surface", choices=("client_typed", "runtime_interpreter"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    product = args.product_root.resolve()
    repo = Path(_git(product, "rev-parse", "--show-toplevel").decode().strip())
    if _git(product, "rev-parse", "HEAD").decode().strip() != args.product_commit:
        raise ValueError("DIAGNOSTIC_SOURCE_COMMIT_MISMATCH")
    identities: dict[str, str] = {}
    for label, path in (
        ("corpus", args.corpus.resolve()),
        ("method", Path(__file__).resolve()),
        ("manifest", product / "product.manifest.json"),
    ):
        raw = path.read_bytes()
        if raw != _git(
            repo, "show", f"{args.product_commit}:{path.relative_to(repo).as_posix()}"
        ):
            raise ValueError("DIAGNOSTIC_INPUT_NOT_FROZEN")
        identities[label + "_sha256"] = _sha(raw)
    manifest = json.loads((product / "product.manifest.json").read_text())
    if _git(product, "status", "--porcelain", "--", *manifest["tree_paths"]):
        raise ValueError("DIAGNOSTIC_PRODUCT_SOURCE_DIRTY")
    corpus = json.loads(args.corpus.read_text())
    if corpus["status"] != "FROZEN_BEFORE_EXECUTION":
        raise ValueError("DIAGNOSTIC_CORPUS_NOT_FROZEN")
    result = evaluate(corpus, args.surface)
    result["identity"] = {
        **identities,
        "source_commit": args.product_commit,
        "product_tree_sha256": manifest["tree_sha256"],
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("surface", "behavior_status", "passed", "failed")
            }
        )
    )


if __name__ == "__main__":
    main()
