"""One K2 candidate: remove whole-JSON copies only inside fixed tree traversal.

Public scope readers and all dynamic validation are unchanged. Private parsed
objects stay inside verify_tree's lexical traversal. Valid outgoing metadata is
(Path, str); malformed mutable digest values are copied before passing them to
scope methods, preserving the original deferred rejection order and isolation.
No metadata or borrowed JSON API, cross-scope cache, or admission cache exists.
"""

from __future__ import annotations

import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import v0222_admission_read_scope as read_scope
import v0222_scoped_evidence as evidence


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
                    scope._stats["json_parses"] += 1
                    entry.parsed = json.loads(
                        entry.data.decode("utf-8"),
                        object_pairs_hook=read_scope._pairs,
                        parse_constant=read_scope._constant,
                        parse_float=read_scope._finite_float,
                    )
                    entry.parsed_ready = True
                try:
                    depth = shallow_builtin_depth(entry.parsed)
                except RecursionError:
                    depth = None
                if depth is not None:
                    # CPython 3.11 copy.py: each builtin list/dict container adds
                    # deepcopy + _deepcopy_list/_deepcopy_dict (two frames).
                    # Dict str keys/atomic leaves and _keep_alive add at most
                    # two more frames. A list chain of maximum+2 containers and
                    # an atomic leaf strictly dominates that stack demand.
                    # Both probe and fallback execute DIRECTLY in this parsed
                    # frame, at the same nesting as original scope.read_json.
                    probe = None
                    for _ in range(depth + 2):
                        probe = [probe]
                    try:
                        copy.deepcopy(probe)
                    except RecursionError:
                        depth = None
                if depth is None:
                    # Outside the probe except block: do not attach the probe's
                    # exception as context to an original-data copy failure.
                    return copy.deepcopy(entry.parsed)
                return entry.parsed
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
def installed_candidate():
    """Replace exactly verify_tree and matching loaded aliases; restore on exit.

    Imports performed while installed see evidence.verify_tree's replacement.
    An already-imported non-V0222/V0223 alias is intentionally not covered: the
    frozen runner must load its named stack before installation and audit it.
    """
    original = evidence.verify_tree
    if original is verify_tree:
        raise RuntimeError("CANDIDATE_INSTALL_MUST_NOT_BE_NESTED")
    changes = []
    existing_candidate_aliases = {
        (id(module), alias)
        for name, module in tuple(sys.modules.items())
        if module is not None and name.startswith(("v0222_", "run_v0222_", "v0223_", "run_v0223_"))
        for alias, value in tuple(vars(module).items())
        if value is verify_tree
    }
    try:
        for name, module in tuple(sys.modules.items()):
            if module is not None and name.startswith(
                ("v0222_", "run_v0222_", "v0223_", "run_v0223_")
            ):
                for alias, value in tuple(vars(module).items()):
                    if value is original:
                        changes.append((module, alias, value))
                        setattr(module, alias, verify_tree)
        yield
    finally:
        for module, alias, value in reversed(changes):
            setattr(module, alias, value)
        for name, module in tuple(sys.modules.items()):
            if module is not None and name.startswith(
                ("v0222_", "run_v0222_", "v0223_", "run_v0223_")
            ):
                for alias, value in tuple(vars(module).items()):
                    if (
                        value is verify_tree
                        and (id(module), alias) not in existing_candidate_aliases
                    ):
                        setattr(module, alias, original)
