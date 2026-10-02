# v13.4 执行检查点（2026-10-03）

Goal 为 **ACTIVE**，完整 v13.4 尚未完成。已按用户指令逐字读取并保留原计划517行，从`2319401bc0c6f29142cdf139a09b22576c0da1c5`建立独立分支`feat/lab-correction-evidence-v13-4-20261003`。原文“文档交付”与旧暂停是历史状态；本次实际执行不改写旧结论。

## 已取得的实际证据

N0 已核对远端 main `95bf708b…`、PR80 open/draft及head `2319401b…`，核对本地执行import来源和R9三臂/E0 R7实际配置哈希。R9 support/read实际为legacy，不能归因于未启用的direct_support。原48项逐条补充映射，状态仍为4限定通过/27部分/1未通过/16未验证。新计划列122项，具体状态以[要求清单](../data/manifests/v13-4-requirements.json)为准，不能由本清单自证研究完成。

N1 新增四个opt-in模块：研究合同、冻结来源适配器、完整正文装包器、单次Reader runner。复用已有MemoryService、来源/版本守卫、统一账本、串行HTTP owner和持久调用准入。查询仅记研究日志，不进入冻结Source，不执行writer或业务工具。装包保留原候选顺序，完整单元放不下明确遗漏，不截断正文。该原语名为ordered_source_v1，尚不是Chain-RAG/Temporal-RAG。

**80项受影响测试通过**，其中11个新增控制；ruff、四模块mypy、活动包依赖边界通过。最终wheel/sdist中的四模块与执行源码逐字一致。独立工程复核发现并关闭了初始Source事件ID/role结构校验缺口；保留错误输出。适配器移入methods层以消除反向依赖，未放宽规则。物理DB I/O未测；记录了逻辑读次数/字节及CPU/wall，嵌套计时不相加。

## 两批真实Reader诊断

两批均为同一组人工构造的机械诊断，**不计入32历史T0，也不是泛化成绩**。每批4个自然问题，每次实际HTTP中均含3份完整来源、479 evidence tokens（上限2048），模型prompt计数与本地tokenizer误差0。8次查询事实/来源摘要均未改变。原始答案、错误、费用全部保留。

| 批次 | 唯一干预与结果 | 实际费用 |
| --- | --- | --- |
| [R0](../data/manifests/v13-4-n1-r0-results.json) | 核心信息4/4出现；3/4额外把observed_at归为更正发布/确认日期 | 4生成，2,887 tokens |
| [R1](../data/manifests/v13-4-n1-r1-results.json) | 增加通用时间字段说明；日期误归因降至1/4，但q4错误将未规定的incident格式泛化为CSV，核心信息3/4 | 4生成，3,125 tokens |

**R1未采用。** 保留R0作为初始共同Reader控制及其日期错误，不再围绕这4题反复调提示。后续T0区分档案缺证、候选漏证、包装漏证和Reader解释错误；完整证据已送达时的误解，不构成复杂选源器价值证据。Root评阅不是独立语义Judge。两批使用相同正文/问题，实际重建观察时间不同，不能声称完整请求字节完全一致的因果比较。

上述 N1 两批合计 **8 generation / 6,012 known及charged tokens / 0 embedding**。该阶段结束时连续账本为9,406次生成；历史unknown1及30,387保守费用保留，无新unknown。N1没有writer调用。源代码检查点为`9ec7c19`，R1配置/结果检查点为`57bfac5`；只在本地提交，未推送/合并。

[有限工程验收](../data/manifests/v13-4-n1-acceptance.json)只证明N1 source-reader入口。真实模型样本使用3条raw Source及空fact bank；非空record版本守卫由机械测试覆盖。不是完整G0-Integrate、原正常24/E0或产品验收。Product API/Schema/权限/Canonical与Archive未修改，Product仍NO_GO。

## T0数据与后续工作

[来源审计](V13_4_SOURCE_ELIGIBILITY.md)保留旧曝光/预留组件；source_id/hash不同不自动表示独立。已从RFC Editor官方勘误元数据和RFC index的updates/obsoletes关系预登记39个保守来源组（32主候选+7顺序备用），先冻结再读正文。[来源清单](../data/manifests/v13-4-t0-origin-shortlist.json)记录许可、排序与排除；[获取与单人适配审查](../data/manifests/v13-4-t0-acquisition.json)已完成：104/104资源（36 RFC、68勘误、6,803,322 bytes），4个浅层更正原件保留并按事前顺序补入4备用，形成32个实质更正候选。全部原文/来源视图/曝光hash核对通过。T0准入仍为0；正文复制许可不等于可自由再发布勘误语料，pre5378及格式适用范围/TBD等限制保留。正文获取不是完整T0标注，也不证明4类配额或个人对话泛化。

[单人语义审查](../data/manifests/v13-4-t0-semantic-audit.json)已检查32候选：RFC7940一条勘误所称旧值与冻结TXT不一致，RFC7970一条勘误给错节号；错误公开值保留，人工找到的正确位置只留在evaluator。JSON/CBOR/CDDL宽依赖族涉及11候选，既不自动视作同一更正，也不能宣称完全独立。多条勘误本身已复述旧文/纠正文/注释，不能强制标成需要RFC加勘误的互补任务。

## N2 问题生成之前的真实形成

按[前瞻协议](V13_4_N2_FORMATION_PROTOCOL.md)，为满足“metadata先于未来问题”，仅将一次形成子步骤从N3前移；G1之前不训练预测器、不分析T1信号。协议/config在`1cdf810`提交，实际输入与driver另存hash冻结。32候选的96份来源经真实公开捕获入口入独立bank（32 RFC+64勘误、0事实行）；Writer每次只见一份勘误，没有未来问题/答案。原RFC语义metadata保持unknown，不广播勘误字段。

[64次形成全部终态](../data/manifests/v13-4-n2-formation-results.json)：64 HTTP 200，**115,463 tokens**，0 embedding、0重试、0新unknown请求。7份通过形状和逐字quote校验，55份含非逐字正文quote、2份JSON无效；按预注册整份unknown政策保留57份失败，不修输出、不补调用。7份校验通过也不证明语义正确。所有实际wire与冻结WriterView一致，prompt计数误差0，来源/事实前后逐字一致。准备CPU/物理I/O未测，不能写成零。

v13.4累计现为 **72 generation / 121,475 known及charged tokens / 0 embedding**；连续账本9,470次生成、known 27,128,352、charged 27,158,739，历史unknown1保留。自然query仍为0，T0仍未准入。只读span入口已增加384正文token的无损query-free分段，并通过独立toy边界审查；实际关系构造及B1/B2共同候选/预算还在冻结实现中，尚不构成T0实证。

下一步先冻结段落关系映射、B1/B2/B3共同信息与K32/装包规则、B4可枚举结构控制，再建立隔离的自然问题、允许部分答案和最小充分集合标注，完成现行冻结后才运行T0。不能把整篇长RFC作为不可拆单元制造预算失败，也不能把57份抽取失败当作廉价metadata已无预测信号的T1结论。

T1真实元数据、T2 pilot、T3正式/公开迁移、最近邻原生接入、独立标注/第二家族、正式统计与论文复现仍未完成，按G1/G2等条件推进；EDM/CEP及旧48项写入/恢复义务继续保留。[持续进度](../data/manifests/v13-4-progress.json)记录完整未完成范围。

## 可追溯限制与恢复

所有原Provider日志、SQLite、构建包和文献原件保留在本工作树ignored `artifacts/v13-4/`；Git只存代码、协议、索引及紧凑结果。初次无隔离build缺hatchling后使用缓存离线构建成功；一次边界命令误扫整个Lab后以标准活动包入口重跑通过；一个摘要辅助脚本字段名过期引发KeyError，运行器自身的冻结校验独立通过，补充核验已完成且未重复模型请求。均未改写失败为成功。

回滚基点`2319401b…`；本地源码检查点`9ec7c19…`，历史远端只作基点核对。全程无需新服务或模型部署，现有服务配置未改。
