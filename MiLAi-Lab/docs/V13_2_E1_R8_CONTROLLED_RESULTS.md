# v13.2 E1 R8固定观察流：完整16边界与原失败

16个首尝试边界都已结束、逐边界Root审查，没有重试。Field的4个首次形成中3个真实提交、1个pending/effect none：模型的字段支持选了Human与tool叶子，外层Source集合漏Human，被原guard拒绝。后续4个查询边界均no_change，保留首失败而不补造原卡；派生8边界0生成，4库最终保留16个原操作与lookup的真实字面观察。进程完成16/16不表示形成4/4通过，固定流没有自由Host最终回答。

| 固定格 | 首形成（两场景） | 查询边界 | 最终记忆 |
| --- | --- | --- | --- |
| Field自主读取 | 1提交 /1pending | 2 no_change | 1条语义卡，首失败库仍0卡 |
| Field预取 | 2提交 | 2 no_change | 2条语义卡 |
| 派生自主读取 | 0生成，4字面事实 | 0生成，保留操作与lookup | 2库共8字面观察 |
| 派生预取 | 0生成，4字面事实 | 0生成，保留操作与lookup | 2库共8字面观察 |

实际SDK另开8库，175个原始item、3语义记录、16字面观察和32个Source与原终态/选中工具literal/owner/role/hash核对；全部数据库hash保持，0额外模型请求。Raw Store的_v13_1.current对应Service read的value，不能把raw包装直接当DTO。Root早期错认record key前缀/原SQL列/整个包装的三次审计失败及parent因缺review拒绝后续调用保留，最终正确SDK核对通过；缺失的当时完整maps不倒补。这些不是模型或Source实现失败。

固定流实际计费8次writer生成、60695已知token；32 embedding、13780 token，逐请求/逐父进程原账本链/总delta一致。新增unknown0，原历史unknown1与保守30387保留，无退款或新0账本。现账本9208生成、25818053 known /25848440 charged，embedding934623，SHA63834ce2。所有失败、未改变请求和重复schema/材料费用包含在内。R0–R7全部保持，连同本固定流累计增加1262生成/5507402 known、519 embedding/217435；自由Host尚未计入。

两个曝光场景、固定顺序与共同工程profile、Field原manual提示/形成/观察差异保持。各库真实namespace/source ID/时间不同；相同公开Source正文hash和实际业务回执相同，不称完整prompt逐字节一样。两种固定读取都由工程入口启动，不证明自由Host读取选择、任务收益、独立评分或泛化；不得仅凭本表宣称预取或投影有因果优势。这里未观察到模型提出的两有限字段字面冲突，1次来源成员拒绝单列，不能人为注入字段错误当自然失败。

失败后复查已存JSONSchemaBench v3，并保存官方2020-12结构/conditional说明及全部返回论文候选；结构合法与来源集合关系分开。通用候选是明确逐字段叶子与外层选中集合、原basis-role/hash/CAS关系，不自动union/推断Source或新增paid repair；尚未应用，不修改R8freeze。2候选复用、2新候选完整PDF/摘要/中文范围留存，均未采用方法或迁移分数。资料现19论文/20项目参考组/829独立核验文件/176链接/0问题；原归档目录重复错误和诊断print失败保存。[资料与原文索引](V13_2_DESIGN_LITERATURE.md)。

[完整16行及SDK/费用证据](../data/manifests/v13-2-e1-r8-controlled-results.json)，[原运行freeze](V13_2_E1_R8_RUNTIME_FREEZE.md)，本地原件artifacts/v13-2-development-r8/。接下来是事前冻结的8条自由Host轨迹/16消息，仍逐消息审查、保存原响应/费用，硬停止受影响运行；本报告不是自由Host结果。E2/E0及D0–D5条件要求继续，原48行状态不变，完整计划ACTIVE/E0 NOT_PASSED/D4 NOT_ADMITTED/Product NO_GO，回滚main95bf708bfd8aac9f7855485166e3bf739928b949。
