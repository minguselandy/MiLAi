# ADR-011：Architecture Bundle 与 Hash Lock

> 状态：`ACCEPTED FOR 1.0.0-candidate.2`  
> 日期：`2026-08-16`

## Decision

`architecture/v1.0-candidate/` 包含规范册、机器 crosswalk、manifest、validator 和负向测试。
`architecture_manifest.json`：

- 锁定包内除自身外的每个 required artifact；
- 锁定设计源、关键 runtime locks/config、ADRs 和选定外部资产 identity；
- 使用 SHA-256 和显式 project/workspace base；
- 不使用 glob、绝对 target 或可逃逸的 `..`；
- manifest 自身不参与自身 hash，发布时单独记录其 digest。

`validate_bundle.py` 验证完整 ID 集、引用存在和状态 banner；`verify_lock.py` 验证内容 hash。
开发模式可只做内部 lock 检查；AF-09 review/release 模式必须额外接收来自 bundle 外部可信提交
回执的 manifest SHA-256。缺少该 trust anchor、digest 不匹配，或同时篡改内容与 manifest，均失败。
任何 drift 使 AF-09 失败。

Candidate.1 的不可变提交归档与回执保留在 `docs/reviews/submissions/`。每次 remediation candidate
都生成新的外部 receipt；review/release 命令必须显式给出该 receipt 中的 manifest digest，不能
从待审 bundle 自己读取 trust anchor。已同时篡改规范和 manifest 的副本仍因外部 digest 不匹配失败。

## Consequences

自动验证通过只证明包一致，不等于独立架构评审接受。candidate banner 只能在 AF-09 审查签署和
新 manifest 发布流程后改变。
