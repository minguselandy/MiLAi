"""HiAgent mechanism transplant on the existing Harbor 0.23 terminal boundary.

This is not original AgentBoard/model/prompt reproduction. Both actor and summary
use the same real Provider and shared ledger, including failures. No implicit runs.
"""

import json
import time
from dataclasses import asdict

from hiagent_terminal_session import TERMINAL_ADAPTER_VERSION, HiAgentTerminalSession
from milai_lab.methods.adaptive_memory import (
    ADAPTIVE_OUTPUT_SCHEMA,
    PROFILES,
    AdaptiveMemoryConfig,
)
from milai_lab.methods.hiagent import METHOD_VERSION, UPSTREAM_COMMIT, HiAgentError
from milai_lab.methods.observational_memory import OM_OUTPUT_SCHEMA, OMConfig
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import MODEL
from workspace_harbor_agent import WorkspaceAgent
from workspace_task_provider import Provider
from workspace_terminal_session import dump


class HiAgentAgent(WorkspaceAgent):
    def __init__(
        self,
        *args,
        hiagent_max_calls=None,
        max_calls=64,
        control_handoff_after=None,
        control_feedback_batch_size=1,
        controller_output_tokens=2048,
        summary_output_tokens=1024,
        om_observation_tokens=12000,
        om_recent_events=2,
        **kwargs,
    ):
        if hiagent_max_calls is not None:
            if type(hiagent_max_calls) is not int or not 1 <= hiagent_max_calls <= 64:
                raise ValueError("INVALID_HIAGENT_CALL_BUDGET")
            max_calls = hiagent_max_calls
        if control_handoff_after is not None and (
            type(control_handoff_after) is not int or control_handoff_after < 1
        ):
            raise ValueError("INVALID_CONTROL_HANDOFF_BOUNDARY")
        self.control_handoff_after = control_handoff_after
        self.control_feedback_batch_size = control_feedback_batch_size
        if any(
            type(n) is not int or not 1 <= n <= 4096
            for n in (controller_output_tokens, summary_output_tokens)
        ):
            raise ValueError("INVALID_ROLE_OUTPUT_CAPS")
        self.controller_output_tokens = controller_output_tokens
        self.summary_output_tokens = summary_output_tokens
        self.om_observation_tokens = om_observation_tokens
        self.om_recent_events = om_recent_events
        super().__init__(*args, max_calls=max_calls, **kwargs)

    @staticmethod
    def name():
        return "milai-hiagent-terminal-transplant"

    def version(self):
        return TERMINAL_ADAPTER_VERSION

    def _solve(self, instruction, terminal, context):
        started = time.monotonic()
        root = self.run_root / "host" / self.logs_dir.parent.name
        root.mkdir(parents=True, exist_ok=True)
        rwc = self.arm in {"WORKSPACE_SIMPLE", "MILAI_RWC"}
        om = self.arm == "OM_SYNC_PORT"
        adaptive = self.arm in PROFILES
        caps = (
            {
                "actor": 4096,
                "maintenance": self.controller_output_tokens,
                "summary": self.summary_output_tokens,
            }
            if rwc
            else {"actor": 4096, "observer": 2048, "reflector": 2048}
            if om
            else {"actor": 4096, "maintenance": self.controller_output_tokens}
            if adaptive
            else {}
        )
        provider = Provider(
            self.run_root / "provider",
            deadline=started + self.task_timeout - 5,
            max_requests=self.wave_cap,
            output_cap=4096,
            allowed_output_caps=tuple(caps.values()) if caps else None,
        )
        session = None
        method_version = METHOD_VERSION
        stop = "GENERATION_LIMIT"
        context.n_input_tokens = context.n_output_tokens = 0
        handed_off = False

        def emit(event):
            append_event(root / "method-events.jsonl", event)

        def generate(request):
            mode = json.loads(request.messages[-1]["content"]).get("mode") if adaptive else None
            if self.stop_requested.is_set():
                raise TimeoutError("TRIAL_STOP_REQUESTED")
            body = {
                "messages": list(request.messages),
                "max_tokens": caps.get(request.kind, provider.output_cap),
                "model": MODEL,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "add_generation_prompt": True,
                "add_special_tokens": False,
                "temperature": 0,
                "top_p": 1,
                "seed": 213,
            }
            if request.kind == "actor" or request.json_output:
                body["response_format"] = {"type": "json_object"}
            if request.kind in {"observer", "reflector"}:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "om_observations",
                        "strict": True,
                        "schema": OM_OUTPUT_SCHEMA,
                    },
                }
            if adaptive and request.kind == "maintenance":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "adaptive_memory", "strict": True,
                                    "schema": ADAPTIVE_OUTPUT_SCHEMA},
                }
            # Summary is a distinct plain-text model call, not an optional actor field.
            # The Provider performs /tokenize and window checks without dropping history.
            emit(
                {
                    "event": "PROVIDER_ATTEMPT",
                    "kind": request.kind,
                    "mode": mode,
                    "segment": request.segment,
                    "body": body,
                }
            )
            before = {
                r["request_id"] for r in read_events(provider.ledger) if r["event"] == "RESERVED"
            }
            try:
                return provider.generate(
                    self.logs_dir.parent.name,
                    body,
                    expected_prompt_tokens=self.counts.wire(body["messages"]),
                )
            finally:
                rows = read_events(provider.ledger)
                reserved = [
                    r["request_id"]
                    for r in rows
                    if r["event"] == "RESERVED" and r["request_id"] not in before
                ]
                for row in rows:
                    if row["event"] == "SETTLED" and row["request_id"] in reserved:
                        context.n_input_tokens += row["usage"]["prompt_tokens"]
                        context.n_output_tokens += row["usage"]["completion_tokens"]
                        if adaptive:
                            session.host.record_usage(
                                row["usage"]["prompt_tokens"], row["usage"]["completion_tokens"],
                                row["seconds"],
                            )
                emit(
                    {
                        "event": "PROVIDER_ATTEMPT_END",
                        "kind": request.kind,
                        "mode": mode,
                        "segment": request.segment,
                        "request_ids": reserved,
                    }
                )

        try:
            model = provider.verify()
            control_options = (
                {"model_profile": f"{MODEL};thinking=false;seed=213;caps={caps}"}
                if rwc or om or adaptive
                else None
            )
            if rwc:
                control_options["feedback_batch_size"] = self.control_feedback_batch_size
            if om or adaptive:
                control_options.update(
                    {
                        "count_text": self.counts.text,
                        "count_messages": lambda messages: self.counts.wire(list(messages)),
                        "config": (AdaptiveMemoryConfig if adaptive else OMConfig)(
                            observation_tokens=self.om_observation_tokens,
                            recent_events=self.om_recent_events,
                            context_tokens=provider.context,
                            **({"maintenance_output_tokens": self.controller_output_tokens}
                               if adaptive else {}),
                        ),
                    }
                )
            session = HiAgentTerminalSession(
                instruction=instruction,
                binding=self.logs_dir.parent.name,
                root=root,
                terminal=terminal,
                generate=generate,
                emit=emit,
                max_calls=self.max_calls,
                method=self.arm,
                control_options=control_options,
            )
            method_version = session.host.snapshot()["method"]
            dump(
                root / "configuration.json",
                {
                    "kind": "RESEARCH_PROTOTYPE",
                    "method": method_version,
                    "arm": self.arm,
                    "terminal_adapter": self.version(),
                    "upstream_commit": UPSTREAM_COMMIT,
                    "model": model,
                    "task_timeout_sec": self.task_timeout,
                    "max_total_model_calls": self.max_calls,
                    "call_budget_includes": [
                        "actor",
                        "summary",
                        "maintenance",
                        "observer",
                        "reflector",
                        "retrieval_decisions",
                        "failed_requests",
                    ],
                    "om_config": asdict(control_options["config"]) if om else None,
                    "adaptive_config": asdict(control_options["config"]) if adaptive else None,
                    "summary_refresh": session.maintenance_mode,
                    "control_handoff_after": self.control_handoff_after,
                    "control_feedback_batch_size": (
                        self.control_feedback_batch_size if rwc else None
                    ),
                    "role_output_caps": caps or {"all": 4096},
                    "instruction": instruction,
                    "actor_policy": session.actor_policy,
                    "summary_policy": session.summary_policy,
                },
            )
            while not session.host.finished:
                if self.stop_requested.is_set() or time.monotonic() >= provider.deadline:
                    raise TimeoutError("NATIVE_TIME_LIMIT")
                try:
                    session.host.step()
                    if (
                        (self.arm == "CONTROL_0" or rwc or om or adaptive)
                        and self.control_handoff_after is not None
                        and not handed_off
                        and not session.host.finished
                        and len(session.tools.raw_receipts) >= self.control_handoff_after
                    ):
                        checkpoint = root / "handoff.json"
                        environment_id = self.logs_dir.parent.name
                        session.save_checkpoint(checkpoint, environment_id=environment_id)
                        # Fresh Host and source registry, same live isolated world.
                        # This is an explicit handoff, not process-crash recovery.
                        session = HiAgentTerminalSession(
                            instruction=instruction,
                            binding=environment_id,
                            root=root,
                            terminal=terminal,
                            generate=generate,
                            emit=emit,
                            max_calls=self.max_calls,
                            method=self.arm,
                            control_options=control_options,
                        )
                        session.restore_checkpoint(checkpoint, environment_id=environment_id)
                        handed_off = True
                finally:
                    dump(root / "memory.json", session.host.snapshot())
            stop = "FINAL_SUBMITTED"
        except HiAgentError as exc:
            stop = str(exc)
            # Exhausting a known call budget is an attempt outcome. Return normally
            # so Harbor can still verify the artifacts; do not turn it into an
            # infrastructure exception or run an unbudgeted final-answer call.
            if stop != "TOTAL_MODEL_CALL_LIMIT":
                raise
        except BaseException as exc:
            stop = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            state = accounting(read_events(provider.ledger))
            context.metadata = {
                "stop_reason": stop,
                "arm": self.arm,
                "method": method_version,
                "control_handoff_completed": handed_off,
                "delivery_status": (
                    getattr(session.host, "delivery_status", None) if session else None
                ),
                "host_evidence": str(root),
                "wave_accounting": state,
            }
            dump(
                root / "terminal.json",
                {
                    **context.model_dump(),
                    "agent_wall_sec": time.monotonic() - started,
                    "tool_sec": session.tools.tool_seconds if session else 0,
                    "call_attempts": dict(session.host.calls) if session else {},
                    "final": session.tools.final_text if session else None,
                },
            )
            provider.close()
