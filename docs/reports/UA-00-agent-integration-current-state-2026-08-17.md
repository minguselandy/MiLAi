# MiLAi 可用性与 Agent 接入当前态审计

> 日期：2026-08-17  
> 范围：`MiLAi_可用性与Agent接入设计开发文档_v1.md` 的 UA-00～UA-08  
> 边界：Logical Architecture 1.0.0 保持 `FROZEN`；Schema 0.1.x 保持
> `EXPERIMENTAL / NO-GO`；Runtime 保持 `CANDIDATE`。

## 结论

现有 Runtime 已提供可验证的 Canonical Gate、Evidence、Proposal/Steward、OpenIssue、撤销、
因果读取、检索追踪和备份恢复内核，但尚不能称为开箱即用的 Agent memory 产品。实施必须在
现有公开 REST 之上增加独立 Integration Plane，不允许适配器连接数据库或拥有评审权限。

## 要求—当前态—关闭证据矩阵

| 工作流 | 实施前状态 | 必须关闭的缺口 | 验收证据 |
|---|---|---|---|
| UA-00 边界 | 部分具备 | 缺接入 ADR、capability ADR、威胁模型、兼容策略 | ADR-020/021/022、contract 与安全测试 |
| UA-01 可用性 | 未具备 | `milai-ops` 无 init/doctor/status/smoke/agent-config | CLI 单测、0600/不覆盖/无 secret 输出、稳定 JSON |
| UA-02 SDK | 未具备 | 无 capabilities、无独立 typed client、无 prompt-safe envelope | OpenAPI、tool contract、Python client contract tests |
| UA-03 生命周期 | 未具备 | 无默认 capture policy、无幂等 hook/facade | lifecycle tests，assistant output 永不成为 Evidence |
| UA-04 MCP | 未具备 | 无 stdio server、无 profile tool allowlist | 官方 SDK、profile/危险工具缺席测试 |
| UA-05 框架 | 未具备 | 无 generic/LangGraph/AutoGen/coding hooks | 独立 adapter 包和无框架依赖的契约测试 |
| UA-06 质量 | 仅 fallback | 16 维 hash 是唯一向量路径、无 provider identity/eval gate | provider protocol、显式 real provider、离线 benchmark |
| UA-07 私有数据 | 阻断 | Blob 明文、无 key/data-mode gate | AEAD envelope、错误 key/tamper/fail-closed tests |
| UA-08 发布 | 未具备 | 无 integration package/inventory/E2E/独立接入评审 | clean-room、全门禁、current-byte inventory、review |

## 已有可复用公开接口

- `POST /v1/memory/query`、`GET /v1/retrieval-traces/{id}`；
- `POST /v1/evidence`、`POST /v1/proposals`；
- `GET /v1/claims/{id}`、`GET /v1/open-issues`；
- `POST /v1/causal-tokens`；
- `POST /v1/evidence/{id}/revoke`、deletion status；
- health、watermark 和 degraded route diagnostics。

## 不可突破的边界

1. Agent 可以读取、捕获 Evidence、创建 Proposal；不能自评审或直接写 Claim。
2. 模型输出默认不是 Evidence；检索空结果是正常 abstention，不得伪造记忆。
3. MCP/框架适配器只依赖 versioned client contract，不导入 Runtime persistence/application。
4. 远程监听、多 Agent 隔离、真实个人数据在各自安全门关闭前继续禁用。
5. 新实施不能改变冻结逻辑架构的 Evidence/Proposal/Decision/Claim/OpenIssue 语义。
