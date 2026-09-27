# 维护输入隔离 R1：原场景通过，Host 反例保留

状态：`COMPLETE_WITH_HOST_COUNTEREXAMPLE_FAILURE`。按
[冻结协议](../data/manifests/local-state-attention-maintenance-events-r1-protocol.json)，
源码 `5640a93071af3abdbc816fa914e5f60969364a03` 完成四轨迹、八个独立进程 phase、23 条消息。
[逐消息评分、实际计量及证据哈希](../data/manifests/local-state-attention-maintenance-events-r1-results.json)
保留所有结果；没有中断、替换或批内改源码。

| 冻结轨迹 | 严格消息 | 完整轨迹 | 真实行动 |
| --- | --- | --- | --- |
| 原高耦合 G | 6/6 | 1/1 | 三次预约，数量 3/4/3，完整字段正确 |
| 原高耦合 L | 6/6 | 1/1 | 三次预约，数量 3/4/3，完整字段正确 |
| 原高耦合 LRU | 6/6 | 1/1 | 三次预约，数量 3/4/3，完整字段正确 |
| 新同文本不同事件 LRU | 3/5 | 0/1 | 实际预约 5，正确数量应为 4；目的地也被缩写 |

附加 LRU 反例单列，不并入三臂匹配分母。一次正例不代替重复与未见收益证据。

## 输入边界与实际行为

G/L 全读路径现在使用 edits-only 维护；controller_focus 为空，但交付仍是实际全 bank。
LRU 的 U/A 继续接收当前任务；三臂可写维护共用仅含
`new_observations / states / source_ids_available` 的输入。legacy focus 保留旧联合合同。
不新增事件账本、不按文字去重，不改 Host schema、原用户/工具消息或 vLLM。

全部 **37 次实际维护 HTTP** 符合这一边界，其中 **14 次 pending 只有工具回执**。
例如原 G 的 trace 第 15 行，维护收到 manage_memory 创建回执，继续保存 3/4/5；L 第 21 行
相同类型回执后也保持 3/4/5。其后真实新会话正确判断 12>10、只减 display 到 3，并执行
3/4/3。原 P3 中通过 current_task 重复提示旧增量的通道已移除，未把工具回执全部跳过。

但 L 最终仍有“Nothing is reserved”的旧计划卡，另有正确结果卡和多余的待确认 needs。
任务 6/6 不能替代完整 reconciliation 或 State 质量验收；本轮不继续措辞微调。

## 新反例的首断点

Expected：初始 2；第一次真实“加一”到 3；跨进程后相同文字但新来源 ID 的第二次指令到 4。
Observed：维护器确实正确形成 3、4，Host 最后报告并实际执行 5。

LRU 反例的实际链：

1. trace 15：第一次增量，新 user source ID；维护从 2 写 3。trace 26 的工具回执后仍为 3。
2. trace 49：第二次增量，另一个 source ID；实际维护输入旧 State=3，输出正确的 4。
3. trace 54：Host 的实际 HTTP 已收到 `4 units (updated from 3)`，同时保留当前原用户增量。
   Host 调用 manage_memory(update)，却写出 `5 units (updated from 4)`。
4. trace 60：维护只收到真实“memory updated”回执，仍保留 4；trace 65 Host 回答 5。
5. trace 71：维护仍明确当前 4、需要 reserve 4；trace 76 的 Host HTTP 也收到这个正文，
   但实际 reserve 使用 quantity=5、destination=`S-2`，而非 `storage S-2`。
6. trace 81：维护如实记录已发生的错误预约 5，没有把真实 side effect 伪装成正确的 4。

H1：相同文本的新事件被去重、重放，或维护再次加一。不同 source ID 和两次正确维护输出
反对此局部解释；工具回执后仍保持 4，也排除了本例在旧断点重犯。
H2：Host 把已含当前增量的 State 当成增量前基数，再应用一次原用户指令；随后错误记忆写入
和助手历史维持了 5。首个错误正出现在正确 State 交付后的 Host 输出，支持 H2，但不能仅凭
此单轨迹断言全部错误都来自同一原因。明确的数字和目的地错误均留在完整分母中。

这不是“先正确后最终没关系”：真实错误预约已持久化。也不是维护器不支持两个相同文本的新
事件：两者均进入实际维护且得到正确的 3→4。正确材料到达与正确行动是两个验收层。

## 成本与验证

| 轨迹 | 控制 calls/tokens | Host calls/tokens | 生成总 tokens | embedding tokens |
| --- | --- | --- | --- | --- |
| G 高耦合 | 9 / 14,183 | 9 / 18,881 | 33,064 | 253 |
| L 高耦合 | 10 / 14,338 | 10 / 22,966 | 37,304 | 270 |
| LRU 高耦合 | 29 / 20,305 | 10 / 20,237 | 40,542 | 234 |
| LRU 新事件反例 | 23 / 12,548 | 8 / 11,554 | 24,102 | 91 |

新增 **108 次生成 / 135,012 generation tokens / 848 embedding tokens**（10 次 embedding）。
控制合计 71 次/61,374，Host 37 次/73,638；控制细分维护 37 次/49,235、U 16 次/5,853、
A 18 次/6,286。实际 HTTP 用时控制 88.113s、Host 34.505s、embedding 0.852s，非端到端时长。
连续账本为 **2,412 次生成 / 3,011,206 generation tokens / 18,183 embedding tokens**；
unknown=0，历史账本链未变，不清零此前全部失败和观察开销。

37 个视图与真实 Host HTTP 顺序绑定，164 次来源正文展开与 scoped Store 原值一致。
四轨迹 BaseStore get/search/put 依次为 177/83/40、230/92/44、212/92/44、122/72/31；
另计 Root 8 次空 namespace 只读检查和 8 次 phase 快照读取。结束 LSA 逻辑 value bytes
为 7,863 / 8,866 / 7,459 / 4,393，不是 PostgreSQL 物理占用。
无控制退化、容量或服务错误，最终 pending=0；这些计数不消除 Host 反例与 L 的过期正文。

源码先前 47 项窄测、目标静态、三臂 /tmp 零模型 prepare 和一次必要构建已通过；此次未重复。
实际 prepare 固定源码/输入/config/dependency，模型/窗口只读核对不产生生成费用。
复现按协议 run_order 用 `tools/run_local_state_attention.py prepare`，再在独立进程执行两个
`run-phase`；配置仅注入本机 tokenizer 路径，DSN 由环境提供。新复现用新 run/namespace 和
连续账本，不覆盖此次结果或重放已提交业务。

## 决策和局限

Continue：保留 events-only 维护边界，停止围绕该断点继续堆维护提示词。先发布本次正反证据。
原生 manage_memory 缺 ID 的可选工具错误观察仍是独立已知缺口，本轮未复发不代表已解决。
下一源码切片可局部处理该参数边界，不能宽泛捕获 ValueError 掩盖真实数据库故障。

Host 的快照时点/当前事件关系另作小型诊断：区分正确 post-event State 的重复应用、原始来源
展开与同 session 旧助手内容的影响。任何候选都须保留当前真实用户/工具消息，不能把合法引用
或机械依赖当语义处理证明，也不能直接删历史、强制新 Host State schema 或加入样本规则。
临时 Astra 只就这个具体跨层冲突提供最小候选，后续协议尚未冻结，不自动重跑整批。

三原轨迹的通过支持本次结构修复在该场景可用，不构成稳定的 LRU 独立收益；G/L 的 schema
也改变了，不能称纯删除一个字段的因果消融。第二模型、强历史基线、LR/R/U=A、授权删除、
归档/未知结果恢复、第二任务族和完整 P4–P7 仍未完成。Goal 保持 ACTIVE，Product 仍 NO-GO。
