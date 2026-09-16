# DG-13U historical gateway header inspection v1

Status: `U0 READ-ONLY OBSERVATION / NOT U1 TOPOLOGY`  
Provider calls: `0`  
Container/network lifecycle mutations: `0`

This receipt records an exact read-only inspection of the locally pinned historical gateway. It
exists to prevent that gateway from being silently reintroduced into the DG-13U U1 provider path.

## Exact identity

- tags: `openworker-gateway-api:2026.5.8.16`, `openworker-gateway-api:2026.5.9.1`
- image ID: `sha256:535bb8b7e3b735cc24b04950449f2a70c9905273eafa7d1b322526ecdc5d3860`
- package: `@gateway/api` version `0.1.0`
- `/app/src/routes/proxy.ts`:
  `e66daf7187a8f10f784147868304861229150975493676ca36d964d55ac2dd87`
- `/app/src/services/proxy.ts`:
  `cea6fb6a0f43d649ab62ee454739dee682f37728824e342a0bea47a6fc35eb50`
- `/app/dist/routes/proxy.js`:
  `78ada0cdeb2d6b5d36e915914345856f4d051b334e7a76ede6b33996f530f49d`
- `/app/dist/services/proxy.js`:
  `ba4ac60499708ef6fbaa671fc039960751138f1293a6ba356f61c5b980444b9c`

## Deterministic finding

The `/v1/chat/completions` route parses the incoming JSON body and passes no incoming header mapping
to its upstream proxy service. The service constructs a new upstream header set containing JSON
content type and, when configured, its own authorization value. Consequently
`X-MiLAi-Host-Instance`, `X-MiLAi-Task-Session`, and `X-MiLAi-Task-Operation` are absent at the Host.

This is a static executable-path finding, not a live provider claim. It does not say that arbitrary
header forwarding would be safe. The accepted local U1 candidate instead uses the DG-13U goal's
explicit direct OpenWorker-to-Host provider network. Future gateway support would require a separate
exact three-header allowlist, authentication review, owner acceptance, and live joined evidence.
