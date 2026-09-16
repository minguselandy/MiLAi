"""Thin text-action bridge; the caller supplies an isolated native terminal.

No shell runs here. Host history defaults to COMMON_CONTEXT; every policy has the
same explicit context controls and immutable observation readback. Raw terminal
outputs are preserved outside Git before a bounded view is returned to the model.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

from milai_lab.methods.workspace_policy import Exchange, Limits, Material, Message, WorkspaceError
from workspace_policy_host import WorkspaceHost

VIEW_CHARS = 16000
INSTRUCTION = """Complete the user task in its isolated terminal environment.
Each response is one JSON object with action and arguments, plus optional work_update.
Actions (exact argument keys):
exec: {command: string, timeout_sec?: integer from 1 to 120}; timeout defaults to 30 seconds.
Runs bash in the task container. Other actions require the exact keys below.
read: {ref: string, start: nonnegative integer, length: integer from 1 to 16000};
reads characters of an immutable prior terminal receipt, not current filesystem state.
context: {mode: \"COMMON_CONTEXT\" or \"MANAGED_WORKSET\", recent_exchanges: integer 1..64};
changes the next input. Default COMMON_CONTEXT keeps all fitting history. MANAGED_WORKSET
keeps the chosen recent exchanges and source bodies selected in work_update.focus_refs.
All original receipts remain readable in either mode. Restore COMMON_CONTEXT explicitly.
final: {text: string}; ends your attempt. Task artifacts and the native verifier determine success.
Example:
{\"action\":\"exec\",\"arguments\":{\"command\":\"pwd\",\"timeout_sec\":10},\"work_update\":null}
You may use ordinary notes, evidence references, uncertainty, review and context selection.
Notes are optional working artifacts; use only detail useful for upcoming decisions.
Output capacity is 4096 tokens shared by action and note; optional note capacity is 2944
tokens, with no 512-token gate on business actions. Terminal receipts initially show at
most 16000 characters, with explicit size and readback references. Prefer bounded commands
and paginate large outputs. Commands have no terminal session: use files or background
processes inside the container when necessary. A terminal timeout ends this attempt
because unfinished command side effects may be unknown. Do not inspect hidden evaluator
or solution files; use the task's ordinary assets and your own checks. Do not contact
the host, its services or credentials. Limit network access to task-required dependencies.
"""


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class TerminalTools:
    """Shared terminal/receipt mechanics, with no working-memory policy."""

    def __init__(self, *, binding, root, terminal):
        self.root, self.terminal, self.binding = root, terminal, binding
        self.sources: dict[str, Material] = {}
        self.raw_receipts: dict[str, str] = {}
        self.finished = False
        self.final_text = None
        self.tool_seconds = 0.0

    @staticmethod
    def validate(action):
        name, args = action["action"], action["arguments"]
        fields = {"exec": {"command", "timeout_sec"}, "read": {"ref", "start", "length"},
                  "final": {"text"}}
        expected = fields.get(name)
        valid_fields = (isinstance(args, dict) and
                        (set(args) == expected or (name == "exec" and set(args) == {"command"})))
        if name not in fields or not valid_fields:
            raise WorkspaceError("UNSUPPORTED_ACTION_OR_ARGUMENTS")
        if name == "exec":
            valid = (isinstance(args["command"], str)
                     and type(args.get("timeout_sec", 30)) is int
                     and 1 <= args.get("timeout_sec", 30) <= 120)
        elif name == "read":
            valid = (isinstance(args["ref"], str) and type(args["start"]) is int
                     and args["start"] >= 0 and type(args["length"]) is int
                     and 1 <= args["length"] <= VIEW_CHARS)
        else:
            valid = isinstance(args["text"], str)
        if not valid:
            raise WorkspaceError("INVALID_ARGUMENT_VALUE")

    def change_context(self, args):
        raise WorkspaceError("CONTEXT_CONTROL_NOT_SUPPORTED")

    def dispatch(self, action):
        self.validate(action)
        name, args = action["action"], action["arguments"]
        started = time.monotonic()
        if name == "exec":
            try:
                result = self.terminal(args["command"], args.get("timeout_sec", 30))
            except BaseException:
                self.tool_seconds += time.monotonic() - started
                raise
        elif name == "read":
            raw = self.raw_receipts.get(args["ref"])
            result = {"status": "NOT_PUBLISHED"} if raw is None else {
                "ref": args["ref"], "total_chars": len(raw), "start": args["start"],
                "text": raw[args["start"]:args["start"] + args["length"]],
            }
        elif name == "context":
            result = self.change_context(args)
        else:
            self.finished, self.final_text = True, args["text"]
            result = {"status": "SUBMITTED_NOT_VERIFIED"}
        elapsed = time.monotonic() - started
        self.tool_seconds += elapsed
        handle = f"H{len(self.sources) + 1:03d}"
        raw = json.dumps({"action": action, "result": result}, ensure_ascii=False)
        self.raw_receipts[handle] = raw
        dump(self.root / "receipts" / f"{handle}.json", {"raw": raw, "seconds": elapsed})
        view = json.dumps({"ref": handle, "total_chars": len(raw),
                           "shown_chars": min(len(raw), VIEW_CHARS), "receipt": raw[:VIEW_CHARS]},
                          ensure_ascii=False)
        material = Material(handle, hashlib.sha256(raw.encode()).hexdigest(),
                            self.binding, view)
        self.sources[handle] = material
        refs = frozenset((material.ref,))
        return Exchange((Message("user", view),), refs, refs)


class TerminalSession(TerminalTools):
    def __init__(self, *, instruction, policy, binding, root, counts, context, terminal):
        super().__init__(binding=binding, root=root, terminal=terminal)
        self.host = WorkspaceHost(
            binding=binding, base=(Message("system", INSTRUCTION), Message("user", instruction)),
            registry=lambda: self.sources, count_text=counts.text, count_messages=counts.messages,
            validate_action=self.validate, policy=policy, enabled=True,
            limits=Limits(work_tokens=2944, focus_refs=64, recent_exchanges=2,
                          input_tokens=context - 4096, output_tokens=4096, catalog_entries=128),
        )

    @staticmethod
    def validate(action):
        if action["action"] != "context":
            return TerminalTools.validate(action)
        args = action["arguments"]
        if not isinstance(args, dict) or set(args) != {"mode", "recent_exchanges"}:
            raise WorkspaceError("UNSUPPORTED_ACTION_OR_ARGUMENTS")
        if (args["mode"] not in ("COMMON_CONTEXT", "MANAGED_WORKSET")
                or type(args["recent_exchanges"]) is not int
                or not 1 <= args["recent_exchanges"] <= 64):
            raise WorkspaceError("INVALID_ARGUMENT_VALUE")

    def change_context(self, args):
        self.host.mode = args["mode"]
        self.host.limits = replace(self.host.limits, recent_exchanges=args["recent_exchanges"])
        return {"next_input_context": args}
