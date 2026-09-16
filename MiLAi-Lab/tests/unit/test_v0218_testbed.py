"""Cross-family calibration uses the pre-existing independent literal test fixtures."""

import copy
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0218_checker
from check_v0218_testbed import ROOTS, boundaries
from prepare_v0218 import claim, scheduling
from prepare_v0218_expansion import financial_basis, release_control
from v0218_world import World

CASES = (
    ("world", scheduling),
    ("world", claim),
    ("expansion", release_control),
    ("financial", financial_basis),
    ("traceability", None),
    ("news", None),
    ("bridge", None),
    ("casework", None),
    ("product_review", None),
    ("research_integrity", None),
    ("transaction", None),
    ("capacity", None),
)


def fixture(case, path):
    name, factory = case
    module = importlib.import_module("test_v0218_" + name)
    if name == "world":
        spec = factory()
        completed = module.populated(path / "completed", spec)
    elif factory:
        spec, completed = factory(), module.populated(path / "completed")
    else:
        result = module.populated(path / "completed")
        completed, spec = result[:2]
    initial = World.create(path / "initial.sqlite", completed.scope, spec["public"])
    return spec, initial, completed


@pytest.mark.parametrize("case", CASES, ids=[root for _, root in ROOTS])
def test_every_profile_reset_cas_clone_canaries_and_malformed_outputs(tmp_path, case):
    spec, initial, completed = fixture(case, tmp_path)
    result = boundaries(spec, initial, completed, tmp_path / "boundary")
    assert result["status"] == "PASS" and result["model_requests"] == 0


@pytest.mark.parametrize("case", CASES, ids=[root for _, root in ROOTS])
def test_every_family_kills_disabled_checker_implementation(tmp_path, case):
    _, _, completed = fixture(case, tmp_path)
    valid = completed.snapshot()
    bad = copy.deepcopy(valid)
    bad["records"] = {}
    assert v0218_checker.evaluate(valid)["status"] == "PASS"
    assert v0218_checker.evaluate(bad)["status"] == "FAIL"
    domain = valid["policy"]["domain"]
    source = Path(v0218_checker.__file__).read_text()
    lines = [line for line in source.splitlines() if line.strip().startswith(f'"{domain}":')]
    assert len(lines) == 1
    mutated = source.replace(lines[0], f'        "{domain}": lambda state: [],')
    namespace = {}
    # Only fixed mutation of this repository's owned checker, never benchmark code.
    exec(compile(mutated, "owned_domain_checker_mutant.py", "exec"), namespace)  # noqa: S102
    assert namespace["evaluate"](bad)["status"] == "PASS"


def test_root_order_remains_twelve_original_lineages_not_variant_expansion():
    assert len(ROOTS) == len({key for _, key in ROOTS}) == len(CASES) == 12
    assert [key for _, key in ROOTS[:2]] == ["executive_assistant_task2", "insurance_task3"]
