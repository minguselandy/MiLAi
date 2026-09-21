from milai.application import memory_context
from milai.application.memory_context_core import (
    common,
    contracts,
    provenance,
    semantics,
    units,
)


def test_memory_context_facade_preserves_compilation_contracts() -> None:
    assert memory_context.ContextCompilation is contracts.ContextCompilation
    assert memory_context.ContextPlanCompilation is contracts.ContextPlanCompilation
    assert memory_context.EvidenceAdjacencyReader is contracts.EvidenceAdjacencyReader
    assert (
        memory_context.ContextTokenAccountingError
        is contracts.ContextTokenAccountingError
    )


def test_memory_context_facade_preserves_common_helpers() -> None:
    assert memory_context._string_values is common._string_values
    assert memory_context._estimated_tokens is common._estimated_tokens
    assert memory_context._authority_class is common._authority_class
    assert memory_context._positions is common._positions
    assert memory_context._sufficiency_status is common._sufficiency_status
    assert memory_context._unique is common._unique
    assert memory_context._sha256 is common._sha256


def test_memory_context_facade_preserves_semantic_helpers() -> None:
    assert memory_context._OPAQUE_READER_KEYS is semantics._OPAQUE_READER_KEYS
    assert (
        memory_context._query_ir_operator_family
        is semantics._query_ir_operator_family
    )
    assert (
        memory_context._query_ir_has_temporal_constraint
        is semantics._query_ir_has_temporal_constraint
    )
    assert (
        memory_context._query_ir_enumerates_members
        is semantics._query_ir_enumerates_members
    )
    assert memory_context._reader_semantic_value is semantics._reader_semantic_value
    assert memory_context._validated_operand is semantics._validated_operand


def test_memory_context_facade_preserves_provenance_helpers() -> None:
    assert memory_context._required_sources is provenance._required_sources
    assert memory_context._operand_sources is provenance._operand_sources
    assert memory_context._provenance_values is provenance._provenance_values
    assert memory_context._canonical_item_sources is provenance._canonical_item_sources
    assert memory_context._canonical_sources is provenance._canonical_sources


def test_memory_context_facade_preserves_unit_helpers() -> None:
    assert memory_context._reader_unit is units._reader_unit
    assert memory_context._status_unit_text is units._status_unit_text
    assert memory_context._render_reader_units is units._render_reader_units
    assert memory_context._render_infeasible_context is units._render_infeasible_context
