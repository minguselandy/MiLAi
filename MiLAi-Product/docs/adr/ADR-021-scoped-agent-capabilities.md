# ADR-021：Scoped Agent Capabilities

> 状态：`ACCEPTED FOR LOCAL CANDIDATE`  
> 日期：2026-08-17

## Decision

服务端识别以下 capability：`memory:read`、`evidence:capture`、`proposal:create`、
`evidence:revoke`、`proposal:review`、`operations:admin`。本地 token 绑定单一配置中的 tenant 与
actor，以常量时间比较验证，只在进程内散列/比较，不写日志或响应；删除环境变量即撤销，替换
即轮换。

reader 只有 `memory:read`；submitter 增加 Evidence/Proposal；operator 单独增加 revoke；reviewer
只具备 `memory:read` + `proposal:review`，使用与 submitter 不同的稳定 actor，并且仅作为本地
人工/受信 Steward 的专用 MCP profile，不进入普通模型 catalog。兼容 `MILAI_API_TOKEN` 暂保留
本地全能力，标记为 transitional，Agent 配置不得使用它；它也不作为 actor-separation 产品
验收凭据。

## Deferred

数据库持久化 token registry、OAuth、TLS、远程撤销 API、每 Agent RLS 需要新的远程/多 Agent
安全评审，不属于本地单用户 candidate。
