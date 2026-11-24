"""The shared S4 evidence prefix is independent of method selection and paid feedback."""

import json
from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import pytest

import repeat_memory_control_v13_finalists as repeats


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def registered(tmp_path, mapped=False):
    root = tmp_path / "experiment"
    base_model = tmp_path / "gte"
    base_model.mkdir()
    initial = root / "weights/s1/checkpoint"
    initial.mkdir(parents=True)
    controller = {
        "backbone": str(base_model),
        "object_batch": 8,
        "limit": 2048,
        "cost_scale": 2048,
        "history": True,
    }
    write(initial / "controller.json", controller)
    (initial / "control.pt").write_bytes(b"fixture")
    contract = dict(
        seed=11,
        input=str(tmp_path / "frozen-evidence.sqlite"),
        full_population=2,
        selected_per_epoch=2,
        epochs=1,
        updates=1,
        effective_batch=32,
        object_batch=8,
        lr=1e-5,
        supervision_mode="evidence",
        parent=None,
        probe=False,
        mixed_precision="bf16",
        schedule="fixed-order",
        group_caps_per_allocation_pass={"source": 6},
        root_weighting="native-group-first",
        source_inventory={"source": {"roots": 2, "groups": 2}},
        source_weights={"source": 1.0},
        fitted_groups=["source/x", "source/y"],
    )
    if mapped:
        contract.update(
            frozen_native_root_order=str(tmp_path / "native-order.gz"),
            frozen_native_root_master=str(tmp_path / "rebuilt-master.sqlite"),
        )
    receipt = dict(
        status="completed",
        contract=contract,
        reload_scores_equal=True,
        roots=2,
        optimizer_updates=1,
        unique_tasks=2,
        demo_steps=1,
        source_exposures={"source": 2},
    )
    write(initial.parent / "run.json", receipt)
    return Namespace(root=root, s1=initial), receipt, controller


def fake_fit(monkeypatch, base, config, calls):
    def run(module, *argv):
        assert module == "pretrained_control_train"
        flags = dict(zip(argv[::2], argv[1::2], strict=True))
        calls.append(flags)
        seed = flags["--seed"]
        result = deepcopy(base)
        result["contract"]["seed"] = seed
        result["fit_identity"] = {"id": seed, "backbone": str(flags["--backbone"])}
        out = Path(flags["--output"])
        metrics = Path(flags["--metrics"])
        (out / "checkpoint").mkdir(parents=True, exist_ok=True)
        (out / "checkpoint/control.pt").write_bytes(b"fixture")
        write(out / "checkpoint/controller.json", config)
        write(out / "run.json", result)
        write(metrics / "run.json", result)

    monkeypatch.setattr(repeats, "run", run)


@pytest.mark.parametrize("mapped", [False, True])
def test_evidence_only_reuses_exact_recipe_and_does_not_select(tmp_path, monkeypatch, mapped):
    args, base, config = registered(tmp_path, mapped)
    calls = []
    fake_fit(monkeypatch, base, config, calls)

    def forbidden(*args, **kwargs):
        raise AssertionError("Selection, Reader, or outcome work is outside evidence-only")

    for function in ("freeze", "roster", "repeat_population", "invoke", "mechanism_readouts"):
        monkeypatch.setattr(repeats, function, forbidden)
    paths = repeats.evidence_only(args)
    assert list(paths) == [29, 47] and [f["--seed"] for f in calls] == [29, 47]
    for flags in calls:
        assert flags["--objective"] == "evidence" and "--initialize" not in flags
        assert (
            flags["--backbone"] == config["backbone"]
            and flags["--data"] == base["contract"]["input"]
        )
        assert (
            flags["--epochs"],
            flags["--lr"],
            flags["--batch"],
            flags["--object-batch"],
            flags["--device"],
        ) == (1, 1e-5, 32, 8, "cuda")
        assert ("--evidence-order-map" in flags) == mapped
        assert ("--evidence-master" in flags) == mapped
        if mapped:
            assert flags["--evidence-order-map"] == base["contract"]["frozen_native_root_order"]
            assert flags["--evidence-master"] == base["contract"]["frozen_native_root_master"]
    assert not (args.root / "warm-11/packs").exists()
    assert not (args.root / "s4").exists() and not (args.root / "baselines").exists()
    assert repeats.evidence_only(args) == paths and len(calls) == 2
    # The existing repeat() uses the very same evidence_fit normal entry point.
    assert str(repeats.evidence_fit(args.root, args.s1, 29)) == paths[29] and len(calls) == 2


def test_unclosed_parents_and_wrong_repeats_are_rejected(tmp_path, monkeypatch):
    args, base, config = registered(tmp_path)
    calls = []
    fake_fit(monkeypatch, base, config, calls)
    write(args.s1.parent / "run.json", dict(base, status="running"))
    with pytest.raises(ValueError, match="complete, reloaded seed11"):
        repeats.evidence_only(args)
    write(args.s1.parent / "run.json", base)
    assert not calls
    assert not (args.root / "fits").exists()
    repeats.evidence_only(args)
    out = args.root / "weights/s1-f29"
    r = json.loads((out / "run.json").read_text())
    wrong = deepcopy(r)
    wrong["contract"]["schedule"] = "different"
    write(out / "run.json", wrong)
    with pytest.raises(ValueError, match="recipe"):
        repeats.evidence_fit(args.root, args.s1, 29)
    write(out / "run.json", r)
    (tmp_path / "other").mkdir()
    write(out / "checkpoint/controller.json", dict(config, backbone=str(tmp_path / "other")))
    with pytest.raises(ValueError, match="foundation|backbone"):
        repeats.evidence_fit(args.root, args.s1, 29)
    assert len(calls) == 2
