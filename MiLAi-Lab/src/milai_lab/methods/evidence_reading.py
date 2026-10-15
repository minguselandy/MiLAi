"""Question-local evidence packs over existing Source ranges and immutable revisions."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.dependency_groups import select_support_routes, support_status
from milai_lab.memory.edit_units import read_revision_evidence
from milai_lab.memory.external_support import inspect_external_unit
from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.memory.retrieval import flat_bm25_rank, merge_candidates
from milai_lab.memory.service import MemoryService
from milai_lab.memory.working_set import material_ref, plan_delivery
from milai_lab.methods.dependency_memory import query_support
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.edit_memory import EditMemory


def unit_closure(state: dict[str, Any], unit_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Follow declared condition/exception edges, never textual similarity."""
    selected = {unit_id}
    changed = True
    while changed:
        previous = len(selected)
        for relation in state.get("relations", []):
            source, target = relation["source_unit"], relation["target_unit"]
            if target in selected:
                selected.add(source)
            if source == unit_id or (
                    source in selected and relation["relation_type"] == "overrides"):
                selected.add(target)
        selected, _ = select_support_routes(state, selected)
        changed = len(selected) != previous
    return ([unit["unit_id"] for unit in state["units"] if unit["unit_id"] in selected],
            [relation for relation in state.get("relations", [])
             if relation["source_unit"] in selected and relation["target_unit"] in selected])


def fixed_history_candidates(
    service: MemoryService, records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose the same actual versions to both Readers in a controlled comparison.

    This is an explicit experimental pool expansion, not ordinary retrieval.
    Each supplied revision bounds its history: reopening an earlier checkpoint
    against a later bank never admits later revisions. Current visibility still
    applies. Unit navigation is removed so both policies may select from the
    whole retrieved record, including its old conditions and change witnesses.
    """
    result = []
    seen: set[tuple[str, int]] = set()
    for row in records:
        record_id, bound = row["id"], row["value"]["revision"]
        revisions, cursor = [bound], None
        while True:
            page = service.history_index(record_id, cursor=cursor)
            revisions.extend(revision for revision in page.get("revisions", [])
                             if revision < bound)
            cursor = page.get("next_cursor")
            if cursor is None:
                break
        for revision in dict.fromkeys(revisions):
            identity = (record_id, revision)
            if identity in seen:
                continue
            seen.add(identity)
            actual = service.read(record_id, revision)
            if actual["ok"]:
                result.append({**actual, "fixed_history_pool": True,
                               **({"historical_selection": True}
                                  if revision != bound else {})})
    return result


def build_evidence_packs(
    service: MemoryService, question: str, date: str, originals: list[dict[str, Any]],
    records: list[dict[str, Any]], *,
    tokenization: Literal["rawrag_space", "unicode_v1"] = "unicode_v1",
    calendar_context: str | None = None,
    source_scope: dict[str, Any] | None = None,
    dependency_selections: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split only the captured pool; keep complete exchanges and one preceding exchange.

    Full captured parent ranges stay program-side for explicit context expansion.
    No later session source, semantic formation or new retrieval enters this pool.
    """
    source_packs = []
    retrieved_ids = {item["id"] for item in originals}
    additional = (service.read_source_materials([
        item for item in source_scope["materials"] if item["id"] not in retrieved_ids
    ]) if source_scope is not None else [])
    for material in [*originals, *additional]:
        turns = json.loads(material["text"])
        if not turns:
            continue
        starts = [i for i, turn in enumerate(turns) if turn["role"] == "user"]
        if not starts or starts[0] != 0:
            starts.insert(0, 0)
        for ordinal, (start, end) in enumerate(zip(starts, [*starts[1:], len(turns)], strict=True)):
            context_start = starts[max(0, ordinal - 1)]
            focused = turns[start:end]
            descriptors = material["source_ranges"][context_start:end]
            source_packs.append({
                **material, "id": f"{material['id']}:exchange:{start}",
                "source_ranges": descriptors,
                "turn_range": [material["turn_range"][0] + context_start,
                               material["turn_range"][0] + end],
                "text": json.dumps(turns[context_start:end], ensure_ascii=False),
                "focus_source_ranges": material["source_ranges"][start:end],
                "context_source_ranges": material["source_ranges"],
                "context_turn_range": material["turn_range"],
                "index_text": " ".join(turn["content"] for turn in focused),
                "pack_kind": "exchange_with_previous_context",
                "scope_only": material["id"] not in retrieved_ids,
            })
    # Search within the identical original pool. RawRAG's own fixed path is unchanged.
    ranked = flat_bm25_rank(source_packs, question, len(source_packs),
                           tokenization=tokenization)
    semantic = []
    selected_records = list(records)
    external_seen: set[tuple[str, int, str]] = set()

    def queue_external(row: dict[str, Any], unit_id: str, *, historical: bool) -> str:
        version = row["value"]["revision"]
        identity = (row["id"], version, unit_id)
        pack_id = f"{row['id']}:external:{version}:{unit_id}"
        if identity not in external_seen:
            external_seen.add(identity)
            selected_records.append({**row, "external_context": True,
                "external_pack_id": pack_id, "historical_selection": historical,
                "retrieval_navigation": {"unit_id": unit_id}})
        return pack_id

    seen_versions = {(row["id"], row["value"]["revision"]) for row in records}
    for row in records:
        if row.get("fixed_history_pool"):
            continue
        selection = (dependency_selections or {}).get(row["id"], {})
        for revision in dict.fromkeys(selection.get("history_revisions", [])):
            identity = (row["id"], revision)
            if identity in seen_versions:
                continue
            historical = service.read(row["id"], revision)
            if historical["ok"]:
                selected_records.append({**historical, "historical_selection": True})
                seen_versions.add(identity)
    for row in selected_records:
        version = row["value"]
        state = version.get("edit_state")
        if not state:
            continue
        hit = row.get("retrieval_navigation", {}).get("unit_id")
        selection = (None if row.get("external_context") else
                     (dependency_selections or {}).get(row["id"]))
        historical = row.get("historical_selection", False)
        if (historical and row.get("fixed_history_pool") and selection is not None
                and version["revision"] not in selection["history_revisions"]):
            continue
        ids, relations = (query_support(state, selection["roots"],
                                       excluded=selection["excluded"],
                                       support_choices=selection.get("support_choices"))
                          if selection is not None and not historical else
                          unit_closure(state, hit) if hit else
                          ([unit["unit_id"] for unit in state["units"]],
                           state.get("relations", [])))
        if not ids and selection is not None and not selection["history_revisions"]:
            continue
        selected_units = [unit for unit in state["units"] if unit["unit_id"] in ids]
        _, groups = select_support_routes(
            state, set(ids),
            choices=(selection or {}).get("support_choices") if not historical else None)
        for group in groups:
            external = {}
            needed = {uid for route in group["alternatives"] for uid in route}
            for uid, reference in group.get("external_units", {}).items():
                if uid not in needed:
                    continue
                inspected = inspect_external_unit(service, reference, historical=historical)
                entry: dict[str, Any] = {"status": inspected["status"],
                                         "unit_id": reference["unit_id"]}
                if "current_record" in inspected:
                    entry["current_pack"] = queue_external(
                        inspected["current_record"], reference["unit_id"], historical=historical)
                if inspected["status"] in {"changed", "retracted"}:
                    entry["bound_pack"] = queue_external(
                        inspected["bound_record"], reference["unit_id"], historical=True)
                if inspected["status"] not in {"unchanged", "historical"}:
                    group["changed_premises"] = list(dict.fromkeys([
                        *group.get("changed_premises", []), uid]))
                external[uid] = entry
            if external:
                group["external_references"] = external
        handles = list(dict.fromkeys(ref["evidence_id"]
                                    for item in [*selected_units, *relations, *groups]
                                    for ref in item["evidence_refs"]))
        if (historical or row.get("fixed_history_pool") or row.get("external_context")
                or (selection is not None and selection["history_revisions"])):
            # A retraction's witness may no longer support any surviving unit.
            handles = list(dict.fromkeys([*handles, *version.get("revision_evidence", []),
                                         *(ref for edit in version.get("edit_operations", [])
                                           for ref in edit["evidence"])]))
        view = EditMemory.revision_view(version, query_time=date,
                                       query_calendar_context=calendar_context)
        time_applicability = {
            unit["unit_id"]: False if unit.get("temporal", {}).get("status") in {
                "expired", "before_explicit_start", "inconsistent_explicit_limits"} else None
            for unit in view["units"]
        }
        for group in groups:
            group["selected_routes_time_eligibility"] = (
                "all_routes_time_ineligible_or_absent"
                if support_status(group, time_applicability) == "unsupported"
                else "requires_source_interpretation")
        view["units"] = [unit for unit in view["units"] if unit["unit_id"] in ids]
        view["relations"] = copy.deepcopy(relations)
        if "support_groups" in state:
            view["support_groups"] = groups
        semantic.append({
            "kind": "semantic_view",
            "id": row.get("external_pack_id", f"{row['id']}:history:{version['revision']}"
                          if historical else row["id"]),
            "record_id": row["id"],
            "revision": version["revision"], "scope": version["scope"],
            "matter_description": state.get("matter_description", version["scope"]),
            "applicability": view, "selected_unit_ids": ids,
            "view_dependencies": {"record_id": row["id"], "revision": version["revision"],
                                  "unit_ids": ids, "root_unit_id": hit,
                                  **({"support_groups": copy.deepcopy(groups)}
                                     if "support_groups" in state else {}),
                                  "relation_ids": [edge["relation_id"] for edge in relations]},
            "revision_evidence": read_revision_evidence(service, {"revision_evidence": handles}),
            "index_text": "\n".join(unit["text"] for unit in selected_units),
            "pack_kind": "supported_semantic_units",
            **({"dependency_selection": copy.deepcopy(selection)} if selection is not None else {}),
            **({"version_view": "historical_exact_revision"} if historical else {}),
        })
    packs = merge_candidates([[item for item in ranked if not item["scope_only"]], semantic])
    packs.extend(item for item in ranked if item["scope_only"])
    positions = {item["id"]: index for index, item in enumerate(packs)}
    for pack in packs:
        for group in pack.get("applicability", {}).get("support_groups", []):
            for entry in group.get("external_references", {}).values():
                for key in ("current_pack", "bound_pack"):
                    if key in entry:
                        entry[key + "_index"] = positions[entry[key]]
                        units = packs[positions[entry[key]]].get("selected_unit_ids", [])
                        entry[key + "_unit"] = (f"u{units.index(entry['unit_id'])}"
                                                if entry["unit_id"] in units else None)
    if packs:
        packs[0]["source_scope"] = {
            "complete": bool(source_scope and source_scope["complete"]),
            "basis": source_scope["basis"] if source_scope else "retrieved_pool",
            "required_ranges": merge_source_ranges([
                span for item in [*originals, *additional] for span in item["source_ranges"]]),
        }
    return packs


def dependency_read_request(
    service: MemoryService, question: str, date: str, records: list[dict[str, Any]], *,
    calendar_context: str | None = None,
) -> dict[str, Any]:
    """One bounded model decision over actual state and available revision numbers.

    The caller meters this selection with its existing provider and budget. Exact
    old bodies are opened only after selection, then passed to the common Reader.
    """
    fixed_versions: dict[str, list[int]] = {}
    for row in records:
        if row.get("fixed_history_pool"):
            fixed_versions.setdefault(row["id"], []).append(row["value"]["revision"])
    records = list({row["id"]: row for row in records if row["value"].get("edit_state")
                    and not row.get("historical_selection")}.values())
    full = [{key: value for key, value in row.items() if key != "retrieval_navigation"}
            for row in records]
    packs = build_evidence_packs(service, question, date, [], full,
                                calendar_context=calendar_context)
    bodies = project_packs(open_evidence_packs(service, packs), list(range(len(packs))))
    properties: dict[str, Any] = {}
    mapping, history = {}, {}
    for index, row in enumerate(records):
        alias = f"r{index}"
        units = [unit["unit_id"] for unit in row["value"]["edit_state"]["units"]]
        revisions, cursor = [], None
        if row["id"] in fixed_versions:
            revisions = fixed_versions[row["id"]]
        else:
            while True:
                page = service.history_index(row["id"], cursor=cursor)
                revisions.extend(revision for revision in page.get("revisions", [])
                                 if revision <= row["value"]["revision"])
                cursor = page.get("next_cursor")
                if cursor is None:
                    break
        history[alias] = {"pack": f"e{index}", "revisions": revisions,
                          "current_revision": row["value"]["revision"]}
        mapping[alias] = {"record_id": row["id"], "units": units}
        refs = ({"type": "array", "items": {"type": "integer", "enum": list(range(len(units)))}}
                if units else {"type": "array", "maxItems": 0})
        properties[alias] = {
            "type": "object", "additionalProperties": False,
            "properties": {"roots": refs, "excluded": copy.deepcopy(refs),
                           "history_revisions": {"type": "array", "items": {
                               "type": "integer", "enum": revisions}} if revisions else {
                                   "type": "array", "maxItems": 0}},
            "required": ["roots", "excluded", "history_revisions"],
        }
        if row["value"]["edit_state"].get("support_groups"):
            choices = {}
            for group in row["value"]["edit_state"]["support_groups"]:
                key = f"u{units.index(group['target_unit'])}"
                choices[key] = ({"type": "array", "items": {"type": "integer", "enum":
                    list(range(len(group["alternatives"])))}} if group["alternatives"] else
                    {"type": "array", "maxItems": 0})
            properties[alias]["properties"]["support_choices"] = {
                "type": "object", "additionalProperties": False, "properties": choices,
                "description": "For each selected derived target, select sufficient alternative "
                               "route indexes. Every premise in a selected route is opened. "
                               "Omitted targets retain all routes as candidates.",
            }
            properties[alias]["required"].append("support_choices")
    schema = {"type": "object", "additionalProperties": False,
              "properties": properties, "required": list(properties)}
    return {"schema": schema, "mapping": mapping,
            "delivered_source_refs": list(dict.fromkeys(
                span["source_ref"] for pack in packs
                for span in [*pack.get("source_ranges", []), *pack.get("support_turns", [])])),
            "messages": [
        {"role": "system", "content": (
            "Select query roots from actual memory and exclusions that are unnecessary for "
            "this question's scope. Unit numbers correspond to u0,u1,... in each pack. "
            "The program opens prerequisites and exceptions of roots, not unrelated sibling "
            "claims. An alternative support that suffices need not open every alternative. "
            "For historical saved-state or change explanations, choose actual history_revisions; "
            "current support alone cannot recover a withdrawn rule or its reason. History "
            "numbers are navigation, not proof of their contents. Later corrections do not "
            "rewrite what was saved earlier. These decisions select evidence only; they do "
            "not update memory or answer the question. Return the supplied schema."
        )},
        {"role": "user", "content": json.dumps({"question": question, "query_time": date,
            "memories": bodies, "history": history, "response_schema": schema},
            ensure_ascii=False, separators=(",", ":"))},
    ]}


def decode_dependency_reads(request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(request["schema"]).validate(response)
    return {row["record_id"]: {
        "roots": [row["units"][i] for i in response[alias]["roots"]],
        "excluded": [row["units"][i] for i in response[alias]["excluded"]],
        "history_revisions": response[alias]["history_revisions"],
        **({"support_choices": {row["units"][int(target[1:])]: indexes
                                for target, indexes in response[alias]["support_choices"].items()}}
           if "support_choices" in response[alias] else {}),
    } for alias, row in request["mapping"].items()}


def open_evidence_packs(
    service: MemoryService, materials: list[dict[str, Any]], *, expand_context: bool = False,
    refresh_current: bool = False,
) -> list[dict[str, Any]]:
    """Reopen selected exact sources/versions under current visibility, without search."""
    result = []
    for original in materials:
        item = copy.deepcopy(original)
        if item["kind"] == "original_source":
            if expand_context:
                item["source_ranges"] = item.get("context_source_ranges", item["source_ranges"])
                item["turn_range"] = item.get("context_turn_range", item["turn_range"])
            actual = service.read_source_materials([item])[0]
            focus = {span["source_ref"] for span in item.get(
                "focus_source_ranges", item["source_ranges"])}
            current_text = " ".join(turn["content"] for turn in json.loads(actual["text"])
                                    if turn["source_ref"] in focus)
            result.append({**item, **actual, "index_text": current_text})
        else:
            actual = service.read(item["record_id"], item["revision"])
            if not actual["ok"]:
                result.append({"kind": "semantic_view", "record_id": item["record_id"],
                               "visibility": actual["status"], "body_delivered": False})
                continue
            historical = item.get("version_view") == "historical_exact_revision"
            current = (service.read(item["record_id"])
                       if refresh_current and not historical else actual)
            item["version_view"] = ("historical_exact_revision" if historical
                                    else "current_at_snapshot")
            item["dependency_status"] = ("frozen_historical" if historical else
                                         "current" if refresh_current else "frozen_snapshot")
            if not current["ok"]:
                item["version_view"] = "historical_exact_revision"
                item["dependency_status"] = "current_unavailable"
            elif current["value"]["revision"] != item["revision"]:
                dependencies = item.get("view_dependencies")
                changed = dependencies is None
                selection = copy.deepcopy(item.get("dependency_selection"))
                groups_changed = (actual["value"]["edit_state"].get("support_groups")
                                  != current["value"]["edit_state"].get("support_groups"))
                if selection is not None and groups_changed:
                    # Route positions belong to their old revision. Reopen new
                    # candidates instead of reusing an index for a different OR route.
                    selection.pop("support_choices", None)
                if dependencies is not None:
                    root = dependencies["root_unit_id"]
                    old_state = actual["value"]["edit_state"]
                    new_state = current["value"]["edit_state"]
                    ids, edges = (query_support(new_state, selection["roots"],
                                               excluded=selection["excluded"],
                                               support_choices=selection.get("support_choices"))
                                  if selection is not None else
                                  unit_closure(new_state, root) if root is not None else
                                  ([unit["unit_id"] for unit in new_state["units"]],
                                   new_state["relations"]))
                    old_ids = dependencies["unit_ids"]
                    old_edges = [edge for edge in old_state["relations"]
                                 if edge["relation_id"] in dependencies["relation_ids"]]
                    changed = (ids != old_ids or edges != old_edges or
                               [unit for unit in old_state["units"] if unit["unit_id"] in old_ids]
                               != [unit for unit in new_state["units"] if unit["unit_id"] in ids])
                    changed = changed or groups_changed
                item["current_record_revision"] = current["value"]["revision"]
                item["dependency_status"] = "changed" if changed else "retained_units_unchanged"
                item["version_view"] = "historical_exact_revision" if changed else "current_units"
                if changed and refresh_current:
                    root = dependencies["root_unit_id"] if dependencies else None
                    current_ids = {
                        unit["unit_id"] for unit in current["value"]["edit_state"]["units"]
                    }
                    retracted = (not set(selection["roots"]) & current_ids
                                 and not selection["history_revisions"] if selection is not None
                                 else root is not None and root not in current_ids)
                    if retracted:
                        result.append({"kind": "semantic_view", "record_id": item["record_id"],
                                       "visibility": "selected_unit_retracted",
                                       "body_delivered": False})
                        continue
                    if root is not None:
                        current["retrieval_navigation"] = {"unit_id": root, "key_kind": "unit"}
                    view = item["applicability"]
                    item = build_evidence_packs(
                        service, "", view.get("query_time") or "", [], [current],
                        calendar_context=view.get("query_calendar_context"),
                        dependency_selections=({item["record_id"]: selection}
                                               if selection is not None else None),
                    )[0]
                    item.update(version_view="current_at_snapshot",
                                dependency_status="refreshed_explicit_dependencies")
                    if groups_changed:
                        item["support_selection_status"] = "new_revision_routes_reopened"
            if refresh_current and item["version_view"] != "historical_exact_revision":
                parent_changed = item["revision"] != original["revision"]
                for group in item.get("applicability", {}).get("support_groups", []):
                    for uid, reference in group.get("external_units", {}).items():
                        inspected = inspect_external_unit(service, reference)
                        entry = group.get("external_references", {}).get(uid)
                        if entry is None:
                            continue
                        entry["status"] = inspected["status"]
                        if parent_changed:
                            # Rebuilding one parent cannot invent indices in the
                            # caller's old pool for newly referenced foreign units.
                            for key in ("current_pack_index", "bound_pack_index",
                                        "current_pack_unit", "bound_pack_unit"):
                                entry.pop(key, None)
                        if parent_changed or inspected["status"] != "unchanged":
                            item["external_support_refresh"] = "new_dependency_pool_required"
                            group["changed_premises"] = list(dict.fromkeys([
                                *group.get("changed_premises", []), uid]))
                            group["selected_routes_time_eligibility"] = (
                                "requires_source_interpretation")
            # A retained interpretation never bypasses current support visibility.
            evidence = []
            for span in item["revision_evidence"]:
                source = service.source(span["source_ref"])
                if source is None:
                    continue
                descriptor = {"kind": "original_source", "id": span["source_ref"],
                              "session_id": source["session"], "turn_range": [0, 1],
                              "source_ranges": [span]}
                evidence.extend(json.loads(service.read_source_materials([descriptor])[0]["text"]))
            result.append({**item, "support_turns": evidence})
    return result


def project_pack(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Short labels and literal evidence; locations and operation handles stay in the pool."""
    result: dict[str, Any] = {"label": f"e{index}", "kind": item["kind"]}
    if item.get("external_support_refresh"):
        result["external_support_refresh"] = item["external_support_refresh"]
    if item.get("visibility") not in (None, "visible"):
        result["visibility"] = item["visibility"]
    if item.get("body_delivered") is False:
        return result
    if item["kind"] == "external_memory":
        return {**result, "content": item["text"], "native_timestamp": item.get("date"),
                "provenance": item["provenance"], "source_mapping": item["source_mapping"]}
    turns = (json.loads(item["text"]) if item["kind"] == "original_source"
             else item.get("support_turns", []))
    sources = {turn["source_ref"]: f"e{index}:s{i}" for i, turn in enumerate(turns)}
    result["evidence"] = [{"source": sources[turn["source_ref"]], **{
        key: turn[key] for key in ("role", "origin", "content", "occurred_at", "observed_at",
                                   "calendar_context", "range") if key in turn},
        "report_time": turn.get("occurred_at", turn.get("timestamp")),
    } for turn in turns]
    if item["kind"] == "semantic_view":
        view = item["applicability"]
        ids = {unit["unit_id"]: f"u{i}" for i, unit in enumerate(view["units"])}
        result.update(scope=item["scope"], matter=item["matter_description"],
                      revision=item["revision"], version_view=item.get("version_view"),
                      dependency_status=item.get("dependency_status"))
        result["units"] = [{"unit": ids[unit["unit_id"]], **{
            key: copy.deepcopy(unit[key]) for key in ("text", "role", "applicability", "temporal")
            if key in unit}, "assertion": {
                key: sources.get(value, "support_not_opened") if key == "source_ref" else value
                for key, value in unit.get("assertion", {}).items()
                if key not in {"source_revision"}
            }} for unit in view["units"]]
        result["relations"] = [{"source": ids[link["source_unit"]],
                                "target": ids[link["target_unit"]],
                                "relation_type": link["relation_type"]}
                               for link in view.get("relations", [])]
        if "support_groups" in view:
            external_ids = {uid for group in view["support_groups"]
                            for uid in group.get("external_references", {})}
            ids.update({uid: f"x{i}" for i, uid in enumerate(sorted(external_ids))})
            result["support_groups"] = [{
                "target": ids[group["target_unit"]],
                "alternatives": [[ids[uid] for uid in route] for route in group["alternatives"]],
                "selected_route_indices": group.get("selected_route_indices"),
                "total_routes": group.get("total_routes", len(group["alternatives"])),
                "selected_routes_time_eligibility": group.get("selected_routes_time_eligibility"),
                "changed_premises": [ids[uid] for uid in group.get("changed_premises", [])
                                     if uid in ids],
                **({"changed_target": True} if group.get("changed_target") else {}),
                **({"external_references": [{"reference": ids[uid], "status": ref["status"],
                    **({"current_pack_index": ref["current_pack_index"]}
                       if "current_pack_index" in ref else {}),
                    **({"current_unit": ref["current_pack_unit"]}
                       if "current_pack_unit" in ref else {}),
                    **({"bound_pack_index": ref["bound_pack_index"]}
                       if "bound_pack_index" in ref else {}),
                    **({"bound_unit": ref["bound_pack_unit"]}
                       if "bound_pack_unit" in ref else {})}
                    for uid, ref in group["external_references"].items()]}
                   if group.get("external_references") else {}),
                **({"external_semantics": "Pack indices locate actual prerequisite material. "
                    "Undelivered bodies are not evidence; changed bindings need reinterpretation."}
                   if group.get("external_references") else {}),
                "semantics": "OR_of_AND; model_interpretation_not_verified_truth",
            } for group in view["support_groups"]]
    return result


SOURCE_REUSE_INSTRUCTIONS = (
    "Source labels are shared across packs. reused_sources points to evidence already shown; "
    "also_selected_as lists other selected labels for the same Source ranges. Neither adds "
    "another observation or event."
)


def project_packs(items: list[dict[str, Any]], indices: list[int]) -> list[dict[str, Any]]:
    """Render one body for exactly repeated visible Source ranges.

    Expanding several hits in one session may reopen the same complete parent.
    Keep the selected aliases, without repeating that parent in the model input.
    Global short Source labels also distinguish reused context from new evidence.
    Different sources, partial visibility and semantic views remain separate.
    """
    result = []
    opened_units = {(index, unit["unit_id"]): f"u{position}"
                    for item, index in zip(items, indices, strict=True)
                    if item.get("body_delivered") is not False
                    for position, unit in enumerate(item.get("applicability", {}).get("units", []))}
    originals: dict[tuple[tuple[Any, ...], ...], dict[str, Any]] = {}
    sources: dict[tuple[str, int], str] = {}
    spans: set[tuple[str, int, tuple[int, ...]]] = set()
    for item, index in zip(items, indices, strict=True):
        ranges = tuple(tuple(span[key] for key in (
            "source_ref", "source_revision", "start", "end"))
            for span in item.get("source_ranges", []))
        shared = (item["kind"] == "original_source" and bool(ranges)
                  and item.get("visibility") == "visible"
                  and item.get("body_delivered") is True
                  and not item.get("unavailable_source_ranges"))
        if shared and ranges in originals:
            originals[ranges].setdefault("also_selected_as", []).append(f"e{index}")
            continue
        projected = project_pack(item, index)
        for group in projected.get("support_groups", []):
            for reference in group.get("external_references", []):
                raw_groups = item.get("applicability", {}).get("support_groups", [])
                raw_references = [ref for g in raw_groups
                                  for ref in g.get("external_references", {}).values()]
                for key in ("current", "bound"):
                    target = reference.get(key + "_pack_index")
                    raw = next((r for r in raw_references
                                if r.get(key + "_pack_index") == target), None)
                    unit = opened_units.get((target, raw["unit_id"])) if raw is not None else None
                    reference[key + "_body_delivered"] = unit is not None
                    if unit is not None:
                        reference[key + "_unit"] = unit
        if "evidence" in projected:
            turns = (json.loads(item["text"]) if item["kind"] == "original_source"
                     else item.get("support_turns", []))
            evidence, local_sources, reused = [], set(), []
            for turn, body in zip(turns, projected["evidence"], strict=True):
                source = (turn["source_ref"], turn.get("source_revision", 1))
                alias = sources.setdefault(source, f"s{len(sources)}")
                local_sources.add(source)
                body["source"] = alias
                span = (*source, tuple(turn["range"]))
                if span in spans:
                    if alias not in reused:
                        reused.append(alias)
                else:
                    evidence.append(body)
                    spans.add(span)
            projected["evidence"] = evidence
            if reused:
                projected["reused_sources"] = reused
            for original, unit in zip(item.get("applicability", {}).get("units", []),
                                      projected.get("units", []), strict=True):
                assertion = original.get("assertion", {})
                if "source_ref" in assertion:
                    source = (assertion["source_ref"], assertion.get("source_revision", 1))
                    unit["assertion"]["source_ref"] = (
                        sources[source] if source in local_sources else "support_not_opened")
        result.append(projected)
        if shared:
            originals[ranges] = projected
    return result


def pack_candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
    """An explicitly incomplete navigation excerpt, never an evidence body."""
    text = item.get("index_text", "") if item.get("body_delivered") is not False else ""
    return {"item_index": index, "kind": item["kind"], "navigation_only": True,
            "excerpt": text[:160], "excerpt_truncated": len(text) > 160,
            "date": item.get("date"), "visibility": item.get("visibility", "visible"),
            "can_expand_context": bool(item.get("context_source_ranges"))}



def admit_pack_indices(wanted: list[int], fits: Callable[[list[int]], bool]) -> dict[str, Any]:
    """Honor model priority and measure the caller's complete input wrapper."""
    # Repeating a read target does not request another observation or increase
    # its priority. Keep its first position for both Benchmark and Host callers.
    wanted = list(dict.fromkeys(wanted))
    accepted: list[int] = []
    for index in wanted:
        if fits([*accepted, index]):
            accepted.append(index)
    return {"admitted_indices": accepted,
            "excluded_indices": [i for i in wanted if i not in accepted]}


def pack_coverage(
    materials: list[dict[str, Any]], opened: list[dict[str, Any]], *,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare literal source ranges; never infer that unseen text is irrelevant."""
    if scope is None:
        scope = materials[0].get("source_scope", {}) if materials else {}
    required = scope.get("required_ranges", [])
    delivered = merge_source_ranges([span for item in opened if item["kind"] == "original_source"
                                     for span in item["source_ranges"]])
    missing = [span for span in required if not any(
        actual["source_ref"] == span["source_ref"]
        and actual["source_revision"] == span["source_revision"]
        and actual["start"] <= span["start"] and actual["end"] >= span["end"]
        for actual in delivered)]
    return {"scope": scope.get("basis", "retrieved_pool"),
            "complete": bool(scope.get("complete")) and not missing,
            "missing_source_ranges": len(missing), "required_source_ranges": len(required),
            "scope_available": bool(scope.get("complete")),
            "meaning": "source delivery coverage, not correctness or external-world completeness"}


def read_question_pack(
    question: str, date: str, materials: list[dict[str, Any]], *, snapshot_id: str,
    open_materials: Callable[[list[dict[str, Any]], bool], list[dict[str, Any]]],
    messages_for: Callable[[list[dict[str, Any]]], list[dict[str, str]]],
    fits: Callable[[list[dict[str, str]]], bool],
    call: Callable[[str, list[dict[str, str]], dict[str, Any] | None], str],
    save: Callable[[dict[str, Any]], None], state: dict[str, Any], max_calls: int,
    source_scope: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Select a budgeted pack; reopen more only for a stated evidence gap.

    Every decision uses the existing main Reader and one cumulative call limit.
    Candidate paging carries navigation only; it never forces all bodies into the Reader.
    State and HTTP caching are owned by the normal caller, not a second persistence layer.
    """
    refs = [material_ref(snapshot_id, i) for i in range(len(materials))]
    state.setdefault("steps", 0)
    state.setdefault("resident_refs", [])
    state.setdefault("opened_indices", [])
    state.setdefault("context_indices", [])
    state.setdefault("excluded_indices", [])
    state.setdefault("task", "lookup")
    state.setdefault("gap", None)
    state.setdefault("candidate_page", 0)
    state["retrieval_snapshot"] = snapshot_id
    state["evidence_policy"] = "question_pack_v1"

    def opened(indices: list[int]) -> list[dict[str, Any]]:
        return [open_materials([materials[i]], i in state["context_indices"])[0] for i in indices]

    def evidence_messages(indices: list[int]) -> list[dict[str, str]]:
        projected = project_packs(opened(indices), indices)
        messages = messages_for(projected)
        messages[0]["content"] += "\n" + SOURCE_REUSE_INSTRUCTIONS
        payload = json.loads(messages[1]["content"])
        payload["source_coverage"] = pack_coverage(materials, opened(indices), scope=source_scope)
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return messages

    visible = open_materials(materials, False)
    directory = [pack_candidate(item, i) for i, item in enumerate(visible)]
    schema: dict[str, Any] = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "answer": {"type": ["string", "null"]},
            "item_indices": {"type": "array",
                             "items": {"type": "integer", "enum": list(range(len(materials)))}}
                            if materials else {"type": "array", "maxItems": 0},
            "expand_context": {"type": "array",
                               "items": {"type": "integer", "enum": list(range(len(materials)))}}
                              if materials else {"type": "array", "maxItems": 0},
            "gap": {"type": ["string", "null"]},
            "task": {"enum": ["lookup", "range"]},
            "candidate_page": {"type": "integer", "minimum": 0},
        }, "required": ["answer", "item_indices", "expand_context", "gap", "task",
                         "candidate_page"],
    }

    def response_schema(indices: list[int]) -> dict[str, Any]:
        selected_schema = copy.deepcopy(schema)
        if not indices:
            selected_schema["properties"]["answer"] = {"type": "null"}
        return selected_schema

    def packet(indices: list[int], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages = evidence_messages(indices)
        payload = json.loads(messages[1]["content"])
        payload.update(candidates=candidates, candidate_page=state["candidate_page"],
                       admitted_indices=indices, excluded_indices=state["excluded_indices"],
                       evidence_gap=state["gap"], task=state["task"],
                       unopened_candidates=len(materials) - len(state["opened_indices"]),
                       coverage="retrieved_pool_only_not_full_history",
                       range_coverage=pack_coverage(materials, opened(indices), scope=source_scope),
                       response_schema=response_schema(indices))
        messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        messages[0]["content"] += (
            "\nReturn JSON following response_schema. Candidate excerpts are only navigation; "
            "answer solely from supplied evidence bodies. If you can answer the original question, "
            "put the complete answer in answer. Otherwise set answer=null and item_indices to the "
            "necessary evidence in priority order (the next set replaces the current set). "
            "Only request another read for a specific gap in gap: missing subject, condition, "
            "negation, date, historical evidence or a needed live observation. expand_context "
            "reopens the captured parent exchange/session for those indices; it never adds later "
            "sources. For ordinary lookup, stop when evidence suffices; do not scan all pending "
            "candidates. For counting/enumeration use task=range, cover the requested range and "
            "state any incomplete coverage; retrieved candidates alone do not establish a full "
            "history. Candidate pages only locate evidence. Internal reading plans never replace "
            "the original question or its constraints. If the evidence cannot resolve the gap, "
            "answer the supported part and state the missing information."
        )
        return messages

    answer: str | None
    # A genuinely small complete pool keeps a one-call ordinary answer path.
    all_indices = list(range(len(materials)))
    lookup_indices = [i for i, item in enumerate(materials) if not item.get("scope_only")]
    # Only a fully represented scope can bypass task selection: a fitting top-k subset
    # does not establish that a count/enumeration query has seen the complete range.
    direct_scope = pack_coverage(materials, opened(lookup_indices), scope=source_scope)
    if not state["steps"] and direct_scope["complete"] and fits(evidence_messages(lookup_indices)):
        state.update(resident_refs=[refs[i] for i in lookup_indices],
                     opened_indices=lookup_indices, active_stage="answer",
                     range_coverage=direct_scope)
        save(state)
        answer = call("answer", evidence_messages(lookup_indices), None)
        state.update(answer=answer, complete=True,
                     delivery_plan={"body_delivered": bool(lookup_indices)},
                     steps=1, coverage_complete=direct_scope["complete"])
        save(state)
        return answer, opened(lookup_indices)

    if state.get("complete") and "answer" in state:
        return state["answer"], opened(state["opened_indices"])

    # Partition only navigation, using the full empty-evidence wrapper's actual cost.
    pages = plan_delivery([{"index": i} for i in all_indices], lambda rows: fits(packet(
        [], [directory[row["index"]] for row in rows])))
    catalogs = [[directory[row["index"]] for row in page] for page in pages["pages"]] or [[]]
    state["candidate_page_count"] = len(catalogs)
    while state["steps"] < max_calls:
        indices = [ref["item_index"] for ref in state["resident_refs"]]
        final_slot = state["steps"] == max_calls - 1 or state.get("final_only", False)
        if final_slot:
            messages = evidence_messages(indices)
            stop = ("No further evidence was requested." if state.get("final_only") else
                    "The total read budget is exhausted.")
            messages[0]["content"] += (
                "\n" + stop + " Answer the supported part of the original "
                "question and explicitly state the remaining gap; do not claim complete range "
                "coverage or invent unavailable information."
            )
            payload = json.loads(messages[1]["content"])
            payload.update(evidence_gap=state["gap"], excluded_indices=state["excluded_indices"],
                           coverage="retrieved_pool_only_not_full_history",
                           range_coverage=pack_coverage(
                               materials, opened(indices), scope=source_scope))
            messages[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            state["active_stage"] = "answer"
            save(state)
            answer = call("answer", messages, None)
        else:
            page = min(state["candidate_page"], len(catalogs) - 1)
            candidates = [candidate for candidate in catalogs[page]
                          if state["task"] == "range" or not materials[
                              candidate["item_index"]].get("scope_only")]
            # Exclude navigation from an evidence-bearing Reader packet when it cannot fit;
            # a further read can revisit that page with a smaller pack.
            messages = packet(indices, candidates)
            if not fits(messages):
                messages = packet(indices, [])
            stage = f"view/pack-{state['steps']}"
            state["active_stage"] = stage
            save(state)
            active_schema = response_schema(indices)
            response = parse_object(
                call(stage, messages, active_schema), reject_duplicate_keys=True)
            Draft202012Validator(active_schema).validate(response)
            answer = response["answer"]
            state["task"] = response["task"]
            coverage = pack_coverage(materials, opened(indices), scope=source_scope)
            state["range_coverage"] = coverage
            if state["task"] == "range" and not coverage["complete"]:
                # A catalog nomination or lookup stop cannot certify a whole range.
                answer = None
                response["gap"] = "The declared source range has not been fully delivered."
                response["item_indices"] = all_indices
                response["expand_context"] = []
            if answer is None:
                previous = (indices, state["context_indices"], page)
                state.update(gap=response["gap"], candidate_page=response["candidate_page"],
                             context_indices=list(dict.fromkeys(response["expand_context"])))
                wanted = response["item_indices"]
                admission = admit_pack_indices(wanted, lambda chosen: fits(packet(chosen, [])))
                accepted = admission["admitted_indices"]
                state["excluded_indices"] = admission["excluded_indices"]
                if state["task"] == "range" and not pack_coverage(
                        materials, opened(accepted), scope=source_scope)["complete"]:
                    state["final_only"] = True
                state["resident_refs"] = [refs[i] for i in accepted]
                state["opened_indices"] = list(dict.fromkeys([*state["opened_indices"], *accepted]))
                if ((indices and not response["gap"]) or previous == (
                        accepted, state["context_indices"], state["candidate_page"])):
                    # No new evidence or explicit gap: use the remaining final-answer slot.
                    state["final_only"] = True
        state["steps"] += 1
        if answer is not None:
            coverage = pack_coverage(materials, opened(indices), scope=source_scope)
            state.update(answer=answer, complete=True,
                         delivery_plan={"body_delivered": bool(indices)},
                         range_coverage=coverage, coverage_complete=coverage["complete"])
            save(state)
            return answer, opened(state["opened_indices"])
        save(state)
    raise ValueError("READ_PACK_CALL_LIMIT_INVALID")


def answer_only_context(
    question: str, material: dict[str, Any], effects: dict[str, Any],
    tool_results: list[dict[str, Any]], *, pending: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Final prose over actual evidence/effects, without a second operation conversation."""
    def facts(packet: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(packet)
        for key in ("candidates", "instructions", "next_cursor", "candidate_page",
                    "candidate_page_count", "memory_view", "read_progress"):
            result.pop(key, None)
        if "items" in result:
            result["items"] = [item for item in result["items"]
                               if not item.get("type", "").endswith("_candidate")]
        return result

    return [
        {"role": "system", "content": (
            "Answer the original user request directly in the user's language. No tools or "
            "new actions are available in this answer-only step. Use the delivered evidence "
            "bodies and confirmed results below; candidate descriptions are not facts. "
            "Preserve subjects, negation, conditions, source roles and unknown times. Keep "
            "current interpretations and actually read historical versions distinct. "
            "A confirmed memory commit is not proof of an external business effect or complete "
            "semantic accuracy. State any failed, unknown or unfinished requested work plainly. "
            "Unavailable evidence does not mean it was never saved. Do not reproduce internal "
            "identifiers or planning details unless the user asked for them. Return the final "
            "answer, not a plan to read or act later."
        )},
        {"role": "user", "content": json.dumps({
            "question": question, "evidence": facts(material), "confirmed_results": effects,
            "observed_tool_results": [
                {"name": row["name"], "result": facts(row["result"])
                 if row.get("memory_read") and isinstance(row["result"], dict)
                 else row["result"]} for row in tool_results
            ], "pending_work": pending or [],
        }, ensure_ascii=False, separators=(",", ":"))},
    ]
