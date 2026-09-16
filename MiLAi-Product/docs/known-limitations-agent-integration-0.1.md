# Agent Integration 0.1 known limitations

- Logical Architecture `1.0.0` is frozen, but Runtime is `0.1.x CANDIDATE` and Schema is
  `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
- Local loopback Runtime plus authenticated loopback Streamable HTTP MCP and stdio compatibility.
  No TLS/OAuth, non-loopback HTTP MCP, browser extension or public SaaS.
- Single trusted orchestrator identity. No per-Agent RLS, delegation or autonomous multi-Agent
  canonical arbitration.
- Real personal data remains disabled despite implemented crypto. User approval and independent
  environment-specific recovery acceptance are missing.
- Candidate extraction is optional and off by default; no model is trusted to create or review
  canonical truth automatically.
- ONNX quality/latency is measured on one fixture/device and is not an SLO. External embedding is
  disabled and requires separate privacy consent.
- Stdio protocol compatibility is verified for `2026-07-28` and `2025-11-25`; the P08 Codex product
  route uses the SDK's Streamable HTTP endpoint with one process-bound Bearer principal.
- Local bearer tokens are environment-configured transitional credentials. They have no durable
  token registry, remote revocation or per-device identity.
- Database migrations from 0015 onward are forward-only. Recovery uses fresh replay, verified
  restore and forward repair, not destructive downgrade.
- Packages are local artifacts. MiLAi has no public distribution license, so this release is not a
  permission to publish them.
- Agent execution optimization remains a local/synthetic Candidate. No target LLM provider has yet
  supplied native input/cached-input/output usage, billing reconciliation, post-ready first-query
  evidence, or a same-task/same-model baseline-versus-optimized quality run. A fail-closed,
  privacy-bounded provider A/B runner and billing reconciliation protocol now exist. Its v2 local
  security remediation is not itself provider evidence: it never emits PASS and has not been
  executed with an approved provider/model or independently accepted for OE-F06.
