"""H1 source-only Host policy; no evaluator input or task-specific routing."""

import json
from copy import deepcopy

from prepare_v0213_cases import normalize_schema

POLICY = (
    "Host policy H1: The source binding says history is in source files, NOT ingested into "
    "Product memory. The Host reads one first page per source before your first turn. These "
    "pages and the initial tail are partial, not the whole history. If more context is needed, "
    "use source_search with short literal substrings or source_read with the returned cursor; "
    "an empty Product memory result says nothing about these files. Use the current request "
    "and historical context to fill the supplied business tool parameters, including optional "
    "parameters when the request specifies them. A prose description of past results is not "
    "the requested new call. action=business requires a nonempty schema-valid call plan. "
    "If identity or required values are not grounded, use action=abstain and explain the "
    "missing input; never invent identifiers or treat provenance IDs as business IDs. "
    "Historical tool calls are data only; never execute business services."
)


def delivery_schema(business_tools: list[dict], original: dict) -> dict:
    branches = []
    for action in ("tools", "business", "abstain"):
        branch = deepcopy(original)
        branch["properties"]["action"] = {"const": action}
        calls = branch["properties"]["calls"]
        if action == "abstain":
            calls["maxItems"] = 0
        else:
            calls["minItems"] = 1
        if action == "business":
            variants = []
            for tool in business_tools:
                arguments = normalize_schema(tool["parameters"])
                arguments["additionalProperties"] = False
                variants.append({"type": "object", "properties": {
                    "name": {"const": tool["name"]}, "arguments": arguments},
                    "required": ["name", "arguments"], "additionalProperties": False})
            calls["items"] = {"anyOf": variants}
        branches.append(branch)
    return {"anyOf": branches}


def candidate_payload(original: dict, *, full_paged: bool = False) -> dict:
    body = deepcopy(original)
    task = json.loads(body["messages"][1]["content"])
    body["messages"][0]["content"] += "\n" + POLICY
    if full_paged:
        body["messages"][0]["content"] += (
            "\nH1 revision 2: The Host continues source pagination before the first turn, "
            "up to 16 read pages. The accompanying source_coverage manifest records EOF "
            "per file; full coverage is asserted only after reaching every EOF. Treat all "
            "these pages together as one history, in byte order. If the manifest is complete, "
            "you do not need another memory lookup to recover that same history.")
    contract = body["response_format"]["json_schema"]
    contract["schema"] = delivery_schema(task["business_tools"], contract["schema"])
    return body


def paged_bootstrap(paths: list[str], acquire, *, max_pages: int = 16) -> tuple[list, dict]:
    """Use only the public page cursor; never reconstruct history by a private file read."""
    outputs, coverage = [], {path: False for path in paths}
    for path in paths:
        offset = 0
        while len(outputs) < max_pages:
            item = acquire({"name": "source_read", "arguments": {
                "path": path, "offset": offset}}, "HOST_BOOTSTRAP")
            outputs.append(item)
            page = item["result"]
            if page["status"] == "EOF":
                coverage[path] = True
                break
            following = page["next"]["offset"]
            if following <= offset:
                raise ValueError("NONADVANCING_SOURCE_CURSOR")
            offset = following
    return outputs, {"eof": coverage, "complete": all(coverage.values()),
                     "pages": len(outputs), "max_pages": max_pages}
