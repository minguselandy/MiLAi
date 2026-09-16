# UA-03 Lifecycle 与受治理写入证据

> Decision: `PASS FOR SYNTHETIC/DE-IDENTIFIED AGENT HOSTS`

`AgentMemory` implements session start, mandatory before-model recall, user/tool observation,
on-demand recall, model-output discard, pre-compaction protected ContextCapsule and session-end
Episode references. Capture modes are exactly `OFF`, `ASK_EACH_TIME` and `ALLOWLISTED`.

Safety properties:

- assistant/model output, full prompt, raw log, credential-like content and sensitive sources are
  never Evidence in any mode;
- hook replay reuses the same operation ID, observed time and payload;
- user/tool capture creates Evidence only; Proposal creation is separate and always pending review;
- trusted host code may classify an allowlisted tool observation as `RUNTIME_OBSERVATION` for an
  existing discharge rule; the model cannot review it;
- source permission snapshots are explicitly readable and classified before they can ground a
  reviewed Claim;
- session end creates an idempotent Episode of references, reports pending Proposal IDs/review URL
  and never creates Settlement.

Python-client lifecycle/contract tests are included in the `20 passed` package gate. The real
three-session fixture uses the LangGraph capture node twice for independent CI/runtime Evidence,
then proves review is still required and revocation reopens the same issue.
