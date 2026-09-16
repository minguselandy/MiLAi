"""Serialization of generated, finite Proposal schemas for Host tool renderers."""

from typing import Any


def inline_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Expose the generated object directly; do not maintain another validation schema."""
    definitions = schema.get("$defs", {})

    def expand(value: Any) -> Any:
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if reference is not None:
            # Public input models own these nonrecursive local references.
            definition = definitions[reference.removeprefix("#/$defs/")]
            return expand({**definition, **{k: v for k, v in value.items() if k != "$ref"}})
        # oneOf + const preserve validation without dangling OpenAPI discriminator
        # mappings into the removed $defs section.
        return {key: expand(item) for key, item in value.items()
                if key not in {"$defs", "discriminator"}}

    return dict(expand(schema))


inline_proposal_schema = inline_tool_schema
