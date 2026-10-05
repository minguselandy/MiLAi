"""Writer orchestration retains legacy identities and complete synthetic contracts."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[2]
GOLDEN = LAB / "data/diagnostics/code-architecture-v12"


def test_old_writer_and_accounting_exports_are_canonical_objects() -> None:
    from milai_lab.analysis.trace_accounting import _accounting
    from milai_lab.runners import langmem_application, local_state_attention, writer_policy

    assert langmem_application.WriterPolicy is writer_policy.WriterPolicy
    assert (
        langmem_application.WRITER_POLICY_INSTRUCTIONS is writer_policy.WRITER_POLICY_INSTRUCTIONS
    )
    assert langmem_application.run_writer_policy_turn is writer_policy.run_writer_policy_turn
    assert local_state_attention._accounting is _accounting
    assert writer_policy._accounting is _accounting
    assert writer_policy.run_writer_policy_turn.__module__ == "milai_lab.runners.writer_policy"
    for name in (
        "fixed_state_read",
        "fixed_state_update",
        "state_update_probe",
        "shared_record_use",
    ):
        module = __import__("milai_lab.runners." + name, fromlist=["_accounting"])
        assert module._accounting is _accounting
    tree = ast.parse((LAB / "src/milai_lab/runners/langmem_application.py").read_text())
    definitions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "run_writer_policy_turn" not in definitions
    assert {"run_phase", "_operator_memory_event", "_collect_turn_tail"} <= definitions


@pytest.mark.parametrize("first", ["langmem_application", "writer_policy", "local_state_attention"])
def test_writer_and_phase_import_orders_have_no_cycle(first: str) -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        f"import milai_lab.runners.{first}; "
        "from milai_lab.runners import langmem_application as app,writer_policy as writer, "
        "local_state_attention as local; "
        "from milai_lab.analysis.trace_accounting import _accounting; "
        "assert app.run_writer_policy_turn is writer.run_writer_policy_turn; "
        "assert local._accounting is writer._accounting is _accounting"
    )
    result = subprocess.run(  # noqa: S603 -- fixed local import-order probe
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_writer_assertions_match_whole_deterministic_contract() -> None:
    # The old synthetic callers have no persisted Host thread. Their full golden
    # contract stays unchanged apart from this new, explicitly absent Scope field.
    # Assert None rather than dropping the actual field or normalizing its value.
    code = (
        "import json,sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(LAB / 'tests/architecture')!r}); "
        "from writer_contract_probe import writer_contract; "
        f"lab=Path({str(LAB)!r}); temporary=sys.argv[1]; "
        "status,cases,sources=writer_contract(lab,temporary); "
        "assert status==0; "
        f"expected=json.loads((lab/'data/diagnostics/code-architecture-v12/"
        "writer-accounting-deterministic-golden.json').read_text())"
        "['contracts']['writer_policies']\n"
        "scope_events=[event for case in expected.values() for event in case['events'] "
        "if event['stage']=='writer_turn.enter']\n"
        "assert len(scope_events)==13\n"
        "for event in scope_events:\n"
        "    assert 'stored_thread_id' not in event['scope']\n"
        "    event['scope']['stored_thread_id']=None\n"
        "actual=json.loads(json.dumps(cases,ensure_ascii=False).replace(temporary,'<TMP>')); "
        "assert actual==expected; "
        "assert all(Path(module.__file__).resolve().is_relative_to(lab/'src') "
        "for name,module in sys.modules.items() "
        "if name.startswith('milai_lab') and getattr(module,'__file__',None)); "
        "print(json.dumps({'writer_cases':len(cases),'full_contract_equal':True,'python_hash_seed':'0'}))"
    )
    with tempfile.TemporaryDirectory(prefix="milai-writer-contract-") as temporary:
        result = subprocess.run(  # noqa: S603 -- frozen synthetic test selection
            [sys.executable, "-c", code, temporary],
            env={**os.environ, "PYTHONHASHSEED": "0"},
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert result.returncode == 0, result.stdout + result.stderr
