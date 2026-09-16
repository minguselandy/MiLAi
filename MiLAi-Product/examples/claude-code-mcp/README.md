# Claude Code + MiLAi MCP (future compatibility)

This example documents the same HTTP endpoint for future Host compatibility. Claude Code is no
longer a Product-08 acceptance dependency and no Claude result is claimed.

```bash
export MILAI_MCP_HTTP_BEARER_TOKEN="...project credential..."
claude
```

The configuration intentionally contains no token or model-selectable identity. Claude may provide
only a memory query and an opaque prior context locator. MiLAi returns governed evidence through
`memory-evidence-context-v1`; Claude owns semantic sufficiency and the final answer.

This is MCP Interactive Mode, not guaranteed prefetch. Report Host invocation failures separately
from MiLAi retrieval failures.
