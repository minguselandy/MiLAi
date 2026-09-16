"""Zero-model public SDK checkpoint lifecycle in a run-owned Product instance.

Parent prepares PostgreSQL/API through public executables. Separate OS processes
save and resume the Host through public Working State only. No private Product
imports, database mutation, model HTTP, or shared-service changes occur here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hiagent_terminal_session import HiAgentTerminalSession
from milai_lab.methods.adaptive_memory import PROFILES, AdaptiveMemoryConfig
from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock
from run_product09_codex_lifecycle import (
    ALEMBIC_EXE,
    API_EXE,
    LAB,
    OPS_EXE,
    PRODUCT,
    RUNTIME,
    ProcessGroup,
    _clean_environment,
    _command,
    _free_port,
    _load_environment,
    _wait_http,
)
from workspace_checkpoint import CheckpointError, WorkingStateCheckpoint, atomic_json, canonical

SDK = PRODUCT / "integrations/python-client"
GOAL = "Retain the completed file action and inspect its original observation after handoff."


def append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def control(kind="ACT", refs=(), *, create=False, start=0):
    route = {"kind": kind, "refs": list(refs), "delivery": None}
    if kind == "RECALL":
        route.update(start=start, length=16000)
    return json.dumps(
        {
            "workspace_update": {
                "working_note": "A return point for an explicit handoff.",
                "put_cards": [
                    {"handle": None, "text": "Retain the completed action", "source_refs": []}
                ],
                "retire_cards": [],
            }
            if create
            else None,
            "frame": {
                "question": "What actually happened?",
                "intent": "Read the saved receipt",
                "selected_refs": [],
            },
            "dispatch": route,
        }
    )


class TracedClient:
    def __init__(self, client, path):
        self.client, self.path = client, path

    def __getattr__(self, name):
        def call(*args, **kwargs):
            append(self.path, {"event": "SDK_ATTEMPT", "method": name})
            try:
                result = getattr(self.client, name)(*args, **kwargs)
            except Exception as exc:
                append(
                    self.path,
                    {
                        "event": "SDK_ERROR",
                        "method": name,
                        "code": getattr(exc, "code", type(exc).__name__),
                    },
                )
                raise
            append(self.path, {"event": "SDK_RETURN", "method": name})
            return result

        return call


def child(root, phase):
    from milai_client import MilaiClient

    assert Path(importlib.util.find_spec("milai_client").origin).resolve() == (
        SDK / "src/milai_client/__init__.py"
    )
    binding = {
        "principal_binding_digest": hashlib.sha256(root.name.encode()).hexdigest(),
        "project_id": "rwc-checkpoint-development",
        "scope_type": "TASK",
        "scope_ref": root.name,
    }

    def events(value):
        append(root / f"{phase}-host-events.jsonl", value)

    with closing(
        MilaiClient(
            base_url=os.environ["MILAI_BASE_URL"],
            token=os.environ["MILAI_API_TOKEN"],
            max_retries=0,
        )
    ) as sdk:
        client = TracedClient(sdk, root / "sdk-events.jsonl")
        port = WorkingStateCheckpoint(
            client, binding=binding, journal=root / "checkpoint-journal.json", emit=events
        )
        world = root / "world"
        world.mkdir(exist_ok=True)

        def terminal(command, timeout):
            result = subprocess.run(  # noqa: S603 -- fixed scripted actions in an owned fixture
                ["/bin/bash", "-c", command],
                cwd=world,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        if phase == "save":
            absent = client.get_working_state(binding)
            assert absent["status"] == "ABSENT"
            client.update_working_state(
                {
                    **binding,
                    "state_id": None,
                    "expected_version": 0,
                    "payload": {"other_host": {"keep": "Unrelated state\n  exact"}},
                },
                operation_id="seed-other-namespace",
            )
            evidence = client.capture_evidence(
                {
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": "test://" + root.name,
                    "subject_id": "rwc-development",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "content": "Allowed observation",
                    "permission_snapshot": {
                        "readable": True,
                        "project_ids": [binding["project_id"]],
                    },
                },
                operation_id="capture-checkpoint-dependency",
            )
            port.evidence_refs = [evidence.evidence_id]
            command = (
                "printf 'once\\n' >> actions.txt\n"
                'python3 -c \'print("PUBLIC_UNSEEN_FEEDBACK" + "来源" * 12000)\''
            )
            replies = iter(
                [
                    control(create=True),
                    json.dumps({"action": "exec", "arguments": {"command": command}}),
                ]
            )
            session = HiAgentTerminalSession(
                instruction=GOAL,
                binding=root.name,
                root=root / "host-before",
                terminal=terminal,
                generate=lambda _: next(replies),
                method="MILAI_RWC",
                emit=events,
            )
            session.host.step()
            session.host.observe("NEW_USER_CONSTRAINT: retain the existing result.")
            artifact = session.checkpoint_data(environment_id=str(world))
            saved = session.save_public_checkpoint(
                port, environment_id=str(world), operation_id="save-host"
            )
            assert saved["version"] == 2
            assert saved["payload"]["other_host"]["keep"] == "Unrelated state\n  exact"
            atomic_json(
                root / "saved.json",
                {
                    "pid": os.getpid(),
                    "state_version": saved["version"],
                    "artifact_sha256": hashlib.sha256(canonical(artifact)).hexdigest(),
                    "evidence_id": evidence.evidence_id,
                    "raw_receipt_chars": len(artifact["receipts"]["H001"]),
                    "pending_pairs": len(session.host._pairs()) - session.host.maintained_pairs,
                    "pending_external": 1,
                    "world_actions": (world / "actions.txt").read_text(),
                },
            )
            return

        if phase == "resume":
            saved = json.loads((root / "saved.json").read_text())
            assert saved["pid"] != os.getpid()
            artifact = port.load()
            assert hashlib.sha256(canonical(artifact)).hexdigest() == saved["artifact_sha256"]
            requests = []
            replies = iter(
                [
                    control("RECALL", ["H001"], start=16000),
                    control(),
                    json.dumps(
                        {
                            "action": "read",
                            "arguments": {"ref": "H001", "start": 16000, "length": 16000},
                        }
                    ),
                    control(),
                    json.dumps({"action": "final", "arguments": {"text": "Restored and read."}}),
                    control("DELIVER"),
                ]
            )

            def generate(request):
                requests.append(request)
                return next(replies)

            session = HiAgentTerminalSession(
                instruction=GOAL,
                binding=root.name,
                root=root / "host-after",
                terminal=terminal,
                generate=generate,
                method="MILAI_RWC",
                emit=events,
            )
            session.restore_checkpoint_data(artifact, environment_id=str(world))
            while not session.host.finished:
                session.host.step()
            first = json.loads(requests[0].messages[-1]["content"])
            actor_input = json.loads(requests[2].messages[-1]["content"])
            assert first["reason"] == "resume" and first["new_event_ids"] == [0]
            assert first["external_observations"] == [
                "NEW_USER_CONSTRAINT: retain the existing result."
            ]
            assert "PUBLIC_UNSEEN_FEEDBACK" in first["materials"][0]["text"]
            assert actor_input["new_event_ids"] == [0]
            assert any(p["start"] == 16000 for p in actor_input["materials"])
            assert session.host.workspace.cards["card:1"].text == "Retain the completed action"
            assert (world / "actions.txt").read_text() == "once\n"
            assert sum(session.host.calls.values()) == 8
            session.save_public_checkpoint(
                port, environment_id=str(world), operation_id="save-resumed"
            )
            atomic_json(
                root / "resumed.json",
                {
                    "pid": os.getpid(),
                    "different_process": True,
                    "original_feedback_preserved": True,
                    "external_feedback_preserved": True,
                    "card_preserved": True,
                    "paginated_source_read": True,
                    "terminal_executions": 1,
                    "scripted_callbacks_total": 8,
                    "model_http_calls": 0,
                    "local_checkpoint_used": False,
                    "final": session.tools.final_text,
                },
            )
            return

        artifact = port.load()
        checks = {}
        new_replies = iter(
            [
                control(),
                json.dumps(
                    {
                        "action": "read",
                        "arguments": {"ref": "H001", "start": 16000, "length": 16000},
                    }
                ),
            ]
        )
        new_goal = HiAgentTerminalSession(
            instruction="New legitimate goal: inspect the prior result again without replay.",
            binding=root.name,
            root=root / "host-new-goal",
            terminal=terminal,
            generate=lambda _: next(new_replies),
            method="MILAI_RWC",
            emit=events,
        )
        new_goal.restore_checkpoint_data(artifact, environment_id=str(world))
        assert not new_goal.tools.finished and new_goal.tools.final_text is None
        assert not new_goal.host.finished and new_goal.host.goal_revision == 2
        new_goal.host.step()
        assert len(new_goal.tools.raw_receipts) == len(artifact["receipts"]) + 1
        assert (world / "actions.txt").read_text() == "once\n"
        checks["completed_checkpoint_new_goal_reopened"] = True
        checks["new_goal_scripted_callbacks"] = 2
        foreign = WorkingStateCheckpoint(
            client,
            binding={**binding, "scope_ref": root.name + "-other"},
            journal=root / "other-journal.json",
        )
        try:
            foreign.load()
        except CheckpointError as exc:
            checks["foreign_scope"] = str(exc)
        else:
            raise AssertionError("cross-scope read unexpectedly succeeded")

        class Race:
            def get_working_state(self, request):
                old = client.get_working_state(request)
                client.update_working_state(
                    {
                        **request,
                        "state_id": old["state_id"],
                        "expected_version": old["version"],
                        "payload": old["payload"],
                    },
                    operation_id="competing-writer",
                )
                return old

            def update_working_state(self, request, **kwargs):
                return client.update_working_state(request, **kwargs)

        race = WorkingStateCheckpoint(Race(), binding=binding, journal=root / "race-journal.json")
        try:
            race.save(artifact, operation_id="stale-cas")
        except Exception as exc:
            assert getattr(exc, "code", None) == "STALE_WORKING_STATE"
            checks["real_cas"] = exc.code
        else:
            raise AssertionError("stale CAS unexpectedly committed")

        class LostAcknowledgement:
            def get_working_state(self, request):
                return client.get_working_state(request)

            def update_working_state(self, request, **kwargs):
                client.update_working_state(request, **kwargs)
                raise TimeoutError("controlled loss after real public commit")

        journal = root / "lost-ack-journal.json"
        lost = WorkingStateCheckpoint(LostAcknowledgement(), binding=binding, journal=journal)
        try:
            lost.save(artifact, operation_id="lost-ack")
        except TimeoutError:
            pass
        fresh = WorkingStateCheckpoint(client, binding=binding, journal=journal)
        try:
            fresh.save(artifact, operation_id="must-not-send")
        except CheckpointError as exc:
            checks["unknown_write_blocks_new_send"] = str(exc)
        else:
            raise AssertionError("unknown write was retried")
        checks["real_commit_controlled_ack_loss"] = fresh.reconcile()["status"]
        assert fresh.load() == artifact
        head = client.get_working_state(binding)
        evidence_id = json.loads((root / "saved.json").read_text())["evidence_id"]
        assert head["payload"]["milai_rwc"]["evidence_refs"] == [evidence_id]
        client.revoke_evidence(
            evidence_id,
            {"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
            operation_id="revoke-owned-development-evidence",
        )
        withheld = client.get_working_state(binding)
        assert withheld["payload_withheld"] and not withheld["payload"]
        for operation in ("load", "save"):
            try:
                if operation == "load":
                    fresh.load()
                else:
                    fresh.save(artifact, operation_id="must-not-overwrite-withheld")
            except CheckpointError as exc:
                assert str(exc) == "CHECKPOINT_PAYLOAD_WITHHELD"
                checks["revoked_" + operation] = str(exc)
            else:
                raise AssertionError("revoked dependency remained usable")
        atomic_json(root / "public-contract-checks.json", checks)


def child_om(root, phase):
    """One OM handoff on unchanged public transport; scripted models, real SDK."""
    from milai_client import MilaiClient

    from milai_lab.methods.observational_memory import OMConfig

    binding = {
        "principal_binding_digest": hashlib.sha256(root.name.encode()).hexdigest(),
        "project_id": "om-checkpoint-development",
        "scope_type": "TASK",
        "scope_ref": root.name,
    }
    world = root / "world"
    world.mkdir(exist_ok=True)
    requests = []
    actions = iter(
        [
            {
                "action": "exec",
                "arguments": {
                    "command": "printf 'once\\n' >> actions.txt\n"
                    'python3 -c \'print("PUBLIC_OM_FEEDBACK" + "来源" * 12000)\''
                },
            },
            {"action": "retrieve", "arguments": {"ref": "H001", "start": 16000}},
            {"action": "retrieve", "arguments": {"ref": "H001", "start": 0}},
        ]
        if phase == "save"
        else [
            {"action": "read", "arguments": {"ref": "H001", "start": 16000, "length": 8000}},
            {
                "action": "final",
                "arguments": {"text": "Restored observations and original receipt."},
            },
        ]
    )

    def generate(request):
        requests.append(request)
        if request.kind == "actor":
            return json.dumps(next(actions))
        return json.dumps(
            {
                "observations": "File action happened once; PUBLIC_OM_FEEDBACK was observed.",
                "continuationHints": {
                    "currentTask": "Inspect preserved result",
                    "suggestedResponse": "Read original receipt",
                },
            }
        )

    def events(value):
        append(root / f"{phase}-host-events.jsonl", value)

    def terminal(command, timeout):
        result = subprocess.run(  # noqa: S603 -- scripted actions in an owned fixture
            ["/bin/bash", "-c", command],
            cwd=world,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "return_code": result.returncode}

    def make(goal=GOAL):
        return HiAgentTerminalSession(
            instruction=goal,
            binding=root.name,
            root=root / ("om-" + phase),
            terminal=terminal,
            generate=generate,
            method="OM_SYNC_PORT",
            emit=events,
            control_options={
                "count_text": len,
                "count_messages": lambda m: len(json.dumps(m, ensure_ascii=False)),
                "config": OMConfig(observation_tokens=1, recent_events=1),
                "model_profile": "scripted-public-lifecycle-no-provider-char-count",
            },
        )

    with closing(
        MilaiClient(
            base_url=os.environ["MILAI_BASE_URL"],
            token=os.environ["MILAI_API_TOKEN"],
            max_retries=0,
        )
    ) as sdk:
        client = TracedClient(sdk, root / "sdk-events.jsonl")
        port = WorkingStateCheckpoint(
            client, binding=binding, journal=root / "checkpoint-journal.json", emit=events
        )
        session = make()
        if phase == "save":
            for _ in range(3):
                session.host.step()
            session.host.observe("NEW_USER_CONSTRAINT: preserve the existing file action.")
            assert any(
                r["ref"] == "H001"
                for g in session.host.observation_groups
                for r in g["source_ranges"]
            )
            artifact = session.checkpoint_data(environment_id=str(world))
            saved = session.save_public_checkpoint(
                port, environment_id=str(world), operation_id="save-om-host"
            )
            atomic_json(
                root / "saved.json",
                {
                    "pid": os.getpid(),
                    "version": saved["version"],
                    "artifact_sha256": hashlib.sha256(canonical(artifact)).hexdigest(),
                    "raw_receipt_chars": len(artifact["receipts"]["H001"]),
                    "observations_saved": len(session.host.observation_groups),
                    "scripted_callbacks": len(requests),
                },
            )
        else:
            saved = json.loads((root / "saved.json").read_text())
            assert saved["pid"] != os.getpid()
            artifact = port.load()
            assert hashlib.sha256(canonical(artifact)).hexdigest() == saved["artifact_sha256"]
            session.restore_checkpoint_data(artifact, environment_id=str(world))
            assert not requests
            assert (
                session.host.observation_groups == artifact["host"]["state"]["observation_groups"]
            )
            assert session.host.continuation_hints["currentTask"] == "Inspect preserved result"
            assert "PUBLIC_OM_FEEDBACK" in session.host._retrieve({"ref": "H001", "length": 1000})
            while not session.host.finished:
                session.host.step()
            actor_input = json.loads(
                next(r for r in requests if r.kind == "actor").messages[-1]["content"]
            )
            assert "NEW_USER_CONSTRAINT" in json.dumps(actor_input["raw_tail"])
            assert len(session.tools.raw_receipts["H001"]) > 16000
            session.save_public_checkpoint(
                port, environment_id=str(world), operation_id="save-om-final"
            )
            complete = port.load()
            revised = make("New real goal: inspect the prior action without replay.")
            revised.restore_checkpoint_data(complete, environment_id=str(world))
            assert not revised.host.finished and revised.tools.final_text is None
            assert revised.host.continuation_hints == {"currentTask": "", "suggestedResponse": ""}
            assert revised.host.goal_revision == 2
            atomic_json(
                root / "resumed.json",
                {
                    "pid": os.getpid(),
                    "different_process": True,
                    "method": "OM_SYNC_PORT",
                    "observations_and_hints_preserved": True,
                    "original_source_range_read": True,
                    "new_goal_clears_final_and_hints": True,
                    "restore_model_calls": 0,
                    "scripted_callbacks_total": sum(session.host.calls.values()),
                    "model_http_calls": 0,
                    "terminal_executions": 1,
                    "local_checkpoint_used": False,
                    "final": session.tools.final_text,
                },
            )
        assert (world / "actions.txt").read_text() == "once\n"


def child_adaptive(root, phase, method):
    """One complete adaptive handoff; real terminal and SDK, controlled cognition."""
    from milai_client import MilaiClient

    assert Path(importlib.util.find_spec("milai_client").origin).resolve() == (
        SDK / "src/milai_client/__init__.py"
    )
    world = root / "world"
    world.mkdir(exist_ok=True)
    requests = []
    outputs = iter([
        {"action": "exec", "arguments": {
            "command": "printf 'once\\n' >> actions.txt\n"
            'python3 -c \'print("PUBLIC_ADAPTIVE_FEEDBACK" + "来源" * 12000)\'',
        }},
        {"observations": "Retained the action and its original receipt.",
         "workspace_update": {"working_note": "Continue from the preserved action.",
                              "put_cards": [{"text": "Deferred route requires reassessment",
                                             "source_refs": ["H001"]}]}},
        {"action": "maintain", "arguments": {"reason": "Reassess the retained work",
                                               "refs": ["obs:1", "card:1"]}},
        {"dispatch": {"kind": "RECALL", "refs": ["H001"], "start": 16000, "length": 4000}},
    ] if phase == "save" else [
        {"group_updates": [{"handle": "obs:1", "text": "Revised using the preserved return"}],
         "workspace_update": {"put_cards": [{"handle": "card:1", "text": "Reassessed route"}]},
         "frame": {"selected_refs": ["obs:1", "card:1"]}},
        {"action": "read", "arguments": {"ref": "H001", "start": 16000, "length": 4000}},
        {},
        {"action": "final", "arguments": {"text": "Preserved action and revised memory resumed."}},
        {"dispatch": {"kind": "DELIVER"}},
    ])

    def generate(request):
        requests.append(request)
        return json.dumps(next(outputs), ensure_ascii=False)

    def events(value):
        append(root / f"{phase}-host-events.jsonl", value)

    def terminal(command, timeout):
        result = subprocess.run(  # noqa: S603 -- fixed command in a run-owned fixture
            ["/bin/bash", "-c", command], cwd=world, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "return_code": result.returncode}

    def make(goal=GOAL):
        return HiAgentTerminalSession(
            instruction=goal, binding=root.name, root=root / ("adaptive-" + phase),
            terminal=terminal, generate=generate, method=method, emit=events, max_calls=32,
            control_options={"count_text": len,
                "count_messages": lambda m: len(json.dumps(m, ensure_ascii=False)),
                "config": AdaptiveMemoryConfig(observation_tokens=1, recent_events=1),
                "model_profile": "scripted-public-lifecycle-no-provider-char-count"},
        )

    binding = {"principal_binding_digest": hashlib.sha256(root.name.encode()).hexdigest(),
               "project_id": "adaptive-checkpoint-development", "scope_type": "TASK",
               "scope_ref": root.name}
    with closing(MilaiClient(base_url=os.environ["MILAI_BASE_URL"],
                             token=os.environ["MILAI_API_TOKEN"], max_retries=0)) as sdk:
        client = TracedClient(sdk, root / "sdk-events.jsonl")
        port = WorkingStateCheckpoint(client, binding=binding,
                                       journal=root / "checkpoint-journal.json", emit=events)
        session = make()
        if phase == "save":
            for _ in range(3):
                session.host.step()
            session.host.observe("NEW_USER_CONSTRAINT: keep the completed file action.")
            assert session.host.pending_control == {"mode": "REVISE", "recalls": 1}
            artifact = session.checkpoint_data(environment_id=str(world))
            saved = session.save_public_checkpoint(
                port, environment_id=str(world), operation_id="save-adaptive-host",
            )
            atomic_json(root / "saved.json", {
                "pid": os.getpid(), "version": saved["version"],
                "artifact_sha256": hashlib.sha256(canonical(artifact)).hexdigest(),
                "actor_view_sha256": hashlib.sha256(
                    canonical(session.host.actor_messages())).hexdigest(),
                "scripted_callbacks": len(requests), "calls": session.host.calls,
                "pending_control": session.host.pending_control,
                "raw_receipt_chars": len(artifact["receipts"]["H001"]),
            })
        else:
            saved = json.loads((root / "saved.json").read_text())
            assert saved["pid"] != os.getpid()
            artifact = port.load()
            assert hashlib.sha256(canonical(artifact)).hexdigest() == saved["artifact_sha256"]
            session.restore_checkpoint_data(artifact, environment_id=str(world))
            assert not requests and session.host.calls == saved["calls"]
            assert hashlib.sha256(canonical(session.host.actor_messages())).hexdigest() == (
                saved["actor_view_sha256"]
            )
            assert session.host.pending_control == saved["pending_control"]
            while not session.host.finished:
                session.host.step()
            first = json.loads(requests[0].messages[-1]["content"])
            assert first["mode"] == "REVISE" and "NEW_USER_CONSTRAINT" in json.dumps(first)
            assert any(r["start"] == 16000 for r in first["memory"]["recalls"])
            assert session.host.observation_groups[0]["revision"] == 2
            assert session.host.workspace.cards["card:1"].revision == 2
            assert session.host.delivery_status == "REVIEWED"
            session.save_public_checkpoint(port, environment_id=str(world),
                                            operation_id="save-adaptive-final")
            complete = port.load()
            revised = make("New goal: inspect the prior result without replay.")
            revised.restore_checkpoint_data(complete, environment_id=str(world))
            assert not revised.tools.finished and revised.tools.final_text is None
            assert revised.host.review_count == 0 and revised.host.goal_revision == 2
            assert revised.host.calls == session.host.calls
            atomic_json(root / "resumed.json", {
                "pid": os.getpid(), "different_process": True, "method": method,
                "pending_recall_and_fresh_feedback_preserved": True,
                "current_observations_cards_frame_preserved": True,
                "original_source_range_read": True, "restore_model_calls": 0,
                "new_goal_clears_frame_draft_and_review_allowance": True,
                "scripted_callbacks_total": sum(session.host.calls.values()),
                "calls": session.host.calls, "mode_calls": session.host.mode_calls,
                "model_http_calls": 0, "terminal_executions": 1,
                "local_checkpoint_used": False, "final": session.tools.final_text,
            })
        assert (world / "actions.txt").read_text() == "once\n"


def run(root, lock, *, reuse_prepared=False, method="MILAI_RWC", child_script=None,
        child_phases=None, child_interpreter=None, child_arguments=()):
    if reuse_prepared:
        # Reuse is only for setup failures before the first SDK request. It is
        # never a replay of an uncertain checkpoint or an executed world action.
        if not (root / "runtime.env").is_file() or (root / "sdk-events.jsonl").exists():
            raise RuntimeError("PREPARED_REUSE_REQUIRES_NO_SDK_ATTEMPTS")
        for name in ("failure.json", "save.log"):
            if (root / name).exists():
                (root / name).rename(root / ("setup-attempt-" + name))
    else:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    verification = verify_product_lock(load_product_lock(lock), PRODUCT).to_dict()
    atomic_json(root / "product-pin.json", verification)
    if not verification["valid"]:
        raise RuntimeError("PRODUCT_PIN_MISMATCH")
    env_file = root / "runtime.env"
    if not reuse_prepared:
        _command(
            [
                str(OPS_EXE),
                "init",
                "--env-file",
                str(env_file),
                "--blob-root",
                str(root / "blobs"),
                "--postgres-port",
                str(_free_port()),
                "--api-port",
                str(_free_port()),
            ],
            cwd=RUNTIME,
        )
    environment = _clean_environment(_load_environment(env_file))
    override = root / "bridge.yaml"
    override.write_text("services:\n  postgres:\n    network_mode: bridge\n")
    compose = [
        "docker",
        "compose",
        "--project-name",
        "rwc-" + hashlib.sha256(str(root).encode()).hexdigest()[:16] + "-pg",
        "--env-file",
        str(env_file),
        "--file",
        str(RUNTIME / "compose.yaml"),
        "--file",
        str(override),
    ]
    atomic_json(root / "compose-command.json", compose)
    processes = ProcessGroup(root)
    try:
        up = _command([*compose, "up", "--detach", "--wait", "postgres"], cwd=RUNTIME, timeout=120)
        (root / "postgres-start.log").write_text(up.stdout + up.stderr)
        migrated = _command(
            [str(ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
            cwd=RUNTIME,
            env=environment,
            timeout=180,
        )
        (root / "migration.log").write_text(migrated.stdout + migrated.stderr)
        api = processes.start("api", [str(API_EXE)], cwd=RUNTIME, env=environment)
        _wait_http(environment["MILAI_BASE_URL"] + "/health/ready", api)
        environment["PYTHONPATH"] = os.pathsep.join([str(LAB / "src"), str(LAB / "tools")])
        phases = child_phases or (
            ("save", "resume") if method == "OM_SYNC_PORT" or method in PROFILES
            else ("save", "resume", "probe")
        )
        interpreter = SDK / ".venv/bin/python"
        if method in PROFILES or child_interpreter is not None:
            # The Lab owns the Host's schema dependency; use the unchanged public
            # SDK source through its normal package entry point in the Lab runtime.
            interpreter = child_interpreter or LAB / ".venv/bin/python"
            environment["PYTHONPATH"] += os.pathsep + str(SDK / "src")
        for phase in phases:
            result = _command(
                [
                    str(interpreter),
                    str(child_script or Path(__file__).resolve()),
                    "--root",
                    str(root),
                    "--phase",
                    phase,
                    "--method",
                    method,
                    *child_arguments,
                ],
                cwd=LAB,
                env=environment,
                check=False,
            )
            (root / f"{phase}.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"PUBLIC_CHECKPOINT_PHASE_FAILED: {phase}; see {phase}.log")
        atomic_json(
            root / "result.json",
            {
                "status": "PASS",
                "method": method,
                "model_http_calls": 0,
                "transport": "PUBLIC_SDK_HTTP",
                "fresh_os_process": True,
                "product_pin_valid": True,
                "artifact_sha256": hashlib.sha256(
                    Path(child_script or __file__).read_bytes()
                ).hexdigest(),
            },
        )
    except BaseException as exc:
        atomic_json(root / "failure.json", {"error_type": type(exc).__name__, "detail": str(exc)})
        raise
    finally:
        processes.stop()
        stopped = _command([*compose, "down"], cwd=RUNTIME, check=False)
        (root / "cleanup.log").write_text(stopped.stdout + stopped.stderr)
        atomic_json(
            root / "cleanup.json",
            {
                "owned_processes_stopped": True,
                "compose_down_returncode": stopped.returncode,
                "owned_volume_retained": True,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--lock", type=Path, default=LAB / "data/locks/workspace-rwc-repair-product.lock.json"
    )
    parser.add_argument("--phase", choices=("save", "resume", "probe"))
    parser.add_argument("--reuse-prepared", action="store_true")
    parser.add_argument("--method", choices=("MILAI_RWC", "OM_SYNC_PORT", *sorted(PROFILES)),
                        default="MILAI_RWC")
    args = parser.parse_args()
    if args.phase:
        if args.method in PROFILES:
            child_adaptive(args.root.resolve(), args.phase, args.method)
        else:
            (child_om if args.method == "OM_SYNC_PORT" else child)(args.root.resolve(), args.phase)
    else:
        run(
            args.root.resolve(),
            args.lock.resolve(),
            reuse_prepared=args.reuse_prepared,
            method=args.method,
        )


if __name__ == "__main__":
    main()
