import json
import os

import pytest

from milai_lab.methods.control_cost_scale import (
    load_host_cost_scale,
    publish_host_cost_scale_witness,
    require_same_host_cost_scale,
)


def example():
    return dict(
        statistic="median_host_terminal_prompt_tokens",
        scale=200.0,
        dataset_run_id="train-v1",
        split_role="train",
        reader_requests=0,
        group_count=3,
        observed_states=3,
        groups_per_source=3,
        seed=11,
        memory_budget_tokens=2048,
        max_operations=6,
        continuation_policy="pi0-fixedcontext-4",
        observation="legal",
        reader_model="frozen",
        sha_validation=False,
        rows=[
            dict(
                source="sample",
                native_group=f"group-{i}",
                task_id=i,
                prompt_tokens=100 * i,
                status="ready",
                termination="handoff",
            )
            for i in (1, 2, 3)
        ],
    )


@pytest.mark.parametrize("error", ["median", "role", "duplicate_group"])
def test_host_scale_rejects_inconsistent_registration(tmp_path, error):
    r = example()
    if error == "median":
        r["scale"] = 201
    elif error == "role":
        r["split_role"] = "dev"
    else:
        r["rows"][0]["native_group"] = r["rows"][1]["native_group"]
    p = tmp_path / "scale.json"
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError):
        load_host_cost_scale(p)


def test_equivalent_copy_and_old_qr_identity_use_sample_semantics(tmp_path):
    p = tmp_path / "scale.json"
    r = example()
    p.write_text(json.dumps(r))
    witness = publish_host_cost_scale_witness(p)
    value, parent = load_host_cost_scale(p, dataset_run_id="train-v1", budget=2048)
    assert value == 200 and parent["witness_file"] == str(witness) and "groups" not in parent
    old = {k: v for k, v in parent.items() if k != "witness_file"}
    old.update(file_size=p.stat().st_size, mtime_ns=0)
    q = tmp_path / "relocated.json"
    r["rows"].reverse()
    q.write_text(json.dumps(r, indent=2))
    os.utime(q, (10, 10))
    require_same_host_cost_scale(old, load_host_cost_scale(q)[1])
    require_same_host_cost_scale(parent, load_host_cost_scale(q)[1])
    # Same median and source counts, distinct measured task.
    r["rows"][1]["task_id"] = 77
    q.write_text(json.dumps(r))
    with pytest.raises(ValueError):
        require_same_host_cost_scale(parent, load_host_cost_scale(q)[1])
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError):
        load_host_cost_scale(p)
