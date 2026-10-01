# v13.2 E2 R9：全部首尝试与失败保留

15 条曝光开发轨迹、45 条公开消息全部完成首尝试；每条实际最终答复、回执、Source、HTTP、连续费用和 Root 显式复核保留。15 次修订均命中原 ID、改对核心偏好并绑定真实更正来源，但这不证明完整范围保真或首次提议正确。查询 Reader 的 Root 开发诊断为 13 项 scoped 正确、1 项语言范围表达 partial、1 项历史回答错误；查询后形成有 8 次不必要提交、1 次错误提议被拒、6 次 no_change。

**E0 仍 NOT_PASSED，D4 仍 NOT_ADMITTED，Product 仍 NO_GO，完整计划 ACTIVE。** Root 复核不是独立 Judge，正确读者答复不能遮盖后台写回的来源支持、重复或范围丢失。

[机器结果与全部原件引用](../data/manifests/v13-2-e2-r9-results.json) · [模型前冻结](V13_2_E2_R9_RUNTIME_FREEZE.md) · [原计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_2.md) · [资料中文总结](V13_2_DESIGN_LITERATURE.md)。

## 实际执行身份

执行提交 `4ca2204732d0ea238e53fa6fc751d5de7bc80da9`、runtime SHA `aa1f4ae7fd3bcc8e11e0361f2099d66a07d84c360dcb865b9188ce2b307ce878` 在第一次模型请求前已在 GitHub/PR79 精确核对。原三接口只保持候选合同与来源回链差异；共同参数说明 A、有界交付和真实保存回执启用，support/read legacy、B legacy、C 禁用。原 Python/SDK/Qwen/bge 路由、2048 材料预算、12 次 Host/output4096/repair0、after_host_final_v1 与形成节奏不改。

216 runtime、396 tests、323 configs、539 tools 的完整 SHA 映射在45个实际父进程前后及整体审计中均不变。45 个离线输入门禁另存，不能算45个实际样本。所有实际生成和 embedding 仅 Root、并发1、同一既有连续账本。普通语义错误与实际 owner/hash/Source 泄漏、假保存成功、gold/未来/offline 输入硬停分别判断；本轮没有触发后者。失败没有重跑、退费、删卡、补绑定或改写最终答复。

## 分开看修订、读者和后续形成

每组两项边界为初次保存和修订，第三项为查询；下列数字是原实际消息 index。所有修订的核心格式/时间和原 ID 正确；scope/频率保真与错误提议限制另列。

| 曝光开发事项 | 接口 | 原消息 | 查询 Reader | 查询后的形成 |
|---|---|---|---|---|
| 语言偏好 | 旧 query | 0/3/6 | scoped 正确 | no_change，原修订来源保持 |
| 语言偏好 | Source 回链 | 1/4/7 | scoped 正确 | r3 仅绑定问题，Source 支持失败 |
| 语言偏好 | 句柄 patch | 2/5/8 | scoped 正确 | r3 仅绑定问题，Source 支持失败 |
| 距离单位 | 旧 query | 9/12/15 | scoped 正确 | no_change；12 完整 update 清空结构 scope |
| 距离单位 | Source 回链 | 10/13/16 | scoped 正确 | no_change |
| 距离单位 | 句柄 patch | 11/14/17 | scoped 正确 | no_change |
| 英语指令要求中文保存 | 旧 query | 18/21/24 | 格式 scoped 正确 | no_change；18 实际英语卡未满足中文保存 |
| 英语指令要求中文保存 | Source 回链 | 19/22/25 | 格式 scoped 正确 | r3 仅问题 Source；19 实际英语卡 |
| 英语指令要求中文保存 | 句柄 patch | 20/23/26 | 格式正确、语言范围表述 partial | 真实中文卡的 r3 仍仅问题 Source |
| 同名不同项目 | 旧 query | 27/30/33 | scoped 正确 | 不必要 update 被 target_not_unique 拒绝，pending |
| 同名不同项目 | Source 回链 | 28/31/34 | scoped 正确 | 真实新增重复海风卡，仅问题 Source |
| 同名不同项目 | 句柄 patch | 29/32/35 | scoped 正确 | 真实新增冗余曙光历史卡，仅问题 Source |
| 纠正与否定范围 | 旧 query | 36/39/42 | **历史回答错误** | no_change，旧 r1 在库但未消费 |
| 纠正与否定范围 | Source 回链 | 37/40/43 | scoped 正确 | r3 丢失本季度/其他会议排除，仅问题 Source |
| 纠正与否定范围 | 句柄 patch | 38/41/44 | scoped 正确 | 同正文/scope重复 r3，仅问题 Source |

7/8/25/26/34/35/43/44 共8个持久提交仅引用当前询问 User；其 ID、owner、角色和正文 hash 合法，询问本身却不支持重写的偏好事实。存在引用、成员合法、成功存储、语义支持是四项不同结论。6 次为原卡额外修订，2 次为新重复/冗余卡；旧真来源仍保留在原历史中，不能据此称当前新版本有真来源。

27 两条带无支持业务 fields 的初始提议被拒后，模型在同一原 ReAct 过程自行合法创建两卡。31、39 首次编造不存在 Source ID 被拒后自行读取真实当前来源；40 首次引用旧初始来源，被 current_boundary_source_required 拒绝。39 在合法 r2 后另提议 label_status:confirmed，被业务字段守卫拒绝。全部6条错误 Host 提议与费用保留；守卫拦截不等于模型首次正确，也不是 Root 自动修复。33 Writer 又把 record ID 填进 object_ref 而缺 id/query，真实拒绝后保持两卡。

12/39/40 完整 update 清空结构 scope，部分事项范围仍在正文；不宣传结构 scope 保持。36 英文 JSON 卡未显式保留“通常”。39 未显式保存“不是周二/不适用其他会议”否定；41 的真实 patch 保留本季度和设计审查、增加其他会议排除。43 后台 r3 的范围流失是真实终态，不能以形成前正确 Reader 或旧 r2 仍在历史中掩盖。

## 实际交付与历史消费

16/17 先前 tool DTO 或首次 packet 中有截断，随后实际 HTTP System 材料已包含完整当前公里与历史英里；不能仅按旧 DTO 判断未送达。42 的实际 HTTP 只有完整当前 r2、可用 history index 和截断 Source 前缀，没有旧 r1 正文；Host 只读当前，又把原安排误说成周四下午，SDK r1 周二上午始终在库。44 初次真实 System 材料已经送达完整当前 r2 和旧 r1、scope 排除，Host 不再额外读 Tool 即回答正确。这是具体交付与消费诊断，不证明外推收益或 Attention 因果。

42 的第三次付费 writer 重复错误答复/no_change，不能替代第二次生成的实际 Host final。完整审计对148个实际生成请求保存材料投影、capacity、usage及形成前 Host final 位置；所有实际HTTP原件保留，tool DTO 不被当作 HTTP 等价物。

跨语言按真实正文/表示记录：18/19 虽 scope 写 Chinese 或答复给中文示例，仍保存英语正文，不能列作英文源→中文卡。20 确实生成中文卡，并在23以英语更正保持中文原 ID。中文来源生成英文正文/JSON和混合字段的各样本分别保留；模型自由形成的实际语言不由输入请求替代。五个已曝光事项只有15条依赖轨迹，不作独立新来源、跨模型验证或单因素 R0→R9 归因。

## 真实费用与 SDK 终态

| 接口 | 生成请求 | 生成 known tokens | embedding 请求 | embedding tokens | 查询后形成 tokens（已包含在生成总计） |
|---|---:|---:|---:|---:|---:|
| 旧 query | 51 | 291730 | 20 | 8072 | 19009 |
| Source 回链 | 48 | 288516 | 21 | 7983 | 19548 |
| 句柄 patch | 49 | 319137 | 22 | 8260 | 22121 |
| 合计 | 148 | 899383 | 63 | 24315 | 60678 |

生成输入888705、输出10678。查询后形成15次/60678已包含在148/899383中，其余Host133次/838705；失败提议、no_change和所有实际追加读取均计费。新增Unknown0，历史Unknown1及30387保守计费不退款。账本前SHA `8547f1ef8d32455ad121799e5c0132a3de24a992067408c4fbbb73d2fb199ca5`，本轮后SHA `991a568c47d3cdb2ad23b658565729331b876cc1c33e837e1f7f89e0405c136a`。

R0–R9 开发调用累计1452生成/6696226 known、590embedding/247457。该累计包含各原失败与旧配置，不是统一比较表。当前连续账本 generation9398、known27006877、charged27037264，embedding known/charged964645；旧历史连续保留。

15个最终库实际安装SQLite SDK只读新进程打开，共347 items、20当前卡、41历史版本；实际45 User/45 assistant Source角色保持，数据库hash和账本不变，0模型HTTP/0存储修改。机械检查验证真实source binding/owner/hash，不替代自由语义支持评审。

## 已保存的方法反思与下一门禁

[资料索引与总结](V13_2_DESIGN_LITERATURE.md)保留EAL/Hindsight/Mem0的证据与形成边界、JSON有效与语言意图、opaque引用的形态与实际身份、Lost in the Middle/Hindsight的历史保留—送达—消费区分。四次R9 primary复查的原浏览、旧完整PDF/HTML/代码、UTC/版本/hash、中文反思均归档；当前19论文/21项目参考组、875文件/191本地链接核验0问题。旧 unversioned 原件不改成固定版本；一个首次browser完整DTO本地未保留、一次Root archiver执行前语法失败明确保存，不补造at-time映射。

通用候选仍为真实公共事件/回执到引用的明确绑定、一次有界公共材料、真实版本/范围与遗漏、显式计费追加读取、模型自行选择 no_change。当前问题不应借已检索卡或 Host 答复升级为新的用户事实；ID存在不证明内容支持。先排查未真实送达的历史，再讨论消费不足，不按案例/题型/语言路由、不建语义判真平台、不自动再读/修补/重试/退费/改最终答案。候选均不是已证明收益。

现有Source共同能力工程另在隔离树、未读Root材料、无真实模型HTTP；它不构成本轮来源语义问题的修复证据。接入须独立有限验收与另立冻结。E0正常24/直接修复与原条件工作仍未完成，不能据15/15核心原ID修订或有限SDK控制晋升D4。

全部原首尝试封存：1069文件，0个symlink元数据；index SHA `374f06ef4b422409ea9d189e24438487e92c65e97f4c709f666d71f384f7091f`，seal SHA `dcc00cb9f5b7a7d8e470a483e8da8dc33d9f0b73aa8088539b2874345e51b782`。后续GitHub发布记录在该不可变root之外追加。
