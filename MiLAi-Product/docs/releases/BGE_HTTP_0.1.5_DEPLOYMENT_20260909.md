# Runtime 0.1.5：BGE HTTP 模型上线回执

日期：2026-09-09。状态：`Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE`。

## 已上线

- 公网 MCP 入口仍为 `https://milai.aigcit.com:7960/mcp`，MCP 服务未重启或改目录。
- API：`milai-product-api-mcp.service`，PID `3330478`，16:08:07 CST 启动。
- worker：`milai-product-worker-mcp.service`，PID `3331050`，16:08:12 CST 启动。
- 安装：`/opt/milai-aigcit/releases/runtime-bge-0.1.5/runtime-venv`；安装源与当前 Runtime
  所有 Python 源文件逐字节一致。依赖版本沿用旧部署，未隐式升级其依赖。
- Runtime wheel SHA-256：`fb1269229c040c4795f9e49eb7a400d1c8ca40b4d8f39d9916b8bd72dc35e914`。

| 资源 | 当前配置 |
|---|---|
| Embedding | `http_embeddings` / `bge-m3` |
| Embedding 地址 | `http://127.0.0.1:7861/v1/embeddings` |
| Rerank | `http_reranker` / `bge-reranker`，部署路径为 `bge-reranker-v2-m3` |
| Rerank 地址 | `http://127.0.0.1:7961/v1/rerank` |
| 向量空间 | 原生 1024d → L2 + 确定性投影 + L2 → 128d |
| 新 projection identity | `32bd0db340cb35295f5e8d5c6f8a23e844e433ad309c19b78ee4dfa4ec259bf8` |

回环端口对应用户提供的 `36.140.33.19:7861/7961`，已经分别实测，不将文本绕行公网。
Embedding revision：`da98b36af6863e2db79c46c51f508349ad8bd6d856aa57626e9a41ecb3412321`；
Rerank revision：`b4efb99276473de1a85a10a331ae7a7bfd32665f518d5bbada19e017575b2b2f`。
revision 根据权重、tokenizer/config 文件与服务镜像摘要生成；不能证明模型进程内存未被
另行热更新，后续改权重必须换 revision 并重建。

## 验证结果

- `uv run ruff check src tests migrations`、`uv run mypy`、`uv build` 均通过。
- 聚焦单测：`91 passed`；完整临时 PostgreSQL：`1225 passed, 1 skipped`，124.05 秒。
  唯一跳过项为缺少 `milai_client` 的 Context Chat 集成测试。
- 真实 BGE + 临时 PostgreSQL 恢复专项：`2 passed`。新旧模型隔离、旧 16d 历史、撤销
  内容阻断、逐轮水位一致、最终清理与 Canonical 历史数量均验证。
- 独立 subagent 完成模型 I/O 与恢复流程审计。慢 headers/body deadline 与并发等待
  发现的问题已修复并补直接测试。
- API `/health/ready` 返回 `vector_embedding=ready`、`bge-m3`、无 warmup 错误；
  `/health/live` 返回 `version=0.1.5`。
- FTS/vector/evidence/purge 水位均为 `2030`；vector 76 条 delivery 全部 DELIVERED。
- 当前受管 tenant：7 个 ClaimVersion、30 个 EvidenceRecord，切换前后数量一致；
  2 个有效 BGE 128d 向量。5 个 blocked Claim 均未通过 Canonical Gate，关联派生
  fragment/vector 均为零。未修改任何 Note、Evidence 或 Claim 原文。
- 后端合成中文查询实际执行 embedding/vector 检索，无降级。用上线配置和已安装
  factory 实调 Rerank，人工智能文本高于无关午餐文本（0.99121094 vs 0.00001603）。
- 直接访问公网 TLS MCP 得到预期未认证 `401`；未重新登录 OAuth 或进行全新客户端验收。
  本机默认代理路径曾报 TLS EOF，禁用代理后公网和回环 TLS 检查均通过。

注意：`access_trace.structural_cost.reranker_calls` 是 reranker stage 计数，不单独证明
HTTP 推理调用次数；上面的真实 Rerank 证明来自独立已安装 factory 调用回执。

## 首次回退与恢复

首次只重建 vector 时，发现既有恢复问题：历史 16d Claim 没有 window fragment，另外
已撤销历史的 fragment 已清理。单独回放 vector 在 `NODATAFOUND` 停止，自动恢复旧配置。
没有通过跳过事件或修改 Canonical 来推进水位。

补充了独占、同事务重置 FTS/vector、每轮各一事件的恢复脚本；每轮验证水位一致、无
错误或未完成的已尝试 delivery，不满足则立即停。旧模型恢复先通过，再执行 BGE 恢复；
二者均 77 轮，最终水位 2030。恢复期间权限 Gate 保持生效，结束检查撤销派生行清零。

此类 FTS 恢复会级联清除旧 128d 向量，回退须重新生成旧模型索引，并非瞬时切换快照。
仅清除和重建可恢复派生索引及 delivery，没有数据库 schema 迁移，没有 Canonical 删除。
回退脚本：`/opt/milai-aigcit/releases/runtime-bge-0.1.5/rollback.sh`。

## 边界与回执

不改变 MCP 八工具合同或 scope；共享 Runtime 的旧 MCP 入口也使用新模型。Note 仍为
字面检索，可选 Evidence dense 通道仍未开启，不新增 LLM 调用。本次不是纯语义 Note
召回或模型质量全面提升的验收；128d 投影可能丢失信息。

操作说明见 [HTTP 模型 runbook](../runbooks/http-model-providers.md)；设计见
[ADR-056](../adr/ADR-056-http-model-providers.md)。

机器回执：

- `MiLAi-Lab/artifacts/bge-http-20260909/recovery-final-full-gate.json`
- `MiLAi-Lab/artifacts/bge-http-20260909/coordinated-recovery-gate.json`
- 部署目录下 `old-model-recovery.json`、`coordinated-recovery.json`、`verify.json`、
  `post-deploy-gate.json`、`final-reranker-probe.json`、`live-query-smoke.json`。

完整测试使用独立临时数据库，结束已清理这些测试数据库；测试内容为合成数据，未删除
公网验收保留的 Note。工作区既有修改保留，无 Git 提交。
