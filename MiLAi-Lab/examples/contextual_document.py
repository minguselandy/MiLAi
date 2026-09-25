"""Real document tools; deterministic wiring or a persistent vLLM conversation CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast

from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    TaskTurn,
    accept_observation,
    dispatch_action,
    run_task_session,
    task_runtime,
)
from milai_lab.runners.contextual_session import HostSession


class DocumentWorkspace:
    """Three tools for one real document in the caller's isolated workspace."""

    def __init__(self, directory: Path, required_sections: tuple[str, ...]) -> None:
        self.path = directory / "document.md"
        self.required_sections = required_sections

    def read(self) -> dict[str, str]:
        body = self.path.read_text()
        return {"content": body, "version": hashlib.sha256(body.encode()).hexdigest()}

    def execute(self, name: str, args: dict[str, Any], call_id: str) -> BusinessToolResult:
        current = self.read()
        status: Literal["succeeded", "failed", "unknown"] = "succeeded"
        if name == "document_read":
            output: dict[str, Any] = current
        elif name == "document_write":
            if args["expected_version"] != current["version"]:
                status = "failed"
                output = {"error": "VERSION_CONFLICT", "version": current["version"]}
            else:
                self.path.write_text(args["content"])
                output = {"version": self.read()["version"], "written": True}
        elif name == "document_check":
            missing = [
                heading
                for heading in self.required_sections
                if heading not in current["content"].splitlines()
            ]
            output = {
                "passed": not missing,
                "missing_sections": missing,
                "version": current["version"],
            }
        else:
            raise ValueError("UNKNOWN_DOCUMENT_TOOL")
        return BusinessToolResult(call_id, status, output)

    def tools(self) -> dict[str, BusinessTool]:
        descriptions = {
            "document_read": "Read the current document and its exact content version.",
            "document_write": "Replace the document only if expected_version is current.",
            "document_check": "Check the real document against required sections.",
        }
        result = {}
        for name, description in descriptions.items():
            properties = (
                {"content": {"type": "string"}, "expected_version": {"type": "string"}}
                if name == "document_write"
                else {}
            )
            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                        "additionalProperties": False,
                    },
                },
            }
            result[name] = BusinessTool(schema, partial(self.execute, name))
        return result


def wiring_example(directory: Path) -> dict[str, Any]:
    """Programmed operations prove wiring and real effects, not autonomous model quality."""
    directory.mkdir(parents=True, exist_ok=True)
    workspace = DocumentWorkspace(directory, ("# Summary", "# Limitations"))
    workspace.path.write_text("# Summary\nDraft.\n")
    memory = ContextualMemory(
        "document-owner",
        host_id="deterministic-wiring",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    memory.start_task("edit", "Prepare this document")
    session = HostSession("edit", memory)
    outcomes: list[dict[str, Any]] = []

    def action(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        receipt = dispatch_action(
            name,
            arguments,
            memory_dispatch=memory.dispatch,
            business_tools=workspace.tools(),
            call_id=f"edit:{len(outcomes)}",
        )
        assert isinstance(receipt, BusinessToolResult)
        acquired = accept_observation(
            memory,
            session,
            Observation(
                receipt.call_id,
                json.dumps(receipt.output),
                "tool",
                name,
                session_id="edit",
                actor_ref=f"tool:{name}",
            ),
        )
        outcomes.append(
            {
                "tool": name,
                "status": receipt.status,
                "output": receipt.output,
                "source_ref": acquired["source_ref"],
            }
        )
        return cast(dict[str, Any], receipt.output)

    initial = action("document_read", {})
    action(
        "document_write",
        {"content": "# Summary\nEdited.\n", "expected_version": initial["version"]},
    )
    check = action("document_check", {})
    assert check["passed"] is False
    evidence = outcomes[-1]["source_ref"]
    old = memory.save(
        op="CREATE",
        about_ref="unresolved",
        certainty="explicit",
        content="The edited document failed its required-sections check.",
        subject="document validation",
        context="this document template",
        source_refs=[evidence],
        dependencies=[],
    )["record"]["ref"]
    assert session.material_view is not None
    session.append_material(session.material_view.project(memory.read(old, _visible=False)))
    memory.advance_turn("Apply the document feedback")
    feedback = accept_observation(
        memory,
        session,
        Observation(
            "feedback-1",
            "Keep the Summary and add a Limitations section before delivery.",
            "user",
            "document-feedback",
            session_id="edit",
            actor_ref="current_user",
        ),
    )
    new = memory.save(
        op="REVISE",
        target_ref=old,
        about_ref="unresolved",
        certainty="explicit",
        subject="document validation",
        context="this document template",
        content="For this document, keep Summary and add Limitations before delivery; "
        "the earlier check failed because Limitations was missing.",
        source_refs=[evidence, feedback["source_ref"]],
        dependencies=[],
    )["record"]["ref"]
    session.close()
    memory.start_task("deliver", "Finish the document using its current requirements")
    next_session = HostSession("deliver", memory)
    result = memory.search(query="document validation")
    next_session.refresh_visibility()
    assert next_session.material_view is not None
    next_session.append_material(next_session.material_view.project(result))
    assert new in memory.seen and old not in memory.seen
    current = workspace.read()
    receipt = workspace.execute(
        "document_write",
        {
            "content": current["content"] + "\n# Limitations\nPending external review.\n",
            "expected_version": current["version"],
        },
        "deliver:write",
    )
    final = workspace.execute("document_check", {}, "deliver:check")
    assert receipt.status == "succeeded" and final.output["passed"] is True
    return {
        "kind": "DETERMINISTIC_WIRING_NOT_MODEL_EVALUATION",
        "old_ref": old,
        "current_ref": new,
        "acquired_source": feedback["source_ref"],
        "later_delivered": new in memory.seen,
        "initial_check": check,
        "final_check": final.output,
        "model_requests": 0,
        "business_calls": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Use configured vLLM and durable memory"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/contextual-memory-v8-off.json")
    )
    parser.add_argument("--workspace", type=Path)
    parser.add_argument(
        "--state", type=Path, help="Persistent bank directory, shared across sessions"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--owner", default="document-owner")
    parser.add_argument("--session")
    parser.add_argument("--turn")
    parser.add_argument("--request-file", type=Path)
    parser.add_argument("--required-section", action="append", default=[])
    parser.add_argument("--keep-session", action="store_true")
    args = parser.parse_args()
    if not args.live:
        with TemporaryDirectory(prefix="milai-document-") as temporary:
            print(json.dumps(wiring_example(Path(temporary)), ensure_ascii=False, indent=2))
        return
    if not all(
        (args.workspace, args.state, args.output, args.session, args.turn, args.request_file)
    ):
        parser.error(
            "--live needs --workspace, --state, --output, --session, --turn, --request-file"
        )
    from milai_lab.harness.contextual_artifacts import write_json

    args.workspace.mkdir(parents=True, exist_ok=True)
    workspace = DocumentWorkspace(args.workspace, tuple(args.required_section))
    if not workspace.path.exists():
        workspace.path.write_text("")
    question = args.request_file.read_text()
    config = json.loads(args.config.read_text())
    with task_runtime(
        config,
        user_id=args.owner,
        output=args.output,
        state_path=args.state,
        business_tools=workspace.tools(),
    ) as (memory, host, runtime):
        session, results = run_task_session(
            [
                TaskTurn(
                    args.turn,
                    question,
                    observations=(
                        Observation(
                            args.turn,
                            question,
                            "user",
                            "document-request",
                            session_id=args.session,
                            actor_ref="current_user",
                        ),
                    ),
                )
            ],
            memory=memory,
            host=host,
            session_id=args.session,
            close=not args.keep_session,
        )
        result = results[-1]
        report = {
            "kind": "LIVE_DOCUMENT_FUNCTIONAL_CHECK_NOT_BENCHMARK",
            "session_id": args.session,
            "turn_id": args.turn,
            "host": asdict(result),
            "session_closed": session.closed,
            "document": workspace.read(),
            "memory_checkpoint": memory.checkpoint(),
            "runtime": runtime,
        }
        key = hashlib.sha256(json.dumps([args.session, args.turn]).encode()).hexdigest()[:16]
        write_json(args.output / f"turn-{key}.json", report)
        print(
            json.dumps(
                {
                    "status": result.status,
                    "answer": result.answer,
                    "maintenance": result.maintenance,
                    "artifact": str(args.output / f"turn-{key}.json"),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
