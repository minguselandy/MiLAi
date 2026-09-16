"""Kill controlled mutations of our checker using independent positive/negative snapshots."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0218_expansion import populated as release_world
from test_v0218_financial import populated as financial_world
from test_v0218_world import populated

import v0218_checker
from prepare_v0218 import claim


def states(tmp_path):
    valid = [
        populated(tmp_path / "schedule").snapshot(),
        populated(tmp_path / "claim", claim()).snapshot(),
        release_world(tmp_path / "release").snapshot(),
        financial_world(tmp_path / "financial").snapshot(),
    ]
    bad = []
    for index, target, changes in [
        (0, "C03", {"mode": "online", "room": "online"}),
        (1, "FLT-DLY-0315", {"amount_cny": "400"}),
        (2, "enterprise-midterm", {"distribution": ["advisor", "enterprise_contact"]}),
        (3, "reported_income", {"basis": "adjusted"}),
        (3, "nii_guide", {"value": 90}),
    ]:
        state = copy.deepcopy(valid[index])
        state["records"][target].update(changes)
        bad.append(state)
    assert all(v0218_checker.evaluate(s)["status"] == "PASS" for s in valid)
    assert all(v0218_checker.evaluate(s)["status"] == "FAIL" for s in bad)
    return valid + bad, ["PASS"] * len(valid) + ["FAIL"] * len(bad)


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("errors = check(state)", "errors = []"),
        ("value.utcoffset().total_seconds() != 28800", "value.utcoffset().total_seconds() != 0"),
        ('if mode not in current["modes"]:', "if False:"),
        (
            'minutes // 60 * policy["hourly_rate_cny"]',
            '(minutes + 59) // 60 * policy["hourly_rate_cny"]',
        ),
        ('type(row["amount_cny"]) not in (int, float)', "False"),
        ('or set(recipients) - set(policy["allowed_distribution"])', "or False"),
        ('for k in ("metric", "basis", "period")', 'for k in ("metric", "period")'),
        ("> tolerance:", '> Decimal("1000"):'),
    ],
)
def test_independent_fixture_set_kills_checker_mutation(tmp_path, original, replacement):
    cases, expected = states(tmp_path)
    source = Path(v0218_checker.__file__).read_text()
    assert source.count(original) == 1
    changed = source.replace(original, replacement)
    namespace = {}
    # Only this repository's owned checker and fixed test mutations; no benchmark code execution.
    exec(compile(changed, "owned_checker_mutant.py", "exec"), namespace)  # noqa: S102
    observed = [namespace["evaluate"](copy.deepcopy(state))["status"] for state in cases]
    assert observed != expected


def test_financial_object_renaming_is_not_a_checker_special_case(tmp_path):
    state = financial_world(tmp_path).snapshot()
    mapping = {key: "object-" + str(index) for index, key in enumerate(state["objects"])}
    state["objects"] = list(mapping.values())
    state["records"] = {
        mapping[key]: {**row, "object_id": mapping[key]} for key, row in state["records"].items()
    }
    state["current"]["metrics"] = {
        mapping[key]: row for key, row in state["current"]["metrics"].items()
    }
    for key in ("left", "right", "object"):
        state["policy"]["comparison"][key] = mapping[state["policy"]["comparison"][key]]
    assert v0218_checker.evaluate(state)["status"] == "PASS"
