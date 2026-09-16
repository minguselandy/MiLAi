# AutoGen Memory reference

MiLAi is an official AutoGen `Memory` implementation. `query/update_context` append a user-data
message; `clear()` is prohibited and `add()` requires an explicitly confirmed user/tool source.

```bash
MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN" \
../../integrations/autogen/.venv/bin/python agent.py "current governed state"
../../integrations/autogen/.venv/bin/python smoke.py
```
