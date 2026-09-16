"""Harbor 0.23.0 public external agent; all terminal actions use BaseEnvironment.

Install Harbor in the external experiment environment, not the Lab dependency set.
Provider transcripts are host-only; only Harbor's trial-owned log mount is shared.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
from pathlib import Path

from harbor.agents.base import BaseAgent

from run_workspace_task_a import Counts
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import MODEL
from workspace_policy_host import Generation, load_policy
from workspace_task_provider import Provider
from workspace_terminal_session import TerminalSession, dump


class WorkspaceAgent(BaseAgent):
    def __init__(self, *args, arm="NOTE", run_root, wave_cap=192, task_timeout=900,
                 smoke=False, max_calls=64, **kwargs):
        if type(max_calls) is not int or not 1 <= max_calls <= 768:
            raise ValueError("INVALID_TOTAL_CALL_BUDGET")
        super().__init__(*args, **kwargs)
        self.arm, self.run_root = arm, Path(run_root)
        self.wave_cap, self.task_timeout, self.smoke = wave_cap, task_timeout, smoke
        self.max_calls = max_calls
        self.stop_requested = threading.Event()

    @staticmethod
    def name():
        return "milai-workspace-native"

    def version(self):
        return "0.1.1-harbor-0.23.0"

    async def setup(self, environment):
        # No agent package, host credentials or model client enters the container.
        await asyncio.to_thread(self._audit_container, environment.session_id)
        if not self.smoke:
            self.counts = await asyncio.to_thread(Counts)

    def _audit_container(self, session_id):
        # Trusted-host inspection only; no model text enters these arguments.
        ids = subprocess.run(  # noqa: S603
            ["/usr/bin/docker", "ps", "-q", "--filter",
             f"label=com.docker.compose.project={session_id}"],
            capture_output=True, text=True, check=True, timeout=10).stdout.split()
        if not ids:
            raise ValueError("NATIVE_CONTAINER_IDENTITY_UNCONFIRMED")
        containers = json.loads(subprocess.run(  # noqa: S603
            ["/usr/bin/docker", "inspect", *ids], capture_output=True,
            text=True, check=True, timeout=10).stdout)
        evidence = []
        allowed = [self.logs_dir.resolve(), (self.logs_dir.parent / "verifier").resolve(),
                   (self.logs_dir.parent / "artifacts").resolve()]
        for item in containers:
            cfg = item["HostConfig"]
            if (cfg["Privileged"] or cfg["NetworkMode"] == "host" or cfg.get("DeviceRequests")
                    or cfg.get("Devices") or cfg.get("PortBindings")):
                raise ValueError("UNAUTHORIZED_CONTAINER_CAPABILITY")
            for mount in item["Mounts"]:
                source = Path(mount["Source"]).resolve()
                if not any(source == base or source.is_relative_to(base) for base in allowed):
                    raise ValueError("UNAUTHORIZED_HOST_MOUNT")
            evidence.append({"id": item["Id"], "image": item["Image"],
                             "host_config": cfg, "mounts": item["Mounts"]})
        dump(self.run_root / "isolation" / f"{self.logs_dir.parent.name}.json", evidence)

    async def run(self, instruction, environment, context):
        if self.smoke:
            result = await environment.exec(command="pwd", timeout_sec=10)
            dump(self.logs_dir / "native-smoke.json", result.model_dump())
            context.metadata = {"kind": "LEGAL_COMMAND_ONLY_NO_MODEL", "command": "pwd"}
            context.n_input_tokens = context.n_output_tokens = 0
            return
        loop = asyncio.get_running_loop()

        def terminal(command, timeout):
            if self.stop_requested.is_set():
                raise TimeoutError("TRIAL_STOP_REQUESTED")
            future = asyncio.run_coroutine_threadsafe(
                environment.exec(command=command, timeout_sec=timeout), loop)
            try:
                return future.result(timeout=timeout + 5).model_dump()
            except BaseException:
                future.cancel()
                raise

        worker = asyncio.create_task(asyncio.to_thread(
            self._solve, instruction, terminal, context))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            self.stop_requested.set()
            # Settle an in-flight HTTP request before returning to the scheduler.
            await worker
            raise

    def _solve(self, instruction, terminal, context):
        started = time.monotonic()
        # Keep model accounting outside the container-visible agent log directory.
        root = self.run_root / "host" / self.logs_dir.parent.name
        provider = Provider(self.run_root / "provider", deadline=started + self.task_timeout - 5,
                            max_requests=self.wave_cap, output_cap=4096)
        session = None
        stop = "GENERATION_LIMIT"
        try:
            model = provider.verify()
            candidates = {"REGULATED_0": "regulated_0.txt", "REGULATED_1": "regulated_1.txt",
                          "REGULATED_2": "regulated_2.txt"}
            policy = (Path(__file__).resolve().parents[1] / "configs/policies/workspace" /
                      candidates[self.arm]).read_text() if self.arm in candidates else load_policy(
                          self.arm)
            session = TerminalSession(instruction=instruction, policy=policy,
                                      binding=self.logs_dir.parent.name, root=root,
                                      counts=self.counts, context=model["max_model_len"],
                                      terminal=terminal)
            dump(root / "configuration.json", {"model": model, "policy": policy,
                 "arm": self.arm, "task_timeout_sec": self.task_timeout,
                 "max_generations": self.max_calls,
                 "instruction": instruction, "agent_version": self.version()})
            context.n_input_tokens = context.n_output_tokens = 0

            def generate(request):
                if self.stop_requested.is_set():
                    raise TimeoutError("TRIAL_STOP_REQUESTED")
                body = {**request, "model": MODEL, "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "add_generation_prompt": True, "add_special_tokens": False,
                        "temperature": 0, "top_p": 1, "seed": 213,
                        "response_format": {"type": "json_object"}}
                append_event(root / "events.jsonl", {"event": "BEFORE_SEND", "body": body})
                raw = provider.generate(self.logs_dir.parent.name, body,
                                        expected_prompt_tokens=self.counts.wire(body["messages"]))
                usage = read_events(provider.ledger)[-1]["usage"]
                context.n_input_tokens += usage["prompt_tokens"]
                context.n_output_tokens += usage["completion_tokens"]
                return Generation(raw, "MODEL", True, usage)

            for _ in range(self.max_calls):
                if self.stop_requested.is_set() or time.monotonic() >= provider.deadline:
                    stop = "NATIVE_TIME_LIMIT"
                    break
                try:
                    session.host.step(new=(), generate=generate, dispatch=session.dispatch)
                finally:
                    dump(root / "rows.json", session.host.rows)
                if session.finished:
                    stop = "FINAL_SUBMITTED"
                    break
        except BaseException as exc:
            stop = type(exc).__name__
            raise
        finally:
            state = accounting(read_events(provider.ledger))
            context.metadata = {"stop_reason": stop, "arm": self.arm,
                                "host_evidence": str(root), "wave_accounting": state}
            dump(root / "terminal.json", {**context.model_dump(),
                 "agent_wall_sec": time.monotonic() - started,
                 "tool_sec": session.tool_seconds if session else 0,
                 "host_attempts": len(session.host.rows) if session else 0,
                 "generations": sum(row["delivery"] == "MODEL_INPUT_SENT"
                                    for row in session.host.rows) if session else 0,
                 "final": session.final_text if session else None})
            provider.close()
