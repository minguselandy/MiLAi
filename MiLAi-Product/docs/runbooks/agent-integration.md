# MiLAi Agent 接入 Runbook

> Agent Integration `0.1 BETA CANDIDATE` · synthetic/de-identified only  
> Schema `0.1.x EXPERIMENTAL` · Runtime `CANDIDATE` · Remote `DISABLED`

## 1. 启动与诊断

在 `runtime/` 执行：

```bash
uv sync --frozen --dev --extra embedding
uv run milai-ops start --background
uv run milai-ops doctor --json
uv run milai-ops status --json
```

`start` 依次检查数据库、migration、角色、Worker/API，再运行隔离 smoke。单独重放：

```bash
uv run milai-ops smoke-test --env-file .env
```

它只创建唯一 `milai_smoke_*` 临时库和临时加密 Blob；当前 tenant 不接收 smoke 数据。停止：

```bash
uv run milai-ops stop --env-file .env
```

默认保留 PostgreSQL volume，项目不提供无确认删除 volume 的快捷命令。

## 2. 固定 Agent Scope 与 authority

Scope 和 authority 属于 host policy，不能成为模型可控 tool 参数：

```bash
export MILAI_BASE_URL=http://127.0.0.1:28080
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}'
export MILAI_AGENT_REQUIRED_AUTHORITY=ACTION_SAFE
export MILAI_AGENT_CONSISTENCY_FLOOR=CANONICAL_REQUIRED
export MILAI_AGENT_MAX_LIMIT=3
export MILAI_AGENT_BUDGET_CLASS=STANDARD
export MILAI_AGENT_CONTEXT_BYTE_BUDGET=16384
export MILAI_AGENT_SLOT_TTL_SECONDS=300
```

`ACTION_SAFE` 必须有非空 Scope，否则 Runtime/adapter fail closed。普通探索性读取可显式使用
`INFORMATIONAL`。token 只进入 host/子进程环境，不进入 Prompt、tool result 或保存的配置。

## 3. Python SDK

```python
from milai_client import (
    AgentRecallPolicy,
    AsyncAgentContext,
    AsyncMilaiClient,
    CallableTokenCounter,
)

client = AsyncMilaiClient(token=reader_token)  # 每个 Agent 生命周期复用并显式 close
counter = CallableTokenCounter("provider-tokenizer-v1", provider_count_tokens)
context = AsyncAgentContext(
    client,
    recall_policy=AgentRecallPolicy(
        scope={"project_ids": ["milai"]},
        authority="ACTION_SAFE",
        consistency_floor="CANONICAL_REQUIRED",
        max_limit=3,
    ),
    token_counter=counter,
)
prepared = await context.prepare(
    "用户偏好的编辑器主题",
    session_id="session-1",
    active_goal="回答且保留不确定性",
)
prompt_data = prepared.compiled.delta.rendered_context  # REPLACE；UNCHANGED 时不要重复注入
```

`prompt_data` 是 `trust=data-only`。必须保留 `ABSTAINED/DEGRADED`、OpenIssue、authority、
canonical position 和 trace，不能用模型常识补成“MiLAi 当前记忆”。

Slot cache 同时绑定 query/goal、Scope、authority、consistency、limit、canonical position、OpenIssue
语义 revision、编译器版本、tokenizer、全部 token/byte budget、constraints 与 TTL。同步/异步公开 API
不接受 `cache_validated`；调用方不能声明自己已经验证缓存。旧 checkpoint 若缺少 `cache_key` 或
`ttl_seconds` 会 fail closed 并重新 recall。

`CallableTokenCounter` 必须包装宿主 provider/model 的真实 tokenizer；无法提供时不要传，SDK 会继续
执行 byte ceiling，但将 token 指标标为未验证。模型调用返回实际 usage 时使用
`ModelCallResult(..., ProviderTokenUsage(...))`，否则 provider token 字段保持空值，绝不伪造。

Framework adapter 必须在 host 构造期创建不可变策略：

```python
from milai_client import AgentRecallPolicy

policy = AgentRecallPolicy(
    scope={"project_ids": ["milai"]},
    authority="ACTION_SAFE",
    consistency_floor="CANONICAL_REQUIRED",
    max_limit=3,
)
```

把该 `policy` 传给 `create_milai_tools`、`recall_node` 或 `MilaiMemory`。不要从 LangGraph state、
AutoGen query kwargs 或模型 tool arguments 读取 Scope/authority；这些覆盖会被 adapter 拒绝。
coding hook 同样只从上述 `MILAI_AGENT_*` 环境读取 recall 与 budget policy；stdin event 中出现对应
覆盖字段会被拒绝。

写入使用 submitter token、稳定 `operation_id` 和明确分类：

```python
receipt = submitter.capture_evidence(
    {
        "source_type": "TOOL_OBSERVATION",
        "source_ref": "ci://run/123",
        "subject_id": "project-runtime",
        "observed_at": "2026-08-17T12:00:00Z",
        "content": "synthetic fixture: Python 3.12",
        "data_classification": "SYNTHETIC",
        "permission_snapshot": {"readable": True},
    },
    operation_id="session-1:ci:123",
)
```

Evidence capture 与 Proposal create 是两个 receipt；Proposal 在独立 reviewer 批准前不可召回为
canonical truth。409 不自动重试；429/503/网络失败只以同 key、同 payload 做有界重放。
模型/extractor 产生的 Proposal 必须先构造 `ProposalDraft`，并提供 model ID、template version、
input snapshot SHA-256、Evidence branches、Scope/authority 与更新操作的 expected head；SDK、LangGraph
和 MCP 都在 HTTP 前执行同一验证。

## 4. MCP transport

Codex uses the P08 authenticated loopback Streamable HTTP facade:

```bash
cd integrations/mcp
export MILAI_BASE_URL=http://127.0.0.1:28080
export MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN"
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}'
export MILAI_AGENT_REQUIRED_AUTHORITY=INFORMATIONAL
export MILAI_MCP_HTTP_BEARER_TOKEN="$(openssl rand -hex 32)"
export MILAI_MCP_HTTP_PRINCIPAL_ID=codex-milai
uv run milai-agent-memory-mcp \
  --host 127.0.0.1 \
  --port 7337 \
  --resolve-budget-profile MCP_INTERACTIVE_STANDARD_V01
```

Configure Codex with `url = "http://127.0.0.1:7337/mcp"` and
`bearer_token_env_var = "MILAI_MCP_HTTP_BEARER_TOKEN"`; see
`examples/codex-mcp/config.toml.example`. `/healthz` and `/readyz` are public loopback probes,
whereas `/mcp` requires the inbound Bearer credential. That credential is distinct from the Runtime
credential in `MILAI_AGENT_TOKEN`. One P08 process binds one trusted principal to one fixed non-empty
scope; model tool arguments remain only `query` and optional `previous_context_id`.

`milai-agent-memory-mcp` fixes Streamable HTTP, the `agent-memory` profile, and zero automatic
Runtime retries. Its CLI deliberately cannot override those Product policy choices.

Stdio remains available for OpenWorker compatibility, SDK interoperability tests and local protocol
debugging. Generate its secret-free configuration skeleton with:

```bash
uv run milai-ops agent-config --transport stdio --profile reader-lite
```

Host 展开 `${MILAI_AGENT_READER_TOKEN}`。`reader-lite` 默认只暴露 recall；按 ID 恢复详情时才
启动 `reader-detail`。reader、submitter、reviewer、operator 是互斥 allowlist；reviewer 只增加
Proposal inbox/detail/review 所需能力，并使用与 submitter 不同的 actor。所有 profile 都没有
direct Claim update、issue resolve、tenant clear、bulk delete 或 database query 工具。
capture/propose/revoke 分别要求字面 `CAPTURE/SUBMIT/REVOKE` 确认。

已验证两个独立 stdio Host：官方 Python Client（协议 `2026-07-28`）和最小独立 JSON-RPC Host
（协议 `2025-11-25`），以及重连、structured+text output 和严格 unknown argument 拒绝。P08
另以真实 Codex `0.151.0` 验证 Streamable HTTP 的 required/no-memory/continuation 三种行为。
非 loopback HTTP、TLS/OAuth 和多 principal token issuance 仍未批准。

## 5. Framework 与自动 smoke

```bash
integrations/python-client/.venv/bin/python examples/generic-agent/smoke.py
integrations/langgraph/.venv/bin/python examples/langgraph/smoke.py
integrations/autogen/.venv/bin/python examples/autogen/smoke.py
integrations/mcp/.venv/bin/python examples/mcp-client/smoke.py
```

- LangGraph：recall node 在 model 前；Context node 保留分支/放电规则；checkpoint 只保留引用。
- AutoGen：`query/update_context` 写入 `milai-memory-data` user-data message；`clear` 禁用。
- coding hook：安装器默认 capture `OFF`；跨进程传递一个已校验 `memory_slot`，按 delta
  replace/remove/unchanged；只管理有标记配置，幂等可卸载。
- generic loop：由 host-side Router 选择 NONE/CACHE/L0/L1；NONE/CACHE 轮次不暴露 MiLAi
  工具，不进行隐式写入。

完整三会话真实数据库重放：

```bash
runtime/.venv/bin/python evals/agent_integration/e2e.py \
  --env-file runtime/.env \
  --report /tmp/milai-agent-e2e.json
```

报告必须为 `PASS` 且 cleanup 为 `PASS`。

规模门可以从任意 cwd 执行，并必须保留原始 JSON：

```bash
runtime/.venv/bin/python evals/agent_efficiency/postgres_scale.py \
  --env-file runtime/.env \
  --output docs/reports/OE-05-postgresql-scale-performance-2026-08-18.json
```

## 6. UI 与治理

打开 loopback Runtime 根页面，使用匹配工作的 scoped token。页面显示真实 capability profile、
data/crypto/remote 状态、watermark/lag、pending Proposal inbox，并可联合查看
Claim/Evidence/OpenIssue/Trace。复制 MCP 配置只复制环境变量占位符，不复制输入框 token。

普通 Agent token 不能 Review。Review 使用独立本地 reviewer token/人类 UI。撤销使用 operator
token，依次观察 logical revoke、canonical block、derived purge、primary erase、backup expiry。

## 7. 数据与发布边界

- `SYNTHETIC_ONLY`：仅接受 `data_classification=SYNTHETIC`；
- `DEIDENTIFIED_ALLOWED`：再允许 `DEIDENTIFIED`；
- `LOCAL_PERSONAL_DATA`：只有 crypto/key recovery gate 与用户批准后才能启用。

分类由可信 host/user 声明；MiLAi 不声称自动识别 PII。外部 Mem0/Graphiti/Hindsight export 先运行
`milai-ops import-dry-run`，只生成 hash/quarantine 报告，永远不自动执行导入。

本版本不是 Remote Beta、Production 或 Schema freeze。详见
`docs/known-limitations-agent-integration-0.1.md`。

## 8. 效率优化启用与回滚

默认推荐组合是 `reader-lite + deterministic router + governed compiler + persistent HTTP +
embedding prewarm`。这些都不拥有 canonical 写权限，也未新增正式状态表。

- 临时回到旧 Agent 调用：保留使用 `AgentMemory.before_model`，但会失去 Slot/Delta 和按需召回收益；
- MCP 兼容：把 host profile 从 `reader-lite` 显式改成 `reader`，不会提升当前 token 的权限；
- 关闭预热：`MILAI_EMBEDDING_PREWARM=false`，首次 L1 查询会承担冷启动；
- MMR 当前默认关闭；若实验中开启后质量或延迟回退，恢复
  `MILAI_RETRIEVAL_MMR_ENABLED=false`；
- Slot 校验失败、canonical position/Issue revision 改变或 Runtime 不可用时，必须丢弃 cache 并重新
  recall/abstain，不能为了可用性复用旧上下文；
- 回滚 adapter 或检索排序不得恢复 revoked Evidence、已清除 Blob、旧权限或已被 OpenIssue 阻断的
  candidate。

优化版本仍是本地 `CANDIDATE`。provider 实账和独立复审完成前，不把离线 token 估算宣传为成本承诺。

## 9. Provider A/B 证据门

`evals/agent_efficiency/provider_ab.py` 使用冻结的 synthetic/de-identified 100/500-turn workload，
对同一精确模型交替运行 current baseline 与 optimized 变体。它保留 provider native call identity、
原生 input/cached-input/output usage、目标 tokenizer 的 memory/tool 分项、模型轮次、wall time 和
质量/安全评分；不保留 prompt、memory、原始输出或 stderr。工具生成的 usage 始终标记为待独立
provider 复核，不会自行宣称 verified。

先复制并填写以下模板；manifest 和 pricing snapshot 不得包含 secret：

```text
evals/agent_efficiency/provider_adapter_manifest.example.json
evals/agent_efficiency/provider_dependency_lock.example.json
evals/agent_efficiency/provider_host_execution_lock.example.json
evals/agent_efficiency/provider_approval.example.json
evals/agent_efficiency/provider_pricing_snapshot.example.json
evals/agent_efficiency/provider_billing_evidence.example.json
evals/agent_efficiency/normalized_provider_billing_export.example.json
```

adapter 必须实现 v3 manifest/approval（JSONL wire protocol 仍为 v2）
`evals/agent_efficiency/PROVIDER_ADAPTER_CONTRACT.md`。runtime/source/dependency lock 必须在 workspace
和 `/root` 外；approval SHA-256 由操作者带外提供，manifest 不能自己声明可信 approval digest。
approval 同时绑定 workload、pricing、精确 shipped tool schema、sandbox/egress 工具、静态 provider IP
白名单、secret 名、非 root uid/gid、Landlock 文件策略、host execution closure、1000 次请求、
input/output/cost 和账单 tolerance。
dependency lock 必须列出 runtime 库、所有导入代码/数据、每个子程序和其传递依赖；未声明的文件读取或
程序执行会被内核拒绝，Landlock ABI 不足时整个运行 fail closed。真实执行要求
root 仅用于建立 mount/PID/network namespace，随后 adapter 降权；workspace、`/root`、通用 DNS 和非
白名单网络均不可见。provider secret 只允许通过 approval 绑定的
`MILAI_PROVIDER_CREDENTIAL_*` 别名传入；adapter 必须显式读取别名并传给 SDK，不能声明或依赖
`OPENAI_API_KEY`、`PYTHONPATH`、`LD_PRELOAD`、`BASH_ENV`、proxy 或其他运行时控制变量。

在填写 manifest/approval 之前，从本次真实执行宿主生成 host execution lock；该命令不联网，也不读取
provider secret：

```bash
runtime/.venv/bin/python evals/agent_efficiency/provider_ab.py host-lock \
  --output /tmp/milai-provider-host-execution-lock.json
```

把该文件的 SHA-256、`entries_sha256`、`file_count` 与 policy 放进 approval，并把路径与文件 SHA
放进 manifest。计划和运行会独立重建 launcher 静态 import、sandbox Python、namespace/network helper
及递归 ELF 依赖闭集；少一项、多一项、宿主变化或执行前后 inode/path/SHA 漂移都会 fail closed。
最终复验只允许在 adapter PID namespace 与所有持久 network helper 已停止并完成 bounded wait 后开始；
无法确认 helper 退出时报告必须是 `FAIL_PARTIAL`，`post_execution_revalidated` 不能为 true。

第一步只生成计划，不联网：

```bash
runtime/.venv/bin/python evals/agent_efficiency/provider_ab.py plan \
  --adapter-manifest /tmp/milai-provider-adapter.json \
  --pricing-snapshot /tmp/milai-provider-pricing.json \
  --expected-approval-sha256 REPLACE_WITH_OUT_OF_BAND_APPROVAL_SHA256 \
  --max-input-tokens-per-request 8000 \
  --max-cost-usd 20 \
  --output /tmp/milai-provider-ab-plan.json
```

确认计划 binding 的 `provider_request_count=1000`、精确 provider/model/origin、pricing、tool schema、
egress policy 与 `authorized_by_cost_limit=true`，并把 `plan_sha256` 作为第二个带外锚点。由操作者通过
秘密管理器配置 manifest 所声明的 `MILAI_PROVIDER_CREDENTIAL_*` 别名；不要把密钥放进命令行、argv、
报告或仓库，也不要把 provider 原生环境变量直接暴露给启动链。真实运行的
input/cost 必须与 approval 精确相等；每次 charge-bearing model call 前先进行目标 tokenizer count 和
最大费用 reservation：

```bash
runtime/.venv/bin/python evals/agent_efficiency/provider_ab.py run \
  --adapter-manifest /tmp/milai-provider-adapter.json \
  --pricing-snapshot /tmp/milai-provider-pricing.json \
  --expected-approval-sha256 REPLACE_WITH_OUT_OF_BAND_APPROVAL_SHA256 \
  --expected-plan-sha256 REPLACE_WITH_REVIEWED_PLAN_SHA256 \
  --max-input-tokens-per-request 8000 \
  --max-cost-usd 20 \
  --max-provider-requests 1000 \
  --data-boundary-ack synthetic-deidentified-only \
  --execute-provider \
  --output /tmp/milai-provider-ab-capture.json
```

完整捕获只产生 `PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED`；任何中途失败原子写入
`FAIL_PARTIAL`，并保留已验证 native IDs 与 cost-to-failure。将 provider 账单导出规范化为仓库外的
逐 native request-ID 文件；sidecar 必须同时指向并绑定 normalized 文件和真实上游 export/invoice。
将 capture SHA-256 作为第三个带外锚点后再执行：

```bash
runtime/.venv/bin/python evals/agent_efficiency/provider_ab.py reconcile \
  --report /tmp/milai-provider-ab-capture.json \
  --billing-evidence /tmp/milai-provider-billing-evidence.json \
  --adapter-manifest /tmp/milai-provider-adapter.json \
  --pricing-snapshot /tmp/milai-provider-pricing.json \
  --expected-report-sha256 REPLACE_WITH_OUT_OF_BAND_CAPTURE_SHA256 \
  --expected-approval-sha256 REPLACE_WITH_OUT_OF_BAND_APPROVAL_SHA256 \
  --expected-plan-sha256 REPLACE_WITH_REVIEWED_PLAN_SHA256 \
  --output /tmp/milai-provider-ab-final.json
```

匹配结果仍只产生 `PROVIDER_EVIDENCE_RECONCILED_REVIEW_REQUIRED`，绝不产生 `PASS`。只有独立审查
确认 adapter/runtime/dependency closure、native receipts、pricing、IP egress、上游账单和完整报告均
无漂移，并单独签发接受记录后，才可关闭 OE-F06。fixture/mock adapter 即使完成捕获与 reconciliation
也不能成为真实 provider 证据。

为避免自动化把“待复核”误认成成功，`run`/`reconcile` 在原子写完完整 artifact 后固定返回退出码 `3`；
`FAIL*` 返回 `1`，输入/验证错误返回 `2`，只有无网络 `plan` 返回 `0`。调用脚本必须显式处理 `3` 并把
artifact 送交独立复核，不能用 `|| true` 抹掉语义。
