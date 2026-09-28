# v4 B R2：当前格式恢复，完整计划复述退化

结论：**按冻结严格门槛仍为 5/6，拒绝本候选晋级；停止继续换措辞或叠加 anchor，C 不创建。**
方法 `24ef49945cd12eccbd85792fee3c256bf3fe6d2a`，唯一源码变化是 v4 的 JSON `answer` 用户可见文本映射。
[事前协议](MILAI_NEXT_DEVELOPMENT_V4_B_R2_PROTOCOL_20260928.md)规定 temporary 先行，通过才继续其余五例；
六项均使用这次新冻结版本，未沿用 R1 成功结果。
[精简结果、原答与证据哈希](../data/manifests/next-development-v4-b-r2-results-20260928.json)保留本轮完整轨迹身份。

## 实际结果

先行两消息通过：首答为 `BRIEF: A title ...` 并在一句中解释 title/heading，下一独立 session 正常解释 caption，无 BRIEF，无持久写入。
Root 核对实际 HTTP 中唯一新增段后记录 pilot gate，再按冻结顺序完成其余五例，期间源码/输入不变。

| 项 | R1 | R2 |
| --- | ---: | ---: |
| 新形成 | 5/5 | 5/5 |
| 修订与无关内容保持 | 1/1 | 1/1 |
| 完整后续使用 | 7/7 | 6/7 |
| 持久正例完整链 | 4/4 | 3/4 |
| 三类负例范围 | 3/3 | 3/3 |
| 当前 BRIEF / 下一 session 无泄漏 | 0/1；1/1 | 1/1；1/1 |
| 完整脚本 / 严格逐消息任务 | 5/6；14/15 | 5/6；14/15 |

R2 的 field_plan 后续原答为：

> Your current sample-delivery plan is for 4 units to be delivered to rack R-7, packed in sealed sleeves.

数量、目的地和包装三个问题中点名的字段均正确；这不是完全错误的回答。
但原冻结 rubric 的 task 要求后续回答准确给出 **all plan fields**，required_record 明列物品 **Harbor sampler trays**。
R2 省略物品身份，因此按原完整性口径判该次 later use 失败，不能在看到结果后将晋级口径改成只检查三个点名字段。
不因省略未预约陈述再增加失败：本次没有业务动作，业务世界仍为空。

实际普通记录完整保存了物品、4/R-7/包装，后续请求的 DURABLE MEMORY 中也有原文。
首断点在最终回答的信息采用/完整性，不是 formation、Store 保持、检索或请求交付。
22 个 generation ID 唯一，六项链审计通过；5 CREATE、1 UPDATE、1 普通 search，无多余写入、假 saved、业务动作、控制/纠正调用或重试。

## 因果解释、拒绝规则与局限

Observed 是当前格式恢复但一条计划回答压缩掉物品；Expected 是格式、持久能力和完整后续使用共同达到原 6/6。
实际链为正确 CREATE → 新 session Store 读取 → 完整记录进入 HTTP → 回答保留三个列举字段、遗漏物品身份。

至少两种解释：通用 format/language/length 说明可能改变回答压缩侧重；或这是 Host 普通输出变化，问题点名三个字段使其只回答这些字段。
单次确定性暴露样本不能把新遗漏归因于该段，也不能把 BRIEF 恢复认定为 JSON 外壳歧义的唯一因果证明。
更简单的观察是：**程序能够交付正确材料，Host 仍可能漏掉验收要求中的内容**。

通用回答完整性表示或更清楚的任务覆盖定义可作为未来研究问题；此轮不再扩写提示或重定义 rubric。
[R2 协议](MILAI_NEXT_DEVELOPMENT_V4_B_R2_PROTOCOL_20260928.md)已规定任一完整回归退化即拒绝唯一候选，停止同义措辞/anchor 变体。
最小下一实验为 **本轮无追加实验**；进入 F9 总体判断，保留源码和失败，不改 Store、不补用 R1 的成功答案，不创建 C。

R2 没有新的未暴露样本、动态世界、实际旧助手冲突或检索容量瓶颈。所有 22 次仍走 all。
来源标签、临时引用和程序审计的工程正确，不等于已建立真实消费可靠性。完整方法稳定条件未满足。

## 成本和复现

| 成本段 | Generation calls | Input / output tokens | Total | Embedding calls / tokens |
| --- | ---: | ---: | ---: | ---: |
| 形成 | 8 | 10,685 / 351 | 11,036 | 4 / 179 |
| 维护 | 4 | 5,535 / 190 | 5,725 | 2 / 60 |
| 使用/负例 | 10 | 11,487 / 323 | 11,810 | 1 / 7 |
| 合计 | 22 | 27,707 / 864 | 28,571 | 7 / 246 |

比 R1 多 958 generation tokens（3.47%），比旧 v3 B0 的同六例多 44.65%；调用数均为22。
embedding 正文变化不能称为压缩效果。先行两消息的 2,224 tokens 已包括在本轮合计，不另计一次。
无错误/未知 usage/容量拒绝；失败回合照常收费。

HTTP wall 10.089 秒；进程 wall 34.709 秒，user/system CPU 34.407/2.798 秒。
43 次普通记录观察 6,328 bytes；18 次 namespace guard 72 bytes；15 次 checkpoint 读取 21,624 bytes；
15 次程序 audit 18,108 bytes，无额外 checkpoint 读取。路由核算 wall 0.785 秒／CPU 0.817 秒为 inclusive，不重复加内部费用。
物理 I/O、普通写入 CPU、GPU 和货币成本保持 unknown。

连续账本从 2972／3,756,920／20,991 到 **2994／3,785,491／21,237**，结束 SHA
`e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`。
两次 B 累计新增 44 generation calls／56,184 generation tokens、14 embedding calls／508 tokens，R1 没有被清零或替换。

执行 freeze SHA `593190a15d7be29b2d4be6ee3d532b6505a63fc2832727978a27a9e1ef6a4ffd`，绑定上述方法、158 项源码、
六份原输入、两份 rubric、固定 temporary-first 顺序、pilot 停止规则、参数、工具、隔离身份及连续账本。
复现入口和私密 DSN 环境注入方式沿用 [R1](MILAI_NEXT_DEVELOPMENT_V4_B_R1_RESULTS_20260928.md)，使用全新 run 目录；
不得重用原 attempted 目录。原始证据 ignored，公开结果保留逐回合答案/记录及 trace/result/manifest hash。

## Reflection

| 总规划 §32 问题 | R2 判断 |
| --- | --- |
| 1 支持什么 | 明确 answer 字段合同后，此暴露临时格式例通过；普通形成/更新继续通过 |
| 2 反驳什么 | 一个格式修订通过就能推断完整方法稳定或直接进入新样本，证据不支持 |
| 3 首断点 | 正确完整材料到最终完整回答之间，物品身份遗漏 |
| 4 更简单解释 | 问题列举字段诱发简略回答或普通 Host 波动；没有唯一因果归因 |
| 5 更简单方法 | 保留普通记忆/真实工具；不以改 Store、更多 selector 或 C 自证解决漏答 |
| 6 复杂度 | 同样22 calls，tokens 高于旧 B0 44.65%，完整脚本仍5/6 |
| 7 过拟合风险 | 原失败题被再次观察，严格禁止补前缀规则、换失败题或放宽完整性标准 |
| 8 反例 | 当前前缀正确、无临时污染，但另一个完整计划回答变短，三点正确并不覆盖原完整门槛 |
| 9 决定 | 拒绝晋级，按预冻规则 Stop 本次修订循环；C/D 不启动 |
| 10 理由 | 本轮明确的完整质量门槛未过，增加控制复杂度或拼接历史成功都不能补证 |

[F9总体报告](MILAI_NEXT_DEVELOPMENT_V4_OVERALL_EXPERIMENT_REPORT_20260928.md)给出完整要求和总体结论；研究目标未达成，Product NO-GO。
