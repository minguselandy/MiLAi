"""Authority boundary for deterministic operator operands.

Natural-language retrieval matches are useful Reader context, but they are not
structured execution inputs.  QueryTaskContract presence or absence cannot
upgrade a Raw prose match into an operator operand.  A future structured input
must use a separate, explicit authority object instead of overloading
``RequirementBinding``.
"""

from __future__ import annotations

from collections.abc import Sequence

from milai.domain.semantic_query import RequirementBinding


def operator_operands_from_raw_bindings(
    bindings: Sequence[RequirementBinding],
) -> tuple[RequirementBinding, ...]:
    """Reject Raw-language bindings as deterministic operator operands."""

    del bindings
    return ()


__all__ = ["operator_operands_from_raw_bindings"]
