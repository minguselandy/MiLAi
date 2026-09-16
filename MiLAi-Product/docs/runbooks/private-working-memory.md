# Private working memory in Codex

Use the existing [private OAuth connection](aigcit-http-mcp.md) with the ordinary
read, State write and Evidence capture scopes. Users receive separate private
memory based on the verified issuer and subject. No manual user allowlist is needed.

The initial product supports one selected workflow per user's default TASK binding.
It does not automatically separate repositories or tasks. Check that restored memory
belongs to the work you are doing; do not overwrite an unrelated workflow silently.

## Ordinary plugin use

After configuring `milai`, start a normal Codex task, then start a new Codex process
for continuation. Preserve the project files. Do not use `exec resume` when testing
cross-session memory recovery. The ordinary memory tools are State get/update, memory
resolve, Evidence capture and exact Claim get; Claim get is not Evidence full-text get.
The full 0.1.6 profile also supports proposals, review, revocation and private cleanup
when the matching OAuth scopes are granted. These operations retain their explicit
current-user intent and project-isolation requirements.

The [working memory configuration](../../examples/codex-mcp/milai-private-workflow.toml.example)
puts the recovery and selective-save convention in developer instructions. Merge it
with existing instructions and configuration. This is a model activation hint, not a
guarantee: the tested local Qwen/Codex combination still skipped memory access with
this configuration. Ordinary file-based task success does not prove memory recovery.

## Host-managed recovery through an existing HTTP MCP

MCP package 0.1.5 adds an existing-connection mode to the `milai codex` launcher:

```bash
milai codex --cwd /path/to/project \
  --mcp-url https://milai.aigcit.com:7960/mcp \
  --mcp-token-env MILAI_MCP_BEARER_TOKEN \
  -- exec "Continue the current project task."
```

Supply the ordinary client's authorized bearer credential through that environment
variable using your credential tooling; do not put it in the command or a chat.
This mode currently accepts a bearer credential, and does not obtain or refresh an
OAuth token from Codex's private credential store. Existing `codex mcp login` and
ordinary OAuth plugin use remain separate supported client operations. A deployment
claim for this new launcher requires its dedicated real-client acceptance.

The launcher reads TASK through the same public MCP, then places the bounded result
in Codex's startup context as untrusted, non-canonical data. It preserves existing
developer instructions, delegates identity/workflow to the server and never starts
a private full-control server. No Runtime credential, database ID, source seeding or
automatic memory write is involved. Prefetch failures stop before Codex starts;
ABSENT is a normal response. HTTPS is required except for loopback test connections.

Run the same command in a new process for a later task. The read is attributed to
the Host. The model still chooses subsequent lookups, corrections and saves. A
successful Host read alone is not proof that the model used the memory correctly.

Trusted Host integrations can use the published Python entrypoint instead:

```python
from milai_mcp import prepare_http_working_context

prepared = await prepare_http_working_context(
    mcp_url, bearer_token, max_bytes=24576, timeout_seconds=20
)
# prepared["state"] is the public read receipt; prepared["context"] is the
# bounded, escaped data presentation. Record trigger == HOST_LIFECYCLE.
```

This helper does not choose a business schema, rewrite memory, infer task completion,
refresh credentials or change server permissions. It returns the State and context
only after successful MCP retrieval and existing bootstrap validation.

## Saving, correcting and checking

Save useful constraints, decisions and unfinished work using the current version and
a fresh operation ID. Preserve unrelated correct content. A no-change check normally
needs no write. Keep the operation receipt distinct from a later GET of current head:
an unknown submission is not proved successful by matching current content.

If a tool reports a conflict, failure or unknown result, report that outcome rather
than saying it was saved. After a correction, a new process must restore the newer
version and use the corrected requirement before a dependent action.

Schema remains **0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE**.
