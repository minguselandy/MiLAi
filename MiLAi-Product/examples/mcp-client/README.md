# MCP stdio client reference

The host owns the token, Scope and authority. None of them are model arguments.

```bash
MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN" \
MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}' \
../../integrations/mcp/.venv/bin/python client.py "current governed state"
../../integrations/mcp/.venv/bin/python smoke.py
```
