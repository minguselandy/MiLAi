# 公共历史与完整历史对照：小接线 R1

四条预注册轨迹、八个独立 phase 进程、24 条消息全部完成。完整历史与 LR 历史均为
strict **10/12**；完整轨迹分别 **0/2、1/2**。LR 使用 56198 generation tokens，完整历史
18508，约 **3.04 倍**。这是一轮已暴露开发输入的接线比较，不证明重复稳定性、未见收益
或独立 attention 效应。所有精确对象名错误继续计为失败。

执行源码：`e44465b4b687dc86e68c6d6f0c079bb81e869d56`，已核对远端；全批源码保持不变。
[冻结协议](../data/manifests/local-state-attention-history-wiring-r1-protocol.json)绑定原两脚本、
原 rubric、顺序和容量；[精简结果](../data/manifests/local-state-attention-history-wiring-r1-results.json)
保存逐消息判定、实际计量与证据哈希。原规划不变，完整 LSA Goal 仍未完成。

## 实现与实际链路

新增共同 `read_history(cursor, max_bytes)`，默认关闭、两新臂显式开启，16384 UTF-8 字节
整回合分页。工具扩大了两臂相同的 JSON action 工具目录，不能把这两臂称为原 B1 的原样合同。
完整历史无 State 控制器，通过公开 checkpoint 读取已发生的各会话，按公开回合的实际顺序
投影到请求副本，包含最终 assistant、实际 tool calls/results 和仅一次当前前缀。
LR 保留 events-only 全候选维护和独立 A，额外获得同一按需历史工具。

历史不来自 observer 私有轨迹、rubric 或未来脚本。原 checkpoint 的 `messages` 保留各自
会话内容，跨会话投影没有写回历史。没有额外完整历史字节截断，容量沿用原 HostCapacity。
不完整旧回合保留实际前缀与 journal 状态并明确标为历史数据，不补造 ToolMessage；已有
owner tombstone 保守抑制该 owner 的历史读取/投影。这是读取屏蔽，尚非物理删除。

71 项受影响测试、目标 Ruff/Mypy/diff、四个零模型 prepare 和一次离线 build 均通过；
命令与构建哈希见协议。没有为发布重跑模型或测试。

实际验证：16 次完整历史 Host HTTP 的全部非 system 消息，逐条对照原始 scoped checkpoint
的回合切片和当前前缀相等；17 次 LR view 绑定真实 HTTP，43 次引用来源正文与保存事件相等。
两个臂实际 action schema 与 `read_history` 描述/参数相同。全部输入、源码 hash、模型参数
和连续账本已核对。没有降级、容量失败、HTTP 异常或末尾 pending。

**两臂均未自然调用 read_history。** 本批实际验证了完整历史自动读取/投影；工具分页、
tombstone、容量失败前缀和交替回到旧 session 的边界来自离线检查，不能称为本批真实触发。

## 结果与首个断点

| 方法 | interleaved | partial | 合计 | 完整轨迹 | 生成调用 | generation tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full_history | 5/6 | 5/6 | 10/12 | 0/2 | 16 | 18508 |
| local_lr_history | 6/6 | 4/6 | 10/12 | 1/2 | 51 | 56198 |

完整历史 interleaved 的 trace23，在原始对象名、全部先前用户消息和当前更新均已送达时，
Host 实际生成 `workshop_handout_packs`、`workshop_field_kits`，随后数据库按这些错误 key
创建预约。预期是精确 `Workshop handout packs`、`Workshop field kits`。数量、目的地、
包装、真实 ID 均正确，第三事项 R-3/14:30/step-free 保留；组合行动仍严格失败。

完整历史 partial 的 trace12，Mira 实际 `item_key` 为单数 `Summit archive crate`；
LR partial 的 trace27/62，Mira 和 Noel 都犯同一单数错误。请求中仍含原复数名称。
首个行为断点在 Host 参数生成，不是历史遗漏或数据库自行改键。完整历史 Noel 使用原复数
名称成功，不用这一成功替换 Mira 的失败。

两条 partial 都实际收到 `ok=false/reserved_label_failed`，真实预约继续存在；跨进程新
session 的 `get_reservation` 均 found，随后 `complete_label` 使用同一个原预约 ID。
最终各恰好两次 reserve、一次 label，没有重复预约或虚构物理发货。此恢复通过不抹去初始
错误 key。Mira 的 D-2/10:15 与 Noel 自己的数量、地点、包装保持隔离。

LR interleaved 自行形成三张卡，六项行为通过；但 trace46 行动前视图已把预约称为
“attempted”，当时真正的工具尚未发生。LR partial 最终卡仍有“预约尝试 failed”的误导性
概括，同时保留实际 ID、部分提交和后续成功标签。因此行为通过不等于 State 每句都正确。

竞争解释与反思：

- H1：Host 把 item_key 当作可规范化的内部标识；完整原始历史也不能阻止缩写/单数化。
- H2：State 标题、助手此前措辞与提示布局影响名称复制。LR partial 的标题为单数，正文及
  原用户消息仍为复数；这是可能影响，不是已隔离因果。完整历史也出现错误，排除“必须由
  State 标题造成”的强说法。
- 通用修复候选是独立的对象标识/解析契约，但现有工具已要求复制完整对象名，不能将重复
  添加该措辞当新修复。此轮不改 tool/parser、rubric 或业务 key，也不因错误进行样本重放。
- 最小下一比较是共享同一合法历史访问的滑动窗口＋短摘要与完整历史；先验证窗口外真实
  历史压缩和恢复，再讨论维护是否值得。名称错误及先报行动的 State 语义问题继续保留。
- Continue 完成强对照和后续必要证据；不宣称 LR 更好，不继续 Host snapshot 措辞路线，
  不将此单次结果作为 Kill 整个研究的依据。

## 完整成本与限制

本批新增 **67 generation calls /74706 generation tokens /108 embedding tokens**（2 次
embedding）。Host 为 33/46911，State-control 为 34/27795；后者全在 LR，维护17/20397、
A17/7398、U0。完整历史 Host prompt tokens 为17557；LR Host 为27281，控制为22653。
HTTP generation wall 合计57.0439秒、embedding0.2913秒；不是包含进程准备和本地 I/O 的
端到端墙钟。LR interleaved 还实际创建两条普通 LangMem memory，相关开销包含在内。

连续账本从2574/3183881/18337增长到 **2641/3258587/18445**，unknown usage0，历史链不变。
账本为 `artifacts/ser-v20/budget.json`；既往 exact-version reads107与本批 LSA I/O 分开。

完整历史新增 checkpoint reads9、逻辑返回字节14576、CPU6.5264毫秒、墙钟30.3801毫秒；
LR 未调用历史工具，因此该专项读取0。完整历史为 tombstone 检查做16次 Store search；
LR为255 get/156 search/78 put。Root 另有8次空 namespace查询、8次 phase snapshot查询、
12个原始会话 checkpoint 离线核对读取，无模型/embedding调用或业务写入。

| 最终存储 | 完整历史 | LR 历史 |
| --- | ---: | ---: |
| 两轨迹 checkpoint SQLite 字节 | 499712 | 610304 |
| LSA events 数/逻辑字节 | 0/0 | 20/9422 |
| State 数/逻辑字节 | 0/0 | 5/5593 |
| LSA metadata 数/逻辑字节 | 0/0 | 3/306 |

SQLite 是实际文件大小，含 checkpoint 版本与引擎开销，不能与逻辑正文直接相比或宣称存储
压缩率。每臂另有同样大小的 business DB与instrumentation文件，详见结果。全部原始轨迹/
DB/日志保留 ignored。完整历史最大预留总 tokens6238，LR7779，远低于65536容量；本批
没有检验长历史压力、压缩节省或大规模 I/O。系统轨迹分叉、一次重复和已暴露输入继续限制
因果解释。剩余 summary/R/U=A、生命周期、原生新任务、模型/规模和论文证据包仍未完成。

## 复现

使用执行提交和其 `uv.lock`，既有服务及DSN通过环境注入，真实HTTP并发1；不得复用已有
运行目录/namespace覆盖原结果。复制 tracked config到ignored路径，仅设置本地tokenizer
路径及 `history.enabled=true`，其他参数按协议。按协议顺序对每行执行：

```bash
.venv/bin/python tools/run_local_state_attention.py prepare \
  --config "$MILAI_HISTORY_CONFIG" --script "$MILAI_HISTORY_SCRIPT" \
  --run "$MILAI_HISTORY_RUN" --arm "$MILAI_HISTORY_ARM" --repeat 1 \
  --runtime-root "$MILAI_HISTORY_ROOT" --output "$MILAI_HISTORY_ROOT/prepared.json"
.venv/bin/python tools/run_local_state_attention.py run-phase \
  --config "$MILAI_HISTORY_CONFIG" --script "$MILAI_HISTORY_SCRIPT" \
  --run "$MILAI_HISTORY_RUN" --arm "$MILAI_HISTORY_ARM" --repeat 1 \
  --runtime-root "$MILAI_HISTORY_ROOT" --prepared "$MILAI_HISTORY_ROOT/prepared.json" \
  --phase 0 --stage lsa-history-wiring-r1-reproduction
.venv/bin/python tools/run_local_state_attention.py run-phase \
  --config "$MILAI_HISTORY_CONFIG" --script "$MILAI_HISTORY_SCRIPT" \
  --run "$MILAI_HISTORY_RUN" --arm "$MILAI_HISTORY_ARM" --repeat 1 \
  --runtime-root "$MILAI_HISTORY_ROOT" --prepared "$MILAI_HISTORY_ROOT/prepared.json" \
  --phase 1 --stage lsa-history-wiring-r1-reproduction
```

每个变量分别指向独立的新config/script/run/arm/root；固定两条输入及rubric hash，不重新
选择有利样本。prepare冻结身份，两个phase为不同进程。结果以实际HTTP、checkpoint、
业务world/journal和原rubric核对；正常退出不能替代语义判断。复现是新重复，成本续记，
不是覆盖本批结果。
