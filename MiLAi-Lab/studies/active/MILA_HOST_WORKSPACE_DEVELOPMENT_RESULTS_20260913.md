---
document_id: MILA-HOST-WORKSPACE-DEVELOPMENT-RESULTS
version: "1.0"
date: "2026-09-13"
status: A_THREE_ARM_DEVELOPMENT_COMPLETE_B_BOUNDED_UNAVAILABLE
experiment_kind: RESEARCH_PROTOTYPE
stage: OPEN_DEVELOPMENT
memory_scope: IN_PROCESS_ONLY
model_requests: 10
known_raw_tokens: 44209
unknown_usage_requests: 0
independent_sources_compared: 1
---

# Host 工作区：真实任务 A 三臂开发结果

已把 opt-in 原型接入真实 Provider 和历史诊断任务，完成 NOTE／REVIEW／REGULATED 三臂，各自交付最终回答。当前决定：**保留普通 NOTE 作为本轮简单参照，暂停追加复杂政策试验；不把候选升为默认策略。** 三臂均未写工作记录，REGULATED 多一次无新增信息的读取，未显示相对 NOTE 的净增量。本次能评价任务中的政策行为，不能分离工作记录形成/消费效应，更不支持持久记忆或新算法结论。

这是原 Goal 允许的“一项真实任务完整三臂 + 第二来源有界处置”交付。第二来源 B 没有实际运行，覆盖不足，**不是两任务验证完成**。未要求模型成功每题；回答中的真实错误保留在结果中。

## 当前实现与复现入口

- [任务入口与提取器](../../tools/run_workspace_task_a.py)：同一入口打包 A、分三段释放历史记录、有限读源/四则计算/建议/阶段答复/最终交付、调用现有 Host 与 Provider。模型没有文件系统、shell、Product 或服务控制入口。
- [Host](../../tools/workspace_policy_host.py)与[核心](../../src/milai_lab/methods/workspace_policy.py)：仍显式 opt-in；默认关闭，三政策和两种材料模式共用机械边界。本轮实际只运行 COMMON_CONTEXT。
- [本轮 Provider 适配器](../../tools/workspace_task_provider.py)：继承[既有 HTTP 客户端](../../tools/v0213_provider.py)的身份检查、timeout 和关闭逻辑，沿用原账务流程，增加可选 output_cap 和本地/服务 tokenizer 一致性检查。本轮使用 2048；旧 Provider 已恢复原始字节，旧调用固定 4096。
- [任务 manifest](../../data/manifests/workspace-task-a-v2.json)、[结构化结果](MILA_HOST_WORKSPACE_RESULTS_20260913.json)、[委托执行授权](MILA_HOST_WORKSPACE_A_EXECUTION_AUTH_20260913.md)、[逐臂语义标注](MILA_HOST_WORKSPACE_A_LABELS_20260913.md)。授权与标注由用户委托的 subagent 执行，不是独立 human gold，也未另加实验模型 Judge。

```bash
uv run python tools/run_workspace_task_a.py pack --root /absolute/path/outside-lab/new-task-pack
uv run python tools/run_workspace_task_a.py run --package /absolute/path/outside-lab/new-task-pack --root /absolute/path/outside-lab/new-run
```

以上是复现命令，运行会消耗新的请求，已有结果无需重跑。原始任务和模型轨迹保持 Git 外：

- [task-a-v2](/cra/memory/mx_memory/evidence/workspace-host/task-a-v2/manifest.json)：18 个必要来源文件 hash、六条请求、逐请求原数组索引/行号与指纹映射；模型只获得字段白名单副本及中性句柄。
- [run-header](/cra/memory/mx_memory/evidence/workspace-host/a-common-v2-20260913/run-header.json)：实际代码/政策快照、模型和 tokenizer、预算、运行顺序。
- [实际终态及账](/cra/memory/mx_memory/evidence/workspace-host/a-common-v2-20260913/result.json)：三臂 rows、发送前事件、最终 HTTP body、完整响应与 usage、动作返回分开存档。

## 开发中实际修了什么

1. **真实模板拒绝原型的政策消息位置。** 原先在用户消息之后再添加 system 政策；当前模型只接受首条 system。现在将可信政策接在原 system 正文后，原用户任务仍为 user，材料仍为数据。三臂使用相同位置，默认禁用路径不受影响。新增/调整测试覆盖单一首条 system、原用户任务和材料权限。
2. **初版材料在第三段超过 8192 tokens。** 仅 CPU 的 task-a-v1 每批选两条最长请求及邻近正常请求，未发送模型。v2 改成每批最长一条和时间顺序最近、低于或等于该批中位时长的正常请求，平局取较早索引；三臂同规则，不按模型输赢选样。三段最短回放输入 2198／4147／6164 真实 tokens；完整运行每次再核对服务计数与实际 usage。
3. **隔离旧实验固定源码依赖。** 首次全量测试发现修改共享 Provider 会触发旧冻结实验的 IMPLEMENTATION_DRIFT。核对失败依赖表，仅该文件不匹配；已恢复原文件（SHA-256 `05601e67f19754cc0bc7ac80bb281e3d6b435e93ec1ce85fe5ece90b42c6d92c`），把扩展移至本轮适配器。真实运行使用的修改版保留在 Git 外代码快照；当前适配器 generate 方法与运行版本 AST 相同，10 个真实请求/响应做了 CPU 回放，最终 HTTP 字节与输出全部一致，未再次调用模型。见[等价回放证据](/cra/memory/mx_memory/evidence/workspace-host/provider-isolation-cpu-replay/result.json)。这是运行后接线整理，不把旧轨迹重标为新代码的再次真实运行。
4. **真实调用/日志接线。** 每个正常决策一次生成；可选 work_update 与动作同回复。发送前保存 Host 请求及最终 body，响应后保留完整响应/用量，再独立持久化动作结果；截断输出不派发，未知用量停整个新批。旧历史账未改写、未置零。

不存在“先规划工作记录”或“再修 JSON”的第二次生成。无工作记录是有效观察，未替模型补写理想记录。CPU 可控记录进入下一步的测试成立；本次真实轨迹没有自产记录，故没有观察到实际模型记录被下一步消费。

## 实际比较与成本

固定 NOTE → REVIEW → REGULATED；三个空工作区，共同任务、输入角色、权限、输出预算与阶段机会。顺序未按结果改变，单请求在途；模型 `Qwen3.6-35B-A3B-FP8`，temperature=0、top_p=1、seed=213、thinking=false。输入 8192，输出 2048，工作记录 512，focus 4，近期 K=2，目录上限 32，动作预留 1024，外壳 128。预留是整体预算配置，不是逐字段硬保证。

每段最多 4 次、每臂最多 12 次、900 秒墙钟、工具累计 CPU 10 秒；外生次序为事务 → 客户端 GC → MCP 边界。各臂提前阶段答复后仍收到后续材料；第三段均交付 final。所有实际用量已核账，finish_reason 均为 stop，发送体与日志逐次一致。

| 臂 | 真实调用 | 输入 tokens | 输出 tokens | raw tokens | 墙钟秒 | 工作记录更新 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NOTE | 3 | 12,619 | 913 | 13,532 | 8.12 | 0 |
| REVIEW | 3 | 12,656 | 932 | 13,588 | 7.68 | 0 |
| REGULATED | 4 | 15,871 | 1,218 | 17,089 | 10.49 | 0 |
| 合计 | 10 | 41,146 | 3,063 | 44,209 | 全批 26.33 | 0 |

NOTE 与 REVIEW 均为两次 stage_answer 加一次 final。REGULATED 先 read E1，再两次 stage_answer 和 final；该次读取获得 E1 实际内容，与已呈现材料相同，无新增观测。REGULATED 比 NOTE 多 3,557 raw tokens（约 26.3%），没有减少已暴露的范围错误。

A 分配上限 36，使用 10，剩余 26 未调用；独立模型调试 0，失败/拒绝/超时模型尝试 0，追加包 0。B 未分配请求，其 72 个规划槽位未转作 A。原 Goal 114/210 是规划包络，不是已经发生的调用数。

HTTP 分开统计：身份 GET 1，tokenize POST 10，生成 POST 10。CPU 接线回放/Mock 测试不计实验模型生成；新比较没有 Product 请求。每臂工具 CPU 约 0.00005／0.00005／0.00007 秒，仅覆盖白名单字典读取与算术/文本回执；持久化使用已有逐事件 fsync，耗时纳入墙钟，未单独测量，不填零。原始文件数/大小见结构化结果。费用与缓存优惠未计价，保持未知；开发主 agent/subagent 用量由平台独立记账，不与 44,209 实验 tokens 相加。

## 任务质量、失败边界与决定

来源核对：R12 客户端 173.056 ms，事务退出 164.426 ms；R22 319.975 ms，事务退出 309.995 ms；R32 51.368 ms，handler 内 7.012 ms，handler 前约 42.394 ms。区间差值与原始事件核对通过；具体原因没有被这些测量直接识别。

- NOTE 保留了前两批事务退出、第三批 handler 前的不同定位，也提出 DB 侧检查；但最终将第一批未观测 GC 与第二批小重叠混在一起排除，并将局部区间推断说得过强。
- REVIEW 前两段抓住约 1.6–1.8 ms 的小残差、漏掉 164/310 ms 主区间；最后将第三批的调度解释推广到前两批，构成实质范围错误。不能用“普通复核”名称替其行为判好。
- REGULATED 前两段保留了部分重要限制，最终却同样丢失第一批 GC 未观测边界，并把事务退出范围过强解释为 commit/rollback 内部；下一检查有用，但宣称的网络/驱动/DB 区分能力不足。多一次读取未形成可见净增量。

完整语义判断及原记录定位见[标注](MILA_HOST_WORKSPACE_A_LABELS_20260913.md)。未用词语匹配或一个总分替代判断；未把合理候选原因自动判错。三臂都有实质进展，也都有错误；没有删掉 REVIEW 失败结果来构造配对胜率。

**W4 决定：保留当前可运行接线与简单 NOTE 参照，暂停当前复杂候选的追加投入。** 当前机会下，记录未被使用、长记录政策没有显示净收益；这不否定 Memory 方向。无需为“写出记录”强制新流程，也不为寻找阳性耗尽追加预算。若后继任务确实需要跨步记录，可另立有界问题；本轮不声称形成、消费、冷恢复或条件重激活收益。任务未含条件 A→B→A；没有记录机制的错误恢复机会分母，Recovery 不适用。

## 第二来源与工程终态

B 的官方 `cancel-async-tasks` 已固定版本并只读核对必要文件。无害 namespace 探测成功，但现有 Lab guard 不是任意代码沙箱，尚无可直接复用的完整安全任务执行入口；官方 checker 未本地运行。按 Goal 的有界替代/停止条款停止 B，未建设隔离平台、下载全套 benchmark 或在宿主执行模型代码。详见[W3 处置记录](MILA_HOST_WORKSPACE_B_DISPOSITION_20260913.md)。

工程检查：55 项邻近测试（含旧 Provider 回归）通过；boundary、ruff `src tests tools`、mypy `src/milai_lab`（40 文件）、sdist/wheel build 通过。全量 pytest 一次 180 秒有界检查终态为 **1822 PASS / 1 FAIL / 1 SKIP，179.93 秒，外层 exit 124**；已中断，未完成。FAIL 是上述旧冻结 Provider 源码漂移，已修复文件并重新通过 55 项邻近测试；随后仅对该失败文件做一次 180 秒有界复验：**179.99 秒、exit 124，未完成任何测试项**（pytest 输出 `no tests ran`，在首项内部被中断），未得到该测试 PASS。原冻结 manifest 的全部依赖 hash 已逐项核对恢复一致；这是源码漂移原因消除的证据，不能代替完整旧测试通过。复验[日志](/cra/memory/mx_memory/evidence/workspace-host/frozen-test-after-provider-isolation.log)保留，不继续扫描旧证据或扩大性能工程。全量日志[保留原样](/cra/memory/mx_memory/evidence/workspace-host/full-pytest-20260913.log)，不声称全仓通过。

Product 默认、Canonical、共享服务、GPU、公开部署、Schema 冻结状态均未修改。旧 Gate A 和 WMA 未重跑，旧未知费用保留。本轮实现与任务判断属于 Lab 开放开发；独立确认、跨模型、未暴露来源和持久链不在本轮已证范围。


## 按原 Goal 收口核对

| 原要求 | 当前证据与结论 |
| --- | --- |
| W1：真实材料、事件语义、Provider 接线 | v2 manifest/六请求原行映射、真实 tokenizer 与服务/usage 逐次一致、三臂完整 rows/HTTP/action 记录。模型写记录并非资格门；本次选择不写，未观察到真实记录消费 |
| W2：同任务完整三臂 | 3/3 完整轨迹，固定顺序、同空初态/权限/材料规则/预算，10/10 known usage；保留语义失败及实际重复，非无记忆因果比较 |
| W3：第二来源比较或有界处理 | B 固定上游版本与来源，实际环境核查、明确停止记录；无 checker 正负例或第二来源比较，不混报完成 |
| W4：解释与取舍 | 基于逐轨迹标注和全成本保留简单 NOTE 参照、暂停复杂候选；没有新解释就不追加比较。未用完配额不算待办 |
| 边界、可运行 opt-in 原型、完整成本与版本 | Lab 专用入口/适配器、Git 外运行快照、结构化账、无产品默认修改；CPU 回放验证最终接线。未知费用和开发成本单列 |
| 工程交付 | 邻近/静态/build 实际结果及一次全量中断原状均列明；修复已发现的相关源码漂移。没有借全量未完成重开旧 Gate |

正常开发交付已覆盖上述范围；两来源覆盖、真实工作记录消费、持久记忆因果和创新确认未证明，不能由完成这份开发交付推导。
