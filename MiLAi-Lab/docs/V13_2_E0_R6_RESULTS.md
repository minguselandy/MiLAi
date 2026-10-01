# v13.2 E0 R6 完整开发诊断

2026-10-01。[完整逐条结果](../data/manifests/v13-2-e0-r6-results.json)为 **21 PASS / 3 FAIL / 0 UNKNOWN**，原24分母不变，22/24门槛未通过。45消息完成、1中断、2未执行；24父级子命令均结束，其中23返回0、update-1返回1。所有45最终回答关联原HTTP回包；没有补试、补答案或与R0–R5拼接。Root复核不属于独立Judge或未见泛化验证。

实际运行遵循[事前冻结](V13_2_E0_R6_FREEZE.md)：211运行文件，map `8c466d3ca839ea0db5aaa722ae20ffa6c11460c8f1d5c068e53921b6cb6551ce`；input SHA `f74b5dd8bf30fb4045c4df4140c5464c724f9f9c4cb729dd86c3324734891f40`。冻结公开提交6dfa313，原24/48与rubric、Host/writer基础提示、Host12/writer1/repair0、2048/max6、bank_prefix及两既有模型不变，仅启用默认关闭direct_support_v1联合profile。共享admission仍legacy，不能据此宣称四臂共同额度或HTTP owner闭包通过。

## 原分母的逐条判断

| 轨迹 | 结果 | 原实际证据与边界 |
| --- | --- | --- |
| save-1 | PASS | 简短偏好真实提交，原user支持，保存回执真实。 |
| save-2 | PASS | 不含咖啡因的茶正确保存。 |
| save-3 | FAIL | 实际卡片和最终答复把“素食者”扩大为避免所有动物制品；原user未提供更强限制。存储确实成功，但所有主张/范围审查未通过。 |
| save-4 | PASS | 阅读大字号偏好正确保存。 |
| recall-1 | PASS | 新进程从实际HTTP材料正确回忆火车，writer不改。 |
| recall-2 | PASS | 正确回答常用Python；scope.type=preference对“常用”的描述有偏移，另列metadata语义限制。 |
| recall-3 | PASS | 正确回忆通常上午开会，不改卡。 |
| recall-4 | PASS | 正确保留提纲先于正文；writer冗余r2四字段完全不变，显式选原user叶，有支持但无必要，不是显式reuse_support_from。 |
| update-1 | FAIL / INTERRUPTED | 初次形成错误反复至12生成上限，无卡片/最终回答；更正和查询NOT_RUN。 |
| update-2 | PASS，来源门禁失败 | 同IDr2中文、r1历史与最终当前/旧英文正确；r2只引用旧英文源，query r3只引用问题。 |
| update-3 | PASS，来源门禁失败 | 同IDr2公里、r1英里与最终当前/旧值正确；改内容及scope只引用旧英里源，query不改。 |
| update-4 | PASS，来源门禁失败 | 同IDr2下午、r1上午与最终正确；更正只引用旧上午源。scope误装source_refs对象，结构允许不等于适用范围正确。 |
| scope-1 | PASS / 维护pending | 正确保留本周团队午餐和个人无固定素食偏好，最终不推长期个人偏好；writer截短/猜造来源ID被拒，原r1不变。 |
| scope-2 | PASS，来源门禁失败 | 最终和正文保留平时详细/这次演示简短；query r2只引用问题。 |
| scope-3 | PASS，来源门禁失败 | 最终区分项目每晚≤800元与私人预算无记录；query r2项目事实/无记录判断只引用问题，未编私人预算值。 |
| scope-4 | PASS | 保留项目相对Friday、无绝对日期，最终不猜日期。 |
| object-continue-1 | PASS | 精确真实预订/标签一次、工具源保存；后续同对象只读，不重做。 |
| object-continue-2 | FAIL，副作用0 | 已读到created后仍调用complete_label，违反“不重做已完成工作”；业务层返回already_labeled。原预订仅一次、最终正确及world不变分别保留，不能把被拒的未授权尝试判为符合指令。 |
| object-continue-3 | PASS | 精确预订/标签一次，后续同reservation只读，无重复动作。 |
| object-continue-4 | PASS | 同上，工具string句柄来自实际Source伴随ID，未作dict类型修正。 |
| restart-1 | PASS | 实际进程退出后重开同持久bank，正确步骤先于例子。 |
| restart-2 | PASS | 独立进程正确回忆安静会议室。 |
| restart-3 | PASS | 独立进程正确回忆少辣椒。 |
| restart-4 | PASS | 独立进程正确回忆按项目组织笔记。 |

以上沿用事前rubric的全部主张/范围、原user指令和被拒提案与实际副作用分列规则；没有用“素食”substring或正确最终回答掩盖失败。没有观察到owner泄露或虚假持久保存回执；save-3的事实扩大与确实写入数据库分别报告。

## 参数形状失败与真实送达审计

update-1第一份Host提案缺field_support；其后11份把top-level kind/basis等实际值换为支持对象，反复生成且未成功提交。12次真实HTTP均200，共94,128已知tokens，随后准备第13份材料，在实际legacy Host额度reservation处拒绝，未dispatch。当前生成grammar仅约束action外壳、arguments仍自由object；完整工具参数schema在prompt及执行前验证。仅返回ValidationError.message缺字段路径，是Root结合真实wire与源码的机制推断，不是provider忽略完整强约束schema的证明。

事前冻结后检原始结果保持失败：只读SDK检查通过，wire报告INCOMPLETE_OR_FAILED后原postcheck停止。三个issue全部属于update-1：末次准备无显式HTTP/拒绝trace，两个后续receipt缺失。另以原collector补充完整分母，单独记录命令/前后源码及账本不变；没有修改原后检脚本、补造拒绝事件、重跑模型或把缺失行改为PASS。

150次已观察Host HTTP均完成独立材料检查，包括中断前12次：实际ordinary联合tokens最大2044、至多6条，选择ID/次序与原构造inventory一致；完整field_support、trigger、当前/历史版本/hash与公开Source实际归属逐项对照实际SDK数据。45完整消息送达通过；另3行仍UNVERIFIED。最后未dispatch准备通过原cap文件12、错误回执、trace及冻结bridge的project→reserve→client顺序独立佐证，明确标为推断且不称实际送达。

Root在独立只读SQLite Store SDK重开24bank，读取458原始items，全部与最后实际receipt一致，DB SHA前后不变、0记忆mutation/新增模型HTTP。保存整个实际cohort文件hash闭包。SDK一致和field-map解码证明结构与持久化；不证明来源蕴含、全部选中Source正文已读或模型语义正确。

## 支持来源与维护结论

三条完成更正都修订原ID并保留历史，没有新偏好副本，当前/旧值回答正确；但更正改动只选旧陈述，直接来源不支持新值。**两个旧update的支持更正及完整修复门禁失败**。此外update-2 query、scope-2 query、scope-3 query三版只引问题。共5轨迹/6已提交版本存在直接来源缺口，原真实更正源与历史仍保留，不能用成员合法替代完整支持。

实际维护45完成消息为26 skipped_host_committed、14 no_change、4 committed、1 pending；另1中断未到维护、2消息NOT_RUN。4 committed含recall-4的支持但冗余修改及3问题源修改。scope-1原截短ID拒绝和pending保持。新版本field_support均为model_selected；真实样本没有执行显式reuse_support_from，工程等值复用检查不能重标为真实模型复用成功。

四对象初次工具事实均真实保存，后续原卡/叶不改；一个重复标签尝试被拒、实际副作用0。新profile的触发/支持职责、Host跳过、伴随string ID及表示/正文分配是联合因子；本轮成本和任务结果不证明单因素收益、方法优越或泛化。

## 完整费用与下一步

R6新增169 generation / 958,878 known tokens：Host150 / 856,495，writer19 / 102,383；45 embedding / 19,279。所有失败、冗余、重复送入材料成本保留，trace与原连续账本差额一致，新增unknown0。R0–R6累计新增1083 generation / 4,224,337 known，435 embedding / 183,453。

原连续账本R6末SHA `73c437acc68e2e6e7a04b0d9ecb9ff3353936769f0d9c7bec4d40566dcbd2df1`；累计9029 generation、24,534,988 known / 24,565,375 charged，历史unknown1 / 保守30,387保持，embedding900,641 / unknown0。费用不作美元/GPU小时或下降结论。

失败后的[原方法资料和总结](V13_2_DESIGN_LITERATURE.md)已保存：新增JSONSchemaBench等五个检索论文原件及三个固定官方project参考，采用方法与未采用候选区分。下一通用候选先明确实际字段值与field_support关系的完整合法shape，提供原validator字段路径/keyword/schema依据反馈，由模型选真实支持；不强选当前源、不补造值/来源、不增加语义verifier或writer重试。共同HTTP owner闭包及D4 reader/cache/形成/B6/写权限仍需独立工程。D4未准入，Product NO_GO，原完整589行计划ACTIVE。

结果SHA：`90809225e5e0a6dfbc87e025ee32fd0b4cfe846fde49bff0ecc22d961a330838`。完整原回执/trace/失败后检、只读回读、补充collector和逐条Root审计在ignored `artifacts/v13-2-development-r6/`，历史R0–R5保持。
