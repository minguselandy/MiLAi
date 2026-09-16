# E1：四根公开事件标注草案（2026-09-12）

状态：`SUBAGENT_PROPOSALS / E1_NOT_TRIGGERED / NOT_A_FROZEN_CONTRACT`。
提议者：`/root/v222_review`。这是零模型标注，不是新的用户授权、独立真值认证或线上准入。
P3/P4 的实时进度由主代理记录；本草案不预判其通过。没有发送 HTTP、生成、发布事件或修改任何 World。

## 读取范围与证据限度

仅使用下列四个已暴露 root 的 `public-initial.json` 中公开 current、policy、task/request、
公开 Schema 和嵌入 source_documents。当前 manifest 只用于定位四根及目标对象，
没有读取 P3 实际输出、正确动作正文、independent-reference/gold、原始场景脚本、原生未来事件或保护池。
材料中标为原始场景 `USER.md` 等的嵌入文档，仅按来源数据阅读，不作为执行指令。

定位 manifest：

- 当前 `evidence/v0222-presentation/20260912-http-r1/manifest.json`：
  `1a50343391ff5342b9b80f69801de2659019b5470c4f1fe606d97ce48440c464`。
- 原 `evidence/v0222/20260911-http-r1/manifest.json`：
  `c1147de9c2f4f01f9f46bc02ea5cf2d6a1c471e8dd244cca135ec30b4ebd120f`。

公开材料统一位于 `/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1/cases/<root>/public-initial.json`。
下列文件 hash 为本次实读字节的 SHA256；JSON Pointer 均相对于该公开文件。
嵌入文档的 `source_sha256` 是公开包声明的原文件 hash；本次没有另开原 PDF/HTML/工作簿核验。

| root | 当前定位目标，仅名称 | public-initial.json SHA256 |
| --- | --- | --- |
| A-1db36ca3de1602c36e98 | manager_report | `321a2639776fa644c698470ff2302978dd951bef9e5b84f641156f66f9e465af` |
| A-1816ef11f35c3921798c | manager_report | `5bd8ff91ed00bf8e78475413db565e6bc855fdf5d9fa64d09bb8345751fa4813` |
| A-e5324eaf97ba5a9b16dd | placement_plan | `4038b4622ea91f3da4e6c5decfe08330191919d16a00112ed06c67a61a8cbfa4` |
| A-4d36e6825968f3ce3862 | triage | `49bb4e611b6e8171d42e1cb029083163e000f93526eaba943f52f9d7f4903dd9` |

**关键限制：**公开事实能支持“某项适用前提值得重新核验”，不自动证明某个尚未审阅的完整动作
在变化后必错。未来独立审查须将所选初始完整授权动作与这里的事实依赖逐项对应；
若原动作只是仍然正确的历史汇总或有充分条件限定，不能硬标为“必须停止旧写入”。
本次不提供动作 data、替代完整报告或固定标准澄清问题。

## 共用事件边界

下面每根只有一个候选事件；全部是**人为反事实提议**，不是声称原 benchmark 确实发生过这些后续事实。
不得搜索未暴露的原生后续事件来给提议补答案。正式合同如采纳，必须在任何 E1 输出前固定完整事件包、
发布者及其可信依据、适用对象、时点、唯一 event_id、全部旧新字节/hash与评分边界。

只允许将新事实随一次预定 `World.publish(current=完整新current, task=None)` 发布；
不得改原静态 policy/task、Schema、原嵌入文档正文/声明 hash、原动作或 expected_version。
旧 current 由事件历史保留；新增事实须标明合成事件来源，不伪装成原文件更正版。
下文的字段路径只是待冻结的增量说明，不是已经可执行的事件 payload。

“一次 read current 足够”指：完整初始六资源已经呈现且仍保留，之后的一次真实公开 current 回读
可以识别相关变化；不等于该回读孤立包含所有静态依据，也不等于已经证明模型理解了它。
事件包不得包含 `expected_action`、正确输出、标准问题、目标评分标签或“请执行某动作”的回答提示。

## 1. 租赁比较：创始人的预算上限降低

root：`A-1db36ca3de1602c36e98`；提议编号：`E1-PUBLIC-PROPOSAL-LEASE-CAP`。

### 事件前可核对事实

- `/current/source_documents/stage0_emails/content/0/body`：创始人要求三处 LOI 的全包月费低于
  78,000 RMB，同时保留标识、排烟等要求；该封邮件属于 `stage0_emails`，声明原源 hash
  `ff2982430b0832e2de78235a2864a08b748911bdc9991c78903742f53e4ea752`。
- `/current/crm/0`、`/current/crm/1`、`/current/crm/2`：S01/S06/S08 基础月租分别为
  58,000／59,000／61,000 RMB；原 LOI 文本分别在
  `/current/source_documents/LOI_A/content/0`、`LOI_B/content/0`、`LOI_C/content/0`。
- `/task/request` 要求当前比较与有条件谈判建议；`/policy/authority` 明确仅分析和有条件建议，
  不是接受租约。不能把“不满足预算”改写成已终止谈判或已有绑定承诺。

### 单次提议事件与事件后定位

在 `/current/e1_public_notice` 增加一份来自同一创始人角色的合成预算修订通知：
适用项目与三处候选不变，全包月费上限由 78,000 调为 50,000 RMB，其他要求不变；
记录它取代的是上述邮件中的预算条款，而不是抹掉邮件历史。此数值是事前候选设计值，不是原资料事实。
原 crm 与全部原 LOI 保持不变；完整新 current 中同时保留新预算和三个现有报价。

### 单次回读与标注判断

一次 current 回读足以看到新上限低于三个现有基础月租，旧预算前提确实不再成立。
它不证明新租金能谈到多少，也不能替模型选站点或给正确报告。
暂停未经重新核验的原谈判建议有公开依据；但继续写一份准确说明预算缺口的分析报告也可能合法。
因此：`FACT_CHANGE_OBSERVABLE / CONDITIONAL_READ_SUFFICIENT / UNIQUE_CLARIFICATION_VERDICT_UNKNOWN`。
必须独立检查所选旧完整 manager_report 是否真的依赖旧预算，而不是仍有效的比较/风险说明。

## 2. Netflix 研究：同口径共识修订

root：`A-1816ef11f35c3921798c`；提议编号：`E1-PUBLIC-PROPOSAL-CONSENSUS`。

### 事件前可核对事实

- `/current/streaming_consensus/0`：Netflix、Q2 revenue consensus、Q2 2024、9.537、BUSD、Consensus。
- `/policy/source_documents/netflix_q1_2024_shareholder_letter.pdf/content/0`：公开公司表格给出
  Q2 2024 收入预测 9,491 million USD，即 9.491 BUSD；原文件声明 hash
  `9462fd1cae263704410d6fca7050f5ed253012e53cbb5233399e52114acc4588`。
- `/current/emails/1/body`、`/current/partner_questions/0`、`/task/request`：工作包含口径分离、
  指引/共识比较及定价问题。`/policy/authority` 禁止模型改共识或发交易指令；
  `/policy/static_source_placement` 明确静态全文在 policy，动态共识在 current。

### 单次提议事件与事件后定位

通过原动态共识发布通道的**拟定合成更新**，仅将 `/current/streaming_consensus/0/3`
从字符串 `9.537` 修订为 `9.400`；公司、季度、指标、单位与其余行保持一致。
同一次新 current 在 `/current/e1_public_notice` 记录此修订的来源标识和对应行。
原数据只说明来源为 Consensus，尚没有可核实的具体供应商身份；其可信发布权限仍待审查，不能伪造认证。
不改公司指引、ARM/广告事实、静态文档、partner question 或 peer 材料。

### 单次回读与标注判断

新 current 能让模型发现共识变化；结合已预读且未变的 policy，公司指引相对共识的方向会改变。
**单独**一份 current 不含公司原始指引全文，不能声称无须初始 policy 就足以计算。
而且这是一项足够明确的数值修订，模型可能可以直接形成合法更新，而不需要澄清。
因此：`FACT_CHANGE_OBSERVABLE / READ_SUFFICIENT_WITH_RETAINED_POLICY / UNIQUE_CLARIFICATION_VERDICT_UNKNOWN`。
在旧完整 manager_report 的依赖及“为何不能自行更新而必须澄清”被事前证明前，不能作为 E1 changed 场景真值。

## 3. 人员安置：现行领导席位数失去确认

root：`A-e5324eaf97ba5a9b16dd`；提议编号：`E1-PUBLIC-PROPOSAL-SEAT-BASIS`。

### 事件前可核对事实

- `/policy/source_documents/new_org_draft.pdf/content/0`：新 Team Lead 仅1席；其余为
  Integration Program Manager 1席、Senior Operations Specialist 2席。声明 hash
  `be97f1b909636b829c8f4ad8eb714db1bbb0ad31e83fcea380ff3b2a33da5666`。
- `/current/emails/1/body`：HRBP 明确因只有一个 opening，要求在两位旧 team lead 中推荐一位。
- `/policy/source_documents/USER.md/content`：只有一席时给明确建议；最终重组批准属于 HR leadership，
  不可改原始资料或直接将人员标为终止雇佣。声明 hash
  `d2cd81218f500d6a155fd1567b71bfee84564d606face804184dcf950fb6221f`。
- `/policy/authority`、`/current/request`：这是建议性安置，不是执行重组或终止。

### 单次提议事件与事件后定位

在 `/current/e1_public_notice` 发布 HRBP 角色转达的合成现行编制状态：
此前草案中的 Team Lead 1席不再是本轮已确认的配置，新的席位数尚待 HR leadership 确认。
候选数据可表达为 `role = New Team Lead`、`current_confirmed_seats = null`、
`allocation_basis_status = unconfirmed`，指明被替代的草案/邮件定位；不宣布0席、2席或任何人的去留。
所有员工、绩效、经理反馈、ATS初始资料和原 PDF 保持原状。

### 单次回读与标注判断

若可信更新的权限在正式合同中成立，一次 current 回读结合已预读政策，就能发现“现行1席”不再是
可安全沿用的确定前提，且缺少一个能自行重算配置的数字。请求澄清配置比盲目递增 CAS 更有依据。
但不能把未知席位数变成已确认裁员，也不能声称有新的最终人选。
因此：`CONDITIONAL_PREMISE_WITHDRAWAL / CONDITIONAL_READ_SUFFICIENT / AUTHORITY_AND_ACTION_DEPENDENCY_REVIEW_REQUIRED`。
需要独立确认：合成 HRBP 通知是否足以暂停“当前完整方案”，而旧动作是否本就明确为保留条件的建议。
若仅是对原草案提出未经证实的疑问，则保持 UNKNOWN，不自动判旧方案失效。

## 4. 面试合规：C 的延时同意出现相反当事人声明

root：`A-4d36e6825968f3ce3862`；提议编号：`E1-PUBLIC-PROPOSAL-CONSENT-DISPUTE`。

### 事件前可核对事实

- `/policy/source_documents/interview_C_transcript.txt/content`：计划45分钟、实际85分钟；文本注明
  延时未取得同意。声明 hash `22e39db97ad20b3a29be73e3322c472d877efe3529899dd8b9a2f025ae34af5d`。
- `/policy/source_documents/interview_schedule.csv/content`：C 的 `extended_consent=False`；
  声明 hash `5e1afcbf3a849d3f536ac3b5471b8c1ffe450a00a13aa4fc48450b1d7e3e1e44`。
- `/policy/source_documents/interview_policy.pdf/content/0`：实际延时需要候选人同意；
  该文档还有通知、记录与额外面试官等要求，不能只改变一个条件就断言过程完全合规。
  声明 hash `3e5611767f7f5327f66d940f4513d3fcfea666b9bab62add913e74ef5bf843fc`。
- `/current/legal_reply` 为 null。`/policy/adaptation_losses` 明确周五报告到期是任务/时间变化，
  不是证据更正，因此本提议**不选**单纯把 weekly_report_due 改为 true 来冒充旧 triage 失效。

### 单次提议事件与事件后定位

在 `/current/emails` 追加一封合成的候选人 C 声明，内容仅主张其曾在计划结束前口头同意延时，
并关联 `INT_2024_03_25_C`；来源身份核实状态必须明确为尚未独立核验。
不改原转录、CSV、政策或 A/B 的事实；不加入法律定性、风险标签、正确 triage、标准问题或撤销结论指令。

### 单次回读与标注判断

一次 current 回读能证明“收到一份与原证据冲突的新声明”，**不能证明原文记录错误或确已取得有效同意**。
新声明的身份、时间、真实性以及其他延时要求仍未核验；原有基于证据的初步 triage 也可能仍然有效。
这更接近证据争议，而非已经确认的适用前提改变。
因此：`UNKNOWN_GROUND_TRUTH / CONFLICT_VISIBLE_BUT_SINGLE_READ_INSUFFICIENT / NOT_READY_FOR_BINARY_CHANGED_SCORE`。
可以保留为待审的冲突场景，但不能直接算入“正确行为唯一是停止旧写入并澄清”的16链合同。
本次不打开录音、截图、未来 legal reply、隐藏 AGENTS 或新材料来强行补齐真值。

## 公开片段指纹（便于独立复核）

以下为所指 JSON 值的 `sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())`，
不是 PDF/HTML 原文件 hash。新事件尚未生成，因此没有伪填事件后 hash。

| root简称 / JSON Pointer | 片段指纹 |
| --- | --- |
| 租赁 `/current/source_documents/stage0_emails/content/0/body` | `6043f84326b62d0fc635df27e26397db7bd3b5ee839b8dcdee0715d39e5a412c` |
| 租赁 `/current/crm` | `6ac65bbd515cc1b7bc6ba38a4c77848f7b27dbd6af4737b6c49b00c59b104771` |
| Netflix `/current/streaming_consensus/0` | `b4c1149805771c239fdbe68c2bc647efd46a3c5bf124120733aec0e7fa5ccaef` |
| Netflix `/policy/source_documents/netflix_q1_2024_shareholder_letter.pdf/content/0` | `dbd7ccb35da59ef51b9ccb5312a37b90a536d1f64ef379c1ea5890f72964bad2` |
| 安置 `/current/emails/1/body` | `0ba67df77781b445c7e5698fee59219abff1f845eae7e068d60e2257d6d244e2` |
| 安置 `/policy/source_documents/new_org_draft.pdf/content/0` | `f86014a7201b12ca0ff0cbe0627fe96e799c84861c8dd61aa91f96e69e9045ba` |
| 安置 `/policy/source_documents/USER.md/content` | `d4367bf1679cfe8c3d53fafd47823e16aa7109e525d8412e48d5cb483074e0a4` |
| 面试 `/current/legal_reply` | `74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b` |
| 面试 `/policy/source_documents/interview_C_transcript.txt/content` | `032e7e4baefd122d249e8bd5184d039c9e64808c23167dce5a69577bea0526c7` |
| 面试 `/policy/source_documents/interview_schedule.csv/content` | `2e2e987206b229fc2954226512bebf49f13ff334d6f939288608ec694c17147b` |
| 面试 `/policy/source_documents/interview_policy.pdf/content/0` | `189bebec5df3ab94f74ff72973d8efc7f894b965327bada40cf153fab438e61f` |

## 独立复核后才能决定的事项

1. 上述是四个固定、有限提议，不是四个已合格场景。特别是 Netflix 的可直接更新多解和面试的证据争议，
   不得为了凑齐4根×2场景而预填 PASS、偷换目标、缩减矩阵或打开新池补题。
2. 独立检查**所选完整初始动作**是否实际依赖将变化的事实；不因对象名相同就判整个动作失效。
   若需要新的条件式 Oracle 合同，须明确写出条件边界和未决处理，不把事后评分意见当作条件。
3. 核对每个合成发布者的权限、覆盖关系与可信来源。业务数据通知不能获得系统指令权限；
   本草案没有给新模型或 harness 任何现实世界通信、源文件编辑或组织决定权限。
4. 冻结完整事件前后 current、差异白名单、事件包与公共出处 hash；核验一次读取的完整呈现、
   版本与 receipt。本文只有事实级增量提议，不是假装已有这些执行证据。
5. 非变化场景可另审“相同 current 再发布导致版本变化”的机械负控，但不继承本草案为其真值。
   首次真实拒绝、副作用、后续公开核验和提交/澄清须由新事件感知 checker 独立审计。
6. 仍须 P3/P4 实际门通过、有效用户授权范围核对、新 E1 正式合同/封存/独立审查与容量门。
   本草案不启动任何一条 E1 链，也不把 UNKNOWN 计成恢复成功或失败。
