# ADR-013：Model、Embedding 与设备 Baseline

> 状态：`ACCEPTED FOR 1.0.0-candidate.1`  
> 日期：`2026-08-16`  
> 性能阈值：`NOT FROZEN`

## Decision

- 模型只用于 query interpretation、DeriveAndDiagnose、answer composition 或离线研究；不在
  canonical transaction 内且不持有 Steward credential；
- 模型输出必须通过 typed schema、deterministic validator、policy/review；
- embedding identity 包含 provider、model、dimension、normalization、code/prompt version；
- model/dimension 改变创建新 projection version，不原地混合向量；
- 当前 deterministic embedding 是测试替身，不是质量 baseline；
- benchmark manifest 固定 snapshot、model、prompt/scorer、seed、budget、device、cost 和 result hash；
- CPU/RAM/latency/throughput 数值只在目标设备和真实 workload（经数据 gate）上冻结。

## Consequences

当前架构不绑定 GPU、云模型或特定外部 framework。没有设备 baseline 不阻塞语义候选，但阻塞性能
SLO 和自动提交策略。模型不可用时 Evidence ingest、canonical read/revoke 仍可工作。

