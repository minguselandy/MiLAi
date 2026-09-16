# MiLAi vLLM Provider 验证与 MCP Agent 接入 Goals

> Goal ID：`DG-10`  
> 文档版本：`0.3.1 CANDIDATE — CONTRACT CLEANUP ONLY`  
> 修订日期：`2026-08-21`（Asia/Shanghai）  
> 当前状态：`RE-REVIEW REQUIRED — L1/L2/L3 AUTHOR EVIDENCE READY；L4/L5 NOT ACCEPTED`  
> 变更类别：`DOCS/CONTRACTS ONLY；NO RUNTIME/ARCHITECTURE/VLLM/CANDIDATE IMPLEMENTATION CHANGE`  
> 唯一被测 Provider：`self-hosted vLLM 0.27.1 / Qwen3.6-35B-A3B-FP8`  
> 对抗证据审计模型：`Codex gpt-5.6-sol`（只读、仓库外闭集、不得参与 A/B 或最终裁决）  
> 外部计费 Provider：`OUT OF CURRENT SCOPE；OE-F06 OPEN / PARKED`  
> 数据边界：`SYNTHETIC / DEIDENTIFIED ONLY`  
> MCP 边界：`LOCAL STDIO ONLY；SECRET-FREE RELAY + BOUNDED UDS CAPABILITY LOCAL CANDIDATE`  
> Runtime：`0.1.x CANDIDATE`  
> Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> Logical Architecture：`1.0.0 FROZEN`，本 Goal 不修改其对象、权限或 invariant

---

# 0. Goal 结论

`DG-10` 的当前完成目标是把 MiLAi Runtime、Python Client、`milai-mcp`、OpenWorker 和现有
自托管 vLLM 封装成一条可安装、可复现、可 benchmark、可独立复核的本地 Agent memory 链：

```text
self-hosted vLLM 0.27.1 / Qwen3.6-35B-A3B-FP8
                  ↕ OpenAI-compatible local API
          OpenWorker Gateway / OpenCode Agent
                  ↕ local MCP stdio
        无可导出 secret 的 UDS Relay
                  ↕ Unix socket
     可信 MiLAi MCP Broker（token + Host policy）
                  ↕ loopback HTTP
     MiLAi Runtime → Canonical Gate → Claim / OpenIssue / Trace

冻结、脱敏、inventory-bound 的证据
                  ↓
 Codex CLI / gpt-5.6-sol / read-only / ephemeral
                  ↓
 REVIEW_CANDIDATE → schema 校验 → 受控接受记录
```

最终必须同时证明：

1. 所有行为、质量与 token A/B 只由同一精确 vLLM 模型产生，不把 Codex 或其他模型混入分母；
2. Agent 通过正式发布包和真实 MCP wire 安全召回，并正确处理 OpenIssue、degraded、abstention、
   revocation、cache invalidation 与 trace；
3. 内部 S1～S10、可行的长期记忆 benchmark、BFCL V4 本地 tool-calling 子集和 vLLM serving
   benchmark 形成治理、记忆质量、工具语义与吞吐的分层证据；
4. MCP、OpenWorker、vLLM 输出和评审模型都不能绕过
   Evidence → Proposal → Decision → Canonical Procedure；
5. OpenWorker 内不存放 MiLAi token 或 Runtime DSN；容器内 root/bash 在无 host privilege、
   无禁止 capability、无危险 mount/network/device 的冻结约束下，只持有 profile-specific socket capability；
6. OpenWorker restart/recreate、MCP disable、broker stop、token revoke 与 image rollback 可复现；
7. Codex `gpt-5.6-sol` 只审核冻结证据并输出结构化 `REVIEW_CANDIDATE`；它不替代确定性 gate、
   vLLM 原生 token 事实或最终受控接受；
8. 当前 Goal 只有满足 §0.1 五层公式才可晋级为 `Local vLLM MCP Agent Candidate`，且不得据此关闭外部账单项 `OE-F06`，
   也不得宣称 external-provider Beta、Production 或 Schema Freeze。

当前事实边界：

| 能力 | 当前事实 | 本版剩余目标 |
| --- | --- | --- |
| vLLM 身份 | vLLM `0.27.1`、模型、镜像、57-file closure 与 2×A100 40GB 已有作者候选锁 | 独立复算并绑定最终 release inventory |
| 同模型 A/B | candidate.2：1,000 logical、1,000 native；baseline 500、optimized 500、hidden 0；质量 488/500 对 500/500，输入 token 709,360 对 365,560 | 复验原始记录、final-prompt token truth 与漂移/隐藏调用负向门 |
| MCP 实现 | `milai-mcp 0.1.0` 与 reader-lite query-only 已存在 | 最终 wheel/sdist、非仓库 cwd clean install、双 Host wire gate |
| OpenWorker | candidate.2.4 已完成 vLLM + MCP S1～S10 作者候选，restart 后 config/catalog 不变 | 复核 container threat model、UDS capability/quota、S8 分 lane、fresh E2E 与回滚 |
| 公开 benchmark | 尚无本 Goal 绑定的 LongMemEval-V2/LongMemEval/BFCL 结果 | 先完成 modality feasibility，再做确定性主评分和独立 characterization |
| Serving 性能 | 已有内部 10k/100k Runtime scale 证据 | 增加 T0～T3、exclusive/characterized window 与分段 p50/p95/p99 |
| 独立评审 | 尚无本版 benchmark/release 的 Codex review receipt | 在仓库外 materialized frozen workspace 用精确 `gpt-5.6-sol` 对抗审计，再受控接受 |
| 外部账单 | `OE-F06 OPEN`，无 invoice/export | 本版明确 PARKED，不阻塞本地 vLLM candidate，但继续阻塞 external-provider Beta |

## 0.1 分阶段 Acceptance State Machine

`DG-10` 是一个 release program；每层有独立状态，后续层失败不能抹去已独立接受的前层事实：

```text
DG10-L1  PACKAGE_VERIFIED
          MCP package / archive / protocol / capability surface

DG10-L2  HOST_ISOLATED
          OpenWorker container / UDS capability / broker / secret boundary

DG10-L3  LOCAL_PROVIDER_VERIFIED
          same-vLLM 500+500 A/B / S1-S10 / zero hidden calls

DG10-L4  QUALITY_CHARACTERIZED
          benchmark feasibility / quality outcome / serving characterization

DG10-L5  INDEPENDENTLY_ACCEPTED
          frozen-workspace audit / finding replay / controlled acceptance
```

每层状态使用：

```text
NOT_STARTED
AUTHOR_CANDIDATE
REVIEW_REQUIRED
ACCEPTED
REVISE
NOT_APPLICABLE_WITH_RATIONALE   # 只适用于预声明的 benchmark slice，不适用于安全门
```

质量结果另有正交字段：

```text
TARGET_MET | BELOW_TARGET | CHARACTERIZED_ONLY | NOT_APPLICABLE
```

因此允许同时成立：

```text
MCP_INTEGRATION_PASS
MODEL_QUALITY_BELOW_TARGET
```

最终可声明状态定义为：

```text
LOCAL_VLLM_MCP_AGENT_CANDIDATE
= L1.ACCEPTED ∧ L2.ACCEPTED ∧ L3.ACCEPTED
  ∧ L4.ACCEPTED ∧ L4.quality_outcome=TARGET_MET
  ∧ L5.ACCEPTED
```

对应关系必须由 `docs/contracts/DG-10-claim-matrix.yaml` 机器校验；任何报告只能使用该矩阵允许的
claim。候选字节变化只失效依赖该字节的层及其下游，不得把未受影响层的历史接受记录改写或删除。

---

# 1. 规范关系

## 1.1 优先级

发生冲突时按以下顺序执行：

1. `architecture/v1.0/` frozen Logical Architecture；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` 中的 frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. `MiLAi_Agent执行效率与Token优化设计开发文档_v1.md`；
5. `MiLAi_可用性与Agent接入设计开发文档_v1.md`；
6. ADR-023 与本 Goal；
7. benchmark adapter、运行脚本与实验实现。

本版按用户明确范围把 `PV-LOCAL` 设为唯一活跃 Provider lane。它细化 `OE-01`、`OE-06`、
`OE-07`、`OG-01/03/04/08/09/10/12` 和 `UA-04/UA-08`，但不声称满足依赖外部 invoice 的
`OE-F06`。`OE-F06` 保持 `OPEN / PARKED`，未来若恢复外部计费 Provider，必须另立批准与复审。

## 1.2 不可改变的边界

- PostgreSQL Canonical Core 仍是唯一正式状态来源；
- vLLM、Agent、MCP tool output、Codex review 和模型回答都不能成为 canonical truth；
- Agent 只能读取、捕获 Evidence 或创建 Proposal，不能自评审或直接修改 Claim/OpenIssue；
- Scope、authority、consistency floor、profile、token 和最大 limit 必须由可信 Host 固定；
- benchmark 与 review 属于隔离 Evaluation Plane，不进入 canonical transaction；
- Remote MCP、公开 Runtime、多 Agent delegation 和真实个人数据不在本 Goal 范围；
- vLLM 或 MCP 失败只能导致降级、abstention 或明确失败，不得提高 authority；
- OpenWorker/OpenCode 不是 MiLAi secret Host；OpenWorker Skill 不是 MCP transport；
- 禁止以 `--network host`、Runtime 非回环 bind、`allow_remote=True` 或新增 Remote MCP
  作为接入捷径；扩大边界必须另立 ADR 和 Remote Access Gate。

---

# 2. North Star 与成功场景

## DG-10：vLLM-Verified MCP Agent Memory

**目标陈述：**

让 OpenWorker/OpenCode 只使用已冻结的本地 vLLM 模型，通过 local stdio MCP 调用 MiLAi，在固定
Scope、authority 和 token budget 下完成安全召回，并以 vLLM usage、GPU/serving 指标、公开
benchmark、MiLAi trace 与独立 review 证明该接入可用、额外成本有界且没有治理回归。

**必须从封装产物回放的端到端场景：**

```text
S1  fresh install/start → MCP initialize/list_tools → 只发现 reader-lite recall
S2  问题无需记忆 → Router NONE → 不调用 MCP、不注入 memory token
S3  当前事实查询 → MCP recall → Canonical Gate → Context → vLLM answer + trace
S4  同一 snapshot → CACHE_CANONICAL → 复验 canonical position / Issue revision
    → payload reuse / Context 不重复注入；validation 成本仍单列
S5  相互冲突 Evidence → OpenIssue 两 branch 保留 → Agent 不输出伪确定结论
S6  Evidence revoke → 旧 slot 与 stale projection 失效 → Agent abstain/degrade
S7  Canonical store 不可用 → ACTION_SAFE 查询明确 abstain
S8a reader Agent 识别写入需要 → reader lane 无写权限
S8b 显式批准 handoff → 独立 submitter lane → 只创建 Evidence/Proposal
S8c reader 不能打开 submitter socket；submitter 不能 review 或直接 canonical write
S9  OpenWorker restart/recreate → MCP 目录自动恢复 → 不依赖容器内手工状态
S10 模型诱导 env/config/proc/bash/log 扫描 → 无 MiLAi token/DSN 可得 → 仅允许 socket tool 调用
```

S1～S10 必须使用同一 vLLM endpoint/model、同一冻结 workload、同一最终封装字节，以及同一冻结
Host-policy manifest 下预声明的 profile-specific policies。reader、submitter、operator 不是同一
policy；S8 的跨 lane handoff 必须有显式 receipt，普通 reader 不挂载 submitter/operator socket。
需分别报告无 MiLAi、naive/RAG、MiLAi 三组的 input/output tokens、模型回合、MCP round、TTFT、
端到端时延、答案质量和治理失败。Codex review 不得执行或补齐任何 benchmark 样本。

---

# 3. 范围与非目标

## 3.1 本 Goal 包含

- 只使用当前自托管 vLLM `Qwen3.6-35B-A3B-FP8` 作为被测模型；
- 冻结 vLLM image/model/tokenizer/chat-template/启动参数/GPU/driver/CUDA 与 endpoint identity；
- 复核既有精确 1,000 次同模型 A/B，并对最终封装字节重放必要样本与负向门；
- 从 clean environment 构建、扫描、安装 `milai-client`、`milai-mcp` 与 OpenWorker 集成包；
- 从 fresh OpenWorker image 通过无可导出 MiLAi secret 的 relay、UDS capability、可信 broker、
  MCP wire 和 Runtime 完成 S1～S10；
- 建立内部治理 benchmark、LongMemEval-V2、LongMemEval、BFCL V4 本地子集、可选 LoCoMo 与
  `vllm bench serve` 的统一执行/评分/证据合同；
- 记录 vLLM usage、tokenizer recount、GPU/serving、MCP round、MiLAi route 与端到端时延；
- 用 Codex CLI 精确 `gpt-5.6-sol` 对冻结脱敏 bundle 做只读结构化 review；
- 生成不含 secret 的 Agent 配置、Runbook、benchmark 报告、回滚说明和独立接受记录。

## 3.2 本 Goal 不包含

- OpenAI、Anthropic、Google 或其他外部计费模型作为运行时 Provider 或 benchmark 样本生成器；
- 用 Codex `gpt-5.6-sol` 充当 A/B 模型、benchmark judge、自动修复者或最终 gate authority；
- 关闭需要 external receipt/invoice 的 `OE-F06`，或宣称 external-provider Beta；
- Remote/HTTP MCP、OAuth、多设备、公网 Runtime、多 Agent 委派或共享记忆治理；
- Agent 自动批准 Proposal、直接写 canonical table 或从 benchmark 写入正式数据；
- 修改、重启或重配置现有 vLLM 服务来追求更好分数；
- 真实个人数据、生产 Prompt、未脱敏 Evidence 或用户聊天记录；
- Schema freeze、Production ready 或通用多 Provider router；
- 把 MiLAi token、Runtime DSN 或 broker secret 注入 OpenWorker、OpenCode、Skill 或评审上下文；
- 把临时 `opencode mcp add`、手工 `docker exec` 或容器内可写 venv 当作发布集成；
- 以 `--network host`、Runtime 外部 bind 或放宽 Client loopback 校验解决网络问题；
- 在未确认 Worker/OpenCode 与 benchmark 数据许可前对外分发派生镜像或数据集。

## 3.3 vLLM-only 完成边界

本版的唯一被测 Provider 固定为 ADR-023 已记录的：

```text
vLLM: 0.27.1
model: Qwen3.6-35B-A3B-FP8
endpoint: 127.0.0.1:7860（隔离 adapter 使用已批准的本地 bridge 路由）
accelerator: 2 × NVIDIA A100 40GB, tensor-parallel=2
```

最终执行必须复算 image ID/repo digest、模型 closure、tokenizer/chat template、启动参数和 GPU 软件栈，
以实际 identity report 为准；本 Goal 不授权改变正在运行的 vLLM。vLLM 属于模型面，MiLAi MCP
属于记忆工具面；模型输出不得直接进入 canonical write path。

自托管 vLLM 没有上游 invoice，因此本地 completion 使用 `PVL-*` 门和资源/usage 证据，而不是伪造
billing truth：

```text
PVL PASS → 只可支持 DG10-L3 LOCAL_PROVIDER_VERIFIED
L1∧L2∧L3∧L4(TARGET_MET)∧L5 → Local vLLM MCP Agent Candidate
任一本地 PASS ≠ OE-F06 CLOSED ≠ External-provider Beta
```

## 3.4 Codex `gpt-5.6-sol` 的位置

Codex 是 Evaluation Plane 内的独立评审助手，不是 MiLAi Provider。它只能读取已经冻结、脱敏、
inventory-bound 的报告、清单、协议和测试输出；禁止读取 `.env`、token、DSN、raw memory、raw prompt、
Provider credential 或仓库外私密证据。其输出状态固定为 `REVIEW_CANDIDATE`，经 JSON Schema、引用路径、
文件 hash 和 finding 可复现性校验后，由受控 reviewer/importer 生成新的接受记录。

Codex 不参与 vLLM A/B 分母、不为 benchmark 答案打分、不修改候选字节、不自动关闭 finding，且其
API token/usage/cost（如客户端可提供）必须独立记录；无法取得时必须写 `UNAVAILABLE`，不得记作 0。

---

# 4. 目标架构与凭据边界

## 4.1 运行链

OpenWorker 不满足“可信 secret Host”前提：其模型执行环境拥有容器内 root/bash，因此必须使用
第 4.3～4.4 节的无可导出 secret relay/broker 变体。vLLM 只接收 Agent 的模型请求，不接收
MiLAi token/DSN。本文的 root claim 只适用于冻结的受限 Worker container，不等于 host root。

```text
┌──────────────────────────────────────────────────────────────┐
│ OpenWorker Gateway / OpenCode Agent                          │
│ - 固定 vLLM endpoint/model、Scope、authority、consistency      │
│ - 决定何时调用 MCP；将 MCP 结果视为 data-only                 │
└───────────────┬───────────────────────────────┬──────────────┘
                │ local model API               │ stdio JSON-RPC
                ▼                               ▼
┌──────────────────────────┐       ┌───────────────────────────┐
│ self-hosted vLLM         │       │ secret-free UDS relay     │
│ request/usage/latency    │       │ → trusted milai-mcp broker│
│ GPU/serving metrics      │       │ scoped token outside host │
└──────────────────────────┘       └─────────────┬─────────────┘
                                                │ loopback HTTP
                                                ▼
                                  ┌─────────────────────────────┐
                                  │ MiLAi Runtime               │
                                  │ Canonical Gate / Trace      │
                                  │ Evidence/Proposal boundary  │
                                  └─────────────────────────────┘
```

## 4.2 Secret 分离

| Secret | 唯一允许持有者 | 禁止出现位置 |
| --- | --- | --- |
| vLLM endpoint access / Gateway key（若启用） | OpenWorker Gateway 的既有模型边界 | MCP args/result、MiLAi Runtime DB、benchmark/report |
| `OPENWORKER_KEY` | OpenWorker Worker/Gateway 现有边界 | MiLAi broker/Runtime/Proposal/Evidence；不得复用为 MiLAi token |
| MiLAi reader token | 通用可信 Host 的 `milai-mcp` 子进程，或 Worker 外 reader broker | OpenWorker env/config/proc、relay args/result、Skill、vLLM prompt |
| MiLAi submitter token | 独立 submitter 进程/broker | reader/operator socket、OpenWorker env/config、模型上下文 |
| MiLAi operator token | 独立 operator 进程/broker | reader/submitter socket、OpenWorker env/config、普通 Agent |
| PostgreSQL DSN/roles | MiLAi Runtime 进程 | MCP/broker/relay、Agent Host、vLLM benchmark adapter |

vLLM benchmark adapter 不接受任何外部 Provider credential；执行环境不得注入 proxy、`PYTHONPATH`、
`LD_PRELOAD`、`BASH_ENV` 或数据库凭据名。若当前 OpenWorker Gateway 已使用内部 key，只能沿用既有
secret 边界，不能复制到 MiLAi broker、MCP 配置、报告或 Codex review bundle。

## 4.3 OpenWorker 预检事实与可接受拓扑

2026-08-20 对本地 `/cra/openworker/openworker-selfhosted-main` 和现有 Worker 镜像进行了
不改写源码的预检。以下只是设计输入，不是最终 release evidence：

| 项 | 预检结果 | 发布要求 |
| --- | --- | --- |
| selfhosted 仓边界 | 只有安装/编排素材，Worker 源码和 Dockerfile 不在该仓 | 确认上游源码/授权，或仅生成不对外发布的本地派生镜像 |
| Worker image | `openworker-v2:2026.5.9.1`，本地 image ID `sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d` | 最终使用完整 image digest/manifest/platform 锁定，不使用漂移 tag |
| Agent engine | OpenCode `1.14.28` 支持 local MCP，实测 local schema 与 `{env:VAR}` 可解析 | 锁定精确 OpenCode bytes/schema，最终配置只使用 local transport |
| Python package | Python `3.12.13` + uv `0.11.9`；当前两个 MiLAi wheel 及 33 个依赖在 musl 镜像安装/import PASS | 生成 musllinux/amd64 锁定 wheelhouse，禁止 release build 无界联网解析依赖 |
| 持久化 | entrypoint 每次清空 `/openworker/runtime` 并从 image template 重建 `opencode.json` | MCP 配置必须进入 image template；手工 `mcp add` 不算完成 |
| 权限 | Worker 以 root 运行，OpenCode Agent 的 bash/external directory 权限开放 | Worker 内不得存在 MiLAi token/DSN，broker 必须位于独立信任边界 |
| 网络 | Worker 位于 Docker bridge；MiLAi Runtime/Client 强制 loopback | 使用 UDS relay 到本地 broker，不改 Runtime 的 remote-access 语义 |

目标链路：

```text
OpenWorker/OpenCode
  → local MCP stdio
  → 无可导出 secret 的 relay
  → Unix socket bearer capability
  → 可信 MiLAi MCP Broker
       - 固定 profile / Scope / authority / consistency / limit
       - 持有对应 scoped MiLAi token
       - 每 connection 启动精确 `milai-mcp --profile ...`
  → loopback HTTP
  → MiLAi Runtime → Canonical Gate / Trace / Evidence-Proposal boundary
```

实施必须满足：

- 派生 Worker 镜像只包含锁定 relay bytes、OpenCode MCP 模板和必要 CA；
- relay 只做 stdin/stdout 与单个 Unix socket 的字节转发，不解析、缓存或记录 MCP 正文；
- broker 对每个 connection 使用完整路径和环境 allowlist 启动精确 `milai-mcp`；
- `reader-lite`、`submitter`、`operator` 使用不同 socket、Unix 权限、token 和 Host policy；
- 普通 OpenWorker 任务只挂载 `reader-lite` socket；submitter/operator 必须使用独立 Worker/Agent policy；
- socket 目录只读挂载且不挂载 Docker socket、Runtime `.env`、主机 secret 目录或 PostgreSQL socket；
- broker 与 MiLAi Runtime 在同一可信本地边界使用 loopback HTTP；Worker 不能直连 Runtime API。
- broker 必须限制每 socket 的并发连接、连接/请求速率、request/frame/message bytes、idle timeout、
  child-process ceiling 和时间窗请求配额；任一上限触发有界拒绝，不得无限排队或 fork；
- broker 必须核验 socket inode/type/owner/mode、连接 peer identity（平台支持时）和 profile 映射，
  并记录不含正文的 accept/reject/quota trace。

直接在 Worker 内运行 `milai-mcp` 并通过 `{env:MILAI_AGENT_READER_TOKEN}` 传 token，
只允许作为无可导出 MiLAi secret、无真实数据、不计入发布证据的临时 POC。最终 candidate 必须重新
独立获取上述身份并记录完整 digest、文件闭包、授权结论和动态证据。

## 4.4 Worker container 与 UDS capability threat model

“relay 不持有 token”不等于 Worker 未获授权。能够打开挂载的 Unix socket 本身就是 bearer
capability：

```text
no extractable MiLAi secret
≠ unauthenticated

Worker socket possession
= server-bounded, profile-specific, revocable authority
```

安全目标是使授权不可升级、不可跨 profile、在冻结 namespace/network/mount 边界外不可导出，并可由
socket unmount、broker stop 或 token revoke 立即撤销；不是声称 Worker 没有权限。必须保持：

```text
Worker root
≠ host root
≠ broker authority
≠ Runtime authority
≠ submitter/operator authority
```

最终 Host identity 和对抗报告必须冻结并复算：

```text
effective Linux capabilities and no-new-privileges
seccomp profile and digest
AppArmor/SELinux profile and enforcement state
network mode, routes, DNS, host-gateway entries and exposed ports
privileged=false
PID / IPC / user namespace configuration
device mounts and device cgroup rules
bind mounts, propagation, read-only flags and rootfs policy
Docker/container-runtime socket absence
host proc/sys, Runtime .env, DB socket and secret mount absence
```

若存在 `CAP_SYS_ADMIN`、`CAP_NET_ADMIN`、privileged、host PID/network、Docker socket、未批准 device、
危险 mount propagation 或可达 Runtime/PostgreSQL 的旁路，`DG10-L2` 必须 `REVISE`。容器内 root 的
测试只能证明上述精确配置下的隔离，不能外推到任意 root container。

---

# 5. 关键结果

## KR-01：vLLM 目标身份与执行边界可复核

形成不含 secret 的 `PV-LOCAL Target Record`，至少冻结：

```text
vLLM version/image ID/repo digest
exact model name and model closure digest
tokenizer/chat-template/quantization identity
startup argv and immutable config digest（只读记录，不改变服务）
GPU model/count, tensor parallel, driver, CUDA and host identity
OpenAI-compatible endpoint route and allowed local network path
request/input/output ceilings and timeout/retry policy
dataset/workload/license digests
source/package/OpenWorker inventory roots
operator and independent reviewer identity/time
```

执行前、执行后都必须重取 identity；任一漂移令本次 run `INVALIDATED`。不要求 external invoice，
但必须记录本地计算窗口、GPU 数量、wall time、请求数、input/output tokens 和失败数。

## KR-02：封装产物与执行闭集

- Runtime、Client、MCP、relay、broker、OpenWorker image、wheelhouse 和配置全部 digest 绑定；
- wheel/sdist/image 逐成员检查，不含 `.env`、secret、cache、log、Blob、backup 或 unsafe path；
- fresh venv 与 fresh Worker image 在非仓库 cwd 进行 locked/offline install；
- OpenWorker 仍只运行无可导出 MiLAi secret 的 relay，MiLAi token 只在 Worker 外 broker；
- Runtime、MCP、vLLM endpoint 与 benchmark harness 使用精确 allowlist，禁止外部 Provider egress；
- benchmark adapter 的 source/dependency/host closure 可独立重建；
- 原始 synthetic prompt/output 若因 benchmark 必须保留，只能在仓库外加密 evidence 目录，仓库内
  仅存脱敏汇总、样本 ID、score 和摘要；
- 任一执行字节、模型身份、数据摘要或 package 漂移都 fail closed。

## KR-03：1,000 次 vLLM 同模型 A/B

复核既有冻结 workload，并在最终 release byte 需要时按变更影响重放：

- `logical_requests=1,000`、`native_model_requests=1,000`、`baseline_arm=500`、
  `optimized_arm=500`、`hidden_or_extra_calls=0`；logical/native ID 一一映射、全覆盖、唯一、terminal；
- 两组使用同一 vLLM/model/tokenizer/template/temperature/seed/tool schema 上限；
- vLLM native usage、最终序列化 prompt 的 tokenizer recount 与 MiLAi component attribution 分层可核对；
- 记录模型调用数、MCP/tool round、TTFT、总 wall time、timeout 和 failure taxonomy；
- 不允许隐含 retry、隐藏模型 call 或以 Codex 补答失败样本；
- 完整 capture 状态只能是 `PVL_CAPTURE_COMPLETE_REVIEW_REQUIRED`；
- partial/timeout/identity drift 不得统计为成功，也不得与原 candidate 静默拼接。

## KR-04：公开 benchmark 可比较且不污染治理边界

必须建立同一 harness 下的三组对照：

```text
NO_MEMORY      vLLM 仅看当前问题
NAIVE/RAG      vLLM + benchmark 官方或冻结的简单检索基线
MILAI          vLLM + OpenWorker → MCP → Runtime
```

三组固定同一 vLLM、generation 参数、答案模板、冻结的 counterbalanced case schedule 和 token ceiling。
公开 test 标签不得用于调参；
先用不超过 10% 的 dev/calibration 子集冻结阈值、prompt 和 grader，再一次性执行 test。官方 deterministic
grader 或 evidence ID 优先；不得用 Codex 作 judge。温度为 0 时执行一次确定性主 run 加一次小规模漂移
重放；若使用随机采样，则至少 3 个冻结 seed，并报告均值、方差和置信区间。

证据必须区分“集成正确性”和“模型/记忆质量表征”，不得用后者抹掉前者：

| Benchmark | 证据类别 | 当前要求 |
| --- | --- | --- |
| 内部 S1～S10 + governance adversary | Integration correctness / release blocking | 全量，零安全失败 |
| [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) | Agent-memory quality characterization | 先过 BMG-00A；兼容才跑 full small，否则只跑明确标注的 adapted slice |
| [LongMemEval](https://github.com/xiaowu0162/LongMemEval) | Long-memory quality characterization | cleaned 500 的可兼容确定性指标必跑 |
| [BFCL V4](https://gorilla.cs.berkeley.edu/leaderboard) | Agent tool-selection semantics characterization | 冻结 local/non-live 子集；不作为 MCP transport/protocol 证明 |
| [LoCoMo](https://github.com/snap-research/locomo) | Conversational-memory secondary characterization | 可选，不单独阻断 integration release |

`BMG-00A Benchmark Feasibility` 必须在下载/转换正式 test 和冻结阈值前记录：

```text
required modalities and trajectory artifacts
required tools and official input/output contract
vLLM/model/adapter modality capability
adapter transformation and information loss
official scorer/judge dependencies
case-level compatible / incompatible decision
```

LongMemEval-V2 可能包含 screenshot/multimodal trajectory evidence。若当前冻结模型/adapter 不能无损满足
某 case 的官方输入合同：full-small 状态必须是 `NOT_APPLICABLE_WITH_RATIONALE`；允许另建 text-only
frozen slice，但必须标 `ADAPTED_PROTOCOL`、列出包含/排除 case ID 和 lossiness，不得称官方 full-small
或 leaderboard score。禁止通过外部 VLM/OCR、人工转写或第二 Provider 静默补模态。

LongMemEval-V2 和 LongMemEval 的官方答案评分流程可能调用外部 OpenAI judge。当前 vLLM-only 范围
禁止该调用。评分严格分层：

```text
Tier 1 — deterministic release evidence
exact match / normalized F1 / evidence IDs / Recall@k /
latest-valid-state / abstention and safety labels

Tier 2 — blinded human audit subset
pre-frozen stratified case IDs and rubric; arm identity hidden;
used to detect deterministic-metric bias and adjudicate ambiguity

Tier 3 — same-vLLM judge characterization only
reported separately; never the sole release-blocking quality metric
```

结果必须标记 `LOCAL_VLLM_PROTOCOL`，不得冒充官方 leaderboard 分数。Tier 2 的人员、冲突处理、
arm blinding 和标注摘要必须记录；Tier 3 不能投票覆盖 Tier 1 安全或确定性失败。
未来若单独批准官方 judge，必须作为新的、与当前分母隔离的 evaluation lane；Codex review 不能代替 judge。

执行时必须锁定 upstream commit/release、dataset license、文件 SHA-256、样本 ID 清单、adapter 映射和
grader version。BFCL 的 live/API/web case 不进入本地-only release gate；任何适配必须保留原始 case ID，
另存 MiLAi mapping，不得修改标签后仍宣称官方分数。

`docs/contracts/DG-10-quality-acceptance.yaml` 必须在 test labels/outputs 打开前由 calibration 结果填充、
审核并 hash freeze；它至少包含每数据集/能力的 delta、absolute safety/false-certainty、token/round 和
统计规则。Goal 不预写未经实验支持的质量数字，test 后不得回改阈值。

## KR-05：vLLM Token、效率、资源与质量门

至少对以下门给出同一 vLLM 的可复算结论：

| Gate | 目标 |
| --- | --- |
| `OG-01 Token Truth` | vLLM native usage、final-prompt tokenizer recount、MiLAi component attribution 三层分离 |
| `OG-03 Compact Tools` | target tokenizer 下 `reader-lite` schema ≤ 250 tokens |
| `OG-04 Context Budget` | STANDARD ≤ 512、HIGH ≤ 1,024、hard ceiling ≤ 1,600 |
| `OG-05 Session Cost` | 冻结 100-turn workload 的 MiLAi extra input < 30,000 tokens |
| `OG-08 Cold Start` | prewarmed ready 后首个正常查询 < 250 ms，或形成有证据的新 candidate target |
| `OG-09 Quality` | 同模型任务质量、安全和 trace 相对最强固定基线无不可接受回归 |
| `PVL Serving` | raw vLLM 与 MiLAi E2E 分开报告 p50/p95/p99、TTFT、TPOT/ITL、req/s、tok/s |
| `PVL Resource` | GPU 数量/型号、显存峰值、GPU util、CPU/RSS、运行时长与失败率有记录 |

以下安全指标必须为零容忍：跨 tenant 返回、revoked Evidence 返回、authority escalation、live
OpenIssue false closure、无 trace 的 authority-bearing answer、canonical unavailable 时伪确定回答。
不能用 accuracy 提升抵消任何安全失败；不能把 vLLM 服务端排队时间算成 MiLAi 开销，必须分段报告。

Token Truth 的精确定义为：

```text
FinalSerializedPrompt
= exact chat template(messages, tools)
  + exact tool serialization
  + exact special-token behavior

T_native
= vLLM reported prompt_tokens                 # accounting truth

T_recount
= len(target_tokenizer(FinalSerializedPrompt)) # independent deterministic verification

T_components
= system + tool_schema + current_query + memory + tool_result + other
                                                 # attribution/decomposition, not native truth
```

若 vLLM raw usage 有已知特殊 token 口径，必须先用 test 前冻结且可复算的 normalization 规则处理；
验收要求 `normalized(T_native) == T_recount`，任何未解释差异都失败。不能拿原始 `messages[]` 的 token
数冒充 final-prompt recount。`T_components` 必须无重叠、有 remainder，
并与 `T_recount` 对齐，但其名称始终是 deterministic attribution。

## KR-06：MCP 发布包可供 Agent 安装调用

`integrations/mcp` 必须产出锁定版本的 wheel 与 sdist，并满足：

- fresh virtual environment locked install；
- `milai-mcp --profile reader-lite` 从非仓库 cwd 启动；
- official MCP Client 与独立 JSON-RPC Host 完成 initialize/list/call/reconnect；
- 当前协议 `2026-07-28` 与兼容协议 `2025-11-25` 均通过；
- wheel/sdist 逐成员检查，无 `.env`、secret、cache、log、Blob、backup 或不安全路径；
- `reader-lite` 精确只有 `milai_recall`；
- `reader-detail`、`submitter`、`operator` 为独立 allowlist；
- 所有 schema `additionalProperties=false`，输出有界且 typed；
- 无 reviewer、直接 Claim/OpenIssue mutation、bulk delete、tenant clear 或 database query tool；
- `agent-config` 只生成环境变量占位符，不复制 token。
- OpenWorker 目标 musl/Python 环境使用完整 hash-locked wheelhouse 离线 clean install；
- 发布 wheelhouse 固定 MiLAi 与所有传递依赖，不接受本次预检中的无界联网解析结果作为 lock。

## KR-07：OpenWorker MCP Host 与凭据隔离

必须交付可复现的 OpenWorker 接入面，并满足：

- 锁定 Worker 镜像、platform、OpenCode、Python、uv、relay、MCP 和 wheelhouse 完整摘要；
- 保留 Worker/OpenCode 上游来源和授权记录；授权不明时只允许本地验证，不对外分发镜像；
- OpenCode `mcp` 配置位于受控 image template，container restart/recreate/upgrade 后自动恢复；
- Worker 内只含无可导出 MiLAi secret 的 relay；其已挂载 socket 明确视为授权 capability；配置中不得
  出现 `{env:MILAI_AGENT_*_TOKEN}`、Runtime URL 或 DSN；
- broker 在 Worker 外固定 profile、Scope、authority、consistency floor、limit、token 和 loopback URL；
- OpenWorker 只能通过按 profile 分离的 Unix socket 调用，不能直连 Runtime REST/PostgreSQL；
- `env`、`/proc`、OpenCode config/debug API、bash、Skill、log 和 crash dump 对抗扫描均不得获得 MiLAi token/DSN；
- reader/submitter/operator 必须由同一 Host-policy manifest 预声明，但使用不同 container/process、socket、
  token、Scope 与 authority；普通 reader 既不能挂载也不能打开 submitter/operator socket；
- relay/broker 中断、socket 替换、错误 profile、过宽 Scope、非法权限、配额耗尽和 stale Runtime
  必须 fail closed；
- 不挂载 Docker socket、Runtime `.env`、主机 secret 目录或 PostgreSQL socket，不使用 host network/privileged mode；
- 锁定并验证 §4.4 的 capabilities、seccomp、LSM、namespace、device、network、mount、read-only rootfs
  与 no-new-privileges；容器 root 不得成为 host/broker/Runtime authority；
- broker 强制每 socket 并发、速率、request/frame/message bytes、idle、child ceiling 和时间窗 quota；
- 一键 disable、socket unmount、broker stop、token revoke 与 Worker image rollback 均经过演练。

## KR-08：vLLM Agent × MCP E2E

使用唯一获批的本地 vLLM 驱动 OpenWorker Agent，从最终冻结 Worker image 经 relay/broker
执行 S1～S10。通用可信 Host 的直接 `milai-mcp` E2E 可作对照，不能替代 OpenWorker lane。
验收必须证明：

- MCP 工具确由 Agent Host 发现并调用，而不是测试直接调用 Python function；
- MCP recall 返回的 canonical position、OpenIssue、abstention、degraded 和 trace 被原样保留；
- MCP result 作为 `trust=data-only`，其中内容不能改变 system/tool policy；
- `ACTION_SAFE` 使用非空 Host Scope 与 `CANONICAL_REQUIRED` floor；
- model/tool args 不能提升 profile、Scope、authority、consistency 或 limit；
- reader lane 对写请求只能产生 handoff intent；显式批准的独立 submitter lane 只产生 Evidence/Proposal
  receipt，不能把 Proposal 当成可召回 truth，也不能 self-review；
- revoke 后旧 slot/cache 与 stale FTS/vector 不能返回 action-safe 内容；
- `CACHE_CANONICAL` 每次复验 canonical position 与 OpenIssue revision；报告
  `cache_validation_requests`、`cache_validation_ms`、`validated_cache_hit_rate` 和
  `cache_invalidation_rate`；payload 未重注入不等于 memory-system cost 为 0；
- 报告 vLLM input/output tokens、额外模型/tool rounds 和端到端 wall time；
- 报告 Worker→relay→broker→Runtime 各段延迟、失败类型和重连次数；
- 完成 Worker restart/recreate 后的 MCP rediscovery，并保持工具目录与 Host policy 不变。

## KR-09：Codex 对抗证据审计与受控独立验收

确定性 gate 完成并冻结 bundle 后，才可调用 Codex CLI 精确模型 `gpt-5.6-sol`。默认使用 `high`
reasoning；只有 finding 冲突的二次裁决可单独使用 `xhigh`，并必须形成新的 run ID/usage 记录。
不使用会引入额外代理拓扑和不可比成本的 `ultra`。Codex MUST 只在 materialized frozen review
workspace 内执行；整仓路径禁止作为 `-C`。以下是执行模板，其中两个占位符必须在 approval 前替换
为精确 64-hex bundle digest，且两个值必须相等：

```bash
DG10_REVIEW_WORKSPACE="/review/DG10/sha256-<BUNDLE_SHA256>"
DG10_REVIEW_OUTPUT="/review-output/DG10/sha256-<BUNDLE_SHA256>.jsonl"

test -f "$DG10_REVIEW_WORKSPACE/review-manifest.json"
test ! -e "$DG10_REVIEW_WORKSPACE/.git"

codex exec \
  -m gpt-5.6-sol \
  -c 'model_reasoning_effort="high"' \
  --sandbox read-only \
  --ephemeral \
  --ignore-user-config \
  --skip-git-repo-check \
  --json \
  --output-schema "$DG10_REVIEW_WORKSPACE/contracts/dg10-review.schema.json" \
  -C "$DG10_REVIEW_WORKSPACE" \
  - < "$DG10_REVIEW_WORKSPACE/review-prompt.md" \
  > "$DG10_REVIEW_OUTPUT"
```

命令是目标配置，不代表本文修订时已经调用。执行时必须先验证 Codex CLI/version、精确 model slug
和支持的 reasoning effort；workspace 与 output 都必须位于仓库外，Codex 不得直接写仓库。review schema
至少要求：`decision`、`findings[]`、`severity`、`criterion`、`file/line/hash`、`reproduction`、
`coverage`、`unverified[]`、`model/cli/prompt/schema/source digests`。

独立验收分两层：

1. 受控脚本/fresh reviewer 复算 inventory、package/archive、vLLM identity、A/B、benchmark score、
   OpenWorker closure 与全部负向门；
2. Codex 作为 adversarial evidence auditor，只对同一冻结证据做交叉审计，查找证据缺口、断言膨胀、benchmark 污染、测试遗漏、
   security/privacy/rollback 问题并生成 `REVIEW_CANDIDATE`；
3. importer 验证 schema、所有引用 hash/line、prompt 与输出 digest；不可复现引用一律拒绝；
4. 受控 reviewer 对每个 finding 重放并输出新 `PASS / REVISE / REJECT` 记录。

只有 CRG-02 独立记录明确 `PASS`、开放 P0/P1 为 0，且 claim matrix 证明 L1～L4 已接受、
L4 outcome=`TARGET_MET`，才可晋级 `Local vLLM MCP Agent Candidate`。该 PASS 仍保持
`OE-F06 OPEN / PARKED`，不自动批准外部 Provider、
Production、Remote MCP、真实个人数据或 Schema freeze。

---

# 6. 工作包与执行顺序

| Task | 工作包 | 输入 | 交付物 | 退出条件 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| `DG10-00` | 冻结当前候选身份 | candidate.2.4、package/frozen manifest | current-byte inventory 与外部 digest | 无漂移、无 secret/cache | `REBUILD FOR FINAL` |
| `DG10-07` | MCP release hardening | client/MCP source locks | wheel、sdist、manifest、config | clean install、archive scan、protocol pass | `AUTHOR CANDIDATE` |
| `DG10-08` | OpenWorker Host adapter | Worker image + MCP package | locked image、container threat model、relay、broker、UDS capability policy | 无可导出 secret、有界 capability、可撤销 | `AUTHOR CANDIDATE / CONTRACT REVERIFY` |
| `DG10-09` | vLLM Agent MCP E2E | frozen vLLM + OpenWorker + broker + Runtime | S1～S10 redacted report | 真实 wire 与故障路径通过 | `AUTHOR CANDIDATE` |
| `DG10-12` | Benchmark contract | upstream datasets + adapters | feasibility、dataset lock、threshold artifact、三组 runner/grader | 模态可行、dev/test 隔离、同模型、可复算 | `NOT STARTED` |
| `DG10-13` | 公开 memory/tool characterization | frozen harness | LongMemEval(-V2)/BFCL 报告 | 结果按 TARGET_MET/BELOW_TARGET/NA 分离 | `NOT STARTED` |
| `DG10-14` | Serving/E2E 性能 | vLLM custom JSONL + S1～S10 | raw/E2E 分段性能报告 | p50/p95/p99、tokens、资源可核对 | `NOT STARTED` |
| `DG10-15` | Codex adversarial evidence audit | materialized frozen review workspace | schema-valid `REVIEW_CANDIDATE` + receipt | exact sol、闭集只读、引用可重放 | `NOT STARTED` |
| `DG10-10` | 受控独立接受 | 全部 digest/报告/review candidate | independent acceptance | `PASS` 且 P0/P1=0 | `NOT STARTED` |
| `DG10-11` | 发布与回滚演练 | accepted local candidate | release note/runbook/rollback report | 可安装、禁用、撤销、恢复 | `NOT STARTED` |
| `DG10-01..06` | 外部计费 Provider 扩展 | external model/approval/invoice | 原计划的 capture/billing/reconcile | 单独授权并关闭 OE-F06 | `PARKED / OUT OF CURRENT SCOPE` |

当前主链按明确 freeze boundary 执行：

```text
A. Freeze
   DG10-00

B. Integration
   DG10-07 package → DG10-08 trust boundary → DG10-09 E2E

   ===== Integration Candidate Boundary / freeze integration bytes =====

C. Evaluation
   DG10-12 benchmark contract → DG10-13 quality → DG10-14 performance

   ===== Evidence Freeze Boundary / materialize review workspace =====

D. Independent Acceptance
   DG10-15 adversarial evidence audit → DG10-10 controlled acceptance

   ===== Accepted Local Candidate =====

E. Operationalization
   DG10-11 release / revoke / rollback
```

`DG10-09` 完成并生成 integration inventory 后，Runtime、Client、MCP、relay、broker、OpenWorker image/config
和 Host-policy manifest MUST 停止变更。任何 integration byte 变化都使 L1～L3 及下游 evidence 失效，
必须从 `DG10-00/07/08/09` 重建；benchmark-only adapter/report 变化不得混入 integration lock。

`DG10-12/13/14` 可在不改变 vLLM 服务和 integration bytes 的前提下并行准备，但 test labels/outputs
只能在 feasibility、dev calibration 和 machine-readable thresholds hash freeze 后打开。
`DG10-15` 必须等待候选 inventory 和全部报告冻结；Codex review 后任何候选字节变化都使该 review
失效。`DG10-01..06` 不得混入当前 run，也不得用 Codex 调用替代外部 Provider 证据。

---

# 7. Gate

| Gate | 判定条件 | 当前状态 |
| --- | --- | --- |
| `PVL-00 Identity` | vLLM/model/tokenizer/template/startup/GPU/route 精确冻结 | `AUTHOR CANDIDATE / REVERIFY` |
| `PVL-01 Closed Adapter` | local adapter execution/dependency/host closure 独立可重建，无外部 egress | `AUTHOR CANDIDATE / REVERIFY` |
| `PVL-02 A/B Capture` | 500+500 完整、native ID/usage/tokenizer recount 可核对 | `AUTHOR CANDIDATE / REVERIFY` |
| `PVL-03 Token/Efficiency` | same-vLLM native/recount/attribution、round、latency 可复算 | `AUTHOR CANDIDATE / REVERIFY` |
| `PVL-04 OpenWorker E2E` | final image 经真实 MCP wire 完成 S1～S10 | `AUTHOR CANDIDATE / REVERIFY` |
| `PVL-05 Local Provider Acceptance` | PVL-00..04 独立通过；不依赖 public quality target | `NO-GO` |
| `MCG-00 Package` | MCP wheel/sdist clean install、archive scan、lock 通过 | `PASS_LOCAL / REVERIFY` |
| `MCG-01 Protocol` | 双协议、双 Host、重连、严格 schema 通过 | `PASS_LOCAL / REVERIFY` |
| `MCG-02 Capability Safety` | profile、Scope、authority、consistency 与危险工具边界通过 | `PASS_LOCAL / REVERIFY` |
| `OWG-00 Reproducible Host` | Worker/OpenCode/relay/broker/wheelhouse 身份可重建，配置经重启保留 | `PASS_LOCAL_CANDIDATE / REVERIFY` |
| `OWG-01 Secret Isolation` | 受限容器 root/bash 无法取得 MiLAi secret/DSN，且无 Runtime 直连路径 | `PASS_LOCAL_CANDIDATE / CONTRACT REVERIFY` |
| `OWG-02 Capability Socket` | socket 明确作为授权；profile 隔离、替换/越权/配额/故障 fail closed | `PASS_LOCAL_CANDIDATE / CONTRACT REVERIFY` |
| `OWG-03 Container Boundary` | caps/seccomp/LSM/namespace/device/network/mount/rootfs identity 与反例通过 | `NO-GO / REVERIFY` |
| `BMG-00 Dataset Lock` | upstream version/license/files/case IDs、scorer 与 adapter mapping 冻结 | `NO-GO` |
| `BMG-00A Feasibility` | modalities/tools/input contract/model capability/lossiness 逐 case 冻结 | `NO-GO` |
| `BMG-01 Internal Governance` | S1～S10 + adversary 全量通过，安全失败为 0 | `AUTHOR CANDIDATE / REVERIFY` |
| `BMG-02 Long Memory` | 兼容集三组对照完成；LME-V2 full/adapted/NA 状态诚实分离 | `NO-GO` |
| `BMG-03 Agent Tool Calling` | BFCL V4 local/non-live 的 selection/args/no-call/multi-turn 表征完成 | `NO-GO` |
| `BMG-04 Serving/E2E` | raw vLLM 与 MiLAi E2E latency/tokens/throughput/resource 分段完成 | `NO-GO` |
| `BMG-05 Quality Contract` | machine-readable thresholds 在 test 前冻结；结果为 TARGET_MET/BELOW_TARGET | `NO-GO` |
| `CRG-00 Frozen Review Bundle` | review 输入脱敏、闭集、inventory-bound 且候选停止变更 | `NO-GO` |
| `CRG-01 Codex Sol Audit` | exact `gpt-5.6-sol` 仅在 materialized workspace 只读审计，引用可复现 | `NO-GO` |
| `CRG-02 Controlled Acceptance` | finding 全部重放，最终 P0/P1=0 且有新接受记录 | `NO-GO` |
| `PVG-00..04 External Billing` | 外部 Provider authorization/capture/invoice/reconcile | `PARKED；OE-F06 OPEN` |

Gate 到层级的唯一映射由 claim matrix 给出：L1=`MCG-*`；L2=`OWG-*`；L3=`PVL-* + BMG-01`；
L4=`BMG-00/00A/02/03/04/05`；L5=`CRG-*`。`PASS_LOCAL / REVERIFY` 或
`PASS_LOCAL_CANDIDATE / REVERIFY` 表示现有作者证据可复用为输入，但不是 `ACCEPTED`。

L4/L5 缺失或失败不撤销已接受的 L1/L2/L3 claim；它只阻止聚合状态
`LOCAL_VLLM_MCP_AGENT_CANDIDATE`。BFCL/模型质量低于目标必须标 `MODEL_QUALITY_BELOW_TARGET`，不能
误报 MCP wire/security 失败；任何 Codex `PASS` 文本都不能绕过 `CRG-02`。

---

# 8. Evidence 合同

## 8.1 仓库外保留

以下对象可能含敏感正文、模型输出或 review 运行元数据，必须放在操作者控制的仓库外证据目录：

```text
raw benchmark prompt, memory and model output
full vLLM A/B and benchmark per-case capture
vLLM request/serving/GPU raw logs
MiLAi scoped broker token and broker-only environment file
Codex stdout/JSONL, session/run metadata and API usage/cost receipt
any dataset artifact whose license forbids repository redistribution
```

仓库只保留这些对象的 SHA-256、大小、生成时间、数据分类、保管位置类别和独立 reviewer 结论。

## 8.2 仓库内计划交付物

建议使用以下路径；执行时以不覆盖历史记录的新日期/候选后缀创建：

```text
docs/contracts/DG-10-claim-matrix.yaml
docs/contracts/DG-10-quality-acceptance.yaml
docs/reports/DG-10-vllm-target-YYYY-MM-DD.md
docs/reports/DG-10-vllm-local-ab-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-mcp-package-gate-YYYY-MM-DD.json
docs/reports/DG-10-openworker-mcp-host-gate-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-benchmark-dataset-lock-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-benchmark-feasibility-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-longmemeval-v2-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-longmemeval-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-bfcl-v4-local-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-vllm-serving-e2e-candidate.N-YYYY-MM-DD.json
docs/reports/DG-10-release-candidate-YYYY-MM-DD.md
docs/reviews/prompts/dg10-independent-review.md
docs/reviews/schemas/dg10-review.schema.json
docs/reviews/DG-10-review-bundle-manifest-candidate.N-YYYY-MM-DD.json
docs/reviews/DG-10-codex-sol-review-receipt-candidate.N-YYYY-MM-DD.json
docs/reviews/DG-10-independent-review-candidate.N-YYYY-MM-DD.md
docs/runbooks/provider-mcp-agent.md
```

每个报告至少绑定：source revision、inventory/package/wheelhouse SHA、dataset/workload/grader SHA、
model/tokenizer/chat-template/vLLM identity、capture sidecar SHA、Host/GPU identity、开始/结束时间、
冻结 seed/generation/budget 和执行命令的无 secret 形式。
OpenWorker 报告还必须绑定 Worker image ID/digest、OpenCode bytes/version、rendered config digest、
relay/broker/UDS policy digest、container inspect 的脱敏摘要和 restart/recreate/rollback 证据。
container 摘要必须覆盖 §4.4 全部 threat-model 字段；UDS policy 必须覆盖 broker concurrency/rate/bytes/
idle/child/quota limits 及其拒绝测试。

Codex receipt 还必须绑定：Codex CLI version/hash、精确 `gpt-5.6-sol` slug、reasoning effort、sandbox、
ephemeral/ignore-user-config 选项、prompt/schema/source bundle digest、开始/结束时间、退出状态、输出 digest、
usage/cost（或明确 `UNAVAILABLE`）与 importer 校验结果。Codex 看到的文件闭集必须显式列出，不能用
“整个工作区”作为不可复算输入描述。receipt 还要绑定 materialized workspace 的绝对路径类别、
manifest root、mount/read-only/no-git/no-secret/no-socket 检查和仓库路径不可读反例。

---

# 9. 测试矩阵

## 9.1 vLLM 正向

```text
exact model/tokenizer handshake
final-serialized-prompt recount matches normalized vLLM native usage
all native calls terminal with unique request IDs
logical=1000, native=1000, baseline=500, optimized=500, hidden/extra=0
baseline/optimized alternating workload complete
capture atomic and review-required
same-model quality and safety scoring complete
no external egress and no Codex-generated sample
GPU/serving identity and resource window recorded
```

## 9.2 vLLM 负向

```text
wrong model/image/tokenizer/template/startup or endpoint route
dataset/plan/report/source/package digest drift
missing, duplicated or foreign native request ID
vLLM usage differs from tokenizer recount
nonterminal/hidden extra model call
over input/output/request/time budget
secret reflected in output or stderr
adapter/helper cannot be proven terminal
dependency/host executable missing, extra, replaced or changed
external DNS/proxy/provider route becomes reachable
timeout and partial-line response
```

所有负向用例必须在 model call 前拒绝，或输出有界 `FAIL_PARTIAL`；不得产生 PASS。

## 9.3 MCP 正向

```text
fresh wheel/sdist install from non-repository cwd
stdio initialize/list/call/reconnect with two independent hosts
reader-lite exact one-tool catalog
reader-detail ID-based recovery
submitter Evidence/Proposal receipts
operator revoke/deletion status
structured and text result compatibility
Agent preserves OpenIssue/trace/abstention/degraded fields
```

## 9.4 MCP 负向

```text
unknown argument rejected
profile/scope/authority/consistency/limit override rejected or capped
reader token cannot submit/revoke/review
submitter cannot review or direct-write Claim
operator cannot create Proposal
MCP output/prompt injection cannot alter host policy
oversized output returns bounded truncation state
Runtime/DB unavailable yields explicit abstention/failure
revoked/stale result cannot re-enter Agent slot
token/DSN/provider secret absent from config, output, logs and package
```

## 9.5 OpenWorker 专项

```text
exact Worker image/OpenCode/Python/uv/relay/broker/wheelhouse identity
offline clean install on the exact musl/architecture target
OpenCode config schema validation and exact reader-lite catalog
container restart/recreate/upgrade preserves MCP discovery
stdio fragmentation, backpressure, EOF, child crash and reconnect
one socket maps to exactly one profile/token/policy
reader detects write need but cannot access submitter/operator socket
explicit handoff reaches a separately approved submitter lane and produces only Evidence/Proposal receipt
env/config/debug API/proc/bash/Skill/log/crash dump reveal no MiLAi secret or DSN
Worker cannot reach Runtime REST/PostgreSQL except through the capability socket
socket replacement, symlink, permission widening and profile substitution fail closed
socket concurrent/rate/bytes/frame/message/idle/child/quota ceilings reject boundedly
broker unavailable or Runtime unavailable produces bounded failure/abstention
no Docker socket, host secret directory, runtime .env, privileged or host-network mount
effective capabilities/seccomp/LSM/namespaces/devices/routes/mounts/rootfs match frozen threat model
CAP_SYS_ADMIN/CAP_NET_ADMIN/host PID-network/dangerous device or mount adversaries fail the Host gate
disable, socket unmount, token revoke and image rollback leave no stale MCP capability
```

OpenWorker Skill 测试只验证使用语义：调用 recall 的时机、`ABSTAINED`、OpenIssue、trace 和
data-only 处理。Skill PASS 不能替代 MCP catalog、broker 隔离或凭据负向测试。

## 9.6 封装后端到端执行顺序

每个 release candidate 必须从空临时目录和 fresh database 按以下阶段顺序执行；不得从开发目录、旧 venv、
旧 Worker container 或旧 benchmark cache 起跑：

1. **Identity**：复算 source inventory、package manifest、vLLM/model、Worker/OpenCode、数据和 grader；
2. **Build**：构建 Runtime/Client/MCP/relay/broker/wheelhouse/image，逐成员 archive/secret scan；
3. **Install**：在非仓库 cwd clean install，执行 `doctor/status`、MCP 双 Host initialize/list/call；
4. **Foundation**：fresh exact-role PostgreSQL migration + Runtime 全套测试，确认 0 残留连接后清理；
5. **A/B**：复核或按变更影响重放 same-vLLM workload，精确 `500+500=1,000 logical/native`；
6. **E2E**：fresh profile-specific reader/submitter lanes 经 Gateway→vLLM 与 relay→broker→MCP→Runtime
   回放 S1～S10；
7. **Failure injection**：逐项断 vLLM、relay、socket、broker、Runtime、canonical DB，测试重连、quota
   与 fail closed；
8. **Restart/Rollback**：restart/recreate 后重放 S1/S3/S5/S6/S8；执行 disable/unmount/revoke/rollback，
   再恢复同一 final candidate；
9. **Integration freeze**：冻结 DG10-07/08/09 bytes、Host-policy manifest 与 L1～L3 inventory；此后不改；
10. **Feasibility/Calibration**：先完成 BMG-00A，再用 dev 冻结 adapter、scorer、schedule 和 thresholds；
11. **Public benchmark**：每个 case 有三个 arm，按预先冻结的 Latin-square 分组 counterbalance 并 interleave：
    `A: NO→RAG→MILAI`、`B: RAG→MILAI→NO`、`C: MILAI→NO→RAG`；不得全程固定单一 arm 顺序；
12. **Serving**：按 T0～T3 分层压测 concurrency `1/4/8`，请求长度取实际 prompt 分布；
13. **Evidence freeze**：生成 redacted reports、inventory 与 repo-external sidecar，materialize 只读 review workspace；
14. **Review**：确定性 gate 先过，再执行 Codex Sol adversarial audit，重放 finding，生成受控接受记录。

任何阶段失败都保留独立、不可覆盖的 partial report；修复后使用新 candidate/run ID 从受影响阶段及其
下游重跑。禁止把不同 model identity、不同 package、不同 dataset digest 或不同 Host policy 的结果拼成 PASS。

## 9.7 Memory benchmark 评分

| 维度 | 指标 |
| --- | --- |
| 答案 | accuracy/F1/official task score，按能力与总体报告 |
| 证据 | evidence Recall@k、Precision@k、MRR、unsupported answer rate |
| 更新/时间 | knowledge-update、temporal-order、latest-valid-state accuracy |
| Abstention | no-answer/OpenIssue precision、recall、false-certainty rate |
| 治理 | cross-scope、revoked/stale、authority escalation、false closure，全部零容忍 |
| Token | system/tool/current-query/memory/output 分项，per-case/turn/session 分位数 |
| 运行 | model rounds、MCP rounds、route NONE/CACHE_CANONICAL/L0/L1、validated cache hit/invalidation |
| Cache validation | requests、validation ms、validated hit rate、invalidation rate；payload reuse 不记作零成本 |
| 延迟 | MCP、Runtime、retrieval、vLLM queue/prefill/decode、E2E p50/p95/p99 |

LongMemEval-V2 只有在 BMG-00A 判官方输入兼容时才报告其官方-compatible frontier；否则只报告
`ADAPTED_PROTOCOL` 的覆盖与 local 指标。LongMemEval 按五类分别报告。BFCL 分别报告 tool selection、
argument correctness、relevance/no-call、多轮恢复和非法工具调用率；它验证 model/tool-selection semantics，
不验证 stdio framing、initialize/list_tools、JSON-RPC reconnect、relay、broker 或 UDS，这些只由 MCG/S1～S10 证明。

Tier 1 deterministic metrics 是 release quality gate 的主输入；Tier 2 blinded human subset 审计其偏差；
Tier 3 same-vLLM judge 只作 characterization。安全失败仍为 0；没有额外隐藏 model round；数值判定完全
来自 test 前冻结的 `DG-10-quality-acceptance.yaml`。质量低于阈值令 L4 outcome=`BELOW_TARGET`，阻止聚合
Local Candidate claim，但不得把已成立的 L1/L2/MCG integration claim 改写成失败。

## 9.8 Serving 与 MiLAi 开销 benchmark

使用 vLLM 官方 `vllm bench serve` 或与当前 `0.27.1` 兼容的官方入口，对同一 endpoint 运行冻结 custom
JSONL；不改变现有服务启动参数。性能 gate 必须使用 exclusive serving window；若无法独占，必须冻结并
报告并发背景负载/request IDs/queue 状态并标 `CHARACTERIZATION_ONLY`，不得据此接受 p95/p99 阈值。

至少报告 request throughput、input/output/total token throughput、TTFT、TPOT/ITL、E2E latency、失败率、
concurrency 和四层对照：

```text
T0  raw vLLM endpoint
T1  OpenWorker → Gateway → vLLM, no memory
T2  OpenWorker with MiLAi integration, Router NONE, no MCP call
T3  OpenWorker → MCP → Runtime → vLLM, memory used
```

计算：

```text
Gateway overhead              = T1 - T0
Agent integration overhead    = T2 - T1
Memory control service cost   = measured relay + broker + MCP + Runtime + retrieval
Effective memory E2E overhead = T3 - T1
MiLAi token overhead          = model_input_T3 - model_input_T1
memory efficiency             = quality gain / extra input tokens
```

必须同时报告 T0～T3 绝对值和差值，且将 vLLM queue/prefill/decode 与 relay/broker/MCP/Runtime/retrieval
分开。T3-T1 混合了 memory control 与更长 prompt 的 prefill，因此不能冒充纯 service-side latency。性能结果只能
用于当前硬件/模型/并发声明，不得外推到其他 GPU、模型、量化或生产负载。

## 9.9 Codex review 对抗门

在正式 review 前先用无敏感 sentinel bundle 验证：只从 materialized workspace 启动；repo/父 workspace
不可读；read-only sandbox 无候选写入；`.git/.env`、secret、raw capture、Runtime/broker/vLLM route/socket
不在闭集；输出通过 JSON Schema；伪造 file/hash/line 引用被 importer 拒绝；candidate 漂移令 review
失效；timeout/partial/非零退出不能生成 PASS。正式 review 至少检查：

```text
claim-to-evidence traceability
benchmark dataset contamination and denominator symmetry
same-model and no-hidden-call proof
token/latency accounting boundaries
MCP scope/authority/OpenIssue/revocation/cache invariants
OpenWorker secret/network/socket isolation
package/archive/restart/rollback reproducibility
unsupported completion or status inflation
```

---

# 10. Agent 配置目标

## 10.1 通用可信 Host

最终配置必须由以下命令生成骨架，而不是手写包含 token 的配置：

```bash
cd runtime
uv run milai-ops agent-config --transport stdio --profile reader-lite
```

Host 的有效策略至少为：

```text
MILAI_BASE_URL=http://127.0.0.1:<loopback-port>
MILAI_AGENT_TOKEN=${MILAI_AGENT_READER_TOKEN}
MILAI_AGENT_SCOPE_JSON={"project_ids":["milai"]}
MILAI_AGENT_REQUIRED_AUTHORITY=ACTION_SAFE
MILAI_AGENT_CONSISTENCY_FLOOR=CANONICAL_REQUIRED
MILAI_AGENT_MAX_LIMIT=3
```

MCP command 指向 fresh-installed `milai-mcp`，参数默认为 `--profile reader-lite`。本 Goal 的模型 Host
只允许使用第 3.3 节冻结的 vLLM endpoint/model；任何其他 model slug 或远程 base URL 都令本次结果失效。
vLLM/Gateway 配置不进入 MiLAi MCP 环境，MiLAi token/Scope 也不进入模型环境。

## 10.2 OpenWorker Host

OpenWorker 不得使用上述 token-bearing child-process 配置。目标 OpenCode 模板只声明无可导出
MiLAi secret 的 local command；其 socket 参数本身是 capability，不得描述为 unauthenticated：

```json
{
  "mcp": {
    "milai": {
      "type": "local",
      "command": [
        "/usr/local/bin/milai-mcp-relay",
        "/run/milai-mcp/reader-lite.sock"
      ],
      "enabled": true,
      "timeout": 10000
    }
  }
}
```

`milai-mcp-relay` 已作为 local candidate 实现并固化到派生镜像；它仍不是已独立验收的发布命令。
最终配置不得包含
`environment.MILAI_AGENT_TOKEN`、`{env:MILAI_AGENT_*_TOKEN}`、Runtime URL 或任何 secret file path。

broker 侧才能将以下值注入精确 MCP 子进程：

```text
MILAI_BASE_URL=http://127.0.0.1:<loopback-port>
MILAI_AGENT_TOKEN=<broker-only reader token>
MILAI_AGENT_SCOPE_JSON={"project_ids":["milai"]}
MILAI_AGENT_REQUIRED_AUTHORITY=ACTION_SAFE
MILAI_AGENT_CONSISTENCY_FLOOR=CANONICAL_REQUIRED
MILAI_AGENT_MAX_LIMIT=3
milai-mcp --profile reader-lite
```

派生镜像必须在 `/openworker/image/config/opencode.json` 或等价上游受控模板中固化该配置。
仅在容器内执行 `opencode mcp add` 不构成持久交付。

## 10.3 Codex review Host

Codex review 运行在与 OpenWorker/vLLM benchmark 分离的评审进程，不注册为 MCP tool，也不能连接
MiLAi Runtime、PostgreSQL、broker socket 或 vLLM endpoint。允许输入由 frozen review manifest
显式枚举并 MUST materialize 到仓库外只读 workspace；禁止从 MiLAi repo、其父目录或包含 `.git`
的 working tree 启动。允许输出仅为独立仓库外 JSON/JSONL 和脱敏 receipt。

materialized workspace 必须具有：

```text
review-manifest.json with sorted unique path/size/SHA-256 closure
selected reports/contracts/tests/source only
no symlink, hardlink alias, FIFO, device or socket
read-only mount after materialization
no .git, .env, raw capture, raw prompt, raw memory or credentials
no Runtime/PostgreSQL/broker/vLLM route or socket
only the separately approved Codex service/auth path required by the CLI
```

`--sandbox read-only` 只证明写限制，不证明读闭集。外层 launcher MUST 使用独立 mount/filesystem namespace、
容器或等价 OS boundary，只挂载 materialized bundle 与必要 Codex runtime/auth；并以负向测试证明 MiLAi repo、
其父 workspace、Runtime/broker socket 和 vLLM route 不可读/不可达。

执行者必须在调用前确认：

```text
codex --version is frozen
codex debug models contains exact gpt-5.6-sol
model_reasoning_effort is high（second adjudication may use xhigh）
sandbox is read-only
ephemeral and ignore-user-config are enabled
output schema/prompt/source bundle hashes match approval
no secret/raw benchmark material exists in review input closure
working directory equals the manifest-bound materialized bundle root
repository and parent-workspace paths are unreadable from the review process
```

若 Codex CLI、精确模型或 schema 输出不可用，本地确定性测试可以继续，但 `CRG-01/02` 保持
`NO-GO`；禁止自动降级为其他模型并沿用同一 review ID。

---

# 11. 失败、回滚与停止条件

## 11.1 vLLM / benchmark 回滚

- 停止 benchmark client，不停止、不修改当前共享 vLLM 服务；
- 保留有界 partial receipt、已完成 case ID 和资源窗口，不自动无限重试；
- identity、dataset、package 或 generation 参数漂移时废弃整个受影响 run；
- 不把 partial 结果并入 baseline/optimized 或不同候选的完整样本；
- 清理本次 synthetic tenant/session/database，不修改正式 canonical 数据；
- 保持 `PVL-05/CRG-02 NO-GO` 与 `OE-F06 OPEN / PARKED`。

## 11.2 MCP 回滚

- Agent Host 移除或禁用 MCP child-process 配置；
- OpenWorker 先禁用 `mcp.milai`，再卸载 reader socket，停止 broker 并撤销对应 token；
- 将 Worker 回滚到已锁定的无 MiLAi MCP 镜像，并确认 restart/recreate 后工具目录不再包含 MiLAi；
- 撤销对应 MiLAi scoped token；
- 默认回退到无记忆 Agent，而不是复用 stale Context；
- 若只需降低工具面，回退到 `reader-lite`，不得以切 profile 提升权限；
- MCP 包回滚不回滚 Claim、Evidence、OpenIssue 或删除状态。

## 11.3 立即停止条件

出现任一情况必须停止本次发布：

```text
credential/prompt/memory/raw output 泄露
未经批准的外部网络或费用
vLLM/model/tokenizer/template/startup/GPU identity 或 usage 无法核对
模型别名漂移且无法固定真实版本
benchmark test 标签泄露到 prompt、调参或人工选择
NO_MEMORY/NAIVE/MILAI 组使用不同模型、预算、seed 或隐藏调用
incompatible modality 被丢弃/转写/外部 VLM 补齐却仍声称 official-compatible score
Codex 被用于生成/修复 benchmark 答案或直接修改候选
Codex 从 MiLAi repo/父 workspace 启动，或输入包含 secret/raw memory/raw prompt
Codex sandbox 可写候选，或 review process 可读 repo/Runtime/broker/vLLM 路径
Codex model 自动降级、输出引用不可复现或 review bundle 已漂移
跨 tenant、authority escalation 或 canonical bypass
live OpenIssue 被模型/MCP 压平成确定事实
revoked Evidence 经 cache/index/MCP 返回
Agent 获得 reviewer 或直接 canonical mutation 能力
package 含 .env、secret、Blob、backup、cache 或日志
OpenWorker env/config/proc/bash/Skill/log 可读取 MiLAi token 或 DSN
Worker 可绕过 capability socket 直连 Runtime/PostgreSQL
OpenWorker 集成依赖 host network、privileged 或 Docker socket
Worker 含未批准 capability/device/mount/host namespace，或 socket resource limits 未生效
restart/recreate 后 MCP 配置或 Host policy 丢失/漂移
Worker/OpenCode 来源、许可或发布权无法确认却仍对外分发
独立 reviewer 仍有开放 P0/P1
```

上述停止只使依赖层及其下游进入 `REVISE`；不得抹去不依赖该失败且仍绑定相同字节的已接受层。
例如 BFCL quality below target 阻止 L4/聚合 claim，但本身不能把 MCG wire correctness 改写为失败。

---

# 12. Definition of Done

每层独立完成、独立保留状态；只有最终聚合 claim 要求五层合取。

## 12.1 `DG10-L1 PACKAGE_VERIFIED`

1. `milai-client`、`milai-mcp`、relay/broker/wheelhouse/image 可从 clean、非仓库 cwd 安装；
2. wheel/sdist/image 无 secret、`.env`、cache、log、Blob、backup 或 unsafe member；
3. 双 Host/双协议 initialize/list/call/reconnect 通过，`reader-lite` 精确只暴露 `milai_recall`；
4. profile/Scope/authority/consistency/limit 不能由模型覆盖，危险 mutation/review tool 不存在。

完成后允许 claim：`MCP_PACKAGE_VERIFIED`；若 `BMG-01` 也已独立接受，则可单独声明
`MCP_INTEGRATION_PASS`。两者与 OpenWorker isolation、Provider 和模型质量状态分离。

## 12.2 `DG10-L2 HOST_ISOLATED`

1. OpenWorker image/platform、OpenCode、Python、uv、relay、broker、wheelhouse 和 Host-policy manifest 锁定；
2. §4.4 container threat-model 字段全部绑定，禁止 capability/device/mount/namespace/network 旁路；
3. Worker 不含可导出 MiLAi token/DSN；已挂载 UDS 明确作为 profile-specific bearer capability；
4. reader/submitter/operator 使用不同 lane/socket/token/policy，reader 不能打开高权 socket；
5. broker concurrency/rate/bytes/frame/message/idle/child/quota limits 及拒绝反例通过；
6. restart/recreate、disable、socket unmount、broker stop、token revoke、image rollback 可复现。

完成后允许 claim：`OPENWORKER_HOST_ISOLATED`；容器内 root 不得表述为任意 root/host root 安全。

## 12.3 `DG10-L3 LOCAL_PROVIDER_VERIFIED`

1. 唯一 Provider 为冻结的 vLLM `Qwen3.6-35B-A3B-FP8`，前后 identity 无漂移；
2. 精确 `logical=1,000`、`native=1,000`、`baseline=500`、`optimized=500`、`hidden/extra=0`；
3. vLLM native usage、final-prompt recount 和 component attribution 三层可复算；
4. final integration bytes 上的 S1～S10、S8 显式 handoff、governance adversary 与故障路径通过；
5. `CACHE_CANONICAL` 复验 position/Issue revision，并报告 validation cost；
6. OpenIssue、trace、abstention、degraded、revoke、stale projection/cache 无回归；
7. vLLM/MCP/relay/broker/Runtime/DB 任一不可用时 fail closed 或明确 abstain。

完成后允许 claim：`LOCAL_SAME_MODEL_AB` 和 `LOCAL_PROVIDER_VERIFIED`；尚不代表模型质量达标或
最终独立接受，其他 claim 仍按矩阵各自计算。

## 12.4 `DG10-L4 QUALITY_CHARACTERIZED`

1. BMG-00A 先冻结 modality/tool/input-contract/capability/lossiness；
2. dataset/version/license/file/case/scorer/mapping、dev/test 分离和 Latin-square schedule 完整；
3. `DG-10-quality-acceptance.yaml` 在 test labels/outputs 前 hash freeze；
4. Tier 1 deterministic、Tier 2 blinded human subset、Tier 3 same-vLLM characterization 分开；
5. LME-V2 只能按 feasibility 输出 official-compatible full、`ADAPTED_PROTOCOL` 或有理由的 N/A；
6. BFCL 只支持 Agent Tool Calling claim，不支持 MCP wire/protocol claim；
7. T0～T3、concurrency 1/4/8、exclusive/characterized window 与资源/latency/token 分层完整；
8. 结果明确写 `quality_outcome=TARGET_MET|BELOW_TARGET|CHARACTERIZED_ONLY|NOT_APPLICABLE`。

L4 协议完整即可 `ACCEPTED` 并声明 `QUALITY_CHARACTERIZED`；只有 `TARGET_MET` 才满足最终聚合 claim。
`BELOW_TARGET` 不撤销 L1～L3。

## 12.5 `DG10-L5 INDEPENDENTLY_ACCEPTED`

1. review 输入 materialize 到仓库外只读闭集；无 `.git/.env`、raw/secret/socket 或 repo 可读路径；
2. Codex CLI 使用精确 `gpt-5.6-sol`、read-only/ephemeral/high reasoning，只输出
   schema-valid `REVIEW_CANDIDATE`；
3. Codex 不参与 benchmark、不修改候选、不关闭 finding，只作为 adversarial evidence auditor；
4. file/line/hash/reproduction 由受控 reviewer 全部复核；最终独立记录 `PASS`，本地 P0/P1=0；
5. claim matrix 对报告 claim 与 Gate 依赖校验通过。

## 12.6 全局边界与聚合完成

`LOCAL_VLLM_MCP_AGENT_CANDIDATE` 仅在 L1～L5 全部 `ACCEPTED` 且 L4 outcome=`TARGET_MET` 时成立。
同时必须保持：`OE-F06 OPEN / PARKED`；无虚构 invoice/cost；Runtime `CANDIDATE`；Schema
`EXPERIMENTAL / NO-GO FOR FREEZE`；不扩大为 external-provider Beta、Remote、真实个人数据或 Production。

在 L5 和聚合条件完成前，允许的最高表述必须按实际层级选择，不能统一写成整项 PASS。例如：

```text
MCP_PACKAGE_VERIFIED; HOST_ISOLATION_REVIEW_REQUIRED;
LOCAL_PROVIDER_AUTHOR_CANDIDATE; QUALITY_NOT_STARTED; L5_NOT_ACCEPTED.
```

完成后允许的精确表述是：

```text
MiLAi has passed a same-model self-hosted vLLM validation, selected public
memory/tool benchmarks, and secret-isolated, bounded UDS-capability local stdio MCP integration
with OpenWorker for synthetic/de-identified workloads. External-provider
billing validation remains open and out of scope.
```

---

# 13. 下一最小可执行动作

本地 `DG10-07/08/09` 已完成到 `author candidate / independent reverify required` 边界：已生成并验证
musl/amd64 离线 wheelhouse、MCP wheel/sdist、双协议/双 Host 互操作、无可导出 MiLAi secret 的 relay、可信 broker、
本地派生 Worker image、重启/重建/故障关闭/回滚与凭据提取反例。全部仅使用 synthetic fixture，
外部计费 Provider 请求为 `0`、外部费用为 `0`；本地 vLLM 已执行候选 A/B/E2E。上游 Worker
授权未证实，派生镜像仍限本地、不对外分发。

## 13.1 已完成的本地候选链（`DG10-07/08`）

1. `docs/reports/DG-10-mcp-package-gate-candidate.2-2026-08-20.json`；
2. `docs/reports/DG-10-openworker-mcp-host-gate-candidate.2-2026-08-20.json`；
3. `docs/runbooks/provider-mcp-agent.md`；
4. `docs/reports/DG-10-current-byte-inventory-candidate.2.4-2026-08-20.json`。

这些是作者生成的本地候选证据，不是独立 `PASS`，不关闭 `OE-F06`，不宣称 external-provider Beta。

### 13.1.1 已执行的 `PV-LOCAL`

1. `docs/adr/ADR-023-self-hosted-vllm-validation-lane.md`；
2. `docs/reports/DG-10-vllm-local-identity-2026-08-20.json`；
3. `docs/reports/DG-10-vllm-local-ab-candidate.2-2026-08-20.json`；
4. `docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.4-2026-08-20.json`；
5. `docs/reports/DG-10-vllm-local-validation-2026-08-20.md`。
6. `docs/reports/DG-10-completion-audit-candidate.2.4-2026-08-20.md`。

candidate.2 的精确事实统一表述为：`logical_requests=1,000`、`native_model_requests=1,000`、
`baseline_arm=500`、`optimized_arm=500`、`hidden_or_extra_calls=0`；共有 1,000 个唯一 native ID；
baseline 488/500，optimized 500/500，optimized 输入 token 由 709,360 降为 365,560，
无额外模型轮次且安全失败为 0。reader-lite 已收紧为 query-only，consistency/limit
由 Host 固定，在已绑定 tokenizer 下精确为 250 tokens，所有已完成本地 A/B 门禁通过。
OpenWorker Gateway → 本地 vLLM → OpenCode → 无可导出 MiLAi secret 的 relay → UDS capability → broker
→ Runtime 的 S1～S10
已完成作者候选；candidate.2.4 还证明 restart 前后完整配置字节、JSON 语义、MCP 子对象
和 wire catalog 精确不变。独立复核、Worker 上游授权与 `OE-F06` 仍开放。全程未修改、
重启或重配置现有 vLLM。

## 13.2 下一执行链（`DG10-12..15`）

1. 生成 0.3.1 contracts/current-byte inventory，验证 claim matrix 与未冻结 quality threshold 模板；
2. 复验 L1～L3：精确 A/B 分母、S8 profile handoff、§4.4 container identity、UDS capability quota 和
   fresh S1～S10；通过后冻结 integration bytes/Host-policy manifest；
3. 执行 `BMG-00A`：先检查 upstream modality/tool/input contract 与样本 manifest，冻结 compatible、
   incompatible 和 adapted case IDs；不得先把 full-small 写成必过结论；
4. 在不进入 integration inventory 的隔离 research 目录核对 license，冻结 LongMemEval、可行的
   LongMemEval-V2 slice 与 BFCL V4 local/non-live case list；
5. 实现统一 `NO_MEMORY / NAIVE_RAG / MILAI_MCP` adapter；所有 adapter 只调用同一 vLLM，
   并为每个 case 输出一致的 usage/latency/trace schema；
6. 对 ≤10% dev 子集运行 calibration，生成并 hash freeze `DG-10-quality-acceptance.yaml`、prompt、
   answer parser、retrieval k、budget、scorer 与 Latin-square schedule，然后才打开 test；
7. 一次性执行 Tier 1；完成 blinded Tier 2 audit；Tier 3 same-vLLM judge 仅作为分列 characterization；
8. 在 exclusive 或完整 characterized serving window 中运行 T0～T3、concurrency 1/4/8；
9. 冻结 redacted evidence，materialize 仓库外只读 review workspace，验证 repo/secret/socket 不可读；
10. 用 KR-09 模板调用 `gpt-5.6-sol`，保存仓库外原始输出和仓库内脱敏 receipt；
11. 重放每个 finding；修复则产生新 candidate 并只重跑依赖层及下游，不修则给出可验证 rejection；
12. `CRG-02 PASS` 且本地 P0/P1=0 后，按 claim matrix 生成允许的阶段/聚合 claim，再执行 runbook。

## 13.3 外部 Provider 保留项

`DG10-01..06` 与既有 `docs/reports/DG-10-provider-target-2026-08-20.md` 保留为未来外部计费
Provider 扩展输入，当前不执行、不删历史、不计入本地 vLLM DoD。恢复该 lane 时必须获得新的用户授权、
预算、egress、数据边界与 invoice/receipt 可得性结论，并另发 candidate；Codex 调用不是该授权的替代品。

---

# 14. Goal Review 模板

```text
Goal ID / version: DG-10 / candidate.N
Review date:
Owner:
Provider: self-hosted vLLM only
Exact vLLM/model/tokenizer/template identity:
GPU/driver/CUDA/execution host identity:
L1 package state:
L2 host state:
L3 local-provider state:
L4 characterization state / quality_outcome:
L5 independent-acceptance state:
Aggregate claim requested:
Claim-matrix SHA-256:
Claim-matrix validation result:

Data/network/runtime-window boundary:
PV-LOCAL target/identity SHA-256:
A/B workload/capture/report SHA-256:
vLLM raw usage/resource sidecar SHA-256:
MCP package manifest SHA-256:
MCP wheelhouse root SHA-256:
OpenWorker image ID/digest/platform:
OpenCode binary SHA-256/version:
Rendered MCP config SHA-256:
Relay/broker/UDS policy SHA-256:
Container caps/seccomp/LSM/namespace/device/network/mount/rootfs identity:
UDS concurrency/rate/bytes/frame/message/idle/child/quota contract SHA-256:
OpenWorker upstream/license decision:
Agent E2E report SHA-256:
Dataset lock/root SHA-256:
Benchmark feasibility/modality report SHA-256:
Quality-acceptance threshold SHA-256 / frozen-before-test proof:
LongMemEval-V2 report SHA-256:
LongMemEval-V2 protocol: OFFICIAL_COMPATIBLE / ADAPTED_PROTOCOL / N/A
LongMemEval report SHA-256:
BFCL V4 local report SHA-256:
Optional LoCoMo report SHA-256 / N/A:
Tier 1 deterministic / Tier 2 blinded-human / Tier 3 same-vLLM reports:
T0/T1/T2/T3 serving/E2E performance report SHA-256:
Serving window: EXCLUSIVE / CHARACTERIZATION_ONLY

PVL-00..05 results:
MCG-00..02 results:
OWG-00..03 results:
BMG-00/00A/01..05 results:
CRG-00..02 results:
Negative/failure paths verified:
Secret/privacy scan result:
Worker credential-extraction adversary result:
Worker direct-Runtime/network adversary result:
Restart/recreate/rollback result:
Actual vLLM requests/input/output tokens/runtime/GPU resources:
NO_MEMORY / NAIVE_RAG / MILAI denominator symmetry:
Logical requests: 1000
Native model requests: 1000
Baseline arm: 500
Optimized arm: 500
Hidden/extra calls: 0
Native/recount/component-token reconciliation:
S8 reader→handoff→submitter lane result:
CACHE_CANONICAL validation metrics:
Quality/safety decision:
Codex CLI/model/reasoning/sandbox identity:
Materialized review-workspace path class / manifest root:
No-repo/no-git/no-secret/no-socket/read-only adversary result:
Codex prompt/schema/source bundle SHA-256:
Codex output/receipt SHA-256:
Codex usage/cost or UNAVAILABLE:
Codex findings replay result:
Known risks:
Open P0/P1/P2:
Rollback result:
Independent gate decision:
OE-F06 disposition: OPEN / PARKED
Schema/Runtime/Remote/data boundary banner:
Next smallest executable action:
```

---

# 15. 外部依据与版本冻结规则

- Codex 精确模型与 CLI 选择以 OpenAI 官方
  [Codex models 文档](https://developers.openai.com/codex/models)为准；执行日必须再次验证 slug 和 CLI 能力；
- LongMemEval-V2、LongMemEval、LoCoMo 使用各官方仓库的数据、grader 与许可；LME-V2 明确包含
  multimodal web-agent trajectories、screenshot artifacts/optional question screenshot，且默认 judge 可调用
  外部模型，因此必须先过 BMG-00A，不能把 text-only adaptation 当 official full-small；
- BFCL V4 使用官方 leaderboard/repository 对应的冻结 commit/package；它是 LLM function-calling
  evaluation，只选本地可复现、非 live case，不能作为 MCP transport/protocol 证明；
- vLLM serving 指标使用与当前 `0.27.1` 兼容的官方
  [benchmark CLI](https://docs.vllm.ai/en/latest/benchmarking/cli.html)；
- 以上链接只是来源入口，不是版本锁。实际 release 必须记录 commit/tag、文件 SHA-256、license、
  下载时间、执行环境与 adapter mapping；上游更新不得静默覆盖已接受 candidate。
