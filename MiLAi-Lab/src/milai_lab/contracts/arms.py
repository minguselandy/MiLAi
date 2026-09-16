from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExperimentArmKind(StrEnum):
    """Authority class for an experiment arm."""

    PRODUCT_BLACK_BOX = "PRODUCT_BLACK_BOX"
    PRODUCT_TESTKIT = "PRODUCT_TESTKIT"
    RESEARCH_PROTOTYPE = "RESEARCH_PROTOTYPE"
    SIMULATION = "SIMULATION"

    @property
    def may_support_product_effect_claim(self) -> bool:
        return self is ExperimentArmKind.PRODUCT_BLACK_BOX

    @property
    def requires_product_pin(self) -> bool:
        return self in {
            ExperimentArmKind.PRODUCT_BLACK_BOX,
            ExperimentArmKind.PRODUCT_TESTKIT,
        }


@dataclass(frozen=True, slots=True)
class ExperimentArmSpec:
    arm_id: str
    kind: ExperimentArmKind
    implementation: str
    product_lock_digest: str | None = None
    public_interface_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.arm_id.strip() or not self.implementation.strip():
            raise ValueError("arm_id and implementation are required")
        if self.kind.requires_product_pin and not self.product_lock_digest:
            raise ValueError(f"{self.kind} requires a product lock digest")
        if self.product_lock_digest is not None and (
            len(self.product_lock_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.product_lock_digest)
        ):
            raise ValueError("product_lock_digest must be a lowercase SHA-256 digest")
        if self.kind.requires_product_pin and not self.public_interface_ids:
            raise ValueError(f"{self.kind} requires at least one public interface")
        if not self.kind.requires_product_pin and self.public_interface_ids:
            raise ValueError(f"{self.kind} cannot claim a product public interface")

    def claim_scope(self) -> str:
        scopes = {
            ExperimentArmKind.PRODUCT_BLACK_BOX: "PRODUCT_EFFECT",
            ExperimentArmKind.PRODUCT_TESTKIT: "ENGINEERING_DIAGNOSTIC",
            ExperimentArmKind.RESEARCH_PROTOTYPE: "METHOD_PROTOTYPE",
            ExperimentArmKind.SIMULATION: "MECHANISM_ONLY",
        }
        return scopes[self.kind]
