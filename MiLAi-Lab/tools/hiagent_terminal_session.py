"""Opt-in HiAgent terminal Host, reusing the existing isolated action bridge.

No model is called on import. Scripted generate/terminal callbacks can exercise the
lifecycle without HTTP; the Harbor adapter supplies real callbacks when requested.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from milai_lab.methods.adaptive_memory import PROFILES, AdaptiveMemoryHost
from milai_lab.methods.controlled_workspace import ReversibleWorkspaceHost
from milai_lab.methods.evidence_maintenance import EvidenceHost, HiAgentOnceHost
from milai_lab.methods.hiagent import HiAgentHost
from milai_lab.methods.observational_memory import ObservationalMemoryHost
from milai_lab.methods.workspace_control import WorkspaceControlHost
from milai_lab.methods.workspace_policy import Material
from workspace_terminal_session import VIEW_CHARS, TerminalTools

POLICY_DIR = Path(__file__).resolve().parents[1] / "configs/policies/hiagent"
TERMINAL_ADAPTER_VERSION = "hiagent-method-adapter-v0.7"
TOOL_CONTRACT = """
The complete action set is exec, read, final, retrieve. Use only these action names.
Create or modify files by running shell commands through exec. File editing is an
exec command, not a separate tool action.
Business actions and exact argument keys:
exec: {command: string, timeout_sec?: integer 1..120}; default 30 seconds.
Runs bash in the isolated task container, without a persistent terminal session.
read: {ref: string, start: nonnegative integer, length: integer 1..16000}; reads a
previous immutable receipt, not the live filesystem. Receipts initially show at
most 16000 characters, explicit size, and a handle; paginate to see more.
final: {text: string}; submits the attempt. Native artifacts/verifier decide success.
There is no context action: subgoal summarization and retrieve control history here.
An execution timeout stops the attempt because side effects may be unknown. Do not
inspect hidden evaluator/solution files or contact host services or credentials.
Use only task assets, your own checks, and network for task-required dependencies.
The entire response shares the configured output capacity; avoid oversized commands.
"""


class HiAgentTerminalSession:
    def __init__(
        self,
        *,
        instruction,
        binding,
        root,
        terminal,
        generate,
        max_calls=64,
        emit=None,
        method="HIAGENT",
        control_options=None,
    ):
        self.method = method
        self.tools = TerminalTools(binding=binding, root=root, terminal=terminal)
        self.actor_policy = (POLICY_DIR / "actor.txt").read_text() + TOOL_CONTRACT
        self.summary_policy = (POLICY_DIR / "summary.txt").read_text()
        host_class = HiAgentHost
        options = {}
        self.maintenance_mode = "EVERY_ASSEMBLY_NO_CACHE"
        if method == "H_ONCE":
            host_class = HiAgentOnceHost
            self.maintenance_mode = "ONCE_PER_SOURCE_AND_POLICY_IDENTITY"
        elif method in {"EVIDENCE_0", "EVIDENCE_1", "INCREMENTAL"}:
            host_class = EvidenceHost
            self.maintenance_mode = "ONCE_PER_NEW_OBSERVATION_BATCH_BEFORE_ACTOR"
            policy_dir = POLICY_DIR.parent / "evidence"
            self.actor_policy = (policy_dir / "actor.txt").read_text() + TOOL_CONTRACT
            self.summary_policy = (policy_dir / f"{method.lower()}.txt").read_text()
            options = {"source_entries": self.source_entries, "policy_version": method}
        elif method == "CONTROL_0":
            host_class = WorkspaceControlHost
            self.maintenance_mode = "INITIAL_AND_NEW_FEEDBACK_PLUS_BOUNDED_DELIVERY_REVIEW"
            policy_dir = POLICY_DIR.parent / "control"
            self.actor_policy = (policy_dir / "actor.txt").read_text() + TOOL_CONTRACT
            self.summary_policy = (policy_dir / "maintain.txt").read_text()
            options = {
                "source_entries": self.source_entries,
                "resolve_source": self.resolve_source,
                **(control_options or {}),
            }
        elif method in {"WORKSPACE_SIMPLE", "MILAI_RWC"}:
            host_class = ReversibleWorkspaceHost
            self.maintenance_mode = "BATCHED_FEEDBACK_LIFECYCLE_AND_OPTIONAL_DELIVERY_REVIEW"
            policy_dir = POLICY_DIR.parent / "workspace_control"
            self.actor_policy = (policy_dir / "actor.txt").read_text() + TOOL_CONTRACT
            self.summary_policy = (
                (policy_dir / "common.txt").read_text()
                + "\n"
                + (policy_dir / f"{method.lower()}.txt").read_text()
            )
            options = {
                "source_entries": self.versioned_sources,
                "resolve_source": self.resolve_source,
                "read_source": self.read_source,
                "archive_summary_policy": (POLICY_DIR / "summary.txt").read_text(),
                "policy_version": method,
                **(control_options or {}),
            }
        elif method == "OM_SYNC_PORT":
            host_class = ObservationalMemoryHost
            self.maintenance_mode = "SYNCHRONOUS_THRESHOLD_OBSERVATION_AND_REFLECTION"
            policy_dir = POLICY_DIR.parent / "om_sync"
            self.actor_policy = (policy_dir / "actor.txt").read_text() + TOOL_CONTRACT.replace(
                "There is no context action: subgoal summarization "
                "and retrieve control history here.",
                "There is no context action. OM retains observations and recent raw pages.",
            )
            self.summary_policy = (policy_dir / "observer.txt").read_text()
            options = {
                "reflector_policy": (policy_dir / "reflector.txt").read_text(),
                "source_entries": self.versioned_sources,
                "read_source": self.read_source,
                **(control_options or {}),
            }
        elif method in PROFILES:
            host_class = AdaptiveMemoryHost
            self.maintenance_mode = "ADAPTIVE_OBSERVE_COMPACT_REVISE_REVIEW"
            policy_dir = POLICY_DIR.parent / "adaptive_memory"
            self.actor_policy = (policy_dir / "actor.txt").read_text() + TOOL_CONTRACT.replace(
                "The complete action set is exec, read, final, retrieve.",
                "The complete action set is exec, read, final, retrieve, maintain.",
            ).replace(
                "There is no context action: subgoal summarization "
                "and retrieve control history here.",
                "There is no context action. Memory is maintained at applicable boundaries.",
            )
            self.summary_policy = (policy_dir / "common.txt").read_text() + "\n" + (
                policy_dir / f"{method.lower()}.txt"
            ).read_text()
            options = {
                "profile": method, "source_entries": self.versioned_sources,
                "read_source": self.read_source, **(control_options or {}),
            }
        elif method != "HIAGENT":
            raise ValueError("UNKNOWN_HIAGENT_METHOD")
        self.host = host_class(
            goal=instruction,
            actor_policy=self.actor_policy,
            summary_policy=self.summary_policy,
            generate=generate,
            validate_action=self.tools.validate,
            dispatch=self.dispatch,
            max_calls=max_calls,
            emit=emit,
            **options,
        )

    def source_entries(self):
        return [
            {"ref": ref, "total_chars": len(raw)} for ref, raw in self.tools.raw_receipts.items()
        ]

    def dispatch(self, action):
        exchange = self.tools.dispatch(action)
        return "\n".join(message.content for message in exchange.messages)

    def resolve_source(self, ref):
        return self.tools.sources[ref].text

    def versioned_sources(self):
        return [
            {"ref": ref, "revision": self.tools.sources[ref].revision, "total_chars": len(raw)}
            for ref, raw in self.tools.raw_receipts.items()
            if self.tools.sources[ref].eligible
            and self.tools.sources[ref].binding == self.tools.binding
        ]

    def read_source(self, ref, start, length):
        material = self.tools.sources.get(ref)
        if material is None or not material.eligible or material.binding != self.tools.binding:
            raise ValueError("SOURCE_NOT_READABLE_IN_CURRENT_BINDING")
        raw = self.tools.raw_receipts[ref]
        return {
            "ref": ref,
            "revision": material.revision,
            "start": start,
            "text": raw[start : start + length],
            "total_chars": len(raw),
            "next_start": start + length if start + length < len(raw) else None,
        }

    def checkpoint_data(self, *, environment_id):
        if not isinstance(self.host, (WorkspaceControlHost, ObservationalMemoryHost)):
            raise ValueError("CHECKPOINT_UNSUPPORTED_FOR_THIS_METHOD")
        return {
            "format": (
                "om-sync-terminal-checkpoint-v1"
                if self.method == "OM_SYNC_PORT"
                else "adaptive-memory-terminal-checkpoint-v1" if self.method in PROFILES
                else "workspace-control-terminal-checkpoint-v1"
            ),
            "method": self.method,
            "binding": self.tools.binding,
            "environment_id": environment_id,
            "host": self.host.checkpoint(),
            "receipts": dict(self.tools.raw_receipts),
            "tool_seconds": self.tools.tool_seconds,
            "finished": self.tools.finished,
            "final_text": self.tools.final_text,
        }

    def save_public_checkpoint(self, port, *, environment_id, operation_id):
        return port.save(
            self.checkpoint_data(environment_id=environment_id), operation_id=operation_id
        )

    def restore_public_checkpoint(self, port, *, environment_id):
        self.restore_checkpoint_data(port.load(), environment_id=environment_id)

    def save_checkpoint(self, path: Path, *, environment_id: str):
        """Explicit quiescent handoff, not per-action audit or crash recovery.

        The caller must keep the same isolated environment. This saves Host data
        and immutable receipts only, and never copies or rolls back the world.
        """
        value = self.checkpoint_data(environment_id=environment_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.host._event("CHECKPOINT_SAVED", path=str(path), environment_id=environment_id)

    def restore_checkpoint(self, path: Path, *, environment_id: str):
        """Resume once into a fresh Host bound to the retained task environment.

        This is a trusted local handoff API, not an untrusted upload or multiwriter
        lease. Do not continue the old Host or reuse an obsolete checkpoint after
        other actions. Unknown in-flight execution must be reconciled separately.
        """
        self.restore_checkpoint_data(json.loads(path.read_text()), environment_id=environment_id)

    def restore_checkpoint_data(self, value, *, environment_id):
        if (
            not isinstance(self.host, (WorkspaceControlHost, ObservationalMemoryHost))
            or self.tools.raw_receipts
            or self.host.initialized
            or sum(self.host.calls.values())
        ):
            raise ValueError("RESTORE_REQUIRES_FRESH_CONTROL_SESSION")
        if (
            value.get("format")
            != (
                "om-sync-terminal-checkpoint-v1"
                if self.method == "OM_SYNC_PORT"
                else "adaptive-memory-terminal-checkpoint-v1" if self.method in PROFILES
                else "workspace-control-terminal-checkpoint-v1"
            )
            or value.get("method", self.method) != self.method
            or value.get("binding") != self.tools.binding
            or value.get("environment_id") != environment_id
        ):
            raise ValueError("CHECKPOINT_ENVIRONMENT_MISMATCH")
        receipts = value["receipts"]
        if (
            not isinstance(receipts, dict)
            or list(receipts) != [f"H{i:03d}" for i in range(1, len(receipts) + 1)]
            or any(not isinstance(raw, str) for raw in receipts.values())
        ):
            raise ValueError("INVALID_CHECKPOINT_RECEIPTS")
        receipts = dict(receipts)
        sources = {}
        for ref, raw in receipts.items():
            view = json.dumps(
                {
                    "ref": ref,
                    "total_chars": len(raw),
                    "shown_chars": min(len(raw), VIEW_CHARS),
                    "receipt": raw[:VIEW_CHARS],
                },
                ensure_ascii=False,
            )
            sources[ref] = Material(
                ref, hashlib.sha256(raw.encode()).hexdigest(), self.tools.binding, view
            )
        self.tools.raw_receipts, self.tools.sources = receipts, sources
        try:
            self.host.restore(value["host"])
        except BaseException:
            self.tools.raw_receipts, self.tools.sources = {}, {}
            raise
        self.tools.tool_seconds = value["tool_seconds"]
        self.tools.finished = self.host.finished
        self.tools.final_text = value["final_text"] if self.tools.finished else None

    def set_goal(self, goal):
        if not isinstance(self.host, AdaptiveMemoryHost):
            raise ValueError("GOAL_UPDATE_UNSUPPORTED_FOR_THIS_METHOD")
        self.host.set_goal(goal)
        self.tools.finished = self.host.finished
        if not self.host.finished:
            self.tools.final_text = None
