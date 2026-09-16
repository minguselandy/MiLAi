# OE-07 provider evidence protocol remediation — candidate.4.4

Status: `READY FOR INDEPENDENT RE-REVIEW — NOT PROVIDER EVIDENCE`  
Date: `2026-08-18` (Asia/Shanghai)  
Boundary: local synthetic fixtures only; no provider credential, external model request or billing
object was used. Runtime remains `0.1.x CANDIDATE`; Schema remains
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.

## Outcome

Candidate.4.4 replaces the candidate.3 provider evidence protocol that independent review rejected.
It does not alter the accepted candidate.2 optimization algorithm, Runtime, database Schema or frozen
Logical Architecture. It closes the local implementation paths behind OE-C3-F01–F07, but does not
claim that those findings are closed until independent re-review reproduces the evidence.

The candidate.4.1 identity was withdrawn before a decision when pre-review found that reconciliation
did not re-assert the exact five-field `normalized_output` schema. Candidate.4.2 adds that closed
schema check and an adversarial report with a fresh attacker-supplied report digest. Candidate.4.2
was then withdrawn when review found that arbitrary credential environment names could select an
interpreter or loader startup control. Candidate.4.3 permits only the inert
`MILAI_PROVIDER_CREDENTIAL_*` alias namespace, rejects native/control names, and invokes the
privileged sandbox Python with `-I -S`.

Candidate.4.3 then received an independent `REVISE` because its successful fixture invoked a host
program absent from the declared dependency lock. Candidate.4.4 binds the Landlock read/execute
policy in approval and plan, requires ABI 1 or newer, permits only runtime/source/declared dependency
bytes, includes the fixture's Bash, `sed` and transitive dynamic dependencies, and proves that an
undeclared host executable fails closed.

No tool-produced state is `PASS`. A complete capture is
`PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED`; matched billing is
`PROVIDER_EVIDENCE_RECONCILED_REVIEW_REQUIRED`; both CLI commands atomically write the artifact and
exit `3`. `provider_usage_verified` remains false. Only a later independent decision over an
approved real provider run may close external `OE-F06`.

## Remediation matrix

| Prior finding | Candidate.4.4 implementation | Adversarial acceptance evidence |
| --- | --- | --- |
| OE-C3-F01 P0, forged reconciliation | Closed report schemas including the exact five-field normalized output; exact 1,000 ordered records; deterministic request/prompt/tool/output/native identities; quality, usage, cost, aggregates and complete gates recomputed; report/approval/plan digests supplied out of band; normalized and actual upstream artifacts separately opened/hashed; approval-only tolerance/cost ceiling; no PASS state | empty gates, shortened report, forged score and an extra normalized-output field all fail even when the attacker supplies the newly computed report hash; missing upstream and caller tolerance fail; a complete mock reconciliation remains review-required/exit 3 |
| OE-C3-F02 P0, decoy/unbound execution | No manifest command/argv. One exact runtime, source and dependency closure are approval-bound. Runtime/source/tool bytes execute through open FDs; dependencies are copied from verified FDs and bind-mounted; Landlock handles `READ_FILE/EXECUTE` and permits only source/runtime/declared targets; open FDs are rehashed after execution | closed manifest rejects added command/credential argv; wrong approval or plan digest fails before adapter start; positive fixture enumerates Bash, `sed` and dynamic closure; an undeclared host executable and undeclared host file read fail closed |
| OE-C3-F03 P0, secret/filesystem escape | Distinct non-root uid/gid, `no_new_privs`, private mount/PID/network namespaces and private `/proc`/tmpfs. Workspace, `/root`, homes, run sockets, var data/log/tmp, srv/mnt/media/opt/dev-shm are hidden. Credentials use only the inert `MILAI_PROVIDER_CREDENTIAL_*` alias namespace; Python startup is `-I -S`. Minimal environment, static hosts, DNS disabled, deny-all or default-drop TCP/443 IP allowlist. Known parent/Runtime/provider secret values are recursively rejected from all adapter responses | fixture asserts uid 65534 and fails if workspace/root is visible; PG, Python, loader, shell and Node control names are rejected before startup; provider-secret reflection returns privacy-bounded FAIL_PARTIAL with no value; deny-all and a local 10.0.2.2:443 allowlist path both execute; non-approved 1.1.1.1 cannot connect in deny-all |
| OE-C3-F04 P1, post-call authorization | Approval binds workload/pricing/tokenizer/tool schemas/manifest/closure/egress/input/output/cost/tolerance. Plan digest binds exact selected limits. Every full request is target-tokenized before model call; input cap and maximum output-cost reservation are enforced before charge; provider input must equal pre-count and actual/reserved/final billing must remain within approval | oversized target count produces zero model calls; wrong plan digest produces zero adapter starts; output/input/native usage and total cost are independently validated |
| OE-C3-F05 P1, fake schemas/rounds | Catalogs are derived directly from inventory-bound `create_milai_tools(profile=reader/reader-lite)`; baseline is six shipped definitions and optimized is the shipped one-tool catalog. Each logical result carries every native call ID, usage, terminal state, closed finish reason and native receipt digest; aggregate usage must equal native sum and billing covers the global native-ID root | exact catalog equality test; hidden extra native call with mismatched sum and non-terminal state fail. Hard-coded fixture output can exercise the protocol but remains unverified/review-required |
| OE-C3-F06 P1, missing CI | The Python-client CI matrix now has an exact provider protocol step: installs namespace/network tools, syncs the locked Runtime environment, checks Ruff format/lint and strict mypy, then runs provider, benchmark and release-safety tests under root with no provider secret | workflow parses as YAML; the same local commands pass 42/42. No hosted CI run is claimed by this local report |
| OE-C3-F07 P2, blocking timeout/no receipt | Binary nonblocking input/output uses one monotonic deadline and a 2 MiB response cap. Timeout terminates the process group/PID namespace. Failure after process start returns an atomically writable FAIL_PARTIAL record containing only validated IDs/cost/hash state and a reason digest | oversized input with a non-reading adapter and one-byte/no-newline output both respect the deadline; a fourth-call stall retains exactly three validated records/native IDs/cost; atomic writer leaves one complete JSON object and no temporary residue |

## Isolation and trust details

The launcher performs privileged setup only. It creates a fresh tmpfs, copies the approved source
from its open FD, pins each dependency byte into the private mount namespace, replaces hosts/resolver,
hides host data roots, drops groups/gid/uid, and waits on a parent start-gate. For allowlisted runs,
the parent attaches slirp and installs nftables default-drop rules before releasing that gate; there
is no pre-firewall adapter race. Runtime/source/dependency FDs are close-on-exec, so provider code
does not inherit the trust handles.

The allowlist tools (`unshare`, `slirp4netns`, `nsenter`, `nft`, `ip`), sandbox runtime and launcher
are approval-bound and executed through their verified FDs where applicable. DNS is not available;
the exact approved provider hostname is statically mapped to the sorted approved IP set. Proxy
variables are not inherited.

The dependency lock is a closed structured list whose paths and bytes are independently approval
bound and pinned. An operator/reviewer still must demonstrate that a real provider adapter's listed
closure is complete; this local fixture locks Bash, `sed` and every discovered dynamic `ldd`
dependency. Landlock makes missing declarations observable rather than silently falling back to host
bytes. Kernel and privileged namespace/network helpers remain part of the operator-approved host TCB;
a real-provider review must additionally bind its immutable host/container image identity.

## Reproduced gates

| Gate | Result |
| --- | --- |
| Provider protocol + deterministic benchmark + release safety | 42/42 PASS in 95.36 s (`28 + 4 + 10`) with pytest cache/bytecode disabled |
| Provider static | Ruff format/check PASS; mypy strict PASS for runner and launcher |
| Python client | Ruff format/check PASS; mypy PASS; 76/76 tests PASS |
| Non-repository cwd | full 1,000-call isolated capture PASS from `/tmp` in 9.32 s |
| Frozen Logical Architecture | validate PASS; release external-anchor lock PASS; 19 tests PASS with one expected Git-scope skip |
| Archive-aware secret scan | PASS; 361 files, 296 archive members, 17 local secret values, zero match/forbidden/unsafe artifact |
| CI syntax | checked-in workflow parsed as YAML; provider gate is present in the Python-client matrix |

The exact candidate.4.4 core bytes before inventory generation were:

| Artifact | SHA-256 |
| --- | --- |
| `evals/agent_efficiency/provider_ab.py` | `ca8569cb388db5a8bc652c2f531a397be82b9d00994417e5a5e596adc6a0fb6e` |
| `evals/agent_efficiency/provider_sandbox_exec.py` | `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4` |
| `evals/agent_efficiency/test_provider_ab.py` | `1554ce63f815f54cd4d6a9b4693afbc577c8f9bbe6c86a55e589b72db1e2cbab` |
| `evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md` | `9602fdc3dc38a80c096461cca63e606bb33b76d5de654dc2841242cbf4d6e69a` |
| frozen provider workload | `ab5cac3c660835ad1beda1cac56e32b893af476f77b3fb987d4f59d3b8e827e0` |
| `.github/workflows/ci.yml` | `be5cef4a6a7283e3c5aba00c38f7099533e99654da0a4f269728c3ad14838e97` |

The inventory generated after this report is the authoritative full-byte identity for independent
review. Frozen/package anchors remained unchanged:

- Logical Architecture manifest:
  `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`
- integration package release manifest:
  `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`

## Remaining external gate

`OE-F06` remains OPEN. Candidate.4.4 contains no approved provider/model, provider adapter approval,
real native receipt, target-provider billing export, first normal post-ready query, or same-model
external quality result. Those facts are absent, not zero. Beta remains NO-GO until a real 1,000-call
run, external objects and a separate independent acceptance record exist.
