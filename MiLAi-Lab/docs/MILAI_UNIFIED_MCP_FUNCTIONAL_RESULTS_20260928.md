# Unified V8/V9：实际 MCP 接线与容量修复结果

本轮验证通过真实 Host Agent → MCP HTTP → strict Store → 回执 → Host 续接，
以及新会话中的持久记忆交付。范围仅为两个已曝光 v7 合成脚本、三条消息；
不构成原生 benchmark 成绩、协议效果消融或 unseen 收益。完整 V8/V9 Goal 继续执行，Product 仍为 NO_GO。

## 结果与失败保留

| 运行 | 源码 | 结果 | 实际费用 |
| --- | --- | --- | --- |
| R1 | `196fa0136effc442b33a346df4bd17631807542d` | CREATE 成功；续接 HTTP 前容量模板失败；后续两条消息未运行 | 1 generation，1,455 tokens；1 embedding，31 tokens |
| R2 | `3f1715aaf8de961fc9aadc8e9abe8e8338157831` | 2/2 脚本、3/3 消息、9/9 任务义务；另有3项非失败诊断 | 4 generation，6,158 tokens；1 embedding，31 tokens |

[R1 失败记录](../data/manifests/unified-v8-v9-mcp-r1-failure-20260928.json)和实际持久化均保留。
R2 使用相同输入、配置、模型参数和离线评分，在全新 namespace、checkpoint、world 中完整重跑；
没有续用 R1 的写入，也没有拼接轨迹。read_only 在 R1 因工程失败未运行，仍列为未运行。

首断点是本地 HF chat template 把合法 OpenAI `function.arguments` JSON 字符串当成字典。
两个竞争解释分别是缺少本地计数适配、上游重复编码。真实 checkpoint 零模型重放确认前者，排除后者：
一次解码等于 checkpoint 参数，首请求的已记录请求对象及1391-token计数一致。
部署中的 vLLM0.27.1 也在模板前执行同类转换。

修复仅在计数深拷贝中按服务规则处理参数；原始 wire 对象、checkpoint、工具 JSON、MCP/Store、prompt 和 schema 不变。
[窄测回执](../data/manifests/unified-v8-v9-capacity-repair-checks-20260928.json)记录6个独立目标通过、0 skip，
以及静态检查和初始失败。Root 验证源码及制品哈希；发布没有触发重复测试或构建。

## 实际验收

[R2 结果与证据索引](../data/manifests/unified-v8-v9-mcp-r2-results-20260928.json)包含每条义务、调用、成本和链路关联。

- save_plan-1：Host 自主提出 CREATE，实际 MCP 回执返回真实 ID；同一 Store 可读到完整计划，Host 续接确认保存，没有业务动作。
- save_plan-2：新 session 的实际请求只有 system/user 两条消息，包含经 MCP 取得的真实记录，没有上一 session 的 assistant/tool 历史；回答正确包含物品、总量、目的地和包装，没有改写记忆或业务动作。
- read_only-1：最终文本为 `45`，没有 Host 工具调用、持久记录、预约或标签尝试。

原生提案、MCP 回执、后续请求中的 tool_call_id 和 record ID 已实际对齐。
四次实际生成的本地／服务 prompt tokens 分别为1395／1395、1795／1795、1441／1441、1374／1374。
这证明本轮续接容量计数适配有效；随机运行引用及时间戳使 R2 字节不同于 R1，不要求跨运行 token 数相同。

后续材料读取由程序通过 MCP 发起，不能称为 Host 自主选择检索。此诊断也没有验证进程重启、跨模型效果、
任意记忆事实的真实性或 native 相对 JSON-action 的优势。

## 成本与复现

本 Goal 截至本轮，含失败累计新增 **5 generation / 7,613 generation tokens / 2 embedding / 62 embedding tokens**。
连续账本为 **3306 generation / 4,212,816 generation tokens / 23,632 embedding tokens**，unknown usage 均为0；
SHA 为 `92a7fd0e8994fbfafbb147ed03be4f0d0f96c4ab48f5a822b64b6f9b98dbedc0`。
没有清零历史。MCP 字节、wall/CPU 见结果索引，其时间与 Store/embedding/取材重叠，不重复相加。
初始化 GPU 时间、物理 I/O 和货币成本未独立计量，开发代理消耗不属于该实验账本。

输入／离线义务位于 `data/diagnostics/unified-v8-v9-mcp-smoke/`；[R2 协议](../data/diagnostics/unified-v8-v9-mcp-smoke/protocol-r2.json)
在真实调用前发布。Root 在源码 `3f1715a` 下使用现有 `tools/run_persistent_memory.py prepare`，
再按 save_plan、read_only 顺序各执行 `run-phase --phase 0`；精确 argv、prepared 身份与 runtime 路径保存在忽略的
`artifacts/unified-v8-v9/mcp-smoke-r2/execution-freeze.json`，SHA 为
`a365bd30481d005593c700aed7bf340532beed4ea94d0a5fa7745b2ec6ed9445`。
服务为固定 Qwen3.6-35B-A3B-FP8@7862、bge-m3@7861，temperature0、max_tokens4096、thinking=false、每消息最多12次生成、HTTP并发1。
凭据、数据库、原始轨迹和环境不提交 Git。复现新运行必须使用新 run_id 和空 namespace，保留历史结果与费用。

决策：Continue 原生 U1 adapters。MCP 接线成功只是前置条件；接下来仍需 MemSyco 三类原题和 MERIT 三域完整 arcs，
再进入 U2 的独立强简单／外部系统比较，以及证据触发的后续分支和 U6 总结。
