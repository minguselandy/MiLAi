from __future__ import annotations

import pytest

from milai_lab.contracts.arms import ExperimentArmKind, ExperimentArmSpec


def test_black_box_arm_is_product_claim_capable() -> None:
    arm = ExperimentArmSpec(
        arm_id="product",
        kind=ExperimentArmKind.PRODUCT_BLACK_BOX,
        implementation="mcp://memory.resolve",
        product_lock_digest="a" * 64,
        public_interface_ids=("mcp",),
    )

    assert arm.claim_scope() == "PRODUCT_EFFECT"
    assert arm.kind.may_support_product_effect_claim


def test_product_arm_requires_pin_and_public_interface() -> None:
    with pytest.raises(ValueError, match="product lock"):
        ExperimentArmSpec(
            arm_id="product",
            kind=ExperimentArmKind.PRODUCT_TESTKIT,
            implementation="testkit",
        )


def test_research_prototype_cannot_claim_product_interface() -> None:
    with pytest.raises(ValueError, match="cannot claim"):
        ExperimentArmSpec(
            arm_id="prototype",
            kind=ExperimentArmKind.RESEARCH_PROTOTYPE,
            implementation="milai_lab.methods.demo",
            public_interface_ids=("mcp",),
        )


def test_product_lock_digest_must_be_sha256() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ExperimentArmSpec(
            arm_id="product",
            kind=ExperimentArmKind.PRODUCT_BLACK_BOX,
            implementation="mcp://memory.resolve",
            product_lock_digest="not-a-digest",
            public_interface_ids=("mcp",),
        )
