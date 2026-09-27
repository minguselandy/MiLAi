# D0：失败前缀与首断点

状态：`OFFLINE_PREFIXES_FROZEN; REPLAY_REPAIR_CHECKED`。对应[新执行 Goal](MILAI_LSA_REVIEW_EXECUTION_GOAL.md)。
[十个前缀索引](../data/manifests/local-state-attention-review-d0-prefixes.json)绑定旧运行源码、
原trace整文件hash、具体HTTP行、输入文件hash及独立[rubric](../data/diagnostics/local_state_attention/review-d0-rubric.json)。
这是已暴露开发材料，来自少数旧轨迹，不是十个独立情景或新源码效果。

| 首断点／对照 | Observed → Expected | 竞争解释与最小区分办法 |
|---|---|---|
| State范围外遗失 | LR wiring L trace28：旧卡含简报R-3/14:30/无障碍入口，当前仅行动两类物品；维护输出删去简报 → 保留安排，不执行简报动作 | H1将“不要行动”误解为删除；H2整段生成近因偏重而漏写。固定旧卡和事件，whole rewrite vs局部entry；加入明确取消、只读历史查询反例 |
| 摘要范围外遗失 | window trace31：第三次摘要收到仍含简报的prior summary，新增仅后台修订，输出丢简报；无截断 → 保留无关事实 | H1只概括新turn而不合并旧摘要；H2优先最近任务。只作为保持诊断/强基线旧证据，不重复缩短摘要 |
| 正确State后再次增量 | maintenance distinct trace49正确3→4，trace54 Host实际收到4后写普通memory=5 → 当前正确值4，无业务动作 | H1当前post-event State被当作前态再次应用；H2旧助手/普通memory路径维持错误。先只变时间边界，再单独测写入权属；不由bank静态风险替代这条真实因果链 |
| 原始对象误写 | full history trace12有完整复数名称、数量/地点/包装，proposal却用单数 → 精确原对象及正确字段 | H1普通复制/生成能力问题；H2工具文本身份表达不足。独立消费层诊断；不自动纠正参数、不修改strict评分 |
| 无变化读取 | LR trace22仅问当前安排 → 三事项事实不变、无行动 | 语义无变化可伴随文字改写；不能把revision变化本身当错，也不能把未改字节当事实正确 |
| 同文本不同事件 | maintenance trace15与49内容逐字相同，source ID不同，分别正确2→3、3→4 | 直接反对按文本去重；同ID重放另由离线bank复现验证 |
| 当前用户改值 | LR trace15只改后台数量/地点，前台和简报不变 → 后台8/north rack，其他保持 | 区分真实新信息与无关读取；不能把全no-op当保持成功 |
| 内部记忆回执 | maintenance trace26仅manage_memory created，保持3 → 证明内部写成功，不证明新增量或业务完成 | 真实工具返回与外部事实支持不同；保留回执，不默认形成重复事实 |
| 部分业务成功 | LR partial trace39为ok=false且reserved_label_failed、实际ID和字段 → 保留已预留、待标签，不盲重复或推断发货 | 区分“全失败”概括与真实部分副作用。与full trace12的错误对象分开评分 |

## 确定实现缺陷与历史归因边界

Sol的零模型复现：同一事件的一批`[合法id:null create, 非法missing-ID update]`，第一次合法卡
已提交且pending保留；逐字重试产生第二个UUID卡。这证明create重试缺少提交身份。
竞争解释“绝对content写入天然幂等”仅适用于同ID同正文update，不能覆盖新建。
修复限定于成功edit的内部提交身份与窄回归，不新增数据库或模型语义裁判。
旧pending合并新事件、模型重新排序/改写提案的语义限制需单列，不能声称解决所有重复应用。
最终实现将精确排序的event_ids集合、目标State或new:原编辑位置、create/update位置散列为
内部`applied_edit_keys`，随成功State写入原子保存；重试返回原ID/revision，失败edit继续pending。
旧集合与旧+新集合身份不同，后续空事件更新保留标记；公开State/模型输入不包含标记。
接口签名和模型schema不变，旧State无此字段仍可读；新增存储字节和I/O照常计量。
最终缺陷相关6项窄测、目标Ruff/Mypy、diff检查通过。主体修改时整份LSA单测64项通过，
其后精确集合和空事件保持改动由最终6项覆盖；不把64项称为最终源码的重复全验。
没有新增构建、服务调用或完整benchmark。

## 材料边界、费用与决策

每个runtime文件只含该次真实HTTP的`request`，原输出、预期及错误标签只在evaluator文件和
rubric中。原请求保留当时实际收到的全部消息/工具schema；不增加私有observer内容或未来。
这些请求并不等于其时所有潜在可读历史。D1如需补充合法历史，各比较臂按同owner/时间边界
共享，另冻结变换，不能只给候选补齐正确材料。

离线提取逐一核对原trace与已发布结果hash；两个增量事件同文异ID、遗失前输入仍含简报、
runtime/evaluator文件隔离均已检查。新增生成/embedding/业务/Store调用均为0；连续账本仍为
2677次生成、3296791 generation tokens、18445 embedding tokens。

Continue：先合并确定重试缺陷；D1将局部entry转移与回合开始snapshot作为两个独立原型，
先冻结小条件比较再组合。范围外保持、真实修订、明确取消、历史查询和部分成功均需覆盖。
旧数据用于定位，不重跑16轮、不混算新源码、不把oracle或proposal分数当在线动作成功。
