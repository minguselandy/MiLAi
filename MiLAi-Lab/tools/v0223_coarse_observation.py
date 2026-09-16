"""Opt-in, single-thread V0223 coarse observation, with no network or report IO.

The installer wraps only named V0222 work boundaries. It never patches a JSON,
filesystem or SQL library. Per-file calls accumulate in memory into their nearest
coarse span: their first/last timestamps are envelopes, NOT continuous intervals.
Exact inclusive/exclusive durations are accumulated while calls are on the stack.
The caller owns process spawn/exit timing and persistence inside its deadline.
This module alone cannot certify measurement coverage or Gate A.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import weakref
from contextlib import contextmanager
from functools import wraps

CATEGORIES = frozenset(
    {
        "execution",
        "operation",
        "operation_entry",
        "operation_body",
        "final_revalidation",
        "inventory",
        "read_first",
        "read_closing",
        "json_parse_copy",
        "jsonl_parse_construct",
        "history",
        "dynamic_validation",
        "scope_close",
        "initialization",
        "parent_gate",
        "reference_preparation",
        "process_spawn_exit",
        "report_io",
    }
)
COUNTERS = (
    "count",
    "unique_files",
    "read_bytes",
    "hash_bytes",
    "json_docs",
    "jsonl_rows",
    "sql_rows",
)


class CoarseObserver:
    """Explicit spans with exact stack accounting; no payloads or file names retained."""

    def __init__(self, run_id, *, enabled=False, clock=time.perf_counter_ns):
        self.run_id, self.enabled, self.clock = run_id, enabled, clock
        self.pid, self.thread = os.getpid(), threading.get_ident()
        self.records, self.stack = [], []
        self.sequence = 0
        self.installed = False
        self.scope_ids = weakref.WeakKeyDictionary()
        self.scope_sequence = 0

    @contextmanager
    def span(self, category, *, operation_id=None, scope_id=None, aggregate=False):
        if category not in CATEGORIES:
            raise ValueError("UNKNOWN_FIXED_MEASUREMENT_BOUNDARY")
        if not self.enabled:
            yield None
            return
        if os.getpid() != self.pid or threading.get_ident() != self.thread:
            raise RuntimeError("FRESH_SINGLE_THREAD_OBSERVER_REQUIRED")
        parent = self.stack[-1] if self.stack else None
        self.sequence += 1
        frame = {
            "span_id": self.sequence,
            "parent_span_id": parent["span_id"] if parent else None,
            "operation_id": operation_id
            if operation_id is not None
            else (parent["operation_id"] if parent else None),
            "scope_id": scope_id
            if scope_id is not None
            else (parent["scope_id"] if parent else None),
            "category": category,
            "start_ns": self.clock(),
            "children_ns": 0,
            "terminal_status": "RETURNED",
            "aggregates": {},
            "aggregate": aggregate,
        }
        frame.update(dict.fromkeys(COUNTERS, 0))
        frame["count"] = 1
        self.stack.append(frame)
        try:
            yield frame
        except BaseException:
            frame["terminal_status"] = "UNWOUND"
            raise
        finally:
            end = self.clock()
            self.stack.pop()
            frame["end_ns"] = end
            wall = end - frame["start_ns"]
            frame["inclusive_wall_ns"] = wall
            frame["exclusive_wall_ns"] = wall - frame.pop("children_ns")
            if parent:
                parent["children_ns"] += wall
            frame.update(run_id=self.run_id, pid=self.pid)
            # Aggregates do not retain an interval list or write per-file records.
            nested = frame.pop("aggregates")
            frame.pop("aggregate")
            coarse = next((item for item in reversed(self.stack) if not item["aggregate"]), None)
            if aggregate and coarse:
                key = (category, frame["scope_id"])
                frame["parent_span_id"] = coarse["span_id"]
                rows = coarse["aggregates"]
                if key not in rows:
                    rows[key] = frame
                    frame["timing_kind"] = "DISJOINT_CALL_SUM_WITH_TIMESTAMP_ENVELOPE"
                else:
                    row = rows[key]
                    row["end_ns"] = end
                    for name in (*COUNTERS, "inclusive_wall_ns", "exclusive_wall_ns"):
                        row[name] += frame[name]
                    if frame["terminal_status"] != "RETURNED":
                        row["terminal_status"] = "CONTAINS_UNWIND"
                # Child aggregation remains separate; parent identifiers identify
                # the invocation even if that invocation itself was aggregated.
                self.records.extend(nested.values())
            else:
                frame["timing_kind"] = "CONTIGUOUS_SPAN"
                self.records.append(frame)
                self.records.extend(nested.values())

    def report(self):
        return {
            "run_id": self.run_id,
            "pid": self.pid,
            "status": "COMPLETE_SPANS" if not self.stack else "INCOMPLETE_SPANS",
            "mode": "S" if self.enabled else "U",
            "records": self.records,
            "unknown": [
                "SQL rows (no SQL cursor substitution)",
                "read/hash/parse volume on failed calls is a lower bound",
                "startup/import and report/exit unless externally enclosed",
                "unwrapped work remains exclusive in its enclosing boundary",
            ],
            "limits": [
                "Timestamp envelopes must not be treated as continuous intervals.",
                "Inclusive nested durations must not be summed.",
                "Scope IDs are process-local mechanical identifiers.",
            ],
        }

    @contextmanager
    def operation(self, manager, *, operation_id=None):
        """Preserve context-manager exception semantics and observe all cleanup.

        The operation interval encloses enter, body, close, deadline checks,
        transaction exit and stop recording. Body duration is explicitly separate.
        """
        with self.span("operation", operation_id=operation_id):
            with self.span("operation_entry"):
                value = manager.__enter__()
            try:
                with self.span("operation_body"):
                    yield value
            except BaseException:
                info = sys.exc_info()
                with self.span("final_revalidation"):
                    suppress = manager.__exit__(*info)
                if not suppress:
                    raise
            else:
                with self.span("final_revalidation"):
                    manager.__exit__(None, None, None)


@contextmanager
def installed(observer, *, batch_class=None):
    """Temporarily instrument the fixed already-imported V0222 CPU stack.

    Must be entered after CPU modules have loaded and before any workload. U
    mode leaves every function unchanged. Import/restore is not workload timing.
    No probe installs itself on import. Existing profiler state is rejected.
    """
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise RuntimeError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    if threading.active_count() != 1 or observer.installed:
        raise RuntimeError("SINGLE_THREAD_NONREENTRANT_INSTALL_REQUIRED")
    if not observer.enabled:
        yield observer
        return
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_presentation_batch_v2 import Batch
    from v0222_scoped_cpu_batch import OfflineBatch

    batch_class = OfflineBatch if batch_class is None else batch_class
    observer.installed = True
    changes = []

    def patch(owner, name, replacement):
        own = name in vars(owner)
        old = getattr(owner, name)
        changes.append((owner, name, old, own))
        setattr(owner, name, replacement)

    def wrapper(original, category, *, aggregate=False, scope_method=False):
        @wraps(original)
        def call(*args, **kwargs):
            scope = args[0] if scope_method else None
            scope_id = None
            before = None
            if scope is not None:
                if scope not in observer.scope_ids:
                    observer.scope_sequence += 1
                    observer.scope_ids[scope] = observer.scope_sequence
                scope_id = observer.scope_ids[scope]
                if category == "json_parse_copy":
                    before = scope.stats["json_parses"]
            selected = category
            if category == "read_first" and kwargs.get("closing"):
                selected = "read_closing"
            with observer.span(selected, scope_id=scope_id, aggregate=aggregate) as row:
                result = original(*args, **kwargs)
                if row is not None:
                    if selected in {"read_first", "read_closing"}:
                        row.update(
                            read_bytes=len(result[0]), hash_bytes=len(result[0]), unique_files=1
                        )
                    elif selected == "json_parse_copy":
                        row["json_docs"] = scope.stats["json_parses"] - before
                    elif selected == "jsonl_parse_construct":
                        row["jsonl_rows"] = len(result)
                return result

        return call

    try:
        for name, category, aggregate in (
            ("_regular_bytes", "read_first", True),
            ("read_json", "json_parse_copy", True),
            ("_close", "scope_close", False),
        ):
            patch(
                AdmissionReadScope,
                name,
                wrapper(
                    getattr(AdmissionReadScope, name),
                    category,
                    aggregate=aggregate,
                    scope_method=True,
                ),
            )
        for owner, names in (
            (Batch, ("_check_journal", "_owned", "_ready")),
            (batch_class, ("_authorize",)),
        ):
            for name in names:
                category = "inventory" if name == "_authorize" else "dynamic_validation"
                patch(owner, name, wrapper(getattr(owner, name), category))
        original_operation = batch_class._operation

        @wraps(original_operation)
        def operation_call(*args, **kwargs):
            return observer.operation(
                original_operation(*args, **kwargs),
                operation_id=f"operation-{observer.sequence + 1}",
            )

        patch(batch_class, "_operation", operation_call)
        # Replace only references identical to the named functions in loaded
        # V0222 modules. No global-library replacement and no future import hook.
        fixed = {
            "v0222_presentation_lineage_v2": {"_snapshot": "dynamic_validation"},
            "v0222_scoped_evidence": {
                "verify_tree": "inventory",
                "verify_manifest": "inventory",
                "read_pinned_events": "jsonl_parse_construct",
            },
            "v0222_scoped_history": {
                "historical_usage_from_pinned": "history",
                "presentation_history": "history",
            },
        }
        for module_name, names in fixed.items():
            module = sys.modules.get(module_name)
            if module is None:
                raise RuntimeError("CPU_MODULES_MUST_BE_LOADED_BEFORE_INSTALL")
            for name, category in names.items():
                original = getattr(module, name)
                replacement = wrapper(original, category)
                for target_name, target in tuple(sys.modules.items()):
                    if (
                        target_name.startswith(("v0222_", "run_v0222_", "v0223_", "run_v0223_"))
                        and target is not None
                    ):
                        for alias, value in tuple(vars(target).items()):
                            if value is original:
                                patch(target, alias, replacement)
        yield observer
    finally:
        for owner, name, old, own in reversed(changes):
            if own:
                setattr(owner, name, old)
            else:
                delattr(owner, name)
        observer.installed = False


def interval_union_ns(records, categories):
    """Union explicit contiguous spans within one process, never aggregate envelopes.

    For generator admission select operation_entry and final_revalidation. This
    retains nested admissions inside a business body without charging the body.
    Process startup/exit remains a separately measured parent-process interval.
    """
    selected = [row for row in records if row["category"] in categories]
    if len({(row["run_id"], row["pid"]) for row in selected}) > 1:
        raise ValueError("CANNOT_COMBINE_PROCESS_CLOCK_DOMAINS")
    if any(row["timing_kind"] != "CONTIGUOUS_SPAN" for row in selected):
        raise ValueError("AGGREGATE_ENVELOPES_ARE_NOT_INTERVALS")
    total, end = 0, None
    for left, right in sorted((row["start_ns"], row["end_ns"]) for row in selected):
        if right < left:
            raise ValueError("NONMONOTONIC_INTERVAL")
        total += max(0, right - (left if end is None else max(left, end)))
        end = right if end is None else max(end, right)
    return total
