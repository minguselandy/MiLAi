"""A partial Writer view over a complete immutable binding map.

Select existing graph context independently of preserve labels. This does not
infer a missing relation, repair an old memory, or replace a record with a slice.
"""
from __future__ import annotations

import copy
from typing import Any


def local_writer_view(packet: dict[str, Any], mapping: dict[str, Any],
                      regions: dict[str, Any], prior_context: list[dict[str, Any]],
                      ) -> dict[str, Any]:
    visible = {uid for region in regions.values() for uid in (
        *region["context_units"], *region.get("support_update_targets", []))}
    supports = []
    for item in packet["historical_support"]:
        endpoints = {item[key] for key in ("unit", "source", "target", "support_target")
                     if key in item}
        if endpoints and endpoints <= visible:
            supports.append(copy.deepcopy(item))
    support_ids = {item["id"] for item in supports}
    needed_ranges = [part for item in supports for part in item["ranges"]]
    bodies = {}
    for record in packet["records"]:
        for clause in record["clauses"]:
            bodies[clause["id"]] = clause
            for condition in clause.get("conditions", []):
                if "reuse" not in condition:
                    bodies[condition["id"]] = condition
        for condition in record.get("unresolved_conditions", []):
            bodies[condition["id"]] = condition
    assertion_sources = set()
    for alias in visible:
        assertion = bodies[alias].get("assertion", {})
        if assertion.get("source") is not None:
            assertion_sources.add(assertion["source"])
        needed_ranges.extend(part for refs in assertion.get("evidence_links", {}).values()
                             for part in refs)

    def needed_evidence(item: dict[str, Any]) -> bool:
        if item.get("delivery_kind", "current") == "current":
            return True
        return any(part["source"] == item["source"]
                   and part["range"][0] < item["range"][1]
                   and item["range"][0] < part["range"][1] for part in needed_ranges)

    evidence = [copy.deepcopy(e) for e in packet["evidence"] if needed_evidence(e)]
    evidence_ids = {item["id"] for item in evidence}
    source_ids = {item["source"] for item in evidence} | {
        part["source"] for part in needed_ranges} | assertion_sources
    records = []
    for record in packet["records"]:
        clauses, rendered_conditions = [], set()
        unit_ids = {uid for uid, unit in mapping["units"].items() if unit["record"] == record["id"]}
        for clause in record["clauses"]:
            if clause["id"] not in visible:
                continue
            selected = copy.deepcopy(clause)
            selected["conditions"] = []
            for condition in clause.get("conditions", []):
                alias = condition["reuse"] if "reuse" in condition else condition["id"]
                if alias not in visible:
                    continue
                # The first declaration can have belonged to an omitted sibling.
                # Reissue its actual body here and keep this edge's own binding.
                body = ({"reuse": alias} if alias in rendered_conditions else
                        {k: copy.deepcopy(v) for k, v in bodies[alias].items() if k != "binding"})
                selected["conditions"].append({
                    **body, "binding": copy.deepcopy(condition["binding"])})
                rendered_conditions.add(alias)
            if "overrides" in selected:
                selected["overrides"] = [edge for edge in selected["overrides"]
                                           if edge["target"] in visible]
            clauses.append(selected)
        standalone = [{k: copy.deepcopy(v) for k, v in bodies[uid].items() if k != "binding"}
            for uid in mapping["units"] if uid in unit_ids & visible - rendered_conditions
            and mapping["units"][uid].get("role") == "condition"]
        projected = {key: copy.deepcopy(record[key])
                     for key in ("id", "representation", "scope", "version_time") if key in record}
        projected.update(view="partial_units", clauses=clauses,
                         omitted_units=len(unit_ids - visible))
        if standalone:
            projected["unresolved_conditions"] = standalone
        if "support_groups" in record:
            projected["support_groups"] = [copy.deepcopy(group)
                for group in record["support_groups"] if group["target_unit"] in visible]
        records.append(projected)
    projected_packet = {**copy.deepcopy(packet), "records": records, "evidence": evidence,
        "historical_support": supports,
        "source_table": [copy.deepcopy(s) for s in packet["source_table"] if s["id"] in source_ids],
        "writer_input": "dependency_region_v1"}
    if "time_choices" in projected_packet:
        projected_packet["time_choices"] = [item for item in projected_packet["time_choices"]
                                             if item["evidence"] in evidence_ids]
    # This is ONLY for constructing the visible action schema. Commit/decoding
    # must still use the original mapping with complete stored record snapshots.
    schema_mapping = {**mapping,
        "units": {uid: value for uid, value in mapping["units"].items() if uid in visible},
        "support": {sid: value for sid, value in mapping["support"].items() if sid in support_ids},
        "evidence": {eid: value for eid, value in mapping["evidence"].items()
                     if eid in evidence_ids}}
    if "time_choices" in mapping:
        schema_mapping["time_choices"] = projected_packet.get("time_choices", [])
    source_refs = {mapping["evidence"][eid]["source_ref"] for eid in evidence_ids}
    context = [copy.deepcopy(row) for row in prior_context if row["source_ref"] in source_refs]
    return {"packet": projected_packet, "schema_mapping": schema_mapping, "prior_context": context,
            "selection": {"visible_units": sorted(visible), "evidence": sorted(evidence_ids),
                          "support": sorted(support_ids),
                          "omitted_prior_context": len(prior_context) - len(context)}}
