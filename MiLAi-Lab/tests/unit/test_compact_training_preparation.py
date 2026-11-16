"""Only declared format fields change; compact feedback initialization stays unbound."""

import copy
import importlib.util
import json

import pytest

from prepare_compact_matched_training import (
    COMPACT_BRANCH,
    OLD_CHOICES,
    PROJECTION_ENTRY,
    compact_spec,
    extend_runtime,
)


def test_literal_overlay_recovers_original_and_compact_projection_is_idempotent(tmp_path):
    source, target = tmp_path / "original", tmp_path / "compact"
    policy = source / "src/milai_lab/methods/laya_memory_policy.py"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        "import json\n\ndef project_operation_payload(payload, projection):\n"
        + PROJECTION_ENTRY
        + '    if projection == "shared_actions":\n        return payload\n'
        + '    raise ValueError("unsupported")\n'
    )
    (source / "tools").mkdir()
    for name in ["train_bounded_laya.py", "evaluate_bounded_laya.py"]:
        (source / "tools" / name).write_text("CHOICES = (" + OLD_CHOICES + "\n")
    (source / "src/unchanged.py").write_text('VALUE = "old logic"\n')
    original = {
        str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    report = extend_runtime(source, target)
    assert len(report["changed_files"]) == 3 and report["unchanged_python_files"] == 1
    assert original == {
        str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    changed = target / policy.relative_to(source)
    assert changed.read_text().replace(COMPACT_BRANCH, "") == policy.read_text()
    spec = importlib.util.spec_from_file_location("compact_mechanical", changed)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {
        "state": {"literal": '  Ω\t\n "quoted"  ', "a": [0, False, None, 1.0]},
        "questions": {"next": {"criteria": {"a": "READ", "b": "HANDOFF"}}},
    }
    before = copy.deepcopy(payload)
    compact = module.project_operation_payload(payload, "compact_actions")
    assert compact["state"] == json.dumps(
        payload["state"], ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    assert compact["questions"] == payload["questions"] and payload == before
    assert module.project_operation_payload(compact, "compact_actions") == compact
    assert module.project_operation_payload(payload, "shared_actions") == before


def test_recipe_preserves_every_optimization_argument_and_leaves_feedback_unbound(tmp_path):
    original = {
        "run_id": "old",
        "argv": [
            "python",
            "old/train_bounded_laya.py",
            "data",
            "shared-initializer",
            "old-output",
            "--operation-state",
            "shared_actions",
            "--compute-phase",
            "old-phase",
            "--optimizer-updates",
            "192",
            "--seed",
            "0",
        ],
        "environment": {"PYTHONPATH": "old/src:old/tools", "CUDA_VISIBLE_DEVICES": "2,3"},
    }
    before = copy.deepcopy(original)
    runtime = tmp_path / "runtime"
    result = compact_spec(original, runtime, tmp_path / "run", "new-phase", unbound_init=True)
    assert original == before and result["initialization_pending"]
    assert result["argv"][3] is None
    assert result["argv"][-4:] == original["argv"][-4:]
    assert result["environment"]["CUDA_VISIBLE_DEVICES"] == "2,3"
    assert result["argv"][result["argv"].index("--operation-state") + 1] == "compact_actions"
    original["argv"][6] = "shared_actions_request_text"
    with pytest.raises(ValueError, match="shared-actions"):
        compact_spec(original, runtime, tmp_path / "other", "other-phase", unbound_init=False)
