"""CPU-only code-object observation; never a reader, cache, or admission gate.

No observed function, frame local, argument, return value or exception is edited.
Callbacks collect only counters and clocks in memory. Inclusive spans overlap.
Reports are written after the entrypoint returns/unwinds, outside the batch tree.
The original parent child-manager includes child report IO in its timeout/wall;
an external stage owner must likewise include parent report IO and process exit.
"""

from __future__ import annotations

import dis
import json
import os
import resource
import sys
import threading
import time

OBSERVE_ENV = "MILA_V0222_CPU_OBSERVE"
SPANS = {"operation", "generator", "child"}


def clocks():
    return time.perf_counter_ns(), time.process_time_ns()


def elapsed(start):
    wall, cpu = clocks()
    return {"wall_ns": wall - start[0], "process_cpu_ns": cpu - start[1]}


def children_cpu():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return value.ru_utime + value.ru_stime


class Observer:
    """One current-thread profile, selected by exact already-loaded code objects.

    The only supported yielding target is the existing synchronous _operation
    context manager (one non-None db/scope/state tuple). Its span remains active
    during the with-body and ends after close, deadline checks and transaction
    exit. This is deliberately not a general async/generator profiling library.
    """

    def __init__(self, targets, *, jsonl_caller=None, json_document_caller=None):
        self.targets = dict(targets)
        self.jsonl_caller = jsonl_caller
        self.json_document_caller = json_document_caller
        self.frames, self.scopes = {}, {}
        self.orphan_scopes = []
        self.active, self.records, self.errors = [], [], []
        self.sequence = 0
        self.started = None
        self.finished = False
        self.callback = self._event

    def start(self):
        if self.started is not None or sys.getprofile() is not None:
            raise RuntimeError("FRESH_UNPROFILED_PROCESS_REQUIRED")
        if threading.active_count() != 1:
            raise RuntimeError("SINGLE_THREAD_CPU_OBSERVATION_REQUIRED")
        self.started = clocks()
        sys.setprofile(self.callback)

    def _new(self, kind, label, frame):
        self.sequence += 1
        row = {
            "id": self.sequence,
            "kind": kind,
            "label": label,
            "parent_operation": self.active[-1][1] if self.active else None,
            "start": clocks(),
        }
        row["start_wall_ns"] = row["start"][0]
        # Identifiers only: never retain data, prompts, event bodies or credentials.
        row["context"] = {
            name: value
            for name in ("stage", "episode", "inflight")
            if type(value := frame.f_locals.get(name)) in (str, bool)
        }
        return row

    def _event(self, frame, event, arg):
        # Deadline/control exceptions here must propagate. CPython can remove
        # the callback on error; finish then explicitly marks coverage incomplete.
        if event in {"call", "return"} and frame.f_code in self.targets:
            self._observe(frame, event, arg)

    def _observe(self, frame, event, arg):
        kind, label = self.targets[frame.f_code]
        key = id(frame)
        if event == "call":
            if kind == "generator" and key in self.frames:
                self.frames[key]["resumes"] += 1
                return
            if kind in {"strict_json", "json_document"}:
                caller = frame.f_back
                expected = self.jsonl_caller if kind == "strict_json" else self.json_document_caller
                if caller is None or caller.f_code is not expected:
                    return
            row = self._new(kind, label, frame)
            self.frames[key] = row
            if kind == "thread_start":
                self.errors.append("ADDITIONAL_THREAD_STARTED_NOT_COVERED")
            if kind in SPANS:
                self.active.append((key, row["id"]))
            if kind == "generator":
                row.update(yields=0, resumes=0)
            elif kind == "child":
                row["child_cpu_before"] = children_cpu()
            elif kind == "scope_init":
                scope_row = self._new("scope", label, frame)
                scope_row.update(read_timing={}, jsonl_parse_attempts=0, json_parse_attempts=0)
                scope_row["jsonl_parse_timing"] = {"wall_ns": 0, "process_cpu_ns": 0}
                scope_row["json_parse_timing"] = {"wall_ns": 0, "process_cpu_ns": 0}
                scope_key = id(frame.f_locals["self"])
                if scope_key in self.scopes:
                    # A scope can be GC'd without close and its object id reused.
                    # Retain only its unfinished measurement, never its raw bytes.
                    self.orphan_scopes.append(self.scopes[scope_key])
                self.scopes[scope_key] = scope_row
            elif kind in {"scope_close", "read"}:
                scope = frame.f_locals["self"]
                row["scope_key"] = id(scope)
                if kind == "scope_close":
                    row["already_closed_on_entry"] = scope._closed
                else:
                    row["phase"] = "closing" if frame.f_locals["closing"] else "first"
            elif kind in {"strict_json", "json_document"}:
                name = "scope" if kind == "strict_json" else "self"
                row["scope_key"] = id(frame.f_back.f_locals[name])
            return

        row = self.frames.get(key)
        if row is None:
            if kind in {"strict_json", "json_document"}:
                return  # Unselected callers of the same JSON function.
            raise RuntimeError("UNMATCHED_SELECTED_RETURN")
        opcode = dis.opname[frame.f_code.co_code[frame.f_lasti]]
        if kind == "generator" and opcode == "YIELD_VALUE" and arg is not None:
            if type(arg) is not tuple or len(arg) != 3 or row["yields"]:
                raise RuntimeError("UNEXPECTED_OPERATION_YIELD")
            row["yields"] += 1
            return
        self.frames.pop(key)
        if kind in SPANS:
            if not self.active or self.active[-1] != (key, row["id"]):
                raise RuntimeError("NON_NESTED_OPERATION_OBSERVATION")
            self.active.pop()
        timing = elapsed(row.pop("start"))
        row.update(timing)
        row["end_wall_ns"] = row["start_wall_ns"] + row["wall_ns"]
        row["return_observation"] = "RETURNED" if opcode == "RETURN_VALUE" else "UNWOUND"
        if kind == "scope_init":
            return
        if kind == "read":
            scope_row = self.scopes[row["scope_key"]]
            aggregate = scope_row["read_timing"].setdefault(
                row["phase"], {"calls": 0, "wall_ns": 0, "process_cpu_ns": 0}
            )
            aggregate["calls"] += 1
            for name in timing:
                aggregate[name] += timing[name]
            return
        if kind in {"strict_json", "json_document"}:
            scope_row = self.scopes[row["scope_key"]]
            prefix = "jsonl" if kind == "strict_json" else "json"
            scope_row[prefix + "_parse_attempts"] += 1
            for name in timing:
                scope_row[prefix + "_parse_timing"][name] += timing[name]
            return
        if kind == "scope_close":
            scope = frame.f_locals["self"]
            row["scope_status_after"], row["stats"] = scope.status, scope.stats
            if row["already_closed_on_entry"]:
                row["completion"] = "REPEATED_CLOSE_NOT_A_NEW_SUCCESS"
                self.records.append(row)
                return
            scope_row = self.scopes.pop(row["scope_key"])
            scope_row.update(elapsed(scope_row.pop("start")))
            scope_row["end_wall_ns"] = scope_row["start_wall_ns"] + scope_row["wall_ns"]
            scope_row.update(status=scope.status, stats=scope.stats, close=row)
            self.records.append(scope_row)
            return
        if kind == "child":
            row["reaped_children_cpu_seconds"] = children_cpu() - row.pop("child_cpu_before")
            row["child_cpu_scope"] = (
                "All children reaped in interval; requires sole child ownership."
            )
            if type(arg) is dict:
                row["exit_summary"] = {
                    name: arg[name] for name in ("pid", "returncode", "timed_out") if name in arg
                }
        self.records.append(row)

    def finish(self):
        if self.started is None or self.finished:
            raise RuntimeError("ONE_STARTED_UNFINISHED_OBSERVER_REQUIRED")
        self.finished = True
        if sys.getprofile() is self.callback:
            sys.setprofile(None)
        else:
            self.errors.append("PROFILE_REMOVED_OR_REPLACED")
        if threading.active_count() != 1:
            self.errors.append("ADDITIONAL_THREADS_NOT_COVERED")
        pending = [
            {"id": row["id"], "kind": row["kind"], "label": row["label"]}
            for row in (*self.frames.values(), *self.scopes.values(), *self.orphan_scopes)
        ]
        return {
            "status": "OBSERVED" if not self.errors and not pending else "INCOMPLETE_OBSERVATION",
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "timing": elapsed(self.started),
            "process_cpu_ns_before_report": time.process_time_ns(),
            "records": self.records,
            "errors": self.errors,
            "pending": pending,
            "limits": [
                "Observation completeness is not workload success or Gate A admission.",
                "Inclusive nested timings overlap; never sum them as total stage cost.",
                "Read timing includes path checks, IO and hashing, not hash-only CPU.",
                "JSON and JSONL counters include unsuccessful parse attempts.",
                "All profile overhead stays inside original deadlines; never subtract it.",
                "Window excludes stack import and report IO; outer process wall must include both.",
                "Forcibly killed processes have missing reports, not complete measurements.",
                "Scope json_parses also counts decode attempts; json_parse_attempts counts loads.",
                "Thread-local profile is for the fixed single-thread CPU workload only.",
            ],
        }


def cpu_targets(main):
    from run_v0222_presentation import run_child
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_cpu_batch import OfflineBatch
    from v0222_scoped_evidence import _strict_json, read_pinned_events

    targets = {
        AdmissionReadScope.__init__.__code__: ("scope_init", "scope.init"),
        AdmissionReadScope._close.__code__: ("scope_close", "scope.close"),
        AdmissionReadScope._regular_bytes.__code__: ("read", "scope.read"),
        json.loads.__code__: ("json_document", "scope.json"),
        _strict_json.__code__: ("strict_json", "history.jsonl"),
        OfflineBatch._operation.__wrapped__.__code__: ("generator", "batch._operation"),
        run_child.__code__: ("child", "run_child"),
        threading.Thread.start.__code__: ("thread_start", "thread.start"),
        main.__code__: ("operation", main.__module__ + ".main"),
    }
    for name in (
        "__init__",
        "_authorize",
        "authorize",
        "initialize",
        "launch_once",
        "claim",
        "admit",
        "http_admit",
        "reserve_request",
        "dispatch_started",
        "settle_event",
        "artifact",
        "references",
        "freeze_artifact",
        "finish",
        "p3_gate",
        "freeze_p3_gate",
        "snapshot",
        "stop",
    ):
        targets[getattr(OfflineBatch, name).__code__] = ("operation", "batch." + name)
    module = sys.modules[main.__module__]
    for name in ("run", "prepare", "preflight"):
        target = getattr(module, name, None)
        if target is not None:
            targets[target.__code__] = ("operation", main.__module__ + "." + name)
    return Observer(
        targets,
        jsonl_caller=read_pinned_events.__code__,
        json_document_caller=AdmissionReadScope.read_json.__code__,
    )


def persist_report(report, role):
    from v0222_scoped_cpu_batch import CPU_ROOT

    directory = CPU_ROOT.with_name(CPU_ROOT.name + "-measurements")
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory:
        raise RuntimeError("CANONICAL_CPU_MEASUREMENT_DIRECTORY_REQUIRED")
    path = directory / f"{role}-{os.getpid()}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_observed(main, role):
    """Explicit CPU-run opt-in, inherited by children; not a send authorization.

    Ordinary engineering help/refusal probes stay side-effect free by default.
    Gate A requires the opt-in and a complete report for every actual process;
    running without observation can never supply the required timing evidence.
    """
    if os.environ.get(OBSERVE_ENV) != "1":
        return main()
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    if role not in {"seal", "prepare", "preflight", "worker", "stage"}:
        raise RuntimeError("FIXED_CPU_OBSERVATION_ROLE_REQUIRED")
    observer = cpu_targets(main)
    observer.start()
    failure = None
    try:
        return main()
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            report = observer.finish()
            report["role"] = role
            report["entry_exception_type"] = type(failure).__name__ if failure is not None else None
            persist_report(report, role)
            if report["status"] != "OBSERVED":
                raise RuntimeError("INCOMPLETE_CPU_OBSERVATION")
        except BaseException as secondary:
            if failure is None:
                raise
            failure.add_note("SECONDARY_CPU_OBSERVATION_FAILURE: " + type(secondary).__name__)
