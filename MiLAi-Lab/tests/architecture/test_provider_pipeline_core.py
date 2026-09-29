"""Core-owned generic hook contracts and the precise provider dependency leaves."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from milai_lab.providers.request_pipeline import ChatRequest, PreparedRequest, ResponseEvent

LAB = Path(__file__).resolve().parents[2]


def test_pipeline_data_keeps_opaque_attachment_and_extra_wire_fields() -> None:
    opaque = object()
    wire = [{"role": "user", "content": "actual", "unknown": {"keep": True}}]
    request = ChatRequest(wire, [], [], False, {"extra": "unchanged"})
    prepared = PreparedRequest(request.messages, request.tools, attachment=opaque)
    event = ResponseEvent("schema_outcome", prepared, {"unknown": True}, "response")
    assert prepared.attachment is opaque
    assert event.request.messages is wire
    assert event.receipt == {"unknown": True}
    assert event.accept_schema_failure is False


def test_pipeline_and_embedding_math_import_without_optional_sdk() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        "import milai_lab.providers.request_pipeline; "
        "from milai_lab.memory.embeddings import normalized; "
        "assert normalized([3., 4.], 2) == [.6, .8]; "
        "assert not any(name.startswith(('langchain', 'langgraph', 'langmem', "
        "'mem0', 'SimpleMem', 'simplemem', 'tokenizers', 'psycopg', 'transformers')) "
        "for name in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generic_provider_has_no_method_policy_or_attachment_inspection() -> None:
    for name in ("chat_bridge.py", "request_pipeline.py", "contextual_embeddings.py"):
        path = LAB / "src/milai_lab/providers" / name
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0
                module = node.module or ""
                assert (
                    not module.startswith("milai_lab.")
                    or module.startswith(
                        (
                            "milai_lab.contracts.",
                            "milai_lab.harness.",
                            "milai_lab.providers.",
                        )
                    )
                    or module in {"milai_lab.memory.presentation", "milai_lab.memory.embeddings"}
                )
            elif isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith(
                        ("milai_lab.methods", "milai_lab.runners", "milai_lab.baselines")
                    )
                    for alias in node.names
                )
            elif isinstance(node, ast.Call):
                assert not (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                assert not (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                )
            if name == "chat_bridge.py" and isinstance(node, ast.Attribute):
                assert node.attr not in {
                    "attachment",
                    "m1",
                    "odr",
                    "projection",
                    "request_view",
                    "memory_protocol",
                    "memory_turn",
                    "research_profile",
                }
    for name in ("presentation.py", "embeddings.py"):
        path = LAB / "src/milai_lab/memory" / name
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] in sys.stdlib_module_names or (
                    node.module or ""
                ).startswith("milai_lab.contracts.")
            elif isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names
                )
