# MiLAi compatibility registry

The machine-readable registry is [`compatibility-registry.json`](compatibility-registry.json).
It makes retention intent explicit without treating every importable Python object as a supported
API.

## Categories

| Category | Meaning | Removal authority |
| --- | --- | --- |
| `PUBLIC_API` | Supported package or executable-facing API | Versioned API decision |
| `PUBLIC_COMPAT` | Historical public location over modular internals | Consumer migration plus compatibility decision |
| `TEST_COMPAT` | Test-only fixture/helper or node-identity seam | Test consumer inventory and direct validation |
| `HISTORICAL_COMPAT` | Frozen receipt or historical artifact dependency | Historical evidence audit |
| `INTERNAL_TEMPORARY` | Explicit internal transition surface | C8 no-consumer proof |

The registry is conservative: being importable does not automatically make a symbol public, and
absence from the registry is not deletion evidence. C8 still requires production, test, CLI/plugin,
Lab, receipt and archive consumer checks before removing anything.

The completed C8 disposition inventory is
[`compatibility-dead-code-audit.json`](compatibility-dead-code-audit.json), with rationale in
[`COMPATIBILITY_DEAD_CODE_AUDIT.md`](COMPATIBILITY_DEAD_CODE_AUDIT.md). No registered entry met the
six-dimensional deletion rule: the sole `INTERNAL_TEMPORARY` entry remains consumed by Product,
tests, and immutable archive material.

## C6 test support boundary

Before C6, ordinary test modules contained 45 direct imports from sibling `test_*.py` modules.
Those imports made collection order and infrastructure ownership implicit. Tests now import shared
fixtures and helpers through three dedicated seams:

- `runtime/tests/integration/support/`
- `integrations/python-client/tests/support/`
- `integrations/mcp/tests/support/`

The seams deliberately preserve the existing helper objects rather than rewriting fixture
behavior. Identity tests record the original owner module for each facade. The large PostgreSQL
and HTTP harnesses remain at their historical owners in C6; relocating their implementations is
not needed to establish a stable test dependency direction and would add behavior risk without
coverage benefit.

All 29 receipt-referenced pytest nodes remain top-level functions at their exact recorded paths.
They are listed verbatim in the registry and checked against both the immutable receipt corpus and
the active AST inventory.

## Verification

Run:

```text
python3 tools/verify_compatibility_registry.py
python3 tools/cleanup_validate.py compatibility-audit --level dev
python3 tools/cleanup_validate.py test-organization --level dev
```

The verifier rejects category drift, missing registered paths, receipt-node drift, missing node
wrappers, support-root drift, and new direct sibling-test imports outside the registered support
seams.
