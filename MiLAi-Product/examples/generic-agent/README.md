# Generic async Agent example

The host keeps `MILAI_AGENT_TOKEN`; the model receives only the `data-only` memory block. Run a
real local query with the reader token and fixed host scope. The example uses the deterministic
router, a maximum recall limit of three, a replaceable memory slot, and a persistent async HTTP
client:

```bash
MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN" \
MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}' \
../../integrations/python-client/.venv/bin/python agent.py "current governed preference"
```

Offline executable smoke:

```bash
../../integrations/python-client/.venv/bin/python smoke.py
```

In a real model host, inject its exact tokenizer through `CallableTokenCounter`; without one MiLAi
keeps byte limits and reports token usage as unverified instead of estimating provider billing.
