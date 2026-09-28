# v4 F0：基线和九类历史失败

状态：**OFFLINE_EVIDENCE_FROZEN**。从已发布 `44f9291bb0c7f3b6d5c9c71dadf76d1924a81eb2` 开始，
保留 v3 B0/B1/C、旧输入、旧 rubric、原分数及所有失败费用。本次只读历史证据，没有模型重跑。
[执行记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V4_20260928.md)列出完整 v4 要求，
[九类失败清单](../data/manifests/next-development-v4-f0-failures-20260928.json)保存最小输入/实际输出/Store 与 Tool 状态、首断点、竞争解释及原证据身份。
清单 SHA `c02bbf23a7d38029bcafad0ddf36be2b01a837d174185f97bbf18ff7669597b8`。

## 实际断点

| 编号 | 最小真实前缀与输出 | Store / Tool 及首断点 | 修复边界 |
| --- | --- | --- | --- |
| F0-1 | v3 field_plan/C 要求长期保存；两次最终候选均声称 saved/committed | 零实际工具、空普通库；Host 未提案 | 程序按真实操作记账，不能拿结果字段自动写记忆或认证语义 |
| F0-2 | independent_note/C 第二项实际补写后，用 record UUID 填 receipt_refs | CREATE 真成功、正文正确；错误发生在模型重报身份 | 操作身份由程序保存，正文成功与引用错误分列 |
| F0-3 | temporary/B0 当前仅本次 BRIEF；原回答没有前缀 | 空库、零写入、后续无污染；当前约束未消费 | 当前 task anchor；不按 BRIEF 关键词自动修答案 |
| F0-4 | v2 all 的一次 TEMP 正确，下一 session 提醒请求仍输出 TEMP | 普通库/State 均无 TEMP；助手历史格式延续 | 临时视图与历史角色分开，不删除不存在的持久偏好 |
| F0-5 | v2 all 真预约并部分标签失败后，记忆仍称 Nothing is reserved | 同一真实预约可恢复且未重复；漏语义维护是首断点 | 历史观察不能冒充实时世界，必要时查业务工具；不虚构历史重复动作 |
| F0-6 | trace76 当前 State4 已送达；旧助手和普通记忆5并存；Host 预约5 | 错在业务参数消费；更早 trace54 首次错误 write5 尚无旧助手5 | 分开角色冲突与增量时点；不可把后续冲突解释套到首次错误 |
| F0-7 | 完整 Summit archive crates 被改成单数 crate | 工具实际收到错误 key，后续真实部分副作用/恢复仍保留 | 不规范化或替换模型参数，不改历史严格评分 |
| F0-8 | 宽卡含三事项；用户仅排除简报行动；整卡重写删去房间/时间/入口 | 初始 State revision4 正确，维护输出及后续交付丢无关事实 | 可独立变化事项独立维护；不把不相关当删除 |
| F0-9 | 相同小 bank/完整历史五种读取均答对 | A 有真实 wrong-kind not_found；额外选择费用未换质量收益 | 默认 all/query；必须有真实瓶颈才付 Attention 成本 |

F0-6 原 trace54/76 均按原行号（从 1 起）读取，整 trace 与历史发布 hash 一致。
trace54 的首错不能由尚未存在的旧助手“5”造成；trace76 确实出现 State4／普通记忆5／旧助手5 的竞争。
这两个证据同时保留，不用单一解释覆盖全部失败。F0-5 的正确实际恢复也保留，不把风险假设写成已发生失败。

## 保存和核查

32 项读取来源记录路径和 SHA；D0 request/evaluator 与既有冻结清单逐项匹配，原 trace 整文件 hash 匹配；
N5 的 trace、manifest、progress 和 business journal 与已发布哈希一致；N2 输入与运行前冻结哈希一致。
v3 各选中轨迹的原 trace 与公开结果清单一致，原输入字节也一致；实际 turn 制品给出最终候选和当前记录。
新提取的完整 request/evaluator 仅保存在 ignored `artifacts/next-development-v4/f0`，公开清单是离线评估证据，不进入 Host。
没有操作历史数据库、修改结果或重写旧 rubric；原 full trace、checkpoint、失败和正确后续轨迹继续保留。

v3 基线远端 [PR66](https://github.com/minguselandy/MiLAi/pull/66) head 已读回一致，draft/open/unmerged；
[Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36373605907) success，Full skipped。
新工程在独立 v4 树进行，旧 main 未跟踪计划与 v27 草稿不被删除或挪用。

新增 generation/embedding 调用 **0/0**。连续账本仍为 **2950 / 3,729,307 / 20,729**
（generation calls / generation tokens / embedding tokens），SHA
`28cbcfe8c0be9208aaa9e6898daa36dcaa1d9202ee27fa73a613d5f45f7a4e38`。
文档/证据整理只核对 JSON、链接、哈希和 diff，不运行测试、构建或模型。

## Reflection

| 总规划 §32 问题 | F0 结论 |
| --- | --- |
| 1 支持什么 | 无操作假 saved、身份混淆、历史消费、宽卡保持、选择开销是可区分断点 |
| 2 反驳什么 | 所有错误都来自 Store 丢写，或都来自旧助手污染，均不符合真实链 |
| 3 首断点 | 九项分别见上表；首个写入错误与后续错误动作不混为一项 |
| 4 更简单解释 | 当前任务遗漏、职责负担、时点歧义与来源竞争即可解释部分现象 |
| 5 更简单方法 | 保留 B0 普通 CRUD；程序记录实际操作，模型视图标来源 |
| 6 复杂度 | 只需最小请求投影、临时 task/ref 视图和审计，无新平台或审核 Agent |
| 7 过拟合风险 | 九类全部已暴露，不能按词语修答案、调 rubric 或宣称 unseen |
| 8 反例 | 无工具却称 saved、实际写入但报告身份错、当前格式遗漏而无持久污染、旧记忆过期但世界恢复正确 |
| 9 决定 | Continue 到分步 F1–F7；先工程，再六脚本回归；A/B 通过后才创建新样本 |
| 10 理由 | 输入和执行链真实可见，缺的是职责边界与消费；增加控制模型不能先验解决这些问题 |

方法效果尚未重新验证，F0 不证明任何 v4 改善。完整工程和新的语义小样本仍待执行；研究目标未达成，Product NO-GO。
