# HTTP Embedding 与 Rerank

状态：`0.1.x EXPERIMENTAL / CANDIDATE / NO-GO FOR SCHEMA FREEZE`。

Runtime 0.1.5 支持显式配置的 `http_embeddings` 与 `http_reranker`。MCP 工具、OAuth
scope、Canonical、权限和撤销合同不变。不调用额外 LLM，不自动收集聊天，不改变 Note
的字面检索。模型只参与现有治理检索路径，是否调用仍由检索路由决定。

## 配置

API 与 worker 必须使用完全一致的 embedding 配置。以下两个回环端口是服务器上用户
提供的 `36.140.33.19:7861/7961` 模型服务，不经公网传输待向量化文本。

```dotenv
MILAI_EMBEDDING_PROVIDER=http_embeddings
MILAI_EMBEDDING_ENDPOINT=http://127.0.0.1:7861/v1/embeddings
MILAI_EMBEDDING_MODEL_ID=bge-m3
MILAI_EMBEDDING_MODEL_REVISION=REPLACE_WITH_DEPLOYMENT_CONTENT_DIGEST
MILAI_EMBEDDING_SOURCE_DIMENSIONS=1024
MILAI_EMBEDDING_PROJECTION_DIMENSIONS=128
MILAI_EMBEDDING_HTTP_TIMEOUT_SECONDS=10
MILAI_EMBEDDING_MAX_CONCURRENCY=4
MILAI_EMBEDDING_BATCH_SIZE=32
MILAI_RETRIEVAL_RERANKER_PROVIDER=http_reranker
MILAI_RETRIEVAL_RERANKER_ENDPOINT=http://127.0.0.1:7961/v1/rerank
MILAI_RETRIEVAL_RERANKER_MODEL_ID=bge-reranker
MILAI_RETRIEVAL_RERANKER_REVISION=REPLACE_WITH_DEPLOYMENT_CONTENT_DIGEST
MILAI_RETRIEVAL_RERANKER_HTTP_TIMEOUT_SECONDS=10
MILAI_RETRIEVAL_RERANKER_MAX_CONCURRENCY=4
```

不要照抄占位 revision。记录权重、tokenizer/config 与服务镜像的摘要作为部署身份。
服务端原地更新同名权重不能通过响应中的 `model` 自动发现；必须更新 revision 并重建。
不把本地旧 ONNX 文件配置当作 HTTP 模型实际权重或来源证明。

当前存储保持 128d：BGE 原生 1024d 经 source L2、现有确定性 dense projection、L2 后
写入索引。**不是原生 1024d 检索，也不是 BGE sparse/multi-vector 检索**；投影可能损失
召回质量，需要真实数据质量评测，不能从少量接口烟测推断提升。

## 输入输出与故障

- Embedding 请求 `model/input[]/encoding_format=float`；按返回 index 恢复输入顺序。
- Rerank 请求 `model/query/documents[]`；按 index 重排已有候选，不接纳远端回显文档。
- 检查模型名、完整数量、唯一合法 index、固定维度、有限数值与非零向量范数。
- 无代理环境继承、HTTP 跳转或自动重试；端点不得携带 URL 凭据、query 或 fragment。
- 请求体上限 4 MiB，响应上限 16 MiB；超时、中断与错误仅向上返回安全错误描述。
- 连接后的总 deadline 通过中断专用 socket 实现，包含慢响应头和持续少量回包。
  连接/DNS 仍受底层网络栈约束；本次使用固定回环 IP，不依赖 DNS。
- Rerank 排队与 I/O 共享 timeout；HTTP embedding 的队列等待和每批 I/O 分别有上限，
  整个多批调用不是单个 timeout。没有静默切回旧模型；沿用检索服务原有降级逻辑。

## 切换、重建与回退

1. 先用合成文本验证模型与 Runtime wheel；保留旧安装、配置和各 projection 水位。
2. 确认实际 tenant、Claim 数量、向量模型身份、worker 与 API 的配置相同。
3. 停止 worker。先检查历史 FTS fragment 是否完整；含旧 16d 记录或已 purge 历史时，
   不能只重建 vector。使用 Steward 现有 procedure 在同一事务重置 FTS/vector。
4. 使用新 wheel 和同一 embedding 配置启动 API，以独占恢复 worker 设置
   `worker_event_limit=1`、`worker_projection_batch_size=1` 回放。每轮必须检查
   FTS/vector 水位一致、无已尝试但未完成的 delivery；任一不一致立即停止，不继续
   下一轮，也不能恢复普通大批量 worker。完整追平后才启动正常 worker。
5. 复查新模型 identity 的向量数量、Canonical 数量不变、API readiness、MCP 入口。

现有 vector 重建 procedure 清除旧 16d `search_embedding`，不直接清除带模型身份的
128d `search_embedding_window_128`；但 FTS 回放重建 fragment 时会级联删除相应 128d
行。**本次历史数据需要联合恢复，回退必须重新生成旧模型索引，不是旧向量快照切换。**
新模型查询始终只读取新 identity。
权限和撤销仍须经过 Canonical Gate，保留旧索引不意味着旧内容可见。若启用了可选
Evidence dense 通道，还需单独执行其有界 backfill；默认未开启，不在本次开通。

回退时停止 worker，恢复旧 wheel 和配置，通过同一事务重置 FTS/vector，再用旧模型
执行同样的逐轮锁步恢复。不能只切 API 模型却留下另一种模型的 worker。此次不需要数据库
schema 迁移；索引属于可重建派生数据，Note / Evidence / Claim 原文不删除。

回放可能短暂重建已撤销 Claim 的派生片段；整个过程中 Canonical Gate 必须继续阻断其
读取。恢复完成前不能宣告这些派生片段物理清理完成或生成该阶段备份；结束时检查
已撤销版本的 fragment/vector 都为零。不因历史事件缺片段而手工跳过或伪造 delivery。

## 验证

```bash
cd runtime
uv run ruff check src tests migrations
uv run mypy
uv run pytest -q tests/unit/test_http_models.py tests/unit/test_embedding.py
uv build
```

在独立临时 PostgreSQL、全部五个正确角色 DSN 配置下运行全量 pytest。专项
`test_http_embedding_rebuild_isolates_identity_and_preserves_canonical` 默认 mock HTTP
结果以保持离线 CI；显式设 `BGE_HTTP_LIVE_TEST=1` 才调用回环 BGE。它创建和撤销的都是
临时数据库合成记录，不允许对公网用户数据运行测试 fixture。
