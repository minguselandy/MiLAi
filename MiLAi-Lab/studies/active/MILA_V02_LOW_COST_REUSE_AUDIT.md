---
document_id: MILA-V02-03-SOURCE-AUDIT
status: SEALED_BEFORE_CANDIDATE_MODEL_ALLOCATION
date: "2026-09-06"
reviewer: ROOT_CODEX_OFFLINE_SOURCE_REVIEW
independent_review: false
human_gold: false
---

# 评价与首个证据缺失点

计数 0a995998：`AMBIGUOUS`。原题“需要从商店领取或退回多少件衣物”及官方参考 3 保持不变。
中性源 hash `9a9186bca9af27696878c06b3d65ec4f846fad7429e9e8aa5167a7d0c8def5ee`，
题目截止 2023-02-15 23:50。对完整 44 session / 484 turn 包做衣物、商店、购买、交换、
领取、归还、借用词族扫描及 session 主题审阅，再核对相关用户原话。不是只查看旧 A0 命中的片段。

| 对象/事件 | 用户来源与时间 | 条件和判定 |
|---|---|---|
| 藏青 blazer 干洗待领 | s11 t0/t10，02-15 06:30 | t0 明确 still need；t10 是计划去领，非完成回执。干洗店是否包括在 store 需说明。重复叙述不是第二件。 |
| Zara 靴子换码后待领 | s19 t6，11:13；s30 t4，16:19 | 同为 02-05/2-5 购买、Zara、尺寸交换、未领新的一双。支持同一事件重复叙述；s19 的 need to return 与随后 exchanged 状态不完全一致。无独立第二购买凭证。 |
| 借给姐姐的绿毛衣 | s19 t2，11:13 | 用户说姐姐未归还；是个人借用，非商店领取/退货。放宽题目到所有待取回衣物才会包含。 |
| 黑色 Levi’s 牛仔裤、白色 H&M 衬衫 | s11 t8 | 已购买且满意，无待领/退货状态。 |
| 瑜伽裤、围巾手套、黄裙、其他衣柜衣物 | s19 t10、s30 t2/t8、s11 | 洗涤/收纳，不能转成商店待领取事件。 |
| 鱼网、DMC 绣线、藏品、家族首饰 | s8、s21、s29、s35 | 已购/已收到或出售意向；非待取衣物。电商经营退货建议 s25、故事 s26、品牌起名 s43 不是用户衣物交易回执。 |

合理解释存在分歧：按“干洗算店、双靴算一项、同一购买去重”得到两项；把单只靴作为一件可能
得到 3；忽略 store 限定加入姐姐毛衣也可能得到 3，但改变了题意。来源未明确 item 单位，
没有依据把任一口径提升成唯一新 gold。保留原参考匹配评价；不用于本轮候选二值胜负。
未创建新的明确化题目，也未改原标签。

普通 8550ddae：`SCORABLE`。源 s5 t2/t4 支持 lavender gin fizz；配方中的替换须按源，
不由酒名推导新事实。更新 852ce960：`SCORABLE`，s2 t2 为 08-11 的 350000，s36 t0 为
11-30 回忆的 400000；只判历史最新表述，不声称当前 lender 确认。

新公开 v0.2 testkit 的来源→候选→Context 核对（固定 query/snapshot，非模型）：

| 锚点 | 已观察链路 | 解释边界 |
|---|---|---|
| 计数 | s11 t0 blazer、s30 t4 boots 均在候选且进入 Context；s19 t6 的重复 boots 在候选未进入 Context；s19 t2 毛衣不在本次候选 | 重复叙述缺失不是新的对象丢失；歧义题无法据此确认任务损失。 |
| 普通 | s5 t2 在返回 Context，含相邻 s5 t3 | 未发现关键酒名证据 first-loss。 |
| 更新 | s2 t2 与 s36 t0 均在候选并进入 Context | 未发现两条金额/日期证据 first-loss。 |

来源完整扫描与 trace 核对由同一执行者进行；未调用独立 Judge。新实验未启动问答 Host，
故外显判断、首次出错位置和 later model inputs 在新锚点上仍 `UNOBSERVED`。
S45 的 `PROOF_ACTION_NOT_SELECTED` 不是 Context 丢弃的同义词；用实际 context_admission 判定递送。
当前没有足以触发 N5 QA 修复的一般性任务缺陷。工程 trace 恢复不算问答候选胜例。
