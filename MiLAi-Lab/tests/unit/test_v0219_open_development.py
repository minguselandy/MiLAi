"""Ordered D opening cannot skip review, take C sources or execute foreign tasks."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_inventory import save, sha
from v0219_open_development import open_next


@pytest.fixture
def pool(tmp_path):
    seal, screen = tmp_path / "seal", tmp_path / "screen"
    seal.mkdir()
    sources = []
    for key in ("D1", "D2", "C1"):
        path = tmp_path / (key + ".py")
        path.write_text("raise RuntimeError('Never execute this task')\n")
        sources.append({"root_id": key, "source_path": str(path), "native_id": key})
    save(
        seal / "assignment.json",
        {
            "D_order": [
                {"root_id": key, "family": key, "order": i + 1}
                for i, key in enumerate(("D1", "D2"))
            ],
            "reserve": [{"root_id": "C1"}],
        },
    )
    save(seal / "private-source-map.json", {"rows": sources})
    save(
        seal / "neutral-manifest.json",
        {
            "rows": [
                {"root_id": s["root_id"], "source_sha256": sha(Path(s["source_path"]))}
                for s in sources
            ]
        },
    )
    save(seal / "seal-A.json", {"files": {p.name: sha(p) for p in seal.iterdir()}})
    return seal, screen


def test_opens_next_D_without_executing_or_copying_C(pool):
    seal, screen = pool
    first = open_next(seal, screen)
    assert first["root_id"] == "D1"
    assert not (screen / "opened/C1").exists()
    with pytest.raises(AssertionError, match="REVIEW_PREVIOUS_ROOT_FIRST"):
        open_next(seal, screen)
    save(screen / "001-decision.json", {"root_id": "D1", "status": "HOLD"})
    assert open_next(seal, screen)["root_id"] == "D2"


@pytest.mark.parametrize(
    "decision",
    [{"root_id": "C1", "status": "ACCEPT_STATIC"}, {"root_id": "D1", "status": "MODEL_PASSED"}],
)
def test_wrong_root_or_outcome_based_decision_cannot_advance(pool, decision):
    seal, screen = pool
    open_next(seal, screen)
    save(screen / "001-decision.json", decision)
    with pytest.raises(AssertionError):
        open_next(seal, screen)


def test_tampered_order_rejected_before_reading_source(pool):
    seal, screen = pool
    (seal / "assignment.json").write_text(json.dumps({"D_order": [{"root_id": "C1"}]}))
    with pytest.raises(AssertionError):
        open_next(seal, screen)
    assert not screen.exists()
