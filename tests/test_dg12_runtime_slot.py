from __future__ import annotations

from pathlib import Path

import pytest

from evals.dg12.runtime_slot import (
    CohortRuntimeSlot,
    LoaderKind,
    RuntimeSlotError,
    SlotLifecycle,
    SlotState,
    bounded_representative_work,
    load_slot_work,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "var/dg11/paper/freeze"


@pytest.mark.parametrize(
    ("name", "loader", "history_count", "question_count"),
    (
        ("cupid-smoke-inputs.json", LoaderKind.CUPID, 6, 6),
        ("horizon-smoke-inputs.json", LoaderKind.HORIZON, 10, 10),
        ("beam-128k-inputs.json", LoaderKind.BEAM, 20, 400),
        ("memora-inputs.json", LoaderKind.MEMORA, 3, 60),
    ),
)
def test_four_loader_families_normalize_to_one_slot_contract(
    name: str, loader: LoaderKind, history_count: int, question_count: int
) -> None:
    _partition, work = load_slot_work(FREEZE / name)

    assert len(work) == history_count
    assert sum(len(item.questions) for item in work) == question_count
    assert {item.history.loader_kind for item in work} == {loader}
    assert all(
        question.history_id == item.history.history_id
        for item in work
        for question in item.questions
    )


def test_runtime_slot_lifecycle_is_typed_and_fails_closed() -> None:
    lifecycle = SlotLifecycle()
    for target in (
        SlotState.MIGRATED,
        SlotState.READY_AND_WARM,
        SlotState.EMPTY,
        SlotState.LOADING_COHORT,
        SlotState.INDEXED,
        SlotState.QUERYING,
        SlotState.INDEXED,
        SlotState.DRAINING,
        SlotState.RESETTING,
        SlotState.EMPTY,
        SlotState.CLOSED,
    ):
        lifecycle.transition(target)
    assert lifecycle.state is SlotState.CLOSED
    with pytest.raises(RuntimeSlotError, match="illegal"):
        lifecycle.transition(SlotState.EMPTY)


def test_runtime_slot_quarantine_cannot_reenter_service() -> None:
    lifecycle = SlotLifecycle()
    lifecycle.quarantine("RESET_VERIFICATION_FAILED")
    assert lifecycle.state is SlotState.QUARANTINED
    assert lifecycle.reason_code == "RESET_VERIFICATION_FAILED"
    with pytest.raises(RuntimeSlotError, match="illegal"):
        lifecycle.transition(SlotState.EMPTY)
    lifecycle.transition(SlotState.CLOSED)


def test_cohort_adapter_implements_unified_runtime_slot_contract(
    tmp_path: Path,
) -> None:
    slot = CohortRuntimeSlot(
        slot_id="slot-fixture",
        env_file=tmp_path / "env",
        tokenizer_path=tmp_path / "tokenizer.json",
    )
    assert slot.slot_id == "slot-fixture"
    assert slot.state is SlotState.NEW
    slot.start()
    with pytest.raises(RuntimeSlotError, match="current state"):
        slot.start()
    slot.close()
    assert slot.state is SlotState.CLOSED


def test_bounded_representative_smoke_rebinds_question_to_prefix_history() -> None:
    _partition, work = load_slot_work(FREEZE / "beam-128k-inputs.json")
    bounded = bounded_representative_work(work[0])

    assert len(bounded.history.sessions) == 1
    assert len(bounded.questions) == 1
    assert bounded.questions[0].history_id == bounded.history.history_id
    assert bounded.history.history_id != work[0].history.history_id
