# MCP Server internal module map

## Compatibility boundary

The supported package entry points remain:

```python
from milai_mcp.server import build_server
from milai_mcp.server import main
```

`integrations/mcp/src/milai_mcp/server.py` is now a 122-line compatibility facade. It keeps the
existing server contracts, helpers, factory and CLI names available from `milai_mcp.server` as the
same objects exported by their owning modules. The new `server_*` modules are internal seams and
do not create a new public API.

Two historical monkeypatch observation points are preserved deliberately:

- `build_server()` resolves the default `MilaiClient` through the loaded `milai_mcp.server`
  facade at call time;
- `main()` resolves `build_server` through that facade at call time.

This keeps existing tests and private consumers that patch `server.MilaiClient` or
`server.build_server` working after the implementation relocation.

## Final responsibility map

| Module | Responsibility | Principal symbols |
| --- | --- | --- |
| `server_contracts.py` | Profiles, tool catalogs/titles/annotations, governance constants, role-routed clients and Pydantic inputs | `Profile`, `CodexFullRuntimeClients`, `CodexFullProposalInput`, `StateKeyInput`, `TaskContextInput`, `TOOL_COMPATIBILITY_VNEXT`, `_tool_annotations` |
| `server_middleware.py` | Strict-argument enforcement, request-token binding and MCP request/schema middleware | `_StrictArguments`, `_RequestAccessTokenMiddleware`, `_StrictSchemaMCPServer`, `_request_access_token` |
| `server_wire.py` | Bounded wire output, guidance, receipt/proof projections and resolve compaction | `_bounded`, `_bounded_memory_resolve`, `_with_mcp_guidance`, `_wire_receipt`, `_wire_proof_pointer`, `_wire_size_diagnostics` |
| `server_reader.py` | Status, recall and memory-resolve tool registration plus Reader policy/access trace | `ReaderToolset`, `build_reader_toolset`, `_bind_effective_need_policy`, `_mcp_access_trace` |
| `server_governance.py` | Identity, mutation and Working State tool registration | `GovernanceToolset`, `build_governance_toolset` |
| `server_codex.py` | Codex-full submitter, reviewer and operator governance tool registration | `extend_codex_governance_tools` |
| `server_factory.py` | Profile validation, client/policy assembly, toolset composition, transport setup and CLI | `build_server`, `main`, `_codex_full_clients_from_environment`, `resolve_budget_profile_by_name` |
| `server.py` | Stable import facade and compatibility aliases | `build_server`, `main` and inventoried legacy exports |

## Equivalence evidence

The extraction baseline is Product commit
`43a2c6a031cbe79a5f34dd835de60c6e3fc9cec3`, where `server.py` contained 4,145 lines.

A local recursive AST comparison against that baseline inspected every named class and function in
the original module and searched all final `server*.py` modules:

```text
baseline recursive definitions: 104
exact AST matches:              102
same-name changed definitions:  2 (build_server, main)
missing definition names:       0

shared top-level assignments:   15
exact assignment matches:       14
changed assignments:            1 (_LOGGER)
missing assignment names:       0
```

The 102 exact matches include nested MCP tool implementations and class methods, not only
top-level helpers. `build_server` and `main` changed structurally because tool groups and the CLI
factory are now composed through internal builders while retaining their original signatures and
facade observation points. `_LOGGER` changed from `logging.getLogger(__name__)` to the explicit
`logging.getLogger("milai_mcp.server")`, preserving the effective logger name after relocation.

`test_server_core_compatibility.py` fixes facade-to-owner object identity for contracts,
middleware, wire helpers, Reader/Governance/Codex builders, the factory and CLI. Existing profile,
catalog, schema, authorization, OAuth/HTTP, wire-size, CLI and entry-point suites provide the
behavioral comparison for the two intentionally restructured orchestration definitions.

## Preserved boundaries

- `build_server()` retains its signature and returns the same MCP server type.
- Tool names, annotations, input schemas and profile catalogs are unchanged.
- Wire limits, compaction, guidance, error codes and authorization behavior are unchanged.
- CLI arguments, environment resolution and transport behavior are unchanged.
- No Runtime behavior, DB schema/migration, OpenWorker, Lab, Frozen Architecture or historical
  receipt changed.
- The C4 candidate contains only MCP internal modularization, compatibility tests, this module map
  and regenerated current Product identity.
