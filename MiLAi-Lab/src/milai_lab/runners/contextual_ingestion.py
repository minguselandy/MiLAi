"""One bounded historical proposal, followed by ordinary versioned memory operations."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from milai_lab.methods.contextual_memory.material_view import source_subject_handle
from milai_lab.methods.contextual_memory.revision import maintenance_records
from milai_lab.methods.contextual_memory.write_contract import (
    CONDITION_DEFINITIONS,
    WRITE_RULES,
    apply_content_patch,
    ordinary_save_schema,
)
from milai_lab.methods.contextual_user_memory import (
    CHANGESET_SCHEMA,
    TOOLS,
    ContextualMemory,
    receipt_outcome,
)
from milai_lab.providers.contextual_vllm import Emit, VLLMClient

PROTOCOL_VERSION = "contextual-ingestion-handles-v30"
INGESTION_PROMPT = """Maintain reusable understanding from NEW observations in one batch proposal.
Consider the entire batch before proposing edits. related_records and related_original_sources
are existing background, not records to copy. Compose changed matters into one current version;
unchanged records need no operation. Sources are already retained. Do not answer a future task.
""" + WRITE_RULES

_SET_FIELDS = {"source_refs", "reason_refs", "group_ids", "dependencies"}
_REF_FIELDS = {"ref", "target_ref", "source_ref", "old_ref", "group_id", "about_ref"}


def normalize_sets(value: Any, changes: list[dict[str, Any]], path: str = "") -> Any:
    """Only declared reference sets are unordered; operation/item sequences stay intact."""
    if isinstance(value, list):
        return [normalize_sets(item, changes, f"{path}/{i}") for i, item in enumerate(value)]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        location = f"{path}/{key}"
        if key in _SET_FIELDS and isinstance(item, list) and all(
            isinstance(ref, str) for ref in item
        ):
            unique = list(dict.fromkeys(item))
            if unique != item:
                changes.append({"path": location, "before": item, "after": unique})
            result[key] = unique
        else:
            result[key] = normalize_sets(item, changes, location)
    return result


def resolve_handles(value: Any, handles: dict[str, dict[str, Any]]) -> Any:
    """Expand only actually delivered handles; never recover an unknown reference by text."""
    def ref(handle: str) -> str:
        if handle.startswith("new:"):
            return handle
        if handle not in handles:
            raise ValueError(f"UNKNOWN_INGESTION_HANDLE:{handle}")
        return str(handles[handle]["ref"])

    if isinstance(value, list):
        return [resolve_handles(item, handles) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in _REF_FIELDS:
            result[key] = ref(item)
        elif key in _SET_FIELDS:
            result[key] = [ref(handle) for handle in item]
        elif key in {"source_delta", "dependency_delta"}:
            result[key] = {change: [ref(handle) for handle in refs]
                           for change, refs in item.items()}
        elif key == "items":
            items = []
            for handle in item:
                resolved: dict[str, Any] = {"ref": ref(handle)}
                if not handle.startswith("new:"):
                    binding = handles[handle]
                    if binding["kind"] == "source":
                        resolved.update(start=binding["start"], end=binding["end"])
                items.append(resolved)
            result[key] = items
        elif key in {"groups", "operations", "changeset"}:
            result[key] = resolve_handles(item, handles)
        else:
            result[key] = item
    return result


def resolve_aliases(value: Any, aliases: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [resolve_aliases(item, aliases) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: aliases.get(item, item) if key in _REF_FIELDS else
        [aliases.get(ref, ref) for ref in item] if key in _SET_FIELDS else
        resolve_aliases(item, aliases) if key in {
            "groups", "operations", "changeset", "items", "source_delta", "dependency_delta",
        }
        else item
        for key, item in value.items()
    }


def related_sources(
    memory: ContextualMemory, records: list[dict[str, Any]], max_bytes: int,
) -> dict[str, Any]:
    """Expand only declared old evidence, with exact ranges and one shared byte budget."""
    pending: list[tuple[str, int, int | None]] = []

    def enqueue(record: dict[str, Any]) -> None:
        items = [
            item for group in record.get("justifications", []) for item in group["items"]
        ]
        pending.extend((item["ref"], item["start"] or 0, item["end"]) for item in items)
        pending.extend((ref, 0, None) for ref in record.get("source_refs", [])
                       if not any(item["ref"] == ref for item in items))

    for record in records:
        enqueue(record)
    visited: set[tuple[str, int, int | None]] = set()
    materials: list[dict[str, Any]] = []
    unexpanded: list[dict[str, Any]] = []
    used = 0
    while pending:
        ref, start, end = pending.pop(0)
        key = (ref, start, end)
        if key in visited:
            continue
        visited.add(key)
        if used >= max_bytes or len(materials) >= 8:
            unexpanded.append({"ref": ref, "start": start, "end": end})
            continue
        page = memory.read(ref, include_sources=False, start=start,
                           length=(end - start) if end is not None else 2048)
        if page["kind"] == "interpretation":
            enqueue(page)
            continue
        size = len(json.dumps(page, ensure_ascii=False).encode())
        if used + size > max_bytes:
            unexpanded.append({"ref": ref, "start": start, "end": end})
            continue
        materials.append(page)
        used += size
        if end is None and page["page"]["end"] < page["page"]["total_chars"]:
            unexpanded.append({"ref": ref, "start": page["page"]["end"],
                               "end": page["page"]["total_chars"]})
    return {"materials": materials, "unexpanded": unexpanded, "bytes": used}


def ordinary_related_context(
    memory: ContextualMemory, candidates: list[dict[str, Any]], max_bytes: int,
    seen_before: set[str], ranges_before: dict[str, set[tuple[int, int]]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Admit old records with their cited sources and independent premises."""
    available = related_sources(memory, candidates, max_bytes)
    pages = {page["ref"]: page for page in available["materials"]}
    selected: list[dict[str, Any]] = []
    selected_sources: set[str] = set()
    selected_dependencies: dict[str, dict[str, Any]] = {}
    read_dependencies: set[str] = set()
    used = 0
    for record in candidates:
        refs = list(dict.fromkeys(record.get("source_refs", [])))
        if any(ref not in pages for ref in refs):
            continue
        dependencies: dict[str, dict[str, Any]] = {}
        for ref in record.get("dependencies", []):
            if ref in selected_dependencies:
                dependencies[ref] = selected_dependencies[ref]
                continue
            page = memory.read(ref, include_sources=False, length=512, _visible=False)
            read_dependencies.add(ref)
            dependencies[ref] = {
                key: page[key] for key in (
                    "ref", "about", "author", "status", "current_ref", "subject",
                    "context", "page", "text",
                ) if key in page
            }
        fresh = [ref for ref in refs if ref not in selected_sources]
        new_dependencies = [ref for ref in dependencies if ref not in selected_dependencies]
        cost = len(json.dumps(record, ensure_ascii=False).encode()) + sum(
            len(json.dumps(pages[ref], ensure_ascii=False).encode()) for ref in fresh
        ) + sum(len(json.dumps(dependencies[ref], ensure_ascii=False).encode())
                for ref in new_dependencies)
        if used + cost > max_bytes:
            continue
        selected.append(record)
        selected_sources.update(fresh)
        selected_dependencies.update(dependencies)
        used += cost
    selected_refs = {record["ref"] for record in selected}
    for ref in (({record["ref"] for record in candidates} - selected_refs)
                - selected_dependencies.keys()) | (
        set(pages) - selected_sources
    ) | ({ref for record in candidates for ref in record.get("source_refs", [])}
         - selected_sources) | (read_dependencies - selected_dependencies.keys()):
        if ref not in seen_before:
            memory.seen.discard(ref)
        if ref in ranges_before:
            memory.visible_source_ranges[ref] = ranges_before[ref]
        else:
            memory.visible_source_ranges.pop(ref, None)
    materials = [page for page in available["materials"]
                 if page["ref"] in selected_sources]
    evidence = {
        "materials": materials,
        "unexpanded": [item for item in available["unexpanded"]
                       if item["ref"] in selected_sources],
        "bytes": sum(len(json.dumps(page, ensure_ascii=False).encode())
                     for page in materials),
        "omitted_records": len(candidates) - len(selected),
    }
    return selected, evidence, list(selected_dependencies.values())


def proposal_schema(max_operations: int, profile: str = "ordinary") -> dict[str, Any]:
    if profile in {"support", "events"}:
        schema = copy.deepcopy(CHANGESET_SCHEMA)
        groups = schema["properties"]["groups"]
        groups["maxItems"] = min(groups["maxItems"], max_operations)
        operations = groups["items"]["properties"]["operations"]
        operations["maxItems"] = min(operations["maxItems"], max_operations)
        if profile == "support":
            operations["items"]["oneOf"] = [
                branch for branch in operations["items"]["oneOf"]
                if branch["properties"]["op"]["const"] in {
                    "claim", "justification", "retract_justification", "review",
                }
            ]
        for branch in operations["items"]["oneOf"]:
            if branch["properties"]["op"]["const"] == "justification":
                branch["properties"]["items"]["items"] = {"type": "string"}
        return schema
    parameters = copy.deepcopy(
        next(
            tool["function"]["parameters"]
            for tool in TOOLS
            if tool["function"]["name"] == "memory_save"
        )
    )
    parameters["properties"].pop("changeset", None)
    branches = ordinary_save_schema(parameters)["oneOf"]
    branches = [
        branch for branch in branches
        if branch["properties"]["op"]["const"] != "RETAIN_SOURCE"
    ]
    no_change = next(branch for branch in branches
                     if branch["properties"]["op"]["const"] == "NO_CHANGE")
    no_change["properties"]["reason"] = {
        "enum": ["NO_NEW_MAINTAINABLE_FACT", "ALREADY_COVERED"],
    }
    no_change["required"].append("reason")
    for branch in branches:
        if branch["properties"]["op"]["const"] in {"CREATE", "REVISE"}:
            if "source_refs" in branch["properties"]:
                branch["properties"]["source_refs"] = {
                    **copy.deepcopy(branch["properties"]["source_refs"]), "minItems": 1,
                }
            # History maintenance uses the durable default; event time is narrative scope.
            branch["properties"].pop("persistence", None)
    return {
        "type": "object",
        "properties": {
            "operations": {"type": "array", "items": {"oneOf": branches},
                           "minItems": 1, "maxItems": max_operations}
        },
        "required": ["operations"],
        "additionalProperties": False,
    }


def bind_proposal_handles(
    schema: dict[str, Any], handles: dict[str, dict[str, Any]], profile: str,
) -> None:
    """Constrain transport references to delivered choices before generation."""
    sources = [key for key, value in handles.items() if value["kind"] == "source"]
    records = [key for key, value in handles.items() if value["kind"] == "record"]
    dependencies = [key for key, value in handles.items()
                    if value["kind"] in {"record", "dependency"}]
    subjects = [key for key, value in handles.items() if value["kind"] == "subject"]
    groups = [key for key, value in handles.items() if value["kind"] == "group"]
    domains = {
        "source_ref": sources, "source_refs": sources,
        "target_ref": records, "old_ref": records, "dependencies": dependencies,
        "about_ref": subjects,
        "group_id": groups, "group_ids": groups,
        "reason_refs": sources + records,
        "items": sources + records,
    }
    alias_fields = {"target_ref", "old_ref", "dependencies", "reason_refs", "items"}

    def bind(node: Any) -> bool:
        if isinstance(node, list):
            node[:] = [item for item in node if bind(item)]
        elif isinstance(node, dict):
            properties = node.get("properties", {})
            for name in list(properties):
                if name in {"source_delta", "dependency_delta"}:
                    delta_choices = sources if name == "source_delta" else dependencies
                    for change in ("add", "remove"):
                        field = copy.deepcopy(properties[name]["properties"][change])
                        if delta_choices:
                            field["items"] = {"type": "string", "enum": delta_choices}
                        else:
                            field["maxItems"] = 0
                        properties[name]["properties"][change] = field
                    continue
                if name not in domains:
                    continue
                # Core schemas intentionally share reference-set definitions.
                properties[name] = copy.deepcopy(properties[name])
                choices: list[dict[str, Any]] = []
                if domains[name]:
                    choices.append({"type": "string", "enum": domains[name]})
                if profile in {"support", "events"} and name in alias_fields:
                    choices.append({"type": "string", "pattern": "^new:[A-Za-z0-9_-]+$"})
                reference = choices[0] if len(choices) == 1 else {"anyOf": choices}
                if properties[name].get("type") == "array":
                    if choices:
                        properties[name]["items"] = reference
                    else:
                        properties[name]["maxItems"] = 0
                elif choices:
                    properties[name] = reference
                elif name in node.get("required", []):
                    return False
                else:
                    del properties[name]
            for value in node.values():
                if isinstance(value, (dict, list)):
                    bind(value)
        return True

    bind(schema)


def prepare_ingestion(
    memory: ContextualMemory,
    observations: list[dict[str, Any]],
    *,
    prompt: str,
    max_operations: int,
    context_bytes: int,
    emit: Emit,
    profile: str = "ordinary",
    old_source_bytes: int = 0,
    maintenance_query: str | None = None,
) -> dict[str, Any]:
    """Expose the legal prefix and related read versions; never expose a future question.

    Proposals execute sequentially through memory_save. A failed operation does not roll
    back earlier successes, and later operations still get their own real receipt.
    """
    local_before = dict(memory.local_timings)
    seen_before_selection = set(memory.seen)
    ranges_before_selection = {
        ref: set(spans) for ref, spans in memory.visible_source_ranges.items()
    }
    query = maintenance_query or "\n".join(item["content"] for item in observations)
    existing = (maintenance_records(memory, query, max_bytes=context_bytes)
                if maintenance_query is not None else
                memory.suggest_existing_records(query, limit=8, max_bytes=context_bytes))
    if maintenance_query is None and memory.revisions.pending:
        queued = maintenance_records(memory, query, max_bytes=context_bytes)
        selected = []
        refs = set()
        used = 0
        for item in queued + [r for r in existing if r["ref"] not in memory.revisions.pending]:
            size = len(json.dumps(item, ensure_ascii=False).encode())
            if item["ref"] not in refs and used + size <= context_bytes:
                refs.add(item["ref"])
                selected.append(item)
                used += size
        existing = selected
    dependencies: list[dict[str, Any]] = []
    evidence: dict[str, Any] | None
    if profile == "ordinary" and maintenance_query is None:
        existing, evidence, dependencies = ordinary_related_context(
            memory, existing, context_bytes,
            seen_before_selection, ranges_before_selection,
        )
    else:
        evidence = (related_sources(memory, existing, old_source_bytes)
                    if old_source_bytes and existing else None)
    handles: dict[str, dict[str, Any]] = (
        {"unknown": {"kind": "subject", "ref": "unresolved"}}
        if profile == "ordinary" else {}
    )

    def source_handle(ref: str, start: int, end: int) -> str:
        source = memory.sources[ref]
        binding = {"kind": "source", "ref": ref, "start": start, "end": end,
                   "role": source.role,
                   "content_sha256": hashlib.sha256(source.content.encode()).hexdigest()}
        for handle, old in handles.items():
            if old == binding:
                return handle
        handle = f"s{sum(item['kind'] == 'source' for item in handles.values())}"
        handles[handle] = binding
        return handle

    def speaker_handle(ref: str) -> str:
        if memory.source_subject(ref) == "current_user":
            handles["u0"] = {"kind": "subject", "ref": "current_user"}
            return "u0"
        canonical = memory.source_subject(ref)
        for handle, binding in handles.items():
            if binding["kind"] == "subject" and binding["ref"] == canonical:
                return handle
        handle = source_subject_handle(memory, ref)
        handles[handle] = {"kind": "subject", "ref": canonical,
                           "source_ref": ref, "role": memory.sources[ref].role}
        return handle

    delivered = []
    for observation in observations:
        ref = observation["source_ref"]
        start = observation.get("start", 0)
        end = observation.get("end", start + len(observation["content"]))
        source = memory.sources[ref]
        if source.content[start:end] != observation["content"] or not 0 <= start <= end <= len(
            source.content
        ):
            raise ValueError("DELIVERED_SOURCE_RANGE_MISMATCH")
        delivered.append({
            "source_ref": source_handle(ref, start, end),
            **({"speaker_ref": speaker_handle(ref)} if profile == "ordinary" else {}),
            "role": source.role, "session_id": source.session_id,
            "date": source.date, "source_sequence": memory.source_sequence[ref],
            "range": [start, end],
            "content": source.content[start:end],
        })
    evidence_handles: dict[str, str] = {}
    if evidence is not None:
        compact_pages = []
        for page in evidence["materials"]:
            ref = page["ref"]
            short = source_handle(ref, page["page"]["start"], page["page"]["end"])
            evidence_handles.setdefault(ref, short)
            compact: dict[str, Any] = {"ref": short}
            if profile == "ordinary":
                compact["speaker_ref"] = speaker_handle(ref)
            compact.update({key: page[key] for key in (
                "role", "session_id", "date", "status", "page",
            ) if key in page})
            compact["source_sequence"] = memory.source_sequence[ref]
            compact["provenance"] = "recorded_source_not_verified_truth"
            current_ref = page.get("current_ref")
            compact["current_version"] = (
                "this_exact_version" if current_ref == ref else "newer_version_requires_read"
            )
            compact["content"] = page["content"]
            compact_pages.append(compact)
        evidence["materials"] = compact_pages
        unexpanded = evidence["unexpanded"]
        evidence["unexpanded"] = [
            {"ref": evidence_handles[item["ref"]], "start": item["start"],
             "end": item["end"]}
            for item in unexpanded if item["ref"] in evidence_handles
        ]
        evidence["omitted_source_ranges"] = (
            len(unexpanded) - len(evidence["unexpanded"])
        )
        evidence["bytes"] = sum(
            len(json.dumps(page, ensure_ascii=False).encode())
            for page in compact_pages
        )
    selected_record_handles = {
        record["ref"]: f"r{index}" for index, record in enumerate(existing)
    }
    for dependency in dependencies:
        ref = dependency["ref"]
        if ref in selected_record_handles:
            continue
        current_ref = dependency.get("current_ref")
        handle = f"d{sum(item['kind'] == 'dependency' for item in handles.values())}"
        handles[handle] = {"kind": "dependency", "ref": ref}
        dependency["ref"] = handle
        if isinstance(dependency.get("about"), dict):
            about = dependency["about"]
            if about.get("kind") == "current_user":
                handles["u0"] = {"kind": "subject", "ref": "current_user"}
                dependency["about"] = {"kind": "current_user", "about_ref": "u0"}
            elif about.get("kind") == "unresolved":
                dependency["about"] = {"kind": "unresolved", "about_ref": "unknown"}
            elif about.get("kind") == "source_speaker":
                dependency["about"] = {
                    "kind": "source_speaker", "source_role": about.get("source_role"),
                }
        dependency["current_version"] = (
            "this_exact_version" if current_ref == ref else "newer_version_requires_read"
        )
        dependency.pop("current_ref", None)
    records = []
    for index, record in enumerate(existing):
        handle = f"r{index}"
        handles[handle] = {
            "kind": "record", "ref": record["ref"],
            "start": record["page"]["start"], "end": record["page"]["end"],
            "total_chars": record["page"]["total_chars"],
        }
        view: dict[str, Any] = {"ref": handle}
        about = record.get("about", {})
        if about.get("kind") == "current_user":
            handles["u0"] = {"kind": "subject", "ref": "current_user"}
            view["about"] = {"kind": "current_user", "about_ref": "u0"}
        elif about.get("kind") == "unresolved":
            view["about"] = {"kind": "unresolved", "about_ref": "unknown"}
        elif about.get("kind") == "actor":
            view["about"] = {"kind": "actor"}
            anchor = next((ref for ref in record.get("source_refs", [])
                           if memory.sources[ref].actor_ref == about.get("actor_ref")), None)
            if anchor is not None:
                view["about"]["about_ref"] = speaker_handle(anchor)
        elif about.get("kind") == "source_speaker":
            source_ref = about.get("source_ref")
            view["about"] = {"kind": "source_speaker",
                             "source_role": about.get("source_role")}
            if isinstance(source_ref, str):
                view["about"]["about_ref"] = speaker_handle(source_ref)
        view["source_refs"] = [
            evidence_handles[ref]
            for ref in record.get("source_refs", [])
        ]
        view["source_roles"] = {
            short: memory.sources[handles[short]["ref"]].role
            for short in view["source_refs"]
        }
        view["dependencies"] = [
            selected_record_handles[ref] if ref in selected_record_handles else
            next(short for short, bound in handles.items()
                 if bound["kind"] == "dependency" and bound["ref"] == ref)
            for ref in record.get("dependencies", [])
        ]
        view.update({key: record[key] for key in (
            "author", "subject", "context", "certainty", "conditions", "support_status",
            "applicability", "valid_from", "valid_until", "status",
            "page", "source_sequence", "text",
        ) if key in record})
        support_groups = []
        for group in record.get("justifications", []):
            key = f"g{sum(item['kind'] == 'group' for item in handles.values())}"
            handles[key] = {"kind": "group", "ref": group["group_id"]}
            support_groups.append({"group_id": key, **{k: group[k] for k in (
                "polarity", "status", "conditions", "valid_from", "valid_until",
            ) if k in group}})
        if support_groups:
            view["justifications"] = support_groups
        records.append(view)
    schema = proposal_schema(max_operations, profile)
    bind_proposal_handles(schema, handles, profile)
    protocol = (
        "Return one ChangeSet with a groups array, containing local operations arrays. "
        "Use op=claim to create or revise an interpretation, with alias new:c1 for a newly "
        "created version. In the same local group use op=justification targeting that alias "
        "to declare its actual supporting or opposing items. Items inside a justification "
        "are jointly needed; separate justifications are alternative paths. Do not mistake "
        "copies or summaries for independent observations. Justification items are source "
        "or record HANDLE STRINGS, never objects or handwritten offsets. Source_refs record "
        "provenance and do not establish support. Revised meanings need their own supports; "
        "For each claim based on provided observations, emit BOTH a claim operation and "
        "at least one justification operation in its group. A lone claim with source_refs "
        "will remain UNSUPPORTED. Only independently authored ideas without claimed evidence "
        "should be left unsupported. "
        "do not reuse an old version's support automatically. Retract only a delivered group_id "
        "when its interpretation of the evidence is no longer applicable. Each local group "
        "commits together; other groups may succeed independently. Empty groups are allowed. "
        "Aliases exist only in this proposal and may refer to earlier successful groups. "
        "For pending_review records, revise the claim/support when warranted, or use "
        "op=review with decision=keep to record completed review without changing support "
        "validity; decision=unresolved leaves that semantic review pending. "
        if profile in {"support", "events"}
        else "The program has already retained the delivered sources. Return one JSON object "
        "with an operations array for understanding maintenance only: op=CREATE with new "
        "content, op=REVISE with a delivered target_ref and either an exact local "
        "content_patch or full replacement content, "
        "or op=NO_CHANGE with reason=NO_NEW_MAINTAINABLE_FACT or ALREADY_COVERED. "
        "CREATE and full REVISE require an explicit full source_refs ARRAY of delivered sN "
        "observations and an about_ref: u0 only when a trusted owner binding was delivered, "
        "a delivered actor or source "
        "speaker handle, or unknown when subject identity is unresolved. A speaker anchor "
        "must have its sN source in source_refs. Author identifies who recorded an "
        "interpretation; it does not identify the person the claim is about. "
        "Full REVISE also requires the complete dependencies ARRAY of independently needed "
        "interpretation premises, using delivered rN or dN handles; [] explicitly clears "
        "old dependencies. The target's own prior version is history, not a premise. "
        "For local text changes on a fully delivered exact target, choose basis_mode=delta "
        "with content_patch and source_delta add/remove; optional dependency_delta does "
        "the same for premises. Inherited old relationships are not a claim of rereading. "
        "Use full REVISE for metadata or global meaning changes. "
        "Source_refs link interpretations to observations; never join handles into one "
        "string, invent refs, or refer to not-yet-created records. "
        "Compare earlier and later expressions about the same subject and matter using "
        "source_sequence and recorded date/session. Keep different matters separate, and "
        "preserve earlier meaning as history when a real change warrants revision. "
        "When a later expression changes a delivered record's meaning or scope, REVISE "
        "that record so its current text preserves the applicable meaning and explains "
        "the earlier scope; do not leave the superseded meaning unqualified beside a new card. "
        "CURRENT labels the latest stored version, not verified present-world truth. "
        "Retaining an observation and maintaining an "
        "interpretation are separate decisions: retained original evidence does not "
        "create or update a current user claim. When delivered "
        "observations warrant a reusable user fact, preference, constraint, or change, "
        "also use CREATE, or REVISE only for an actually changed delivered rN, with "
        "source_refs and warranted scope and certainty; use NO_CHANGE "
        "when no such interpretation is supported, and never invent one. "
        "Operations execute in order, individually. "
    )
    if profile == "events":
        protocol += (
            " Distinguish three events: state_change ends an old state and creates the new "
            "one, preserving the former interval; task_override applies only to this task "
            "and leaves the durable default intact; reinterpret corrects a previous "
            "interpretation of unchanged observations. Explicitly choose any group_ids "
            "whose original evidence still supports that corrected version; groups=[] "
            "transfers none. Add fresh justifications where the meaning or scope changed. "
            "Do not turn a temporary task request into a permanent state change. Only use "
            "world dates present in the observations; never invent an effective date. "
        )
    if maintenance_query is not None:
        protocol += (
            " This is the one permitted supplemental maintenance proposal for the current "
            "task. Known structural invalidation has already happened. Review the selected "
            "pending records for the legal task below. Revise exact versions and supports "
            "only when warranted; op=review with decision=keep records a completed review "
            "without changing validity. decision=unresolved leaves the item pending. "
            "An unsupported or invalid path never becomes valid merely because it was reviewed."
        )
    handle_protocol = (
        "Use ONLY delivered sN source handles, rN exact record handles, dN independent "
        "premise handles, actor or source-speaker handles, and u0/unknown subject handles. "
        "rN may be "
        "target_ref or a dependency; dN is only a dependency. Delivered related_records "
        "already contain the read exact versions; no separate memory_read is needed in "
        "this batch proposal. Use u0 for an explicit self-report by this user, and a p handle for "
        "a source speaker distinct from the current user. Do not write batch-local handles "
        "into stored prose as person names. "
        if profile == "ordinary" else
        "Use ONLY delivered sN source handles, rN exact record handles and gN group "
        "handles. rN versions have already been read. "
    )
    messages = [
        {
            "role": "system",
            "content": prompt
            + "\nHistorical batch protocol: "
            + protocol
            + handle_protocol
            + "The program binds identity, role, content hash and exact delivered range. "
            "Never write long IDs, start/end offsets, or unseen handles. "
            "Prefer revising the same subject and matter only when the target truly changes. "
            "The new current content should stand alone; old versions remain stored. "
            "Keep narrative scope and explanations in content/context; use only supplied "
            "structured condition definitions for external applicability predicates. "
            "Use exact calendar dates only in valid_from/valid_until; put relative time "
            "phrases in context. Do not answer a future question. "
            "Combine changes to one delivered rN version into ONE update; do not submit "
            "multiple independent updates against that same old version in this proposal. "
            f"Propose at most {max_operations} operations in total. Proposal schema: "
            + json.dumps(schema, ensure_ascii=False),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "phase": (
                        "maintenance" if maintenance_query is not None else "history_ingestion"
                    ),
                    "related_records": records,
                    **({"related_dependencies": [item for item in dependencies
                                               if item["ref"] not in selected_record_handles]}
                       if any(item["ref"] not in selected_record_handles
                              for item in dependencies) else {}),
                    "condition_definitions": {
                        key: {"meaning": definition.meaning,
                              "comparison": definition.comparison,
                              "value_type": "string"}
                        for key, definition in CONDITION_DEFINITIONS.items()
                    },
                    **({"related_original_sources": evidence} if evidence is not None else {}),
                    **({"task": maintenance_query} if maintenance_query is not None else {}),
                    "observations": delivered,
                },
                ensure_ascii=False,
            ),
        },
    ]
    if evidence is not None:
        messages[0]["content"] += (
            " Related original sources contain accurate acquired text, not new independent "
            "observations. Reconsider the old interpretation against those sources and the "
            "new batch in this same proposal; preserve their conditions and provenance. "
            "Unexpanded ranges are unavailable here; do not invent their contents."
        )
        emit({"event": "ingestion_source_context", "bytes": evidence["bytes"],
              "sources": len(evidence["materials"]), "unexpanded": evidence["unexpanded"]})
    emit({"event": "local_execution", "operation": "prepare_ingestion",
          **{key: value - local_before[key] for key, value in memory.local_timings.items()}})
    return {"protocol": PROTOCOL_VERSION, "proposal_id": uuid4().hex,
            "profile": profile, "messages": messages,
            "schema": schema, "handles": handles, "max_operations": max_operations,
            "related_record_refs": [record["ref"] for record in existing],
            "proposal_valid": False, "unit_receipts": {}, "committed_units": [],
            "unsubmitted_units": [], "aliases": {}, "state": "prepared"}


def ingest_chunk(
    memory: ContextualMemory,
    observations: list[dict[str, Any]],
    *,
    host: VLLMClient,
    prompt: str,
    max_operations: int,
    context_bytes: int,
    emit: Emit,
    profile: str = "ordinary",
    old_source_bytes: int = 0,
    maintenance_query: str | None = None,
    state: dict[str, Any] | None = None,
    persist: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Freeze a proposal before applying units; persist each actual local commit boundary."""
    started = time.monotonic()
    if state is None:
        state = prepare_ingestion(
            memory, observations, prompt=prompt, max_operations=max_operations,
            context_bytes=context_bytes, emit=emit, profile=profile,
            old_source_bytes=old_source_bytes, maintenance_query=maintenance_query,
        )
    if state["protocol"] != PROTOCOL_VERSION:
        raise ValueError("INGESTION_PROTOCOL_MISMATCH")
    if not isinstance(state.get("proposal_id"), str) or not state["proposal_id"]:
        raise ValueError("INGESTION_PROPOSAL_ID_MISSING")

    def save() -> None:
        if state["proposal_valid"]:
            state["committed_units"] = [
                int(index) for index, call in state["unit_receipts"].items()
                if call["operation_receipt"]["completion"] in {"complete", "pending"}
            ]
            state["unsubmitted_units"] = [
                index for index in range(len(state["units"]))
                if index not in state["committed_units"]
            ]
        if persist is not None:
            persist(state)

    if state["state"] in {"request_started", "invalid"}:
        raise ValueError("UNFINISHED_PROPOSAL_REQUIRES_EXPLICIT_REPAIR")
    if not state["proposal_valid"]:
        state["state"] = "request_started"
        save()
        receipt = host.chat(
            state["messages"],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "historical_memory_proposal",
                    "strict": True,
                    "schema": state["schema"],
                },
            },
        )
        state["raw_receipt"] = receipt
        state["state"] = "invalid"
        save()
        choice = receipt["choices"][0]
        if choice.get("finish_reason") == "length":
            state["failure"] = "TRUNCATED"
            emit({"event": "ingestion_rejected", "reason": "TRUNCATED"})
            save()
            raise ValueError("Historical proposal truncated; no operations executed")
        changes: list[dict[str, Any]] = []
        try:
            proposal = normalize_sets(json.loads(choice["message"]["content"]), changes)
            validate(proposal, state["schema"])
            resolved = normalize_sets(resolve_handles(proposal, state["handles"]), changes)
            if profile in {"support", "events"}:
                if sum(len(group["operations"]) for group in proposal["groups"]) > max_operations:
                    raise ValueError("Historical ChangeSet exceeds total operation budget")
                validate(resolved, CHANGESET_SCHEMA)
                units = [{"changeset": {"groups": [group]}} for group in resolved["groups"]]
            else:
                units = resolved["operations"]
                for unit in units:
                    if unit.get("op") != "REVISE" or "content_patch" not in unit:
                        continue
                    binding = next((item for item in state["handles"].values()
                                    if item["kind"] == "record"
                                    and item["ref"] == unit["target_ref"]), None)
                    if binding is None:
                        raise ValueError("CONTENT_PATCH_TARGET_NOT_DELIVERED")
                    original = memory.read(
                        unit["target_ref"], include_sources=False,
                        length=binding["total_chars"], max_bytes=0, _visible=False,
                    )["text"]
                    apply_content_patch(original, unit["content_patch"],
                                        visible_spans=[(binding["start"], binding["end"])])
        except (ValueError, ValidationError) as error:
            state["failure"] = {"type": type(error).__name__, "message": str(error)[:1000]}
            emit({"event": "ingestion_rejected", "reason": "STRUCTURE_OR_HANDLE",
                  "error": state["failure"]})
            save()
            raise
        state.update(proposal=proposal, units=units, normalizations=changes,
                     proposal_valid=True, state="validated")
        emit({"event": "ingestion_normalization", "changes": changes})
        save()
    # Restored checkpoints need the same explicitly delivered read versions, not latest aliases.
    for binding in state["handles"].values():
        if binding["kind"] in {"record", "dependency"}:
            memory.read(binding["ref"], include_sources=False)
        elif binding["kind"] == "source":
            source = memory.sources[binding["ref"]]
            if hashlib.sha256(source.content.encode()).hexdigest() != binding["content_sha256"]:
                raise ValueError("FROZEN_HANDLE_CONTENT_CHANGED")
            memory.read(binding["ref"], include_sources=False,
                        start=binding["start"],
                        length=binding["end"] - binding["start"], max_bytes=0)
    for index, unit in enumerate(state["units"]):
        if str(index) in state["unit_receipts"]:
            continue
        arguments = resolve_aliases(unit, state["aliases"])
        proposal_reason = arguments.pop("reason", None)
        unit_started = time.monotonic()
        result = memory.dispatch(
            "memory_save", arguments,
            operation_id=f"ingest:{state['proposal_id']}:{index}",
        )
        emit({"event": "local_execution", "operation": "ingestion_commit",
              "dispatch_seconds": time.monotonic() - unit_started})
        receipt_result = receipt_outcome("memory_save", result)
        call = {
            "name": "memory_save",
            "arguments": arguments,
            "ok": receipt_result.ok,
            "result": result,
            "operation_receipt": asdict(receipt_result),
        }
        if proposal_reason is not None:
            call["proposal_reason"] = proposal_reason
        state["unit_receipts"][str(index)] = call
        state["aliases"].update(result.get("changeset", {}).get("aliases", {}))
        state["state"] = "committing"
        save()
        emit({"event": "host_tool_call", "call": call})
    calls = list(state["unit_receipts"].values())
    failed = any(
        call["operation_receipt"]["completion"] in {"failed", "partial_failure"}
        for call in calls
    )
    state["state"] = "unsettled" if failed else "settled"
    save()
    emit({"event": "ingestion_settlement", "proposal_valid": True,
          "local_units": len(state["units"]), "committed_units": len(state["committed_units"]),
          "unsubmitted_units": len(state["unsubmitted_units"]),
          "maintenance_settled": not failed})
    return {
        "status": "partial_failure" if failed else
                  "pending" if any(not call["ok"] for call in calls) else "complete",
        "proposal": state["proposal"],
        "calls": calls,
        "related_record_refs": state["related_record_refs"],
        "proposal_valid": state["proposal_valid"],
        "maintenance_settled": not failed,
        "normalizations": state["normalizations"],
        "usage": state["raw_receipt"].get("usage"),
        "elapsed_seconds": time.monotonic() - started,
    }
