# v13.2 E0 R7 原完整分母结果

R7原24轨迹首次执行完毕：22子命令返回0、2返回1；48消息中46完成、2中断、0 NOT_RUN。Root按原rubric审查全部主张、范围、来源与授权，任务21 PASS / 3 FAIL，正常22门槛未过，并发现1处虚假持久保存答复。来源支持门槛未过，D4未准入，Product NO_GO。原失败、最终答复、账本和分母保持，没有重试、补答或拼接。Root评审属于开发诊断，非独立评分或未见泛化验证。

[实际结果manifest](../data/manifests/v13-2-e0-r7-results.json) SHA为`73af977f03805765c4278d16e438b3bc9c08154ede58700767e573e61649f8fe`。212运行文件map仍为`36338eb57ba458ceb5a02308c254d84615f1896535c6a1e1c0a802c369e798cf`；事前配置、原rubric、原3.11.13/SDK、模型route及所有历史cohort不改。首次HTTP前已核对GitHub冻结提交`b6e33011f79ebfc640e04b136cca2b2b11319c44`和draft PR79 head/body；主分支未合并。

## 原24逐条评审

| 轨迹 | 原任务判定 | 全部关键事实与限制 |
| --- | --- | --- |
| save-1 | PASS | 简短回答偏好真实保存，实际Human叶支持，最终答复与SDK一致。 |
| save-2 | PASS | 不含咖啡因的茶及饮品范围保持，真实持久保存。 |
| save-3 | PASS | 素食餐食偏好保持，未扩大为禁止所有动物制品；R6扩大失败仍是独立历史。 |
| save-4 | PASS | 大字号阅读偏好及范围保持，真实保存。 |
| recall-1 | PASS | 新进程从实际送达材料正确回忆火车通勤，维护no_change。 |
| recall-2 | PASS | 正确回忆常用Python；scope为common language，未误标偏好，no_change。 |
| recall-3 | PASS | 正确回忆通常上午会议，r1/原支持保持，no_change。 |
| recall-4 | PASS | 正确提纲先于邮件正文，原r1保持，无冗余修订。 |
| update-1 | PASS | 原ID r2茶、r1咖啡保留；四字段支持均实际更正Human叶，当前/旧值答复正确。 |
| update-2 | PASS | 原ID r2中文、r1英文保留；四字段支持均实际更正Human叶，最终当前/旧值正确。 |
| update-3 | PASS | 原ID r2公里及scope、r1英里保留；四字段支持均实际更正Human叶，最终当前/旧值正确。 |
| update-4 | PASS，直接来源FAIL | 原ID r2下午/r1上午和答复正确；改动仍只选旧上午Source，不支持新下午事实。 |
| scope-1 | PASS，直接来源FAIL | Reader实际读原Human正文，正确区分本周团队午餐与个人无固定素食偏好；writer r2只用当前问题支持复制事实及scope。 |
| scope-2 | FAIL / writer pending | 最终把平时偏好说成简短，未保留平时详细/本次演示简短区别。writer用assistant源作user_statement被source_role_mismatch拒绝，r1不变。 |
| scope-3 | PASS | 项目每晚≤800元与私人预算无记录分别回答，no_change。 |
| scope-4 | PASS | 只保留项目相对Friday，绝对日期未提供则不编造，no_change。 |
| object-continue-1 | PASS | 真实精确预订/标签一次，Tool叶卡已存；后续同对象get只读，无重做。 |
| object-continue-2 | FAIL / 中断 | 初次真实业务与卡保存；后续使用实际搜索返回的游标，却被普通检索包的分页校验拒绝，无最终答复/业务状态读取。 |
| object-continue-3 | FAIL / 虚假保存 / 中断 | 初次业务成功，但Host声称已保存时没有语义卡，后续writer提案被拒，SDK卡数0；后续实际搜索游标也被普通包校验拒绝。 |
| object-continue-4 | PASS | 真实精确业务一次，实际Tool支持episodic卡；后续get同对象已完成状态，无重做。 |
| restart-1 | PASS | 真实新进程重开持久bank，正确步骤先于例子，no_change。 |
| restart-2 | PASS | 新进程正确回忆安静会议室，no_change。 |
| restart-3 | PASS / writer pending | 新进程正确回忆少辣椒；之后唯一writer生成被截断，无actions/receipts，原卡保留，无付费repair。 |
| restart-4 | PASS / writer pending | 新进程正确回忆按项目分类；之后唯一writer生成被截断，无actions/receipts，原卡保留，无付费repair。 |

原user指令、整个断言、范围和被拒提案/实际副作用分别审查，不用关键词或成功业务掩盖失败。两个旧update-2/3在本轮的原ID、更正、历史、最终当前/旧值及直接更正叶限定门槛通过；全cohort来源、正常任务和保存门槛仍失败。R0–R6原结论与失败不升级。

## 实际搜索游标的机制缺口

两次中断的实际Host参数逐字等于显式search_memory结果的`coverage.read_more.cursor`，且原最后付费HTTP请求确实包含该游标。Root独立按原owner/namespace/request_ref/omitted_menu重算hash并匹配实际参数；不是模型猜造或截短游标。普通System包同时带有另一结果集的游标，二者身份不同。

冻结`grounded_memory.py`中显式搜索状态写入`query:<session,turn,query>`，而`selected_page_tool`只读取`packet:<session,turn>`。由此将显式结果集的正确指针与普通结果集menu比较并拒绝，是Root根据原wire/状态及冻结静态路由的机制推断。原游标guard正确拒绝了不匹配身份；下一通用修正须使解析器找到实际返回的正确快照，继续检查owner/turn/hash/Source/版本，不自动改游标、重检索、取全量或放宽guard。原calls不重放。

## 保存承诺、来源与维护

object-continue-3初次final原文包含“结果已保存，方便下一次继续。”。实际Host无语义卡提交；闭合writer混合Human/Tool叶作user_statement，Service以source_role_mismatch拒绝，维护pending，实际receipt/独立SDK均卡数0。业务预订/标签确实成功，原Source及确定性观察确实持久化；依原扩展rubric，这些不能替代声称成功保存的语义卡。此硬门槛在全部24 terminal后的Root完整离线审查才检出；发现时已无本cohort待执行消息，此后不启新真实模型cohort直到通用设计再评估，未伪称运行时提前发现/拦截。

update-4 r2只引旧上午陈述；scope-1 r2只引当前问题支持复制团队要求、个人否定和scope。共2轨迹/2提交版本直接来源缺口。模型可选真实当前或历史叶；成员/角色/hash合法不等于蕴含。四字段全为model_selected，实际显式reuse_support_from仍0；没有语义verifier、默认current、Source union或问句/案例分类。

46完成消息的维护为26 skipped_host_committed、14 no_change、2 committed、4 pending；另2中断未到维护。pending为scope-2角色拒绝、object-continue-3角色拒绝、restart-3/4各一付费writer截断。全部原pending/拒绝/失败费用保存，没有重试。四对象业务均初次精确授权一次，后续无重复reservation/complete_label尝试，实际新增副作用0；两中断对象没有完成后续业务状态查询，不称整任务成功。未观察owner泄漏。

## 冻结后检与完整费用

事前冻结的SDK重开、实际请求检查、完整分母collector三个原命令均返回0，前后源码和账本不变。Root独立只读SQLite Store SDK重开24bank/471实际items，与各bank最后原receipt一致，DB SHA不变、0记忆mutation。151 Host请求和171 Host/writer通信逐条核对实际catalog/guide/feedback、材料版本/叶/owner/hash和完整请求成本；普通metadata＋body＋reference最大2048/max6，issues0。48行包含两中断前已实际送达请求；这个机械PASS不表示中断有最终答复或语义任务通过。

R7新增171 generation / 1,222,370 known及charged：Host151 / 1,085,579，writer20 / 136,791；52 embedding / 20,202。原trace与连续账本差额精确匹配，新unknown0，失败/截断和所有重复材料仍计费。R0–R7累计新增1254 generation / 5,446,707 known、487 embedding / 203,655。

原连续账本末SHA`374fcef4dd8a3082d352e2e936f68601edd65ba142880655349cfc68e652b15f`，累计9200 generation、25,757,358 known / 25,787,745 charged，历史unknown1 / 保守30,387不变；embedding920,843 / unknown0。没有成本下降、美元/GPU小时、单因素收益或泛化声明。

失败后的[primary论文/项目与中文反思](V13_2_DESIGN_LITERATURE.md)继续归档，已采用原则和未采用候选分开。下一候选先修正实际结果集分页身份与真实已知读取错误的有限反馈；未知程序/权限/CAS/预算错误不广泛吞掉。共同HTTP owner闭包、D4同能力reader/cache/形成/B6/写权限和D5独立正式门槛仍需执行。完整原589行计划ACTIVE，48项验收分母保持，Product NO_GO。
