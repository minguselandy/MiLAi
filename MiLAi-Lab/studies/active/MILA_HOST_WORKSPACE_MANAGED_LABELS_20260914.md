---
document_id: MILA-HOST-WORKSPACE-MANAGED-LABELS
date: "2026-09-14"
status: OFFLINE_DEVELOPMENT_ANNOTATION_COMPLETE
reviewer: user_delegated_development_subagent
independent_human_gold: false
new_experimental_model_requests: 0
---

# Managed 比较 1：v3 失败与 v4 交付标注

直接阅读 `evidence/workspace-host/followup-20260914/a-managed-v3` 与 `a-managed-v4` 下全部三臂 rows/terminal，按同一 `task-a-v2` 的 visible 与 offline source-map 判读。row 从 0 开始。沿用[首轮原始行核对](MILA_HOST_WORKSPACE_A_LABELS_20260913.md)的证据：R12 transaction exit 164.426 ms，R22 309.995 ms；R32 的 42.393870 ms 是 **MCP client start 到 handler start**，handler 本身仅 7.012 ms。R12 GC 未观测，后两批只覆盖客户端进程。没有独立 human gold、额外 Judge 或实验模型请求。

## 实际呈现与工作记录

两版三臂都先在已呈现 E1 时 `read E1`，然后回答阶段；所有 29 个 row 的 work_update 均未写入，workspace revision 始终 0，无容量拒绝。这是实际未使用可选工作记录/选材的观察，不证明持久 Memory 收益或失败。

| v4 输入 row（三臂共同到 row 3） | 实际正文 `assembled_body_refs` | 行为机会 |
| --- | --- | --- |
| 0、1 | E1 | row 0 复读已呈现 E1，row 1 阶段答复 |
| 2 | E2、G2 | E1 正文已退出；row 1 的 B1 回答仍作为最近完整交换存在 |
| 3 | E2、G2、E3、G3 | 首次 B3 观察直接呈现，未因 focus 为空而丢失；B1 正文/回答已经退出 |
| 4 | E3、G3 | E2 及 B2 回答退出；REVIEW 此步交 final，另外两臂再次 stage_answer |
| 5（仅 NOTE、REGULATED） | 无 | 保留最近的 B3 stage_answer/结果，全部原正文退出；模型仍可 read 所有已发布句柄，但直接 final |

以上是实际正文记录与请求共同支持的退出，不是仅凭模式名判断。v3 也在 row 2 退出 E1，row 3 保留 E2/G2 及新 E3/G3；因调度提前结束，没有后续综合机会。早期总结进入普通历史，不等于生成了独立短工作记录。

## v3：保留为执行失败，不当最终能力成绩

三臂各 4 次，末段均提交 `stage_answer`。旧 dispatcher 结束该段后没有继续 final 机会，terminal 均 `NO_FINAL_DELIVERY`。这项可修复的执行问题解释“无最终交付”，不能标成 Memory 失败。v4 三臂从头运行，不用 v3 阶段回答拼接。

阶段文本仍保留语义证据：NOTE rows 1/2 抓住两批事务退出，row 3 抓住 handler 前主区间；REVIEW row 1 误以 1.56 ms 残差为主问题，row 2 虽抓住 310 ms exit，却据此编出 B1 为 post-transaction、B2 为 exit 的差别，row 3 沿用该错误。REGULATED rows 1/2 抓住大 exit，但 row 1 将 outside_handler 差值误称 handler-start 到 runtime-client-start，row 2 把 top-client-duration 当高负载关联；row 3 正确说出 client-start→handler-start，却把客户端 GC 零覆盖推广为所有 GC 无因果。合理的锁、网络、fsync **候选假设**本身不计事实误认；错误在已测区间定义及范围越界。

## v4：最终质量及错误链

| 臂 | 有效进展 | 关键错误、遗漏与来源 | 下一检查价值 |
| --- | --- | --- | --- |
| NOTE：6 次，final=row 5 | rows 1/2 正确保留 R12 164 ms、R22 310 ms，并在 row 1 明确 B1 GC 未观测；row 3 分清后两类位置，row 4 延续这种概括 | final 将 B1/B2 举例写成 **R31**、exit **1.2–1.3 ms**、median **0.1 ms**，把 B3 的约 1.2/1.3 ms 搬到旧批次并添了无来源的比较基准。这不是四舍五入，实质改变旧证据。row 4 基本逐字重复 row 3，未新增信息，也未补读；row 5 输入只剩该 B3 总结。保留“两类位置”概括不抵消数字/身份错误 | DB commit 路径检查方向有用，但最终旧批次依据已损坏；对 B3 的 handler entry/exit profiling 若只测 handler 内，不能解释开始前的 42 ms。应沿 client发送、服务端接收/入队、handler-start 对齐边界；不能由 clock binding 单独推定根因在 MCP 内部 |
| REVIEW：5 次，final=row 4 | row 2 正确定位 309.995 ms exit，final 对 R32 的 client/handler/before/after 数值基本准确，辨认主要延迟在 handler 之前 | row 1 将 hold−enter−exit 残差错称 exit 到 release，并把小区间作为主要调查目标；final 明确标题只报告 **Batch 3**，未综合 B1/B2 的巨大事务退出和 GC 缺口。虽有合法重读句柄，未重读。最终将前区间收窄为 MCP client preparation / arrival scheduler，也超过所给边界；不是确认了客户端位置 | 提议 first-byte、队列及连接建立事件可实际缩小前区间，优于只测 handler 内；但连接事件相关不等于唯一根因。对 B3 有正向价值，不能替代整项任务的跨批交付 |
| REGULATED：6 次，final=row 5 | rows 1/2 抓住 R12/R22 事务退出并在 B1 保留 GC unknown；合理指出需更多日志区分候选 | row 3 **原始 E3 仍在输入时**已将 before_handler=42 ms 改成“handler 内、runtime call 之前”；row 4/5 沿用并把 R31 2.1 ms 也改为 before-runtime。7 ms handler 不能容纳 42 ms 内部区间。这是新证据解释错误先发生、原正文后退出，不能全归于遗忘。final 仅 B3，B1/B2 未综合；客户端 GC overlap=0 被用来排除 MCP 进程 GC，也越界 | 建议 MCP 内部 serialization/lock logging 是可检验候选，但其优先级依赖错误区间定位，可能错过真正的 handler 前链路。合理的 payload/锁假设不单独计错；“已定位 handler pre-runtime”才是有证据反驳的断言 |

另有次要算术/定义误差：NOTE row 1 把 166.204/168.944≈98.4% 写成约 96%，row 2 把 312.028/315.273≈99.0% 写成约 97.5%；残差 hold−enter−exit 不代表 enter/exit overhead。这些不改变前两批 exit 占主导的事实，重要性低于最终跨批错引。

三臂最终均未声称已经执行提出的新检查，也未要求降低审计、持久化或负载约束。v4 的 `COMPLETE` 证明 dispatcher 收到 final，不证明语义交付合格；这里三臂都未完整、可靠地完成跨批综合。

## 成本与决定

v3：12 次、45,402 raw tokens；v4：17 次、62,220 raw tokens；合计 **29 次、107,622 tokens**，pending/violations 均空，符合比较 1 的 ≤36 次包络。v4 NOTE/REVIEW/REGULATED 分别 21,393 / 18,957 / 21,870 tokens。每臂首次复读已直接呈现 E1 可疑重复；NOTE row 4 重复已有 B3 回答没有新证据，REGULATED row 4 只重述已有错误解释。完整 HTTP 预检、工具、墙钟和开发成本另见执行总账。

**当前不保留“managed 能改善续接或节省重读”的收益主张。** 接线确实使旧正文退出，也保留共同读取入口；模型未选材、未写短记录、未补读旧材料，发生可定位的事实错引和交付范围缩减。允许一次同 v4、同 NOTE 的 COMMON/MANAGED 整体上下文保留消融，检验保留旧正文及完整历史是否减轻这些具体错误；该消融已在[批准记录](MILA_HOST_WORKSPACE_MANAGED_AUTH_20260914.md)限定为最多 16 次。REGULATED 在正文仍在时就误解新边界，提醒保留上下文也可能无法修复语义解释。

判读保留不确定性：文本将 handler/client/arrival 混称的部分可宽松视为命名不精确，但 REGULATED 明确“within handler”与 42>7 ms、NOTE 数值/请求跨批迁移、两臂缺失旧批次综合都有直接证据，不依赖宽严措辞选择。无第二标注者或独立复核一致性统计，不作跨来源、持久恢复或算法优劣结论。

## 唯一比较 2：整体上下文保留消融

比较 2 的四条轨迹均只使用 NOTE。首次 `note-common-v4` 在 4 次、19,349 tokens 后停止，CPU 重放定位 `PROTECTED_INPUT_OVER_BUDGET`：需要 9679 tokens，超过 8192；该次组装未产生新 HTTP 生成。这是执行容量失败，不计最终任务质量输赢。配对的 `note-managed-v4` 用 5 次、19,530 tokens 交付，但 final 聚焦 B3，仅以“earlier batches ... might have been dominant”含糊提旧批，未可靠综合旧定位；不能只保留后一次较好的 MANAGED。

容量修正版 `note-common-v4-input16k` 与 `note-managed-v4-input16k` 双方共同 input 16384、同 v4/NOTE/原证据/`[2,2,4]`/Provider，固定 COMMON→MANAGED。全部记录仍为空。此修正版是本节主要可解释配对，和 8192 版本不合并胜率。

| 修正版轨迹 | 实际呈现、行动与继承 | 最终语义判断 |
| --- | --- | --- |
| COMMON：8 次，66,518 tokens，final=row 7 | 每批新源直接呈现；rows 4–7 均含 E1/E2/G2/E3/G3 全部正文，最终亦含前 7 次完整动作/回答。分别 read E1/E2/E3，都在该批正文已呈现后，返回真实 READ；row 6 再综合后 row 7 final | final 覆盖两类旧/新位置，保留 R12/R22 173/320 ms、R32 42 ms handler 前差值、两类时钟覆盖。却漏掉 **164/310 ms exit** 这一已有最具体定位，持续误以 1.5–1.8 ms 残差表示“非活动事务”并将其作为 DB 机制解释；全正文保留没有避免该错误。阶段与最终一再建议不存在的高 inflight R13/R33，并提前把 R31 设为高并发。对负载影响的待检验问题合理，但“若高 inflight 就 confirms queueing/DB contention”不能成立，只有相关不足以识别根因 |
| MANAGED：5 次，21,115 tokens，final=row 4 | row 2 已无 E1 正文，但继承 row 1 的 B1 回答；row 2 回答再次写出 R12 164/R22 310。row 3 含 E2/G2 和新 E3/G3，并把旧数字写进 B3 阶段综合。final 输入仅 E3/G3 与该 row 3 回答，**通过普通阶段回答继承保留 164/310**，无 work_update 或 focus。仅 read E1 一次 | final 正确保留 R12/R22 164/310 ms exit，与 R32 1.32 ms exit、42.39 ms handler 前区间对比；此次旧批数值保真与定位粒度优于配对 COMMON。仍将“different root cause”说得过满，把计时边界称 arrival-dispatch→handler，而原 before_handler 从 MCP client start 算起；候选集中 scheduler/event-loop，对高 concurrency/load 只有猜测。建议 queue depth/idle time 可检验一个候选，但高队列/低 idle 不能直接推出增加 handlers 或唯一确认 blocking，缺少传输/接收/入队边界 |

COMMON 的 R13/R31-high-inflight/R33 均只出现在 stage/final 建议文本，**没有实际 read 未知句柄**，因此这次不能虚称 dispatcher 已拒绝这些请求，也不能记为读取成功。实际 read 仅 E1/E2/E3，全部正确返回原正文。合法建议收集新的高并发材料允许存在，问题是给尚不存在的记录预定身份/属性且夸大辨识力；不能把没有该观测填成结果。

GC 范围同样保留：COMMON row 3 把客户端 0.3 ms 直接说成排除 GC 原因，未限定其他进程；MANAGED row 1 正确保留 B1 NOT_OBSERVED、row 2 写出 LOAD_CLIENT_ONLY，row 3 又用 B3 客户端零 overlap 排除整体 GC，属于覆盖过推。MANAGED final 没再重复 GC 排除，也没保留 B1 缺口；遗漏与明确填零分开记录。row 2 关于“policy might mask pauses”是未证实猜测，材料实际 `policy_changed_by_probe=false`，不能当已发生干预。

以上完成配对直接反驳“保留全部正文和历史就足以避免该错误”的强说法；只证明此 COMMON 轨迹即使保留仍错。本次 MANAGED 更低成本且较好保留旧数字，却不能证明截短导致改善：动作数不同、阶段回答自身可续接；此前 `a-managed-v4/NOTE` final 错引、`note-managed-v4` final 旧批遗漏都仍在结果集中。没有 workspace 更新，不能主张短记录形成/消费有收益。全部来源仍只有 A，不新增独立 lineage。

## 最终有界决定与总账

**保留 opt-in 的 COMMON/MANAGED 可运行入口和简单 NOTE；暂停 REGULATED 的必要机制/默认优胜主张，结束本轮生成，不再追加字段、政策、题目或参数搜索。** 本轮已证明新观察共同直达、旧正文实际退出、合法读取保持、完整成本可查；没有可靠且重复的短记录或材料选择收益。完成配对出现一次较低成本且旧定位更好的 MANAGED 结果，作为有边界的开发观察保留，同时保留先前失败，既不将它提升为创新信号，也不因空记录否定整个方向。

比较 2 首版 9 次 / 38,879 tokens，加容量修正版 13 次 / 87,633 tokens，共 **22 次 / 126,512 tokens**。加比较 1 的 29 次 / 107,622 tokens，本轮实际 **51 次 / 234,134 raw tokens，debug 0**；已查各 result accounting 的 pending/violations 为空。没有把未发送的容量失败补成模型调用，没有把费用未知写零。不同输入容量/机会/执行版本不合并为胜率，失败成本全部保留。完整工具、墙钟、HTTP 预检与工程终态由主报告单列。

独立来源、公开持久化/冷恢复、冻结候选确认与产品默认化仍未触发；本轮不要求靠耗完 76 次上限获得阳性。上述决定是开放开发收口，不是证明创新成立。
