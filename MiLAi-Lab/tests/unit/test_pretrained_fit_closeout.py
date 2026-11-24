import json

import pytest

from milai_lab.runners.pretrained_fit_closeout import finish_verified, fit_owner


def test_fit_ownership_includes_shared_metrics_and_output_alias(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    metrics = tmp_path / "metrics"
    with fit_owner(first, metrics):
        link = tmp_path / "alias"
        link.symlink_to(first, target_is_directory=True)
        with pytest.raises(RuntimeError, match="Another fit owns"), fit_owner(link, second):
            pass
        with pytest.raises(RuntimeError, match="Another fit owns"), fit_owner(second, metrics):
            pass
    with fit_owner(first, metrics):
        pass


def test_interrupted_publish_uses_original_probe_and_device(tmp_path):
    torch = pytest.importorskip("torch")
    directory = tmp_path / "checkpoint"
    directory.mkdir()
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    contract = dict(epochs=1, selected_per_epoch=1, updates=1, fitted_groups=[])
    proof = dict(
        fit_identity="first-fit",
        contract=contract,
        device_type="cpu",
        online={"visible": 1},
        scores=[[[0.25]], [[0.5]]],
        summary={
            "optimizer_updates": 1,
            "roots": 1,
            "source_exposures": {"source": 1},
            "contract": dict(contract, fitted_groups=["source/group"]),
        },
    )
    (directory / "fit_completion.json").write_text(json.dumps(proof))

    class Reload:
        @classmethod
        def load(cls, path, device):
            assert path == directory and device == "cpu"
            return cls()

        def score(self, online):
            assert online == {"visible": 1}
            return torch.tensor([[0.25]]), torch.tensor([[0.5]])

    with pytest.raises(ValueError, match="parity device"):
        finish_verified(Reload, tmp_path, metrics, "first-fit", contract, "cuda")
    with pytest.raises(ValueError, match="Published fit"):
        finish_verified(Reload, tmp_path, metrics, "other-fit", contract, "cpu")
    finish_verified(Reload, tmp_path, metrics, "first-fit", contract, "cpu")
    assert (metrics / "run.json").read_text() == (tmp_path / "run.json").read_text()
    before = (tmp_path / "run.json").read_text()
    proof["scores"][0][0][0] = 0.75
    (directory / "fit_completion.json").write_text(json.dumps(proof))
    with pytest.raises(AssertionError):
        finish_verified(Reload, tmp_path, metrics, "first-fit", contract, "cpu")
    assert (tmp_path / "run.json").read_text() == before
