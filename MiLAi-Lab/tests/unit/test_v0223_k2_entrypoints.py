"""Every new CPU entry refuses before replay work when socket denial cannot install."""

import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"


@pytest.mark.parametrize(
    "entry,args",
    [
        ("prepare_v0223_k2_fixture.py", ["--instance", "k2-base"]),
        ("inventory_v0223_k2_fixture.py", ["--instance", "k2-base", "--output", "forbidden.json"]),
        ("run_v0223_k2_prefix.py", []),
        ("run_v0223_k2_pair.py", []),
        ("assemble_v0223_k2_pair.py", []),
    ],
)
def test_new_entry_refuses_unconfirmed_guard_before_outputs(tmp_path, entry, args):
    code = f"""
import runpy, sys
sys.path.insert(0, {str(TOOLS)!r})
import v0222_scoped_cpu_guard as guard
guard.sys.addaudithook = lambda hook: None
sys.argv = [{entry!r}] + {args!r}
try:
    runpy.run_path({str(TOOLS / entry)!r}, run_name="__main__")
except RuntimeError as error:
    assert str(error) == "CPU_NETWORK_GUARD_REGISTRATION_NOT_CONFIRMED", repr(error)
    print("REFUSED_BEFORE_REPLAY")
else:
    raise AssertionError("ENTRY_DID_NOT_REFUSE")
"""
    child = subprocess.run(  # noqa: S603 - fixed interpreter and parametrized test code; no shell
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert child.stdout.strip() == "REFUSED_BEFORE_REPLAY"
    assert not list(tmp_path.iterdir())
