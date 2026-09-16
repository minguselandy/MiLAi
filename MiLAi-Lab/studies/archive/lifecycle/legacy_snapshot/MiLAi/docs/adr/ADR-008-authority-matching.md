# ADR-008：Authority 使用显式匹配而非总序

> 状态：`ACCEPTED FOR 1.0.0-candidate.1`  
> 日期：`2026-08-16`

## Decision

Authority 不定义为可传递的单一等级。请求与 ClaimVersion 使用显式 matrix：

| Request | Match |
| --- | --- |
| `INFORMATIONAL` | live、readable、Scope/time 匹配 |
| `USER_CONFIRMED` | Claim 明确为 `USER_CONFIRMED`，lineage live |
| `ACTION_SAFE` | Claim 明确为 `ACTION_SAFE`，无 live block/issue |
| `ACTION_SAFE + confirmation` | 上项加五分钟内、subject/action/content/source 绑定的 confirmation Evidence |

confidence、freshness、epistemic 或 `USER_CONFIRMED` 不自动升级为 `ACTION_SAFE`。所有匹配在 ECS/
Canonical Gate 内完成，unknown fail closed。

## Consequences

新增 authority 需要扩展 request/claim matrix、procedure、Gate、负向测试和 crosswalk；不能只调
score threshold。当前 migration 0013 的 live confirmation revalidation 是 action 路径基线。

