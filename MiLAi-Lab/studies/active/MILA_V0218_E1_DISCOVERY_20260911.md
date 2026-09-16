# V0218 E1：同信息消费策略首批开放发现

状态：E1 首批及唯一一次固定冷复验均完整执行并审计；E2 尚未执行。以下前半为生成前合同。
前置 [E0 v4](MILA_V0218_E0_V4_20260911.md) 已完成，统一 S*=N1，全部旧账为
941 requests / 2168439 raw，未知用量=0。[选择配置](../../configs/v0218-s-star.json)
绑定 E0 汇总 hash；不能根据每题切换对手或引用旧协议的有利成绩。

## 入口与反证

[首批清单](../../configs/v0218-e1-discovery.json)选两个已暴露 D lineage：
日程存在旧 Note/新来源双呈现后的无必要暂停；新闻标准 N1 已成功但重复四条已满足记录，
同时其未决 probe 存在实际交付缺口。前者观察更新，后者既是效率机会也是干预过度反例。
Stable/Superseded 同源配对不增加独立 N；本批只两 roots/两个 family，不解封 C。

| 臂 | 唯一新增差异 | 可反驳的预测 |
| --- | --- | --- |
| N1 / S* | 无；与 E0 v4 原 Host 相同 system/messages/tools | 基线不能因包装器、丢历史、少生成机会而削弱 |
| C1 | 通用 evidence/action audit 提示，区分计划、来源与实际工作，保留满足项并完成缺口 | 若无业务/重复工作改善，或 Stable 受损、同质量成本更高，则没有支持它的实用复杂性 |
| C2 | C1 加一次自由文本公开 Note 检查点：旧前提、适用证据/变化、已执行工作及下一动作/真未决 | 若相较去掉检查点的 C1 没有独立改善，删除该组件；笔记更详尽不等于业务更好 |

精确英文提示在 [policy Host](../../tools/v0218_policy_host.py)，不包含任务 ID、实体、答案或
checker 标签。C2 的检查点只要求简短可见证据/行动摘要，不索取隐藏思维链，不新增业务 schema。
这里研究的是同一 A 信息下的消费策略，不是修改 A 写作策略的端到端 externalization 优势。
C1 可能仅为同信息提示工程；C2 可能只是多一次普通复核。必须以 E2 排除简单解释，不预设新机制。

## 冷运行与成本合同

每 root 用未变的 common v4 Host 生成一个新的正常 A，仍允许 NO_WRITE；不选最佳 A、不强填理想 Note。
同一个 A 的真实业务状态/授权历史与原样 Note 派生 N1/C1/C2 B。C2 在 B 内自写新检查点才是候选行为，
不会回溯修改共同 A 或别的臂。每个 B 独立 scope、公开精确复制、全新 Host 进程，A 成本只计一次。

2 A + 2 roots × 2 worlds × 3 arms = 14 episodes，最多 224 次生成；
每 episode 16 次含最后 finish-only，900 秒；单请求 60 秒、输出 4096、模型串行，批次 14400 秒。
现有 Provider 的输入预检/容量、动作/恢复余量、未知 usage 停发和真实公共 Product pin 核验原样保留。
累计 raw cap=null，Judge/embedding/训练/额外兼容=0。检查点保存占同一个 16 次额度，没有免费 Reviewer。
各臂可自主取得同样的公开来源；实际读了什么、生成了多少、检查点是否执行均逐次计账，
同入口可得性不等于每条轨迹实际取得的信息完全相同。必要时 E2 需另测同呈现条件。

公共 Note CRUD、World/Checker/Provider 和 common v4 Host 文件不变；
新包装器在新进程仅设置冻结 system，再调用 common Host。N1 的实际请求与直接 common Host
在离线相同输入下逐对象相等；C1/C2 相同来源/Note/机会、无隐式写入有独立接线测试。
通用 runner 只增加显式已冻结 policy 分支和真实 stage 状态，不换模型、不改世界评分。
旧 E0 manifest/代码/失败输出不覆盖，新批保存全部执行源码、合同、E0/S* hash。

完整运行后保留全部尝试，不因 NO_WRITE 或不利结果替换 root。仅有可解释现象才登记一次额外冷复验。
E2 后续按结果安排普通复核、去组件、同信息/等机会及最近邻概念对照；已有
[近邻核查](MILA_V0218_PRIOR_ART_20260911.md)不能替代候选明确后的核查和真实比较。
E3/E4 尚未触发，C=0；E5 必须交付，当前整个 Goal 未完成。

## 首批实际结果与一次复验决定

Git 外 `evidence/v0218/20260911/e1-discovery-v1`：14 episodes 全部 FINISHED，
11 PASS / 3 FAIL；139 requests / 393907 raw，pending/violations=0。
公共 pin、两个新自主 A Note、12 个 B 精确冷读和实际旧/新来源双呈现均通过离线审计。
新 A 成本 27 / 64196 只计一次；新闻 A 用满 16 次、仅写两项，业务 FAIL 保留。
日程 A 完整通过。两种旧事实 Note 都可据 A 来源核验，新闻 Note 为待创建计划，不冒充完整落库。

| root/world | N1 | C1 | C2 |
| --- | --- | --- | --- |
| 日程 Stable | PASS，5 次 | PASS，3 次 | PASS，5 次 |
| 日程 Superseded | FAIL，7 次 | FAIL，13 次 | PASS，9 次 |
| 新闻 Stable | PASS，15 次 | PASS，9 次 | PASS，9 次 |
| 新闻 Superseded | PASS，15 次 | PASS，11 次 | PASS，11 次 |

C2 日程更新的公开检查点 SHA `0a9edafdc1bb19fbf199c596b04868fc5f35d07eff3ca2e3c1d672190bbccd0f`，
记录旧业务与当前约束不一致，随后真实更新两个对象，中途 CAS 拒绝后重新取得版本完成。
N1/C1 均实际澄清而留旧状态。全部有 current 与旧 Note 实际呈现，不是隐藏反证。
该检查点比要求的“简短”更长，未增额；自由文本格式/长短不是业务评分条件。
C1 在新闻 B 也自选保存了 Note，因此 C1 只是删除检查点指令，不等于保证没有自发检查点。
还不能把表中差异直接归因于 C2 的关系表达或公开持久化。

首批 manifest SHA `3c4e378ba8f6e0002441c20dc423037561a3882bb319087a9545a8ea0bf67c1b`；
result SHA `2c656f30aec3f4663337ee634e11eb075a8ff2466e01b4e07e11371a2a2903e5`；
`discovery-audit-v1.json` SHA `e80dd76857d4a9d1601cc7dd5aca66a3504eb346f9a0cafb13ec9ee4766ceac7`。
共同 A Note SHA：日程 `fc23938f736a34559055f9ede25a31138ed9210c5381ca1757289ca28b5e63e0`，
新闻 `bc3cf404e1f9610a088f4f67e34f4120c7c0d901424827582617037023f4e97e`。
首批 API/PG 已停止、卷保留；旧账加首批总计 1080 requests / 2562346 raw，全部 settled。

按原先“有可解释信号再做一次冷复验”的条件，登记
[第二次清单](../../configs/v0218-e1-repeat.json)：相同两个 roots、两个 worlds、三臂全部重复，
相同 policy/common Host/model/工具/预算，仍生成每 root 一个新共同 A，不挑最好 Note。
重复不新增 root，任何不利结果都保留；本次后不再为重复首批信号循环尝试。
当前离线检查 1232 passed / 1 optional skip；boundary/Ruff/mypy/build/diff-check 通过。

## 第二次冷复验：信号重复，但不稳定的效率收益保留

Git 外 `evidence/v0218/20260911/e1-discovery-r2-v1`：14 episodes 全部 FINISHED，
11 PASS / 3 FAIL，130 requests / 342620 raw，全部 settled；API/PG 已停，卷保留。
新增 A 成本 25 / 59819；两 A 均自写 Note，新闻 A 再次只写两项并用满 16 次，FAIL 保留。
12 个 B 再次核验精确公共冷读、实际 old/current 双呈现及同一个 A 业务/历史边界。
两次运行源码/策略、模型、预算相同，新的 A 内容不同，不把 28 episodes 当 28 个独立任务。

| root/world | N1 | C1 | C2 |
| --- | --- | --- | --- |
| 日程 Stable | PASS，5 次 | PASS，5 次 | PASS，5 次 |
| 日程 Superseded | FAIL，9 次 | FAIL，8 次 | PASS，9 次 |
| 新闻 Stable | PASS，13 次 | PASS，9 次 | PASS，9 次 |
| 新闻 Superseded | PASS，10 次 | PASS，12 次 | PASS，11 次 |

日程 C2 的更新通过重复出现，N1/C1 仍无必要暂停；两次 Stable 都没有业务质量损害。
但新闻更新第二次 N1 比 C1/C2 更少调用，首批的该项效率优势没有复现。
新闻 Stable 的 A 原来就缺业务记录，因此它是事实不变下补全工作，不是完整 A 的纯保持机会；
两候选相对 N1 减少的调用部分来自 CAS/读回差异，不直接叫 Memory continuity 因果收益。
首批 C2 在新闻 Stable 还重复写两项已完成记录，第二次无重复，未证明检查点普遍减少冗余。

非盲 Note 语义复核：第二次日程 A SHA
`c51bac85ff14d03339dee1ef65c83ba19cba8a0d63a909a04effedcd77bdccd5`，
当时两个时段/房间/面试官与真实记录一致，A 来源下合法；不同于首批 C04 面试官 B，
不是将首批 Note 改写后偷偷重用。新闻 A SHA
`07050133f6a8a8a32af8d23b4dedd273ea7690db630c2b0ca12f82619fcebd22`，
四项旧来源及待创建计划正确，完整 A 业务仍缺两项；不因部分执行失败否定正确旧前提。
复核由同一开发者、已知 arm/结果；没有独立人审或 Judge，无法推导模型内部采信过程。

| 两次 E1 成本口径 | requests | raw tokens | B 业务结果 |
| --- | --- | --- | --- |
| 4 共同 A，只计一次 | 52 | 124015 | 2 PASS / 2 FAIL |
| N1 B | 79 | 237167 | 6 PASS / 2 FAIL |
| C1 B | 70 | 194581 | 6 PASS / 2 FAIL |
| C2 B | 68 | 180764 | 8 PASS |
| E1 两批完整合计 | **269** | **736527** | 2 个原 lineage，28 episodes |

这里不计算把两次/两个世界视为独立样本的显著性或置信区间。
C2 相对 N1/C1 的质量胜例集中在同一个日程更新 lineage；新闻最终质量全部相同。
C2 每个 B 保存一次检查点；C1/N1 在新闻也自然保存，指令消融并非实际“有 Note/无 Note”。
并且 C2 的文字更长、实际模型计算/读取不同，最多说明一个需要拆解的消费策略信号。
E2 必须面对普通复核、去结构/去组件和直接近邻；不得由两次 4/4 直接进入创新成立或产品默认。

复验 manifest SHA `ffc6dd3b4995c691c3f5e8b64d71f905ebc09b51be7ecae604a7d2c686e3e32f`；
result SHA `ab921ec71c608f63d1f236b5ebb1144865336872ce993d558a47142832a76cad`；
audit SHA `4c58dcd3b9ea15470efe36c44f2586bf3225d7ca660cd87a8e56fc088de7e12f`。
首批审计与整个 E0 汇总重放均输出原结果相等，未改判历史。

总账更新：建设/所有旧新 E0 941 / 2168439 + E1 269 / 736527 =
**1210 requests / 2904966 raw**，未知用量=0，Judge=0，累计 raw cap=null。
当前没有在途模型、自有活动服务或剩余活动分配。E1 发现完成，E2 筛选未完成；
条件 E3/E4 与必须的 E5 尚未完成，整个 Goal 保持 active，不标创新已证明。
