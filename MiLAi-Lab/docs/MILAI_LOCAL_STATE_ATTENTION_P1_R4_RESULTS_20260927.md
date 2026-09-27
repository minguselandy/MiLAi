# LSA P1 R4：全量与焦点读取的完整小对照

源码 `aa73962426d67de648505b2d367b3f033652bce6`，
[冻结协议](../data/manifests/local-state-attention-p1-r4-protocol.json)，
[精简结果](../data/manifests/local-state-attention-p1-r4-results.json)。
六条冻结轨迹、十二个独立进程 phase、28 条消息全部执行，没有容量跳过、重试或未知用量。
两臂共同移除了 Host 临时视图的内部 State ID/revision，控制器仍为 R3。

| 任务分母 | local_all | local_state（focus） |
| --- | ---: | ---: |
| 原交错六消息 | 5/6 | 4/6 |
| 原部分失败六消息 | 2/6 | 3/6 |
| 原严格总分 | 7/12 | 7/12 |
| 原完整轨迹 | 0/2 | 0/2 |
| 新增用户报告控制 | 2/2 | 1/2 |

这是暴露 development 输入的一次在线比较。全量读取有恢复收益的具体实例，但两臂
原任务总分相同，不能得出稳定效果或普遍优劣。P1 严格闭环仍未通过。

## 结果与实际因果链

交错 all 将当前 field kits 的 8/N-6/rigid cases 和 briefing 的 R-3/14:30/step-free
恢复给新会话；focus 对这两次查询均给空视图。focus 的组合行动反而正确创建了两项
预留，all 却把两个地点作为 item_key、把另一事项的 Room R-3 当作共同 destination。
all 的动作前视图还包含没有真实回执的“Reserved”新卡，因此它并非干净的正确 State
上界。两臂的粒度与维护输出不同：all 最终五卡，focus 三卡；不是同 bank 的因果替换。

部分失败两臂都保存真实部分成功 ID，并在新进程实际 complete_label 同一 ID，无重复
reserve。**操作恢复不等于严格通过**：初次创建都把完整对象名 `Summit archive crates`
改成单数；恢复 get 分别用 reservation ID 和 `Summit archive crate M-4`，都返回
not_found。随后标签补全成功，不能抹去此前错误读取。Noel 的 key 分别单数化和改成
下划线形式，all 还改变字段大小写，因此严格动作均失败；用户隔离本身保持。

all 的 Mira 卡在处理实际补标签回执时丢失原先同卡的 D-2/10:15，故后续全量读取也
找不到该事实；focus 的卡保留它并正确回答。这个首个断点在维护写入，不能算读取遗漏。

用户报告两臂均形成正确陈述。all 在新会话交付并正确归因于用户本人；focus 的两次空
视图导致 memory search 后回答无记录。该实例支持“正确存储不等于实际可用”，同时
不是选路器已被证明无效的重复/跨模板证据。

## 竞争解释与最小下一步

H1：联合编辑/选择输出空 focus，屏蔽正确持久事实。用户报告控制和交错恢复支持它；
今后可独立复用只读 selector，但此轮不同时改变维护语义、Host 和选择策略。

H2：State 内容压缩/污染遗漏真实工具字段。两臂恢复视图有 reservation ID，却没有完整
真实回执的 item_key；合法工具 evidence_refs 与原始 receipt 仍在同 owner 的事件档案。
P2 已经证明直接真实回执可使这类首响应参数正确，无需再次做同一能力探针。

H3：Host 独立使用材料错误。正确计划与错误衍生卡混在全量视图，以及将无关 room 用于
业务，都可能干扰；对象精确命名问题也在多轮中保持。不能仅因 memory tool 返回成功
或标签最终创建就声称真实任务符合约定。

决定：**保留失败，优先实现按已选 State 的合法 evidence_refs 展开真实来源的薄视图**，
使实际请求可取得摘要漏掉的原字段。仅使用模型明确引用且权限内仍存在的事件；程序机械
删除依赖不当作语义引用，空引用不猜来源，保留来源种类和原内容。保持当前观察、控制器、
Host 工具合同不变，新增读取与字节成本据实计量。先做相关离线接线与小型 on/off 完整
恢复对照；保留初次创建错误，不能将 get 修复称作整个 P1 通过。

P3 的完整 G/L/LRU 比较尚未开始。规划要求的强 G/L 表示实现及少量 wiring 不必等所有
Host 精确参数失误都消失；但不能凭接口通过就运行 36 条广泛批次，也不提前记 P3 完成。
停止 R3 控制合同措辞微调，分开处理读取、摘要保真和独立 Host 使用问题。

## 成本与复现边界

| 角色 | 实际 HTTP | tokens | HTTP wall seconds |
| --- | ---: | ---: | ---: |
| state_control | 48 | 60218 | 66.328 |
| task_host | 48 | 55636 | 24.635 |
| embedding | 11 | 256 | 0.410 |

新增 **96 generation / 115854 generation tokens / 256 embedding tokens**。
连续账本 **1079 generation calls / 1300287 generation tokens / 10831 embedding tokens**；
LSA 启动以来累计 216 generation / 257558 generation tokens / 1214 embedding tokens。
所有控制和 memory 往返均计入；all 仍计算 focus，不是删除 selector 成本的臂。

全部实际用户输入字节已在真实 Host HTTP 中核对。临时 State 对象仅含 title/content/
needs/evidence_refs，trace 则分别保留 controller_focus、delivered_state_ids、read_policy。
0 degraded/0 pending 只是程序计数，不能替代上述失败链。
各 run 的实际 BaseStore get/search/put、CPU/wall、逻辑输入/结果字节及 State/事件/meta
逻辑存储见精简数据；不把这些数等同物理数据库大小或旧 SER exact reads。

ignored 证据在 `artifacts/local-state-attention/p1-r4/`，包括实际入口生成的 manifest、
execution-freeze、原配置、前后账本、逐 phase Store 快照、trace/world/checkpoint/journal、
完整 offline-review。依固定 run_plan 顺序，每个 run 先 prepare 后逐进程 run-phase 0/1。
独立复现须使用本页源码 SHA、冻结原脚本字节与新 run/root；不重用已执行身份。
此后改变视图不能追写本次锁、输入或结果，也不能将单次在线差异解释为稳定 attention 收益。
