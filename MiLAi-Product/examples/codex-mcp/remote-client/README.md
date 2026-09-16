# MiLAi Codex remote registration bundle

This bundle registers an existing Codex installation with the remote MiLAi `codex-full`
Streamable HTTP endpoint. It contains no Bearer token, Runtime credential, database setting or
server package.

This is a deployment-neutral package. The server operator must provide the exact endpoint:

```text
https://<your-milai-host>/mcp
```

## Requirements

- Codex CLI with `codex mcp add` support;
- Python 3.11 or newer for the protocol-level verifier;
- a MiLAi inbound Bearer token transferred separately over a secure channel.

## Install on Linux or macOS

Extract the archive and verify the supplied archive checksum before continuing. Put the separately
transferred token in a private file, then run:

```bash
chmod 600 /secure/path/codex-full-public.token
./install.sh \
  --url https://<your-milai-host>/mcp \
  --token-file /secure/path/codex-full-public.token
```

The installer performs a real authenticated MCP `initialize` and `tools/list` before changing the
Codex registry. It expects the exact 13-tool `codex-full` catalog. It then:

1. registers `milai` in Codex with `bearer_token_env_var = "MILAI_CODEX_TOKEN"` so
   Codex configuration output cannot reveal the credential;
2. writes an equivalent valid `mcpServers` JSON file to
   `${XDG_CONFIG_HOME:-$HOME/.config}/milai/mcpServers.json`;
3. sets both configuration files to mode `0600`.

Start Codex with the token provided through the named environment variable:

```bash
MILAI_CODEX_TOKEN="$(tr -d '\r\n' < /secure/path/codex-full-public.token)" codex
```

## Existing registration

The installer is idempotent when the existing registration has the same URL. It refreshes the
headers without creating another registration. It refuses to overwrite a different URL unless
`--replace` is supplied.

```bash
./install.sh \
  --url https://<your-milai-host>/mcp \
  --token-file /secure/path/token \
  --replace
```

## Manual registration

The equivalent Codex TOML and cross-client JSON forms are in `config.toml.example` and
`mcpServers.json.example`:

```json
{
  "mcpServers": {
    "milai": {
      "type": "http",
      "url": "https://<your-milai-host>/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

The generic JSON file contains the token and must remain private. Codex TOML stores only the
environment-variable name. Do not put token material in a repository, chat, logs or the
registration archive. The unique Bearer credential maps to one server-owned principal; clients
cannot select a principal through headers or tool arguments.

`mcpServers` is a common client configuration shape, not an MCP protocol message and not a
cross-client standard. Codex's native registration format is TOML/CLI. For a shell-managed Token:

```bash
export MILAI_CODEX_TOKEN='<server-issued-token>'
codex mcp add milai \
  --url https://<your-milai-host>/mcp \
  --bearer-token-env-var MILAI_CODEX_TOKEN
```

Unlike an OAuth-enabled HTTPS service, this static-token deployment cannot securely support
URL-only `codex mcp add ... --url ...` onboarding.

For a direct-IP development deployment, use `http://<public-ip>:<port>/mcp` and pass
`--allow-insecure-http`. This remains standard Streamable HTTP MCP, but the transport is not
confidential. If a local HTTP proxy returns 502 for that IP, set `NO_PROXY=<public-ip>` only for
the verifier/Codex process.

## Verify again

```bash
MILAI_CODEX_TOKEN="$(tr -d '\n' < /secure/path/token)" \
  python3 verify_mcp.py --url https://<your-milai-host>/mcp
```

Successful output includes:

```text
authenticated=true
tool_count=13
catalog=codex-full-v1
```

## Uninstall

```bash
./uninstall.sh
```

This removes the Codex registration and generated `mcpServers.json`. It does not delete the
separately supplied source token file.

## Security boundary

HTTPS is the default. `--allow-insecure-http` is available only for a trusted loopback/private
development endpoint and explicitly acknowledges that an on-path observer could steal the Bearer
token. This bundle does not add WebSocket support; MCP streaming uses standard HTTP/SSE.
