---
document_id: MILA-V02-05-LOCAL-SIM-01
version: "1.0"
status: LOCAL_SIMULATION_COMPLETE
arm_kind: SIMULATION
paid_model_requests: 0
local_model_sessions: 3
local_model_requests: 7
formal_holdout_consumed: false
schema: NO-GO_FOR_SCHEMA_FREEZE
---

# MiLAi v0.2 本地 vLLM 开发实验模拟

## 结论

本地模型可以用于低成本查验请求、工具、保存和冷恢复流程。本次已完成一条 G/A/B 小链：
3 个会话、7 次推理请求，共 **21,880 raw token**，无付费请求、未知用量或自动重跑。
隔离的真实 PostgreSQL / 公开 MCP 保存及恢复成功；A/B 都给出了正确的回滚决策字段。

但本例 **B STATE_FIRST 比 A FLAT_PREFETCH 多用 67.23% token**，不能据此推广 State-first
省钱。完整操作顺序也没有全部表达正确：A 漏通知和恢复后核验；B 漏恢复后核验。
`LOCAL_SIMULATION_COMPLETE` 是流程终态，不是完整任务质量、产品净收益或 D3–D5 的 PASS。

继续保留 A0；不启用自动维护，不扩大 Hint/图/Reviewer，不解锁任何付费阶段。

## 1. 范围与运行条件

- 依据 [MILA-V02-05 v0.3 Goal](../../../MiLAi-Product/docs/goals/MILA_V02_05_端到端通用记忆开发与泛化验证_GOAL_20260906.md)
  与 [实施设计](../../../MiLAi-Product/docs/goals/MILA_V02_05_开发流程审阅与实施设计_20260906.md)
  的当前 **G/A/B 装配比较**，没有恢复旧 N5 或改成 F/S。
- 用户本轮授权本地模拟；原付费额度仍为 0。
- 模型：`Qwen3.6-35B-A3B-FP8`；本机 `http://127.0.0.1:7860`；观察到 vLLM `0.27.1`，
  `/v1/models` 返回上下文上限 65,536。没有下载、更换或重启模型，也未核验权重内容哈希。
- 新增轻量 `LOCAL_JSON_ACTION_HOST`：模型自己选择文件操作、公开 MCP 调用或结束。
  JSON 动作协议不是原付费 Host / 原生工具调用的等价实现。公共目录实际列出 13 个 MCP
  工具，完整参数可按需获取；治理写操作仍无授权。没有 shell、外部检索、隐藏 Reader/Judge。
- 使用一个**合成、已开放的发布交接文档任务**，不是 LME 效果实验。先验证最低成本链路，
  本轮不消耗 Formal 500，不把历史 LME 结果改标成本地结果。
- Product 只经公开入口使用；核验 pin 为
  `c5561412b0440f84e628d69a7c271c96d66bae7f89d4e3f1db46ede97a1608bf`。
  Product 代码、Schema、公开服务配置均未改。

## 2. 实际链路与可归因边界

1. G 阅读四份来源，产出 `release-plan.md` 与 `handoff.md`。任务明确要求这两份正常文档；
   不是“自主发现该保存什么”的自然效果实验。G 结束后公开 State 为 `ABSENT v0`。
2. 零模型适配器保存原样交接内容、详细文件的路径/哈希和来源版本入口；公开 CAS 提交后，
   回执与 GET 均确认 `ACTIVE v1`。保存计时 1.425 秒包含观察客户端/服务启动，不能与历史
   纯提交延迟直接比较。没有二次总结调用，也不将文件路径当成 Evidence 授权。
3. G 进程结束；A/B 从同一 G 普通文件快照独立建立工作区，通过公开接口建立等价 State，
   再各启新 Host 和 MCP 客户端冷读。三份 Host PID 不同，A/B 任务绑定不同，载荷及文件
   哈希一致。A 输入包含 L1 + L2；B 初始仅含 L1 和来源/文件入口。
4. A 直接回答；B 自主读取 `release-plan.md`，其完整页确实进入下一次已记录的请求，然后回答。
   没有用隐藏提示强迫 B 回查。该例 L1 实际已经包含关键回滚条件，这是运行后观察，
   **没有事前按“L1 足够/不足”分组，不可补称预注册子组验证**。

边界：两臂使用同一新项目中的不同 TASK 绑定。本次没有 Agent 发起 MCP mutation、来源
导入或索引写入；只有机械 State 建立和本地文件读取。完整跨项目隔离、H′ 泄漏 canary、
撤权派生披露、并发覆盖、L2 权限/失效传播、异常断电等尚未跑通；不能宣布完整 D3。

## 3. 预算和结果

运行前封存 [配置](../../configs/v02-local-vllm-simulation.json) 和
[fixture](../../data/fixtures/v02-local-vllm-simulation/release.json)：最多 G/A/B 三个会话、
每会话 10 个推理请求 / 20,000 raw token、批次 60,000 token、单请求输出最多 1,200 token。
会话检查超时配置为 180 秒，HTTP 超时为 30 秒；未声称实现产品级 30 秒端到端 SLO。

| 会话 | 请求数 | 输入 token | 输出 token | raw token | Host 时间 | 结果口径 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| G 生成任务文档 | 4 | 11,645 | 1,451 | 13,096 | 13.350 秒 | 两份文件产生；未完整评审全部语义 |
| A 预载详细笔记 | 1 | 3,121 | 166 | 3,287 | 2.890 秒 | 三个决策字段通过 |
| B State-first | 2 | 5,269 | 228 | 5,497 | 3.587 秒 | 三个决策字段通过 |
| 已计量试验合计 | 7 | 20,035 | 1,845 | **21,880** | — | 3/3 分配收尾；未知请求 0 |

计时从创建隔离实例到进入清理为 36.729 秒，不含开发、离线测试及清理本身。
本地服务推理不产生本轮付费 API 请求，但 **GPU、电力及占用成本并非零**，本轮未计价。
服务没有返回可用的 cached-token 明细，不能当作 0 或推算付费账单。
本次开发对话、实现及人工式复核使用的开发助手消耗未计量，不包含在 21,880 token 内；
“试验付费 API 请求为 0”不代表本轮开发或本次对话免费。

- 只比较未来消费：B 比 A 多 2,210 token（+67.23%）。多一轮推理要重发已有上下文，
  本例省下的首轮预载不足以覆盖第二轮成本。
- 包含共同 G：G+A = 16,383，G+B = 18,593 token。保存阶段没有新增推理调用。
- 已计量试验总账只计 G 一次，为 21,880；不能将 G+A 与 G+B 相加再作为实际消耗。
- 自动评分仅检查 `decision=rollback`、`target=1.7.4`、`destructive_change=false`。
  人工复核补充：A 没有表达通知负责人及恢复后核验；B 表达通知，但也漏核验。
  不把字段 PASS 改写成完整行动链正确，更不声称“首次实际操作成功”——本轮没有执行部署。

## 4. 本地控制器证明了什么

[本地 Provider](../../tools/v02_local_provider.py) 仅接受固定 loopback URL 和模型标识，
不继承代理、不读取 API key、不跟随重定向，不存在自动重试或模型切换。
每次生成前用同一聊天模板和消息调用 `/tokenize`，把输入计数和输出上限先写入持久 ledger
并 fsync，再发送。文件锁跨越预约、发送与结算，同一批次只允许一个在途请求。

全部 7 次请求的预分词数量与服务返回 prompt token 相等，completion 均不超过预约；
全量输入计入预算，不扣除缓存。缺失用量、超时、输入计数不符、重定向均会保留未结算预约，
阻止后续启动。重启读取 ledger 不会释放未知请求。

这些是 **此轻量本地路径** 的证据，不是原付费 Host 的逐请求控制证明；实际收费、缓存计费、
原生 Host 隐式压缩等仍未验证。结构化输出用法参考
[vLLM 官方文档](https://docs.vllm.ai/en/stable/examples/features/structured_outputs/)，
运行时字段以本机公开 API schema 和实际回执为准。

## 5. 失败、修复与工程检查

首个实例 `local-sim-20260906a` 在 Docker 创建网络时失败：默认地址池耗尽。
当时分配和模型请求均为 0；失败结果保留，没有删网络或数据库。
随后增加仅用于本地模拟的 [Compose override](../../tools/containers/v02-local-bridge.compose.yaml)，
复用现有 bridge，数据库仍绑定本机随机端口。通用 Lab 准备入口只增加一个可选参数，
其他实验默认行为不变。第二次基础设施启动使用 `local-sim-20260906b`，没有重跑任何已消费的 G。

运行后核对真实目录，修正轻量 Host 白名单中三个只读 MCP 工具名称，并加参数化测试。
本轮模型没有调用这些工具，因此不是效果修复；未追加模型运行。实际执行源码哈希仍保留在
`preflight.json`，不冒称它与运行后的只读名称修复完全相同。

检查命令：

```bash
uv run milai-lab-check-boundary
uv run pytest -q
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

最终结果：**203 项测试通过**（新增本地模拟测试 23 项）；边界检查、全量 Ruff、
30 个源文件的 mypy 检查、sdist/wheel 构建均通过。Product pin 前后均有效。
Product 未改，不重复声称完成 Runtime 全量验收。
当前副作用仅为 Lab 实现、合成资料、隔离实例数据/日志及已停止的试验容器。
独立 API、worker、六个临时 MCP 进程均已不存在；PostgreSQL 容器 `Exited (0)`，数据卷保留。
共享 vLLM 与原公网 MCP 进程未改变。

## 6. 证据与后续门禁

复用入口（另一次运行会占用本地 GPU 并生成新的独立记录，不是自动续跑）：

```bash
uv run python tools/run_v02_local_vllm.py --run-id local-sim-UNIQUE_ID
```

将 `UNIQUE_ID` 换为小写字母、数字或连字符；已有运行目录拒绝覆盖。入口不接受云端 Provider，
也不会读取原付费实验的 API key 或释放旧额度。当前 fixture、3 会话和 60,000 token 上限见配置。

[结构化摘要](MILA_V02_LOCAL_VLLM_SIMULATION_RESULTS.json)；原始请求、响应、来源、载荷、提交回执、
分配记录留在忽略目录：

```text
artifacts/v02-local-vllm-simulation/local-sim-20260906a/  # 零模型基础设施失败
artifacts/v02-local-vllm-simulation/local-sim-20260906b/  # 完整本地 G/A/B
```

第二个目录内 SHA-256：

```text
result.json          e68e6f0028265f577f42479957d7ee8fb9e33dbf122d78a1660c8211de1b39a9
provider-ledger.jsonl 842f417153cded344b579db3e72c8daf45e467a03e1ea062ddaeb5cb72164afb
preflight.json       67a3f68439ce67cb52d0c97df3ab47f07e0051b5cc2f2d1918e42948580af3be
```

后续应先用本地模拟查工程与成本失败，再考虑付费最小确认。本轮不追加案例；下一小步可选
一个已开放 LME 历史，保留完整合法来源、同源快照和分页，先做非模型输入预算审计。
只有在现有本地上限内有机会完成，才另开独立本地批次；不为跑通长历史直接扩大上下文或预算。
进入付费实验仍需原 D1–D3、真实 Provider 成本控制和新的明确预算通过。

Schema 继续 **NO-GO FOR SCHEMA FREEZE**。
