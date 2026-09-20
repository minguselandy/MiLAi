# MiLAi module inventory

Source commit: `798b7cac21957873791afff6122d3f06a82214c5`

## Counts

| Metric | Count |
| --- | ---: |
| Python production files | 804 |
| Python test files | 483 |
| Pytest top-level nodes | 3517 |
| Receipt-referenced pytest node IDs | 29 |
| Files >= 30 KB | 83 |
| Files >= 60 KB | 17 |
| Files >= 100 KB | 7 |

## Largest active Python files

| Bytes | Path |
| ---: | --- |
| 195742 | `MiLAi-Product/runtime/src/milai/application/retrieval.py` |
| 178277 | `MiLAi-Product/integrations/mcp/src/milai_mcp/server.py` |
| 160854 | `MiLAi-Product/integrations/openworker-mcp/src/milai_openworker_mcp/host/orchestrator.py` |
| 153970 | `MiLAi-Product/runtime/src/milai/application/memory_context.py` |
| 121941 | `MiLAi-Product/runtime/tests/integration/test_runtime_foundation.py` |
| 113775 | `MiLAi-Product/runtime/tests/integration/test_projection_worker.py` |
| 108810 | `MiLAi-Product/integrations/openworker-mcp/tests/test_host_adapter.py` |
| 92646 | `MiLAi-Product/integrations/mcp/tests/test_profiles.py` |
| 89081 | `MiLAi-Product/runtime/src/milai/application/evidence_acquisition.py` |
| 86535 | `MiLAi-Lab/tools/run_product05_openworker_lme.py` |
| 78198 | `MiLAi-Product/runtime/tests/integration/test_retrieval_api.py` |
| 76137 | `MiLAi-Product/runtime/src/milai/application/query_operators.py` |
| 70031 | `MiLAi-Product/runtime/src/milai/application/query_task_compiler.py` |
| 64289 | `MiLAi-Product/integrations/python-client/src/milai_client/models.py` |
| 64236 | `MiLAi-Product/runtime/src/milai/persistence/retrieval_repository.py` |
| 63263 | `MiLAi-Lab/tools/run_product10_context.py` |
| 62512 | `MiLAi-Product/runtime/src/milai/application/evidence_semantics.py` |
| 58205 | `MiLAi-Product/integrations/python-client/src/milai_client/optimization.py` |
| 55205 | `MiLAi-Product/integrations/python-client/tests/test_client_contract.py` |
| 53424 | `MiLAi-Lab/tools/run_product05_lifecycle.py` |
| 51958 | `MiLAi-Lab/src/milai_lab/methods/adaptive_memory.py` |
| 51392 | `MiLAi-Product/runtime/src/milai/application/memory_query.py` |
| 51347 | `MiLAi-Product/tools/verify_architecture_conformance.py` |
| 50736 | `MiLAi-Product/runtime/src/milai/observability/retrieval_audit.py` |
| 48627 | `MiLAi-Lab/tools/run_product02_context_gate.py` |
| 48468 | `MiLAi-Product/runtime/src/milai/application/memory_resolve.py` |
| 48152 | `MiLAi-Product/integrations/mcp/src/milai_mcp/oauth_provider.py` |
| 46936 | `MiLAi-Product/runtime/src/milai/application/context_preparation.py` |
| 45849 | `MiLAi-Lab/tools/run_product02_longmemeval.py` |
| 43539 | `MiLAi-Lab/src/milai_lab/methods/controlled_workspace.py` |
| 43050 | `MiLAi-Lab/tools/run_product01_s4_longmemeval.py` |
| 42905 | `MiLAi-Lab/tools/v0218_checker.py` |
| 42611 | `MiLAi-Product/integrations/python-client/src/milai_client/client.py` |
| 42158 | `MiLAi-Lab/tools/run_v02_local_vllm.py` |
| 40906 | `MiLAi-Product/integrations/python-client/src/milai_client/context_policy.py` |
| 40255 | `MiLAi-Product/runtime/tests/unit/test_dg17_memory_context.py` |
| 40246 | `MiLAi-Lab/src/milai_lab/product11_subagent.py` |
| 39847 | `MiLAi-Lab/tools/check_v02_e2e_live.py` |
| 39779 | `MiLAi-Product/runtime/tests/unit/test_retrieval_fusion.py` |
| 39601 | `MiLAi-Product/integrations/mcp/tests/test_codex_full_http_smoke.py` |

## Entrypoints

| Name | Target | Source |
| --- | --- | --- |
| `milai-api` | `milai.api.cli:main` | `MiLAi-Product/runtime/pyproject.toml` |
| `milai-context-testkit` | `milai.testkit.cli:main` | `MiLAi-Product/runtime/pyproject.toml` |
| `milai-db-check` | `milai.persistence.cli:main` | `MiLAi-Product/runtime/pyproject.toml` |
| `milai-ops` | `milai.operations.cli:main` | `MiLAi-Product/runtime/pyproject.toml` |
| `milai-retrieval-trace-testkit` | `milai.testkit.retrieval_trace_cli:main` | `MiLAi-Product/runtime/pyproject.toml` |
| `milai-worker` | `milai.workers.main:main` | `MiLAi-Product/runtime/pyproject.toml` |
| `milai-hook` | `milai_hooks.cli:main` | `MiLAi-Product/integrations/hooks/pyproject.toml` |
| `milai-hook-config` | `milai_hooks.config:main` | `MiLAi-Product/integrations/hooks/pyproject.toml` |
| `milai` | `milai_mcp.launcher:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-agent-memory-mcp` | `milai_mcp.agent_memory:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-codex-full-mcp` | `milai_mcp.codex_full:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-codex-user` | `milai_mcp.remote_registration:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-mcp` | `milai_mcp.server:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-oauth-readiness` | `milai_mcp.deployment_readiness:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-oauth-user` | `milai_mcp.oauth_admin:main` | `MiLAi-Product/integrations/mcp/pyproject.toml` |
| `milai-mcp-broker` | `milai_openworker_mcp.broker:main` | `MiLAi-Product/integrations/openworker-mcp/pyproject.toml` |
| `milai-mcp-relay` | `milai_openworker_mcp.relay:main` | `MiLAi-Product/integrations/openworker-mcp/pyproject.toml` |
| `milai-openworker-adapter` | `milai_openworker_mcp.host_adapter:main` | `MiLAi-Product/integrations/openworker-mcp/pyproject.toml` |
| `milai-lab-check-boundary` | `milai_lab.boundary:main` | `MiLAi-Lab/pyproject.toml` |
| `milai-lab-verify-product` | `milai_lab.product_adapter.manifest:main` | `MiLAi-Lab/pyproject.toml` |

## Compatibility facades

| Category | Path |
| --- | --- |
| `PUBLIC_COMPAT` | `MiLAi-Product/integrations/openworker-mcp/src/milai_openworker_mcp/host_adapter.py` |

## Receipt node compatibility

All `29` referenced node IDs are present: `YES`

The complete node set, public-import surfaces, module import graph, and Lab→Product imports are in [`module-inventory.json`](module-inventory.json).

## Lab → Product imports

`9` active Lab files contain Product-package imports. These are baseline observations, not newly approved private dependencies:

- `MiLAi-Lab/tools/check_v02_mixed_load.py` → `milai_client`
- `MiLAi-Lab/tools/check_v02_private_http_load.py` → `milai_client`, `milai_mcp`, `milai_mcp.aigcit_auth`, `milai_mcp.auth_policy`, `milai_mcp.http_transport`, `milai_mcp.server`
- `MiLAi-Lab/tools/check_v02_scoped_recall.py` → `milai_client`
- `MiLAi-Lab/tools/check_v02_service_concurrency.py` → `milai_client`
- `MiLAi-Lab/tools/run_product05_lifecycle.py` → `milai_client`, `milai_openworker_mcp.memory_facade`, `milai_openworker_mcp.transport`
- `MiLAi-Lab/tools/run_reasoningbank_public_checkpoint.py` → `milai_client`
- `MiLAi-Lab/tools/run_workspace_public_checkpoint.py` → `milai_client`
- `MiLAi-Lab/tools/v02_lme_capture_worker.py` → `milai_client`, `milai_hooks.agent_event`
- `MiLAi-Lab/tools/v06_http_bootstrap.py` → `milai_mcp`

## Scope notes

- `MiLAi-Lab/studies/archive/**` is deliberately excluded and remains immutable.
- Build, virtual-environment, cache, and distribution directories are excluded.
- Inventory is observational and uses only Python's standard library.
