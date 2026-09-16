# LangGraph reference

`milai_recall` runs before the model and `milai_context` builds protected OpenIssue data. The
LangGraph checkpoint remains framework-owned and contains only MiLAi references.

```bash
MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN" \
../../integrations/langgraph/.venv/bin/python agent.py "current runtime"
../../integrations/langgraph/.venv/bin/python smoke.py
```
