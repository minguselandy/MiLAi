# v13.1 首批六故事 R1 结果

日期：2026-09-30。状态：TERMINAL_DEVELOPMENT_NEGATIVE_USABILITY_RESULT。
完整规划仍ACTIVE，P1可用性门槛未满足；P3–P8未执行完毕。

## 身份与真实链

[source/input/cost完整核查](../data/manifests/v13-1-d0-six-stories-r1-results.json)。
源码199文件，manifest SHA256 `da7705e5f35a1e316040f2a7c340ed69d75a987fdeea24a5fde994563e4f0c6b`；
输入freeze SHA256 `becf42ee83c506648c294ad7b2c251c1a03c148822ebc09c7e24b6386bcf81d2`。
实际Qwen3.6-35B-A3B-FP8/7860/JSON-action/temp0/thinking=false/4096输出/12调用每消息/并发1。
唯一变量是opt-in服务，旧默认未改。当前检索明确为raw_keyword；不是dense或算法优势比较。

6故事/12消息全部终态；每条消息由独立进程重开同一SQLite SDK Store/checkpointer/world/journal。
全部进程退出后，另一个真实进程3436322又通过公开SDK重开六个Store核对记录和来源owner。
这证明持久链路可用，不能替代模型内容正确性。无Model/DB/服务部署，无Product变更。

## 完整结果与首断点

| 故事 | 原冻结验收 | 最早断点/限制 |
|---|---|---|
| 保存 | PASS | 原始用户偏好、Host提案、提交和独立进程读回一致 |
| 召回 | FAIL | 正确偏好已提交；无空格中文query未匹配原文，真实检索返回空 |
| 更新 | FAIL | 用户明确更新，Host提案仍create新卡；无版本替换。后续只检索旧卡并回答旧值 |
| scope | FAIL | 团队/本周卡和完整原始否定消息都已交付；reader把当前问句误当个人偏好陈述，随后错误正文实际提交 |
| 对象继续 | PASS，同时wrong proposal1 | live query已显示label created，Host仍调用complete_label；API返回already_labeled，无新效果。不能藏掉该错误提案 |
| 重启 | PASS | 新会话和新进程召回此前保存的格式偏好 |

合计3/6开发故事通过。原计划24例中只运行首6，另18为NOT_RUN，不能报告22/24或所有用例成功。
wrong proposals和wrong effects分别记账；当前对象故事0重复预订、0新错误效果不等于0错误提案。
无observed跨owner暴露和虚假持久化成功回执；这不证明任意工作负载的权限正确性。

Field-grounded具有机械反控，但实际对象记忆提案fields为空，回执正确标为unchecked。
因此真实R1没有验证两字段绑定减少传播。自由正文未验证，scope错误被保留而未事后修正。
Ref-only独立条件尚无真实行为对照，不能把机械差异说成Agent效益。

## 验证与成本

[工程证据](../data/manifests/v13-1-engineering-results.json)：最终服务/完整Agent MockHTTP16通过，
legacyCRUD/MCP9通过，受影响architecture/boundary/source217通过；mypy6文件、Ruff、198源码
测试矩阵通过。初次2项服务测试失败、9项Ruff错误和CI登记drift全部保留，并记录实际修正。
没有反复运行 broad suite；未运行Postgres/CAS、真实三崩溃窗口、正式矩阵、远端CI或不必要build。

R1全部实际HTTP与原ledger增量逐项吻合：+28generation/+35132 generation tokens/+0embedding，
Judge0、unknown0。连续累计6173generation/11442218 generation tokens/416930embedding tokens。
ref绑定的额外公开discovery已计lookup/wall/cpu；每消息wall/cpu和DBbytes留存，但完整Store逐操作
I/O记账未实现，明确属于缺口。没有把token差称为美元/GPU小时节省。

## 反思与下一最小区分实验

召回已唯一定位到字面检索分词：字符串split把完整汉字query当单一长词；不会匹配同义上下文
含共有子词的正确卡。优先做通用Unicode词元/汉字片段检索改进，不加案例词典、embedding免费
写入、更多writer或Attention。冻结bank/query做零模型前后检索反控，再用同一bank的独立新进程
reader比较；不把重写bank与检索改动混合。

更新最早在Host选择create，而非Store丢失；scope最早在已交付正确证据后的理解/新提案。
二者须单独冻结交互/工具指令比较，检索改进不能被声称修复所有语义错误。保护层的来源存在性
只说明问句是真的输入，不能证明问句中的命题是用户确认的事实；不扩张成免费自然语言verifier。

固定：原6故事、Host模型/参数/节奏、source/owner、业务合同、形成权限和连续账本。
否定条件：相同bank/query仍不能检索，或正确卡已交付但仍答错，分别否定分词解释的充分性。
费用：先零模型固定输入检查，reader有限调用并全部记账；新版本另有身份和结果。
旧R1失败卡、原提案、world/checkpoint/source/input与全部成本保留。当前未宣称可用性、论文增益
或Product发布门禁通过。
