# ADR-056: 可版本化 HTTP 模型适配

日期：2026-09-09。状态：Implementation CANDIDATE，NO-GO FOR SCHEMA FREEZE。

## 决策

新增 `http_embeddings` / `http_reranker`，以调用方显式配置的模型服务代替本地 ONNX。
保留原 ONNX 与 deterministic provider；不改变检索路由、工具权限和 Canonical Gate。

HTTP 模型属于不可信外部 I/O 边界：响应必须匹配声明的模型、索引和完整数量；Embedding
验证维度和有限非零向量，Reranker 仅用分数排序原有候选，忽略远端回显文本。不得通过
模型结果创造 Claim/Evidence、放宽权限或发起写入。禁止跳转、隐式代理、自动重试。

沿用既有 16/128d 投影接口与表结构。本次 BGE 采用 1024→128d 投影，不能视作原生
1024d 质量。provider/model/source dims/projection dims/normalization/revision 均进入
ProjectionIdentity；API 与 worker 必须一致，新查询不得读取旧 identity 的向量。

revision 为部署声明，应以权重、tokenizer/config 和服务镜像摘要生成。HTTP 响应仅验证
模型名，不能证明内存中权重与磁盘摘要相同；服务原地更新必须同步换 revision、重建。

现有受控 rebuild 只重放派生索引，不改 Canonical。历史包含旧 16d 与已 purge 的记录时，
FTS/vector 必须联合重置、逐轮锁步恢复，失败即停。FTS fragment 重建会级联删除旧 128d
向量，因此此类回退须用旧模型重新生成，不承诺即时切换旧快照。失败可降低召回，
不能提高权威。Note 字面检索与默认关闭的 Evidence dense
开关均保持不变，不启用 LLM。

## 验证与影响

外部响应校验、慢速 headers/body、并发排队与恢复均有直接测试。真实 PostgreSQL 测试
覆盖旧 identity 不被新查询读取、重建、Canonical 历史数量不变、旧 128d 索引保留、
租户/项目隔离及撤销后清理。无需 schema migration，无 OAuth scope 变化。

运行配置、网络时限边界与回退流程见 [HTTP 模型 runbook](../runbooks/http-model-providers.md)。
