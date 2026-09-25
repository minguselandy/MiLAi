"""Task-local, exact-reference model projection of complete internal materials."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from milai_lab.methods.contextual_user_memory import ContextualMemory


VIEW_PROTOCOL = "contextual-material-view-v9"


def source_speaker_handle(ref: str) -> str:
    """Name an exact local source consistently, without inferring person identity."""
    return "p" + ref.rsplit("/source:", 1)[1]


def source_subject_handle(memory: ContextualMemory, ref: str) -> str:
    canonical = memory.source_subject(ref)
    if canonical == "current_user":
        return "u0"
    if canonical.startswith("actor:"):
        return "a" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return source_speaker_handle(ref)


@dataclass(frozen=True)
class MaterialBinding:
    exact_ref: str
    kind: str
    spans: tuple[tuple[int, int], ...] = ()
    content_sha256: str = ""


def serialized_material_bytes(value: Any) -> int:
    """The entire JSON material area, with references and limits included."""
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())


def _public_error(result: dict[str, Any]) -> str:
    """Expose core diagnostic codes without leaking exact refs in exception text."""
    error = result.get("error")
    if isinstance(error, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", error):
        return error
    return "MEMORY_OPERATION_ERROR"


def _parts(item: dict[str, Any]) -> list[tuple[int, int, str, str]]:
    key = "content" if item.get("kind") == "source" else "text"
    pages = item.get("excerpts")
    if isinstance(pages, list):
        candidates = pages
    elif isinstance(item.get(key), str):
        candidates = [item]
    else:
        return []
    parts = []
    for candidate in candidates:
        body = candidate.get("content") if pages is not None else candidate.get(key)
        page = candidate.get("page")
        if not isinstance(body, str):
            continue
        if page is None:
            page = {"start": 0, "end": len(body),
                    "content_sha256": hashlib.sha256(body.encode()).hexdigest()}
        if not isinstance(page, dict):
            continue
        start, end = page.get("start"), page.get("end")
        digest = page.get("content_sha256")
        if (type(start) is int and type(end) is int and isinstance(digest, str)
                and end >= start and len(body) == end - start):
            parts.append((start, end, body, digest))
    return parts


def _remaining(start: int, end: int, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    cursor = start
    for lower, upper in sorted(covered):
        if upper <= cursor or lower >= end:
            continue
        if lower > cursor:
            result.append((cursor, lower))
        cursor = max(cursor, upper)
    if cursor < end:
        result.append((cursor, end))
    return result


@dataclass
class MaterialView:
    """One Host task. Allocated aliases never change meaning or get reused."""

    generation: str
    memory: ContextualMemory | None = None
    _next: int = 0
    _bindings: dict[str, MaterialBinding] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._bindings.setdefault("unknown", MaterialBinding("unresolved", "subject"))

    def subject_catalogue(self) -> list[dict[str, str]]:
        """Only task-local, actually delivered speaker anchors can be proposed."""
        catalogue = ([{"ref": "u0", "kind": "current_user"}]
                     if "u0" in self._bindings else [])
        catalogue.append({"ref": "unknown", "kind": "unresolved"})
        memory = self.memory
        if memory is None:
            return catalogue
        visible_sources = {
            binding.exact_ref: short
            for short, binding in self._bindings.items()
            if binding.kind == "source" and binding.spans
        }
        for short, binding in self._bindings.items():
            if binding.kind != "subject" or binding.exact_ref in {"current_user", "unresolved"}:
                continue
            refs = [ref for ref in visible_sources if ref in memory.sources
                    and memory.source_subject(ref) == binding.exact_ref]
            if refs:
                catalogue.append({
                    "ref": short, "kind": "actor" if binding.exact_ref.startswith("actor:")
                    else "source_speaker", "source_ref": visible_sources[refs[0]],
                    "source_role": memory.sources[refs[0]].role,
                })
        return catalogue

    def binding(self, short_ref: str) -> MaterialBinding:
        try:
            return self._bindings[short_ref]
        except KeyError as exc:
            raise ValueError("MATERIAL_REF_NOT_DELIVERED") from exc

    def resolve_ref(self, short_ref: str) -> str:
        return self.binding(short_ref).exact_ref

    def revoke(self, short_refs: set[str]) -> None:
        """Drop aliases whose containing receipts left the Host transcript."""
        for short in short_refs:
            self._bindings.pop(short, None)
        visible_sources = {
            binding.exact_ref for binding in self._bindings.values()
            if binding.kind == "source" and binding.spans
        }
        if self.memory is not None:
            subjects = {self.memory.source_subject(ref) for ref in visible_sources
                        if ref in self.memory.sources}
            for short, binding in list(self._bindings.items()):
                if (binding.kind == "subject"
                        and binding.exact_ref not in {"current_user", "unresolved"} | subjects):
                    self._bindings.pop(short)

    def visible_bindings(self, projected: dict[str, Any]) -> dict[str, MaterialBinding]:
        """Refs actually present in one projected receipt, including bodyless links."""
        aliases: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for key, part in value.items():
                    if (key in {"ref", "current_ref", "expand_ref",
                               "correction_expand_ref", "speaker_ref", "about_ref"}
                            and isinstance(part, str)):
                        aliases.add(part)
                    elif key not in {"content", "text", "context", "scope_note"}:
                        collect(part)
            elif isinstance(value, list):
                for part in value:
                    if isinstance(part, str) and part in self._bindings:
                        aliases.add(part)
                    else:
                        collect(part)

        collect(projected)
        return {short: self._bindings[short] for short in aliases if short in self._bindings}

    def preview(
        self, result: dict[str, Any], *, max_bytes: int = 16000,
        linked: bool = False,
    ) -> dict[str, Any]:
        """Estimate selection cost without publishing model-visible aliases."""
        temporary = MaterialView(self.generation, self.memory, self._next,
                                 dict(self._bindings))
        return temporary.project(result, max_bytes=max_bytes, linked=linked)

    def project_write(
        self, result: dict[str, Any], *, max_bytes: int = 16000,
    ) -> dict[str, Any]:
        """Expose completed write identities without the executor's internal plan."""
        output: dict[str, Any] = {"view": VIEW_PROTOCOL}
        for key in ("status", "operation_id", "decision", "completion"):
            value = result.get(key)
            if isinstance(value, str):
                output[key] = value
        if result.get("status") == "ERROR":
            output["error"] = _public_error(result)
        known: dict[str, str] = {}
        record = result.get("record")
        if isinstance(record, dict) and record.get("kind") in {"source", "interpretation"}:
            projected_record = dict(record)
            exact_ref = record.get("ref")
            current_ref = record.get("current_ref")
            projected_record["status"] = (
                "CURRENT" if exact_ref == current_ref else "SUPERSEDED"
            ) if isinstance(exact_ref, str) and isinstance(current_ref, str) else "UNKNOWN"
            material = self.project(projected_record, max_bytes=max_bytes)
            output["record"] = {"status": record.get("status", "SAVED"),
                                "material": material}
            for short, bound in self.visible_bindings(material).items():
                if bound.spans:
                    known.setdefault(bound.exact_ref, short)

        def link(ref: str, kind: str | None = None) -> str:
            if ref in known:
                return known[ref]
            short = f"m{self._next}"
            self._next += 1
            bound = MaterialBinding(ref, kind or (
                "source" if "/source:" in ref else "interpretation"
            ))
            self._bindings[short] = bound
            known[ref] = short
            return short

        source = result.get("source")
        if isinstance(source, dict):
            output["source"] = {"status": source.get("status", "UNKNOWN")}
            if isinstance(source.get("ref"), str):
                output["source"]["ref"] = link(source["ref"], "source")
        if isinstance(record, dict) and isinstance(record.get("ref"), str):
            output.setdefault("record", {"status": record.get("status", "UNKNOWN")})
            output["record"]["ref"] = link(record["ref"], "interpretation")
        changeset = result.get("changeset")
        if isinstance(changeset, dict):
            groups = []
            for group in changeset.get("groups", []):
                summary: dict[str, Any] = {"status": group.get("status", "UNKNOWN")}
                operations = []
                for operation in group.get("operations", []):
                    step = {key: operation[key] for key in ("op", "status", "group_id")
                            if key in operation}
                    if isinstance(operation.get("ref"), str):
                        step["ref"] = link(operation["ref"])
                    operations.append(step)
                summary["operations"] = operations
                groups.append(summary)
            output["changeset"] = {
                "groups": groups,
                "aliases": {alias: link(ref)
                            for alias, ref in changeset.get("aliases", {}).items()},
                "pending_refs": [link(ref) for ref in changeset.get("pending_refs", [])],
            }
        return output

    def _historical_limits(self, ref: str) -> dict[str, Any]:
        memory = self.memory
        if memory is None or ref in memory.sources:
            return {}
        handle = memory._handle(ref)
        details = (memory.history[ref] if ref in memory.history
                   else asdict(memory.details[handle]))
        return {key: details[key] for key in (
            "valid_from", "valid_until", "uncertain_start", "uncertain_end",
        ) if details.get(key)}

    def _bind(
        self, exact_ref: str, kind: str, spans: tuple[tuple[int, int], ...] = (),
        digest: str = "", *, provisional: dict[str, MaterialBinding],
    ) -> str:
        wanted = MaterialBinding(exact_ref, kind, spans, digest)
        for short, bound in provisional.items():
            if bound == wanted:
                return short
        short = f"m{self._next + len(provisional)}"
        provisional[short] = wanted
        return short

    def project(
        self, result: dict[str, Any], *, max_bytes: int = 16000,
        linked: bool = False, include_optional: bool = False,
        include_sources: bool = False,
    ) -> dict[str, Any]:
        """Project one read/search response, including all serialized material bytes."""
        if result.get("status") == "ERROR":
            return {"view": VIEW_PROTOCOL, "status": "ERROR",
                    "error": _public_error(result)}
        if max_bytes <= 0:
            return {"view": VIEW_PROTOCOL, "status": "INSUFFICIENT_MATERIAL_BUDGET"}
        roots = (
            [*result.get("materials", []), *result.get("expanded_materials", [])]
            if isinstance(result.get("materials"), list) else [result]
        )
        provisional: dict[str, MaterialBinding] = {}
        covered: dict[tuple[str, str], list[tuple[int, int]]] = {}
        rows: list[dict[str, Any]] = []
        unexpanded: list[str] = []
        first_alias: dict[str, str] = {}
        first_row: dict[str, int] = {}
        relations: list[tuple[int, list[dict[str, Any]]]] = []
        required_pairs: list[tuple[int, int]] = []
        provisional_speakers: dict[str, str] = {}
        about_sources: dict[int, str] = {}

        def speaker(ref: str) -> str:
            assert self.memory is not None
            canonical = self.memory.source_subject(ref)
            if canonical == "current_user":
                return "u0"
            for short, binding in self._bindings.items():
                if binding.kind == "subject" and binding.exact_ref == canonical:
                    return short
            provisional_speakers[ref] = source_subject_handle(self.memory, ref)
            return provisional_speakers[ref]

        def kind_for(ref: str) -> str:
            return "source" if "/source:" in ref else "interpretation"

        def link(ref: str) -> str:
            if ref in first_alias:
                return first_alias[ref]
            return self._bind(ref, kind_for(ref), provisional=provisional)

        def project_reason_refs(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: link(part) if key in {"basis_ref", "source_ref"}
                    and isinstance(part, str) else project_reason_refs(part)
                    for key, part in value.items()
                }
            if isinstance(value, list):
                return [project_reason_refs(part) for part in value]
            return value

        def add(item: dict[str, Any]) -> int:
            ref = item["ref"]
            kind = item["kind"]
            original = _parts(item)
            fresh: list[tuple[int, int, str]] = []
            digest = original[0][3] if original else ""
            for start, end, body, part_digest in original:
                coverage_key = (ref, part_digest)
                for low, high in _remaining(start, end, covered.get(coverage_key, [])):
                    fresh.append((low, high, body[low - start:high - start]))
                covered.setdefault(coverage_key, []).append((start, end))
            if not fresh and ref in first_row:
                return first_row[ref]
            spans = tuple((start, end) for start, end, _ in fresh)
            alias = self._bind(ref, kind, spans, digest if spans else "",
                               provisional=provisional)
            first_alias.setdefault(ref, alias)
            row: dict[str, Any] = {"ref": alias, "kind": kind,
                                   "status": item.get("status", "UNKNOWN"),
                                   "body_delivery": "partial"}
            page = item.get("page")
            if isinstance(page, dict) and type(page.get("total_chars")) is int:
                row["total_chars"] = page["total_chars"]
            for key in (
                "role", "date", "session_id", "source_sequence", "author",
                "subject", "context", "certainty", "persistence", "retired",
                "applicability", "applicability_reasons", "conditions", "valid_from",
                "valid_until", "uncertain_start", "uncertain_end", "support_status",
                "opposition_status", "disputed", "event_date_match", "pending_review",
                "task_override", "scope_status", "scope_reasons", "structured_scope",
            ):
                value = item.get(key)
                if value not in (None, "", [], {}):
                    row[key] = (project_reason_refs(value) if key in {
                        "applicability_reasons", "scope_reasons",
                    } else value)
            if kind == "source" and self.memory is not None:
                row["retention"] = ("durable" if ref in self.memory.retained else
                                    "session" if ref in self.memory.task_sources else
                                    "available_input_only")
                if ref in self.memory.source_sequence:
                    row["source_sequence"] = self.memory.source_sequence[ref]
                if fresh:
                    row["speaker_ref"] = speaker(ref)
            if kind == "interpretation":
                about = item.get("about")
                if isinstance(about, dict):
                    about_kind = about.get("kind")
                    if about_kind == "current_user":
                        row["about"] = {"kind": "current_user", "label": "current user"}
                        row["about_ref"] = "u0"
                    elif about_kind == "unresolved":
                        row["about"] = {"kind": "unresolved", "label": "unspecified subject"}
                        row["about_ref"] = "unknown"
                    elif about_kind == "actor" and self.memory is not None:
                        row["about"] = {"kind": "actor"}
                        anchor = next((source for source in item.get("source_refs", [])
                                       if source in self.memory.sources and
                                       self.memory.sources[source].actor_ref ==
                                       about.get("actor_ref")), None)
                        if anchor is not None:
                            about_sources[len(rows)] = anchor
                    elif about_kind == "source_speaker":
                        source_ref = about.get("source_ref")
                        if isinstance(source_ref, str):
                            row["about"] = {
                                "kind": "source_speaker",
                                "source_ref": link(source_ref),
                                "source_role": about.get("source_role", "UNKNOWN"),
                            }
                            about_sources[len(rows)] = source_ref
            row.update(self._historical_limits(ref))
            if kind == "source":
                row["provenance"] = "recorded_source_not_verified_truth"
            elif not any(row.get(key) for key in (
                "conditions", "valid_from", "valid_until", "uncertain_start",
                "uncertain_end",
            )):
                row.setdefault("structured_scope", "UNDECLARED")
                row["scope_note"] = "No structured scope check; context still limits use"
            current = item.get("current_ref")
            if isinstance(current, str) and current != ref:
                row["current_ref"] = link(current)
            if fresh:
                body_key = "content" if kind == "source" else "text"
                if len(fresh) == 1:
                    row[body_key] = fresh[0][2]
                    row["range"] = [fresh[0][0], fresh[0][1]]
                else:
                    row["excerpts"] = [
                        {"range": [start, end], body_key: body}
                        for start, end, body in fresh
                    ]
            else:
                row["expand_ref"] = alias
            if any(not part.get("complete", False) for part in (
                [item.get("page", {})] if "page" in item else
                [excerpt.get("page", {}) for excerpt in item.get("excerpts", [])]
            )):
                row["expand_ref"] = alias
            if item.get("requires_expansion") or item.get("unexpanded_ranges"):
                row["expand_ref"] = alias
            source_refs = item.get("source_refs", [])
            if isinstance(source_refs, list) and source_refs:
                row["source_refs"] = [link(source) for source in source_refs]
                if self.memory is not None:
                    row["source_roles"] = {
                        link(source): self.memory.sources[source].role
                        for source in source_refs if source in self.memory.sources
                    }
            dependencies = item.get("dependencies", [])
            if kind == "interpretation" and isinstance(dependencies, list) and dependencies:
                row["dependency_refs"] = [link(ref) for ref in dependencies]
            if kind == "interpretation" and (source_refs or dependencies):
                row["basis_relation_use"] = "existing_lineage_not_body_read"
            change = item.get("basis_change")
            if (kind == "interpretation" and isinstance(change, dict)
                    and change.get("mode") == "delta"):
                row["basis_change"] = {
                    "mode": "delta",
                    "target_ref": link(change["target_ref"]),
                    "sources": {key: [link(ref) for ref in change["sources"][key]]
                                for key in ("inherited", "added", "removed")},
                    "dependencies": {key: [link(ref) for ref in change["dependencies"][key]]
                                     for key in ("inherited", "added", "removed")},
                    "reviewed_source_ranges": [
                        {"ref": link(ref), "spans": spans}
                        for ref, spans in change["reviewed_source_ranges"].items()
                    ],
                    "meaning": "version_lineage_not_independent_support",
                }
            dependency_status = item.get("dependency_status", [])
            if isinstance(dependency_status, list) and dependency_status:
                row["dependency_status"] = [
                    {"ref": link(dependency["observed_ref"]),
                     "current_ref": link(dependency["current_ref"])
                     if dependency.get("current_ref") != "UNAVAILABLE" else "UNAVAILABLE",
                     "status": dependency["status"]}
                    for dependency in dependency_status
                    if isinstance(dependency, dict) and "observed_ref" in dependency
                ]
            rows.append(row)
            first_row.setdefault(ref, len(rows) - 1)
            return len(rows) - 1

        for item in roots:
            if not isinstance(item, dict):
                continue
            if item.get("kind") not in {"source", "interpretation"}:
                if isinstance(item.get("ref"), str):
                    unexpanded.append(link(item["ref"]))
                continue
            index = add(item)
            links: list[dict[str, Any]] = []
            for associated in item.get("associated_materials", []):
                if not isinstance(associated, dict) or "ref" not in associated:
                    continue
                relation = associated.get("relation", "associated")
                required = include_optional or relation in {
                    "source_replacement", "current_interpretation", "support_replacement",
                    "revised_interpretation", "direct_interpretation",
                } or (
                    linked and relation == "session_neighbor_correction"
                )
                if required:
                    correction_index = add(associated)
                    required_pairs.append((index, correction_index))
                links.append({"relation": relation, "ref": link(associated["ref"]),
                              "expanded": required})
            for source in item.get("sources", []):
                if not isinstance(source, dict) or "ref" not in source:
                    continue
                expand_source = include_sources or include_optional
                if expand_source and source.get("kind") in {"source", "interpretation"}:
                    add(source)
                links.append({"relation": "source_provenance", "ref": link(source["ref"]),
                              "expanded": expand_source})
            for ref in item.get("unexpanded_associated_refs", []):
                if isinstance(ref, str):
                    links.append({"relation": "associated", "ref": link(ref),
                                  "expanded": False})
            required_refs = item.get("required_associated_refs", [])
            if required_refs:
                rows[index]["required_correction_refs"] = [
                    link(ref) for ref in required_refs
                ]
                rows[index]["correction_status"] = "REQUIRES_EXPANSION"
            relations.append((index, links))
        for index, links in relations:
            if links:
                existing = rows[index].get("related", [])
                rows[index]["related"] = [json.loads(link) for link in dict.fromkeys(
                    json.dumps(link, sort_keys=True) for link in [*existing, *links]
                )]
        for index, source_ref in about_sources.items():
            rows[index]["identity_anchor"] = link(source_ref)
            rows[index]["identity_anchor_use"] = (
                "retain this source relation when keeping the same subject; "
                "it is lineage, not independent proof of the current value"
            )
            if self.memory is not None and self.memory.source_subject(source_ref) == "current_user":
                rows[index]["about_ref"] = "u0"
                continue
            canonical = (self.memory.source_subject(source_ref) if self.memory is not None
                         else f"speaker:{source_ref}")
            existing_speaker = next(
                (short for short, binding in self._bindings.items()
                 if binding.kind == "subject" and binding.exact_ref == canonical),
                None,
            )
            if existing_speaker is not None or source_ref in provisional_speakers:
                rows[index]["about_ref"] = existing_speaker or provisional_speakers[source_ref]
        # A link may have been allocated before the target body was encountered.
        # Prefer its delivered range alias when that target is in this response.
        link_aliases = {short: first_alias[bound.exact_ref]
                        for short, bound in provisional.items()
                        if not bound.spans and bound.exact_ref in first_alias}
        def resolve_links(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: {link_aliases.get(ref, ref): role for ref, role in part.items()}
                    if key == "source_roles" else resolve_links(part)
                    for key, part in value.items()
                }
            if isinstance(value, list):
                return [resolve_links(part) for part in value]
            if isinstance(value, str):
                return link_aliases.get(value, value)
            return value
        rows = resolve_links(rows)
        body_aliases = {row["ref"] for row in rows if row.get("content")
                        or row.get("text") or row.get("excerpts")}
        for row in rows:
            current_ref = row.get("current_ref")
            if row.get("status") == "SUPERSEDED" and current_ref not in body_aliases:
                row["correction_status"] = "CURRENT_VERSION_REQUIRES_EXPANSION"
                row["correction_expand_ref"] = current_ref
        projected = {"view": VIEW_PROTOCOL, "materials": rows}
        if rows:
            projected["status_meaning"] = (
                "CURRENT means latest stored version, not current world state"
            )
        for row in rows:
            front = {key: row[key] for key in ("ref", "kind", "about", "about_ref",
                     "speaker_ref", "role", "subject", "content", "text", "excerpts", "context",
                     "certainty", "status") if key in row}
            tail = {key: value for key, value in row.items() if key not in front}
            row.clear()
            row.update(front)
            row.update(tail)
        if unexpanded:
            projected["unexpanded_refs"] = list(dict.fromkeys(unexpanded))
        if not rows:
            projected["status"] = "NO_MATERIALS"

        # The material budget applies to the complete serialized view. Shrink exact
        # ranges in place; a correction row stays beside the old row it qualifies.
        while serialized_material_bytes(projected) > max_bytes:
            choices = [
                (len(row.get(key, "")), index, key)
                for index, row in enumerate(rows) for key in ("content", "text")
                if isinstance(row.get(key), str) and row[key]
            ]
            if not choices:
                break
            _, index, key = max(choices)
            row = rows[index]
            old = row[key]
            keep = len(old) // 2
            row[key] = old[:keep]
            if isinstance(row.get("range"), list):
                row["range"][1] = row["range"][0] + keep
            row["expand_ref"] = row["ref"]
            row["delivery"] = "PARTIAL_RANGE; expand before relying on omitted text"
        for old_index, correction_index in required_pairs:
            old, correction = rows[old_index], rows[correction_index]
            if (not (correction.get("content") or correction.get("text")
                     or correction.get("excerpts")) or correction.get("expand_ref")):
                old.pop("content", None)
                old.pop("text", None)
                old.pop("excerpts", None)
                old.pop("range", None)
                old["expand_ref"] = old["ref"]
                old["correction_status"] = "REQUIRES_EXPANSION"
        for row in rows:
            delivered_ranges = (
                [row["range"]] if isinstance(row.get("range"), list)
                and (row.get("content") or row.get("text")) else
                [part["range"] for part in row.get("excerpts", [])]
            )
            if not delivered_ranges:
                row["body_delivery"] = "link"
            elif (type(row.get("total_chars")) is int
                  and delivered_ranges == [[0, row["total_chars"]]]
                  and not row.get("expand_ref")):
                row["body_delivery"] = "full"
        delivered_speakers = {
            row["speaker_ref"] for row in rows
            if row.get("kind") == "source" and row.get("speaker_ref")
            and (row.get("content") or row.get("excerpts"))
        }
        for row in rows:
            if row.get("kind") == "source" and row.get("speaker_ref") not in delivered_speakers:
                row.pop("speaker_ref", None)
            if (row.get("kind") == "interpretation"
                    and row.get("about_ref") in provisional_speakers.values()
                    and row["about_ref"] not in delivered_speakers):
                row.pop("about_ref", None)
        if serialized_material_bytes(projected) > max_bytes:
            return {"view": VIEW_PROTOCOL, "status": "INSUFFICIENT_MATERIAL_BUDGET"}

        # Only aliases in the final view are valid. Truncated ranges bind to their
        # actual delivered span, never the larger pre-budget range.
        visible: set[str] = set()
        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for key, part in value.items():
                    if (key in {"ref", "current_ref", "expand_ref",
                               "correction_expand_ref", "speaker_ref", "about_ref"}
                            and isinstance(part, str)):
                        if part in provisional:
                            visible.add(part)
                    elif key not in {"content", "text", "context", "scope_note"}:
                        collect(part)
            elif isinstance(value, list):
                for part in value:
                    collect(part)
            elif isinstance(value, str) and value in provisional:
                visible.add(value)
        collect(projected)
        for row in rows:
            alias = row["ref"]
            if alias in provisional:
                binding = provisional[alias]
                spans = (
                    (tuple(row["range"]),)
                    if isinstance(row.get("range"), list) and (
                        row.get("content") or row.get("text")
                    ) else tuple(tuple(part["range"]) for part in row.get("excerpts", []))
                )
                provisional[alias] = MaterialBinding(
                    binding.exact_ref, binding.kind, spans,
                    binding.content_sha256 if spans else "",
                )
        self._bindings.update({short: bound for short, bound in provisional.items()
                               if short in visible})
        self._bindings.update({
            short: MaterialBinding(self.memory.source_subject(source_ref), "subject")
            for source_ref, short in provisional_speakers.items()
            if short in delivered_speakers and self.memory is not None
        })
        if any((row.get("speaker_ref") == "u0" or row.get("about_ref") == "u0")
               and (row.get("content") or row.get("text") or row.get("excerpts"))
               for row in rows):
            self._bindings["u0"] = MaterialBinding("current_user", "subject")
        self._next += len(provisional)
        return projected
