# MiLAi Agent Execution Optimization 0.1 独立验收

Decision: **REVISE**

Reviewer identity: /root/af09_independent_review  
Independence: separate no-history sub-agent; did not author candidate  
Review start: 2026-08-18T06:28:13Z / 2026-08-18T14:28:13+08:00  
Record prepared: 2026-08-18T06:57:10Z / 2026-08-18T14:57:10+08:00  
Environment: Linux 5.15.0-86-generic x86_64; CPython 3.11.13; Ruff 0.16.3; mypy 1.20.2; pytest 8.4.2; PostgreSQL/pgvector local exact-role environment.

## 1. 独立结论

当前候选不能通过 OE-07，也不能使用设计文档 §20 的最终发布叙事。结论不是由作者矩阵的 PARTIAL 状态推导，而是由当前源码、当前保留包和独立重放得到：

- 两个开放 P0：正常 cache 复用不绑定 host policy/budget，能够跨 scope 保留旧 slot；coding hook 的 stdin event payload 能覆盖环境固定的 scope/authority/consistency。
- 四个开放 P1：OpenIssue 的 transport request_id 使语义不变的 cache 永不命中；Compiler 接受伪造/不完整 OpenIssue minimum；Router 报告 L0 但显式 UUID 实际走 L1；真实 provider/token/billing/cold-query/同模型质量证据缺失。
- 一个开放 P2：PostgreSQL scale runner 的 Alembic 路径依赖未声明的当前工作目录，且没有保留 raw JSON。

与此同时，基础工程门禁是真实可复现的：fresh exact-role Runtime 152/152、三会话 Agent E2E、10k/100k scale、六个 wheel clean install、archive-aware scan、包级静态检查和测试均通过。它们不能抵消上述 policy/cache 与发布证据门。

允许的当前边界仅为：**local synthetic/de-identified Optimization Candidate**。不允许晋级 Beta/Production，不允许声称 provider-exact 或 bounded release 已完成。Runtime 仍为 CANDIDATE；Schema 仍为 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE；frozen Logical Architecture 1.0.0 bundle 本身保持不变并通过 bundle-scope release lock。

## 2. 候选身份与无漂移基线

审查开始及最后一次写入 review 前，独立结果均为：

| Artifact | SHA-256 / identity |
| --- | --- |
| OE inventory file | 32c15cd82f364728682f6b4fe64333c670e43a3715afffb9212b683347f01294 |
| Canonical inventory entries root | 31bbc18a6d819e1a00792e26bc87b2d84db32cfd0abfb599b71634de588e1606 |
| Entry count | 342 |
| OE design | 8c1f9fcd1cae31fe78029fced998c4587d712db18cc6e8a54e3483200b5de014 |
| Implementation evidence | fbc1e87529c91dae64a461930083d7aa11d326e590102f7e192745b9c58b2f39 |
| Requirements matrix | 1c97fa99d21317a496a498c801c9715309c89a7ada1e00af2f89c09d2fe20750 |
| Package release manifest | d88b17ca65c0fd29b7ac445929222067acb4370a530a8b006388f6ebe0ec8146 |
| Frozen architecture manifest | ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e |

独立枚举没有调用 inventory builder 的输出作为真值：重新遍历声明 roots，逐项重算 size/SHA、排序、唯一性和 canonical JSON root；结果与 342 个 inventory entries 完全相等。顶层分组为 .github 1、.gitignore 1、AGENTS 1、两份 Agent/OE design 各 1、architecture 19、contracts 4、docs 76、evals 14、examples 12、integrations 61、runtime 143、scripts 6、tests 2。未发现绝对路径、..、反斜杠逃逸、symlink、live .env、venv 或 cache entry。

本 review 位于 docs/reviews，明确不属于候选 inventory scope。

## 3. Findings

### OE-F01 — P0 — Cache 没有绑定 host policy、budget 或可信验证来源

Artifacts:

- MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:550-577、1411-1416、1505-1506
- integrations/python-client/src/milai_client/optimization.py:325-354、388-424、1061-1079
- integrations/python-client/src/milai_client/lifecycle.py:155-225、273-283
- integrations/python-client/src/milai_client/async_context.py:60-130、176-188
- integrations/python-client/tests/test_optimized_lifecycle.py:132-143

Evidence:

1. DeterministicRecallRouter.cache_key() 包含 scope/authority/consistency，但全仓运行源码没有调用它；只有单元测试调用。
2. MemorySlot 不保存该 policy digest。memory_slot_cache_valid() 只比较 canonical position 与 full-raw Issue digest。
3. 正常自动复验反例：首轮 scope A + INFORMATIONAL/EVENTUAL 取得对象 v-A；同 session、同 query 的第二轮改为 scope B + ACTION_SAFE/CANONICAL_REQUIRED。canonical position 未变且无 Issue 时，第二轮返回 CACHE/UNCHANGED，recall 总数仍为 1，slot 仍保存 v-A。
4. 公开参数 cache_validated=True 可完全跳过 _validate_slot_cache。先把 canonical 7→8、Issue revision 1→2，再传该参数，结果仍是 CACHE/UNCHANGED、无 recall、旧 content hash 保留。
5. Budget 反例：首轮 slot 为 1482 个 chars.v1 token；同 query 第二轮把 max_memory_tokens 改为 256，仍 CACHE/UNCHANGED，metrics 报 0，实际 registry slot 仍为 1482 token。

Impact:

这是跨 scope 保留旧模型上下文的 host-policy 边界破坏；同时 authority/consistency、tokenizer/compiler/budget 变化不失效，且 caller assertion 可把 stale canonical/Issue 状态伪装成已验证。它直接否定 OE-02/OE-03、OG-04/OG-11 及 DoD 3/6/7/8。

Required change:

- 让 slot 持有并校验不可伪造的 policy/cache binding，至少覆盖 query/goal、scope、authority、consistency、canonical position、Issue semantic revision、router/compiler policy version、tokenizer、budget class/ceiling 与 TTL。
- 不接受 public boolean 作为验证事实；只能使用内部 validator 产生且与当前输入绑定的结果。CANONICAL_REQUIRED 无法复验时必须 recall/abstain，不能 CACHE。
- policy/budget 变化时 REMOVE 或重新 recall/compile；不得将旧 block 计为 0 后继续保留。
- 为 sync、async、hook checkpoint、LangGraph、AutoGen 添加 scope/authority/consistency/canonical/Issue/tokenizer/budget/TTL 的正反回归。

Re-verification:

上述三个最小反例必须全部 fail closed；真实同 policy、同 semantic Issue、同 watermark 的第二轮必须稳定 CACHE/UNCHANGED。

### OE-F02 — P0 — Coding hook 的 event stdin 可覆盖环境固定 host policy

Artifacts:

- MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:485-493、518、1430-1434
- docs/runbooks/agent-integration.md:31-43
- integrations/hooks/src/milai_hooks/cli.py:27-54、72-105
- integrations/hooks/tests/test_cli.py:46-78

Evidence:

在环境中固定 MILAI_AGENT_SCOPE_JSON={"project_ids":["host-fixed"]}、ACTION_SAFE、CANONICAL_REQUIRED、limit 1 后，调用 _policy() 并在 event payload 放入 scope payload-wide、INFORMATIONAL、EVENTUAL、limit 3，返回值精确采用 payload-wide/INFORMATIONAL/EVENTUAL/3。stdin event 因此优先于 runbook 声明的 host 环境配置。

Impact:

任意能够影响 hook event JSON 的调用方可扩大 scope、降低 authority/consistency 并增大 limit；这不是 catalog 缩减，而是 host policy 本身被降级。与 OE-F01 的 restored checkpoint 组合时，还能跨 policy 复用旧 slot。

Required change:

- scope、authority、consistency、limit 和 budget policy 只能来自 host-owned constructor/config/environment；event payload 中出现这些键应拒绝或完全忽略。
- 将 query、session/event identity 与 host configuration 分开建模；跨进程 checkpoint 必须绑定 host-policy digest。
- 添加 stdin adversarial tests，证明 payload 无法覆盖环境策略，且环境缺失/非法时 fail closed。

Re-verification:

用本 finding 的精确环境/payload 反例，结果必须拒绝或保持 host-fixed/ACTION_SAFE/CANONICAL_REQUIRED/1；不得发出弱化请求。

### OE-F03 — P1 — OpenIssue transport metadata 破坏 semantic cache/delta

Artifacts:

- runtime/src/milai/api/app.py:51-53、147-153
- runtime/src/milai/api/canonical_routes.py:183-191
- integrations/python-client/src/milai_client/optimization.py:769-788、928-966、1030-1047、1061-1079
- integrations/python-client/src/milai_client/lifecycle.py:273-283

Evidence:

Runtime 每次 GET /v1/open-issues/{id} 在 body 加入新的 request_id。issue_revision_digest() 和 _snapshot_id() 对完整 raw Issue 做哈希，rendered payload 也保留完整 raw。

最小复现保持 issue_id/status/revision/branches/discharge_rule/canonical position/query 全部不变，只把 request_id 从 req-1 改为 req-2：

- digest equality = false；
- memory_slot_cache_valid = false；
- lifecycle 第二轮 route/delta = L1/REPLACE；
- recall count 从 1 增为 2。

Impact:

任何带 live OpenIssue 的正常会话都无法获得设计要求的 stable CACHE/UNCHANGED，重复注入正文并扭曲 token/latency 收益；作者 500-turn cache test 没有覆盖真实 request_id 变化。

Required change:

定义唯一的 OpenIssue semantic projection，只哈希/渲染受治理字段，排除 request_id、response_request_id 等 transport metadata；snapshot 与 revision digest 必须使用同一 canonicalization。以两次真实 GET body 回归语义不变 cache，并证明 revision/branch/discharge/status 的真实变化仍立即失效。

### OE-F04 — P1 — Compiler 只检查 OpenIssue 键存在，不验证 minimum 语义

Artifacts:

- MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:632-653、689-766、1420-1422、1503-1504
- integrations/python-client/src/milai_client/optimization.py:769-788
- integrations/python-client/tests/test_optimization.py:226-303

Evidence:

_material() 只要求 issue_id/status/branches/discharge_rule 四个 key 存在。最小反例提供 envelope open_issue_ids=["i1"]，详情为 status="RESOLVED"、revision=-9、错误 target、branches=[]、discharge_rule={}。Compiler 没有抛 CONTEXT_ISSUE_DETAILS_REQUIRED，而是返回 REPLACE 并把该伪造结构放入 OPEN ISSUES。

Impact:

“字段名存在”被误当成 protected minimum 完整性；缺 branch/discharge、非 live 状态或非法 revision 可以获得表面成功，否定作者报告第 28 行的安全断言及 DoD 5/6/12。

Required change:

为 Compiler 输入引入严格 typed OpenIssue semantic validation：required ID 唯一匹配、live status/revision/target 合法、discharge rule 非空且满足合同、branch 结构与 issue type 的最低要求满足；任何缺失或冲突必须整体 infeasible/integrity error。加入 empty、wrong-type、stale-status、negative-revision、duplicate/spoofed-ID 回归。

### OE-F05 — P1 — 显式 UUID 被报告为 L0，实际发出 L1 请求

Artifacts:

- MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:503-545、871-875、1501
- integrations/python-client/src/milai_client/optimization.py:301-310
- integrations/python-client/src/milai_client/lifecycle.py:210-225
- integrations/python-client/src/milai_client/async_context.py:114-130

Evidence:

query 中的 UUID 被 Router 加入 object_ids，所以 decision.route="L0"。但是 lifecycle 只有 known_claim_ids 非空才调用 recall_exact；仅由 query 解析出的 UUID 没有进入 decision selector，随后 else 分支调用 client.recall，即 route L1。最小反例 “check claim 11111111-1111-4111-8111-111111111111” 输出 decision L0、transport call recall/L1。

Impact:

trace/metrics 所称的 L0 与真实 retrieval route 不一致，明确 Claim/OpenIssue ID 没有获得设计要求的 exact canonical fast path；OpenIssue ID 也没有 typed recovery。

Required change:

RoutingDecision 必须携带经过验证的 typed exact selector，或在 lifecycle 明确解析/分类后调用相应 exact Claim/OpenIssue API。无法判断对象类型时不能谎报 L0。为 query-only Claim UUID、known claim、OpenIssue UUID、多个/非法 UUID 和 sync/async 路径加入 transport-level assertions。

### OE-F06 — P1 — 必需的 provider-exact、cold-query 与同模型质量 release evidence 缺失

Artifacts:

- MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:1181-1190、1231-1236、1377-1395、1497-1511
- docs/reports/OE-07-agent-efficiency-implementation-evidence-2026-08-18.md:14-18、42-55、97-98
- docs/reports/OE-requirements-evidence-matrix-2026-08-18.md:11-18、24-36、40-43
- docs/reports/OE-00-agent-efficiency-benchmark-2026-08-18.json

Evidence:

- 独立重跑的 workload 与保留 JSON 均明确 provider="offline-synthetic"、model_id="no-llm-called"、provider_usage_verified=false、pricing 全 null；20/100/500 数值可复现，但不是 provider token 或账单。
- ProviderTokenUsage 可由任意 host code 在无 provider I/O、无 request_id 情况下构造，verified 默认即 true；因此单元测试中的该对象不能成为外部实账证据。
- 没有 target provider 下 reader-lite ≤250、STANDARD/HIGH/1600、100-turn <30000 的证明。
- status 只证明 ONNX prewarm READY（486.844 ms）；没有 prewarmed-ready 后首个正常 query <250 ms 的独立 retained run。
- 没有 current 与 optimized 使用同任务、同真实模型、同 provider、同调用上限的 20/100/500 A/B；没有实际 provider input/cached/output、额外模型回合、端到端 wall time、账单或 task/quality/safety comparison。

Impact:

OG-00/01/03/04/05/08/09 与 DoD 10/12 不能作为 release gate 关闭；本 review 也不能把诚实的 “unverified” 改写为 PASS。

Required change:

冻结至少一个明确受支持 target model/provider 和 pricing snapshot，以同一任务/权限/最大模型调用数运行 current 与 optimized 20/100/500；保留 provider 原生 usage/request IDs、input/cached/output、MiLAi memory/tool split、模型回合、wall time、费用和质量/安全指标。另保留真实 post-ready first-query 计时。无法取得 provider 证据时继续称 Candidate，不得使用最终发布叙事。

### OE-F07 — P2 — Scale runner 依赖未声明 cwd，raw report 未保留

Artifacts:

- evals/agent_efficiency/postgres_scale.py:329-340、438-440
- runtime/alembic.ini:1-3
- docs/reports/OE-05-postgresql-scale-performance-2026-08-18.md

Evidence:

从仓库根运行 PYTHONPATH=runtime/src runtime/.venv/bin/python evals/agent_efficiency/postgres_scale.py 会在创建临时 DB 后因 “Path doesn't exist: migrations” 阻塞；cleanup PASS。原因是 Config 指向绝对 alembic.ini，但 script_location=migrations 仍按 cwd 解释。从 runtime/ 工作目录运行则 PASS。当前只保留手写 Markdown，没有同一次运行的 raw JSON。

Required change:

Runner 应把 Alembic script_location/prepend_sys_path 解析成绝对路径，或在权威命令中显式声明 cwd；保留并 inventory-bind raw JSON、runner SHA、environment、cleanup。P2 不单独阻止 Candidate，但必须在下一次 release evidence 中关闭。

## 4. OE-00～OE-07 disposition

| Work package | Independent disposition | Evidence |
| --- | --- | --- |
| OE-00 | NOT MET | workload/fixtures/SHA 和 scale generator 可复现；但没有同真实模型/provider、同质量口径的 current hook/MCP/LangGraph/AutoGen baseline，退出条件未满足（OE-F06）。 |
| OE-01 | PARTIAL | TokenCounter、fallback/null、split fields 与 privacy behavior 存在；没有 provider reconciliation，且 verified 是 host assertion（OE-F06）。 |
| OE-02 | FAIL | one-slot/delta 单测通过，但 policy/budget stale reuse 与 request_id over-invalidation 反例推翻完整 invalidation claim（OE-F01/F03）。 |
| OE-03 | FAIL | deterministic routes、reader-lite 和 profile clamp 通过；cache key 未进入运行路径，hook policy 可被覆盖，query UUID L0 被误发 L1（OE-F01/F02/F05）。 |
| OE-04 | FAIL | tiers、bytes/token test counter 与 ordinary infeasible tests 通过；invalid Issue minimum 被接受，cache 可绕过更小预算，target tokenizer 缺失（OE-F01/F04/F06）。 |
| OE-05 | PASS — local synthetic only | persistent HTTP、bounded prewarm、RRF/default-off MMR、Canonical Gate 与 independent 10k/100k run 通过；reproducibility P2 仍开放。 |
| OE-06 | FAIL | 当前三会话 E2E 通过；但 hook 不保持 host policy，same-workload/provider cross-framework 证据缺失（OE-F02/F06）。 |
| OE-07 | FAIL | package/install/examples/CI/security 技术门通过；2 P0、4 P1 未关闭，provider release proof 不存在。 |

## 5. OG-00～OG-12 disposition

| Gate | Result | Independent evidence |
| --- | --- | --- |
| OG-00 Reproducible Baseline | NOT MET | Offline fixture与runner SHA可复现；真实模型/provider/current cross-framework baseline 不完整。 |
| OG-01 Token Truth | NOT MET | 无 provider usage/billing reconciliation；本地未伪造数值只证明诚实缺失。 |
| OG-02 No Quadratic Growth | PASS — narrow | SDK/AutoGen 500 tests 保持一个 slot、无 append；但 live Issue 受 OE-F03 影响会重复 REPLACE。 |
| OG-03 Compact Tools | NOT MET | reader-lite 一工具且 evaluation tokenizer 小；target provider ≤250 未证明。 |
| OG-04 Context Budget | FAIL | 普通 injected-counter ceiling 测试通过；1482→256 cache 反例和 invalid Issue minimum 失败，target provider 也缺失。 |
| OG-05 Session Cost | NOT MET for release | Offline regex 100-turn=10280<30000；不是实际 provider input/cached-input。 |
| OG-06 Warm L0 | PASS | 独立 fresh scale 10k C1 p95 27.402 ms <30。 |
| OG-07 Warm L1 | PASS | 独立 fresh scale 10k C1 p95 35.951 ms <100。 |
| OG-08 Cold Start | NOT MET | READY/prewarm 可见；post-ready first normal query gate 未保留。 |
| OG-09 Quality | FAIL | 无同模型 A/B，且 P0 host-policy/cache 与 OpenIssue integrity 是实际安全回归。 |
| OG-10 Frameworks | FAIL | E2E transports 通过；hook host-policy boundary 与 generic/hook cache binding 不同合同。 |
| OG-11 Failure Safety | FAIL | revoke/DB/stale projection tests 通过；stale cache 与 policy-change 反例未 fail closed。 |
| OG-12 Independent Review | FAIL | 本 review 为 REVISE，开放 2 P0、4 P1。 |

## 6. Definition of Done 1～15

| DoD | Result | Reason |
| --- | --- | --- |
| 1 | NOT MET for release | 无受支持 provider 的真实计数证明；当前明确 unverified 是诚实行为但不关闭 OG-01。 |
| 2 | PASS — narrow | replace/remove/unchanged 与 500-turn one-slot 行为存在；不表示 cache correctness 已通过。 |
| 3 | FAIL | query UUID L0 misdispatch；policy-change cache 可绕过当前 host canonical recall。 |
| 4 | PASS | reader-lite 只暴露 milai_recall；profile/limit/consistency adversary 被 SDK/MCP clamp。 |
| 5 | FAIL | 空 branches/discharge、非 live/非法 revision 的 Issue 被当成完整 minimum。 |
| 6 | FAIL | 更小 budget 可 CACHE 保留超限旧 slot 并报告 0。 |
| 7 | FAIL | cache 在 policy 变化后实际成为旧上下文的决定性来源。 |
| 8 | FAIL | caller boolean 可绕过 canonical/Issue 变化；scope/authority/consistency/tokenizer/budget 未绑定。 |
| 9 | FAIL | hook event payload 能降低 host policy；框架边界不一致。 |
| 10 | FAIL | 100/500 无 actual provider token、模型回合、billing 和端到端 wall time。 |
| 11 | PASS | 独立 1/1k/10k/100k、C1/4/16、cold/warm run 与 cleanup 通过；OE-F07 为可复现性 P2。 |
| 12 | FAIL | 无同模型质量比较，且 OpenIssue/cache/authority 反例是明确回归。 |
| 13 | FAIL | package/install/examples/CI/scan 通过；独立审查决定不是 PASS。 |
| 14 | PASS | runtime pyproject/lock 未发现 Mem0/ReMe/Hindsight/OpenViking/Graphiti 等外部 memory engine 依赖。 |
| 15 | PASS | live doctor/status 与源码均为 Schema 0.1.x EXPERIMENTAL / NO-GO；Runtime CANDIDATE。 |

## 7. 独立命令与结果

| Gate / command summary | Result |
| --- | --- |
| Independent inventory traversal + per-entry size/SHA + canonical JSON root | 342/342 exact; sorted/unique/safe; root/file SHA exact |
| Package-local Ruff format/check + mypy + pytest | SDK 57, MCP 9, LangGraph 4, AutoGen 4, Hooks 4; all PASS |
| Runtime Ruff format/check + mypy | 117 files formatted; 63 source files typed; PASS |
| Fresh exact-role PostgreSQL scripts/run_runtime_full_gate.py to a temporary report | 152 passed in 77.63s; exit 0; cleanup 0 connections; PASS |
| Fresh evals/agent_integration/e2e.py to a temporary report | Generic SDK, official MCP 2026-07-28, independent wire 2025-11-25, LangGraph, AutoGen read; conflict/head/revoke/purge; cleanup PASS |
| Fresh evals/agent_efficiency/postgres_scale.py from runtime cwd | 1/1k/10k/100k PASS; 10k C1 p95 L0/L1 27.402/35.951 ms; 100k 27.399/56.360 ms; cleanup PASS |
| Fresh offline benchmark + tests | 3 passed; 20/100/500 totals 2056/10280/51400 and exact frozen fixture SHA; provider_usage_verified=false |
| Six-wheel clean install in fresh temporary venvs, Python -I, PEP 561 | 6/6 PASS; wheel SHAs match retained report/manifest |
| Independent unpack of all six wheels and six sdists | 12/12 manifest size/SHA exact; 295 regular members total; zero unsafe path/link/forbidden member |
| scripts/scan_ua_secrets.py | 344 files, 295 archive members, 17 local secret values, zero match/forbidden/unsafe; PASS; no secret value printed |
| tests/test_release_safety.py | 8 passed, including nested compressed secret, env/cache/link, inventory and Runtime sdist adversaries |
| Generic/MCP/LangGraph/AutoGen example smokes | 4/4 PASS |
| Live milai-ops doctor/status | doctor 17/17 PASS; API live/ready PASS; ONNX READY; synthetic-only; remote false |
| Frozen architecture validate/verify/unittest with CI bundle env | validation PASS; manifest SHA exact; 19 tests OK, 1 expected skip |
| Research OSPC Ruff/mypy/unittest | 9 tests; PASS |
| Dynamic tool adversary | reader-lite remained one tool; attempted scope/authority/consistency/limit escalation stayed host scope/ACTION_SAFE/CANONICAL_REQUIRED/2; invalid profile rejected |
| Cache/OpenIssue/budget/UUID/hook/provider adversaries | Reproduced OE-F01～F06 exactly as described |

Notes on reviewer command setup:

- Running the scale script from repository root exposed OE-F07 and cleaned its temporary DB; rerunning from runtime/ completed successfully.
- A first benchmark-test invocation omitted repository root from PYTHONPATH; the corrected command with PYTHONPATH=.:integrations/python-client/src:runtime/src passed 3/3.
- Frozen architecture unittest without the workflow's MILAI_ARCHITECTURE_LOCK_SCOPE=bundle predictably reports post-freeze project-source drift. The exact checked-in CI environment passes the immutable bundle gate; no frozen byte was refreshed.
- Package artifacts were not rebuilt in place because the review was forbidden to mutate candidate bytes. They were independently unpacked, source-compared on optimization/runtime/framework modules, scanned and installed into six fresh temporary environments.

## 8. Acceptance conditions for re-review

A new candidate may request re-review only after:

1. OE-F01 and OE-F02 have code-level fixes and cross-framework adversarial regression tests.
2. OE-F03～OE-F05 have semantic/transport exactness fixes and real Runtime response tests.
3. OE-F06 has actual provider/model evidence, or the release remains explicitly Candidate and does not request PASS.
4. OE-F07 reproducibility is repaired and raw scale evidence is inventory-bound.
5. All packages/artifacts/manifests/inventory are regenerated from the fixed source, archive scan and clean install pass, and a new exact inventory identity is supplied.

Open findings: **P0=2, P1=4, P2=1**. Therefore OG-12 and DoD 13 cannot close, and the only defensible decision is **REVISE**.
