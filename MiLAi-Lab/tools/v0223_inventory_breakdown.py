"""Versioned S-only private inventory attribution; algorithm copied from candidate.

One K2 candidate: remove whole-JSON copies only inside fixed tree traversal.

Public scope readers and all dynamic validation are unchanged. Private parsed
objects stay inside verify_tree's lexical traversal. Valid outgoing metadata is
(Path, str); malformed mutable digest values are copied before passing them to
scope methods, preserving the original deferred rejection order and isolation.
No metadata or borrowed JSON API, cross-scope cache, or admission cache exists.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import v0222_admission_read_scope as read_scope
import v0222_scoped_evidence as evidence

PHASES = ("private_json_parse", "private_json_eligibility", "private_json_copy_guard")
_ACTIVE = None


def _invalid(state, exc):
    state["errors"].append(type(exc).__name__)


def _start(scope, category):
    state = _ACTIVE
    if state is None:
        raise RuntimeError("BREAKDOWN_REQUIRES_INSTALLED_OBSERVER")
    observer = state["observer"]
    try:
        if os.getpid() != observer.pid or threading.get_ident() != observer.thread:
            raise RuntimeError("FRESH_SINGLE_THREAD_OBSERVER_REQUIRED")
        if not observer.stack or observer.stack[-1]["category"] != "inventory":
            raise RuntimeError("PRIVATE_PHASE_REQUIRES_INVENTORY_PARENT")
        parent = observer.stack[-1]
        if scope not in observer.scope_ids:
            observer.scope_sequence += 1
            observer.scope_ids[scope] = observer.scope_sequence
        start = observer.clock()
        return state, parent, observer.scope_ids[scope], category, start
    except BaseException as exc:
        _invalid(state, exc)
        return None


def _finish(token, success):
    if token is None:
        return
    state, parent, scope_id, category, start = token
    observer = state["observer"]
    try:
        end = observer.clock()
        elapsed = end - start
        if elapsed < 0 or not observer.stack or observer.stack[-1] is not parent:
            raise RuntimeError("INVALID_PRIVATE_PHASE_ACCOUNTING")
        key = (parent["span_id"], scope_id, category)
        rows = state["rows"]
        if key not in rows:
            observer.sequence += 1
            row = dict.fromkeys(
                (
                    "count",
                    "attempted_count",
                    "completed_count",
                    "failed_count",
                    "unique_files",
                    "read_bytes",
                    "hash_bytes",
                    "json_docs",
                    "jsonl_rows",
                    "sql_rows",
                    "inclusive_wall_ns",
                    "exclusive_wall_ns",
                ),
                0,
            )
            row.update(
                span_id=observer.sequence,
                parent_span_id=parent["span_id"],
                operation_id=parent["operation_id"],
                scope_id=scope_id,
                category=category,
                start_ns=start,
                end_ns=end,
                timing_kind="DISJOINT_CALL_SUM_WITH_TIMESTAMP_ENVELOPE",
                terminal_status="RETURNED",
                run_id=observer.run_id,
                pid=observer.pid,
            )
            rows[key] = row
            observer.records.append(row)
        row = rows[key]
        row["end_ns"] = end
        row["inclusive_wall_ns"] += elapsed
        row["exclusive_wall_ns"] += elapsed
        row["count"] += 1
        row["attempted_count"] += 1
        row["completed_count"] += int(success)
        row["failed_count"] += int(not success)
        if category == "private_json_parse" and success:
            row["json_docs"] += 1
        if not success:
            row["terminal_status"] = "CONTAINS_UNWIND"
        parent["children_ns"] += elapsed
    except BaseException as exc:
        _invalid(state, exc)


def inventory_breakdown_report(observer):
    state = getattr(observer, "_inventory_breakdown_state", None)
    if not observer.enabled:
        return {"status": "DISABLED", "categories": list(PHASES), "errors": []}
    errors = state["errors"] if state is not None else ["BREAKDOWN_NOT_INSTALLED"]
    return {
        "status": "INVALID_OBSERVATION" if errors else "COMPLETE_AGGREGATES",
        "categories": list(PHASES),
        "errors": list(errors),
    }


def verify_tree(scope, path, expected_sha256, seen=None):
    """Original traversal/order/counters with a lexical read-only parsed consumer."""
    with evidence._guard(scope):
        if seen is not None and (type(seen) is not set or seen):
            raise evidence.ScopedEvidenceError("TREE_SEEN_MUST_START_EMPTY")
        stack, completed = set(), set()

        def shallow_builtin_depth(value):
            """Eligibility only: every uncertain shape uses the original copy.

            The 64-container boundary is NOT an acceptance/depth limit. It bounds
            a small recursion-budget probe; deeper values take original deepcopy.
            No scan result survives this one original read_json-equivalent call.
            """
            if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11):
                return None
            pending, seen_containers, maximum = [(value, 0)], set(), 0
            while pending:
                node, depth = pending.pop()
                kind = type(node)
                if kind is dict or kind is list:
                    depth += 1
                    if depth > 64 or id(node) in seen_containers:
                        return None
                    seen_containers.add(id(node))
                    maximum = max(maximum, depth)
                    if kind is dict:
                        if any(type(key) is not str for key in node):
                            return None
                        pending.extend((child, depth) for child in node.values())
                    else:
                        pending.extend((child, depth) for child in node)
                elif kind not in (str, int, float, bool, type(None)):
                    return None
            # Python frames are only a conservative early fallback trigger, NOT
            # a proof of C recursion headroom. The direct sentinel below checks
            # actual remaining recursion capacity, including hidden C callers.
            frame, python_depth = sys._getframe(), 0
            while frame is not None:
                python_depth += 1
                frame = frame.f_back
            if python_depth + 2 * (maximum + 2) >= sys.getrecursionlimit():
                return None
            return maximum

        def parsed(current, digest):
            # Same _entry invocation, strict hooks, parse counter and poisoning as
            # read_json. The only omitted work is its final defensive deepcopy.
            entry = scope._entry(current, digest)
            try:
                if not entry.parsed_ready:
                    token = _start(scope, "private_json_parse")
                    success = False
                    try:
                        scope._stats["json_parses"] += 1
                        entry.parsed = json.loads(
                            entry.data.decode("utf-8"),
                            object_pairs_hook=read_scope._pairs,
                            parse_constant=read_scope._constant,
                            parse_float=read_scope._finite_float,
                        )
                        entry.parsed_ready = True
                        success = True
                    finally:
                        _finish(token, success)
                token = _start(scope, "private_json_eligibility")
                success = False
                try:
                    try:
                        depth = shallow_builtin_depth(entry.parsed)
                    except RecursionError:
                        depth = None
                    success = True
                finally:
                    _finish(token, success)
                token = _start(scope, "private_json_copy_guard")
                success = False
                try:
                    if depth is not None:
                        # Same frame, sentinel depth and fallback as sealed candidate.
                        probe = None
                        for _ in range(depth + 2):
                            probe = [probe]
                        try:
                            copy.deepcopy(probe)
                        except RecursionError:
                            depth = None
                    if depth is None:
                        # Outside sentinel except: original exception context retained.
                        value = copy.deepcopy(entry.parsed)
                    else:
                        value = entry.parsed
                    success = True
                    return value
                finally:
                    _finish(token, success)
            except BaseException as exc:
                scope._poison(exc)
                raise

        def digest_metadata(value):
            # Do not validate early: a previous missing direct edge must still
            # fail before this invalid digest reaches the original _entry.
            return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

        def edges(node):
            if isinstance(node, list):
                for item in node:
                    yield from edges(item)
            elif isinstance(node, dict):
                for field in ("files", "dependencies", "inputs"):
                    for name, digest in evidence._mapping(node.get(field, {}), field).items():
                        yield Path(name), digest_metadata(digest)
                hashes = node.get("hashes", {})
                if not isinstance(hashes, dict):
                    raise evidence.ScopedEvidenceError("HASHES_MAPPING_REQUIRED")
                for field, digest in hashes.items():
                    candidate = node.get(field)
                    if isinstance(candidate, str) and Path(candidate).is_absolute():
                        yield Path(candidate), digest_metadata(digest)
                for field in ("references", "entries"):
                    if field in node:
                        yield from edges(node[field])

        def visit(current, digest):
            current = Path(current)
            scope.read_bytes(current, digest)
            if current.suffix != ".json":
                return
            key = (str(current.resolve()), digest)
            value, loaded = None, False
            if current.name == "manifest.json":
                value = parsed(current, digest)
                loaded = True
                if isinstance(value, dict) and all(
                    field in value for field in ("dependencies", "inputs", "python", "packages")
                ):
                    evidence.verify_manifest(scope, current.parent, digest)
            if key in completed:
                return
            if not loaded:
                value = parsed(current, digest)
            references = tuple(edges(value))
            for target, target_digest in references:
                scope.read_bytes(target, target_digest)
            if key in stack:
                return
            stack.add(key)
            try:
                for target, target_digest in references:
                    visit(target, target_digest)
                completed.add(key)
            finally:
                stack.remove(key)

        visit(path, expected_sha256)


@contextmanager
def installed_inventory_breakdown(observer):
    """Install after candidate and before coarse; U is an exact no-patch path."""
    global _ACTIVE
    if not observer.enabled:
        yield observer
        return
    import v0223_tree_readonly_candidate as candidate

    if _ACTIVE is not None or observer.installed:
        raise RuntimeError("BREAKDOWN_INSTALL_ORDER_OR_REENTRY")
    if evidence.verify_tree is not candidate.verify_tree:
        raise RuntimeError("BREAKDOWN_REQUIRES_CANDIDATE_FIRST")
    original, replacement = evidence.verify_tree, verify_tree
    state = {"observer": observer, "rows": {}, "errors": []}
    observer._inventory_breakdown_state = state
    changes = []
    prefixes = ("v0222_", "run_v0222_", "v0223_", "run_v0223_")
    existing = {
        (id(module), alias)
        for name, module in tuple(sys.modules.items())
        if module is not None and name.startswith(prefixes)
        for alias, value in tuple(vars(module).items())
        if value is replacement
    }
    _ACTIVE = state
    try:
        for name, module in tuple(sys.modules.items()):
            if module is not None and name.startswith(prefixes):
                for alias, value in tuple(vars(module).items()):
                    if value is original:
                        changes.append((module, alias, value))
                        setattr(module, alias, replacement)
        yield observer
    finally:
        for module, alias, value in reversed(changes):
            setattr(module, alias, value)
        for name, module in tuple(sys.modules.items()):
            if module is not None and name.startswith(prefixes):
                for alias, value in tuple(vars(module).items()):
                    if value is replacement and (id(module), alias) not in existing:
                        setattr(module, alias, original)
        _ACTIVE = None
