# HTTP-PUBLIC-01 remote registration package audit

> Executed: `2026-09-04 14:32:17 +08:00`  
> Artifact: `milai-codex-remote-client-0.1.2.tar.gz`  
> Terminal: `REMOTE_REGISTRATION_PACKAGE_READY`

## Artifact identity

```text
path:
  integrations/mcp/dist/remote-client/milai-codex-remote-client-0.1.2.tar.gz

sha256:
  28a789c600656ad3110f5fe67aa6d1303161ccc934e301ffdaaffd439849f9e5
```

The adjacent `.sha256` file uses the archive basename, so verification still works after transfer
to another directory or machine.

## Scope

This is one remote registration package, not a Runtime/server installer. It contains:

```text
README.md
config.toml.example
configure_clients.py
install.sh
mcpServers.json.example
verify_mcp.py
uninstall.sh
MANIFEST.sha256
```

The package contains no inbound Bearer token, Runtime role token, database URL, tenant identity,
project authority or service configuration. The server token must be transferred separately over a
secure channel.

## Verified behavior

```text
archive SHA-256                              PASS
all packaged-file SHA-256 entries            PASS
real server-token byte scan                  absent
shell syntax                                  PASS
Python compile / Ruff                         PASS
insecure HTTP without explicit acknowledgement REJECT
authenticated public MCP initialize           PASS
negotiated protocol                           supported
exact codex-full tools/list                    13
fresh empty CODEX_HOME install                 PASS
same registration reinstall                   idempotent
Codex TOML direct static headers               PASS / mode 0600
generic mcpServers JSON                        PASS / mode 0600
Codex process with MILAI_CODEX_TOKEN unset     PASS
uninstall removes generated registration       PASS
public service ready after packaging           HTTP 200
```

## Failure reflection

- The first verifier required the requested MCP protocol version to equal the negotiated version.
  The server correctly selected `2025-11-25`; the verifier now accepts only an explicit supported
  negotiation set and still rejects unknown versions.
- The first isolated install exposed that a newly configured but absent `CODEX_HOME` is rejected by
  Codex. The installer now creates the directory with mode `0700` before inspecting or adding MCP
  registrations.
- Static analysis found a non-executable source shebang and an overly broad response-type
  exception. Both were corrected before archive creation.
- The first package used `bearer_token_env_var`, which caused a new Codex process without inherited
  `MILAI_CODEX_TOKEN` to reject the MCP at startup. Version 0.1.2 instead installs static
  `Authorization` and `x-agent-id` headers in private Codex TOML and emits the equivalent valid
  `mcpServers` JSON. A real Codex process passed with the environment variable explicitly unset.
- One test initially inspected direct header fields at the top level of `codex mcp list --json`;
  the CLI nests them under `transport`. The assertion was corrected without changing Product code.

Invalid intermediate archives were not retained as the delivery artifact.

## Remote install

```bash
sha256sum -c milai-codex-remote-client-0.1.2.tar.gz.sha256
tar -xzf milai-codex-remote-client-0.1.2.tar.gz
cd milai-codex-remote-client-0.1.2
./install.sh --token-file /secure/path/token --agent-id user-a --allow-insecure-http
codex
```

The explicit insecure-HTTP acknowledgement is required because the current public endpoint does
not terminate TLS. WebSocket is not included; MCP streaming remains HTTP/SSE.
